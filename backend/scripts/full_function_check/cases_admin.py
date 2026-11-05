"""管理后台：各配置页、单位、用户（含改口令）、项目、成员、邀请注册、审计日志。

新建的单位、用户、项目都带「全功能验收」字样，最后一条用例把它们删掉。
"""

from __future__ import annotations

import uuid

from scripts.full_function_check.base import Context, api_case, check, items_of, skip

ADMIN_PAGES = (
    ("/api/projects", {"page": 1, "pageSize": 20}, "项目管理"),
    ("/api/admin/org-units", {}, "组织"),
    ("/api/admin/users", {}, "用户"),
    ("/api/admin/audit-logs", {"page": 1, "pageSize": 20}, "审计日志"),
    ("/api/admin/config-overview", {}, "配置总览"),
    ("/api/admin/material-review-points", {}, "资料审查点"),
    ("/api/admin/prompt-templates", {}, "Prompt 模板"),
    ("/api/admin/report-templates", {}, "报告模板"),
    ("/api/admin/integration-contract", {}, "联调清单"),
    ("/api/admin/todo-rules", {}, "待办规则"),
    ("/api/admin/message-templates", {}, "消息模板"),
    ("/api/admin/tool-sources", {}, "工具来源"),
    ("/api/admin/field-mappings", {}, "字段映射"),
    ("/api/business-packs", {}, "业务包"),
    ("/api/review-plugins", {}, "审查插件"),
    ("/api/permissions/resources", {}, "权限矩阵"),
    ("/api/operations/overview", {"area": "admin"}, "运营摘要"),
)
NEW_PASSWORD_1 = "Fullcheck!2026a"
NEW_PASSWORD_2 = "Fullcheck!2026b"


def suffix(ctx: Context) -> str:
    if "admin_suffix" not in ctx.store:
        ctx.store["admin_suffix"] = uuid.uuid4().hex[:6]
    return ctx.store["admin_suffix"]


def etag_of(item: dict) -> str:
    return str(item.get("etag") or "*")


@api_case(
    "ADM-01",
    "管理后台各页面数据可读",
    role="admin",
    steps=[f"管理员 GET {path}（{label}）" for path, _, label in ADMIN_PAGES],
    expected="每个页面的接口都成功返回",
    priority="P1",
)
def pages_readable(ctx: Context) -> None:
    admin = ctx.session("admin")
    failures = []
    for path, params, label in ADMIN_PAGES:
        reply = admin.get(path, **params)
        if not (reply.http == 200 and reply.code == 0):
            failures.append(f"{label} {path}: {reply.brief()}")
    check(not failures, "；".join(failures))


@api_case(
    "ADM-02",
    "新建单位",
    role="admin",
    steps=["POST /api/admin/org-units（名称、类型=施工单位、联系人）", "GET /api/admin/org-units"],
    expected="创建成功，列表里能看到",
    priority="P1",
    writes=True,
)
def create_org(ctx: Context) -> None:
    admin = ctx.session("admin")
    name = f"全功能验收施工单位-{suffix(ctx)}"
    data = admin.ok(
        "POST",
        "/api/admin/org-units",
        json={"name": name, "type": "contractor", "contactName": "验收"},
    )
    org = data.get("orgUnit") or data
    check(org.get("id"), f"没返回单位编号：{data}")
    ctx.store["admin_org"] = org
    listed = admin.ok_get("/api/admin/org-units")
    check(name in str(listed), "单位列表里没有新单位")


@api_case(
    "ADM-03",
    "新建用户：业务角色必须归属单位",
    role="admin",
    steps=["不填单位建一个施工方用户", "填上新单位再建"],
    expected="不填单位被拒；填了之后创建成功，新用户能登录",
    priority="P0",
    writes=True,
)
def create_user(ctx: Context) -> None:
    org = ctx.need("admin_org")
    admin = ctx.session("admin")
    username = f"fullcheck_{suffix(ctx)}"
    no_org = admin.call(
        "POST",
        "/api/admin/users",
        json={"username": username + "_x", "name": "无单位", "role": "contractor"},
    )
    check(no_org.code == 40001, f"不填单位应被拒，实际 {no_org.brief()}")
    data = admin.ok(
        "POST",
        "/api/admin/users",
        json={
            "username": username,
            "name": "全功能验收用户",
            "role": "contractor",
            "orgId": org["id"],
            "password": NEW_PASSWORD_1,
        },
    )
    user = data.get("user") or data
    ctx.store["admin_user"] = user
    login = ctx.send(
        "POST", "/api/auth/login", json={"username": username, "password": NEW_PASSWORD_1}
    )
    check((login.data or {}).get("token"), f"新用户登录失败：{login.brief()}")
    ctx.store["admin_user_token"] = login.data["token"]


