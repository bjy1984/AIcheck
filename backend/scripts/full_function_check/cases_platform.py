"""平台（多院）：开通新院、院管理员登录、数据隔离、停用启用、加管理员、重置口令、同步规则。"""

from __future__ import annotations

import uuid

from scripts.full_function_check.base import Context, api_case, check, items_of

FIRST_PASSWORD = "Institute!2026a"
CHANGED_PASSWORD = "Institute!2026c"
RESET_PASSWORD = "Institute!2026b"


def institute(ctx: Context) -> dict:
    return ctx.need("institute")


def login_institute(ctx: Context, username: str, password: str, tenant_id: str):
    return ctx.send(
        "POST",
        "/api/auth/login",
        json={"username": username, "password": password, "tenantId": tenant_id},
    )


@api_case(
    "PLAT-01",
    "平台管理员查看各院",
    role="admin",
    steps=["平台管理员 GET /api/platform/institutes"],
    expected="列出各院（编号、名称、状态、管理员）",
    priority="P1",
)
def list_institutes(ctx: Context) -> None:
    data = ctx.session("admin").ok_get("/api/platform/institutes")
    check(isinstance(data, dict | list), "院列表格式不对")


@api_case(
    "PLAT-02",
    "开通新院，院管理员能登录本院",
    role="admin",
    steps=[
        "POST /api/platform/institutes（编号、名称、管理员账号和初始口令）",
        "用新院管理员账号登录（tenantId=TENANT-编号）",
        "直接读项目",
        "按要求先改口令，再读项目",
    ],
    expected="开通成功；首次登录必须先改口令（改之前业务接口返回 40301）；改完后正常使用",
    priority="P0",
    writes=True,
    in_process_only=True,
)
def open_institute(ctx: Context) -> None:
    code = f"FC{uuid.uuid4().hex[:4].upper()}"
    admin_username = f"fc-admin-{code.lower()}"
    data = ctx.session("admin").ok(
        "POST",
        "/api/platform/institutes",
        json={
            "code": code,
            "name": f"全功能验收特检院{code}",
            "adminUsername": admin_username,
            "adminName": "验收院管理员",
            "adminPassword": FIRST_PASSWORD,
        },
    )
    tenant_id = str(
        (data or {}).get("tenantId")
        or (data.get("institute") or {}).get("tenantId")
        or f"TENANT-{code}"
    )
    ctx.store["institute"] = {"tenantId": tenant_id, "admin": admin_username, "code": code}
    login = login_institute(ctx, admin_username, FIRST_PASSWORD, tenant_id)
    check((login.data or {}).get("token"), f"新院管理员登录失败：{login.brief()}")
    check((login.data.get("user") or {}).get("role") == "admin", "新院管理员登录后不是管理员角色")
    first_headers = {"Authorization": f"Bearer {login.data['token']}", "X-Role": "admin"}
    gated = ctx.send("GET", "/api/projects", headers=first_headers)
    check(gated.code == 40301, f"首次登录没改口令就能用业务接口：{gated.brief()}")
    changed = ctx.send(
        "POST",
        "/api/auth/change-password",
        json={"currentPassword": FIRST_PASSWORD, "newPassword": CHANGED_PASSWORD},
        headers=first_headers,
    )
    check(
        changed.code == 0 and (changed.data or {}).get("token"),
        f"首次改口令失败：{changed.brief()}",
    )
    ctx.store["institute_token"] = changed.data["token"]


@api_case(
    "PLAT-03",
    "新院看不到别的院的项目",
    role="admin",
    steps=["新院管理员 GET /api/projects"],
    expected="项目列表为空，看不到默认院的演示项目",
    priority="P0",
    in_process_only=True,
)
def isolation(ctx: Context) -> None:
    item = institute(ctx)
    token = ctx.need("institute_token")
    reply = ctx.send(
        "GET",
        "/api/projects",
        params={"page": 1, "pageSize": 50},
        headers={"Authorization": f"Bearer {token}", "X-Role": "admin"},
    )
    check(reply.code == 0, f"新院管理员读项目失败：{reply.brief()}")
    leaked = [p.get("id") for p in items_of(reply.data) if str(p.get("id")) in ctx.need("projects")]
    check(not leaked, f"新院看到了默认院的项目：{leaked}（{item['tenantId']}）")


