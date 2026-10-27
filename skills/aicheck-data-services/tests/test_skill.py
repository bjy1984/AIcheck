import importlib.util,json,sys
from pathlib import Path
from unittest.mock import patch
import pytest
S=Path(__file__).resolve().parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('data_transport',S/'service_transport.py');transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
sys.modules['service_transport']=transport
spec=importlib.util.spec_from_file_location('data_client_under_test',S/'data_client.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

def test_scope_excludes_review():
    assert len(c.ACTIONS)==9
    for name in ('rules','review_request','start','projects'):
        assert not c.invoke(name,{})['ok']
    assert c.ACTIONS['ocr_submit']['readOnly'] is False

def test_upload_exact_bytes_and_no_project(tmp_path,monkeypatch):
    p=tmp_path/'test.pdf';p.write_bytes(b'%PDF-1.4 test')
    monkeypatch.setenv('AICHECK_DATA_ALLOWED_ROOTS',json.dumps([str(tmp_path)]))
    with patch.object(c,'Client') as C:
        client=C.return_value;client.decode.return_value={'jobId':'OCR-1'};client.safe.side_effect=lambda x:x
        out=c.invoke('ocr_submit',{'filePath':str(p),'requestId':'a'*32})
        assert out['ok']
        assert client.open.call_args.kwargs['body']==p.read_bytes()
        assert 'documentId' not in str(client.open.call_args)
        assert out['data']['sourceSha256']
        client.open.reset_mock()
        denied=c.invoke('ocr_submit',{'filePath':'/etc/passwd','requestId':'a'*32})
        assert denied['error']['code']=='pathNotAllowed'
        client.open.assert_not_called()

def test_no_local_runtime_or_empty_credential_assumption(monkeypatch):
    monkeypatch.delenv('AICHECK_BASE_URL',raising=False)
    assert c.invoke('connection',{})['error']['code']=='notConfigured'
    assert not c.invoke('ocr_result',{'jobId':'x','pageNo':0})['ok']
