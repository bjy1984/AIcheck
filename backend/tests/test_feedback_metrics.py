"""P12 F2：§17.3 指标全部从真实采集数据算；FDE 看板接口只对 FDE/管理员开放。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.feedback.metrics import compute_feedback_metrics, render_markdown

client = TestClient(app)


def _state() -> dict:
    return {
        "ai_runs": [
            {"id": "A1", "projectId": "P", "nodeId": 1, "findings": [{"groundingStatus": "grounded"}, {"groundingStatus": "insufficient_evidence"}]},
            {"id": "A2", "projectId": "P", "nodeId": 2, "findings": [{"groundingStatus": "insufficient_evidence"}]},
            {"id": "A3", "projectId": "P", "nodeId": 3, "findings": []},
        ],
        "review_opinions": [
            {"projectId": "P", "nodeId": 1, "result": "满足要求", "aiSuggestedResult": "建议满足要求", "overriddenFromAi": False},
            {"projectId": "P", "nodeId": 2, "result": "需补正", "aiSuggestedResult": "建议满足要求", "overriddenFromAi": True},
            {"projectId": "P", "nodeId": 9, "result": "满足要求", "aiSuggestedResult": "需人工确认", "overriddenFromAi": False},
        ],
        "ai_feedback": [
            {"feedbackType": "accepted", "accepted": True, "findingId": "F1", "source": "finding_card"},
            {"feedbackType": "hallucination", "accepted": False, "findingId": "F2", "source": "finding_card"},
            {"feedbackType": "missed_issue", "accepted": False, "source": "conclusion_card"},
            {"feedbackType": "guard_false_downgrade", "accepted": False, "findingId": "F3", "claim": "TS1"},
            {"feedbackType": "edited", "accepted": False, "rootCause": "guard_downgrade", "source": "review_opinion"},
            {"feedbackType": "edited", "accepted": False, "rootCause": "policy", "source": "review_opinion"},
        ],
        "node_evidence_links": [
            {"manualStatus": "confirmed"},
            {"manualStatus": "confirmed"},
            {"manualStatus": "rejected"},
            {"manualStatus": "pending"},
        ],
    }


def test_metrics_follow_the_plan_definitions() -> None:
    metrics = compute_feedback_metrics(_state())
    assert metrics["collectionCoverage"]["value"] == round(2 / 3, 4), "3 个有 AI 审查的节点里 2 个有人工结论"
    assert metrics["adoptionRate"]["value"] == 0.5, "只算 AI 建议能映射的两条：一条采纳一条改判"
    assert metrics["overrideRate"]["value"] == 0.5
    assert metrics["findingPrecision"]["value"] == 0.5
    assert metrics["supplementalFindings"] == 1
    assert metrics["downgradeRate"]["value"] == round(2 / 3, 4)
    assert metrics["falseDowngradeRate"]["value"] == 0.5
    assert metrics["evidenceReferenceAccuracy"]["value"] == round(2 / 3, 4)
    assert metrics["rootCauses"]["guard_downgrade"] == 1 and metrics["rootCauses"]["policy"] == 1 and metrics["rootCauses"]["prompt"] == 0
    assert metrics["rubberStampIndex"] is None
    text = render_markdown(metrics)
    assert "| 采集覆盖率 | 66.7%（2/3） | ≥ 95% |" in text
    assert "guard_downgrade 1" in text


def test_empty_state_gives_null_ratios_not_division_errors() -> None:
    metrics = compute_feedback_metrics({})
    assert metrics["collectionCoverage"]["value"] is None
    assert "—（0/0）" in render_markdown(metrics)


def test_metrics_route_is_fde_only() -> None:
    repo.reset()
    forbidden = client.get("/api/fde/feedback/metrics", headers={"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"})
    assert forbidden.json()["code"] != 0
    allowed = client.get("/api/fde/feedback/metrics", headers={"X-Role": "fde"})
    payload = allowed.json()
    assert payload["code"] == 0, payload
    assert payload["data"]["metrics"]["schemaVersion"] == "FeedbackMetrics@1.0.0"
    assert "| 指标 | 当前值 | 方向 |" in payload["data"]["markdown"]
