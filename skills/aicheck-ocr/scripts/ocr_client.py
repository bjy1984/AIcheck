"""Local asynchronous adapter to the project's OCR runtime; stdlib only."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

TEXT={'type':'string','minLength':1,'maxLength':4096}
def action(description,props,required):
    return {'description':description,'inputSchema':{'type':'object','properties':props,'required':list(required),'additionalProperties':False}}
ACTIONS={
'connection':action('检查项目OCR运行配置、可用profile和数据处理边界。配置就绪不等于引擎实测通过。',{},()),
'start':action('识别用户指定的本地PDF/PNG/JPEG，异步返回taskId。engine=mineru上传文件至MinerU，runtime官方/混合模式可能发送页面至千问；本地保存结果，不创建工程。',{'filePath':TEXT,'profileId':TEXT,'engine':{'type':'string','enum':['runtime','mineru']}},('filePath',)),
'result':action('查询本机OCR任务；返回覆盖情况和本地结果路径，可按原件物理页读取正文及结构化内容。',{'taskId':TEXT,'pageNo':{'type':'integer','minimum':1}},('taskId',)),
}
class ClientError(Exception):
    def __init__(self,code,message):self.code=code;self.message=message;super().__init__(message)
def fail(code,message):raise ClientError(code,message)


def config():
    root=Path(os.environ.get('AICHECK_OCR_PROJECT_ROOT','')).expanduser().resolve()
    if not os.environ.get('AICHECK_OCR_PROJECT_ROOT') or not (root/'backend/scripts/ocr_mcp_worker.py').is_file():fail('notConfigured','设置 AICHECK_OCR_PROJECT_ROOT 为本项目目录。')
    python=Path(os.environ.get('AICHECK_OCR_PYTHON',str(root/'backend/.venv/bin/python'))).expanduser()
    if not python.is_file():fail('runtimeUnavailable','找不到项目 Python，请配置 AICHECK_OCR_PYTHON。')
    try:
        values=json.loads(os.environ.get('AICHECK_OCR_ALLOWED_ROOTS','[]'))
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or not Path(v).expanduser().is_absolute() for v in values):raise ValueError()
        roots=[Path(v).expanduser().resolve() for v in values]
    except (ValueError,TypeError):fail('notConfigured','AICHECK_OCR_ALLOWED_ROOTS 需为允许读取的绝对目录JSON数组。')
    out=Path(os.environ.get('AICHECK_OCR_OUTPUT_DIR',str(Path.home()/'.aicheck/ocr-results'))).expanduser().resolve()
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    return root,python,roots,out


def runtime_info(root,python):
    try:
        p=subprocess.run([str(python),str(root/'backend/scripts/ocr_mcp_worker.py'),'--describe'],capture_output=True,text=True,timeout=20,check=True)
        return json.loads(p.stdout)
    except (OSError,subprocess.SubprocessError,ValueError):fail('runtimeUnavailable','项目OCR依赖或运行配置不可用；请用项目Python安装后端依赖。')


def invoke(name,args):
    try:
        if name not in ACTIONS:fail('invalidArguments','未知操作')
        props=ACTIONS[name]['inputSchema']
        if not isinstance(args,dict) or set(args)-props['properties'].keys() or not set(props['required'])<=args.keys():fail('invalidArguments','参数不符合约定')
        for key,value in args.items():
            if key=='pageNo':
                if type(value) is not int or value<1:fail('invalidArguments','pageNo 必须是正整数')
            elif not isinstance(value,str) or not value.strip() or len(value)>4096:fail('invalidArguments','参数必须是非空字符串')
        if 'engine' in args and args['engine'] not in {'runtime','mineru'}:fail('invalidArguments','未知engine')
        root,python,roots,out=config()
        if name=='connection':
            return {'ok':True,'data':{**runtime_info(root,python),'outputDirectory':str(out),'allowedRoots':[str(r) for r in roots],
                'projectRecordsCreated':False,'retention':'结果与任务元数据保存在本地；本地引擎可能有缓存，官方服务留存遵循其政策。',
                'supportedFormats':['.pdf','.png','.jpg','.jpeg'],'tools':list(ACTIONS)}}
        if name=='start':
            path=Path(args['filePath']).expanduser()
            if not path.is_absolute():fail('invalidArguments','filePath 必须是绝对路径')
            path=path.resolve()
            if not any(path.is_relative_to(r) for r in roots):fail('pathNotAllowed','文件不在配置的允许目录中')
            if not path.is_file() or path.suffix.lower() not in {'.pdf','.png','.jpg','.jpeg'}:fail('unsupportedFile','仅支持已有 PDF、PNG、JPEG 文件；DOC/DOCX 请先导出 PDF')
            if path.stat().st_size>100*1024*1024:fail('fileTooLarge','文件不得超过100MB')
            info=runtime_info(root,python)
            if args.get('engine')=='mineru' and not info['mineruCredentialsConfigured']:fail('notConfigured','尚未配置 AICHECK_MINERU_API_KEY')
            if args.get('profileId') and args['profileId'] not in info['profiles']:fail('invalidArguments','未知profileId，请从connection返回值选择')
            active=0
            for status in out.glob('*/status.json'):
                try:
                    if json.loads(status.read_text()).get('status') in {'queued','running'}:
                        pid=int((status.parent/'pid').read_text());os.kill(pid,0);active+=1
                except (OSError,ValueError):pass
            if active>=2:fail('busy','已有两个识别任务在运行，请稍后提交')
            task=uuid.uuid4().hex;folder=out/task;folder.mkdir(mode=0o700)
            request={**args,'filePath':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'createdAt':time.time()}
            (folder/'request.json').write_text(json.dumps(request,ensure_ascii=False))
            (folder/'status.json').write_text('{"status":"queued"}')
            try:
                proc=subprocess.Popen([str(python),str(root/'backend/scripts/ocr_mcp_worker.py'),'--task',str(folder)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            except OSError:fail('runtimeUnavailable','无法启动OCR任务')
            (folder/'pid').write_text(str(proc.pid))
            return {'ok':True,'data':{'taskId':task,'status':'queued','sha256':request['sha256'],'externalProcessingPossible':args.get('engine')=='mineru' or info['externalProcessingPossible']}}
        task=args['taskId']
        if not re.fullmatch(r'[a-f0-9]{32}',task):fail('invalidArguments','taskId 格式无效')
        folder=out/task
        if not (folder/'status.json').is_file():fail('taskNotFound','本地任务不存在')
        status=json.loads((folder/'status.json').read_text())
        if status['status'] in {'running','queued'}:
            try:os.kill(int((folder/'pid').read_text()),0)
            except (OSError,ValueError):status={'status':'failed','error':{'code':'workerInterrupted','message':'识别进程已结束且未返回结果，请重新提交。'}}
        data={'taskId':task,**status}
        if (folder/'result.json').is_file():
            data['files']={'resultJson':str(folder/'result.json'),'textMarkdown':str(folder/'full.md')}
            result=json.loads((folder/'result.json').read_text())
            if (folder/'mineru-original.zip').is_file():data['files']['mineruOriginalZip']=str(folder/'mineru-original.zip')
            data['quality']=result.get('quality');data['source']=result['source'];data['metadata']=result.get('metadata')
            if 'pageNo' in args:
                page=args['pageNo']
                if page>result['source']['totalPages']:fail('pageOutOfRange','页码超出原件范围')
                selected={k:[r for r in result.get(k,[]) if r.get('pageNo')==page] for k in ['pages','fragments','fields','tables','seals','signatures','layoutBlocks']}
                encoded=json.dumps(selected,ensure_ascii=False)
                if len(encoded)>120000:data['page']={'pageNo':page,'inlineContentOmitted':True,'reason':'该页结果过大，请读取本地resultJson，未截断原始结果'}
                else:data['page']={'pageNo':page,**selected}
        return {'ok':True,'data':data}
    except ClientError as exc:return {'ok':False,'error':{'code':exc.code,'message':exc.message}}
    except (OSError,ValueError,KeyError,TypeError):return {'ok':False,'error':{'code':'localRuntimeError','message':'本地任务文件或配置不可用'}}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=ACTIONS);p.add_argument('--json',default='{}');a=p.parse_args()
    print(json.dumps(invoke(a.action,json.loads(a.json)),ensure_ascii=False))
