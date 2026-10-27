from datetime import UTC, datetime, timedelta
from copy import deepcopy
import json
from types import SimpleNamespace
import pytest
from libs.ocr_failover import observe_provider, select_qwen
from libs.db.repository import InMemoryRepository
from apps.worker import tasks
from apps.api.mineru_ocr_routes import public_mineru_job


def test_pending_deadline_survives_restart_and_resets_on_running(monkeypatch):
    monkeypatch.setenv('AICHECK_MINERU_PENDING_TIMEOUT_SECONDS', '60')
    now = datetime.now(UTC);job = {}
    assert not observe_provider(job, 'pending', now=now)
    restarted = json.loads(json.dumps(job))
    assert not observe_provider(restarted, 'pending', now=now+timedelta(seconds=59))
    assert observe_provider(restarted, 'pending', now=now+timedelta(seconds=60))
    assert not observe_provider(restarted, 'running', now=now+timedelta(seconds=61))
    assert 'pendingSince' not in restarted
    assert not observe_provider(restarted, 'pending', now=now+timedelta(seconds=62))


def test_pending_switch_prevents_download_and_restart_resubmission(monkeypatch):
    monkeypatch.setenv('AICHECK_MINERU_PENDING_TIMEOUT_SECONDS', '0')
    job={'id':'FALLBACK-1','provider':'mineru','providerTaskId':'batch-1','providerTaskType':'batch','providerUploadState':'uploaded'}
    class Client:
        def wait_for_result(self, submission, *, progress_callback):
            progress_callback({'state':'pending'})
            raise AssertionError('Must exit MinerU polling')
        def download_result(self, *_):raise AssertionError('Must not download stale MinerU result')
    monkeypatch.setattr(tasks,'MinerUClient',Client)
    monkeypatch.setattr(tasks,'_persist_mineru_job',lambda job:None)
    calls=[]
    monkeypatch.setattr(tasks,'run_qwen_fallback_job',lambda job:calls.append(job['id']) or {'status':'success'})
    assert tasks.run_mineru_job(job)['status']=='success'
    assert job['fallback']['remoteCancellation']=='unsupported'
    assert job['fallback']['localWaitStopped']
    switched=deepcopy(job['fallback'])
    monkeypatch.setattr(tasks,'MinerUClient',lambda:pytest.fail('Restart must not contact MinerU'))
    tasks.run_mineru_job(job)
    select_qwen(job)
    assert job['fallback']==switched
    assert calls==['FALLBACK-1','FALLBACK-1']


def test_qwen_public_status_keeps_job_id_and_reports_real_provider():
    job={'id':'job-1','provider':'mineru','activeProvider':'qwen','activeModel':'test-ocr','status':'running','providerProgress':{'state':'pending'},'pageProgress':{'completed':1,'total':2}}
    public=public_mineru_job(job)
    assert public['jobId']=='job-1'
    assert public['provider']=='qwen'
    assert public['model']=='test-ocr'
    assert '千问' in public['statusMessage']
    assert public['pageProgress']['total']==2


def test_qwen_standalone_result_preserves_quality_and_artifacts(monkeypatch,tmp_path):
    source=tmp_path/'test.pdf';source.write_bytes(b'%PDF')
    job={'id':'standalone','provider':'mineru','activeProvider':'qwen','storageKey':str(source),'fileName':'test.pdf','fallback':{'reason':'MINERU_PENDING_TIMEOUT'}}
    runtime={'official':{'primaryModel':'actual-ocr'},'render':{}}
    monkeypatch.setattr(tasks,'ocr_runtime_config',lambda **kw:deepcopy(runtime))
    monkeypatch.setattr(tasks,'mineru_source_path',lambda job:(source,None))
    monkeypatch.setattr(tasks,'_persist_mineru_job',lambda job:None)
    monkeypatch.setattr(tasks,'_load_official_page_checkpoints',lambda run:{1:[{'cached':True}]})
    monkeypatch.setattr(tasks,'store_ocr_pipeline_artifact',lambda *a:('minio://test/checkpoint','hash'))
    original={'status':'success','outcomeStatus':'partial','parserVersion':'aliyun-qwen-ocr@2',
              'pages':[{'pageNo':1,'width':100,'height':100}],
              'fragments':[{'pageNo':1,'text':'Q345R','bbox':[0,0,30,10],'sourceEngine':'aliyun_qwen_ocr_advanced'}],
              'fields':[],'tables':[], 'seals':[], 'engineRuns':[{'engine':'aliyun_qwen_ocr','status':'success'}],
              'quality':{'blockingReasons':[{'code':'OCR_OUTPUT_TRUNCATED'}],'reasons':['OCR_OUTPUT_TRUNCATED']},
              'metadata':{'provider':'aliyun_model_studio','model':'actual-ocr','formalReadinessProfileAllowed':False},
              'groundingValidation':{'outputTruncated':True}}
    def extract(path,**kw):
        assert kw['page_call_cache']=={1:[{'cached':True}]}
        kw['page_completed'](1,1,1,[{'cached':True}])
        return deepcopy(original)
    monkeypatch.setattr(tasks,'official_ocr_extract',extract)
    bundles=[]
    monkeypatch.setattr(tasks,'_store_mineru_artifacts',lambda job,bundle:bundles.append(bundle) or {})
    result=tasks.run_qwen_fallback_job(job)
    assert result['metadata']['provider']=='aliyun_model_studio'
    assert result['engineVersion']=='aliyun-qwen-ocr'
    assert result['formalEvidenceReady'] is False
    assert {'code':'OCR_OUTPUT_TRUNCATED'} in result['quality']['blockingReasons']
    assert result['outcomeStatus']=='partial'
    assert job['pageProgress']['completed']==1
    archived=json.loads(bundles[0].artifacts['normalized_json'].data)
    assert archived['quality']==result['quality']
    assert archived['fields']==result['fields']
    assert 'original_zip' not in bundles[0].artifacts


