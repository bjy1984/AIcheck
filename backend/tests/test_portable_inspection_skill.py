"""Portable review client against real FastAPI; only HTTP transport is in-process."""
import importlib.util
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("portable_client", ROOT / "skills/aicheck-inspection/scripts/aicheck_client.py")
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class Response(BytesIO):
    def __init__(self, response):
        super().__init__(response.content)
        self.status = response.status_code
        self.headers = response.headers


@pytest.fixture
def connected(monkeypatch):
    repo.reset()
    for name, value in {"postgres_enabled": False, "sync_postgres": None, "postgres_dsn": None,
                        "sqlite_enabled": False, "sqlite_path": None}.items():
        monkeypatch.setattr(repo, name, value)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")
    http = TestClient(app)
    monkeypatch.setenv("AICHECK_BASE_URL", "http://127.0.0.1")
    monkeypatch.delenv("AICHECK_TOKEN", raising=False)
    monkeypatch.delenv("AICHECK_TOKEN_FILE", raising=False)
    # These services do not depend on membership of an application project.
    repo.state["project_members"] = []
    requests = []

    class Opener:
        def open(self, request, timeout=None):
            parsed = urlsplit(request.full_url)
            assert parsed.hostname == "127.0.0.1", "No external requests in portable integration"
            assert not request.has_header("Authorization")
            requests.append((request.method, parsed.path))
            response = http.request(request.method, parsed.path + ("?" + parsed.query if parsed.query else ""),
                headers=dict(request.header_items()), content=request.data, follow_redirects=False)
            return Response(response)

    monkeypatch.setattr(portable.request, "build_opener", lambda *args: Opener())
    return requests


def checked(action, arguments):
    result = portable.invoke(action, arguments)
    assert result["ok"], result
    return result["data"]


def test_projectless_connection_and_versioned_rules(connected):
    before = deepcopy(repo.state)
    capabilities = checked("connection", {})
    assert capabilities["projectRequired"] is False
    assert capabilities["ocrProvided"] is False
    assert capabilities["documentUploadAccepted"] is False
    assert capabilities["retention"]["serverStoresInput"] is False
    assert checked("rules", {"nodeId": 24})["source"] == "local"
    remote = checked("rules", {"source": "server", "nodeId": 24})
    assert remote["nodes"][0]["nodeId"] == 24
    assert remote["nodes"][0]["version"]
    assert len(checked("rules", {"source": "server"})["nodes"]) == 12
    assert repo.state == before


def test_minimal_certificate_facts_do_not_create_data_or_review_tasks(connected):
    before = deepcopy(repo.state)
    facts = {"certificates": [{"certificateNo": "LOCAL-ONLY-CERTIFICATE", "holder": "测试人员",
                              "validFrom": "2024-01-01", "validUntil": "2027-01-01", "scopes": ["GC2"]}],
             "expectedHolder": "测试人员", "requiredScopes": ["GC2"],
             "periodStart": "2026-09-01", "periodEnd": "2026-09-20"}
    result = checked("certificate_validity", facts)
    assert result["result"] == "passed"
    assert result["authenticityVerified"] is False
    facts["periodEnd"] = "2027-01-02"
    assert checked("certificate_validity", facts)["result"] == "failed"
    del facts["periodStart"]
    del facts["periodEnd"]
    assert not portable.invoke("certificate_validity", facts)["ok"]
    assert repo.state == before


def test_registry_queries_without_confirmation_and_without_system_cache(connected, monkeypatch):
    from libs.integrations import external_registry_queries

    seen = []
    def query(identifier):
        seen.append(identifier)
        return {"person": {"ryxm": "测试人员"}, "licenses": []}
    monkeypatch.setattr(external_registry_queries, "query_cnse_persons", query)
    before = deepcopy(repo.state)
    checked("certificate_registry", {"kind": "person", "identifier": "110101199001011234"})
    assert seen == ["110101199001011234"]
    assert repo.state == before


@pytest.mark.parametrize("action", ["ocr", "projects", "documents", "evidence", "upload", "download", "analyze", "start", "runs"])
def test_removed_engineering_data_actions_never_reach_backend(connected, action):
    result = portable.invoke(action, {})
    assert not result["ok"] and result["error"]["code"] == "unknownAction"
    assert connected == []


def test_old_token_configuration_does_not_block_public_services(connected, monkeypatch):
    monkeypatch.setenv("AICHECK_TOKEN", "revoked-token")
    monkeypatch.setenv("AICHECK_TOKEN_FILE", "/missing/old-token")
    assert checked("connection", {})["authenticationRequired"] is False


def test_standard_services_use_public_routes(connected, monkeypatch):
    from apps.api import std_samr_routes
    monkeypatch.setattr(std_samr_routes, "query_standard_status", lambda *args: {"status": "COMPLETED"})
    assert "items" in checked("standards", {"query": "管道"})
    assert checked("standard_status", {"standardRef": "GB/T 20801.1-2020"})["status"] == "COMPLETED"
    result = portable.invoke("standard_content", {"fileId": "KF-KB-MISSING"})
    assert result["error"]["code"] == "standardFileUnavailable"
    assert all(path.startswith("/api/inspection-services/") for _, path in connected)


def test_search_to_actual_canonical_content_roundtrip(connected):
    from test_standard_knowledge_canonical import canonical_source_fixture
    from libs.standard_knowledge_canonical import build_standard_knowledge_record
    state=canonical_source_fixture()
    for key,rows in state.items():
        repo.state[key]=rows
    file=state['knowledge_files'][0]
    record=build_standard_knowledge_record(state,file["id"],ROOT)
    repo.state['standard_knowledge_records']=[record]
    hits=checked('standards',{'query':'范围正文'})['items']
    assert hits
    hit=next(item for item in hits if item['fileId']==file['id'])
    assert hit['standardContentAvailable'] is True
    assert hit['evidenceKind']=='standard_text'
    result=checked('standard_content',hit['standardContentArguments'])
    assert result['knowledgeFileId']==file['id']
    assert result['sourceFingerprint']==record['sourceFingerprint']
    assert '范围正文' in str(result)


