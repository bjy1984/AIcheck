"""Project runtime for the local OCR MCP. Does not write engineering repository records."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))


def configure():
    from dotenv import load_dotenv
    load_dotenv(BACKEND/'.env',override=False)
    # Never let placeholder output masquerade as recognized evidence.
    os.environ['AICHECK_OCR_ALLOW_PLACEHOLDER']='false'


def describe():
    from libs.ocr_runtime import ocr_runtime_config
    from libs.ocr.profiles import OCR_PROFILES
    runtime=ocr_runtime_config(validate=False)
    return {'mode':runtime['mode'],'officialCredentialsConfigured':bool(runtime['official'].get('apiKey')),
            'engines':['runtime','mineru'],'mineruCredentialsConfigured':bool(os.environ.get('AICHECK_MINERU_API_KEY')),
            'profiles':sorted(OCR_PROFILES),'maxPages':runtime['render']['maxDocumentPages'],
            'maxCostCnyPerDocument':runtime['render']['maxCostCnyPerDocument'],
            'externalProcessingPossible':runtime['mode'] in {'official','hybrid_auto'},
            'readiness':'configuration_only_not_engine_probe'}


def write_json(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temp,path)


def run(folder):
    req=json.loads((folder/'request.json').read_text())
    write_json(folder/'status.json',{'status':'running'})
    try:
        from libs.ocr_runtime import ocr_runtime_config
        from libs.ocr.profiles import profile_for, OCR_PROFILES
        source=Path(req['filePath']);profile_id=req.get('profileId')
        if profile_id and profile_id not in OCR_PROFILES:raise ValueError('unknown profile')
        runtime=ocr_runtime_config(validate=False)
        # Freeze the exact input locally; discard working pages after the run.
        with tempfile.TemporaryDirectory(prefix='ocr-mcp-',dir=folder) as temp:
            work=Path(temp);snapshot=work/source.name
            snapshot.write_bytes(source.read_bytes())
            if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=req['sha256']:
                write_json(folder/'status.json',{'status':'failed','error':{'code':'inputChanged','message':'资料内容已变化，请重新提交。'}});return
            if source.suffix.lower()=='.pdf':
                import fitz
                with fitz.open(snapshot) as doc:total=doc.page_count
            else:
                from PIL import Image
                with Image.open(snapshot) as img:
                    total=getattr(img,'n_frames',1)
                    if total!=1:raise ValueError('multi-frame image unsupported')
            if total>runtime['render']['maxDocumentPages']:raise ValueError('page limit')
            if req.get('engine') == 'mineru':
                from libs.integrations.mineru_client import MinerUClient
                from libs.mineru_ocr import normalize_mineru_zip
                client=MinerUClient()
                try:
                    submission=client.submit_file(snapshot,data_id=folder.name,options={})
                    provider_result=client.wait_for_result(submission)
                    archive=client.download_result(provider_result['full_zip_url'])
                    bundle=normalize_mineru_zip(archive,storage_key=source.name,file_name=source.name,
                        profile_id=profile_id,document_type=None,provider_task_id=str(submission.get('providerTaskId','')),
                        preserve_source_tables=True)
                    result=bundle.result
                    (folder/'mineru-original.zip').write_bytes(archive)
                finally:
                    client.client.close()
            elif runtime['mode'] in {'official','hybrid_auto'}:
                from libs.official_ocr_pipeline import official_ocr_extract
                result=official_ocr_extract(snapshot,profile=profile_for(profile_id,None),runtime=runtime,work_directory=work)
            else:
                from apps.ocr_service.service import ocr_service
                result=ocr_service.parse_document(str(snapshot),file_name=source.name,profile_id=profile_id)
        # Preserve engine output as evidence, but keep credentials/request payloads out of artifacts.
        public={k:result.get(k) for k in ('status','outcomeStatus','parserVersion','profileId','documentType','pages','fragments','fields','tables','seals','signatures','layoutBlocks','quality') if k in result}
        public['engine']=req.get('engine','runtime')
        public['source']={'fileName':source.name,'sha256':req['sha256'],'totalPages':total}
        public['metadata']={k:v for k,v in (result.get('metadata') or {}).items() if k in {'providerMode','provider','model','selectedPageNos','recognitionPageCoverage','outputTruncated','budgetStopped','costCny','modelCallCount'}}
        fragments=public.get('fragments') or []
        seen={r.get('pageNo') for r in fragments if str(r.get('text') or '').strip()}
        seen|={r.get('pageNo') for r in public.get('tables') or [] if r.get('rows') or r.get('normalizedRows') or r.get('html') or r.get('text')}
        unconfirmed=[n for n in range(1,total+1) if n not in seen]
        public['coverage']={'totalPages':total,'pagesWithRecognizedContent':sorted(n for n in seen if type(n) is int),
            'unconfirmedPages':unconfirmed,'requiresOriginalReview':True,
            'note':'无识别内容的页面可能为空白或识别失败，不能当作未提供资料；有文字不证明表格及关键字段正确。'}
        write_json(folder/'result.json',public)
        lines=['# OCR 正文（识别结果，需核对原件）','',f'源文件：{source.name}',f'SHA-256：{req["sha256"]}','']
        for page in range(1,total+1):
            lines += [f'## 原件第 {page} 页','']+[str(r.get('text','')) for r in fragments if r.get('pageNo')==page]+['']
            for table in public.get('tables') or []:
                if table.get('pageNo')==page:
                    lines += ['### 识别表格', str(table.get('html') or table.get('text') or json.dumps(table.get('rows') or table.get('normalizedRows') or table,ensure_ascii=False)), '']
            if page in unconfirmed:lines.append('本页未确认识别内容，请核对原页。')
        (folder/'full.md').write_text('\n'.join(lines)+'\n')
        failed=result.get('status') in {'failed','error'} or not (fragments or public.get('tables') or public.get('fields'))
        state='failed' if failed else 'partial' if unconfirmed or result.get('outcomeStatus')=='partial' or (result.get('quality') or {}).get('status') not in {None,'usable','passed','auto_usable'} else 'completed'
        write_json(folder/'status.json',{'status':state,'coverage':public['coverage'],'error':{'code':'ocrFailed','message':'OCR 未返回可用正文，请检查引擎和配置。'} if failed else None})
    except Exception as exc:
        code=str(getattr(exc,'code','') or getattr(exc,'reason','') or 'ocrRuntimeError')
        # Exceptions from provider calls may contain image URLs or credentials.
        write_json(folder/'status.json',{'status':'failed','error':{'code':code if code.isidentifier() else 'ocrRuntimeError','message':'识别未完成；请检查运行配置、文件格式、页数限制及引擎就绪情况。','type':type(exc).__name__}})


def main():
    p=argparse.ArgumentParser();p.add_argument('--describe',action='store_true');p.add_argument('--task',type=Path);a=p.parse_args()
    configure()
    if a.describe:print(json.dumps(describe(),ensure_ascii=False))
    elif a.task:run(a.task.resolve())
    else:p.error('missing task')

if __name__=='__main__':main()
