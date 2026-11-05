"""节点审计任务队列：状态口径（纯函数）＋接口权限与取数。"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.node_audit_tasks import build_node_audit_tasks

NOW = datetime(2026, 11, 5, 10, 0, 0)  # noqa: DTZ001 -- 与 server_time 同为服务器本地时间口径
NODES = [{"nodeId": node_id, "name": f"节点{node_id}"} for node_id in range(1, 9)]


def ai(run_id: str, node_id: int, status: str, started: str, **extra):
    return {"id": run_id, "nodeId": node_id, "status": status, "startedAt": started, **extra}


def review(run_id: str, node_id: int, status: str, created: str, **extra):
    return {
        "reviewRunId": run_id,
        "nodeId": node_id,
        "status": status,
        "createdAt": created,
        **extra,
    }


def build(ai_runs, review_runs, opinions=(), *, abandoned=(), queue=None, finished_limit=50):
    return build_node_audit_tasks(
        ai_runs=ai_runs,
        review_runs=review_runs,
        opinions=list(opinions),
        nodes=NODES,
        now=NOW,
        looks_abandoned=lambda run: run["reviewRunId"] in abandoned,
        queue_status=lambda run: (queue or {}).get(run["reviewRunId"], {"pending": None}),
        finished_limit=finished_limit,
    )


def by_node(payload):
    return {row["nodeId"]: row for row in payload["items"]}


def test_每个节点一行且状态口径与复核记录一致() -> None:
    outcome_failed = [
        {"atomicCheckId": "A1", "result": "failed", "checks": [{"code": "c1", "passed": False}]}
    ]
    outcome_passed = [{"atomicCheckId": "A1", "result": "passed"}]
    payload = build(
        [
            ai("AI-1", 1, "推理中", "2026-11-05 09:58:00", reviewRunId="RR-1"),
            ai("AI-2", 2, "推理中", "2026-11-05 09:40:00", reviewRunId="RR-2"),
            ai("AI-3", 3, "推理中", "2026-11-05 08:00:00", reviewRunId="RR-3"),
            ai("AI-4", 4, "推理中", "2026-11-05 09:30:00", reviewRunId="RR-4"),
            # 节点 5 跑过两次：旧的失败、新的已完成，只取新的
            ai("AI-5a", 5, "失败", "2026-11-04 09:00:00", reviewRunId="RR-5a"),
            ai("AI-5b", 5, "成功", "2026-11-05 08:00:00", reviewRunId="RR-5b"),
            ai("AI-6", 6, "失败", "2026-11-05 07:00:00", reviewRunId="RR-6"),
            ai("AI-7", 7, "成功", "2026-11-05 06:00:00", reviewRunId="RR-7"),
        ],
        [
            review("RR-1", 1, "queued", "2026-11-05 09:58:00", aiRunId="AI-1"),
            review("RR-2", 2, "running", "2026-11-05 09:40:00", startedAt="2026-11-05 09:50:00"),
            review("RR-3", 3, "queued", "2026-11-05 08:00:00"),
            review(
                "RR-4",
                4,
                "waiting_human_input",
                "2026-11-05 09:30:00",
                startedAt="2026-11-05 09:31:00",
            ),
            review("RR-5a", 5, "failed", "2026-11-04 09:00:00"),
            review(
                "RR-5b",
                5,
                "waiting_human_review",
                "2026-11-05 08:00:00",
                startedAt="2026-11-05 08:01:00",
                finishedAt="2026-11-05 08:09:00",
                atomicCheckOutcomes=outcome_failed,
            ),
            review(
                "RR-6",
                6,
                "failed_to_start",
                "2026-11-05 07:00:00",
                dispatchErrorMessage="broker down",
            ),
            review(
                "RR-7",
                7,
                "completed",
                "2026-11-05 06:00:00",
                startedAt="2026-11-05 06:00:00",
                finishedAt="2026-11-05 06:05:00",
                atomicCheckOutcomes=outcome_passed,
            ),
        ],
        # 节点 7 完成之后监检给了结论；节点 5 的意见早于这次复核，不算确认
        opinions=[
            {"nodeId": 7, "result": "满足要求", "createdAt": "2026-11-05 07:00:00"},
            {"nodeId": 5, "result": "需补正", "createdAt": "2026-11-04 10:00:00"},
        ],
        abandoned={"RR-3"},
        queue={"RR-1": {"pending": True, "ahead": 2}},
    )
    rows = by_node(payload)

    assert set(rows) == {1, 2, 3, 4, 5, 6, 7}  # 节点 8 没跑过复核，不进队列
    assert rows[1]["state"] == "queued" and rows[1]["queueAhead"] == 2
    assert rows[1]["startedAt"] is None and rows[1]["waitSeconds"] == 120
    assert rows[2]["state"] == "running" and rows[2]["elapsedSeconds"] == 600
    # 排队两小时、broker 里也没有：判失败，和 review_run_view 同一口径
    assert rows[3]["state"] == "failed" and rows[3]["stale"] is True
    assert "重新发起" in rows[3]["errorMessage"]
    assert rows[4]["state"] == "needs_input"
    assert rows[5]["state"] == "done" and rows[5]["aiRunId"] == "AI-5b"
    assert rows[5]["result"] == {"group": "failed", "notApplicable": False}
    assert rows[5]["confirmed"] is False and rows[5]["elapsedSeconds"] == 480
    assert rows[6]["state"] == "failed" and rows[6]["errorMessage"] == "broker down"
    assert rows[7]["confirmed"] is True and rows[7]["humanResult"] == "满足要求"

    assert [row["nodeId"] for row in payload["items"]] == [2, 1, 4, 3, 6, 5, 7]
    assert payload["active"] == 2
    assert payload["counts"]["awaitingConfirmation"] == 1
    assert payload["counts"]["failed"] == 2


def test_缺项预审不算待确认且已完成的条数有上限() -> None:
    payload = build(
        [
            ai(f"AI-{n}", n, "成功", f"2026-11-05 0{n}:00:00", reviewRunId=f"RR-{n}")
            for n in (1, 2, 3)
        ],
        [
            review(
                f"RR-{n}",
                n,
                "completed",
                f"2026-11-05 0{n}:00:00",
                finishedAt=f"2026-11-05 0{n}:05:00",
                reviewMode="gap_precheck" if n == 1 else "formal",
                atomicCheckOutcomes=[{"result": "passed"}],
            )
            for n in (1, 2, 3)
        ],
        finished_limit=2,
    )
    assert payload["counts"]["done"] == 3
    assert payload["counts"]["awaitingConfirmation"] == 2
    assert payload["settledTotal"] == 3 and payload["settledShown"] == 2
    # 新完成的在前，超出上限的旧记录不回传
    assert [row["nodeId"] for row in payload["items"]] == [3, 2]


def test_接口只给监检和管理员且只回本项目() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None
    project_id = "P-2026-HDCP-001"
    tenant = repo.require_project(project_id).get("tenantId")
    repo.state.setdefault("ai_runs", []).extend(
        [
            {
                "id": "AI-QUEUE-1",
                "projectId": project_id,
                "nodeId": 24,
                "status": "推理中",
                "startedAt": "2026-11-05 09:00:00",
                "reviewRunId": "RR-QUEUE-1",
                "tenantId": tenant,
            },
            {
                "id": "AI-OTHER",
                "projectId": "P-OTHER",
                "nodeId": 24,
                "status": "推理中",
                "startedAt": "2026-11-05 09:00:00",
                "tenantId": tenant,
            },
        ]
    )
    repo.state.setdefault("review_runs", []).append(
        {
            "reviewRunId": "RR-QUEUE-1",
            "projectId": project_id,
            "nodeId": 24,
            "status": "running",
            "createdAt": "2026-11-05 09:00:00",
            "startedAt": "2026-11-05 09:00:00",
            "updatedAt": "2099-01-01 00:00:00",
            "tenantId": tenant,
        }
    )
    client = TestClient(app)
    url = f"/api/projects/{project_id}/inspection/node-audit-tasks"

    reply = client.get(url, headers={"X-Role": "inspection"}).json()
    assert reply["code"] == 0
    ids = [row["aiRunId"] for row in reply["data"]["items"]]
    assert "AI-QUEUE-1" in ids and "AI-OTHER" not in ids
    row = next(item for item in reply["data"]["items"] if item["aiRunId"] == "AI-QUEUE-1")
    assert row["state"] == "running" and row["nodeName"]

    assert client.get(url, headers={"X-Role": "admin"}).json()["code"] == 0
    assert client.get(url, headers={"X-Role": "contractor"}).json()["code"] in {401, 403}
    assert (
        client.get(
            "/api/projects/P-NOPE/inspection/node-audit-tasks", headers={"X-Role": "inspection"}
        ).json()["code"]
        == 40404
    )
