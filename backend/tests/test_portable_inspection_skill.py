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
    login = http.post("/api/auth/login", json={"username": "inspection", "password": "anyuekeji.123"}).json()
    assert login["code"] == 0
    monkeypatch.setenv("AICHECK_BASE_URL", "http://127.0.0.1")
    monkeypatch.setenv("AICHECK_TOKEN", login["data"]["token"])
    # These services do not depend on membership of an application project.
    repo.state["project_members"] = []
    requests = []

    class Opener:
        def open(self, request, timeout=None):
            parsed = urlsplit(request.full_url)
            assert parsed.hostname == "127.0.0.1", "No external requests in portable integration"
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


def test_registry_uses_authorized_identifier_without_system_cache(connected, monkeypatch):
    from libs.integrations import external_registry_queries

    seen = []
    def query(identifier):
        seen.append(identifier)
        return {"person": {"ryxm": "测试人员"}, "licenses": []}
    monkeypatch.setattr(external_registry_queries, "query_cnse_persons", query)
    before = deepcopy(repo.state)
    checked("certificate_registry", {"kind": "person", "identifier": "110101199001011234", "allowExternalQuery": True})
    assert seen == ["110101199001011234"]
    assert repo.state == before


@pytest.mark.parametrize("action", ["ocr", "projects", "documents", "evidence", "upload", "download", "analyze", "start", "runs"])
def test_removed_engineering_data_actions_never_reach_backend(connected, action):
    result = portable.invoke(action, {})
    assert not result["ok"] and result["error"]["code"] == "unknownAction"
    assert connected == []


def test_invalid_token_cannot_use_review_services(connected, monkeypatch):
    monkeypatch.setenv("AICHECK_TOKEN", "revoked-token")
    result = portable.invoke("connection", {})
    # Existing API authentication failures use the business envelope at HTTP 200.
    assert not result["ok"] and result["error"]["code"] == "401"