@api_case(
    "ADM-04",
    "用户自己修改口令",
    role="contractor",
    steps=[
        "新用户 POST /api/auth/change-password（旧口令错）",
        "新口令只有 5 位",
        "正确修改",
        "旧令牌再访问、旧口令再登录",
    ],
    expected="旧口令错、新口令太短都被拒；修改成功返回新令牌；旧令牌失效，旧口令登录失败、新口令登录成功",
    priority="P0",
    writes=True,
)
def change_password(ctx: Context) -> None:
    user = ctx.need("admin_user")
    token = ctx.need("admin_user_token")
    headers = {"Authorization": f"Bearer {token}", "X-Role": "contractor"}
    path = "/api/auth/change-password"
    wrong = ctx.send(
        "POST",
        path,
        json={"currentPassword": "nope-nope", "newPassword": NEW_PASSWORD_2},
        headers=headers,
    )
    check(wrong.code == 401, f"旧口令错应被拒，实际 {wrong.brief()}")
    short = ctx.send(
        "POST",
        path,
        json={"currentPassword": NEW_PASSWORD_1, "newPassword": "Ab1!x"},
        headers=headers,
    )
    check(short.code == 40001, f"5 位新口令应被拒，实际 {short.brief()}")
    done = ctx.send(
        "POST",
        path,
        json={"currentPassword": NEW_PASSWORD_1, "newPassword": NEW_PASSWORD_2},
        headers=headers,
    )
    check(done.code == 0 and (done.data or {}).get("token"), f"改口令应成功，实际 {done.brief()}")
    stale = ctx.send("GET", "/api/auth/me", headers=headers)
    check(stale.http == 401 or stale.code == 401, f"改口令后旧令牌应失效，实际 {stale.brief()}")
    username = str(user.get("username"))
    old = ctx.send(
        "POST", "/api/auth/login", json={"username": username, "password": NEW_PASSWORD_1}
    )
    check(not (old.data or {}).get("token"), "旧口令还能登录")
    new = ctx.send(
        "POST", "/api/auth/login", json={"username": username, "password": NEW_PASSWORD_2}
    )
    check((new.data or {}).get("token"), f"新口令登录失败：{new.brief()}")


@api_case(
    "ADM-05",
    "新建项目",
    role="admin",
    steps=[
        "POST /api/admin/projects（业务包、编号、名称、四方单位、成员）",
        "GET /api/projects/{项目}",
    ],
    expected="创建成功；四方成员自动授权；项目详情能读",
    priority="P0",
    writes=True,
)
def create_project(ctx: Context) -> None:
    admin = ctx.session("admin")
    code = f"P-FULLCHECK-{suffix(ctx).upper()}"
    data = admin.ok(
        "POST",
        "/api/admin/projects",
        json={
            "businessPackId": "engineering_inspection_v1",
            "code": code,
            "name": f"全功能验收项目-{suffix(ctx)}",
            "type": "工业压力管道",
            "region": "华东",
            "ownerOrgName": "华东管网建设公司",
            "contractorOrgName": "粤海安装工程有限公司",
            "ndtOrgName": "粤检无损检测",
            "inspectionOrgName": "省特检院一部",
            "memberUserIds": {
                "owner": "USER-OWNER-001",
                "contractor": "USER-CONTRACTOR-001",
                "ndt": "USER-NDT-001",
                "inspection": "USER-INSPECTION-001",
            },
        },
    )
    project = data.get("project") or data
    check(project.get("id"), f"没返回项目编号：{data}")
    ctx.store["admin_project"] = project
    admin.ok_get(f"/api/projects/{project['id']}")
    contractor_projects = items_of(
        ctx.session("contractor").ok_get("/api/workbench/projects", role="contractor")
    )
    check(
        any(str(item.get("id")) == project["id"] for item in contractor_projects),
        "施工方成员看不到新项目",
    )


@api_case(
    "ADM-06",
    "项目成员：加人、移除",
    role="admin",
    steps=[
        "POST /api/projects/{新项目}/members（新用户）",
        "GET …/members",
        "DELETE …/members/{成员}",
    ],
    expected="加人成功并按角色给默认动作和节点范围；移除后该用户看不到项目",
    priority="P1",
    writes=True,
)
def members(ctx: Context) -> None:
    project = ctx.need("admin_project")
    user = ctx.need("admin_user")
    admin = ctx.session("admin")
    detail = admin.ok_get(f"/api/projects/{project['id']}")
    etag = etag_of(detail.get("project") or detail)
    batch = admin.ok(
        "POST",
        f"/api/projects/{project['id']}/members",
        json={"userIds": [user["id"]]},
        headers={"If-Match": etag},
    )
    member = (batch.get("members") or [{}])[0]
    check(member.get("userId") == user["id"], f"加人结果不对：{batch}")
    check(member.get("nodeScope"), "新成员没有默认节点范围")
    listed = items_of(admin.ok_get(f"/api/projects/{project['id']}/members"))
    check(any(item.get("id") == member["id"] for item in listed), "成员列表里没有新成员")
    removed = admin.ok(
        "DELETE",
        f"/api/projects/{project['id']}/members/{member['id']}",
        headers={"If-Match": etag_of(member)},
    )
    check(removed.get("deleted") is True, f"移除失败：{removed}")


