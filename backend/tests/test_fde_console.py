from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import fde_ocr_100_action_handoff_snapshot
from libs.db.repository import repo
from libs.db.seed import STANDARD_RULES_SOURCE_ID


client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


def assert_error(response, reason: str):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == reason
    return payload


def allow_published_test_bindings(monkeypatch) -> None:
    from libs.business_pack import load_business_pack

    pack = load_business_pack("engineering_inspection_v1")
    monkeypatch.setitem(pack["atomicCheckToolBindingSet"], "lifecycleStatus", "published")


def seed_confirmed_node_24_evidence(project_id: str = "P-2026-HDCP-001") -> None:
    from libs.material_targeting import review_points_for_project

    project = repo.require_project(project_id)
    points = [
        point
        for point in review_points_for_project(repo, project, node_id=24)
        if point.get("requiredType") != "可选"
    ]
    for index, point in enumerate(points, start=1):
        link_id = f"NEL-FDE-TEST-24-{index}"
        if repo.find_one("node_evidence_links", link_id):
            continue
        is_certificate = point.get("materialTypeCode") == "welder_certificate"
        repo.state["node_evidence_links"].append(
            {
                "id": link_id,
                "projectId": project_id,
                "nodeId": 24,
                "nodeName": point.get("nodeName"),
                "reviewPointId": point.get("id"),
                "reviewContent": point.get("reviewContent"),
                "materialTypeCode": point.get("materialTypeCode"),
                "materialTypeName": point.get("materialTypeName"),
                "requiredType": point.get("requiredType"),
                "documentId": "DOC-20260625-001" if is_certificate else "DOC-20260625-002",
                "documentVersionId": "DV-20260625-001-V2" if is_certificate else "DV-20260625-002-V1",
                "fileName": "焊工资格证-王建国.pdf" if is_certificate else "焊工名册.xlsx",
                "pageNo": 1,
                "bbox": [10, 20, 180, 42],
                "fieldName": "证书编号" if is_certificate else "焊工姓名",
                "fieldId": "FIELD-24-001" if is_certificate else None,
                "quotedText": "TS6J-2024-03158" if is_certificate else "王建国 焊工名册",
                "matchedEvidenceItems": ["TS6J-2024-03158"] if is_certificate else ["王建国"],
                "supportStatus": "supported",
                "confidence": 0.96,
                "manualStatus": "confirmed",
                "manualStatusLabel": "已确认",
                "confirmedByName": "张工",
                "confirmedAt": "2026-07-08 00:00:00",
                "source": "test_confirmed_evidence",
                "createdAt": "2026-07-08 00:00:00",
            }
        )


def test_fde_ocr_action_handoff_marks_stale_when_board_summary_changes(tmp_path) -> None:
    handoff_dir = tmp_path / "ocr_100_action_handoff"
    handoff_dir.mkdir()
    collect_csv = handoff_dir / "collect_samples.csv"
    collect_csv.write_text("scenario,missingCases\nndt_rt_profile,1\n", encoding="utf-8")
    manifest = {
        "schemaVersion": "aicheck-ocr-100-action-handoff-v1",
        "generatedAt": "2026-06-30T16:00:00Z",
        "outputDir": str(handoff_dir),
        "summary": {
            "status": "needs_sample_files",
            "score": 79,
            "readyForEval": 0,
            "requiredReadyForEval": 100,
            "collectionMissingCases": 75,
            "actions": 1,
            "laneCounts": {"collect_samples": 1},
        },
        "laneCounts": {"collect_samples": 1},
        "files": {"collectCsv": str(collect_csv)},
    }
    (handoff_dir / "handoff_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = fde_ocr_100_action_handoff_snapshot(
        tmp_path,
        current_summary={
            "status": "needs_sample_files",
            "score": 79.0,
            "readyForEval": 0,
            "requiredReadyForEval": 100,
            "collectionMissingCases": 75,
            "actions": 2,
            "laneCounts": {"collect_samples": 1, "label_existing": 1},
        },
    )

    assert snapshot["ok"] is False
    assert snapshot["status"] == "stale"
    assert {item["field"] for item in snapshot["staleReasons"]} == {"actions", "laneCounts"}
    assert snapshot["files"][0]["exists"] is True


def test_fde_ocr_action_handoff_artifact_download_is_key_scoped() -> None:
    refresh = assert_ok(
        client.post(
            "/api/fde/ocr-100/action-board/refresh",
            json={},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr100-download-001"},
        )
    )
    assert refresh["board"]["handoff"]["status"] == "ready"

    download = client.get(
        "/api/fde/ocr-100/action-board/handoff/collectCsv",
        headers={"X-Role": "fde"},
    )
    assert download.status_code == 200
    assert "text/csv" in download.headers["content-type"]
    assert "priority" in download.text
    assert "scenario" in download.text
    assert "dropDirectory" in download.text

    invalid = client.get(
        "/api/fde/ocr-100/action-board/handoff/../../secret",
        headers={"X-Role": "fde"},
    )
    assert invalid.status_code == 404

    assert_error(
        client.get(
            "/api/fde/ocr-100/action-board/handoff/secret",
            headers={"X-Role": "fde"},
        ),
        "NOT_FOUND",
    )


def test_fde_login_and_dynamic_routes() -> None:
    login = assert_ok(client.post("/api/auth/login", json={"username": "fde", "password": "fde"}))
    routes = assert_ok(client.get("/api/auth/routes?role=fde"))

    assert login["user"]["role"] == "fde"
    assert login["user"]["defaultPath"] == "/fde/dashboard"
    assert [route["path"] for route in routes] == ["/fde"]
    assert routes[0]["redirect"] == "/fde/dashboard"
    assert routes[0]["children"][0]["path"] == "dashboard"
    assert routes[0]["children"][0]["component"] == "views/AICheck/FdeConsole"


def test_fde_dashboard_and_masked_ai_run_detail() -> None:
    dashboard = assert_ok(client.get("/api/fde/dashboard", headers={"X-Role": "fde"}))
    detail = assert_ok(client.get("/api/fde/ai-runs/AIRUN-24-20260625-01", headers={"X-Role": "fde"}))

    assert {item["label"] for item in dashboard["metrics"]} >= {"AI Run", "采纳率", "证据命中率", "误报率", "疑似漏报率"}
    assert detail["run"]["immutable"] is True
    assert detail["run"]["rawAccess"] is False
    assert detail["run"]["inputHash"].startswith("sha256:")
    assert detail["run"]["outputHash"].startswith("sha256:")
    assert detail["run"]["llmAuditAvailable"] is True
    assert "promptAudit" not in detail["run"]
    assert "llmMetadata" not in detail["run"]
    assert detail["traceSteps"]
    assert detail["accessPolicy"]["rawAccessRequiresGrant"] is True
    assert detail["llmAudit"]["runType"] == "ai_run"
    assert detail["llmAudit"]["visibility"] == "masked"
    assert detail["llmAudit"]["inputs"]["systemPrompt"]
    assert detail["llmAudit"]["inputs"]["messagesHash"].startswith("sha256:")
    assert detail["llmAudit"]["outputs"]["resultText"]
    assert detail["llmAudit"]["metadata"]["conversationId"] == "chatcmpl-aicheck-demo-24-001"
    assert "reasoningProcess" not in detail["llmAudit"]["metadata"]
    assert detail["llmAudit"]["reasoning"]["redactionPolicy"] == "audit_summary_only_no_raw_chain_of_thought"
    assert detail["llmAudit"]["reasoning"]["rawChainOfThoughtAvailable"] is False


def test_fde_dashboard_v2_uses_terminal_runs_for_success_rate() -> None:
    before = assert_ok(client.get("/api/fde/dashboard", headers={"X-Role": "fde"}))
    success_metric_before = next(item for item in before["metrics"] if item["key"] == "ai_success_rate")
    repo.state["ai_runs"].append(
        {
            "id": "AIRUN-FDE-RUNNING-001",
            "tenantId": "TENANT-DEFAULT",
            "projectId": "P-2026-HDCP-001",
            "status": "running",
            "createdAt": "2026-07-15 10:00:00",
        }
    )

    dashboard = assert_ok(client.get("/api/fde/dashboard", headers={"X-Role": "fde"}))
    success_metric = next(item for item in dashboard["metrics"] if item["key"] == "ai_success_rate")

    assert dashboard["schemaVersion"] == "FdeDashboard@2.0.0"
    assert dashboard["scope"]["tenantId"] == "TENANT-DEFAULT"
    assert dashboard["totals"]["aiRuns"] == before["totals"]["aiRuns"] + 1
    assert success_metric["denominator"] == success_metric_before["denominator"]
    assert success_metric["sampleSize"] == success_metric["denominator"]
    assert dashboard["freshness"]["stale"] is False
    assert "runStatus" in dashboard
    assert "dataQuality" in dashboard


def test_fde_blockers_include_failed_to_start_and_enforce_tenant_scope() -> None:
    repo.state["review_runs"].extend(
        [
            {
                "id": "RR-FDE-FAILED-START-001",
                "reviewRunId": "RR-FDE-FAILED-START-001",
                "tenantId": "TENANT-DEFAULT",
                "projectId": "P-2026-HDCP-001",
                "status": "failed_to_start",
                "failureReason": "调度器未接受任务",
                "createdAt": "2026-07-15 10:00:00",
            },
            {
                "id": "RR-OTHER-TENANT-001",
                "reviewRunId": "RR-OTHER-TENANT-001",
                "tenantId": "TENANT-OTHER",
                "projectId": "P-OTHER",
                "status": "failed_to_start",
            },
        ]
    )

    blockers = assert_ok(
        client.get(
            "/api/fde/blockers?domain=review-runs&page=1&pageSize=1",
            headers={"X-Role": "fde"},
        )
    )

    assert blockers["page"] == 1
    assert blockers["pageSize"] == 1
    assert blockers["summary"]["filtered"] >= 1
    assert any(item["code"] == "REVIEW_FAILED_TO_START" for item in blockers["items"])
    assert all(item["sourceId"] != "RR-OTHER-TENANT-001" for item in blockers["items"])
    assert blockers["items"][0]["statusTone"] == "danger"


def test_fde_meta_exposes_permission_driven_domains_without_role_mutation() -> None:
    permissions_before = list(repo.role_actions("fde"))
    meta = assert_ok(client.get("/api/fde/meta", headers={"X-Role": "fde"}))

    assert meta["schemaVersion"] == "FdeMeta@1.0.0"
    assert len(meta["capabilities"]) == 14
    assert {item["group"] for item in meta["capabilities"]} == {
        "overview",
        "production",
        "improvement",
        "delivery",
        "operations",
    }
    assert meta["boundaries"]["businessWriteAllowed"] is False
    assert any(item["code"] == "failed_to_start" and item["tone"] == "danger" for item in meta["statusCatalog"])
    assert repo.role_actions("fde") == permissions_before


def test_fde_business_pack_validation_get_is_read_only() -> None:
    installations_before = list(repo.state.get("business_pack_installations", []))
    audits_before = list(repo.state.get("audit_logs", []))

    validation = assert_ok(
        client.get("/api/fde/business-packs/validation", headers={"X-Role": "fde"})
    )

    assert validation["readOnly"] is True
    assert validation["schemaVersion"] == "FdeBusinessPackValidation@1.0.0"
    assert validation["results"]
    assert repo.state.get("business_pack_installations", []) == installations_before
    assert repo.state.get("audit_logs", []) == audits_before


