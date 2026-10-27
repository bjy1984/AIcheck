import hashlib
import json

from libs.mineru_ocr import finalize_mineru_after_seals
from libs.data_service_ocr_result import project_ocr_result
from libs.seal_vision import read_seal_texts
from tests.test_mineru_ocr import _normalize, _zip_bytes
from libs.mineru_ocr import normalize_mineru_zip


def test_finalized_seals_and_artifact_share_quality_and_unverified_evidence():
    bundle = _normalize(_zip_bytes())
    seal = bundle.result['seals'][0]
    class Client:
        def chat_sync(self, *args, **kwargs):
            return {'reply': json.dumps({'text':'测试质检章','sealType':'公章','legible':True})}
        @staticmethod
        def first_message_text(response):return response['reply']
    # Exercise real seal enrichment and real fusion; only the external model is replaced.
    read_seal_texts([seal], {seal['imagePath']:b'png'}, client=Client())
    bundle.result.setdefault('diagnostics', []).append({'code':'seal_vision_reading'})
    finalize_mineru_after_seals(bundle)
    final = next(s for s in bundle.result['seals'] if s.get('sealName')=='测试质检章')
    assert final['recognized'] is False
    assert final['requiresHumanConfirmation'] is True
    assert final['sealEvidenceLevel']=='model_read_unverified'
    assert 'provider_confidence_unavailable' in bundle.result['quality']['reasons']
    processing = bundle.result['metadata']['postProcessing']
    assert processing['profileExtraction']=='applied' and processing['qualityAfterSealRecognition']=='applied'
    artifact = bundle.artifacts['normalized_json']
    assert json.loads(artifact.data)==bundle.result
    assert artifact.sha256==hashlib.sha256(artifact.data).hexdigest()
    public = project_ocr_result(bundle.result, page_no=1)
    assert public['processing']['provenanceAvailable']
    assert any(s.get('requiresHumanConfirmation') for s in public['seals'])


def test_finalization_keeps_unmapped_coordinates_blocking():
    bundle = _normalize(_zip_bytes(middle={'pdf_info':[{'page_idx':0}]}))
    finalize_mineru_after_seals(bundle)
    assert not bundle.result['formalEvidenceReady']
    assert bundle.result['outcomeStatus']=='partial'
    assert bundle.result['quality']['status']=='needs_human_review'


def test_page_projection_keeps_unlocated_objects_and_does_not_mutate_source():
    source={'pages':[{'pageNo':1},{'pageNo':2}],
            'fields':[{'fieldCode':'document','value':'doc'},{'fieldCode':'page2','pageNo':2}],
            'tables':[{'tableId':'T','rows':[['a']], 'pageNo':None}]}
    page=project_ocr_result(source,page_no=1)
    assert not page['fields'] and not page['tables']
    assert page['documentFields'][0]['value']=='doc'
    assert page['unlocatedContent']['tables'][0]['tableId']=='T'
    page['documentFields'][0]['value']='changed'
    assert source['fields'][0]['value']=='doc'
    assert not page['processing']['provenanceAvailable']


def test_mineru_generic_profile_routes_and_extracts_welder_fields_and_table():
    text='''特种设备焊接作业人员证（测试样本）
姓名 测试人员
证件编号 000000000000000001
档案编号 TS2100000000001
发证机关 测试市场监督管理局
作业项目代号 批准日期 有效日期
GTAW-FeⅡ-6G-3/159-FefS-02/11/12 2024.07.25 2028.07.24
'''
    bundle=normalize_mineru_zip(_zip_bytes(content=[{'type':'text','text':text,'bbox':[10,10,900,400],'page_idx':0}]),
                               storage_key='test.pdf',file_name='test.pdf',profile_id=None,
                               document_type=None,provider_task_id='TEST')
    result=bundle.result
    assert result['profileId']=='welder_certificate_v1'
    assert result['metadata']['detectedProfileId']=='welder_certificate_v1'
    assert any(f.get('fieldCode')=='welder_certificate_no' and f.get('fieldValue')=='000000000000000001' for f in result['fields'])
    assert result['tables']
    assert result['metadata']['postProcessing']['profileExtraction']=='applied'


def test_worker_persists_seal_enrichment_before_refreshing_artifact(monkeypatch):
    from apps.worker import tasks
    from libs.db.repository import InMemoryRepository
    repository=InMemoryRepository()
    job=repository.create_ocr_job_record(document_id='',version_id='',storage_key='https://example.org/test.pdf',
                                         file_name='test.pdf',provider='mineru',source_url='https://example.org/test.pdf')
    class Client:
        def submit_url(self,*args,**kwargs):return {'kind':'task','providerTaskId':'TEST'}
        def wait_for_result(self,*args,**kwargs):return {'full_zip_url':'https://example.org/result.zip'}
        def download_result(self,*args):return _zip_bytes()
    def supplement(job,bundle,archive):
        bundle.result['seals'][0].update({'sealName':'测试单位','recognized':False,'requiresHumanConfirmation':True})
        bundle.result.setdefault('diagnostics',[]).append({'code':'seal_vision_reading'})
    stored={}
    def put(bucket,name,data,**kwargs):
        stored[name]=data;return 'minio://'+bucket+'/'+name
    monkeypatch.setattr(tasks,'repo',repository)
    monkeypatch.setattr(tasks,'MinerUClient',Client)
    monkeypatch.setattr(tasks,'_persist_mineru_job',lambda *a:None)
    monkeypatch.setattr(tasks,'_read_seal_texts_from_zip',supplement)
    monkeypatch.setattr(tasks.object_storage,'put_bytes',put)
    result=tasks.run_mineru_job(job)
    record=repository.finish_ocr_job_record(job,result)
    artifact=json.loads(next(data for name,data in stored.items() if name.endswith('normalized-result.json')))
    assert artifact['seals']==record['seals']
    assert artifact['quality']==record['quality']
    assert record['profilePostprocessVersion'] and record['formalEvidenceReady']==result['formalEvidenceReady']
    assert record['metadata']['postProcessing']['qualityAfterSealRecognition']=='applied'
    assert any(s.get('sealName')=='测试单位' and s['recognized'] is False for s in record['seals'])
