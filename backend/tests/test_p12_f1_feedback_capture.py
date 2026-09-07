"""P12 F1 采集补全：发现级反馈、"其实有依据"、人工结论不一致的根因，都落 ai_feedback。

2026-09-06 生产核实：采纳/驳回 AI 建议不落库、证据链驳回发常量字符串，117 次 AI 审查
无一条人工纠正可供迭代。这里钉的是采集字段真的进库，以及"采纳一条发现"不等于"确认整次运行"。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)
RUN_ID = "AIRUN-24-20260625-01"


def setup_function() -> None:
    repo.reset()


def _post(body: dict, key: str):
    response = client.post(
        f"/api/ai/runs/{RUN_ID}/feedback",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]


def test_finding_level_accept_records_finding_id_but_does_not_confirm_the_run() -> None:
    before = repo.find_one("ai_runs", RUN_ID)["status"]
    data = _post(
        {"feedbackType": "accepted", "accepted": True, "findingId": "FND-1", "source": "finding_card"},
        "f1-accept-finding",
    )
    assert data["feedback"]["findingId"] == "FND-1"
    assert data["feedback"]["source"] == "finding_card"
    assert data["aiRun"]["status"] == before, "采纳单条发现不代表认可整次结论"
    stored = next(item for item in repo.state["ai_feedback"] if item["id"] == data["feedback"]["id"])
    assert stored["findingId"] == "FND-1"


def test_run_level_accept_still_confirms_the_run() -> None:
    data = _post({"feedbackType": "accepted", "accepted": True, "source": "adopt_suggestion"}, "f1-accept-run")
    assert data["aiRun"]["status"] == "已人工确认"


def test_claim_supported_and_override_root_cause_are_stored() -> None:
    supported = _post(
        {
            "feedbackType": "guard_false_downgrade",
            "accepted": False,
            "findingId": "FND-2",
            "claim": "TS9999999-2030",
            "comment": "安装许可证扫描件 第 1 页 证书编号栏",
            "source": "insufficient_group",
        },
        "f1-claim",
    )
    assert supported["feedback"]["claim"] == "TS9999999-2030"
    assert supported["feedback"]["feedbackType"] == "guard_false_downgrade"

    override = _post(
        {
            "feedbackType": "edited",
            "accepted": False,
            "rootCause": "guard_downgrade",
            "suggestedResult": "证据不足",
            "humanResult": "满足要求",
            "comment": "AI 结论其实有依据，却被判成证据不足",
            "source": "review_opinion",
        },
        "f1-override",
    )
    assert override["feedback"]["rootCause"] == "guard_downgrade"
    assert override["feedback"]["suggestedResult"] == "证据不足"
    assert override["feedback"]["humanResult"] == "满足要求"


def test_unknown_root_cause_is_rejected_with_the_allowed_list() -> None:
    response = client.post(
        f"/api/ai/runs/{RUN_ID}/feedback",
        json={"feedbackType": "edited", "accepted": False, "rootCause": "vibes"},
        headers={"Idempotency-Key": "f1-bad-root-cause"},
    )
    payload = response.json()
    assert payload["code"] != 0
    assert "guard_downgrade" in payload["data"]["allowedRootCauses"]
