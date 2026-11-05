"""消息与待办：按角色投递、做完自动关、已读按人记。依赖主业务链路已经走过一次打回和补正。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip

MESSAGE_ROLES = ("inspection", "contractor", "ndt", "owner", "admin")


def messages(ctx: Context, role: str, **params: object) -> list[dict]:
    return items_of(ctx.session(role).ok_get("/api/messages", page=1, pageSize=100, **params))


def todos(ctx: Context, role: str, **params: object) -> list[dict]:
    return items_of(
        ctx.session(role).ok_get("/api/todos", role=role, page=1, pageSize=100, **params)
    )


@api_case(
    "MSG-01",
    "各角色的消息和待办都能读",
    role="inspection,contractor,ndt,owner,admin",
    steps=["各角色 GET /api/messages", "各角色 GET /api/todos?role=<角色>"],
    expected="都成功；每条有标题、内容、时间、已读状态",
    priority="P1",
)
def readable(ctx: Context) -> None:
    for role in MESSAGE_ROLES:
        for item in messages(ctx, role)[:5]:
            check(item.get("title") and "read" in item, f"{role} 的消息缺标题或已读状态：{item}")
        todos(ctx, role)


@api_case(
    "MSG-02",
    "打回后施工方有补正待办、建设方收到通知",
    role="contractor,owner",
    steps=["（主链路已打回节点 24）施工方 GET /api/todos", "建设方 GET /api/messages"],
    expected="施工方有「节点 24 退回补正」待办；建设方有节点 24 退回补正的消息，内容是打回理由",
    priority="P0",
)
def return_notifies(ctx: Context) -> None:
    ctx.need("flow_rectification")
    contractor_todos = [
        item
        for item in todos(ctx, "contractor")
        if int(item.get("nodeId") or 0) == 24 and "补正" in str(item.get("title"))
    ]
    check(contractor_todos, "施工方没有节点 24 的补正待办")
    owner_messages = [
        item for item in messages(ctx, "owner") if "全功能验收" in str(item.get("content"))
    ]
    check(owner_messages, "建设方没收到打回通知")


@api_case(
    "MSG-03",
    "补正提交后施工方的补正待办自动关闭",
    role="contractor",
    steps=["（主链路施工方已补正提交）施工方 GET /api/todos?status=待处理"],
    expected="节点 24 的补正待办不再是「待处理」",
    priority="P0",
)
def todo_auto_close(ctx: Context) -> None:
    ctx.need("flow_rectification")
    still_open = [
        item
        for item in todos(ctx, "contractor", status="待处理")
        if int(item.get("nodeId") or 0) == 24 and "补正" in str(item.get("title"))
    ]
    check(not still_open, f"补正后待办仍是待处理：{[item.get('id') for item in still_open]}")


@api_case(
    "MSG-04",
    "提交后监检有待核验待办，下完结论自动关闭",
    role="inspection",
    steps=["监检 GET /api/todos?role=inspection"],
    expected="有「节点资料已提交，待监检核验」待办，且节点办结后状态为已完成",
    priority="P1",
)
def inspection_todo(ctx: Context) -> None:
    ctx.need("flow_binding")
    submitted = [
        item
        for item in todos(ctx, "inspection")
        if "已提交" in str(item.get("title")) and int(item.get("nodeId") or 0) == 24
    ]
    check(submitted, "监检没有节点 24 的待核验待办")
    check(
        all(item.get("status") != "待处理" for item in submitted), "节点办结后待核验待办仍是待处理"
    )


@api_case(
    "MSG-05",
    "标记已读按人记",
    role="inspection,contractor",
    steps=["监检把一条两人都能看到的消息标为已读", "施工方再看这条消息"],
    expected="监检那边已读；施工方那边仍是未读",
    priority="P1",
    writes=True,
)
def read_per_person(ctx: Context) -> None:
    contractor_ids = {
        str(item.get("id")) for item in messages(ctx, "contractor") if not item.get("read")
    }
    shared = [
        item
        for item in messages(ctx, "inspection")
        if not item.get("read") and str(item.get("id")) in contractor_ids
    ]
    if not shared:
        skip("没有两人都能看到的未读消息")
    message_id = str(shared[0]["id"])
    ctx.session("inspection").ok("POST", f"/api/messages/{message_id}/read")
    mine = {str(item.get("id")): item for item in messages(ctx, "inspection")}
    check(mine[message_id].get("read") is True, "监检标已读后仍是未读")
    theirs = {str(item.get("id")): item for item in messages(ctx, "contractor")}
    check(theirs[message_id].get("read") is False, "监检标已读把施工方的也改成了已读")


@api_case(
    "MSG-06",
    "全部标为已读",
    role="owner",
    steps=["建设方 POST /api/messages/read-all", "GET /api/messages?read=false"],
    expected="成功；建设方不再有未读消息（建设方唯一允许的写操作）",
    priority="P2",
    writes=True,
)
def read_all(ctx: Context) -> None:
    ctx.session("owner").ok("POST", "/api/messages/read-all", json={})
    unread = [item for item in messages(ctx, "owner") if not item.get("read")]
    check(not unread, f"全部已读后仍有 {len(unread)} 条未读")


@api_case(
    "MSG-07",
    "手动完成一条待办",
    role="contractor",
    steps=["施工方取一条待处理待办", "POST /api/todos/{待办}/complete（说明）"],
    expected="待办变为已完成，带上完成说明",
    priority="P2",
    writes=True,
)
def complete_todo(ctx: Context) -> None:
    pending = todos(ctx, "contractor", status="待处理")
    if not pending:
        skip("施工方没有待处理待办")
    todo_id = str(pending[0]["id"])
    ctx.session("contractor").ok(
        "POST", f"/api/todos/{todo_id}/complete", json={"comment": "全功能验收：已处理"}
    )
    after = {str(item.get("id")): item for item in todos(ctx, "contractor")}
    check(after.get(todo_id, {}).get("status") != "待处理", "完成后待办仍是待处理")
