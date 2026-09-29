"""Portable bridge to server data services; no project or node review tools."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from service_transport import ACTIONS as EXISTING, Client, ClientError, _validate, invoke as existing_invoke

NAMES=('standards','standard_content','standard_status','certificate_registry','certificate_validity')
ACTIONS={name:EXISTING[name] for name in NAMES}
def spec(description,properties,required=(),read_only=True):
    return dict(description=description,readOnly=read_only,inputSchema=dict(type='object',properties=properties,required=list(required),additionalProperties=False))
TEXT={'type':'string','minLength':1,'maxLength':4096}
ACTIONS.update({
 'connection':spec('检查基础服务；OCR使用登录令牌，专项匹配由宿主按标准逐项核验，不提供节点整体审查。',{}),
 'ocr_submit':spec('将用户指定本地PDF/图片上传到服务器MinerU。须事先说明外发及服务留存；不关联工程。相同requestId仅用于原样重试。',{'filePath':TEXT,'requestId':{'type':'string','minLength':16,'maxLength':80},'language':{'type':'string','enum':['ch','en']}},('filePath','requestId'),False),
 'ocr_status':spec('查询服务器MinerU任务状态和产物清单；未完成不能报告识别成功。',{'jobId':TEXT},('jobId',)),
 'ocr_result':spec('读取本人的服务器OCR结构化结果，可按PDF物理页选择；不生成业务结论。',{'jobId':TEXT,'pageNo':{'type':'integer','minimum':1}},('jobId',)),
})
def invoke(name,args):
    try:
        if name not in ACTIONS:raise ClientError('unknownAction','仅提供数据处理和专项核验，不提供节点规则、请求登记或审查任务。')
        _validate(args,ACTIONS[name]['inputSchema'])
        if name in NAMES:return existing_invoke(name,args)
        if name=='connection':
            c=Client(require_token=False)
            data=c.api('GET','inspection-services/capabilities')
            return {'ok':True,'data':{'standardContent':data.get('standardContent'),'certificateRegistry':data.get('certificateRegistry'),'ocr':{'authenticationRequired':os.getenv('AICHECK_DATA_TEST_NOAUTH') != '1','credentialsConfigured':bool(os.getenv('AICHECK_TOKEN') or os.getenv('AICHECK_TOKEN_FILE')),'executionVerified':False},'matchingExecutor':'host_ai_with_source_evidence','overallReviewProvided':False}}
        c=Client(require_token=os.getenv('AICHECK_DATA_TEST_NOAUTH') != '1')
        if name=='ocr_submit':
            roots=json.loads(os.getenv('AICHECK_DATA_ALLOWED_ROOTS','[]'))
            if not isinstance(roots,list) or not roots or any(not isinstance(x,str) or not Path(x).expanduser().is_absolute() for x in roots):raise ClientError('notConfigured','配置允许读取的绝对目录JSON数组 AICHECK_DATA_ALLOWED_ROOTS。')
            p=Path(args['filePath']).expanduser()
            if not p.is_absolute():raise ClientError('invalidArguments','必须使用本地绝对路径。')
            p=p.resolve()
            if not any(p.is_relative_to(Path(x).expanduser().resolve()) for x in roots):raise ClientError('pathNotAllowed','文件不在允许目录。')
            if p.suffix.lower() not in {'.pdf','.png','.jpg','.jpeg'} or not p.is_file():raise ClientError('unsupportedFile','仅支持PDF/PNG/JPEG。')
            if not 0<p.stat().st_size<=100*1024*1024:raise ClientError('fileTooLarge','文件必须为1字节至100MB。')
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',args['requestId']):raise ClientError('invalidArguments','requestId使用16–80位字母数字、下划线或连字符。')
            meta={'fileName':p.name,'options':{'language':args.get('language','ch')}}
            body=p.read_bytes()
            response=c.open('POST',c.url('internal/ocr/mineru/tasks/upload'),body=body,headers={'Content-Type':'application/octet-stream','Idempotency-Key':args['requestId'],'X-AICheck-Ocr-Metadata-B64':base64.b64encode(json.dumps(meta,ensure_ascii=False).encode()).decode()})
            data=c.decode(response);data['sourceSha256']=hashlib.sha256(body).hexdigest()
        else:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',args['jobId']):raise ClientError('invalidArguments','任务编号格式无效。')
            path='internal/ocr/mineru/tasks/'+args['jobId']
            if name=='ocr_result':path+='/result'
            data=c.api('GET',path,query={'pageNo':args['pageNo']} if 'pageNo' in args else None)
        return {'ok':True,'data':c.safe(data)}
    except ClientError as exc:return {'ok':False,'error':{'code':exc.code,'message':exc.message}}
    except (OSError,ValueError,TypeError,KeyError):return {'ok':False,'error':{'code':'invalidConfigurationOrResponse','message':'本地配置、文件或服务器响应无效；未自动重试。'}}
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=ACTIONS);p.add_argument('--json',default='{}');a=p.parse_args()
    print(json.dumps(invoke(a.action,json.loads(a.json)),ensure_ascii=False))