@api_case(
    "PLAT-04",
    "新院管理员不能用平台功能",
    role="admin",
    steps=["新院管理员 GET /api/platform/institutes"],
    expected="被拒（只有平台管理员能管各院）",
    priority="P0",
    in_process_only=True,
)
def not_platform_admin(ctx: Context) -> None:
    token = ctx.need("institute_token")
    reply = ctx.send(
        "GET",
        "/api/platform/institutes",
        headers={"Authorization": f"Bearer {token}", "X-Role": "admin"},
    )
    check(
        reply.http in (401, 403) or reply.code in (401, 403),
        f"院管理员不该能看平台院列表，实际 {reply.brief()}",
    )


@api_case(
    "PLAT-05",
    "停用院后不能登录，启用后恢复",
    role="admin",
    steps=[
        "POST /api/platform/institutes/{院}/status（disabled）",
        "院管理员登录",
        "再改回 active 并登录",
    ],
    expected="停用后登录被拒（单位未开通或已停用）；启用后能登录",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def disable_enable(ctx: Context) -> None:
    item = institute(ctx)
    admin = ctx.session("admin")
    path = f"/api/platform/institutes/{item['tenantId']}/status"
    admin.ok("POST", path, json={"status": "disabled"})
    blocked = login_institute(ctx, item["admin"], CHANGED_PASSWORD, item["tenantId"])
    check(not (blocked.data or {}).get("token"), "停用的院还能登录")
    admin.ok("POST", path, json={"status": "active"})
    back = login_institute(ctx, item["admin"], CHANGED_PASSWORD, item["tenantId"])
    check((back.data or {}).get("token"), f"启用后登录失败：{back.brief()}")


@api_case(
    "PLAT-06",
    "给院加管理员、重置管理员口令",
    role="admin",
    steps=[
        "POST /api/platform/institutes/{院}/admins（第二个管理员）",
        "POST …/admins/{原管理员}/reset-password（新口令）",
        "原管理员用新口令登录",
    ],
    expected="加管理员成功、能登录；重置后旧口令失效、新口令可用",
    priority="P1",
    writes=True,
    in_process_only=True,
)
def admins(ctx: Context) -> None:
    item = institute(ctx)
    admin = ctx.session("admin")
    second = f"{item['admin']}-2"
    admin.ok(
        "POST",
        f"/api/platform/institutes/{item['tenantId']}/admins",
        json={"username": second, "name": "第二管理员", "password": FIRST_PASSWORD},
    )
    check(
        (login_institute(ctx, second, FIRST_PASSWORD, item["tenantId"]).data or {}).get("token"),
        "第二个管理员登录失败",
    )
    admin.ok(
        "POST",
        f"/api/platform/institutes/{item['tenantId']}/admins/{item['admin']}/reset-password",
        json={"password": RESET_PASSWORD},
    )
    check(
        not (
            login_institute(ctx, item["admin"], CHANGED_PASSWORD, item["tenantId"]).data or {}
        ).get("token"),
        "重置后旧口令还能登录",
    )
    check(
        (login_institute(ctx, item["admin"], RESET_PASSWORD, item["tenantId"]).data or {}).get(
            "token"
        ),
        "重置后新口令登录失败",
    )


@api_case(
    "PLAT-07",
    "平台把规则同步到各院",
    role="admin",
    steps=["POST /api/platform/institutes/sync-rules"],
    expected="成功；返回同步到的院和规则版本",
    priority="P2",
    writes=True,
    in_process_only=True,
)
def sync_rules(ctx: Context) -> None:
    ctx.session("admin").ok("POST", "/api/platform/institutes/sync-rules", json={})
