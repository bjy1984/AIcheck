import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api import data_service_mcp_routes as m

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);(tmp_path/'output').mkdir();(tmp_path/'output/data-services-noauth.enabled').write_text('enabled')
    app=FastAPI();app.include_router(m.router,prefix='/api');return TestClient(app)

def call(c,method,params={}):
    return c.post('/api/mcp/data-services',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})

def test_protocol(client):
    assert call(client,'initialize',{'protocolVersion':'2025-06-18'}).json()['result']['protocolVersion']=='2025-06-18'
    tools=call(client,'tools/list').json()['result']['tools'];assert len(tools)==9
    submit=next(t for t in tools if t['name']=='aicheck_ocr_submit')
    assert 'filePath' not in submit['inputSchema']['properties']
    assert client.get('/api/mcp/data-services').status_code==405
    assert client.post('/api/mcp/data-services',json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code==202
    assert client.post('/api/mcp/data-services',headers={'origin':'https://untrusted.example'},json={}).status_code==403
    assert call(client,'tools/call',{'name':'aicheck_rules','arguments':{}}).json()['error']['code']==-32602

def test_upload_ticket_and_bytes(client,monkeypatch):
    received=[]
    async def fake_api(request,method,path,**kwargs):
        received.append((method,path,kwargs));return {'ok':True,'data':{'jobId':'TEST'}}
    monkeypatch.setattr(m,'api',fake_api)
    args={'fileName':'test.pdf','requestId':'1234567890abcdef','profileId':'generic_document_v1'}
    r=call(client,'tools/call',{'name':'aicheck_ocr_submit','arguments':args}).json()
    data=json.loads(r['result']['content'][0]['text'])['data']
    from urllib.parse import urlsplit
    path=urlsplit(data['uploadUrl']).path
    assert client.put(path,content=b'%PDF-1.4 test').json()['data']['jobId']=='TEST'
    assert received[0][2]['body']==b'%PDF-1.4 test'
    assert received[0][2]['headers']['Idempotency-Key']==args['requestId']
    import base64
    metadata=json.loads(base64.b64decode(received[0][2]['headers']['X-AICheck-Ocr-Metadata-B64']))
    assert metadata['profileId']=='generic_document_v1'
    assert client.put(path+'x',content=b'test').status_code==403
    monkeypatch.setattr(m.time,'time',lambda:9999999999)
    assert client.put(path,content=b'test').status_code==403
    r=call(client,'tools/call',{'name':'aicheck_ocr_submit','arguments':{**args,'fileName':'/etc/test.pdf'}})
    assert 'error' in r.json()
    r=call(client,'tools/call',{'name':'aicheck_ocr_submit','arguments':{**args,'profileId':'not_a_real_profile'}})
    assert r.json()['error']['code']==-32602

def test_proxy_url_mapping_and_error(client,monkeypatch):
    received=[]
    async def fake_api(request,method,path,**kwargs):
        received.append((method,path,kwargs));return {'ok':False,'error':{'code':'401'}}
    monkeypatch.setattr(m,'api',fake_api)
    r=call(client,'tools/call',{'name':'aicheck_standards','arguments':{'query':'GB/T 39280-2020'}}).json()['result']
    assert r['isError']
    assert received[0][2]['query']['keyword']=='GB/T 39280-2020'

def test_connection_describes_remote_ocr_storage(client,monkeypatch):
    async def fake_api(*args,**kwargs):
        return {'ok':True,'data':{'ocrProvided':False,'documentUploadAccepted':False,
                                 'retention':{'serverStoresInput':False,'serverStoresResult':False}}}
    monkeypatch.setattr(m,'api',fake_api)
    r=call(client,'tools/call',{'name':'aicheck_connection','arguments':{}}).json()
    d=json.loads(r['result']['content'][0]['text'])['data']
    assert d['ocrProvided'] and d['documentUploadAccepted']
    assert d['retention']['serverStoresInput'] and d['retention']['serverStoresResult']
    assert d['retention']['externalProviders']==['MinerU','Alibaba Cloud Qwen']
    assert d['ocr']['fallbackProvider']=='qwen'
    assert d['retention']['automaticDeletionGuaranteed'] is False
    assert d['ocr']['executionVerified'] is False
