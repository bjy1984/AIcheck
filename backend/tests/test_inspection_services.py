"""No project state, payload audit, upload, provider cache or response replay."""
from __future__ import annotations

import json
import logging
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs.db.repository import repo

client = TestClient(main.app)
PREFIX = "/api/inspection-services"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001", "Idempotency-Key": "no-payload-cache"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)


def data(response):
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["data"]


def test_certificate_input_and_results_are_not_persisted_or_replayed(monkeypatch, caplog):
    before = deepcopy(repo.state)
    def no_write(*args, **kwargs):
        pytest.fail("ephemeral request must not flush project/audit/idempotency records")
    monkeypatch.setattr(main, "flush_state", no_write)
    monkeypatch.setattr(main, "flush_mutation_records", no_write)
    payload = {"certificates": [{"holder": "PRIVATE-HOLDER", "validFrom": "2024-01-01", "validUntil": "2028-01-01"}],
               "referenceDate": "2026-09-22"}
    with caplog.at_level("INFO", logger="aicheck.api"):
        output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json=payload))
        assert output["result"] == "passed"
        data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json=payload))
    assert repo.state == before
    assert "PRIVATE-HOLDER" not in caplog.text
    assert "operation=certificate-validity status=200 duration_ms=" in caplog.text


def test_rules_are_versioned_and_need_no_project_membership():
    repo.state["project_members"] = []
    before = deepcopy(repo.state)
    assert len(data(client.get(PREFIX + "/rules", headers=HEADERS))["nodes"]) == 12
    node = data(client.get(PREFIX + "/rules?nodeId=24", headers=HEADERS))["nodes"][0]
    assert node["nodeId"] == 24 and node["version"] and "平台" in node["content"]
    assert client.get(PREFIX + "/rules?nodeId=1", headers=HEADERS).status_code == 400
    assert repo.state == before


def test_service_does_not_offer_ocr_or_document_upload():
    output = data(client.get(PREFIX + "/capabilities", headers=HEADERS))
    assert output["projectRequired"] is False
    assert output["documentUploadAccepted"] is False
    assert output["ocrProvided"] is False
    assert output["retention"]["temporaryFiles"] == "none"
    assert output["certificateRegistry"]["externalProviderRetention"] == "not_controlled"
    assert client.post(PREFIX + "/ocr", headers=HEADERS, json={}).status_code == 404


def test_request_stream_limit_and_invalid_json_have_no_retention():
    before = deepcopy(repo.state)
    response = client.post(PREFIX + "/certificate-registry", headers=HEADERS, content=b"x" * 4097)
    assert response.status_code == 413
    response = client.post(PREFIX + "/certificate-validity", headers=HEADERS, content=b"not-json")
    assert response.status_code == 400
    assert repo.state == before


@pytest.mark.parametrize("certificate,expected", [
    ({"holder": "张三", "validFrom": "2024-01-01", "validUntil": "2028-01-01"}, "passed"),
    ({"holder": "张三", "validUntil": "2020-01-01"}, "failed"),
    ({"holder": "张三", "validFrom": "2027-01-01", "validUntil": "2028-01-01"}, "failed"),
    ({"holder": "张三丰", "validUntil": "2028-01-01"}, "failed"),
    ({"holder": "张三"}, "evidence_insufficient"),
])
def test_certificate_checks_are_deterministic_and_not_authenticity(certificate, expected):
    before = deepcopy(repo.state)
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={
        "certificates": [certificate], "expectedHolder": "张三", "referenceDate": "2026-09-22"}))
    assert output["result"] == expected
    assert output["authenticityVerified"] is False
    assert repo.state == before


def test_certificate_date_validation_and_empty_evidence():
    for body in [
        {"certificates": [{"validUntil": "2026-02-31"}]},
        {"certificates": [], "periodStart": "2026-01-01"},
        {"certificates": [], "periodStart": "2026-02-01", "periodEnd": "2026-01-01"},
        {"certificates": [], "projectId": "FORBIDDEN"},
        {"certificates": [{"validUntil": "2028-01-01"}]},
    ]:
        assert client.post(PREFIX + "/certificate-validity", headers=HEADERS, json=body).status_code == 400
    assert data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={"certificates": [], "referenceDate": "2026-09-22"}))["result"] == "evidence_insufficient"


def test_validity_period_and_scope_failures_are_specific():
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={
        "certificates": [{"validFrom": "2026-02-01", "validUntil": "2026-10-01", "scopes": ["GC2"]}],
        "periodStart": "2026-01-01", "periodEnd": "2026-09-01", "requiredScopes": ["GC1"],
    }))
    assert output["result"] == "failed"
    failed = {check["code"].split(":")[-1] for check in output["checks"] if not check["passed"]}
    assert {"valid_from_covers_period_start", "scope_exact_items_present"} <= failed


@pytest.mark.parametrize("actual,required,expected", [
    (["压力容器制造"], ["无缝钢管制造"], "failed"),
    (["RT-Ⅰ"], ["RT-Ⅱ"], "failed"),
    (["RT-I"], ["RT-Ⅱ"], "failed"),
    (["RT-II"], ["RT-Ⅱ"], "passed"),
    (["ＧＣ２"], ["GC2"], "passed"),
    (["无缝钢管制造（限小口径）"], ["无缝钢管制造"], "failed"),
    ([], ["无缝钢管制造"], "evidence_insufficient"),
])
def test_scope_matching_preserves_chinese_roman_numerals_and_complete_items(actual, required, expected):
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={
        "certificates": [{"validFrom": "2024-01-01", "validUntil": "2028-01-01", "scopes": actual}],
        "referenceDate": "2026-09-22", "requiredScopes": required,
    }))
    assert output["result"] == expected
    assert output["facts"]["certificates"][0]["dimensionResults"]["scopeMatch"] == expected
    assert output["scopeMatching"] == "NFKC_normalized_exact_items_only"
    assert output["facts"]["requiredScopes"] != [""]
    assert not any("scope_covers_required" in check["code"] for check in output["checks"])


