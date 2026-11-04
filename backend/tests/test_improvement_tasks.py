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


def claim(task_id: str, agent: str, key: str) -> str:
    return data(act(task_id, "claim", {"agent": agent}, key))["task"]["claim"]["id"]


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
    claim_id = claim(gd_task, "claude-code", "c1")
    assert code_of(act(gd_task, "claim", {"agent": "codex"}, "c2")) != 0, "已被领取"
    packet = data(client.get(f"/api/platform/improvement-tasks/{gd_task}", headers=PLATFORM))["packet"]
    assert packet["taskStatement"].startswith("公示平台") and len(packet["sources"]) == 2 and packet["rules"]
    assert all("submittedBy" not in src and ID_NUMBER not in src["contentRedacted"] for src in packet["sources"])
    assert code_of(act(gd_task, "submit", {"prUrl": "", "tests": "", "claimId": claim_id}, "s0")) != 0, "回报要带 PR 和测试结果"
    assert code_of(act(gd_task, "submit", {"prUrl": "https://github.com/x/y/pull/1", "tests": "ok"}, "s00")) != 0, \
        "不带领取号交不了"
    data(act(gd_task, "submit", {"prUrl": "https://github.com/x/y/pull/1", "commit": "abc1234", "tests": "R24 12 passed",
                                 "claimId": claim_id}, "s1"))

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
    data(act(task_id, "approve", {"title": "R24 结论不符", "taskStatement": "修正 R24", "acceptanceCriteria": "评测不低于基线"}, "a1"))
    first = claim(task_id, "codex", "c1")
    data(act(task_id, "submit", {"prUrl": "https://github.com/x/y/pull/2", "tests": "ok", "claimId": first}, "s1"))
    assert code_of(act(task_id, "status", {"status": "approved"}, "r0")) != 0, "重新打开要写原因"
    data(act(task_id, "status", {"status": "approved", "note": "PR 改错了规则，电话 13812345678"}, "r1"))
    packet = data(client.get(f"/api/platform/improvement-tasks/{task_id}", headers=PLATFORM))["packet"]
    assert "PR 改错了规则" in packet["reopenNote"] and "13812345678" not in packet["reopenNote"], "重开原因脱敏后给 AI"
    stale = claim(task_id, "claude-code", "c2")
    with institutes.platform_scope() as state:
        task = next(row for row in state[it.COLLECTION] if row["id"] == task_id)
        task["claim"]["expiresAt"] = "2000-01-01 00:00:00"
    assert next(row for row in tasks() if row["id"] == task_id)["status"] == "approved", "超时按待开发显示"
    fresh = claim(task_id, "codex", "c3")
    assert fresh != stale
    # 过期的领取人不能再交、也不能释放别人的领取（2026-11-04 审计）
    assert code_of(act(task_id, "submit", {"prUrl": "https://github.com/x/y/pull/9", "tests": "ok", "claimId": stale}, "s2")) != 0
    assert code_of(act(task_id, "release", {"claimId": stale}, "l1")) != 0
    data(act(task_id, "release", {"claimId": fresh}, "l2"))


def test_审批必须写标题_标题之前平台任务不回写反馈原文():
    gd = bearer(open_gdtj())
    feedback_id = submit(gd, "张三的工程节点 24 有问题", "f1")
    task_id = escalate(gd, feedback_id, "e1")
    assert "张三" not in str(my_feedback(gd, feedback_id)["platformTask"].get("title") or "")
    assert code_of(act(task_id, "approve", {"taskStatement": "修", "acceptanceCriteria": "过"}, "a0")) != 0, "要写标题"
    data(act(task_id, "approve", {"title": "节点 24 结论偏差", "taskStatement": "修", "acceptanceCriteria": "过"}, "a1"))
    assert my_feedback(gd, feedback_id)["platformTask"]["title"] == "节点 24 结论偏差"


def test_任务只存在平台院_来源院不写进tenantId():
    gd = bearer(open_gdtj())
    task_id = escalate(gd, submit(gd, "OCR 读错焊工项目代号", "f1"), "e1")
    with institutes.tenant_scope(GD) as state:
        assert not state.get(it.COLLECTION), "广东院里没有任务"
    with institutes.platform_scope() as state:
        task = next(row for row in state[it.COLLECTION] if row["id"] == task_id)
        assert task["sources"][0]["sourceTenantId"] == GD and task.get("tenantId") in {None, institutes.platform_tenant_id()}
    assert repo.state is not None


def _deployed_task_with_two_sources(gd: dict) -> tuple[str, str, str]:
    gd_feedback = submit(gd, "焊工证登记查询失败", "cf1")
    platform_feedback = submit(PLATFORM, "焊工证登记查不到", "cf2")
    task_id = escalate(gd, gd_feedback, "ce1")
    data(act(escalate(PLATFORM, platform_feedback, "ce2"), "merge", {"intoTaskId": task_id}, "cm1"))
    data(act(task_id, "approve", {"title": "焊工证查询", "taskStatement": "修查询", "acceptanceCriteria": "用例通过"}, "ca1"))
    claim_id = claim(task_id, "codex", "cc1")
    data(act(task_id, "submit", {"prUrl": "https://github.com/x/y/pull/3", "tests": "ok", "claimId": claim_id}, "cs1"))
    data(act(task_id, "status", {"status": "deployed"}, "cd1"))
    return task_id, gd_feedback, platform_feedback


