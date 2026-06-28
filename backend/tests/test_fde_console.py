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
                {"fieldName": "炉批号", "fieldValue": "H240315A07", "confidence": 0.66, "pageNo": 1}
            ],
            "tables": [{"tableId": "T1", "structureConfidence": 0.86}],
            "seals": [{"sealId": "S1", "sealName": "测试单位章"}],
            "diagnostics": [{"code": "TABLE_STRUCTURE_LOW_CONFIDENCE", "level": "warning"}],
            "engineRuns": [{"engine": "pp_structure_v3", "status": "success"}],
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
    assert quality["failurePools"]["tableFailures"]
    assert runs["items"][0]["id"] == job["id"]
    assert detail["parseResult"]["parseResultId"] == result["parseResultId"]
    assert correction["correction"]["fieldId"] == "FIELD-16-001"
    assert repo.find_one("extracted_fields", "FIELD-16-001")["reviewStatus"] == "已修正"
    assert evaluation["run"]["metrics"]["fileSuccessRate"] == 1


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
