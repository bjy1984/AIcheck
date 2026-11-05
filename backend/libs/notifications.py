"""待办与消息：谁该做什么、谁该知道什么（2026-11-04）。

## 原来的问题（2026-11-04 盘点）

- 待办几乎全发给监检；施工方只在被退回补正时收到一条，建设方什么都收不到。
- 消息根本不由业务事件产生：唯一会写消息的是每周盲审提醒。
- 待办建了就永远「待处理」：监检审完了「待监检核验」还挂着，施工方补交了
  「退回补正」也还在，只能手动点完成——徽标数字因此越攒越多。
- 消息只有一个全局 read：任何一人点「全部已读」，全项目的人都成了已读。
- 项目没有监检成员时 assigneeName 写成「待分配」，按名字匹配谁都对不上，
  除管理员外没人看得见。

## 口径

- **待办**：要这个角色动手的事，带 `assigneeRole` 与 `kind`。该做的事一做完，
  由对应的业务动作自动关掉（`close_todos`），不靠人记得去点。
  带了 assigneeRole 的按角色投递：这个项目里该角色的人都看得见（团队收件箱），
  assigneeName 只用来显示。
- **消息**：只是告知，带 `recipientRoles`；已读按人记（`readBy`）。
  同一件事（`dedupeKey`）再次发生时更新原消息并重新标成未读，不刷屏。
- 老记录（没有 assigneeRole / recipientRoles）按原来的口径：
  待办按责任人名字，消息全项目可见；老消息的全局 read 视作所有人已读。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time

PENDING = "待处理"
DONE = "已完成"
UNASSIGNED_NAMES = {"", "待分配"}

# 监检「审这份资料」类待办：节点下了结论或退回后就算办完了
REVIEW_KINDS = frozenset({"submission_review", "resubmission_review", "ndt_submission_review", "ndt_resubmission_review"})
RECTIFICATION_KINDS = frozenset({"rectification"})
NDT_MATERIAL_CATEGORY = "无损检测资料"


def _bump(record: dict[str, Any], now: str) -> None:
    record["revision"] = int(record.get("revision") or 1) + 1
    record["updatedAt"] = now


def _node_ids(record: dict[str, Any]) -> set[int]:
    ids = {int(value) for value in record.get("nodeIds") or [] if str(value).isdigit()}
    if str(record.get("nodeId") or "").isdigit():
        ids.add(int(record["nodeId"]))
    return ids


# ── 待办 ────────────────────────────────────────────────────────────────


def open_todo(
    state: dict[str, Any],
    *,
    kind: str,
    project_id: str,
    title: str,
    target_type: str,
    target_id: str | None,
    assignee_role: str,
    assignee_name: str = "",
    node_id: int | None = None,
    node_ids: list[int] | None = None,
    priority: str = "中",
    actions: list[str] | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """新建一条待办并放到最前；同一 dedupeKey 还开着就复用那一条。"""
    todos = state.setdefault("todos", [])
    now = server_time()
    if dedupe_key:
        existing = next(
            (item for item in todos if item.get("dedupeKey") == dedupe_key and item.get("status", PENDING) == PENDING),
            None,
        )
        if existing:
            existing["title"] = title
            _bump(existing, now)
            return existing
    todo: dict[str, Any] = {
        "id": f"TODO-{uuid4().hex[:8].upper()}",
        "kind": kind,
        "title": title,
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": target_type,
        "targetId": target_id,
        "status": PENDING,
        "priority": priority,
        "assigneeRole": assignee_role,
        # 没人可派时留空：「待分配」是个非空名字，按名字匹配谁都对不上，结果谁都看不见
        "assigneeName": "" if str(assignee_name or "").strip() in UNASSIGNED_NAMES else str(assignee_name),
        "actions": list(actions or []),
        "createdAt": now,
    }
    if node_ids is not None:
        todo["nodeIds"] = list(node_ids)
    if dedupe_key:
        todo["dedupeKey"] = dedupe_key
    todos.insert(0, todo)
    return todo


def _legacy_kind(todo: dict[str, Any]) -> str:
    """老待办没有 kind：按它当时的写法认回来，好让这次一起关掉。"""
    target = str(todo.get("targetType") or "")
    if target == "submission":
        return "submission_review"
    if target == "rectification":
        return "rectification"
    if target == "report":
        return "report_review"
    return ""


def close_todos(
    state: dict[str, Any],
    *,
    project_id: str,
    kinds: Iterable[str],
    node_id: int | None = None,
    target_id: str | None = None,
    dedupe_key: str | None = None,
    assignee_role: str | None = None,
    reason: str,
) -> list[str]:
    """把已经办完的待办关掉，返回关掉的 id。按节点、目标、dedupeKey、责任角色收窄。

    一条待办管着几个节点时（一次提交多个节点），按节点关要等每个节点都办完。"""
    wanted = set(kinds)
    now = server_time()
    closed: list[str] = []
    for todo in state.get("todos") or []:
        if not isinstance(todo, dict) or todo.get("projectId") != project_id:
            continue
        if todo.get("status", PENDING) != PENDING:
            continue
        if (todo.get("kind") or _legacy_kind(todo)) not in wanted:
            continue
        if target_id is not None and str(todo.get("targetId") or "") != str(target_id):
            continue
        if dedupe_key is not None and todo.get("dedupeKey") != dedupe_key:
            continue
        if assignee_role is not None and todo.get("assigneeRole") != assignee_role:
            continue
        if node_id is not None:
            nodes = _node_ids(todo)
            if int(node_id) not in nodes:
                continue
            done_nodes = {int(value) for value in todo.get("doneNodeIds") or []} | {int(node_id)}
            if not nodes <= done_nodes:
                todo["doneNodeIds"] = sorted(done_nodes)
                _bump(todo, now)
                continue
        todo["status"] = DONE
        todo["completedAt"] = now
        todo["closedBy"] = "系统"
        todo["closeReason"] = reason
        _bump(todo, now)
        closed.append(str(todo.get("id")))
    return closed


def pending(todos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """徽标只数还要办的：已完成、已延期的原来也算进去了。"""
    return [item for item in todos if isinstance(item, dict) and item.get("status", PENDING) == PENDING]


# ── 消息 ────────────────────────────────────────────────────────────────


def notify(
    state: dict[str, Any],
    *,
    kind: str,
    project_id: str,
    title: str,
    content: str,
    recipient_roles: Iterable[str],
    node_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any] | None:
    roles = sorted({str(role) for role in recipient_roles if role})
    if not roles:
        return None
    messages = state.setdefault("messages", [])
    now = server_time()
    if dedupe_key:
        existing = next((item for item in messages if item.get("dedupeKey") == dedupe_key), None)
        if existing:
            existing.update({"title": title, "content": content, "recipientRoles": roles, "createdAt": now})
            existing["readBy"] = {}
            existing["read"] = False
            existing.pop("readAt", None)
            _bump(existing, now)
            messages.remove(existing)
            messages.insert(0, existing)
            return existing
    message: dict[str, Any] = {
        "id": f"MSG-{uuid4().hex[:8].upper()}",
        "kind": kind,
        "title": title,
        "content": content,
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": target_type,
        "targetId": target_id,
        "recipientRoles": roles,
        "readBy": {},
        "read": False,
        "createdAt": now,
    }
    if dedupe_key:
        message["dedupeKey"] = dedupe_key
    messages.insert(0, message)
    return message


def message_visible_to(message: dict[str, Any], role: str) -> bool:
    if str(role or "") == "admin":
        return True
    roles = message.get("recipientRoles")
    return not roles or str(role or "") in roles


def visible_messages(messages: Iterable[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [item for item in messages if isinstance(item, dict) and message_visible_to(item, role)]


def _reader(user_id: str | None) -> str:
    """认不出是谁（未开鉴权的本机 / 测试环境）时统一记成 anonymous，读写用同一个键。"""
    return str(user_id or "anonymous")


def message_read_by(message: dict[str, Any], user_id: str) -> bool:
    read_by = message.get("readBy")
    if isinstance(read_by, dict):
        return _reader(user_id) in read_by
    return message.get("read") is True  # 老消息：全局已读


def message_view(message: dict[str, Any], user_id: str) -> dict[str, Any]:
    """给某个人看的样子：read / readAt 是他自己的，不是全项目的。"""
    view = dict(message)
    read_by = message.get("readBy")
    view.pop("readBy", None)
    view["read"] = message_read_by(message, user_id)
    if isinstance(read_by, dict):
        view["readAt"] = read_by.get(_reader(user_id))
    return view


def mark_read(message: dict[str, Any], user_id: str) -> bool:
    """记成这个人已读；返回是否有变化。"""
    if message_read_by(message, user_id):
        return False
    now = server_time()
    read_by = message.get("readBy")
    if not isinstance(read_by, dict):
        read_by = {}
        message["readBy"] = read_by
    read_by[_reader(user_id)] = now
    _bump(message, now)
    return True


def unread_count(messages: Iterable[dict[str, Any]], user_id: str) -> int:
    return sum(1 for item in messages if isinstance(item, dict) and not message_read_by(item, user_id))


# ── 业务事件 → 待办 / 消息 ─────────────────────────────────────────────


def material_role(document: dict[str, Any] | None) -> str:
    """资料是谁交的：无损检测资料归无损检测单位，其余归施工方。"""
    category = str((document or {}).get("materialCategory") or "").strip()
    return "ndt" if category == NDT_MATERIAL_CATEGORY else "contractor"


def node_concluded(state: dict[str, Any], *, project_id: str, node_id: int, result: str, node_name: str = "") -> None:
    """监检保存了节点结论：审资料的待办办完了；施工方、无损检测、建设方都该知道结论。"""
    close_todos(state, project_id=project_id, kinds=REVIEW_KINDS, node_id=node_id, reason=f"监检已下结论：{result}")
    label = f"节点 {node_id}{f' {node_name}' if node_name else ''}"
    notify(
        state,
        kind="node_conclusion",
        project_id=project_id,
        node_id=node_id,
        title=f"{label} 审查结论：{result}",
        content=f"监检已对{label}下结论「{result}」。",
        recipient_roles=("contractor", "ndt", "owner"),
        target_type="node",
        target_id=str(node_id),
        dedupe_key=f"conclusion:{project_id}:{node_id}",
    )


def correction_returned(state: dict[str, Any], *, project_id: str, node_id: int, mode: str, reason: str) -> None:
    """退回补正 / 发起补充资料：监检这一轮审完了；建设方要知道这个节点被退回。
    施工方（或无损检测）的待办由调用方用 open_todo 建，这里不重复发消息。"""
    action = "补充资料" if mode == "supplement_request" else "退回补正"
    close_todos(state, project_id=project_id, kinds=REVIEW_KINDS, node_id=node_id, reason=f"监检已{action}")
    notify(
        state,
        kind="node_correction",
        project_id=project_id,
        node_id=node_id,
        title=f"节点 {node_id} {action}",
        content=str(reason or "")[:300] or f"监检对节点 {node_id} {action}。",
        recipient_roles=("owner",),
        target_type="node",
        target_id=str(node_id),
        dedupe_key=f"correction:{project_id}:{node_id}",
    )


def correction_resubmitted(state: dict[str, Any], *, project_id: str, node_id: int, rectification_id: str | None) -> None:
    """施工方 / 无损检测交了补正：他们那条「退回补正」办完了。"""
    close_todos(
        state,
        project_id=project_id,
        kinds=RECTIFICATION_KINDS,
        node_id=node_id,
        target_id=rectification_id or None,
        reason="补正资料已重新提交",
    )


def ndt_correction_submitted(
    state: dict[str, Any], *, project_id: str, node_id: int, feedback_id: str, assignee_name: str = ""
) -> None:
    """无损检测交了补正：它的「退回补正」办完了；监检要复审（原来什么都不给监检）。"""
    close_todos(
        state, project_id=project_id, kinds=RECTIFICATION_KINDS, node_id=node_id, assignee_role="ndt",
        reason="无损检测补正已提交",
    )
    open_todo(
        state,
        kind="ndt_resubmission_review",
        project_id=project_id,
        node_id=node_id,
        title=f"节点 {node_id} 无损检测补正已提交，待复审",
        target_type="ndt_feedback",
        target_id=feedback_id,
        assignee_role="inspection",
        assignee_name=assignee_name,
        priority="高",
        actions=["review:save"],
        dedupe_key=f"ndt-resubmission:{project_id}:{node_id}:{feedback_id}",
    )


def evidence_decided(
    state: dict[str, Any],
    *,
    project_id: str,
    node_id: int,
    link: dict[str, Any],
    status: str,
    document: dict[str, Any] | None,
) -> None:
    """监检确认 / 不采用某份资料：交资料的一方要知道「监检已经看过、结论是什么」。

    只发消息、不建待办：不采用常常是系统把资料挂错了审查点，不是交资料的人做错了；
    真要对方补交，监检会退回补正，那一步才建待办。
    """
    file_name = str(link.get("fileName") or (document or {}).get("fileName") or "资料")
    document_key = str(link.get("documentId") or link.get("documentVersionId") or file_name)
    confirmed = status == "confirmed"
    comment = str(link.get("manualComment") or "").strip()
    notify(
        state,
        kind="evidence_decision",
        project_id=project_id,
        node_id=node_id,
        title=f"节点 {node_id}「{file_name}」{'已确认' if confirmed else '未被采用'}",
        content=(
            f"监检已确认「{file_name}」可作为节点 {node_id} 的审查依据。"
            if confirmed
            else f"监检没有采用「{file_name}」作为节点 {node_id} 的审查依据{f'：{comment}' if comment else '。'}"
        ),
        recipient_roles=(material_role(document),),
        target_type="node",
        target_id=str(node_id),
        dedupe_key=f"evidence:{project_id}:{node_id}:{document_key}",
    )


def report_archived(state: dict[str, Any], *, project_id: str, report: dict[str, Any]) -> None:
    """报告归档：复核待办办完了；各方都该知道报告已出。"""
    report_id = str(report.get("id") or "")
    close_todos(state, project_id=project_id, kinds={"report_review"}, target_id=report_id, reason="报告已归档")
    title = str(report.get("title") or "监检报告")
    notify(
        state,
        kind="report_archived",
        project_id=project_id,
        node_id=(report.get("nodeIds") or [None])[0],
        title=f"报告已归档：{title}",
        content=f"「{title}」已签发归档，可在归档区查看和下载。",
        recipient_roles=("contractor", "ndt", "owner"),
        target_type="report",
        target_id=report_id,
        dedupe_key=f"report:{project_id}:{report_id}",
    )


def uploads_received(
    state: dict[str, Any], *, project_id: str, uploader_role: str, file_count: int
) -> dict[str, Any] | None:
    """施工方 / 无损检测传了资料但还没提交：告诉监检有资料进来了，按天合并成一条。"""
    if uploader_role not in {"contractor", "ndt"} or file_count <= 0:
        return None
    who = "无损检测单位" if uploader_role == "ndt" else "施工方"
    day = server_time()[:10]
    key = f"uploads:{project_id}:{uploader_role}:{day}"
    existing = next((item for item in state.get("messages") or [] if item.get("dedupeKey") == key), None)
    total = int((existing or {}).get("fileCount") or 0) + int(file_count)
    message = notify(
        state,
        kind="uploads_received",
        project_id=project_id,
        title=f"{who}今天上传了 {total} 份资料",
        content=f"{who}今天上传了 {total} 份资料，还没有提交审查；提交后会出现在你的待办里。",
        recipient_roles=("inspection",),
        target_type="project",
        target_id=project_id,
        dedupe_key=key,
    )
    if message is not None:
        message["fileCount"] = total
    return message