def test_fde_replay_creates_child_run_without_overwriting_parent() -> None:
    parent_before = repo.find_one("ai_runs", "AIRUN-24-20260625-01").copy()
    replay = assert_ok(
        client.post(
            "/api/fde/ai-runs/AIRUN-24-20260625-01/replay",
            json={"runType": "diagnostic_replay", "reason": "验证不可变重跑"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-replay-001"},
        )
    )
    parent_after = repo.find_one("ai_runs", "AIRUN-24-20260625-01")

    assert replay["childRun"]["id"] != "AIRUN-24-20260625-01"
    assert replay["childRun"]["parentRunId"] == "AIRUN-24-20260625-01"
    assert replay["replay"]["runType"] == "diagnostic_replay"
    assert parent_after["status"] == parent_before["status"]
    assert parent_after["suggestion"] == parent_before["suggestion"]


def test_review_run_orchestration_graph_and_human_decision(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    allow_published_test_bindings(monkeypatch)
    seed_confirmed_node_24_evidence()
    ai_run = assert_ok(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            headers={"X-Role": "inspection", "Idempotency-Key": "review-run-inline-001"},
        )
    )

    review_run_id = ai_run["dispatch"]["reviewRunId"]
    business_view = assert_ok(client.get(f"/api/review-runs/{review_run_id}", headers={"X-Role": "inspection"}))
    graph = assert_ok(client.get(f"/api/review-runs/{review_run_id}/graph", headers={"X-Role": "inspection"}))
    timeline = assert_ok(client.get(f"/api/review-runs/{review_run_id}/timeline", headers={"X-Role": "inspection"}))
    decision = assert_ok(
        client.post(
            f"/api/review-runs/{review_run_id}/human-decision",
            json={"decision": "accept", "comment": "证据链完整，人工确认。"},
            headers={
                "X-Role": "inspection",
                "Idempotency-Key": "review-run-decision-001",
                "If-Match": business_view["run"]["etag"],
            },
        )
    )

    assert ai_run["dispatch"]["mode"] == "inline"
    assert business_view["run"]["workflowEngine"] == "inline_temporal_compatible"
    assert business_view["run"]["graphEngine"] in {"langgraph", "langgraph_fallback"}
    assert business_view["run"]["graphRunner"] in {"langgraph", "manual"}
    assert business_view["run"]["modelGateway"] == "qwen_runtime"
    assert business_view["run"]["qualityGate"]["passed"] is True
    assert business_view["run"]["qualityGate"]["metrics"]["status"] == "ready_for_human_review"
    assert len(graph["nodes"]) >= 12
    assert all(node["status"] == "succeeded" for node in graph["nodes"])
    assert graph["artifactSummary"]["toolCalls"] >= 3
    assert graph["artifactSummary"]["ruleCheckResults"] >= 1
    assert graph["artifactSummary"]["retrievalTraces"] >= 1
    assert graph["artifactSummary"]["findingDrafts"] >= 1
    validation_nodes = {
        node["nodeKey"]: node.get("details") or {}
        for node in graph["nodes"]
        if node["nodeKey"] in {"schema_validation", "evidence_validation", "reference_validation", "quality_gate"}
    }
    graph_nodes_by_key = {node["nodeKey"]: node for node in graph["nodes"]}
    assert graph_nodes_by_key["run_rule_engine"]["artifactCounts"]["ruleResults"] >= 1
    assert graph_nodes_by_key["run_rule_engine"]["ruleResults"][0]["linkedClauseIds"]
    assert graph_nodes_by_key["retrieve_knowledge"]["artifactCounts"]["retrievalTraces"] >= 1
    assert graph_nodes_by_key["retrieve_knowledge"]["retrievalTraces"][0]["selectedClauseCount"] >= 1
    assert graph_nodes_by_key["quality_gate"]["validationSummary"]["passed"] is True
    assert validation_nodes["schema_validation"]["checked"] >= 1
    assert "failures" in validation_nodes["evidence_validation"]
    assert validation_nodes["reference_validation"]["metrics"]["ruleResultCount"] >= 1
    assert validation_nodes["quality_gate"]["metrics"]["requiresHumanReview"] is True
    assert len(graph["edges"]) == len(graph["nodes"]) - 1
    assert any(event["eventType"] == "review_run.waiting_human" for event in timeline["events"])
    assert decision["reviewRun"]["status"] == "accepted_by_human"
    assert decision["temporalSignal"]["status"] == "skipped"
    assert any(item.get("reviewRunId") == review_run_id for item in repo.state["review_step_runs"])
    assert any(item.get("reviewRunId") == review_run_id for item in repo.state["review_findings"])
    assert any(item.get("reviewRunId") == review_run_id for item in repo.state["retrieval_traces"])
    assert any(item.get("reviewRunId") == review_run_id for item in repo.state["rule_check_results"])
    assert decision["feedback"]["feedbackType"] == "accepted"
    assert decision["feedback"]["reviewRunId"] == review_run_id
    assert decision["feedback"]["shouldEnterEvaluationSet"] is False
    assert decision["feedback"]["originalAiOutput"]
    trace = next(item for item in repo.state["retrieval_traces"] if item.get("reviewRunId") == review_run_id)
    rule_result = next(item for item in repo.state["rule_check_results"] if item.get("reviewRunId") == review_run_id)
    assert trace["selectedClauses"]
    assert rule_result["linkedClauseIds"]
    assert business_view["run"]["findingDrafts"][0]["kbRefs"][0]["clauseIds"]


def test_review_run_can_call_litellm_and_normalize_structured_findings(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    allow_published_test_bindings(monkeypatch)
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "litellm")
    seed_confirmed_node_24_evidence()

    def fake_chat_sync(self, messages, model="default-chat", **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"findings":[{"findingType":"field_missing","severity":"high",'
                            '"title":"缺少关键字段","description":"报告缺少材料牌号，需人工确认。",'
                            '"confidence":0.91,"suggestedAction":"request_correction"}]}'
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 120},
        }

    monkeypatch.setattr("libs.review_orchestrator.execution.LiteLLMClient.chat_sync", fake_chat_sync)

    ai_run = assert_ok(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            headers={"X-Role": "inspection", "Idempotency-Key": "review-run-litellm-001"},
        )
    )
    review_run_id = ai_run["dispatch"]["reviewRunId"]
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId")
    tool_calls = [
        item
        for item in repo.state["review_tool_calls"]
        if item.get("reviewRunId") == review_run_id and item.get("toolName") == "call_qwen_runtime_chat"
    ]

    assert run["status"] == "waiting_human_review"
    assert run["findingDrafts"][0]["findingType"] == "field_missing"
    assert run["findingDrafts"][0]["severity"] == "high"
    assert run["findingDrafts"][0]["requiresHumanConfirmation"] is True
    assert run["findingDrafts"][0]["llmGenerated"] is True
    assert tool_calls and tool_calls[0]["allowed"] is True


def test_review_run_downgrades_unsupported_structured_litellm_claims(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    allow_published_test_bindings(monkeypatch)
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "litellm")
    seed_confirmed_node_24_evidence()

    def fake_chat_sync(self, messages, model="default-chat", **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"findings":[{"findingType":"ai_review_suggestion","severity":"medium",'
                            '"title":"资格证匹配","description":"焊工王建国证书编号、有效期和持证项目与焊接工艺要求匹配。",'
                            '"confidence":0.94,"suggestedAction":"human_confirm"}]}'
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 118},
        }

    monkeypatch.setattr("libs.review_orchestrator.execution.LiteLLMClient.chat_sync", fake_chat_sync)

    ai_run = assert_ok(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            headers={"X-Role": "inspection", "Idempotency-Key": "review-run-grounding-001"},
        )
    )
    review_run_id = ai_run["dispatch"]["reviewRunId"]
    run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId")
    draft = run["findingDrafts"][0]

    assert run["status"] == "waiting_human_review"
    assert draft["groundingStatus"] == "insufficient_evidence"
    assert draft["unsupportedClaims"]
    assert "证据不足" in draft["title"]
    assert "王建国" not in draft["description"]
    assert draft["confidence"] <= 0.5


def test_fde_review_run_visualization_replay_and_shadow(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    allow_published_test_bindings(monkeypatch)
    seed_confirmed_node_24_evidence()
    ai_run = assert_ok(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            headers={"X-Role": "inspection", "Idempotency-Key": "review-run-fde-001"},
        )
    )
    review_run_id = ai_run["dispatch"]["reviewRunId"]

    page = assert_ok(client.get("/api/fde/review-runs", headers={"X-Role": "fde"}))
    detail = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}", headers={"X-Role": "fde"}))
    graph = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}/graph", headers={"X-Role": "fde"}))
    temporal = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}/temporal-history", headers={"X-Role": "fde"}))
    audit_package = assert_ok(
        client.get(f"/api/fde/review-runs/{review_run_id}/audit-package", headers={"X-Role": "fde"})
    )
    replay = assert_ok(
        client.post(
            f"/api/fde/review-runs/{review_run_id}/replay",
            json={"runMode": "diagnostic_replay", "reason": "验证编排不可变重跑"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-review-replay-001"},
        )
    )
    shadow = assert_ok(
        client.post(
            f"/api/fde/review-runs/{review_run_id}/shadow-run",
            json={"reason": "验证影子运行"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-review-shadow-001"},
        )
    )

    assert any(item["reviewRunId"] == review_run_id for item in page["items"])
    assert detail["run"]["reviewRunId"] == review_run_id
    assert detail["run"]["llmAuditAvailable"] is True
    assert "promptAudit" not in detail["run"]
    assert "llmMetadata" not in detail["run"]
    assert detail["llmAudit"]["runType"] == "review_run"
    assert detail["llmAudit"]["visibility"] == "masked"
    assert detail["llmAudit"]["inputs"]["messages"]
    assert detail["llmAudit"]["outputs"]["available"] is True
    assert detail["llmAudit"]["reasoning"]["redactionPolicy"] == "audit_summary_only_no_raw_chain_of_thought"
    assert detail["llmAudit"]["reasoning"]["rawChainOfThoughtAvailable"] is False
    assert audit_package["schemaVersion"] == "FdeReviewRunAuditPackage@1.0.0"
    assert audit_package["reviewRunId"] == review_run_id
    assert audit_package["visibility"] == "masked"
    assert audit_package["chainOfThoughtPolicy"]["rawChainOfThoughtIncluded"] is False
    assert audit_package["integrity"]["packageHash"].startswith("sha256:")
    assert audit_package["lineage"]["inputHash"] == detail["lineage"]["inputHash"]
    assert audit_package["llmAudit"]["outputs"]["available"] is True
    assert audit_package["llmAudit"]["reasoning"]["rawChainOfThoughtAvailable"] is False
    assert audit_package["scorecard"]["targetScore"] == 100
    assert all("rawChainOfThought" not in item for item in audit_package["reasoningTrace"])
    assert detail["temporal"]["historyPolicy"] == "ids_hashes_versions_only"
    assert detail["scorecard"]["targetScore"] == 100
    assert detail["scorecard"]["sections"]
    assert {"workflow", "graph", "evidence", "governance"} <= {
        item["name"] for item in detail["scorecard"]["sections"]
    }
    assert detail["scorecard"]["score"] < 100
    assert any("Temporal" in blocker for blocker in detail["scorecard"]["blockers"])
    assert detail["reasoningTrace"]
    assert detail["reasoningTrace"][0]["redactionPolicy"] == "audit_summary_only_no_raw_chain_of_thought"
    assert all("rawChainOfThought" not in item for item in detail["reasoningTrace"])
    assert detail["lineage"]["reasoningPolicy"] == "show_audit_summary_not_raw_chain_of_thought"
    assert detail["lineage"]["capabilityBundleHash"].startswith("sha256:")
    assert detail["qualityEvaluation"]["dimensions"]
    assert detail["qualityEvaluation"]["gates"]
    assert detail["qualityEvaluation"]["humanReviewRequired"] is True
    assert detail["humanCorrections"] == []
    assert graph["nodes"]
    assert graph["artifactSummary"]["toolCalls"] >= 3
    assert graph["artifacts"]["retrievalTraces"]
    assert graph["artifacts"]["ruleCheckResults"]
    assert temporal["workflowType"] == "ReviewRunWorkflow"
    decision = assert_ok(
        client.post(
            f"/api/review-runs/{review_run_id}/human-decision",
            json={
                "decision": "edit",
                "comment": "人工修正 finding 表述，纳入评估样本。",
                "correctedOutput": [{"description": "人工修正后的审查发现。"}],
                "shouldEnterEvaluationSet": True,
            },
            headers={
                "X-Role": "inspection",
                "Idempotency-Key": "fde-review-decision-001",
                "If-Match": detail["run"]["etag"],
            },
        )
    )
    detail_after_decision = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}", headers={"X-Role": "fde"}))
    assert decision["feedback"]["feedbackType"] == "edited"
    assert detail_after_decision["humanCorrections"]
    assert detail_after_decision["humanCorrections"][0]["shouldEnterEvaluationSet"] is True
    assert replay["reviewRun"]["parentReviewRunId"] == review_run_id
    assert replay["reviewRun"]["runMode"] == "diagnostic_replay"
    assert shadow["reviewRun"]["parentReviewRunId"] == review_run_id
    assert shadow["reviewRun"]["runMode"] == "shadow_replay"


def test_fde_review_run_diagnostic_feedback_does_not_change_business_state(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
    allow_published_test_bindings(monkeypatch)
    seed_confirmed_node_24_evidence()
    ai_run = assert_ok(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
            headers={"X-Role": "inspection", "Idempotency-Key": "fde-review-feedback-inline-001"},
        )
    )
    review_run_id = ai_run["dispatch"]["reviewRunId"]
    detail_before = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}", headers={"X-Role": "fde"}))
    before_status = detail_before["run"]["status"]
    feedback = assert_ok(
        client.post(
            f"/api/fde/review-runs/{review_run_id}/feedback",
            json={
                "feedbackType": "wrong_evidence",
                "rootCause": "prompt_error",
                "comment": "FDE 标记证据范围需修正，不改变业务结论。",
                "correctedOutput": [{"description": "补充页码、bbox 和条款映射。"}],
                "shouldEnterEvaluationSet": True,
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-review-feedback-001"},
        )
    )
    detail_after = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}", headers={"X-Role": "fde"}))
    forbidden = assert_error(
        client.post(
            f"/api/fde/review-runs/{review_run_id}/feedback",
            json={"feedbackType": "wrong_evidence"},
            headers={"X-Role": "contractor", "Idempotency-Key": "fde-review-feedback-forbidden"},
        ),
        "FORBIDDEN",
    )

    assert feedback["businessImpactPolicy"] == "diagnostic_only_no_business_state_change"
    assert feedback["feedback"]["reviewRunId"] == review_run_id
    assert feedback["feedback"]["source"] == "fde_review_run_diagnostic"
    assert feedback["feedback"]["governanceState"] == "needs_triage"
    assert feedback["feedback"]["shouldEnterEvaluationSet"] is True
    assert feedback["reviewRun"]["status"] == before_status
    assert detail_after["run"]["status"] == before_status
    assert detail_after["humanCorrections"]
    assert detail_after["humanCorrections"][0]["feedbackType"] == "wrong_evidence"
    assert forbidden["message"]