def test_completed_fallback_duplicate_never_calls_provider(monkeypatch):
    repo=InMemoryRepository();job=repo.create_ocr_job_record(document_id='',version_id='',storage_key='x',file_name='test.pdf',provider='mineru')
    job.update(status='success',activeProvider='qwen',parseResultId='qwen-result')
    monkeypatch.setattr(tasks,'repo',repo)
    monkeypatch.setattr(tasks,'refresh_worker_state',lambda *a:None)
    monkeypatch.setattr(tasks,'run_mineru_job',lambda *a:pytest.fail('Completed job must not run again'))
    result=tasks._execute_mineru_ocr_extract(SimpleNamespace(),job['id'])
    assert result['alreadyCompleted']
    assert result['parseResultId']=='qwen-result'


def test_concurrent_execution_does_not_start_second_provider(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    repo=InMemoryRepository();job=repo.create_ocr_job_record(document_id='',version_id='',storage_key='x',file_name='test.pdf',provider='mineru')
    monkeypatch.setattr(tasks,'repo',repo);monkeypatch.setattr(tasks,'refresh_worker_state',lambda *a:None)
    monkeypatch.setattr(tasks,'_persist_mineru_job',lambda *a:None)
    monkeypatch.setattr(tasks,'flush_state_records',lambda *a:None)
    entered=threading.Event();release=threading.Event();calls=[]
    def run(job):
        calls.append(job['id']);entered.set();assert release.wait(5)
        return {'status':'success','parseResultId':'only-result'}
    monkeypatch.setattr(tasks,'run_mineru_job',run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(tasks._execute_mineru_ocr_extract,SimpleNamespace(),job['id'])
        assert entered.wait(5)
        second=tasks._execute_mineru_ocr_extract(SimpleNamespace(),job['id'])
        release.set();assert first.result()['status']=='success'
    assert second['status']=='duplicate_inflight'
    assert len(calls)==1


def test_selected_pages_are_not_silently_expanded(tmp_path):
    import fitz
    from libs.official_ocr_pipeline import selected_source_pages
    from libs.aliyun_ocr import AliyunOcrError
    path=tmp_path/'three.pdf'
    with fitz.open() as doc:
        for _ in range(3):doc.new_page()
        doc.save(path)
    runtime={'render':{'maxDocumentPages':200,'requestedPageNos':[2,3]}}
    assert selected_source_pages(path,{},runtime)==[2,3]
    runtime['render']['requestedPageNos']=[4]
    with pytest.raises(AliyunOcrError):selected_source_pages(path,{},runtime)


def test_remote_source_rejects_private_address_before_connect(monkeypatch,tmp_path):
    import libs.ocr_source as source
    monkeypatch.setattr(source.socket,'getaddrinfo',lambda *a,**kw:[(0,0,0,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='NOT_PUBLIC'):
        source.download_public_ocr_source('https://test.example/file.pdf',tmp_path/'file.pdf')


def test_lost_lock_refuses_ocr_persistence(monkeypatch):
    import threading
    import libs.pipeline_lock as locks
    event=threading.Event();event.set();token=locks._ACTIVE_LOCK_LOST.set(event)
    monkeypatch.setattr(tasks,'flush_state_records',lambda *a:pytest.fail('Must not persist without execution ownership'))
    try:
        with pytest.raises(locks.PipelineLockUnavailable):tasks._persist_mineru_job({'id':'stale'})
    finally:locks._ACTIVE_LOCK_LOST.reset(token)


def test_credentials_only_reused_for_same_dashscope_region():
    from libs.ocr_runtime import ocr_runtime_config
    env={'AICHECK_LLM_VISION_API_BASE':'https://dashscope.aliyuncs.com/compatible-mode/v1','AICHECK_LLM_VISION_API_KEY':'test-key'}
    c=ocr_runtime_config(env=env)
    assert c['official']['apiKey']=='test-key'
    assert c['official']['apiKeyEnv']=='AICHECK_LLM_VISION_API_KEY'
    env['AICHECK_LLM_VISION_API_BASE']='https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
    assert not ocr_runtime_config(env=env)['official']['apiKeyConfigured']


def test_ocr_lock_fails_closed_when_configured_database_unavailable(monkeypatch):
    import sys
    from libs.pipeline_lock import pipeline_lock, PipelineLockUnavailable
    monkeypatch.setenv('AICHECK_DATABASE_URL','postgresql://not-available')
    monkeypatch.setenv('AICHECK_STRICT_PRODUCTION','false')
    def unavailable(*a,**kw):raise ConnectionError('not available')
    monkeypatch.setitem(sys.modules,'psycopg',SimpleNamespace(connect=unavailable,Error=Exception))
    with pytest.raises(PipelineLockUnavailable):
        with pipeline_lock('failover-test',keepalive=True):pytest.fail('Cannot use a local lock on DB failure')