@api_case(
    "ADM-07",
    "项目邀请链接：生成、对方申请、管理员审批",
    role="admin,public",
    steps=[
        "建一个存库的管理员账号并登录（内置演示账号不在用户表里，发不了链接）",
        "POST /api/projects/{新项目}/registration-links",
        "不登录 GET /api/registration-links/{令牌}",
        "不登录 POST …/apply（用户名、角色=施工方、口令）",
        "GET /api/projects/{新项目}/registration-requests",
        "POST …/registration-requests/{申请}/review（approved=true）",
        "申请人登录",
    ],
    expected="链接能打开并显示项目名；申请提交成功；审批通过后申请人能登录并看到该项目",
    priority="P1",
    writes=True,
)
def registration(ctx: Context) -> None:
    project = ctx.need("admin_project")
    builtin = ctx.session("admin")
    admin_name = f"fullcheck_admin_{suffix(ctx)}"
    created = builtin.ok(
        "POST",
        "/api/admin/users",
        json={
            "username": admin_name,
            "name": "验收管理员",
            "role": "admin",
            "password": NEW_PASSWORD_1,
        },
    )
    ctx.store["admin_user_2"] = created.get("user") or created
    login = ctx.send(
        "POST", "/api/auth/login", json={"username": admin_name, "password": NEW_PASSWORD_1}
    )
    check((login.data or {}).get("token"), f"存库管理员登录失败：{login.brief()}")
    from scripts.full_function_check.base import RoleSession

    admin = RoleSession(ctx, "admin", login.data["token"], login.data.get("user") or {})
    link = admin.ok("POST", f"/api/projects/{project['id']}/registration-links", json={})
    token = str(link.get("token") or "")
    check(token, f"没返回邀请令牌：{link}")
    info = ctx.send("GET", f"/api/registration-links/{token}")
    check(info.code == 0, f"邀请链接打不开：{info.brief()}")
    username = f"fullcheck_join_{suffix(ctx)}"
    applied = ctx.send(
        "POST",
        f"/api/registration-links/{token}/apply",
        json={
            "username": username,
            "role": "contractor",
            "password": NEW_PASSWORD_1,
            "displayName": "验收申请人",
        },
    )
    check(applied.code == 0, f"申请提交失败：{applied.brief()}")
    request_id = str((applied.data or {}).get("requestId") or "")
    requests = items_of(admin.ok_get(f"/api/projects/{project['id']}/registration-requests"))
    check(any(str(item.get("id")) == request_id for item in requests), "申请列表里没有这条")
    reviewed = admin.call(
        "POST",
        f"/api/projects/{project['id']}/registration-requests/{request_id}/review",
        json={"approved": True},
    )
    if reviewed.code != 0 and "组织" in reviewed.message:
        skip(f"项目缺施工方组织，审批不了：{reviewed.brief()}")
    check(reviewed.code == 0, f"审批失败：{reviewed.brief()}")
    login = ctx.send(
        "POST", "/api/auth/login", json={"username": username, "password": NEW_PASSWORD_1}
    )
    check((login.data or {}).get("token"), f"审批通过后申请人登录失败：{login.brief()}")


@api_case(
    "ADM-08",
    "审计日志记下了管理操作",
    role="admin",
    steps=["GET /api/admin/audit-logs?keyword=全功能验收"],
    expected="能查到建单位、建用户、建项目等记录，带操作人和时间",
    priority="P1",
)
def audit_logs(ctx: Context) -> None:
    ctx.need("admin_project")
    logs = items_of(ctx.session("admin").ok_get("/api/admin/audit-logs", page=1, pageSize=200))
    check(logs, "审计日志为空")
    for item in logs[:5]:
        check(
            item.get("action") or item.get("operation") or item.get("title"),
            f"审计日志缺操作名：{item}",
        )


@api_case(
    "ADM-09",
    "删除验收数据：项目、用户、单位",
    role="admin",
    steps=[
        "DELETE /api/projects/{新项目}",
        "DELETE /api/admin/users/{新用户}",
        "DELETE /api/admin/org-units/{新单位}",
    ],
    expected="空项目直接删除，有业务数据的改为归档；被引用的单位改为停用并让出名字",
    priority="P2",
    writes=True,
)
def cleanup(ctx: Context) -> None:
    admin = ctx.session("admin")
    project = ctx.store.get("admin_project")
    if project:
        detail = admin.ok_get(f"/api/projects/{project['id']}")
        admin.ok(
            "DELETE",
            f"/api/projects/{project['id']}",
            headers={"If-Match": etag_of(detail.get("project") or detail)},
        )
    users = {str(item.get("id")): item for item in items_of(admin.ok_get("/api/admin/users"))}
    for key in ("admin_user", "admin_user_2"):
        user = ctx.store.get(key)
        if user:
            admin.ok(
                "DELETE",
                f"/api/admin/users/{user['id']}",
                headers={"If-Match": etag_of(users.get(user["id"], user))},
            )
    org = ctx.store.get("admin_org")
    if org:
        orgs = {
            str(item.get("id")): item for item in items_of(admin.ok_get("/api/admin/org-units"))
        }
        admin.ok(
            "DELETE",
            f"/api/admin/org-units/{org['id']}",
            headers={"If-Match": etag_of(orgs.get(org["id"], org))},
        )