def test_fde_feedback_triage_and_release_gate() -> None:
    triage = assert_ok(
        client.post(
            "/api/fde/feedback/AIFB-24-001/triage",
            json={"rootCause": "prompt_error", "status": "approved_for_eval", "canUseForEval": True},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-triage-001"},
        )
    )
    blocked_release = assert_ok(
        client.post(
            "/api/fde/releases",
            json={"capabilityBundleId": "BUNDLE-REVIEW-202606", "riskLevel": "high"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-001"},
        )
    )
    feedback_rows = assert_ok(client.get("/api/fde/feedback", headers={"X-Role": "fde"}))
    feedback_row = next(item for item in feedback_rows if item["id"] == "AIFB-24-001")

    assert triage["feedback"]["status"] == "approved_for_eval"
    assert triage["feedback"]["governanceState"] == "promoted_to_eval"
    assert triage["feedback"]["evaluationCaseId"] == triage["evaluationCase"]["id"]
    assert triage["feedback"]["canUseForEval"] is True
    assert triage["feedback"]["sampleUsage"]["evaluationCaseId"] == triage["evaluationCase"]["id"]
    assert triage["evaluationCase"]["sourceFeedbackId"] == "AIFB-24-001"
    assert triage["evaluationCase"]["status"] == "approved_for_eval"
    assert triage["evaluationCase"]["canUseForEval"] is True
    assert feedback_row["governanceState"] == "promoted_to_eval"
    assert feedback_row["evaluationCaseId"] == triage["evaluationCase"]["id"]
    assert feedback_row["canUseForEval"] is True
    assert feedback_row["canUseForTraining"] is False
    assert feedback_row["dataSensitivity"] == "masked"
    assert feedback_row["adjudicationRequired"] is False
    assert feedback_row["sampleUsage"]["sourceFeedbackId"] == "AIFB-24-001"
    assert any(item.get("sourceFeedbackId") == "AIFB-24-001" for item in repo.state["evaluation_cases"])
    assert blocked_release["plan"]["status"] == "blocked_by_gate"
    assert "缺少评估报告" in blocked_release["plan"]["blockingReasons"]
    assert "缺少回滚方案" in blocked_release["plan"]["blockingReasons"]


def test_fde_access_grant_controls_raw_ai_run_view() -> None:
    masked = assert_ok(client.get("/api/fde/ai-runs/AIRUN-24-20260625-01", headers={"X-Role": "fde"}))
    grant = assert_ok(
        client.post(
            "/api/fde/access-grants/request",
            json={"targetType": "ai_run", "targetId": "AIRUN-24-20260625-01", "reason": "诊断证据定位"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-access-001"},
        )
    )
    approved = assert_ok(
        client.post(
            f"/api/fde/access-grants/{grant['grant']['id']}/approve",
            json={},
            headers={"X-Role": "admin", "Idempotency-Key": "fde-access-approve-001"},
        )
    )
    raw = assert_ok(client.get("/api/fde/ai-runs/AIRUN-24-20260625-01", headers={"X-Role": "fde"}))

    assert masked["run"]["rawAccess"] is False
    assert masked["llmAudit"]["visibility"] == "masked"
    assert grant["grant"]["status"] == "pending"
    assert approved["grant"]["status"] == "approved"
    assert not approved["grant"]["expiresAt"].startswith("9999-")
    assert raw["run"]["rawAccess"] is True
    assert raw["llmAudit"]["visibility"] == "raw"


def test_fde_evaluation_report_and_release_state_machine() -> None:
    evaluation = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={"evaluationSetId": "ESET-GOLDEN-ENGINEERING-001", "capabilityBundleId": "BUNDLE-REVIEW-202606", "profile": "legacy_non_certifying"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-eval-001"},
        )
    )
    report = assert_ok(
        client.get(
            f"/api/fde/evaluation-runs/{evaluation['run']['id']}/report",
            headers={"X-Role": "fde"},
        )
    )
    release = assert_ok(
        client.post(
            "/api/fde/releases",
            json={
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "riskLevel": "high",
                "evaluationReportId": evaluation["report"]["id"],
                "rollbackPlanId": "ROLLBACK-BUNDLE-202606",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-gated-001"},
        )
    )
    assert evaluation["run"]["caseSummary"]["cases"] >= 1
    assert evaluation["run"]["metrics"]["casePassRate"] >= 0.9
    assert evaluation["run"]["metrics"]["retrievalRecall"] >= 0.9
    assert evaluation["run"]["metrics"]["wrongReferenceRate"] == 0
    assert evaluation["caseResults"]
    assert evaluation["caseResults"][0]["evaluationRunId"] == evaluation["run"]["id"]
    assert evaluation["caseResults"][0]["status"] == "passed"
    assert evaluation["caseResults"][0]["retrievalPassed"] is True
    assert evaluation["caseResults"][0]["expectedClauseIds"] == ["TSG-Z6002-3.2"]
    assert evaluation["caseResults"][0]["selectedRoute"] == "hybrid_review_basis_search"
    assert evaluation["caseResults"][0]["retrievalTraceId"]
    assert any(item.get("evaluationRunId") == evaluation["run"]["id"] for item in repo.state["evaluation_case_results"])
    assert any(
        item.get("evaluationRunId") == evaluation["run"]["id"]
        and item.get("queryType") == "fde_evaluation_retrieval"
        for item in repo.state["retrieval_traces"]
    )
    assert report["report"]["caseSummary"]["cases"] == evaluation["run"]["caseSummary"]["cases"]
    assert report["report"]["caseSummary"]["retrievalRecall"] >= 0.9
    assert report["caseResults"]
    fde_approval = assert_error(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/approve",
            json={"comment": "FDE 不能自批高风险发布。"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-approve-fde-001"},
        ),
        "FORBIDDEN",
    )
    submitted = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/submit",
            json={"reason": "提交完整评估、风险集和回滚方案进行发布门禁校验。"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-submit-001"},
        )
    )
    approved = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/approve",
            json={"status": "approved", "comment": "评估、风险集和回滚计划满足灰度前置条件。"},
            headers={"X-Role": "admin", "Idempotency-Key": "fde-release-approve-admin-001"},
        )
    )
    direct_canary = assert_error(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/request-canary",
            json={"tenantPercent": 10},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-canary-direct-001"},
        ),
        "VALIDATION_ERROR",
    )
    shadow = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/start-shadow",
            json={"sampleRate": 0.1, "reason": "验证候选能力组合在真实流量副本上的证据命中情况。"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-shadow-001"},
        )
    )
    canary = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/request-canary",
            json={"tenantPercent": 10},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-canary-001"},
        )
    )

    assert evaluation["run"]["status"] == "completed"
    assert report["report"]["status"] == "passed"
    assert release["plan"]["status"] == "blocked_by_gate"
    assert any(gate["gate"] == "release_approval" and not gate["passed"] for gate in release["gates"])
    assert fde_approval["data"]["reason"] == "FORBIDDEN"
    assert submitted["plan"]["status"] == "blocked_by_gate"
    assert any(gate["gate"] == "release_approval" and not gate["passed"] for gate in submitted["gates"])
    assert approved["approval"]["status"] == "approved"
    assert approved["plan"]["status"] == "submitted"
    assert all(gate["passed"] for gate in approved["gates"])
    assert direct_canary["data"]["reason"] == "VALIDATION_ERROR"
    assert shadow["plan"]["status"] == "shadow_running"
    assert canary["plan"]["status"] == "canary_requested"


def test_fde_evaluation_run_fails_when_case_findings_are_missing() -> None:
    evaluation = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={
                "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "profile": "legacy_non_certifying",
                "caseResults": {
                    "ECASE-24-001": {
                        "actualFindings": [],
                        "actualEvidence": [],
                        "replayMode": "shadow_replay",
                    }
                },
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-eval-fail-001"},
        )
    )
    report = assert_ok(
        client.get(
            f"/api/fde/evaluation-runs/{evaluation['run']['id']}/report",
            headers={"X-Role": "fde"},
        )
    )
    failed_metric = next(
        item
        for item in repo.state["evaluation_metrics"]
        if item.get("evaluationRunId") == evaluation["run"]["id"] and item.get("metric") == "casePassRate"
    )

    assert evaluation["report"]["status"] == "failed"
    assert evaluation["run"]["caseSummary"]["failed"] == 1
    assert evaluation["caseResults"][0]["status"] == "failed"
    assert evaluation["caseResults"][0]["missingFindings"]
    assert failed_metric["passed"] is False
    assert report["report"]["status"] == "failed"
    assert report["caseResults"][0]["missingFindings"] == evaluation["caseResults"][0]["missingFindings"]


def test_fde_evaluation_run_fails_when_expected_clause_is_missing() -> None:
    evaluation = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={
                "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "profile": "legacy_non_certifying",
                "caseResults": {
                    "ECASE-24-001": {
                        "actualClauseIds": ["TSG-D7005-7.4"],
                        "selectedRoute": "hybrid_review_basis_search",
                    }
                },
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-eval-retrieval-fail-001"},
        )
    )
    retrieval_metric = next(
        item
        for item in repo.state["evaluation_metrics"]
        if item.get("evaluationRunId") == evaluation["run"]["id"] and item.get("metric") == "retrievalRecall"
    )
    wrong_reference_metric = next(
        item
        for item in repo.state["evaluation_metrics"]
        if item.get("evaluationRunId") == evaluation["run"]["id"] and item.get("metric") == "wrongReferenceRate"
    )

    assert evaluation["report"]["status"] == "failed"
    assert evaluation["caseResults"][0]["retrievalPassed"] is False
    assert evaluation["caseResults"][0]["missingClauseIds"] == ["TSG-Z6002-3.2"]
    assert evaluation["caseResults"][0]["unexpectedTopClauseId"] == "TSG-D7005-7.4"
    assert retrieval_metric["passed"] is False
    assert wrong_reference_metric["passed"] is False


