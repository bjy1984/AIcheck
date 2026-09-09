from __future__ import annotations

import json

import fitz
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.integrations import task_dispatcher
from libs.review_orchestrator.execution import (
    create_review_run_from_ai_run,
    review_run_state_records,
)

client = TestClient(app)


def test_real_route_carries_page_scope_to_ai_run_and_evidence_package(monkeypatch, tmp_path):
    from apps.api import routes

    _allow_dispatch(monkeypatch)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    monkeypatch.setenv("AICHECK_REVIEW_PAGE_RANGES_ENABLED", "true")
    version_id = _mount_ocr_document(document_id_hint="PAGES", file_name="fixed-pages.pdf",
                                     material_type_code="design_license", quoted_text="OUTSIDE-PAGE-ONE")
    version = repo.find_one("versions", version_id)
    version["hash"] = "test-uploaded-body"
    path = tmp_path / "fixed-pages.pdf"
    with fitz.open() as pdf:
        for _ in range(3):
            pdf.new_page()
        pdf.save(path)
    monkeypatch.setattr(routes, "local_storage_path", lambda key: path)
    body = {"reviewMode": "gap_precheck", "auditInputMode": "ocr_llm", "inputDocumentVersionIds": [version_id],
            "inputDocumentPageRanges": {version_id: {"start": 2, "end": 3}}}
    response = client.post(f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck", json=body)
    run = _assert_ok(response)["latestRun"]
    assert run["inputDocumentPageRanges"] == body["inputDocumentPageRanges"]
    assert run["evidenceLinks"] == []
    snapshots = [row for row in repo.state["evidence_snapshots"] if row.get("aiRunId") == run["id"]]
    assert snapshots[0]["documentPageRanges"] == run["inputDocumentPageRanges"]
    shards = [row for row in repo.state["evidence_shards"] if row.get("aiRunId") == run["id"]]
    assert "OUTSIDE-PAGE-ONE" not in json.dumps(shards)
    count = len(repo.state["ai_runs"])
    body["inputDocumentPageRanges"][version_id]["end"] = 4
    rejected = client.post(f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck", json=body).json()
    assert rejected["code"] != 0
    assert len(repo.state["ai_runs"]) == count


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def _assert_ok(response) -> dict:
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


def _mount_ocr_document(
    *,
    document_id_hint: str,
    file_name: str,
    material_type_code: str,
    quoted_text: str,
) -> str:
    document, version = repo.create_document(
        PROJECT_ID,
        file_name,
        "application/pdf",
        material_category="资质证照" if material_type_code == "design_license" else "设计文件",
    )
    document["materialTypeCode"] = material_type_code
    parse_result = {
        "status": "success",
        "documentType": material_type_code,
        "fileName": file_name,
        "artifactHash": f"sha256:{document_id_hint.lower()}",
        "fields": [
            {
                "fieldName": "OCR全文",
                "fieldValue": quoted_text,
                "pageNo": 1,
                "bbox": [10, 20, 500, 80],
                "confidence": 0.96,
            }
        ],
        "fragments": [
            {
                "id": f"FRAG-{document_id_hint}",
                "pageNo": 1,
                "text": quoted_text,
                "bbox": [10, 20, 500, 80],
                "confidence": 0.96,
            }
        ],
        "tables": [],
        "seals": [],
    }
    repo.apply_ocr_result(document["id"], version["id"], parse_result)
    repo.state["node_evidence_links"].append(
        {
            "id": f"NEL-{document_id_hint}",
            "projectId": PROJECT_ID,
            "nodeId": 1,
            "nodeName": "设计单位许可资质",
            "reviewPointId": f"REQ-{document_id_hint}",
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "fileName": file_name,
            "materialTypeCode": material_type_code,
            "materialTypeName": file_name,
            "requiredType": "必传",
            "supportStatus": "命中",
            "confidence": 0.96,
            "matchedEvidenceItems": [quoted_text],
            "manualStatus": "confirmed",
            "revision": 1,
            "source": "test",
        }
    )
    return version["id"]


def _allow_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        task_dispatcher,
        "ai_recheck_dispatch_readiness",
        lambda: {"ready": True, "mode": "test", "statusReason": "test_dispatch"},
    )
    monkeypatch.setattr(
        task_dispatcher,
        "dispatch_ai_recheck",
        lambda project_id, node_id, run_id, **_kwargs: {"mode": "test", "taskId": f"TEST-{run_id}"},
    )


def test_later_upload_review_run_uses_all_current_node_documents(monkeypatch) -> None:
    _allow_dispatch(monkeypatch)
    license_version = _mount_ocr_document(
        document_id_hint="LICENSE",
        file_name="设计许可证.pdf",
        material_type_code="design_license",
        quoted_text="许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
    )

    first = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={"reviewMode": "gap_precheck"},
        )
    )["latestRun"]

    drawing_version = _mount_ocr_document(
        document_id_hint="DRAWING",
        file_name="施工图.pdf",
        material_type_code="design_document",
        quoted_text="设计单位广东政和工程有限公司，压力管道级别GC2。",
    )
    second = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={"reviewMode": "gap_precheck"},
        )
    )["latestRun"]

    assert first["evidenceSnapshotHash"] != second["evidenceSnapshotHash"]
    assert first["inputDocumentVersionIds"] == [license_version]
    assert second["inputDocumentVersionIds"] == sorted([license_version, drawing_version])
    assert second["evidenceManifestId"]
    assert second["evidenceShardIds"]
    assert second["evidenceCoverage"]["structuralCoveragePassed"] is True
    assert second["evidenceCoverage"]["processingCoveragePassed"] is False
    assert second["evidenceCoverage"]["coveragePassed"] is False


