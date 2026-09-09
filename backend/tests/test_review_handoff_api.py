from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_review_workstations import run_for

from apps.api.main import app
from libs.db.repository import STATE_COLLECTIONS, repo

client = TestClient(app)
PROJECT = "P-2026-HDCP-001"
HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    repo.reset()
    repo.postgres_enabled = False
    repo.sqlite_enabled = False
    repo.state["review_handoffs"] = []
    for node, name in ((24, "SOURCE"), (35, "TARGET")):
        run = run_for(node)
        run.update(id=name, projectId=PROJECT, tenantId="TENANT-DEFAULT", inputHash=name, inputDocumentVersionIds=[])
        repo.state["review_runs"].append(run)


def payload():
    return {"sourceRunId": "SOURCE", "targetRunId": "TARGET", "kind": "collaboration",
            "subject": {"objectType": "weld", "objectId": "W-1", "repairRound": 0, "eventId": "EVENT-1"},
            "payload": {"request": "核对返修后检测"}, "evidenceRefs": []}


def test_save_read_deduplicate_and_preserve_stale_handoff():
    assert STATE_COLLECTIONS["review_handoffs"] == "review_handoffs"
    url = f"/api/projects/{PROJECT}/review-handoffs"
    before = deepcopy(repo.state["review_runs"])
    saved = client.post(url, headers=HEADERS, json=payload()).json()
    assert saved["code"] == 0, saved
    record = saved["data"]
    assert record["draft"]["authoritative"] is False
    again = client.post(url, headers=HEADERS, json=payload()).json()
    assert again["data"] == record
    assert len(repo.state["review_handoffs"]) == 1
    detail = client.get(f"{url}/{record['id']}", headers=HEADERS).json()
    assert detail["data"]["validation"]["status"] == "current_draft"
    assert repo.state["review_runs"] == before
    repo.find_one("review_runs", "SOURCE")["inputHash"] = "NEW"
    stale = client.get(f"{url}/{record['id']}", headers=HEADERS).json()
    assert stale["data"]["validation"]["status"] == "stale_or_invalid"
    assert repo.find_one("review_handoffs", record["id"]) == record


@pytest.mark.parametrize("case", ["foreign_project", "foreign_tenant", "missing_run", "outside_evidence", "identity_field", "role", "disabled"])
def test_handoff_rejects_unauthorized_or_invalid_creation(case, monkeypatch):
    body = payload()
    headers = HEADERS
    if case == "foreign_project":
        repo.find_one("review_runs", "TARGET")["projectId"] = "OTHER"
    elif case == "foreign_tenant":
        repo.find_one("review_runs", "TARGET")["tenantId"] = "OTHER"
    elif case == "missing_run":
        body["sourceRunId"] = "MISSING"
    elif case == "outside_evidence":
        body["evidenceRefs"] = [{"documentVersionId": "UNAUTHORIZED", "pageNo": 1}]
    elif case == "identity_field":
        body["authoritative"] = True
    elif case == "role":
        headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    elif case == "disabled":
        monkeypatch.delenv("AICHECK_WORKSTATIONS_ENABLED")
    response = client.post(f"/api/projects/{PROJECT}/review-handoffs", headers=headers, json=body).json()
    assert response["code"] != 0, response
    assert repo.state["review_handoffs"] == []


def test_saved_draft_survives_sqlite_repository_reload(tmp_path, monkeypatch):
    from libs.db.repository import InMemoryRepository

    monkeypatch.setenv("AICHECK_SQLITE_DISABLE", "false")
    path = tmp_path / "handoff.sqlite3"
    try:
        repo.configure_sqlite(path)
        repo.flush_to_sqlite()
        result = client.post(f"/api/projects/{PROJECT}/review-handoffs", headers=HEADERS, json=payload()).json()
        assert result["code"] == 0, result
        restored = InMemoryRepository(seed=False)
        restored.configure_sqlite(path)
        restored.load_from_sqlite(selected_state_keys={"review_handoffs"}, tenant_id="TENANT-DEFAULT")
        assert restored.find_one("review_handoffs", result["data"]["id"]) == result["data"]
    finally:
        repo.sqlite_enabled = False
        repo.sqlite_path = None