def test_fde_release_gate_rejects_failed_report_and_accepts_run_id_reference() -> None:
    failed_eval = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={
                "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "profile": "legacy_non_certifying",
                "caseResults": {"ECASE-24-001": {"actualFindings": [], "actualEvidence": []}},
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-eval-failed-release-001"},
        )
    )
    failed_release = assert_ok(
        client.post(
            "/api/fde/releases",
            json={
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "riskLevel": "high",
                "evaluationReportId": failed_eval["report"]["id"],
                "rollbackPlanId": "ROLLBACK-BUNDLE-202606",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-failed-report-001"},
        )
    )
    passed_eval = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={
                "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "profile": "legacy_non_certifying",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-eval-runref-001"},
        )
    )
    run_ref_release = assert_ok(
        client.post(
            "/api/fde/releases",
            json={
                "capabilityBundleId": "BUNDLE-REVIEW-202606",
                "riskLevel": "high",
                "evaluationReportId": passed_eval["run"]["id"],
                "rollbackPlanId": "ROLLBACK-BUNDLE-202606",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-runref-001"},
        )
    )

    failed_gate = next(gate for gate in failed_release["gates"] if gate["gate"] == "evaluation_report")
    run_ref_gate = next(gate for gate in run_ref_release["gates"] if gate["gate"] == "evaluation_report")
    assert failed_eval["report"]["status"] == "failed"
    assert failed_release["plan"]["status"] == "blocked_by_gate"
    assert failed_gate["passed"] is False
    assert failed_gate["message"] == "评估报告未通过"
    assert passed_eval["report"]["status"] == "passed"
    assert run_ref_gate["passed"] is True
    assert run_ref_release["plan"]["status"] == "blocked_by_gate"


def test_fde_business_pack_install_rca_and_data_export() -> None:
    validation = assert_ok(
        client.post(
            "/api/fde/business-packs/validate-all",
            headers={"X-Role": "fde"},
        )
    )
    install = assert_ok(
        client.post(
            "/api/fde/business-packs/engineering_inspection_v1/install",
            json={"tenantId": "TENANT-DEFAULT", "dryRun": True},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-bp-install-001"},
        )
    )
    export = assert_ok(
        client.post(
            "/api/fde/data-exports",
            json={"targetType": "ai_run", "targetId": "AIRUN-24-20260625-01", "masked": True},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-export-001"},
        )
    )
    rca = assert_ok(
        client.post(
            "/api/fde/incidents/INC-AI-20260626-001/rca",
            json={
                "status": "open",
                "rootCause": "low_quality_scan",
                "temporaryAction": "低置信字段全部转人工复核。",
                "longTermAction": "调整低清扫描件预处理并补充回归样本。",
                "owner": "FDE 质量负责人",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-rca-001"},
        )
    )
    costs = assert_ok(client.get("/api/fde/cost-budgets", headers={"X-Role": "fde"}))

    assert validation["scorecard"]["targetScore"] == 100
    assert validation["scorecard"]["ok"] is True
    assert validation["scorecard"]["blockers"] == []
    assert {"catalog", "core-boundary", "fixtures", "delivery"} <= {
        item["name"] for item in validation["scorecard"]["sections"]
    }
    assert install["installation"]["status"] == "dry_run_passed"
    assert install["validation"]["ok"] is True
    assert export["export"]["watermark"].startswith("FDE-")
    assert rca["rca"]["incidentId"] == "INC-AI-20260626-001"
    assert costs["budgets"]
    assert costs["exports"]


def test_fde_ocr_quality_runs_corrections_and_eval() -> None:
    job = repo.create_ocr_job_record(
        document_id="DOC-20260625-003",
        version_id="DV-20260625-003-V2",
        storage_key="documents/DV-20260625-003-V2.pdf",
        file_name="质量证明书.pdf",
        profile_id="quality_certificate_v1",
        document_type="quality_certificate",
    )
    result = repo.finish_ocr_job_record(
        job,
        {
            "status": "success",
            "parseResultId": "PARSE-FDE-OCR-001",
            "fields": [
                {
                    "fieldCode": "heat_no",
                    "fieldName": "炉批号",
                    "fieldValue": "H240315A07",
                    "confidence": 0.66,
                    "pageNo": 1,
                    "sourceEngine": "paddle_ocr_subprocess",
                    "qualityFlags": ["field_low_confidence"],
                },
                {
                    "fieldCode": "report_no",
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.91,
                    "sourceEngine": "profile_regex",
                    "qualityFlags": ["field_value_conflict"],
                },
            ],
            "tables": [
                {
                    "tableId": "T1",
                    "sourceEngine": "heuristic_table_from_ocr_fragments",
                    "structureConfidence": 0.86,
                    "qualityFlags": ["table_evidence_missing", "heuristic_table_fallback"],
                    "businessRows": [{"pipeNo": "PL8301"}],
                    "normalizedRows": [{"pipeNo": "PL8301"}],
                },
                {
                    "tableId": "T2",
                    "sourceEngine": "opencv_grid_text_aligned",
                    "structureConfidence": 0.92,
                    "qualityFlags": ["opencv_grid_structure", "ocr_text_aligned"],
                    "businessRows": [{"pipeNo": "PL8302"}, {"pipeNo": "VT8301"}],
                    "normalizedRows": [{"pipeNo": "PL8302"}, {"pipeNo": "VT8301"}],
                    "cells": [{"text": "pipeNo"}, {"text": "PL8302"}, {"text": "VT8301"}],
                },
            ],
            "seals": [
                {"sealId": "S1", "sealName": "测试单位章", "qualityFlags": ["seal_evidence_missing"]},
                {
                    "sealId": "S2",
                    "sealName": "压力管道 杨道红 TS1810648-2021",
                    "sealType": "design_license_seal",
                    "sourceEngine": "fragment_seal_text_fusion",
                    "ocrConfidence": 0.88,
                    "qualityFlags": ["fragment_seal_text"],
                },
                {
                    "sealId": "S3",
                    "sealName": "视觉印章候选",
                    "sealType": "visual_red_seal_candidate",
                    "visualConfidence": 0.93,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                },
            ],
            "diagnostics": [{"code": "TABLE_STRUCTURE_LOW_CONFIDENCE", "level": "warning"}],
            "quality": {
                "status": "needs_human_review",
                "evidenceCompleteness": 0.5,
                "missingFields": ["drawing_no"],
                "missingTables": ["piping_characteristic_table"],
                "matchedSealTypes": ["design_license_seal"],
                "missingExpectedSealTypes": ["inspection_testing_seal"],
                "reasons": [
                    "FIELD_EVIDENCE_MISSING",
                    "FIELD_VALUE_CONFLICT",
                    "TABLE_EVIDENCE_MISSING",
                    "SEAL_EVIDENCE_MISSING",
                ],
                "missingEvidence": [
                    {"targetType": "field", "targetId": "report_no"},
                    {"targetType": "table", "targetId": "T1"},
                    {"targetType": "seal", "targetId": "S1"},
                ],
            },
            "engineRuns": [
                {
                    "engine": "paddle_ocr_subprocess",
                    "status": "success",
                    "durationMs": 1200,
                    "engineCacheHit": True,
                    "variantCacheHit": False,
                },
                {
                    "engine": "opencv_table_grid_subprocess",
                    "status": "success",
                    "durationMs": 180,
                    "engineCacheHit": False,
                    "variantCacheHit": True,
                },
            ],
        },
    )

    quality = assert_ok(client.get("/api/fde/ocr-quality", headers={"X-Role": "fde"}))
    runs = assert_ok(client.get("/api/fde/ocr-runs", headers={"X-Role": "fde"}))
    detail = assert_ok(client.get(f"/api/fde/ocr-runs/{job['id']}", headers={"X-Role": "fde"}))
    correction = assert_ok(
        client.post(
            "/api/fde/ocr-corrections",
            json={"fieldId": "FIELD-16-001", "correctedValue": "H240315A07", "reason": "低置信度复核"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr-correction-001"},
        )
    )
    evaluation = assert_ok(
        client.post(
            "/api/fde/ocr-evaluation-runs",
            json={"profileId": "quality_certificate_v1"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr-eval-001"},
        )
    )

    assert quality["jobLevel"]["total"] >= 1
    assert quality["cacheMetrics"]["engineRunCount"] >= 2
    assert quality["cacheMetrics"]["engineCacheHits"] >= 1
    assert quality["cacheMetrics"]["variantCacheHits"] >= 1
    assert quality["cacheMetrics"]["slowEngines"][0]["engine"] == "paddle_ocr_subprocess"
    assert quality["fieldLevel"]["parseFieldCount"] >= 2
    assert quality["fieldLevel"]["lowConfidenceParseFieldCount"] >= 1
    assert quality["fieldLevel"]["conflictFieldCount"] >= 1
    assert quality["fieldLevel"]["missingRequiredFieldCount"] >= 1
    assert quality["fieldLevel"]["averageFieldConfidence"] > 0
    assert "drawing_no" in {item["fieldCode"] for item in quality["fieldLevel"]["missingRequiredFieldBreakdown"]}
    assert "report_no" in {item["fieldCode"] for item in quality["fieldLevel"]["fieldCodeBreakdown"]}
    assert "field_value_conflict" in {item["flag"] for item in quality["fieldLevel"]["qualityFlagCounts"]}
    assert "paddle_ocr_subprocess" in {item["source"] for item in quality["fieldLevel"]["sourceBreakdown"]}
    assert quality["evidenceLevel"]["missingEvidence"] >= 3
    assert quality["evidenceLevel"]["fieldEvidenceMissing"] >= 1
    assert quality["evidenceLevel"]["tableEvidenceMissing"] >= 1
    assert quality["evidenceLevel"]["sealEvidenceMissing"] >= 1
    assert quality["evidenceLevel"]["averageEvidenceCompleteness"] < 1
    assert quality["tableLevel"]["tableCount"] >= 2
    assert quality["tableLevel"]["formalTableCount"] >= 1
    assert quality["tableLevel"]["heuristicTableCount"] >= 1
    assert quality["tableLevel"]["reviewRequiredCount"] >= 1
    assert quality["tableLevel"]["missingRequiredTableCount"] >= 1
    assert quality["tableLevel"]["businessRowCount"] >= 3
    assert quality["tableLevel"]["cellCount"] >= 3
    assert quality["tableLevel"]["formalTableRate"] > 0
    assert "heuristic_table_fallback" in {item["flag"] for item in quality["tableLevel"]["qualityFlagCounts"]}
    assert "opencv_grid_text_aligned" in {item["source"] for item in quality["tableLevel"]["sourceBreakdown"]}
    assert "piping_characteristic_table" in {
        item["tableCode"] for item in quality["tableLevel"]["missingRequiredTableBreakdown"]
    }
    assert quality["sealLevel"]["sealCount"] >= 3
    assert quality["sealLevel"]["readableSealCount"] >= 1
    assert quality["sealLevel"]["fragmentSealCount"] >= 1
    assert quality["sealLevel"]["visualCandidateCount"] >= 1
    assert quality["sealLevel"]["reviewRequiredCount"] >= 2
    assert quality["sealLevel"]["missingExpectedSealTypeCount"] >= 1
    assert quality["sealLevel"]["fragmentSealRate"] > 0
    assert "design_license_seal" in {item["sealType"] for item in quality["sealLevel"]["sealTypeBreakdown"]}
    assert "design_license_seal" in {item["sealType"] for item in quality["sealLevel"]["readableSealTypeBreakdown"]}
    assert "design_license_seal" in {item["sealType"] for item in quality["sealLevel"]["matchedExpectedSealTypeBreakdown"]}
    assert "inspection_testing_seal" in {item["sealType"] for item in quality["sealLevel"]["missingExpectedSealTypeBreakdown"]}
    assert quality["sealLevel"]["sampleMissingExpectedSealTypes"][0]["sealType"] == "inspection_testing_seal"
    assert "fragment_seal_text" in {item["flag"] for item in quality["sealLevel"]["qualityFlagCounts"]}
    assert {item["reason"] for item in quality["qualityReasonCounts"]} >= {
        "FIELD_EVIDENCE_MISSING",
        "FIELD_VALUE_CONFLICT",
        "TABLE_EVIDENCE_MISSING",
        "SEAL_EVIDENCE_MISSING",
    }
    assert quality["failurePools"]["fieldFailures"]
    assert {item["code"] for item in quality["failurePools"]["fieldFailures"]} >= {
        "FIELD_EVIDENCE_MISSING",
        "FIELD_LOW_CONFIDENCE",
        "FIELD_VALUE_CONFLICT",
    }
    assert quality["runtimeDoctor"]["status"] in {"unavailable", "attention", "ready"}
    assert "summary" in quality["runtimeDoctor"]
    assert quality["ocr100Scorecard"]["targetScore"] == 100
    assert quality["ocr100Scorecard"]["score"] < 100
    assert quality["ocr100Scorecard"]["sections"]
    assert quality["ocr100Scorecard"]["blockers"]
    assert {"runtime", "evaluation", "sample-probes", "observability"} <= {
        item["name"] for item in quality["ocr100Scorecard"]["sections"]
    }
    assert quality["ocr100ActionBoard"]["schemaVersion"] == "aicheck-ocr-100-action-board-v1"
    assert quality["ocr100ActionBoard"]["summary"]["requiredReadyForEval"] == 100
    assert "collect_samples" in quality["ocr100ActionBoard"]["summary"]["laneCounts"]
    assert any(action["lane"] == "label_existing" for action in quality["ocr100ActionBoard"]["actions"])
    assert quality["ocr100ActionBoard"]["handoff"]["schemaVersion"] == "aicheck-ocr-100-action-handoff-v1"
    assert quality["ocr100ActionBoard"]["handoff"]["status"] in {"ready", "incomplete", "missing"}
    assert quality["ocr100ActionBoard"]["handoff"]["manifestPath"].endswith("ocr_100_action_handoff/handoff_manifest.json")
    if quality["ocr100ActionBoard"]["handoff"]["files"]:
        handoff_files = {item["key"]: item for item in quality["ocr100ActionBoard"]["handoff"]["files"]}
        assert {"collectCsv", "labelCsv"} <= set(handoff_files)
        assert handoff_files["collectCsv"]["owner"] == "采样人员"
        assert "backend/ocr_eval/reports/ocr_100_action_handoff" in handoff_files["labelCsv"]["path"]
    refresh = assert_ok(
        client.post(
            "/api/fde/ocr-100/action-board/refresh",
            json={},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr100-refresh-001"},
        )
    )
    assert refresh["board"]["schemaVersion"] == "aicheck-ocr-100-action-board-v1"
    assert refresh["board"]["handoff"]["status"] == "ready"
    assert refresh["outputs"]["csv"].endswith("ocr_100_action_board.csv")
    assert refresh["auditLogId"]
    assert quality["failurePools"]["tableFailures"]
    assert "TABLE_EVIDENCE_MISSING" in {item["code"] for item in quality["failurePools"]["tableFailures"]}
    seal_failure_codes = {item["code"] for item in quality["failurePools"]["sealFailures"]}
    assert "SEAL_EVIDENCE_MISSING" in seal_failure_codes
    assert "SEAL_REVIEW_REQUIRED" in seal_failure_codes
    assert "S2" not in {item.get("sealId") for item in quality["failurePools"]["sealFailures"]}
    assert runs["items"][0]["id"] == job["id"]
    assert detail["parseResult"]["parseResultId"] == result["parseResultId"]
    assert correction["correction"]["fieldId"] == "FIELD-16-001"
    assert repo.find_one("extracted_fields", "FIELD-16-001")["reviewStatus"] == "已修正"
    assert evaluation["run"]["metrics"]["fileSuccessRate"] == 1
    assert evaluation["run"]["metrics"]["caseCount"] == evaluation["run"]["evaluationSummary"]["summary"]["cases"]
    assert evaluation["run"]["evaluationReport"]["ok"] is False
    assert evaluation["run"]["evaluationReport"]["findingCounts"]["OCR_EVAL_FIELD_EVIDENCE_MISSING"] >= 1
    assert evaluation["run"]["evaluationSummary"]["ok"] is False
    assert evaluation["run"]["evaluationSummary"]["findingCounts"]["OCR_EVAL_FIELD_EVIDENCE_MISSING"] >= 1
    assert evaluation["run"]["evaluationSummary"]["failedCases"]
    assert {"field_extraction_profile", "table_structure_profile", "seal_text_profile"} <= set(evaluation["run"]["scenarioMetrics"])
    assert {"field_extraction_profile", "table_structure_profile", "seal_text_profile"} <= set(
        evaluation["run"]["evaluationSummary"]["scenarioMetrics"]
    )
    assert evaluation["run"]["scenarioMetrics"]["field_extraction_profile"]["findingCounts"]["OCR_EVAL_FIELD_EVIDENCE_MISSING"] >= 1
    assert evaluation["run"]["caseDiagnostics"][0]["details"]
    assert any(
        item.get("code") == "OCR_EVAL_FIELD_EVIDENCE_MISSING"
        for diagnostic in evaluation["run"]["caseDiagnostics"]
        for item in diagnostic.get("findings", [])
    )
    quality_after_eval = assert_ok(client.get("/api/fde/ocr-quality", headers={"X-Role": "fde"}))
    assert quality_after_eval["ocr100Scorecard"]["sections"][1]["name"] == "evaluation"
    assert any(
        "evaluation set has fewer than 100 cases" in blocker
        for blocker in quality_after_eval["ocr100Scorecard"]["blockers"]
    )


def test_fde_ocr_evaluation_accepts_explicit_cases_and_returns_diagnostics() -> None:
    evaluation = assert_ok(
        client.post(
            "/api/fde/ocr-evaluation-runs",
            json={
                "profileId": "piping_characteristic_list_v1",
                "thresholds": {
                    "metrics": {"fieldBboxHitRate": 0.95},
                    "scenarios": {"piping_table_profile": {"metrics": {"fieldBboxHitRate": 0.95}}},
                },
                "cases": [
                    {
                        "caseId": "fde-explicit-bbox",
                        "scenario": "piping_table_profile",
                        "minScore": 0,
                        "fixtureDerived": True,
                        "collectionStatus": "needs_real_sample_replacement",
                        "result": {
                            "parseResultId": "PARSE-FDE-EXPLICIT",
                            "status": "success",
                            "fields": [{"fieldCode": "pipe_no", "fieldValue": "PL8301", "bbox": [0, 0, 10, 10]}],
                            "tables": [],
                            "seals": [],
                            "quality": {"status": "auto_usable", "reasons": []},
                        },
                        "expected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [100, 100, 120, 120]}],
                        },
                    }
                ],
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr-eval-explicit-001"},
        )
    )

    run = evaluation["run"]
    diagnostics = run["caseDiagnostics"][0]

    assert run["evaluationReport"]["ok"] is False
    assert run["metrics"]["caseCount"] == 1
    assert run["evaluationSummary"]["ok"] is False
    assert run["evaluationSummary"]["failedCases"][0]["caseId"] == "fde-explicit-bbox"
    assert run["evaluationSummary"]["scenarioMetrics"]["piping_table_profile"]["thresholdFailures"][0]["metric"] == "fieldBboxHitRate"
    assert run["scenarioMetrics"]["piping_table_profile"]["thresholdFailures"][0]["metric"] == "fieldBboxHitRate"
    assert diagnostics["caseId"] == "fde-explicit-bbox"
    assert diagnostics["fixtureDerived"] is True
    assert diagnostics["collectionStatus"] == "needs_real_sample_replacement"
    assert diagnostics["details"]["fields"][0]["status"] == "bbox_mismatch"


def test_fde_ocr_annotation_queue_import_and_review() -> None:
    listing = assert_ok(client.get("/api/fde/ocr-annotation/tasks", headers={"X-Role": "fde"}))

    assert listing["summary"]["tasks"] >= 1
    assert listing["summary"]["readyForEval"] == 0
    assert listing["page"]["items"][0]["candidateCounts"]["fields"] >= 1
    assert listing["page"]["items"][0]["pageDimensions"]["1"] == [2000, 1500]

    export = assert_ok(
        client.post(
            "/api/fde/ocr-annotation/export-label-studio",
            json={"includeWithoutImage": True},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-export-001"},
        )
    )

    assert export["summary"]["tasks"] >= 1
    assert export["tasks"][0]["data"]["case_id"] == "real-piping_table_profile-seed-001"
    assert "<RectangleLabels" in export["labelConfigXml"]

    expected = {
        "qualityStatus": "auto_usable",
        "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 40, 20], "pageNo": 1}],
        "tables": [{"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 20, 90, 80], "pageNo": 1}],
    }
    imported = assert_ok(
        client.post(
            "/api/fde/ocr-annotation/import-label-studio",
            json={
                "markStatus": "ready_for_eval",
                "labelStudioExport": [
                    {
                        "data": {"case_id": "real-piping_table_profile-seed-001", "page_no": 1},
                        "annotations": [
                            {
                                "id": 1,
                                "result": [
                                    {
                                        "from_name": "label_json",
                                        "type": "textarea",
                                        "value": {"text": [json.dumps(expected, ensure_ascii=False)]},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-import-001"},
        )
    )

    assert imported["import"]["summary"]["importedTasks"] == 1
    assert imported["readiness"]["summary"]["humanLabeled"] == 1
    assert "review_labeler_missing" in imported["readiness"]["summary"]["blockerCounts"]

    reviewed = assert_ok(
        client.post(
            "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/review",
            json={"labeler": "标注员A", "reviewer": "FDE 工程师", "comment": "二审通过"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-review-001"},
        )
    )

    assert reviewed["readiness"]["ok"] is True
    assert reviewed["task"]["collectionStatus"] == "ready_for_eval"


def test_fde_ocr_capability_pdf_annotation_uses_page_preview() -> None:
    repo.state.setdefault("fde_capability_test_runs", []).insert(
        0,
        {
            "runId": "FDE-OCR-RUN-PDF-001",
            "id": "FDE-OCR-RUN-PDF-001",
            "uploadSessionId": "FDE-OCR-UP-PDF-001",
            "status": "completed",
            "fileName": "sample.pdf",
            "contentType": "application/pdf",
            "fileSize": 1024,
            "storageKey": "fde-capability-tests/ocr/FDE-OCR-UP-PDF-001/sample.pdf",
            "storageUrl": "minio://ocr-artifacts/fde-capability-tests/ocr/FDE-OCR-UP-PDF-001/sample.pdf",
            "parseResultId": "PARSE-PDF-001",
            "profileId": "generic_document_v1",
            "documentType": "generic_document",
        },
    )
    repo.state.setdefault("ocr_parse_results", []).append(
        {
            "parseResultId": "PARSE-PDF-001",
            "profileId": "generic_document_v1",
            "documentType": "generic_document",
            "quality": {"status": "needs_human_review"},
            "pages": [{"pageNo": 1, "width": 1132, "height": 1600}],
            "fields": [],
            "fragments": [
                {
                    "text": "广东星燃石化设计院有限公司",
                    "bbox": [110, 90, 460, 132],
                    "pageNo": 1,
                    "confidence": 0.92,
                    "sourceEngine": "pp_ocr_v6",
                }
            ],
            "tables": [
                {
                    "tableId": "table-1",
                    "bbox": [82, 266, 1047, 700],
                    "rows": 10,
                    "columns": 2,
                }
            ],
            "seals": [],
        }
    )

    converted = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-PDF-001/to-annotation",
            headers={"X-Role": "fde", "Idempotency-Key": "fde-pdf-annotation-preview-001"},
        )
    )

    task = converted["task"]
    assert task["previewType"] == "pdf"
    assert task["pagePreviewUrl"] == "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-PDF-001/page-preview?pageNo=1"
    assert task["pageDimensions"]["1"] == [1132, 1600]
    text_fields = [
        item
        for item in task["suggestedExpected"]["fields"]
        if str(item.get("fieldCode", "")).startswith("ocr_text_")
    ]
    assert text_fields[0]["value"] == "广东星燃石化设计院有限公司"
    assert text_fields[0]["bbox"] == [110, 90, 460, 132]

    detail = assert_ok(client.get(f"/api/fde/ocr-annotation/tasks/{task['taskId']}", headers={"X-Role": "fde"}))
    assert detail["task"]["pagePreviewUrl"] == task["pagePreviewUrl"]
    assert detail["task"]["pageDimensions"]["1"] == [1132, 1600]


def test_fde_ocr_capability_annotation_keeps_full_table_content() -> None:
    table_rows = [
        ["序号", "名称", "图号"],
        ["1", "工艺图纸目录", "QX201903S-13-Y-00"],
        ["2", "工艺设计说明书", "QX201903S-13-Y-01"],
        ["3", "卸车改造带控制点流程图", "QX201903S-13-Y-02"],
        ["4", "设备表一览表", "QX201903S-13-Y-03"],
        ["5", "卸车鹤管平面布置图", "QX201903S-13-Y-04"],
        ["6", "卸车台配管平面图", "QX201903S-13-Y-05"],
        ["7", "管道安装材料表", "QX201903S-13-Y-06"],
        ["8", "管道特性表", "QX201903S-13-Y-07"],
        ["9", "设备及管道油漆保温一览表", "QX201903S-13-Y-08"],
        ["10", "综合材料表", "QX201903S-13-Y-09"],
    ]
    table_cells = [
        {"row": row_index, "col": column_index, "text": text}
        for row_index, row in enumerate(table_rows)
        for column_index, text in enumerate(row)
    ]
    repo.state.setdefault("fde_capability_test_runs", []).insert(
        0,
        {
            "runId": "FDE-OCR-RUN-TABLE-CELLS-001",
            "id": "FDE-OCR-RUN-TABLE-CELLS-001",
            "status": "completed",
            "fileName": "table.pdf",
            "contentType": "application/pdf",
            "parseResultId": "PARSE-TABLE-CELLS-001",
            "profileId": "generic_document_v1",
            "documentType": "generic_document",
        },
    )
    repo.state.setdefault("ocr_parse_results", []).append(
        {
            "parseResultId": "PARSE-TABLE-CELLS-001",
            "profileId": "generic_document_v1",
            "documentType": "generic_document",
            "quality": {"status": "needs_human_review"},
            "pages": [{"pageNo": 1, "width": 1132, "height": 1600}],
            "fields": [],
            "fragments": [],
            "tables": [
                {
                    "tableId": "table-1",
                    "bbox": [82, 266, 1047, 700],
                    "rows": len(table_rows),
                    "columns": len(table_rows[0]),
                    "cells": table_cells,
                    "text": "| 序号 | 名称 | 图号 |\n| --- | --- | --- |\n| 1 | 工艺图纸目录 | QX201903S-13-Y-00 |",
                }
            ],
            "seals": [],
        }
    )

    converted = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-TABLE-CELLS-001/to-annotation",
            headers={"X-Role": "fde", "Idempotency-Key": "fde-table-cells-annotation-001"},
        )
    )

    table = converted["task"]["suggestedExpected"]["tables"][0]
    assert "| 10 | 综合材料表 | QX201903S-13-Y-09 |" in table["contentMarkdown"]
    assert table["content"] == table["contentMarkdown"]

    stale_expected = {
        "fields": [],
        "tables": [
            {
                "tableId": "table-1",
                "bbox": [82, 266, 1047, 700],
                "minRows": 11,
                "minColumns": 3,
            }
        ],
        "seals": [],
    }
    repo.state.setdefault("ocr_annotation_tasks", []).append(
        {
            "taskId": "ANNO-TABLE-CELLS-STALE-001",
            "caseId": "fde-ocr-capability-table-stale",
            "sourceType": "fde_capability_test",
            "parseResultId": "PARSE-TABLE-CELLS-001",
            "collectionStatus": "needs_labeling",
            "expectedTemplate": stale_expected,
            "suggestedExpected": stale_expected,
        }
    )

    detail = assert_ok(
        client.get(
            "/api/fde/ocr-annotation/tasks/ANNO-TABLE-CELLS-STALE-001",
            headers={"X-Role": "fde"},
        )
    )

    hydrated_table = detail["task"]["suggestedExpected"]["tables"][0]
    assert "| 10 | 综合材料表 | QX201903S-13-Y-09 |" in hydrated_table["contentMarkdown"]
    assert detail["task"]["readinessBlockers"] != ["OCR_ANNOTATION_EXPECTED_TABLE_CONTENT_MISSING"]


def test_fde_ocr_capability_annotation_dedupes_stamp_candidates_and_keeps_location() -> None:
    repo.state.setdefault("fde_capability_test_runs", []).insert(
        0,
        {
            "runId": "FDE-OCR-RUN-SEAL-DEDUP-001",
            "id": "FDE-OCR-RUN-SEAL-DEDUP-001",
            "status": "success",
            "fileName": "sealed.png",
            "contentType": "image/png",
            "parseResultId": "PARSE-SEAL-DEDUP-001",
            "profileId": "seal_text_profile_v1",
            "documentType": "sealed_document",
        },
    )
    repo.state.setdefault("ocr_parse_results", []).append(
        {
            "parseResultId": "PARSE-SEAL-DEDUP-001",
            "profileId": "seal_text_profile_v1",
            "documentType": "sealed_document",
            "quality": {"status": "needs_human_review"},
            "pages": [{"pageNo": 1, "width": 1132, "height": 1600}],
            "fields": [],
            "fragments": [],
            "tables": [],
            "seals": [
                {
                    "sealId": "blue-visual-1",
                    "sealName": "视觉蓝章候选",
                    "sealType": "visual_blue_stamp_candidate",
                    "visualColor": "blue",
                    "visualConfidence": 0.86,
                    "bbox": [630, 895, 1010, 1096],
                    "pageNo": 1,
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                },
                {
                    "sealId": "blue-ocr-1",
                    "sealName": "广东省建设工程勘察设计出图专用章",
                    "sealType": "drawing_approval_seal",
                    "visualColor": "blue",
                    "ocrConfidence": 0.91,
                    "bbox": [640, 905, 1000, 1088],
                    "pageNo": 1,
                    "sourceEngine": "visual_seal_crop_ocr",
                    "fields": [{"fieldName": "资质证书编号", "fieldValue": "A244010070"}],
                    "qualityFlags": ["visual_candidate_only", "seal_text_from_crop_ocr"],
                },
            ],
        }
    )

    converted = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-SEAL-DEDUP-001/to-annotation",
            headers={"X-Role": "fde", "Idempotency-Key": "fde-seal-dedup-annotation-001"},
        )
    )

    seals = converted["task"]["suggestedExpected"]["seals"]
    assert len(seals) == 1
    assert seals[0]["nameContains"] == "广东省建设工程勘察设计出图专用章"
    assert seals[0]["text"] == "广东省建设工程勘察设计出图专用章\n资质证书编号：A244010070"
    assert seals[0]["bbox"] == [640, 905, 1000, 1088]
    assert seals[0]["bboxLabel"] == "盖章位置"
    assert seals[0]["stampLocationRequired"] is True
    assert seals[0]["dedupedCandidateCount"] == 2


def test_fde_ocr_capability_rerun_requeues_existing_run(monkeypatch) -> None:
    started: list[str] = []
    monkeypatch.setattr("apps.api.routes.fde_start_ocr_capability_test_worker", started.append)
    repo.state.setdefault("fde_capability_test_runs", []).append(
        {
            "runId": "FDE-OCR-RUN-RERUN-001",
            "id": "FDE-OCR-RUN-RERUN-001",
            "uploadSessionId": "FDE-OCR-UP-RERUN-001",
            "status": "success",
            "fileName": "sample.pdf",
            "contentType": "application/pdf",
            "storageKey": "fde-capability-tests/ocr/FDE-OCR-UP-RERUN-001/sample.pdf",
            "parseResultId": "PARSE-OLD-001",
            "ocrJobRecordId": "OCRJOB-OLD-001",
            "resultSummary": {"pages": 1, "fields": 2},
            "diagnostics": [{"code": "OLD"}],
            "engineRuns": [{"engine": "old"}],
            "profileId": "generic_document_v1",
            "documentType": "generic_document",
        }
    )

    rerun = assert_ok(
        client.post(
            "/api/fde/capability-tests/ocr/runs/FDE-OCR-RUN-RERUN-001/rerun",
            json={"reason": "test_refresh"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-ocr-rerun-001"},
        )
    )

    assert rerun["alreadyRunning"] is False
    assert rerun["run"]["status"] == "ocr_queued"
    assert rerun["run"]["parseResultId"] is None
    assert rerun["run"]["previousParseResultId"] == "PARSE-OLD-001"
    assert rerun["run"]["rerunCount"] == 1
    assert rerun["run"]["diagnostics"] == []
    assert started == ["FDE-OCR-RUN-RERUN-001"]


def test_fde_ocr_annotation_preview_resolves_sibling_heic(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("apps.api.routes.WORKSPACE_ROOT", tmp_path)
    repo.state["ocr_annotation_tasks"][0]["sourcePath"] = "Scan/IMG_6509.png"
    scan_dir = tmp_path / "Scan"
    scan_dir.mkdir()
    # Tiny PNG payload with a .heic name exercises extension fallback without relying on
    # platform-specific HEIC codecs in CI.
    (scan_dir / "IMG_6509.heic").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lwN5nAAAAABJRU5ErkJggg=="
        )
    )
    monkeypatch.setattr(
        "apps.api.routes.fde_render_heic_page_preview",
        lambda _path: (base64.b64decode("iVBORw0KGgo="), "image/png"),
    )

    detail = assert_ok(
        client.get("/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001", headers={"X-Role": "fde"})
    )

    assert detail["task"]["previewUrl"] == "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/preview"
    preview = client.get(
        "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/preview",
        headers={"X-Role": "fde"},
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG")


def test_fde_builtin_ocr_annotation_label_verify_and_import_pack() -> None:
    expected = {
        "qualityStatus": "auto_usable",
        "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [120, 260, 220, 300], "pageNo": 1}],
        "tables": [
            {
                "businessSchema": "piping_characteristic_table_v1",
                "bbox": [70, 230, 1800, 1120],
                "minRows": 10,
                "minColumns": 12,
                "pageNo": 1,
            }
        ],
    }

    saved = assert_ok(
        client.put(
            "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/label",
            json={
                "labeler": "标注员A",
                "labeledExpected": expected,
                "pageDimensions": {"1": [2000, 1500]},
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-label-001"},
        )
    )

    assert saved["task"]["collectionStatus"] == "labeled"
    assert saved["task"]["labelCounts"] == {"fields": 1, "tables": 1, "seals": 0}
    assert saved["readiness"]["summary"]["readyForEval"] == 0
    assert "review_required" in saved["readiness"]["summary"]["blockerCounts"]

    verified = assert_ok(
        client.post(
            "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/verify",
            json={"reviewer": "FDE 工程师", "decision": "approved", "comment": "内置标注台二审通过"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-verify-001"},
        )
    )

    assert verified["readiness"]["ok"] is True
    assert verified["task"]["readyForEval"] is True
    assert verified["task"]["labeledExpected"]["review"]["reviewer"] == "FDE 工程师"

    imported = assert_ok(
        client.post(
            "/api/fde/ocr-annotation/import-pack",
            json={
                "tasks": [
                    {
                        "taskId": "ANNO-IMPORT-DEMO-001",
                        "caseId": "real-seal_text_profile-import-demo",
                        "scenario": "seal_text_profile",
                        "profileId": "seal_text_profile_v1",
                        "documentType": "seal_photo",
                        "collectionStatus": "needs_labeling",
                        "suggestedExpected": {
                            "qualityStatus": "needs_human_review",
                            "seals": [
                                {
                                    "sealType": "company_official_seal",
                                    "nameContains": "设计院",
                                    "bbox": [10, 10, 120, 90],
                                    "pageNo": 1,
                                }
                            ],
                        },
                    }
                ]
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-pack-001"},
        )
    )

    assert imported["summary"]["importedTasks"] == 1
    assert imported["summary"]["totalTasks"] >= 2

    deleted = assert_ok(
        client.delete(
            "/api/fde/ocr-annotation/tasks/ANNO-IMPORT-DEMO-001",
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-delete-001"},
        )
    )

    assert deleted["deleted"] is True
    assert deleted["taskId"] == "ANNO-IMPORT-DEMO-001"
    assert all(item["taskId"] != "ANNO-IMPORT-DEMO-001" for item in deleted["page"]["items"])
    missing_after_delete = client.get(
        "/api/fde/ocr-annotation/tasks/ANNO-IMPORT-DEMO-001",
        headers={"X-Role": "fde"},
    )
    assert missing_after_delete.status_code == 404


def test_fde_ocr_annotation_label_blocks_non_fde_and_bad_schema() -> None:
    forbidden = assert_error(
        client.put(
            "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/label",
            json={"labeledExpected": {"qualityStatus": "auto_usable"}},
            headers={"X-Role": "contractor", "Idempotency-Key": "fde-annotation-label-forbidden"},
        ),
        "FORBIDDEN",
    )
    assert forbidden["code"] != 0

    invalid_expected = {
        "qualityStatus": "auto_usable",
        "fields": [
            {"fieldCode": "pipe_no", "value": "PL8301", "bbox": [120, 260, 220, 300], "pageNo": 1},
            {"fieldCode": "pipe_no", "value": "PL8301", "bbox": [120, 260, 220, 300], "pageNo": 1},
            {"fieldCode": "empty_value", "value": "", "bbox": [10, 10, 20, 20], "pageNo": 1},
        ],
        "tables": [
            {"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 100, 100], "minRows": 0, "pageNo": 1},
            {"businessSchema": "piping_characteristic_table_v1", "bbox": [0, 0, 100, 100], "pageNo": 1},
        ],
    }

    saved = assert_ok(
        client.put(
            "/api/fde/ocr-annotation/tasks/ANNO-SEED-PIPING-001/label",
            json={"labeler": "标注员A", "labeledExpected": invalid_expected, "pageDimensions": {"1": [90, 90]}},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-annotation-label-invalid"},
        )
    )

    blockers = saved["readiness"]["summary"]["blockerCounts"]
    assert blockers["OCR_ANNOTATION_DUPLICATE_FIELD"] == 1
    assert blockers["OCR_ANNOTATION_FIELD_VALUE_EMPTY"] == 1
    assert blockers["OCR_ANNOTATION_DUPLICATE_TABLE"] == 1
    assert blockers["OCR_ANNOTATION_TABLE_MIN_INVALID"] == 1
    assert blockers["OCR_ANNOTATION_BBOX_OUT_OF_BOUNDS"] >= 1


def test_fde_cannot_execute_business_review_mutation() -> None:
    payload = assert_error(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "满足要求", "opinion": "FDE 不应能保存正式审查意见。"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-business-review"},
        ),
        "FORBIDDEN",
    )

    assert "FDE" in payload["message"]


def test_fde_auth_required_uses_single_role(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    login = assert_ok(client.post("/api/auth/login", json={"username": "fde", "password": "fde"}))

    dashboard = assert_ok(
        client.get("/api/fde/dashboard", headers={"Authorization": f"Bearer {login['token']}"})
    )
    forbidden = assert_error(
        client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "满足要求"},
            headers={"Authorization": f"Bearer {login['token']}", "Idempotency-Key": "fde-auth-business"},
        ),
        "FORBIDDEN",
    )

    assert dashboard["metrics"]
    assert forbidden["code"] != 0


def test_fde_100_routes_and_governance_surface() -> None:
    routes = assert_ok(client.get("/api/auth/routes?role=fde"))
    child_paths = {child["path"] for child in routes[0]["children"]}

    assert {
        "projects",
        "dashboard",
        "ai-runs",
        "review-runs",
        "feedback",
        "evaluation",
        "capability-bundles",
        "releases",
        "ocr-quality",
        "business-packs",
        "security",
        "incidents",
        "costs",
        "acceptance",
    } <= child_paths


def test_fde_project_audit_workspace_groups_tasks_and_blockers() -> None:
    projects = assert_ok(client.get("/api/fde/projects", headers={"X-Role": "fde"}))
    first = projects[0]
    project_id = first["project"]["id"]
    workspace = assert_ok(
        client.get(f"/api/fde/projects/{project_id}/audit-workspace", headers={"X-Role": "fde"})
    )
    node_id = workspace["selectedNodeId"]
    detail = assert_ok(
        client.get(
            f"/api/fde/projects/{project_id}/nodes/{node_id}/audit-detail",
            headers={"X-Role": "fde"},
        )
    )

    assert first["metrics"]["nodes"] >= 1
    assert workspace["project"]["id"] == project_id
    assert workspace["groups"]
    assert workspace["nodeSummaries"]
    assert workspace["metrics"]["documents"] >= 1
    assert workspace["metrics"]["knowledgeChunks"] >= 1
    assert workspace["metrics"]["knowledgeVectors"] >= 1
    assert workspace["metrics"]["vectorizedDocuments"] >= 1
    assert workspace["metrics"]["pageIndexNodes"] >= 1
    assert "reviewRuns" in workspace
    assert "ocrJobs" in workspace
    assert "ocrAnnotationTasks" in workspace
    assert "qualityBlockers" in workspace
    if workspace["reviewRuns"]:
        review_run = workspace["reviewRuns"][0]
        assert review_run["graphSummary"]["total"] >= 1
        assert review_run["graphAuditSummary"]["nodeCount"] >= 1
        assert review_run["graphAuditSummary"]["edgeCount"] >= 1
        assert review_run["graphAuditSummary"]["timelineCount"] >= 1
        assert review_run["graphAuditSummary"]["workflowEngine"]
        assert review_run["graphAuditSummary"]["graphEngine"] == "langgraph"
        assert "artifactSummary" in review_run["graphAuditSummary"]
    if workspace["ocrAnnotationTasks"]:
        annotation_task = workspace["ocrAnnotationTasks"][0]
        assert "candidateCounts" in annotation_task
        assert "labelCounts" in annotation_task
        assert "readyForEval" in annotation_task
        assert "readinessBlockers" in annotation_task
    document = workspace["documents"][0]
    assert document["knowledgeFileId"].startswith("KF-")
    assert document["sliceStatus"] in {"已切片", "切片中", "待切片", "等待OCR"}
    assert document["vectorStatus"] in {"已向量化", "向量化中", "待向量化", "未向量化"}
    assert document["chunkCount"] >= 1
    assert document["vectorCount"] >= 1
    assert document["embeddingModel"] == "embedding-default"
    assert document["embeddingModelId"] == "Qwen/Qwen3-Embedding-0.6B"
    assert document["indexVersion"]
    assert document["pageIndexStatus"] == "已构建"
    assert document["pageIndexNodeCount"] >= 1
    assert document["knowledgeLineage"]["schemaVersion"] == "FdeKnowledgeLineage@1.0.0"
    assert document["knowledgeLineage"]["stages"]
    assert {stage["key"] for stage in document["knowledgeLineage"]["stages"]} >= {
        "ocr_parse",
        "knowledge_slice",
        "vector_embed",
        "pageindex_tree",
        "review_ready",
    }
    assert workspace["knowledgeLineage"]["schemaVersion"] == "FdeProjectKnowledgeLineage@1.0.0"
    assert workspace["knowledgeLineage"]["source"] == "backend_audit_projection"
    assert len(workspace["knowledgeLineage"]["vectorFlow"]) == 5
    assert len(workspace["knowledgeLineage"]["pageIndexFlow"]) == 5
    assert workspace["technologyStack"]["schemaVersion"] == "FdeTechnologyStack@1.0.0"
    assert workspace["technologyStack"]["hotSwap"]["enabled"] is True
    assert workspace["technologyStack"]["active"]["embedding"]["alias"] == "embedding-default"
    assert workspace["technologyStack"]["active"]["embedding"]["modelId"] == "Qwen/Qwen3-Embedding-0.6B"
    assert workspace["technologyStack"]["qwenRuntime"]["mode"] == "server"
    assert workspace["technologyStack"]["qwenRuntime"]["activeModels"]["review"] == "review-chat"
    assert workspace["technologyStack"]["qwenRuntime"]["embeddingOptional"] == "text-embedding-v4"
    assert workspace["technologyStack"]["qwenRuntime"]["embeddingSwitchDefault"] is False
    assert workspace["technologyStack"]["auditRuntime"]["mode"] == "ocr_llm"
    assert workspace["technologyStack"]["auditRuntime"]["useOcrEvidence"] is True
    assert {
        item["modelId"] for item in workspace["technologyStack"]["embeddingModelRegistry"]
    } >= {"Qwen/Qwen3-Embedding-0.6B", "BAAI/bge-m3"}
    assert detail["summary"]["nodeId"] == node_id
    assert "bindings" in detail


def test_fde_project_audit_workspace_does_not_invent_projection_data() -> None:
    workspace = assert_ok(
        client.get(
            "/api/fde/projects/P-2026-GDLNG-002/audit-workspace?nodeId=16",
            headers={"X-Role": "fde"},
        )
    )

    assert workspace["metrics"]["documents"] == 0
    assert workspace["metrics"]["knowledgeChunks"] == 0
    assert workspace["metrics"]["knowledgeVectors"] == 0
    assert workspace["metrics"]["pageIndexNodes"] == 0
    assert workspace["metrics"]["ocrJobs"] == 0
    assert workspace["metrics"]["annotationTasks"] == 0
    assert workspace["documents"] == []
    assert workspace["reviewRuns"] == []
    assert workspace["ocrJobs"] == []
    assert workspace["ocrAnnotationTasks"] == []
    assert workspace["qualityBlockers"] == []
    assert workspace["knowledgeLineage"]["retrievalTraceCount"] == 0
    assert workspace["knowledgeLineage"]["pageIndexTraceCount"] == 0


def test_fde_synthetic_review_and_ocr_records_are_not_exposed() -> None:
    assert_error(
        client.get(
            "/api/fde/review-runs/RR-AUDIT-P-2026-GDLNG-002-16",
            headers={"X-Role": "fde"},
        ),
        "NOT_FOUND",
    )
    assert_error(
        client.get(
            "/api/fde/ocr-runs/OCR-JOB-FDE-2026GDLNG002-1",
            headers={"X-Role": "fde"},
        ),
        "NOT_FOUND",
    )


def test_fde_security_masking_data_export_and_audit_flow() -> None:
    policies = assert_ok(client.get("/api/fde/security/masking-policies", headers={"X-Role": "fde"}))
    created_policy = assert_ok(
        client.post(
            "/api/fde/security/masking-policies",
            json={"targetType": "ai_run", "fieldPath": "findingDrafts.description", "visibleChars": 80},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-mask-policy-001"},
        )
    )
    export = assert_ok(
        client.post(
            "/api/fde/data-exports",
            json={"targetType": "ai_run", "targetId": "AIRUN-24-20260625-01", "masked": True},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-export-approval-001"},
        )
    )
    forbidden = assert_error(
        client.post(
            f"/api/fde/data-exports/{export['export']['id']}/approve",
            json={"status": "approved"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-export-approval-denied"},
        ),
        "FORBIDDEN",
    )
    approved = assert_ok(
        client.post(
            f"/api/fde/data-exports/{export['export']['id']}/approve",
            json={"status": "approved"},
            headers={"X-Role": "admin", "Idempotency-Key": "fde-export-approval-admin"},
        )
    )
    expired = assert_ok(
        client.post(
            f"/api/fde/data-exports/{export['export']['id']}/expire",
            json={"reason": "测试过期"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-export-expire-001"},
        )
    )
    audit = assert_ok(client.get("/api/fde/audit-events", headers={"X-Role": "fde"}))

    assert policies
    assert created_policy["policy"]["status"] == "draft"
    assert forbidden["data"]["reason"] == "FORBIDDEN"
    assert approved["export"]["status"] == "approved"
    assert expired["export"]["status"] == "expired"
    assert any(item["objectType"] == "DataExport" for item in audit["events"])
    assert any(item["objectType"] == "MaskingPolicy" for item in audit["events"])


def test_fde_version_diff_release_impact_and_production_gate() -> None:
    bundle_id = repo.state["capability_bundles"][0]["id"]
    bundle_diff = assert_ok(client.get(f"/api/fde/capability-bundles/{bundle_id}/diff", headers={"X-Role": "fde"}))
    pack_diff = assert_ok(client.get("/api/fde/business-packs/engineering_inspection_v1/diff", headers={"X-Role": "fde"}))
    release = assert_ok(
        client.post(
            "/api/fde/releases",
            json={
                "capabilityBundleId": bundle_id,
                "riskLevel": "medium",
                "targetScope": {"tenantIds": ["TENANT-DEFAULT"], "businessPackIds": ["engineering_inspection_v1"], "projectIds": []},
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-100-001"},
        )
    )
    release_id = release["plan"]["id"]
    impact = assert_ok(client.get(f"/api/fde/releases/{release_id}/impact", headers={"X-Role": "fde"}))
    shadow = assert_ok(
        client.post(
            f"/api/fde/releases/{release_id}/start-shadow",
            json={"sampleRate": 0.1, "reason": "验证中风险发布计划。"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-shadow-100"},
        )
    )
    shadow_passed = assert_ok(
        client.post(
            f"/api/fde/releases/{release_id}/mark-shadow-passed",
            json={
                "metrics": {"sampleCount": 100, "failedRuns": 0, "evidenceHitRate": 0.99},
                "reason": "100 个 Shadow 样本无失败且证据命中率达到 99%。",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-shadow-pass-100"},
        )
    )
    production_forbidden = assert_error(
        client.post(
            f"/api/fde/releases/{release_id}/approve-production",
            json={"comment": "FDE 不可批准生产"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-prod-denied"},
        ),
        "FORBIDDEN",
    )
    production = assert_ok(
        client.post(
            f"/api/fde/releases/{release_id}/approve-production",
            json={"comment": "管理员批准生产"},
            headers={"X-Role": "admin", "Idempotency-Key": "fde-release-prod-admin"},
        )
    )

    assert bundle_diff["bundleId"] == bundle_id
    assert pack_diff["businessPackId"] == "engineering_inspection_v1"
    assert impact["affectedProjectCount"] >= 1
    assert shadow["plan"]["status"] == "shadow_running"
    assert shadow_passed["plan"]["status"] == "shadow_passed"
    assert production_forbidden["data"]["reason"] == "FORBIDDEN"
    assert production["plan"]["status"] == "production_approved"


def test_fde_incident_close_and_cost_budget_change_request() -> None:
    budget_id = repo.state["cost_budgets"][0]["id"]
    change = assert_ok(
        client.post(
            f"/api/fde/cost-budgets/{budget_id}/propose-change",
            json={"proposedLimit": 1000, "reason": "测试预算变更"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-budget-change-001"},
        )
    )
    closed = assert_ok(
        client.post(
            "/api/fde/incidents/INC-AI-20260626-001/close",
            json={"resolution": "测试关闭"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-incident-close-001"},
        )
    )
    costs = assert_ok(client.get("/api/fde/cost-budgets", headers={"X-Role": "fde"}))

    assert change["changeRequest"]["status"] == "pending_approval"
    assert closed["incident"]["status"] == "closed"
    assert any(item["id"] == change["changeRequest"]["id"] for item in costs["changeRequests"])


def test_fde_vector_file_detail_returns_chunk_level_quality() -> None:
    knowledge_file = repo.find_one("knowledge_files", "KF-DOC-20260625-001")
    knowledge_file["chunkCount"] = 2
    knowledge_file["vectorCount"] = 2
    repo.state["knowledge_chunks"].extend(
        [
            {
                "id": "CHK-KF-DOC-20260625-001-1",
                "fileId": "KF-DOC-20260625-001",
                "documentId": "DOC-20260625-001",
                "documentVersionId": "DV-20260625-001-V2",
                "chunkNo": 1,
                "text": "焊工资格证编号 TS6J-2024-03158，姓名王建国，有效期覆盖项目施工周期。",
                "pageNo": 1,
                "bbox": [120, 220, 780, 310],
                "tokenCount": 42,
                "createdAt": "2026-06-27 00:00:00",
            },
            {
                "id": "CHK-KF-DOC-20260625-001-2",
                "fileId": "KF-DOC-20260625-001",
                "documentId": "DOC-20260625-001",
                "documentVersionId": "DV-20260625-001-V2",
                "chunkNo": 2,
                "text": "持证项目覆盖 SMAW 和 GTAW，需核对外部查询截图来源。",
                "pageNo": 2,
                "bbox": [160, 180, 860, 280],
                "tokenCount": 36,
                "createdAt": "2026-06-27 00:01:00",
            },
        ]
    )
    repo.state.setdefault("review_runs", []).append(
        {
            "id": "RR-CHUNK-001",
            "reviewRunId": "RR-CHUNK-001",
            "projectId": "P-2026-HDCP-001",
            "nodeId": 24,
            "inputDocumentVersionIds": ["DV-20260625-001-V2"],
        }
    )
    repo.state.setdefault("retrieval_traces", []).append(
        {
            "id": "RTR-CHUNK-001",
            "retrievalTraceId": "RTR-CHUNK-001",
            "reviewRunId": "RR-CHUNK-001",
            "query": "焊工资格证有效期如何校验？",
            "selectedRoute": "hybrid_review_basis_search",
            "filters": {"projectId": "P-2026-HDCP-001", "nodeId": 24, "businessPackId": "engineering_inspection_v1"},
            "selectedClauses": [
                {
                    "id": "KC-CHK-KF-DOC-20260625-001-1",
                    "clauseId": "CHK-KF-DOC-20260625-001-1",
                    "fileId": "KF-DOC-20260625-001",
                    "documentVersionId": "DV-20260625-001-V2",
                    "pageNo": 1,
                    "bbox": [120, 220, 780, 310],
                }
            ],
        }
    )

    detail = assert_ok(
        client.get(
            "/api/fde/projects/P-2026-HDCP-001/documents/DV-20260625-001-V2/vector-detail",
            headers={"X-Role": "fde"},
        )
    )
    forbidden = assert_error(
        client.get(
            "/api/fde/projects/P-2026-HDCP-001/documents/DV-20260625-001-V2/vector-detail",
            headers={"X-Role": "contractor"},
        ),
        "FORBIDDEN",
    )

    assert detail["schemaVersion"] == "FdeVectorFileDetail@1.1.0"
    assert detail["compatibleSchemaVersion"] == "FdeVectorFileDetail@1.0.0"
    assert detail["fileName"] == "焊工资格证-王建国.pdf"
    assert detail["chunkSummary"]["materializedChunkCount"] == 2
    assert detail["chunkSummary"]["pageCoverage"] == 1
    assert detail["chunkSummary"]["bboxCoverage"] == 1
    assert detail["chunkRows"][0]["chunkId"] == "CHK-KF-DOC-20260625-001-1"
    assert detail["chunkRows"][0]["retrievalHitCount"] >= 1
    assert detail["retrievalTraceRows"][0]["selectedChunkCount"] >= 1
    assert detail["sourcePreview"]["schemaVersion"] == "FdeSourcePreview@1.0.0"
    assert detail["ocrArtifacts"]["schemaVersion"] == "FdeOcrArtifacts@1.0.0"
    assert detail["textRecords"]
    assert detail["vectorPayloads"][0]["indexRecord"]["payloadHash"]
    assert detail["indexRecords"][0]["vectorId"]
    assert detail["llmUsage"]["scope"] == "document_explicit"
    assert detail["processingPipeline"]["source"]["stage"] == "image"
    assert detail["processingPipeline"]["ocr"]["summary"]["fieldCount"] >= 1
    assert detail["processingPipeline"]["text"]["textRecordCount"] >= 1
    assert detail["processingPipeline"]["vectorFormat"]["rows"][0]["embeddingInput"]["model"] == "embedding-default"
    assert detail["processingPipeline"]["vectorFormat"]["rows"][0]["vectorRecord"]["payloadHash"]
    assert forbidden["data"]["reason"] == "FORBIDDEN"


def test_fde_standards_vectorization_is_global_rules_source() -> None:
    repo.state["knowledge_files"].append(
        {
            "id": "KF-KB-FDE-STANDARD-001",
            "fileName": "GBT 3087-2022 低中压锅炉用无缝钢管.pdf",
            "sourceId": STANDARD_RULES_SOURCE_ID,
            "sourceName": "标准规范库（业务规则引用标准）",
            "sourceType": "standard",
            "contextType": "standard_reference",
            "documentId": "KDOC-FDE-STANDARD-001",
            "documentVersionId": "KDV-FDE-STANDARD-001-V1",
            "sourceRelativePath": "rules/standards/GBT 3087-2022 低中压锅炉用无缝钢管.pdf",
            "ocrStatus": "已识别",
            "sliceStatus": "已切片",
            "vectorStatus": "已向量化",
            "chunkCount": 1,
            "vectorCount": 1,
            "embeddingModel": "Qwen/Qwen3-Embedding-0.6B",
            "indexVersion": "knowledge-index-qwen3-0.6b@1024",
            "vectorDimensions": 1024,
        }
    )
    repo.state["knowledge_chunks"].append(
        {
            "id": "CHK-KF-KB-FDE-STANDARD-001-1",
            "fileId": "KF-KB-FDE-STANDARD-001",
            "documentId": "KDOC-FDE-STANDARD-001",
            "documentVersionId": "KDV-FDE-STANDARD-001-V1",
            "chunkNo": 1,
            "text": "GB/T 3087-2022 规定低中压锅炉用无缝钢管的订货内容、尺寸、外形和技术要求。",
            "pageNo": 1,
            "bbox": [40, 80, 560, 180],
            "sectionPath": ["范围"],
            "sourceMethod": "pymupdf_text_layer",
            "tokenCount": 48,
        }
    )
    repo.state["knowledge_vectors"].append(
        {
            "id": "KV-CHK-KF-KB-FDE-STANDARD-001-1",
            "fileId": "KF-KB-FDE-STANDARD-001",
            "chunkId": "CHK-KF-KB-FDE-STANDARD-001-1",
            "documentVersionId": "KDV-FDE-STANDARD-001-V1",
            "dimensions": 1024,
            "embeddingModel": "Qwen/Qwen3-Embedding-0.6B",
            "indexVersion": "knowledge-index-qwen3-0.6b@1024",
            "embedding": [0.0] * 1024,
        }
    )
    repo.state["knowledge_page_index_nodes"].append(
        {
            "id": "PIN-FDE-STANDARD-001",
            "pageIndexNodeId": "PIN-FDE-STANDARD-001",
            "kbDocId": STANDARD_RULES_SOURCE_ID,
            "kbVersion": "rules-standards-test",
            "nodeId": "KF-KB-FDE-STANDARD-001",
            "parentNodeId": "PIN-ROOT-TEST",
            "title": "GBT 3087-2022 低中压锅炉用无缝钢管.pdf",
            "summary": "低中压锅炉用无缝钢管标准首页。",
            "startPage": 1,
            "endPage": 1,
            "sectionPath": ["标准规范库", "GBT 3087-2022"],
            "linkedClauseIds": ["CHK-KF-KB-FDE-STANDARD-001-1"],
            "sourceRelativePath": "rules/standards/GBT 3087-2022 低中压锅炉用无缝钢管.pdf",
            "indexVersion": "pageindex-standard-rules-v1",
        }
    )

    overview = assert_ok(
        client.get(
            "/api/fde/standards/vectorization?keyword=3087",
            headers={"X-Role": "fde"},
        )
    )
    detail = assert_ok(
        client.get(
            "/api/fde/standards/files/KF-KB-FDE-STANDARD-001/vector-detail",
            headers={"X-Role": "fde"},
        )
    )
    forbidden = assert_error(
        client.get(
            "/api/fde/standards/vectorization",
            headers={"X-Role": "contractor"},
        ),
        "FORBIDDEN",
    )

    assert overview["sourceId"] == STANDARD_RULES_SOURCE_ID
    assert overview["metrics"]["fileCount"] >= 1
    assert overview["metrics"]["vectorCount"] >= 1
    assert overview["files"][0]["sourceRelativePath"].startswith("rules/standards/")
    assert all(item.get("sourceId") == STANDARD_RULES_SOURCE_ID for item in overview["files"])
    assert all(not item.get("projectId") for item in overview["files"])
    assert detail["scope"] == "standards"
    assert detail["knowledgeFileId"] == "KF-KB-FDE-STANDARD-001"
    assert detail["sourceRelativePath"].startswith("rules/standards/")
    assert detail["chunkRows"][0]["text"].startswith("GB/T 3087-2022")
    assert detail["chunkRows"][0]["sourceMethod"] == "pymupdf_text_layer"
    assert detail["pageIndexNodes"][0]["id"] == "PIN-FDE-STANDARD-001"
    assert detail["llmUsage"]["scope"] == "standards_knowledge_base"
    assert forbidden["data"]["reason"] == "FORBIDDEN"


def test_fde_vector_corrections_review_apply_and_reject() -> None:
    knowledge_file = repo.find_one("knowledge_files", "KF-DOC-20260625-001")
    knowledge_file["chunkCount"] = 1
    knowledge_file["vectorCount"] = 1
    knowledge_file["vectorStatus"] = "已向量化"
    repo.state["knowledge_chunks"].append(
        {
            "id": "CHK-FDE-CORR-001",
            "fileId": "KF-DOC-20260625-001",
            "documentId": "DOC-20260625-001",
            "documentVersionId": "DV-20260625-001-V2",
            "chunkNo": 1,
            "text": "原始切片文本",
            "pageNo": 1,
            "bbox": [10, 20, 100, 120],
            "tokenCount": 12,
        }
    )
    repo.state["knowledge_vectors"].append(
        {
            "id": "KV-CHK-FDE-CORR-001",
            "fileId": "KF-DOC-20260625-001",
            "chunkId": "CHK-FDE-CORR-001",
            "documentVersionId": "DV-20260625-001-V2",
            "dimensions": 1024,
            "embeddingModel": "Qwen/Qwen3-Embedding-0.6B",
            "indexVersion": "knowledge-index-qwen3-0.6b@1024",
            "embedding": [0.0] * 1024,
        }
    )

    created = assert_ok(
        client.post(
            "/api/fde/vector-corrections",
            json={
                "documentVersionId": "DV-20260625-001-V2",
                "knowledgeFileId": "KF-DOC-20260625-001",
                "chunkId": "CHK-FDE-CORR-001",
                "correctionType": "text",
                "after": {"text": "人工校对后的切片文本"},
                "reason": "抽查发现 OCR 文本缺字",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-vector-correction-create-001"},
        )
    )
    correction_id = created["correction"]["id"]
    detail_after_create = assert_ok(
        client.get(
            "/api/fde/projects/P-2026-HDCP-001/documents/DV-20260625-001-V2/vector-detail",
            headers={"X-Role": "fde"},
        )
    )
    assert detail_after_create["correctionSummary"]["pending"] == 1
    assert detail_after_create["chunkRows"][0]["correctionCount"] == 1

    approved = assert_ok(
        client.post(
            f"/api/fde/vector-corrections/{correction_id}/approve",
            json={"reason": "复核通过"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-vector-correction-approve-001"},
        )
    )
    assert approved["correction"]["status"] == "approved"

    applied = assert_ok(
        client.post(
            f"/api/fde/vector-corrections/{correction_id}/apply",
            json={"reason": "应用并重建向量"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-vector-correction-apply-001"},
        )
    )
    chunk = next(item for item in repo.state["knowledge_chunks"] if item["id"] == "CHK-FDE-CORR-001")
    assert chunk["text"] == "人工校对后的切片文本"
    assert applied["correction"]["status"] == "applied"
    assert applied["file"]["vectorStatus"] == "待向量化"
    assert applied["task"]["taskType"] == "vector"
    assert [item for item in repo.state["knowledge_vectors"] if item.get("chunkId") == "CHK-FDE-CORR-001"] == []

    rejected_seed = assert_ok(
        client.post(
            "/api/fde/vector-corrections",
            json={
                "documentVersionId": "DV-20260625-001-V2",
                "knowledgeFileId": "KF-DOC-20260625-001",
                "chunkId": "CHK-FDE-CORR-001",
                "correctionType": "ignoreChunk",
                "after": {"ignoredByFde": True},
                "reason": "测试驳回",
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-vector-correction-create-002"},
        )
    )
    rejected = assert_ok(
        client.post(
            f"/api/fde/vector-corrections/{rejected_seed['correction']['id']}/reject",
            json={"reason": "保留切片"},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-vector-correction-reject-001"},
        )
    )
    assert rejected["correction"]["status"] == "rejected"
    forbidden = assert_error(
        client.post(
            "/api/fde/vector-corrections",
            json={
                "documentVersionId": "DV-20260625-001-V2",
                "knowledgeFileId": "KF-DOC-20260625-001",
                "chunkId": "CHK-FDE-CORR-001",
                "correctionType": "text",
                "after": {"text": "无权限"},
            },
            headers={"X-Role": "contractor"},
        ),
        "FORBIDDEN",
    )
    assert forbidden["data"]["reason"] == "FORBIDDEN"


def test_fde_vector_file_detail_rejects_unmaterialized_synthetic_document() -> None:
    assert_error(
        client.get(
            "/api/fde/projects/P-2026-GDLNG-002/documents/FDE-DV-2026GDLNG002-4-V1/vector-detail",
            headers={"X-Role": "fde"},
        ),
        "NOT_FOUND",
    )
