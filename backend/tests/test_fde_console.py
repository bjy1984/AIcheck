from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import fde_ocr_100_action_handoff_snapshot
from libs.db.repository import repo


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


def test_fde_login_and_dynamic_routes() -> None:
    login = assert_ok(client.post("/api/auth/login", json={"username": "fde", "password": "fde"}))
    routes = assert_ok(client.get("/api/auth/routes?role=fde"))

    assert login["user"]["role"] == "fde"
    assert login["user"]["defaultPath"] == "/fde/projects"
    assert [route["path"] for route in routes] == ["/fde"]
    assert routes[0]["children"][0]["path"] == "projects"
    assert routes[0]["children"][0]["component"] == "views/AICheck/FdeConsole"


def test_fde_dashboard_and_masked_ai_run_detail() -> None:
    dashboard = assert_ok(client.get("/api/fde/dashboard", headers={"X-Role": "fde"}))
    detail = assert_ok(client.get("/api/fde/ai-runs/AIRUN-24-20260625-01", headers={"X-Role": "fde"}))

    assert {item["label"] for item in dashboard["metrics"]} >= {"AI Run", "采纳率", "证据命中率", "误报率", "疑似漏报率"}
    assert detail["run"]["immutable"] is True
    assert detail["run"]["rawAccess"] is False
    assert detail["run"]["inputHash"].startswith("sha256:")
    assert detail["run"]["outputHash"].startswith("sha256:")
    assert detail["traceSteps"]
    assert detail["accessPolicy"]["rawAccessRequiresGrant"] is True


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
            headers={"X-Role": "inspection", "Idempotency-Key": "review-run-decision-001"},
        )
    )

    assert ai_run["dispatch"]["mode"] == "inline"
    assert business_view["run"]["workflowEngine"] == "inline_temporal_compatible"
    assert business_view["run"]["graphEngine"] in {"langgraph", "langgraph_fallback"}
    assert business_view["run"]["graphRunner"] in {"langgraph", "manual"}
    assert business_view["run"]["modelGateway"] == "litellm"
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
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "litellm")

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
        if item.get("reviewRunId") == review_run_id and item.get("toolName") == "call_litellm_chat"
    ]

    assert run["status"] == "waiting_human_review"
    assert run["findingDrafts"][0]["findingType"] == "field_missing"
    assert run["findingDrafts"][0]["severity"] == "high"
    assert run["findingDrafts"][0]["requiresHumanConfirmation"] is True
    assert run["findingDrafts"][0]["llmGenerated"] is True
    assert tool_calls and tool_calls[0]["allowed"] is True


def test_fde_review_run_visualization_replay_and_shadow(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "inline")
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
            headers={"X-Role": "inspection", "Idempotency-Key": "fde-review-decision-001"},
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
            json={"expiresAt": "9999-12-31 23:59:59"},
            headers={"X-Role": "admin", "Idempotency-Key": "fde-access-approve-001"},
        )
    )
    raw = assert_ok(client.get("/api/fde/ai-runs/AIRUN-24-20260625-01", headers={"X-Role": "fde"}))

    assert masked["run"]["rawAccess"] is False
    assert grant["grant"]["status"] == "pending"
    assert approved["grant"]["status"] == "approved"
    assert raw["run"]["rawAccess"] is True


def test_fde_evaluation_report_and_release_state_machine() -> None:
    evaluation = assert_ok(
        client.post(
            "/api/fde/evaluation-runs",
            json={"evaluationSetId": "ESET-GOLDEN-ENGINEERING-001", "capabilityBundleId": "BUNDLE-REVIEW-202606"},
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
            json={},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-submit-001"},
        )
    )
    approved = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/approve",
            json={"comment": "评估、风险集和回滚计划满足灰度前置条件。"},
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
            json={"sampleRate": 0},
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
            json={"tenantId": "demo", "dryRun": True},
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
            json={"status": "open", "rootCause": "low_quality_scan"},
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
    assert workspace["reviewRuns"]
    review_run = workspace["reviewRuns"][0]
    assert review_run["graphSummary"]["total"] >= 1
    assert review_run["graphAuditSummary"]["nodeCount"] >= 1
    assert review_run["graphAuditSummary"]["edgeCount"] >= 1
    assert review_run["graphAuditSummary"]["timelineCount"] >= 1
    assert review_run["graphAuditSummary"]["workflowEngine"]
    assert review_run["graphAuditSummary"]["graphEngine"] == "langgraph"
    assert "artifactSummary" in review_run["graphAuditSummary"]
    assert workspace["ocrAnnotationTasks"]
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
    assert detail["summary"]["nodeId"] == node_id
    assert "bindings" in detail