def test_read_and_save_require_both_node_scopes_and_current_document_access():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    saved = client.post(url, headers=HEADERS, json=payload()).json()["data"]
    member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT and row.get("userId") == HEADERS["X-User-Id"])
    before = deepcopy(repo.state["review_handoffs"])
    original_scope = member.get("nodeScope")
    member["nodeScope"] = [24]
    for response in (client.get(f"{url}/{saved['id']}", headers=HEADERS), client.post(url, headers=HEADERS, json=payload())):
        assert response.json()["code"] != 0, response.text
    member["nodeScope"] = original_scope
    repo.find_one("review_runs", "SOURCE")["inputDocumentVersionIds"] = ["UNAVAILABLE"]
    response = client.get(f"{url}/{saved['id']}", headers=HEADERS)
    assert response.json()["code"] != 0, response.text
    assert repo.state["review_handoffs"] == before


def test_list_filters_permissions_before_pagination_and_supports_run_filters():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    visible_ids = set()
    for weld in ("W-1", "W-2"):
        body = payload()
        body["subject"]["objectId"] = weld
        response = client.post(url, headers=HEADERS, json=body).json()
        assert response["code"] == 0, response
        visible_ids.add(response["data"]["id"])
    other = run_for(36)
    other.update(id="TARGET-OTHER", projectId=PROJECT, tenantId="TENANT-DEFAULT", inputHash="other", inputDocumentVersionIds=[])
    repo.state["review_runs"].append(other)
    response = client.post(url, headers=HEADERS, json={**payload(), "targetRunId": "TARGET-OTHER"}).json()
    assert response["code"] == 0, response
    member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT and row.get("userId") == HEADERS["X-User-Id"])
    member["nodeScope"] = [24, 35]
    pages = [client.get(url, headers=HEADERS, params={"page": page, "pageSize": 1}).json()["data"] for page in (1, 2, 3)]
    assert [page["total"] for page in pages] == [2, 2, 2]
    assert {row["id"] for page in pages for row in page["items"]} == visible_ids
    assert pages[2]["items"] == []
    for filters, count in (({"sourceRunId": "SOURCE"}, 2), ({"targetRunId": "TARGET"}, 2), ({"targetRunId": "TARGET-OTHER"}, 0), ({"sourceRunId": "UNKNOWN"}, 0)):
        result = client.get(url, headers=HEADERS, params=filters).json()["data"]
        assert result["total"] == count
    invalid = client.get(url, headers=HEADERS, params={"pageSize": 101}).json()
    assert invalid["code"] != 0 and invalid["data"]["reason"] == "VALIDATION_ERROR", invalid


def test_removed_source_input_does_not_bypass_frozen_document_read_permission():
    version_id = "HANDOFF-SENSITIVE-VERSION"
    document = {"id": "HANDOFF-SENSITIVE", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT",
                "currentVersionId": version_id, "fileName": "sensitive.pdf"}
    repo.state["documents"].append(document)
    repo.state["versions"].append({"id": version_id, "documentId": document["id"], "tenantId": "TENANT-DEFAULT"})
    source = repo.find_one("review_runs", "SOURCE")
    source["inputDocumentVersionIds"] = [version_id]
    url = f"/api/projects/{PROJECT}/review-handoffs"
    result = client.post(url, headers=HEADERS, json=payload()).json()
    assert result["code"] == 0, result
    record = result["data"]
    assert record["draft"]["source"]["documentVersionIds"] == [version_id]
    source["inputDocumentVersionIds"] = []
    document["tenantId"] = "TENANT-OTHER"
    assert client.get(f"{url}/{record['id']}", headers=HEADERS).json()["code"] != 0
    assert client.get(url, headers=HEADERS).json()["data"]["total"] == 0
    assert repo.find_one("review_handoffs", record["id"]) == record


@pytest.mark.parametrize("case,expected", [("located", "page_located"), ("missing", "page_unavailable"),
    ("tenant", "parse_unavailable"), ("version", "parse_unavailable"), ("duplicate", "parse_ambiguous"),
    ("pages", "page_ambiguous"), ("boolean", "page_unavailable"), ("absent", "parse_unavailable")])