def test_rule_versions_and_data_readiness(connected):
    local=checked('rules',{})
    remote=checked('rules',{'source':'server'})
    assert all(row['ruleVersion']==local['ruleVersion'] for row in remote['nodes'])
    readiness=checked('connection',{})['standardContent']
    assert readiness['canonicalRecordCount']==0
    assert readiness['available'] is False
    hits=checked('standards',{'query':'工业管道'})['items']
    assert hits
    for row in hits:
        assert row['fileId']
        assert row['evidenceKind']=='business_rule'
        assert row['ruleFamily']=='legacy-business-rules'
        assert row['formalEvidenceEligible'] is False
        assert row['pageNo'] is None
        assert row['standardContentAvailable'] is False
        assert row['standardContentArguments'] is None


@pytest.mark.parametrize('value',['rules/standards/a.pdf','a\\b','../a'])
def test_invalid_file_paths_rejected_without_http(connected,value):
    result=portable.invoke('standard_content',{'fileId':value})
    assert result['error']['code']=='invalidArguments'
    assert connected==[]


def test_tsg_reports_adapter_limit_instead_of_invalid_input(connected):
    result=checked('standard_status',{'standardRef':'TSG D0001-2009','reviewDate':'2021-04-02'})
    assert result['verdict']=='unsupported_family'
    assert result['manualConfirmationRequired'] is True


def test_registry_explicit_disable_prevents_http(connected):
    result=portable.invoke('certificate_registry',{'kind':'person','identifier':'TEST','allowExternalQuery':False})
    assert result['error']['code']=='invalidArguments'
    assert connected==[]


def test_readonly_sidecar_corpus_does_not_modify_project_repository(connected, monkeypatch, tmp_path):
    import json
    from test_standard_knowledge_canonical import canonical_source_fixture
    from libs.standard_knowledge_canonical import build_standard_knowledge_record
    from libs.inspection_standard_corpus import SCHEMA
    state=canonical_source_fixture()
    file=state['knowledge_files'][0]
    state['standard_knowledge_records']=[build_standard_knowledge_record(state,file['id'],ROOT)]
    path=tmp_path/'corpus.json'
    path.write_text(json.dumps({'schemaVersion':SCHEMA,'state':state}))
    monkeypatch.setenv('AICHECK_INSPECTION_CORPUS',str(path))
    before=deepcopy(repo.state)
    assert checked('connection',{})['standardContent']['canonicalRecordCount']==1
    hit=checked('standards',{'query':'范围正文'})['items'][0]
    assert hit['fileId']==file['id']
    content=checked('standard_content',hit['standardContentArguments'])
    assert '范围正文' in str(content)
    assert repo.state==before
    assert '范围正文' in str(checked('standard_content',{'fileId':file['id'],'pageNo':7}))


def test_corpus_rejects_project_material(tmp_path,monkeypatch):
    import json
    from libs.inspection_standard_corpus import standard_state,SCHEMA
    path=tmp_path/'corpus.json'
    path.write_text(json.dumps({'schemaVersion':SCHEMA,'state':{
        'knowledge_files':[{'id':'private','sourceType':'standard','projectId':'P'}],
        'standard_knowledge_records':[]}}))
    monkeypatch.setenv('AICHECK_INSPECTION_CORPUS',str(path))
    with pytest.raises(ValueError,match='project documents'):
        standard_state({})


def test_public_search_does_not_substitute_unrelated_or_nonexistent_standards(connected):
    for query in ('zzz不存在的东西qqq','GB 50316 工业金属管道设计规范'):
        assert checked('standards',{'query':query})['items']==[]


@pytest.mark.parametrize('file_id',['KS-STANDARD-RULES','GBT 8163-2018.pdf','a/b'])
def test_content_rejects_non_file_identifiers_locally(connected,file_id):
    assert portable.invoke('standard_content',{'fileId':file_id})['error']['code']=='invalidArguments'
    assert connected==[]


def test_public_search_exposes_uncertainty_and_blocks_conflicting_identity(connected):
    from test_standard_knowledge_canonical import canonical_source_fixture
    from libs.standard_knowledge_canonical import build_standard_knowledge_record
    state = canonical_source_fixture()
    for key, rows in state.items():
        repo.state[key] = rows
    file = state['knowledge_files'][0]
    record = build_standard_knowledge_record(state, file['id'], ROOT)
    record['identity']['standardCode'] = {'value': 'NB/T 47013.10-2015', 'sources': [{'value': 'NB/T 47013.10-2015', 'sourceType': 'filename_inference'}]}
    repo.state['standard_knowledge_records'] = [record]
    query = {'query': 'NB/T 47013.10-2015'}
    hits = checked('standards', query)['items']
    assert hits and all(h['identityCheck']['status'] == 'unverified' for h in hits)
    assert all(h['formalEvidenceEligible'] is False for h in hits)
    record['blocks'].append({'text': 'NB/T 47013.10-2015', 'pageNo': 1})
    hits = checked('standards', query)['items']
    assert hits and all(h['identityCheck']['status'] == 'verified' for h in hits)
    record['blocks'][-1]['text'] = 'NB/T 47013.10-2025'
    assert checked('standards', query)['items'] == []
    hits = checked('standards', {'query': '范围正文'})['items']
    assert hits and all(h['identityCheck']['status'] == 'conflict' for h in hits)
    assert all(h['formalEvidenceEligible'] is False for h in hits)