def test_fde_project_audit_workspace_supplies_backend_projection_data() -> None:
    workspace = assert_ok(
        client.get(
            "/api/fde/projects/P-2026-GDLNG-002/audit-workspace?nodeId=16",
            headers={"X-Role": "fde"},
        )
    )

    assert workspace["metrics"]["documents"] >= 4
    assert workspace["metrics"]["knowledgeChunks"] >= 100
    assert workspace["metrics"]["knowledgeVectors"] >= 80
    assert workspace["metrics"]["pageIndexNodes"] >= 4
    assert workspace["metrics"]["ocrJobs"] >= 4
    assert workspace["metrics"]["annotationTasks"] >= 4
    assert {item["fileName"] for item in workspace["documents"]} >= {
        "管道特性表-第2版.png",
        "质量证明书-QX201903S.pdf",
        "RT检测报告-焊口清单.pdf",
        "焊工资格证与外部查询截图.pdf",
    }
    assert any(item["profileId"] == "piping_characteristic_list_v1" for item in workspace["ocrJobs"])
    assert any(item["profileId"] == "seal_text_profile_v1" for item in workspace["ocrAnnotationTasks"])
    assert any(item["vectorCount"] < item["chunkCount"] for item in workspace["documents"])
    assert workspace["knowledgeLineage"]["retrievalTraceCount"] >= 1
    assert workspace["knowledgeLineage"]["pageIndexTraceCount"] >= 1
    assert any(item["readiness"] == "needs_attention" for item in workspace["knowledgeLineage"]["documents"])
    assert workspace["reviewRuns"]

    review_run_id = workspace["reviewRuns"][0]["reviewRunId"]
    detail = assert_ok(client.get(f"/api/fde/review-runs/{review_run_id}", headers={"X-Role": "fde"}))
    graph = detail["graph"]

    assert detail["run"]["workflowEngine"] == "temporal"
    assert detail["run"]["graphEngine"] == "langgraph"
    assert detail["run"]["graphExecution"]["checkpointer"] == "postgres"
    assert detail["scorecard"]["score"] == 100
    assert detail["lineage"]["reasoningPolicy"] == "show_audit_summary_not_raw_chain_of_thought"
    assert len(graph["nodes"]) >= 12
    assert graph["artifactSummary"]["toolCalls"] >= 5
    assert graph["artifactSummary"]["retrievalTraces"] >= 2
    assert graph["artifactSummary"]["pageIndexTraces"] >= 1
    assert graph["artifactSummary"]["findingDrafts"] >= 2
    assert detail["reasoningTrace"]
    assert all("rawChainOfThought" not in item for item in detail["reasoningTrace"])

    ocr_job_id = workspace["ocrJobs"][0]["jobId"]
    ocr_detail = assert_ok(client.get(f"/api/fde/ocr-runs/{ocr_job_id}", headers={"X-Role": "fde"}))
    assert ocr_detail["job"]["jobId"] == ocr_job_id
    assert ocr_detail["parseResult"]["parseResultId"] == workspace["ocrJobs"][0]["parseResultId"]
    assert ocr_detail["parseResult"]["preprocessStatus"]["generatedVariants"]
    assert ocr_detail["parseResult"]["fields"]
    assert ocr_detail["parseResult"]["tables"]
    assert ocr_detail["parseResult"]["seals"]
    assert ocr_detail["parseResult"]["diagnostics"]


def test_fde_synthetic_ocr_job_detail_can_be_opened_directly() -> None:
    review_detail = assert_ok(
        client.get(
            "/api/fde/review-runs/RR-AUDIT-P-2026-GDLNG-002-16",
            headers={"X-Role": "fde"},
        )
    )
    detail = assert_ok(
        client.get(
            "/api/fde/ocr-runs/OCR-JOB-FDE-2026GDLNG002-1",
            headers={"X-Role": "fde"},
        )
    )

    assert review_detail["run"]["reviewRunId"] == "RR-AUDIT-P-2026-GDLNG-002-16"
    assert review_detail["run"]["workflowEngine"] == "temporal"
    assert review_detail["run"]["graphExecution"]["checkpointer"] == "postgres"
    assert review_detail["graph"]["artifactSummary"]["pageIndexTraces"] >= 1
    assert detail["job"]["jobId"] == "OCR-JOB-FDE-2026GDLNG002-1"
    assert detail["parseResult"]["profileId"] == "piping_characteristic_list_v1"
    assert "table_line_enhanced" in detail["parseResult"]["preprocessStatus"]["generatedVariants"]
    assert detail["parseResult"]["quality"]["status"] in {"auto_usable", "needs_human_review"}


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
                "targetScope": {"tenantIds": ["demo"], "businessPackIds": ["engineering_inspection_v1"], "projectIds": []},
            },
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-100-001"},
        )
    )
    release_id = release["plan"]["id"]
    impact = assert_ok(client.get(f"/api/fde/releases/{release_id}/impact", headers={"X-Role": "fde"}))
    shadow = assert_ok(
        client.post(
            f"/api/fde/releases/{release_id}/start-shadow",
            json={"sampleRate": 0},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-shadow-100"},
        )
    )
    shadow_passed = assert_ok(
        client.post(
            f"/api/fde/releases/{release_id}/mark-shadow-passed",
            json={"metrics": {"failedRuns": 0}},
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
