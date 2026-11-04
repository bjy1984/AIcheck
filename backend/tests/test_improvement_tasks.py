"""意见反馈 → 送平台审批 → 平台审批 → AI 领取修复 → 上线关闭（2026-11-04）。

两个院端到端：广东院和平台院各提一条，院管理员送平台；平台合并重复、审批、AI 领取回报、标上线、关闭，
进度回写到两个院各自的反馈里。每个用例收尾都跑一遍落库前的院标记检查（夹具来自 test_platform_institutes）。
"""
from __future__ import annotations

from libs import improvement_tasks as it
from libs import institutes
from libs.db.repository import repo
from tests.test_platform_institutes import (  # noqa: F401 -- isolated 是自动夹具，导入即生效
    GD,
    PLATFORM,
    bearer,
    client,
    code_of,
    data,
    isolated,
    open_gdtj,
)

ID_NUMBER = "110101199003071237"  # 校验位正确的示例号


def submit(headers: dict, content: str, key: str) -> str:
    body = data(client.post("/api/user-feedback", headers={**headers, "Idempotency-Key": key},
                            json={"category": "audit_accuracy", "content": content, "context": {"page": "/workbench", "nodeId": "24"}}))
    return body["feedback"]["id"]


def escalate(headers: dict, feedback_id: str, key: str, scope: str = "public") -> str:
    return data(client.post(f"/api/admin/user-feedback/{feedback_id}/escalate", headers={**headers, "Idempotency-Key": key},
                            json={"scope": scope, "note": "多个项目都遇到"}))["taskId"]


def tasks(status: str | None = None) -> list[dict]:
    return data(client.get("/api/platform/improvement-tasks" + (f"?status={status}" if status else ""), headers=PLATFORM))["items"]


def act(task_id: str, verb: str, body: dict, key: str):
    return client.post(f"/api/platform/improvement-tasks/{task_id}/{verb}", headers={**PLATFORM, "Idempotency-Key": key}, json=body)


def my_feedback(headers: dict, feedback_id: str) -> dict:
    items = data(client.get("/api/user-feedback/mine", headers=headers))["items"]
    return next(row for row in items if row["id"] == feedback_id)


def test_两个院的同类反馈送平台_合并_审批_AI修复_上线关闭_进度回写各院():
    gd = bearer(open_gdtj())
    gd_feedback = submit(gd, f"焊工证查不到登记，身份证 {ID_NUMBER}，联系 13812345678", "f1")
    platform_feedback = submit(PLATFORM, "焊工证登记查询失败", "f2")
    gd_task = escalate(gd, gd_feedback, "e1")
    platform_task = escalate(PLATFORM, platform_feedback, "e2")

    assert my_feedback(gd, gd_feedback)["status"] == "escalated"
    assert my_feedback(gd, gd_feedback)["platformTask"]["statusLabel"] == "待平台审批"
    pending = {row["id"]: row for row in tasks("pending_review")}
    source = pending[gd_task]["sources"][0]
    assert source["sourceTenantId"] == GD and "submittedBy" not in source
    assert ID_NUMBER not in source["contentRedacted"] and "13812345678" not in source["contentRedacted"]
    assert "1101**********1237" in source["contentRedacted"] and "138****5678" in source["contentRedacted"]
    assert pending[gd_task]["sourceInstitutes"] == ["广东特检院"]

    # 重复合并：平台院那条并进广东院那条，两个院都挂在一条任务上
    data(act(platform_task, "merge", {"intoTaskId": gd_task}, "m1"))
    merged = next(row for row in tasks() if row["id"] == gd_task)
    assert merged["sourceTenantCount"] == 2
    assert my_feedback(PLATFORM, platform_feedback)["platformTask"]["taskId"] == gd_task

    # 审批：没有任务描述和验收标准不让过
    assert code_of(act(gd_task, "approve", {"taskStatement": "", "acceptanceCriteria": ""}, "a0")) != 0
    data(act(gd_task, "approve", {"title": "焊工证登记查询失败", "taskStatement": "公示平台查询失败时按需人工确认，不判证据不足",
                                  "acceptanceCriteria": "R24 用例通过；评测不低于基线", "priority": "P1"}, "a1"))
    assert my_feedback(gd, gd_feedback)["platformTask"]["statusLabel"] == "待开发"

    # AI：领取锁定、别人领不了；任务包按任务描述干活，不带提交人
    data(act(gd_task, "claim", {"agent": "claude-code"}, "c1"))
    assert code_of(act(gd_task, "claim", {"agent": "codex"}, "c2")) != 0, "已被领取"
    packet = data(client.get(f"/api/platform/improvement-tasks/{gd_task}", headers=PLATFORM))["packet"]
    assert packet["taskStatement"].startswith("公示平台") and len(packet["sources"]) == 2 and packet["rules"]
    assert all("submittedBy" not in src and ID_NUMBER not in src["contentRedacted"] for src in packet["sources"])
    assert code_of(act(gd_task, "submit", {"prUrl": "", "tests": ""}, "s0")) != 0, "回报要带 PR 和测试结果"
    data(act(gd_task, "submit", {"prUrl": "https://github.com/x/y/pull/1", "commit": "abc1234", "tests": "R24 12 passed"}, "s1"))

    # 人：合并部署后标上线，确认后关闭 → 两个院的反馈都变成已解决并收到回复
    assert code_of(act(gd_task, "status", {"status": "closed"}, "x0")) != 0, "要先上线才能关闭"
    data(act(gd_task, "status", {"status": "deployed"}, "x1"))
    data(act(gd_task, "status", {"status": "closed"}, "x2"))
    for headers, feedback_id in ((gd, gd_feedback), (PLATFORM, platform_feedback)):
        row = my_feedback(headers, feedback_id)
        assert row["status"] == "resolved" and row["reply"]["content"].startswith("平台已修复并上线")


