"""Stateless Streamable HTTP MCP (2025-06-18) for the existing data APIs."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
import secrets
from urllib.parse import quote
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from libs.data_service_mcp_contract import ACTIONS, validate

router = APIRouter()
PREFIX = '/mcp/data-services'
VERSIONS = ('2025-06-18', '2025-03-26')
MAX_FILE = 100 * 1024 * 1024
INSTRUCTIONS = '使用远程数据工具。OCR submit 返回临时上传地址，宿主使用文件工具 PUT 用户指定的 PDF/图片原件，上传响应提供 jobId，再调用 status/result。不得读取服务器路径、编造上传成功或将工具成功视为工程符合。标准需核对编号版本；证件未检出不等于伪证。'


def rpc_error(i, code, message, status=200):
    return JSONResponse({'jsonrpc':'2.0','id':i,'error':{'code':code,'message':message}},status_code=status)


def test_mode(request):
    from libs.security.data_service_test_mode import allows
    return allows(request.method,request.url.path)


async def api(request, method, path, *, query=None, payload=None, body=None, headers=None):
    # Fixed loopback destination; no caller-supplied URL or redirects.
    hdr = dict(headers or {})
    if not test_mode(request) and request.headers.get('authorization'):
        hdr['Authorization'] = request.headers['authorization']
    async with httpx.AsyncClient(trust_env=False, timeout=300, follow_redirects=False) as c:
        response = await c.request(method,'http://127.0.0.1:8000/api/'+path,
                                   params=query,json=payload,content=body,headers=hdr)
    try:
        data = response.json()
    except ValueError:
        return {'ok':False,'error':{'code':'upstreamUnavailable','message':'后台未返回 JSON。'}}
    if response.is_error or data.get('code') not in (0,200):
        return {'ok':False,'error':{'code':str(data.get('code',response.status_code)),
                                  'message':data.get('message','后台调用失败。')}}
    return {'ok':True,'data':data.get('data')}


def secret():
    path=Path('output/mcp/upload-signing.key');path.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
    value=path.read_bytes()
    if len(value)!=32:raise ValueError('Signing key unavailable')
    return value


def owner(request):
    if test_mode(request):return 'internal-data-services-test'
    claims=getattr(request.state,'auth',None) or {}
    return str(claims.get('tid',''))+':'+str(claims.get('sub',''))


def ticket(request,args):
    name=args['fileName']
    if '/' in name or '\\' in name or Path(name).suffix.lower() not in {'.pdf','.png','.jpg','.jpeg'}:
        raise ValueError('仅支持无目录的 PDF/PNG/JPEG 文件名。')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',args['requestId']):raise ValueError('requestId 格式无效。')
    if 'profileId' in args:
        from libs.ocr.profiles import OCR_PROFILES, PROFILE_ALIASES
        if args['profileId'] not in OCR_PROFILES and args['profileId'] not in PROFILE_ALIASES:
            raise ValueError('profileId 无效，请从 connection.ocr.profiles 选择。')
    payload={**args,'expires':int(time.time())+900,'owner':owner(request)}
    raw=base64.urlsafe_b64encode(json.dumps(payload,ensure_ascii=False).encode()).decode().rstrip('=')
    token=raw+'.'+hmac.new(secret(),raw.encode(),hashlib.sha256).hexdigest()
    base=os.getenv('AICHECK_MCP_PUBLIC_BASE_URL','http://39.108.65.148:8081').rstrip('/')
    return {'ok':True,'data':{'status':'awaiting_upload','uploadUrl':base+'/api'+PREFIX+'/uploads/'+token,
            'method':'PUT','contentType':'application/octet-stream','expiresInSeconds':900,'maxBytes':MAX_FILE,
            'instructions':'以宿主文件工具上传用户指定文件原始字节；同一 requestId 只重试相同文件。上传响应 data.jobId 用于后续查询。'}}


def decode_ticket(request, token):
    raw,sig=token.rsplit('.',1)
    if not hmac.compare_digest(hmac.new(secret(),raw.encode(),hashlib.sha256).hexdigest(),sig):raise ValueError()
    d=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
    if d['expires']<time.time() or d['owner']!=owner(request):raise ValueError()
    return d


async def invoke(request,name,args):
    if name=='ocr_submit':return ticket(request,args)
    if name=='connection':
        from libs.ocr.profiles import OCR_PROFILES
        result=await api(request,'GET','inspection-services/capabilities')
        if result.get('ok'):
            result['data']={**(result.get('data') or {}),'transport':'streamable-http',
                'ocrProvided':True,'documentUploadAccepted':True,
                'retention':{'serverStoresInput':True,'serverStoresResult':True,
                             'temporaryFiles':'upload_ticket_expires_after_900_seconds; stored_objects_do_not_expire_with_ticket',
                             'externalProvider':'MinerU / Alibaba Cloud Qwen','externalProviders':['MinerU','Alibaba Cloud Qwen'],'automaticDeletionGuaranteed':False},
                'ocr':{'uploadMode':'temporary_put_url','authenticationRequired':not test_mode(request),'executionVerified':False,
                       'fallbackProvider':'qwen','fallbackTrigger':'mineru_pending_timeout','profiles':sorted(OCR_PROFILES),'resultKind':'processed_ocr','pageScopedContent':True,
                       'documentFieldsIncluded':True,'sealRecognitionIsNotRegistryVerification':True},
                'overallReviewProvided':False}
        return result
    if name=='standards':return await api(request,'GET','inspection-services/standards',query={'keyword':args['query'],'page':args.get('page',1),'pageSize':args.get('pageSize',20)})
    if name=='standard_content':
        if not re.fullmatch(r'KF-KB-[A-Za-z0-9_-]+',args['fileId']):raise ValueError('fileId 必须来自检索结果。')
        return await api(request,'GET','inspection-services/standards/'+quote(args['fileId'],safe='')+'/canonical',query={k:v for k,v in args.items() if k in ('pageNo','section')})
    if name in ('standard_status','certificate_validity','certificate_registry'):
        if name=='certificate_registry':args={'allowExternalQuery':True,**args}
        return await api(request,'POST','inspection-services/'+name.replace('_','-'),payload=args)
    job=args['jobId']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',job):raise ValueError('任务编号无效。')
    return await api(request,'GET','internal/ocr/mineru/tasks/'+job+('/result' if name=='ocr_result' else ''),
                     query={'pageNo':args['pageNo']} if 'pageNo' in args else None)


async def limited_body(request, maximum):
    parts=[];size=0
    async for part in request.stream():
        size+=len(part)
        if size>maximum:raise ValueError('请求超过大小限制。')
        parts.append(part)
    return b''.join(parts)


def origin_allowed(request):
    origin=request.headers.get('origin')
    allowed=os.getenv('AICHECK_MCP_ALLOWED_ORIGINS','').split(',')
    return not origin or origin in allowed


@router.api_route(PREFIX,methods=['POST','GET','DELETE'])
async def mcp(request:Request):
    if not origin_allowed(request):return Response(status_code=403)
    if request.method!='POST':return Response(status_code=405,headers={'Allow':'POST'})
    if request.headers.get('mcp-protocol-version','2025-03-26') not in VERSIONS:return rpc_error(None,-32600,'Unsupported protocol version',400)
    if 'application/json' not in request.headers.get('content-type',''):return Response(status_code=415)
    try:msg=json.loads(await limited_body(request,1024*1024))
    except (ValueError,UnicodeError):return rpc_error(None,-32700,'Invalid JSON or body too large',400)
    if not isinstance(msg,dict) or msg.get('jsonrpc')!='2.0' or not isinstance(msg.get('method'),str):return rpc_error(None,-32600,'Invalid Request',400)
    if 'id' not in msg:return Response(status_code=202)
    i=msg['id'];method=msg['method'];params=msg.get('params',{})
    if not isinstance(params,dict):return rpc_error(i,-32602,'Invalid params')
    try:
        if method=='initialize':
            result={'protocolVersion':params.get('protocolVersion') if params.get('protocolVersion') in VERSIONS else VERSIONS[0],
                    'capabilities':{'tools':{},'resources':{}},'serverInfo':{'name':'aicheck-data-services','version':'2.1.0'},'instructions':INSTRUCTIONS}
        elif method=='ping':result={}
        elif method=='tools/list':result={'tools':[{'name':'aicheck_'+n,'description':s['description'],'inputSchema':s['inputSchema'],
                    'annotations':{'readOnlyHint':s.get('readOnly',False),'destructiveHint':False,'openWorldHint':True}} for n,s in ACTIONS.items()]}
        elif method=='resources/list':result={'resources':[{'uri':'aicheck-data://skill','name':'远程数据服务使用说明','mimeType':'text/markdown'}]}
        elif method=='resources/read':
            if params.get('uri')!='aicheck-data://skill':raise ValueError('Unknown resource')
            result={'contents':[{'uri':params['uri'],'mimeType':'text/markdown','text':INSTRUCTIONS}]}
        elif method=='tools/call':
            n=params.get('name','')
            if not isinstance(n,str) or not n.startswith('aicheck_') or n[8:] not in ACTIONS:raise ValueError('Unknown tool')
            n=n[8:];args=params.get('arguments',{});validate(args,ACTIONS[n]['inputSchema'])
            try:data=await invoke(request,n,args)
            except httpx.HTTPError:data={'ok':False,'error':{'code':'upstreamUnavailable','message':'后台调用超时或连接失败；不要重复创建任务。'}}
            result={'isError':not data.get('ok'),'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}]}
        else:return rpc_error(i,-32601,'Method not found')
    except ValueError as exc:return rpc_error(i,-32602,str(exc))
    except (OSError,KeyError,TypeError):return rpc_error(i,-32603,'Internal configuration error')
    return JSONResponse({'jsonrpc':'2.0','id':i,'result':result})


@router.put(PREFIX+'/uploads/{token}')
async def upload(request:Request,token:str):
    if not origin_allowed(request):return Response(status_code=403)
    try:d=decode_ticket(request,token)
    except (ValueError,KeyError,TypeError,OSError):return JSONResponse({'ok':False,'error':{'code':'invalidUploadTicket'}},status_code=403)
    try:
        body=await limited_body(request,MAX_FILE)
        if not body:raise ValueError('文件不能为空。')
    except ValueError as exc:return JSONResponse({'ok':False,'error':{'code':'invalidFile','message':str(exc)}},status_code=400)
    metadata={'fileName':d['fileName'],'options':{'language':d.get('language','ch')}}
    if d.get('profileId'):metadata['profileId']=d['profileId']
    headers={'Content-Type':'application/octet-stream','Idempotency-Key':d['requestId'],
             'X-AICheck-Ocr-Metadata-B64':base64.b64encode(json.dumps(metadata).encode()).decode()}
    try:result=await api(request,'POST','internal/ocr/mineru/tasks/upload',body=body,headers=headers)
    except httpx.HTTPError:result={'ok':False,'error':{'code':'upstreamUnavailable','message':'上传结果未知，请使用原 URL 和原文件重试。'}}
    return JSONResponse(result,status_code=200 if result.get('ok') else 502)