def confirm(headers: dict, feedback_id: str, key: str, **body):
    return client.post(f"/api/user-feedback/{feedback_id}/confirm", headers={**headers, "Idempotency-Key": key}, json=body)


def test_提交人都确认已解决才自动关闭():
    gd = bearer(open_gdtj())
    task_id, gd_feedback, platform_feedback = _deployed_task_with_two_sources(gd)
    assert my_feedback(gd, gd_feedback)["platformTask"]["status"] == "deployed"
    data(confirm(gd, gd_feedback, "k1", resolved=True))
    # 只记确认、不提前标已解决（2026-11-04 审计：提前标已解决，院管理员能再送一次平台）
    row = my_feedback(gd, gd_feedback)
    assert row["status"] == "escalated" and row["submitterConfirmation"]["resolved"] is True
    assert next(row for row in tasks() if row["id"] == task_id)["status"] == "deployed", "另一个院还没确认"
    assert code_of(client.post(f"/api/admin/user-feedback/{gd_feedback}/escalate", headers={**gd, "Idempotency-Key": "k1e"},
                               json={})) != 0, "确认后也不能再送平台"
    data(confirm(PLATFORM, platform_feedback, "k2", resolved=True))
    assert next(row for row in tasks() if row["id"] == task_id)["status"] == "closed"
    assert my_feedback(gd, gd_feedback)["status"] == "resolved"
    assert my_feedback(PLATFORM, platform_feedback)["reply"]["content"].startswith("平台已修复并上线")


def test_提交人说仍有问题_任务重新打开_原因脱敏给AI():
    gd = bearer(open_gdtj())
    task_id, gd_feedback, _ = _deployed_task_with_two_sources(gd)
    assert code_of(confirm(gd, gd_feedback, "k0", resolved=False)) != 0, "要写哪里不对"
    data(confirm(gd, gd_feedback, "k1", resolved=False, note="还是查不到，电话 13812345678"))
    detail = data(client.get(f"/api/platform/improvement-tasks/{task_id}", headers=PLATFORM))
    assert detail["task"]["status"] == "approved" and "138****5678" in detail["task"]["reopenNote"]
    assert "138****5678" in detail["packet"]["reopenNote"], "AI 的任务包里看得到重开原因"
    assert my_feedback(gd, gd_feedback)["status"] == "escalated"


def test_关闭后再重新打开_反馈回到已送平台_上线后能再确认():
    gd = bearer(open_gdtj())
    task_id, gd_feedback, platform_feedback = _deployed_task_with_two_sources(gd)
    data(confirm(gd, gd_feedback, "k1", resolved=True))
    data(confirm(PLATFORM, platform_feedback, "k2", resolved=True))
    assert my_feedback(gd, gd_feedback)["status"] == "resolved"
    data(act(task_id, "status", {"status": "approved", "note": "线上复现了"}, "r1"))
    row = my_feedback(gd, gd_feedback)
    assert row["status"] == "escalated" and not row.get("submitterConfirmation"), "旧确认作废"
    again = claim(task_id, "codex", "c9")
    data(act(task_id, "submit", {"prUrl": "https://github.com/x/y/pull/4", "tests": "ok", "claimId": again}, "s9"))
    data(act(task_id, "status", {"status": "deployed"}, "d9"))
    data(confirm(gd, gd_feedback, "k3", resolved=True))


def test_没上线不能确认_别人的反馈不能确认():
    gd = bearer(open_gdtj())
    feedback_id = submit(gd, "测试确认边界", "f1")
    escalate(gd, feedback_id, "e1")
    assert code_of(confirm(gd, feedback_id, "k1", resolved=True)) != 0
    assert code_of(confirm(PLATFORM, feedback_id, "k2", resolved=True)) != 0, "别的院的人看不到这条"


def test_字符串false不算已解决_领取过期后审批清掉领取_反馈里显示待开发():
    gd = bearer(open_gdtj())
    _, gd_feedback, _ = _deployed_task_with_two_sources(gd)
    assert code_of(confirm(gd, gd_feedback, "k1", resolved="false")) != 0, "\"false\" 是仍有问题，要写原因"
    assert my_feedback(gd, gd_feedback)["status"] == "escalated"

    feedback_id = submit(gd, "领取过期的显示测试", "x1")
    other = escalate(gd, feedback_id, "x2")
    data(act(other, "approve", {"title": "显示测试", "taskStatement": "修", "acceptanceCriteria": "过"}, "x3"))
    claim(other, "codex", "x4")
    assert my_feedback(gd, feedback_id)["platformTask"]["statusLabel"] == "开发中"
    with institutes.platform_scope() as state:
        next(row for row in state[it.COLLECTION] if row["id"] == other)["claim"]["expiresAt"] = "2000-01-01 00:00:00"
    with institutes.tenant_scope(institutes.find_institute("TENANT-GDTJ")["id"]) as state:
        row = next(item for item in state["user_feedback"] if item["id"] == feedback_id)
        row["platformTask"]["claimExpiresAt"] = "2000-01-01 00:00:00"
    assert my_feedback(gd, feedback_id)["platformTask"]["statusLabel"] == "待开发", "领取过期后不再显示开发中"
    data(act(other, "approve", {"title": "显示测试", "taskStatement": "再修", "acceptanceCriteria": "过"}, "x5"))
    detail = data(client.get(f"/api/platform/improvement-tasks/{other}", headers=PLATFORM))["task"]
    assert detail["claim"] is None and detail["status"] == "approved"