def test_evidence_location_read_checks(case, expected):
    version = "HANDOFF-V1"
    repo.state["documents"].append({"id": "HANDOFF-D", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT", "currentVersionId": version})
    repo.state["versions"].append({"id": version, "documentId": "HANDOFF-D", "tenantId": "TENANT-DEFAULT"})
    repo.find_one("review_runs", "SOURCE")["inputDocumentVersionIds"] = [version]
    parse = {"id": "PARSE", "documentVersionId": version, "tenantId": "TENANT-DEFAULT", "pages": [{"pageNo": 1, "text": "original"}]}
    if case == "missing":
        parse["pages"] = [{"pageNo": 2}]
    elif case == "boolean":
        parse["pages"] = [{"pageNo": True}]
    elif case == "tenant":
        parse["tenantId"] = "OTHER"
    elif case == "version":
        parse["documentVersionId"] = "OTHER"
    elif case == "pages":
        parse["pages"].append({"pageNo": 1})
    repo.state["ocr_parse_results"] = [] if case == "absent" else [parse]
    if case == "duplicate":
        repo.state["ocr_parse_results"].append({**parse, "id": "SECOND"})
    url = f"/api/projects/{PROJECT}/review-handoffs"
    result = client.post(url, headers=HEADERS, json={**payload(), "kind": "facts", "evidenceRefs": [{"documentVersionId": version, "pageNo": 1}]}).json()
    assert result["code"] == 0, result
    record = result["data"]
    detail_url = f"{url}/{record['id']}"
    view = client.get(detail_url, headers=HEADERS).json()["data"]
    check = view["validation"]["evidenceLocationCheck"]
    assert check["items"][0]["status"] == expected
    assert check["authoritative"] is False and check["contentSupportStatus"] == "unverified"
    assert view["draft"]["evidenceVerificationStatus"] == "unverified"
    assert client.get(url, headers=HEADERS).json()["data"]["items"][0]["validation"] == view["validation"]
    if case == "located":
        parse["pages"][0]["text"] = "changed"
        updated = client.get(detail_url, headers=HEADERS).json()["data"]
        assert updated["validation"]["evidenceLocationCheck"]["items"][0]["parseFingerprint"] != check["items"][0]["parseFingerprint"]
    assert repo.find_one("review_handoffs", record["id"]) == record
    repo.find_one("review_runs", "SOURCE")["inputHash"] = "CHANGED"
    assert "evidenceLocationCheck" not in client.get(detail_url, headers=HEADERS).json()["data"]["validation"]


def test_pipeline_failure_report_is_saved_and_requires_frozen_access(monkeypatch, tmp_path):
    from libs.review_orchestrator import execution
    from libs.review_orchestrator.pipeline_facts import PipelineFactsConflict

    version = "CONFLICT-V1"
    document = {"id": "CONFLICT-D", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT", "currentVersionId": version}
    repo.state["documents"].append(document)
    repo.state["versions"].append({"id": version, "documentId": document["id"], "tenantId": "TENANT-DEFAULT"})
    run = repo.find_one("review_runs", "SOURCE")
    run.update(reviewRunId="SOURCE", status="queued", advisoryOnly=True, inputDocumentVersionIds=[version])
    conflicts = [{"pipelineId": "PL-1", "field": "designPressureMPa", "sources": [
        {"value": 1.6, "source": {"documentVersionId": version, "pageNo": 2}},
        {"value": 2.5, "source": {"documentVersionId": version, "pageNo": 3}},
    ]}]

    def fail_graph(*args, **kwargs):
        raise PipelineFactsConflict(conflicts)

    monkeypatch.setattr("libs.review_orchestrator.graph.execute_review_graph", fail_graph)
    result = execution.execute_review_run_inline("SOURCE")
    assert result["status"] == "failed", result
    assert result["errorCode"] == "REVIEW_PIPELINE_FACTS_CONFLICT" and not result["retryable"]
    report = deepcopy(run["pipelineConflictReport"])
    assert report["conflicts"] == conflicts and report["inputHash"] == run["inputHash"]
    conflicts[0]["sources"][0]["value"] = 999
    assert run["pipelineConflictReport"] == report
    assert "pipelineConflictReport" not in execution.review_run_view(run)
    from libs.db.repository import InMemoryRepository

    monkeypatch.setenv("AICHECK_SQLITE_DISABLE", "false")
    path = tmp_path / "pipeline-report.sqlite3"
    try:
        repo.configure_sqlite(path)
        repo.flush_to_sqlite()
        restored = InMemoryRepository(seed=False)
        restored.configure_sqlite(path)
        restored.load_from_sqlite(selected_state_keys={"review_runs"}, tenant_id="TENANT-DEFAULT")
        assert restored.find_one("review_runs", "SOURCE")["pipelineConflictReport"] == report
    finally:
        repo.sqlite_enabled = False
        repo.sqlite_path = None
    url = f"/api/projects/{PROJECT}/review-runs/SOURCE/pipeline-conflicts"
    response = client.get(url, headers=HEADERS).json()
    assert response["code"] == 0, response
    assert response["data"] == {"report": report, "historical": True, "authoritative": False}
    run["inputDocumentVersionIds"] = []
    document["tenantId"] = "OTHER"
    assert client.get(url, headers=HEADERS).json()["code"] != 0
    assert run["pipelineConflictReport"] == report


@pytest.mark.parametrize("case", ["missing", "tenant", "node", "run", "versions", "role", "disabled"])
def test_pipeline_report_identity_and_access(case, monkeypatch):
    report = {"schemaVersion": "pipeline-conflict-report-v1", "reviewRunId": "SOURCE", "projectId": PROJECT,
              "tenantId": "TENANT-DEFAULT", "nodeId": 24, "documentVersionIds": [], "conflicts": []}
    run = repo.find_one("review_runs", "SOURCE")
    run["pipelineConflictReport"] = report
    headers = HEADERS
    if case == "missing":
        run.pop("pipelineConflictReport")
    elif case == "tenant":
        report["tenantId"] = "OTHER"
    elif case == "node":
        report["nodeId"] = 35
    elif case == "run":
        report["reviewRunId"] = "TARGET"
    elif case == "versions":
        report.pop("documentVersionIds")
    elif case == "role":
        headers = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
    elif case == "disabled":
        monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    assert client.get(f"/api/projects/{PROJECT}/review-runs/SOURCE/pipeline-conflicts", headers=headers).json()["code"] != 0


def test_handoff_idempotency_replays_and_rejects_changed_body_or_snapshot():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    headers = {**HEADERS, "Idempotency-Key": "handoff-request-1"}
    first = client.post(url, headers=headers, json=payload()).json()
    assert first["code"] == 0, first
    assert client.post(url, headers=headers, json=payload()).json()["data"] == first["data"]
    changed = {**payload(), "payload": {"request": "different"}}
    assert client.post(url, headers=headers, json=changed).json()["code"] != 0
    repo.find_one("review_runs", "SOURCE")["inputHash"] = "CHANGED"
    assert client.post(url, headers=headers, json=payload()).json()["code"] != 0
    assert len(repo.state["review_handoffs"]) == 1


def test_handoff_cached_replay_checks_original_document_access_and_lab_flag(monkeypatch):
    version = "REPLAY-V1"
    doc = {"id": "REPLAY-D", "projectId": PROJECT, "tenantId": "TENANT-DEFAULT", "currentVersionId": version}
    repo.state["documents"].append(doc)
    repo.state["versions"].append({"id": version, "documentId": doc["id"], "tenantId": "TENANT-DEFAULT"})
    repo.find_one("review_runs", "SOURCE")["inputDocumentVersionIds"] = [version]
    url = f"/api/projects/{PROJECT}/review-handoffs"
    headers = {**HEADERS, "Idempotency-Key": "guarded-replay"}
    assert client.post(url, headers=headers, json=payload()).json()["code"] == 0
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    assert client.post(url, headers=headers, json=payload()).json()["code"] != 0
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    doc["tenantId"] = "OTHER"
    repo.find_one("review_runs", "SOURCE")["inputDocumentVersionIds"] = []
    assert client.post(url, headers=headers, json=payload()).json()["code"] != 0
    assert len(repo.state["review_handoffs"]) == 1


@pytest.mark.parametrize("endpoint", ["SOURCE", "TARGET"])
@pytest.mark.parametrize("change", ["ocr", "correction"])
def test_frozen_endpoint_source_changes_invalidate_read_save_and_replay(endpoint, change):
    from libs.review_document_scope import freeze_document_scope

    version = "FROZEN-HANDOFF-V1"
    repo.state["documents"].append({"id": "FROZEN-HANDOFF-D", "projectId": PROJECT,
                                   "tenantId": "TENANT-DEFAULT", "currentVersionId": version})
    repo.state["versions"].append({"id": version, "documentId": "FROZEN-HANDOFF-D",
                                  "tenantId": "TENANT-DEFAULT"})
    parse = {"id": "FROZEN-PARSE", "documentVersionId": version, "tenantId": "TENANT-DEFAULT",
             "pages": [{"pageNo": 1, "text": "original"}]}
    repo.state["ocr_parse_results"] = [parse]
    selected = repo.find_one("review_runs", endpoint)
    selected["inputDocumentVersionIds"] = [version]
    for run_id in ("SOURCE", "TARGET"):
        run = repo.find_one("review_runs", run_id)
        run["documentScopeSnapshot"] = freeze_document_scope(run, repo.state)
    url = f"/api/projects/{PROJECT}/review-handoffs"
    headers = {**HEADERS, "Idempotency-Key": "frozen-source-request"}
    saved = client.post(url, headers=headers, json=payload()).json()
    assert saved["code"] == 0, saved
    record = saved["data"]
    detail_url = f"{url}/{record['id']}"
    initial = client.get(detail_url, headers=HEADERS).json()["data"]
    assert initial["validation"]["inputSourceCheck"]["status"] == "current"
    runs_before = deepcopy(repo.state["review_runs"])
    if change == "ocr":
        parse["pages"][0]["text"] = "changed"
    else:
        repo.state.setdefault("fact_corrections", []).append({
            "id": "CORRECTION", "projectId": PROJECT, "nodeId": selected["nodeId"],
            "documentVersionId": version, "status": "active", "fieldId": "field", "value": "changed",
        })
    detail = client.get(detail_url, headers=HEADERS).json()["data"]
    validation = detail["validation"]
    assert validation["status"] == "stale_or_invalid"
    assert "evidenceLocationCheck" not in validation
    check = validation["inputSourceCheck"]
    assert check["requiresRevalidation"] and check["affectedTargetRunId"] == "TARGET"
    changed = [row for row in check["endpoints"] if row["status"] == "stale_or_invalid"]
    assert [row["endpoint"] for row in changed] == [endpoint.lower()]
    assert client.get(url, headers=HEADERS).json()["data"]["items"][0]["validation"] == validation
    assert client.post(url, headers=HEADERS, json=payload()).json()["code"] != 0
    assert client.post(url, headers=headers, json=payload()).json()["code"] != 0
    assert repo.state["review_runs"] == runs_before
    assert repo.state["review_handoffs"] == [record]


def test_legacy_handoff_source_freshness_is_explicitly_unverified():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    saved = client.post(url, headers=HEADERS, json=payload()).json()["data"]
    check = client.get(f"{url}/{saved['id']}", headers=HEADERS).json()["data"]["validation"]["inputSourceCheck"]
    assert check["status"] == "unverified"
    assert not check["requiresRevalidation"]
    assert check["authoritative"] is False


def test_unselected_ocr_and_other_node_corrections_do_not_invalidate_handoff():
    from libs.review_document_scope import freeze_document_scope

    for run_id in ("SOURCE", "TARGET"):
        run = repo.find_one("review_runs", run_id)
        run["documentScopeSnapshot"] = freeze_document_scope(run, repo.state)
    url = f"/api/projects/{PROJECT}/review-handoffs"
    saved = client.post(url, headers=HEADERS, json=payload()).json()["data"]
    repo.state["ocr_parse_results"].append({"documentVersionId": "UNSELECTED", "pages": [{"pageNo": 1}]})
    repo.state.setdefault("fact_corrections", []).append({
        "projectId": "OTHER", "nodeId": 1, "documentVersionId": "UNSELECTED",
        "status": "active", "fieldId": "field", "value": "changed",
    })
    check = client.get(f"{url}/{saved['id']}", headers=HEADERS).json()["data"]["validation"]["inputSourceCheck"]
    assert check["status"] == "current"


def test_event_bound_handoffs_deduplicate_only_within_same_event():
    url = f"/api/projects/{PROJECT}/review-handoffs"
    first_body = payload()
    first = client.post(url, headers=HEADERS, json=first_body).json()["data"]
    assert first["draft"]["schemaVersion"] == "review-handoff-draft-v2"
    second_body = deepcopy(first_body)
    second_body["subject"]["eventId"] = "EVENT-2"
    second = client.post(url, headers=HEADERS, json=second_body).json()["data"]
    assert first["id"] != second["id"]
    assert client.post(url, headers=HEADERS, json=first_body).json()["data"]["id"] == first["id"]
    assert client.get(url, headers=HEADERS).json()["data"]["total"] == 2
    for event, identity in (("EVENT-1", first["id"]), ("EVENT-2", second["id"])):
        filtered = client.get(url, headers=HEADERS, params={"eventId": event}).json()["data"]
        assert filtered["total"] == 1 and filtered["items"][0]["id"] == identity
    assert client.get(url, headers=HEADERS, params={"eventId": "UNKNOWN"}).json()["data"]["total"] == 0
    missing = deepcopy(first_body)
    missing["subject"].pop("eventId")
    assert client.post(url, headers=HEADERS, json=missing).json()["code"] != 0
    assert len(repo.state["review_handoffs"]) == 2
