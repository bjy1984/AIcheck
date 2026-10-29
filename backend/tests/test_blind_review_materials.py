from fastapi.testclient import TestClient
from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)


def setup_function():
    repo.reset()


def test_blind_materials_are_run_scoped_and_do_not_reveal_conclusions():
    document = repo.state['documents'][0]
    project_id = document['projectId']
    version = repo.current_version(document['id'])
    repo.state['blind_review_tasks'] = [{'id': 'BRT-M', 'projectId': project_id, 'nodeId': 24, 'aiRunId': 'RUN-M', 'status': 'open', 'aiResult': 'secret-ai', 'regularResult': 'secret-human'}]
    repo.state['ai_runs'].insert(0, {'id': 'RUN-M', 'projectId': project_id, 'nodeId': 24, 'inputDocumentVersionIds': [version['id']], 'suggestion': {'result': 'secret-ai'}})
    response = client.get('/api/fde/blind-review/tasks/BRT-M/materials', headers={'X-Role': 'fde'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['code'] == 0, payload
    data = payload['data']
    assert [item['documentVersionId'] for item in data['materials']] == [version['id']]
    assert data['scopeSource'] == 'run_snapshot'
    assert 'versionId=' in data['materials'][0]['originalUrl']
    assert data['materials'][0]['downloadUrl'] == data['materials'][0]['originalUrl'].replace('disposition=inline', 'disposition=attachment')
    assert 'secret-ai' not in response.text and 'secret-human' not in response.text
    assert 'suggestion' not in response.text and 'reviewOpinion' not in response.text
    assert client.get('/api/fde/blind-review/tasks/BRT-M/materials', headers={'X-Role': 'contractor'}).json()['code'] != 0
    assert client.get('/api/fde/blind-review/tasks/missing/materials', headers={'X-Role': 'fde'}).json()['code'] != 0


def test_blind_materials_do_not_substitute_current_files_for_missing_snapshot():
    project = repo.state['projects'][0]
    repo.state['blind_review_tasks'] = [{'id': 'BRT-LEGACY', 'projectId': project['id'], 'nodeId': 24, 'aiRunId': 'MISSING', 'status': 'open'}]
    data = client.get('/api/fde/blind-review/tasks/BRT-LEGACY/materials', headers={'X-Role': 'fde'}).json()['data']
    assert data['materials'] == []
    assert data['scopeSource'] == 'unavailable'
    assert data['unavailableReason']
