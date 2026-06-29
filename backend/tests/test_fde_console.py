from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.mongo = None
    repo.sync_mongo = None


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


def test_fde_login_and_dynamic_routes() -> None:
    login = assert_ok(client.post("/api/auth/login", json={"username": "fde", "password": "fde"}))
    routes = assert_ok(client.get("/api/auth/routes?role=fde"))

    assert login["user"]["role"] == "fde"
    assert login["user"]["defaultPath"] == "/fde/dashboard"
    assert [route["path"] for route in routes] == ["/fde"]
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

    assert triage["feedback"]["status"] == "approved_for_eval"
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
    submitted = assert_ok(
        client.post(
            f"/api/fde/releases/{release['plan']['id']}/submit",
            json={},
            headers={"X-Role": "fde", "Idempotency-Key": "fde-release-submit-001"},
        )
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
    assert release["plan"]["status"] == "submitted"
    assert all(gate["passed"] for gate in submitted["gates"])
    assert shadow["plan"]["status"] == "shadow_running"
    assert canary["plan"]["status"] == "canary_requested"


def test_fde_business_pack_install_rca_and_data_export() -> None:
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
    assert diagnostics["details"]["fields"][0]["status"] == "bbox_mismatch"


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
