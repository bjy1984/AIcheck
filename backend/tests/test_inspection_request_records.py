from uuid import uuid4
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from apps.api import main
from libs.db.repository import repo

client = TestClient(main.app)
URL = '/api/inspection-services/requests'
ADMIN = {'X-Role': 'admin', 'X-User-Id': 'USER-ADMIN-001'}

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    repo.reset()
    for k,v in dict(postgres_enabled=False,sync_postgres=None,postgres_dsn=None,sqlite_enabled=False,sqlite_path=None).items():
        monkeypatch.setattr(repo,k,v)
    monkeypatch.setattr(repo,'sqlite_enabled',True)
    monkeypatch.setattr(repo,'sqlite_path',str(tmp_path/'requests.sqlite'))
    repo.state['inspection_requests']=[]

def payload():return dict(requestId=str(uuid4()),requestText='核对焊材与工程要求\n保留原始换行。',platform='WorkBuddy',nodeIds=[24,26])

def test_register_retry_admin_query_and_tenant_boundary(monkeypatch):
    import libs.db.repository as db
    writes=[]
    monkeypatch.setattr(db,'flush_state_records',lambda records:writes.append(deepcopy(records)))
    p=payload()
    for _ in range(2):
        response=client.post(URL,json=p)
        assert response.status_code==200,response.text
        assert response.json()['data']['saved']
    assert len(writes)==1
    assert writes[0]['inspection_requests'][0]['requestText']==p['requestText']
    response=client.get(URL,headers=ADMIN,params={'keyword':'焊材','pageSize':1})
    assert response.status_code==200,response.text
    assert response.json()['data']['total']==1
    assert response.json()['data']['items'][0]['identityVerified'] is False
    repo.state['inspection_requests'].append({**repo.state['inspection_requests'][0],'id':str(uuid4()),'tenantId':'another-tenant'})
    assert client.get(URL,headers=ADMIN).json()['data']['total']==1
    assert client.get(URL).status_code in (401,403)
    assert client.get(URL,headers={'X-Role':'inspection','X-User-Id':'USER-INSPECTION-001'}).status_code==403
    p['requestText']='different'
    assert client.post(URL,json=p).status_code==409

@pytest.mark.parametrize('change',[{'requestText':' '},{'requestText':'x'*4001},{'nodeIds':[99]},{'requestId':'bad'},{'ocrText':'附件全文'}])
def test_invalid_requests_are_not_saved(change):
    p=payload();p.update(change)
    assert client.post(URL,json=p).status_code==400
    assert not repo.state['inspection_requests']

def test_sqlite_records_survive_reload(tmp_path,monkeypatch):
    # Exercise the application's actual record writer, then reload from storage.
    path=tmp_path/'requests.sqlite'
    monkeypatch.setattr(repo,'sqlite_enabled',True)
    monkeypatch.setattr(repo,'sqlite_path',path)
    p=payload();response=client.post(URL,json=p)
    assert response.status_code==200,response.text
    repo.state['inspection_requests']=[]
    repo.load_from_sqlite(selected_state_keys={'inspection_requests'})
    row=next(r for r in repo.state['inspection_requests'] if r['id']==p['requestId'])
    assert row['requestText']==p['requestText']


def test_failed_persistence_does_not_claim_saved(monkeypatch):
    import libs.db.repository as db
    def fail_write(records): raise OSError('database unavailable')
    monkeypatch.setattr(db,'flush_state_records',fail_write)
    response=client.post(URL,json=payload())
    assert response.status_code==503
    assert not repo.state['inspection_requests']


def test_registration_does_not_duplicate_text_in_audit_or_logs(caplog):
    import logging
    p=payload();p['requestText']='UNIQUE-PRIVATE-REQUEST-TEXT'
    before=deepcopy(repo.state.get('audit_logs',[]))
    with caplog.at_level(logging.INFO):
        assert client.post(URL,json=p).status_code==200
    assert repo.state.get('audit_logs',[])==before
    assert p['requestText'] not in caplog.text


def test_memory_only_mode_cannot_claim_saved(monkeypatch):
    monkeypatch.setattr(repo, 'sqlite_enabled', False)
    monkeypatch.setattr(repo, 'sqlite_path', None)
    response = client.post(URL, json=payload())
    assert response.status_code == 503
    assert not repo.state['inspection_requests']