def test_review_run_copies_and_flushes_the_persisted_evidence_package(monkeypatch) -> None:
    _allow_dispatch(monkeypatch)
    _mount_ocr_document(
        document_id_hint="LICENSE",
        file_name="设计许可证.pdf",
        material_type_code="design_license",
        quoted_text="许可证编号TS1844171-2028，工业管道GC1覆盖GC2。",
    )
    ai_run = _assert_ok(
        client.post(
            f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck",
            json={
                "reviewMode": "gap_precheck",
                "projectReviewRunId": "PRRUN-PARENT-1",
                "triggerType": "manual_full",
                "autoReviewPolicyRevision": 3,
            },
        )
    )["latestRun"]

    review_run = create_review_run_from_ai_run(ai_run, mode="inline")
    records = review_run_state_records(review_run["reviewRunId"])

    assert review_run["evidenceSnapshotId"] == ai_run["evidenceSnapshotId"]
    assert review_run["evidenceManifestId"] == ai_run["evidenceManifestId"]
    assert review_run["evidenceShardIds"] == ai_run["evidenceShardIds"]
    assert review_run["projectReviewRunId"] == "PRRUN-PARENT-1"
    assert review_run["triggerType"] == "manual_full"
    assert review_run["autoReviewPolicyRevision"] == 3
    assert records["evidence_snapshots"][0]["reviewRunId"] == review_run["reviewRunId"]
    assert records["evidence_manifests"][0]["reviewRunId"] == review_run["reviewRunId"]
    assert records["evidence_shards"]
    assert all(
        row["reviewRunId"] == review_run["reviewRunId"]
        for row in records["evidence_shards"]
    )