def test_院管理员看不到平台队列_已送平台的不能再送也不能在院里改():
    gd = bearer(open_gdtj())
    feedback_id = submit(gd, "总览加载很慢，要等好几秒", "f1")
    escalate(gd, feedback_id, "e1")
    assert code_of(client.get("/api/platform/improvement-tasks", headers=gd)) != 0
    again = client.post(f"/api/admin/user-feedback/{feedback_id}/escalate", headers={**gd, "Idempotency-Key": "e2"}, json={})
    assert code_of(again) != 0
    reply = client.post(f"/api/admin/user-feedback/{feedback_id}/reply", headers={**gd, "Idempotency-Key": "r1"},
                        json={"status": "resolved", "reply": "已解决"})
    assert code_of(reply) != 0


def test_暂不采纳要写理由并回复提交人_重新打开要写原因():
    gd = bearer(open_gdtj())
    feedback_id = submit(gd, "希望报告抬头用本院名称", "f1")
    task_id = escalate(gd, feedback_id, "e1", scope="gray")
    assert code_of(act(task_id, "decline", {"reason": ""}, "d0")) != 0
    data(act(task_id, "decline", {"reason": "这是院级配置：在报告模板里改抬头"}, "d1"))
    row = my_feedback(gd, feedback_id)
    assert row["status"] == "declined" and "报告模板" in row["reply"]["content"]


def test_审核不通过重新打开_AI重领_领取超时自动释放():
    gd = bearer(open_gdtj())
    task_id = escalate(gd, submit(gd, "节点 24 结论和资料不符", "f1"), "e1")
    data(act(task_id, "approve", {"taskStatement": "修正 R24", "acceptanceCriteria": "评测不低于基线"}, "a1"))
    data(act(task_id, "claim", {"agent": "codex"}, "c1"))
    data(act(task_id, "submit", {"prUrl": "https://github.com/x/y/pull/2", "tests": "ok"}, "s1"))
    assert code_of(act(task_id, "status", {"status": "approved"}, "r0")) != 0, "重新打开要写原因"
    data(act(task_id, "status", {"status": "approved", "note": "PR 改错了规则"}, "r1"))
    data(act(task_id, "claim", {"agent": "claude-code"}, "c2"))
    with institutes.platform_scope() as state:
        task = next(row for row in state[it.COLLECTION] if row["id"] == task_id)
        task["claim"]["expiresAt"] = "2000-01-01 00:00:00"
    assert next(row for row in tasks() if row["id"] == task_id)["status"] == "approved", "超时按待开发显示"
    data(act(task_id, "claim", {"agent": "codex"}, "c3"))


def test_任务只存在平台院_来源院不写进tenantId():
    gd = bearer(open_gdtj())
    task_id = escalate(gd, submit(gd, "OCR 读错焊工项目代号", "f1"), "e1")
    with institutes.tenant_scope(GD) as state:
        assert not state.get(it.COLLECTION), "广东院里没有任务"
    with institutes.platform_scope() as state:
        task = next(row for row in state[it.COLLECTION] if row["id"] == task_id)
        assert task["sources"][0]["sourceTenantId"] == GD and task.get("tenantId") in {None, institutes.platform_tenant_id()}
    assert repo.state is not None
