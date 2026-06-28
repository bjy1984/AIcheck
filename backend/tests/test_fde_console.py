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

    assert {item["label"] for item in dashboard["metrics"]} >= {"AI Run", "采纳率", "证据命中率"}
    assert detail["run"]["immutable"] is True
    assert detail["run"]["rawAccess"] is False
    assert detail["run"]["inputHash"].startswith("sha256:")
    assert detail["run"]["outputHash"].startswith("sha256:")
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