@pytest.mark.parametrize("period", [
    {"referenceDate": "2026-09-22"},
    {"periodStart": "2026-01-01", "periodEnd": "2026-09-22"},
])
def test_missing_certificate_start_never_claims_date_coverage(period):
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={
        "certificates": [{"validUntil": "2028-01-01"}], **period,
    }))
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["certificates"][0]["dimensionResults"]["dateValidity"] == "evidence_insufficient"
    assert any(check["code"] == "valid_from_present" and not check["passed"] for check in output["checks"])


def test_only_requested_dimensions_are_reported_as_checked():
    payload = {"certificates": [{"validFrom": "2024-01-01", "validUntil": "2028-01-01"}],
               "referenceDate": "2026-09-22"}
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json=payload))
    assert output["result"] == "passed"
    assert output["checkedDimensions"] == ["dateValidity"]
    assert output["uncheckedDimensions"] == ["holderMatch", "scopeMatch", "authenticity"]
    assert output["warnings"] == []
    assert output["facts"]["dateBasis"] == "explicit_reference_date"
    payload.update(expectedHolder="张三", requiredScopes=["RT-Ⅱ"])
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json=payload))
    assert output["result"] == "evidence_insufficient"
    assert output["checkedDimensions"] == ["dateValidity", "holderMatch", "scopeMatch"]
    assert output["uncheckedDimensions"] == ["authenticity"]
    dimensions = output["facts"]["certificates"][0]["dimensionResults"]
    assert dimensions == {"dateValidity": "passed", "holderMatch": "evidence_insufficient", "scopeMatch": "evidence_insufficient"}


def test_explicit_business_period_never_invents_today_as_reference_date():
    output = data(client.post(PREFIX + "/certificate-validity", headers=HEADERS, json={
        "certificates": [{"validFrom": "2023-01-01", "validUntil": "2025-01-01"}],
        "periodStart": "2024-01-01", "periodEnd": "2024-09-01",
    }))
    assert output["result"] == "passed"
    assert output["facts"]["referenceDate"] == "2024-09-01"
    assert output["facts"]["referenceDateSource"] == "period_end"
    assert output["facts"]["dateBasis"] == "business_period"


def test_registry_uses_direct_client_only_after_external_consent(monkeypatch, caplog):
    from libs.integrations import external_registry_queries
    calls = []
    def query(identifier):
        calls.append(identifier)
        logging.getLogger("httpx").info("request identity=%s", identifier)
        logging.getLogger("httpcore.http11").info("request identity=%s", identifier)
        return {"person": {"ryxm": "测试人员"}, "licenses": []}
    monkeypatch.setattr(external_registry_queries, "query_cnse_persons", query)
    before = deepcopy(repo.state)
    body = {"kind": "person", "identifier": "110101199001011234", "allowExternalQuery": False}
    assert client.post(PREFIX + "/certificate-registry", headers=HEADERS, json=body).status_code == 400
    assert calls == []
    body["allowExternalQuery"] = True
    with caplog.at_level("INFO"):
        for _ in range(2):
            output = data(client.post(PREFIX + "/certificate-registry", headers=HEADERS, json=body))
            assert output["authenticityConclusion"] == "manual_confirmation_required"
            assert output["retention"]["externalProviderRetention"] == "not_controlled"
        logging.getLogger("httpx").info("unrelated-request-is-still-logged")
    assert len(calls) == 2  # Same idempotency header never caches identity data/results.
    assert repo.state == before
    assert body["identifier"] not in json.dumps(repo.state, ensure_ascii=False)
    assert body["identifier"] not in caplog.text
    assert "unrelated-request-is-still-logged" in caplog.text


def test_registry_failure_is_sanitized_and_not_cached(monkeypatch):
    from libs.integrations import external_registry_queries
    def unavailable(identifier):
        raise RuntimeError("PRIVATE-REGISTRY-IDENTITY=" + identifier)
    monkeypatch.setattr(external_registry_queries, "query_cnse_persons", unavailable)
    before = deepcopy(repo.state)
    response = client.post(PREFIX + "/certificate-registry", headers=HEADERS, json={
        "kind": "person", "identifier": "110101199001011234", "allowExternalQuery": True})
    assert response.status_code == 503
    assert "REGISTRY_UNAVAILABLE" in response.text
    assert "110101199001011234" not in response.text
    assert repo.state == before


def test_authenticated_access_is_required_and_other_roles_denied(monkeypatch):
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    assert client.get(PREFIX + "/rules").json()["code"] != 0
    login = client.post("/api/auth/login", json={"username": "inspection", "password": "anyuekeji.123"}).json()["data"]
    headers = {"Authorization": "Bearer " + login["token"]}
    assert data(client.get(PREFIX + "/rules", headers=headers))["nodes"]
    forged = {**headers, "X-Role": "admin"}
    assert client.post(PREFIX + "/certificate-validity", headers=forged, json={"certificates": []}).json()["code"] != 0
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "false")
    for role in ("owner", "contractor", "ndt", "fde"):
        denied = {"X-Role": role, "X-User-Id": "USER-INSPECTION-001"}
        assert client.get(PREFIX + "/rules", headers=denied).status_code == 403
        assert client.post(PREFIX + "/certificate-validity", headers=denied, json={"certificates": []}).json()["code"] != 0