def test_real_route_freezes_confirmed_mapping_and_executes_selected_source(monkeypatch):
    from copy import deepcopy

    from apps.api import routes
    from libs.business_pack import load_business_pack
    from libs.review_condition_facts import condition_candidates_from_run
    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator import execution
    from libs.review_tools.condition_execution import prepare_condition_results

    _allow_dispatch(monkeypatch)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    version_id = _mount_ocr_document(document_id_hint="MAPPING", file_name="mapping.pdf",
                                    material_type_code="design_license", quoted_text="source")
    repo.find_one("versions", version_id)["hash"] = "uploaded-mapping"
    parse = {"id": "PARSE-MAPPING", "tenantId": "TENANT-DEFAULT", "documentVersionId": version_id, "fields": []}
    repo.state["ocr_parse_results"].append(parse)
    parse["fields"].extend([
        {"id": "SELECTED", "fieldName": "thickness", "value": 12, "pageNo": 1, "bbox": [0, 0, 10, 10]},
        {"id": "OTHER", "fieldName": "thickness", "value": 3, "pageNo": 1, "bbox": [20, 0, 30, 10]},
    ])
    pack = load_business_pack("engineering_inspection_v1")
    atomic = next(row["id"] for row in pack["atomicChecks"] if row["nodeId"] == 1)
    rule = {"id": "RULE-MAPPING", "projectId": PROJECT_ID, "revision": 1, "version": "test-v1", "status": "已发布",
            "businessPackId": pack["id"], "nodeIds": [1], "executionConditions": {"schemaVersion": "rule-conditions-v1", "checks": [
                {"id": "C", "atomicCheckId": atomic, "field": "thickness", "operator": "gte", "expected": 10}]}}
    monkeypatch.setattr(routes, "current_published_rule_for_node", lambda *args, **kwargs: rule)
    monkeypatch.setattr(execution, "current_published_rule_for_node", lambda *args, **kwargs: rule)
    source = {"projectId": PROJECT_ID, "nodeId": 1, "businessPackId": pack["id"], "inputDocumentVersionIds": [version_id]}
    source["documentScopeSnapshot"] = freeze_document_scope(source, repo.state)
    candidates = condition_candidates_from_run(repo.state, source, rule["executionConditions"])
    mapping = {"ruleVersionId": rule["id"], "ruleRevision": 1, "sourceSnapshotHash": source["documentScopeSnapshot"]["snapshotHash"],
               "selection": {"subject": {"objectType": "weld", "objectId": "W1"}, "confirmedSameObject": True,
                             "fields": {"thickness": candidates["thickness"][0]["candidateId"]}}}
    body = {"reviewMode": "gap_precheck", "auditInputMode": "ocr_llm", "inputDocumentVersionIds": [version_id], "conditionObjectMapping": mapping}
    response = _assert_ok(client.post(f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck", json=body))
    ai_run = repo.find_one("ai_runs", response["latestRun"]["id"])
    assert ai_run["conditionObjectMapping"] == mapping
    run = create_review_run_from_ai_run(ai_run, mode="inline")
    assert run["conditionObjectMappingSnapshot"]["selection"] == mapping["selection"]
    result = prepare_condition_results(repo.state, run, pack)[atomic]
    assert result["result"] == "passed"
    assert result["toolResults"][0]["evidenceRefs"][0]["fieldId"] == "SELECTED"
    before = len(repo.state["ai_runs"])
    changed = deepcopy(body)
    changed["conditionObjectMapping"]["ruleRevision"] = 2
    assert client.post(f"/projects/{PROJECT_ID}/inspection/nodes/1/ai-recheck", json=changed).json()["code"] != 0
    assert len(repo.state["ai_runs"]) == before


def test_real_route_uses_verified_handoff_and_rejects_changed_verification(monkeypatch):
    from copy import deepcopy

    from test_review_workstations import run_for

    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator import execution
    from libs.review_rule_snapshot import freeze_effective_rule

    _allow_dispatch(monkeypatch)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    headers = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
    version_id = _mount_ocr_document(document_id_hint="HANDOFF", file_name="handoff.pdf",
                                    material_type_code="design_license", quoted_text="焊口W1交接原文")
    repo.find_one("versions", version_id)["hash"] = "uploaded-handoff"
    repo.state["ocr_parse_results"].append({"id": "HANDOFF-PARSE", "tenantId": "TENANT-DEFAULT",
        "documentVersionId": version_id, "pages": [{"pageNo": 1, "text": "焊口W1交接原文"}]})
    for node, name in ((24, "HANDOFF-SOURCE"), (35, "HANDOFF-TARGET")):
        run = run_for(node)
        run.update(id=name, reviewRunId=name, projectId=PROJECT_ID, tenantId="TENANT-DEFAULT", inputHash=name,
                   inputDocumentVersionIds=[version_id], status="completed", outputHash="OUTPUT")
        run["documentScopeSnapshot"] = freeze_document_scope(run, repo.state)
        run["effectiveRuleSnapshot"] = freeze_effective_rule(run, {"id": f"RULE-{node}", "version": "1"})
        repo.state["review_runs"].append(run)
    subject = {"objectType": "weld", "objectId": "W1", "eventId": "EV1", "repairRound": 0}
    base = f"/api/projects/{PROJECT_ID}/review-handoffs"
    record = _assert_ok(client.post(base, headers=headers, json={"sourceRunId": "HANDOFF-SOURCE", "targetRunId": "HANDOFF-TARGET",
        "kind": "facts", "subject": subject, "payload": {"observation": "已核对焊口W1资料"},
        "evidenceRefs": [{"documentVersionId": version_id, "pageNo": 1}]}))
    decision = {"snapshotHash": record["draft"]["snapshotHash"], "expectedPreviousId": None, "subject": subject,
        "outcome": "verified", "objectMatchConfirmed": True, "evidenceSupportConfirmed": True, "note": "人工核验示例"}
    verified = _assert_ok(client.post(f"{base}/{record['id']}/verifications", headers=headers, json=decision))
    selection = {"subject": subject, "confirmedSameObject": True, "items": [{"handoffId": record["id"], "verificationId": verified["verifications"][-1]["id"]}]}
    body = {"reviewMode": "gap_precheck", "auditInputMode": "ocr_llm", "inputDocumentVersionIds": [version_id], "handoffSelection": selection}
    path = f"/projects/{PROJECT_ID}/inspection/nodes/35/ai-recheck"
    ai_run = _assert_ok(client.post(path, headers=headers, json=body))["latestRun"]
    assert ai_run["handoffSelection"] == selection
    run = execution.create_review_run_from_ai_run(ai_run, mode="inline")
    parts = execution.build_review_prompt_parts(run, {})
    assert parts["userPayload"]["verifiedHandoffs"][0]["handoffId"] == record["id"]
    dependency_path = f"/api/projects/{PROJECT_ID}/review-runs/{run['reviewRunId']}/handoff-dependencies"
    assert _assert_ok(client.get(dependency_path, headers=headers))["status"] == "current"
    listed = _assert_ok(client.get(base, headers=headers, params={"targetRunId": run["reviewRunId"]}))
    assert [item["id"] for item in listed["items"]] == [record["id"]]
    detail = _assert_ok(client.get(f"{base}/{record['id']}", headers=headers, params={"contextRunId": run["reviewRunId"]}))
    assert detail["readContext"] == {"runId": run["reviewRunId"], "relation": "used_input"}
    assert detail["draft"]["target"]["runId"] == "HANDOFF-TARGET"
    assert client.get(f"{base}/{record['id']}", headers=headers, params={"contextRunId": "HANDOFF-SOURCE"}).json()["code"] != 0

    # The workbench summary must follow live dependencies without rerunning or rewriting history.
    summary_path = f"/api/projects/{PROJECT_ID}/review-handoff-node-statuses"
    repo.state.setdefault("review_sessions", []).append({
        "id": "HANDOFF-TRANSITION-SESSION", "projectId": PROJECT_ID, "nodeId": 35,
        "tenantId": "TENANT-DEFAULT", "createdBy": headers["X-User-Id"],
        "status": "active", "activeReviewRunId": run["reviewRunId"],
    })
    before = deepcopy(run)
    task_count = len(repo.state["ai_runs"])

    def assert_summary(expected_status, expected_count):
        summary = _assert_ok(client.get(summary_path, headers=headers))
        row = next(item for item in summary["items"] if item["nodeId"] == 35)
        assert row["reviewRunId"] == run["reviewRunId"]
        assert row["status"] == expected_status
        assert summary["requiresRevalidationCount"] == expected_count
        assert summary["automaticRerun"] is False
        assert len(repo.state["ai_runs"]) == task_count
        assert run == before

    assert_summary("current", 0)
    source = repo.find_one("review_runs", "HANDOFF-SOURCE")
    original_hash = source["inputHash"]
    source["inputHash"] = "UPSTREAM-CHANGED"
    assert_summary("requires_revalidation", 1)
    source["inputHash"] = original_hash
    assert_summary("current", 0)
    decision.update(expectedPreviousId=verified["verifications"][-1]["id"], outcome="rejected", note="重新核验不匹配")
    _assert_ok(client.post(f"{base}/{record['id']}/verifications", headers=headers, json=decision))
    assert _assert_ok(client.get(dependency_path, headers=headers))["requiresRevalidation"] is True
    stale_detail = _assert_ok(client.get(f"{base}/{record['id']}", headers=headers, params={"contextRunId": run["reviewRunId"]}))
    assert stale_detail["verification"]["status"] == "rejected"
    assert_summary("requires_revalidation", 1)
    member = next(row for row in repo.state["project_members"] if row.get("projectId") == PROJECT_ID and row.get("userId") == headers["X-User-Id"])
    previous_scope = member.get("nodeScope")
    member["nodeScope"] = [35]
    assert client.get(f"{base}/{record['id']}", headers=headers, params={"contextRunId": run["reviewRunId"]}).json()["code"] != 0
    member["nodeScope"] = previous_scope

    count = len(repo.state["ai_runs"])
    assert client.post(path, headers=headers, json=body).json()["code"] != 0
    assert len(repo.state["ai_runs"]) == count
    assert run == before
