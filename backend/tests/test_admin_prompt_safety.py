"""Production templates are immutable; publication is an explicit transition."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)


@pytest.fixture(autouse=True)
def memory_repository():
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def create_draft():
    response = client.post('/admin/prompt-templates', json={
        'name': 'Production safety regression', 'status': 'draft',
        'businessPackId': 'safety-pack', 'promptKey': 'safety-review',
        'systemPrompt': 'Keep traceable evidence', 'version': 'v1',
    }).json()
    assert response['code'] == 0, response
    return response['data']['template']


@pytest.mark.parametrize('status', ['production', '已发布'])
def test_production_template_cannot_be_edited_or_downgraded(status):
    template = create_draft()
    record = repo.find_one('prompt_templates', template['id'])
    record['status'] = status
    before = deepcopy(record)
    response = client.patch(f"/admin/prompt-templates/{template['id']}", json={
        'status': 'draft', 'systemPrompt': 'Mutated production instructions',
    }).json()
    assert response['code'] != 0
    assert response['data']['reason'] == 'VALIDATION_ERROR'
    assert record == before


@pytest.mark.parametrize('status', ['production', '已发布'])
def test_create_and_update_cannot_bypass_publish_action(status):
    template = create_draft()
    count = len(repo.state['prompt_templates'])
    response = client.post('/admin/prompt-templates', json={
        'name': 'Bypass publication', 'systemPrompt': 'Unsafe', 'status': status,
    }).json()
    assert response['code'] != 0
    assert len(repo.state['prompt_templates']) == count
    response = client.put(f"/admin/prompt-templates/{template['id']}", json={
        'status': status,
    }).json()
    assert response['code'] != 0
    assert repo.find_one('prompt_templates', template['id'])['status'] == 'draft'


def test_new_draft_can_be_edited_then_published_without_mutating_source():
    original = create_draft()
    response = client.post(f"/admin/prompt-templates/{original['id']}/publish", json={
        'reason': 'Reviewed v1',
    }).json()
    assert response['code'] == 0
    original_record = repo.find_one('prompt_templates', original['id'])
    draft = create_draft()
    response = client.patch(f"/admin/prompt-templates/{draft['id']}", json={
        'version': 'v2', 'systemPrompt': 'New reviewed instructions',
    }).json()
    assert response['code'] == 0
    assert original_record['systemPrompt'] == 'Keep traceable evidence'

    response = client.post(f"/admin/prompt-templates/{draft['id']}/publish", json={
        'reason': 'Reviewed replacement v2',
    }).json()
    assert response['code'] == 0
    assert response['data']['template']['status'] == 'production'
    assert original_record['status'] == 'retired'
    assert original_record['systemPrompt'] == 'Keep traceable evidence'


@pytest.mark.parametrize('status', ['draft', '草稿', 'retired', '已停用'])
def test_runtime_never_falls_back_to_an_unpublished_template(status):
    from libs.business_pack import build_ai_review_prompt, load_business_pack
    from libs.review_orchestrator.execution import select_prompt_template

    repo.state['prompt_templates'] = [{
        'id': 'UNPUBLISHED', 'status': status, 'businessPackId': 'engineering_inspection_v1',
        'version': 'v-next', 'systemPrompt': 'UNPUBLISHED_PROMPT_MUST_NOT_EXECUTE',
    }]
    selected = select_prompt_template({
        'businessPackId': 'engineering_inspection_v1', 'promptVersion': 'UNPUBLISHED',
    })
    assert selected is None
    parts = build_ai_review_prompt(
        load_business_pack('engineering_inspection_v1'), node={'nodeId': 1},
        fields=[], prompt_template=selected,
    )
    assert 'UNPUBLISHED_PROMPT_MUST_NOT_EXECUTE' not in parts['system']
    assert parts['template']['id'] is None


def test_runtime_never_falls_back_to_another_business_pack():
    from libs.review_orchestrator.execution import select_prompt_template

    repo.state['prompt_templates'] = [{
        'id': 'FOREIGN', 'status': 'production', 'businessPackId': 'foreign-pack',
        'systemPrompt': 'Instructions for a different business',
    }]
    assert select_prompt_template({'businessPackId': 'engineering_inspection_v1'}) is None


@pytest.mark.parametrize('status', ['production', 'published', 'active', '启用', '已发布'])
def test_runtime_still_selects_a_matching_published_version(status):
    from libs.review_orchestrator.execution import select_prompt_template

    production = {'id': 'PRODUCTION', 'status': status, 'businessPackId': 'safety-pack',
                  'version': 'v1', 'systemPrompt': 'Published evidence instructions'}
    repo.state['prompt_templates'] = [
        {**production, 'id': 'NEW-DRAFT', 'status': 'draft', 'version': 'v2'},
        production,
    ]
    selected = select_prompt_template({'businessPackId': 'safety-pack', 'promptVersion': 'v1'})
    assert selected == production
    assert selected is not production
