"""登录与账号、权限与数据隔离。"""

from __future__ import annotations

from scripts.full_function_check.base import ROLE_LABELS, Context, api_case, check, items_of, skip

ROLES = ("inspection", "contractor", "ndt", "owner", "admin", "fde")
DEFAULT_PATH_PREFIX = {
    "inspection": ("/workbench/inspection", "/ai-review-b"),
    "contractor": ("/workbench/contractor",),
    "ndt": ("/workbench/ndt",),
    "owner": ("/workbench/owner",),
    "admin": ("/admin",),
    "fde": ("/fde",),
}
# 监检的默认首页服务器仍回已下线的 /ai-review-b，前端 permission.ts 会原地改到 /workbench/inspection。


@api_case(
    "AUTH-01",
    "六个角色都能用账号口令登录",
    role="all",
    steps=["依次用监检、施工方、无损、建设方、管理员、FDE 账号 POST /api/auth/login"],
    expected="每个角色都拿到令牌；返回的用户角色与账号一致，默认首页指向本角色工作台",
    priority="P0",
)
def login_all_roles(ctx: Context) -> None:
    for role in ROLES:
        session = ctx.session(role)
        check(session.token, f"{ROLE_LABELS[role]}没拿到令牌")
        check(
            session.user.get("role") == role,
            f"{ROLE_LABELS[role]}登录后角色是 {session.user.get('role')}",
        )
        default_path = str(session.user.get("defaultPath") or "")
        check(
            default_path.startswith(DEFAULT_PATH_PREFIX[role]),
            f"{ROLE_LABELS[role]}默认首页应是 {DEFAULT_PATH_PREFIX[role][0]}…，实际 {default_path}",
        )
        check(
            "password" not in session.user and "passwordHash" not in session.user,
            "登录返回里不该带口令字段",
        )


@api_case(
    "AUTH-02",
    "口令错误不能登录",
    role="public",
    steps=["用监检账号和错误口令登录"],
    expected="登录失败（业务码 401 类），不发令牌；提示不泄露账号是否存在",
    priority="P0",
)
def wrong_password(ctx: Context) -> None:
    reply = ctx.login("inspection", password="wrong-password-for-check")
    data = reply.data if isinstance(reply.data, dict) else {}
    check(not data.get("token"), "错误口令不应拿到令牌")
    check(
        reply.code not in (0, None) or reply.http in (401, 403), f"应登录失败，实际 {reply.brief()}"
    )


@api_case(
    "AUTH-03",
    "不存在的账号不能登录",
    role="public",
    steps=["用一个不存在的用户名登录"],
    expected="登录失败，提示与口令错误相同（不暴露账号是否存在）",
    priority="P1",
)
def unknown_user(ctx: Context) -> None:
    unknown = ctx.send(
        "POST", "/api/auth/login", json={"username": "no-such-user-fullcheck", "password": "x" * 8}
    )
    wrong = ctx.login("contractor", password="wrong-password-for-check")
    check(not (unknown.data or {}).get("token"), "不存在的账号不应拿到令牌")
    check(unknown.code == wrong.code, f"两种失败的业务码应一致：{unknown.code} vs {wrong.code}")


@api_case(
    "AUTH-04",
    "未登录访问业务接口被拒",
    role="public",
    steps=["不带令牌 GET /api/workbench/projects", "不带令牌 GET /api/auth/me"],
    expected="都返回 401（请先登录）",
    priority="P0",
)
def anonymous_denied(ctx: Context) -> None:
    anonymous = ctx.session("public")
    anonymous.denied("GET", "/api/workbench/projects", params={"role": "inspection"})
    anonymous.denied("GET", "/api/auth/me")


@api_case(
    "AUTH-05",
    "伪造或篡改的令牌被拒",
    role="public",
    steps=["用乱写的 Bearer 令牌请求", "把真令牌最后几位改掉再请求"],
    expected="都返回 401",
    priority="P0",
)
def forged_token(ctx: Context) -> None:
    real = ctx.session("inspection").token
    for token in (
        "not-a-real-token",
        real[:-4] + ("AAAA" if not real.endswith("AAAA") else "BBBB"),
    ):
        reply = ctx.send(
            "GET",
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}", "X-Role": "inspection"},
        )
        check(reply.http == 401 or reply.code == 401, f"伪造令牌应被拒，实际 {reply.brief()}")


@api_case(
    "AUTH-06",
    "冒充角色无效：请求头写管理员也只按令牌身份办事",
    role="contractor",
    steps=["施工方登录", "带 X-Role: admin 请求 GET /api/admin/users"],
    expected="仍被拒绝（403）；身份以令牌为准",
    priority="P0",
)
def role_header_spoof(ctx: Context) -> None:
    contractor = ctx.session("contractor")
    contractor.denied(
        "GET", "/api/admin/users", headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"}
    )


@api_case(
    "AUTH-07",
    "查看当前账号信息",
    role="all",
    steps=["各角色 GET /api/auth/me"],
    expected="返回本人姓名、角色、所属单位和项目授权；非管理员只看到自己的项目授权",
    priority="P1",
)
def me(ctx: Context) -> None:
    for role in ROLES:
        session = ctx.session(role)
        data = session.ok_get("/api/auth/me")
        check(data.get("role") == role, f"{role} 的 /auth/me 角色不对：{data.get('role')}")
        check(data.get("displayName"), f"{role} 缺显示名")
        if role != "admin":
            others = [
                item
                for item in data.get("projectAuthorizations") or []
                if str(item.get("userId") or "") not in ("", session.user_id)
            ]
            check(not others, f"{role} 不该看到别人的项目授权（{len(others)} 条）")


@api_case(
    "AUTH-08",
    "退出登录后令牌立即失效",
    role="inspection",
    steps=["监检另开一次登录拿新令牌", "POST /api/auth/logout", "用这个令牌再 GET /api/auth/me"],
    expected="退出成功；再用旧令牌返回 401",
    priority="P0",
)
def logout(ctx: Context) -> None:
    reply = ctx.login("inspection")
    token = str((reply.data or {}).get("token") or "")
    if not token:
        skip(f"登录失败：{reply.brief()}")
    headers = {"Authorization": f"Bearer {token}", "X-Role": "inspection"}
    out = ctx.send("POST", "/api/auth/logout", headers={**headers, "Idempotency-Key": "ff-logout"})
    check(out.http == 200 and out.code == 0, f"退出应成功，实际 {out.brief()}")
    after = ctx.send("GET", "/api/auth/me", headers=headers)
    check(after.http == 401 or after.code == 401, f"退出后旧令牌应失效，实际 {after.brief()}")


@api_case(
    "AUTH-09",
    "各角色的菜单与可做动作",
    role="all",
    steps=["各角色 GET /api/auth/routes?role=<角色>", "GET /api/auth/actions?role=<角色>"],
    expected="都成功返回；管理员的动作集合覆盖其他角色",
    priority="P2",
)
def routes_and_actions(ctx: Context) -> None:
    for role in ROLES:
        session = ctx.session(role)
        session.ok_get("/api/auth/routes", role=role)
        session.ok_get("/api/auth/actions", role=role)


@api_case(
    "AUTH-10",
    "不允许的租户不能登录",
    role="public",
    steps=["登录请求里带一个未开通的 tenantId"],
    expected="被拒绝（403：单位未开通或当前部署不允许该租户），不发令牌",
    priority="P1",
)
def unknown_tenant(ctx: Context) -> None:
    reply = ctx.send(
        "POST",
        "/api/auth/login",
        json={
            "username": "inspection",
            "password": ctx.password,
            "tenantId": "tenant-fullcheck-unknown",
        },
    )
    check(not (reply.data or {}).get("token"), "未开通租户不应拿到令牌")
    check(reply.http == 403 or reply.code in (403, 40001), f"应被拒，实际 {reply.brief()}")


# ---------------- 权限与数据隔离 ----------------


@api_case(
    "PERM-01",
    "管理后台只给管理员",
    role="inspection,contractor,ndt,owner",
    steps=["监检、施工方、无损、建设方分别 GET /api/admin/users 和 /api/admin/org-units"],
    expected="全部被拒（403）",
    priority="P0",
)
def admin_only(ctx: Context) -> None:
    for role in ("inspection", "contractor", "ndt", "owner"):
        session = ctx.session(role)
        session.denied("GET", "/api/admin/users")
        session.denied("GET", "/api/admin/org-units")


@api_case(
    "PERM-02",
    "监检专用接口不给施工方、无损、建设方",
    role="outside",
    steps=["三个对外角色 GET /api/projects/{项目}/inspection/audit-overview"],
    expected="全部被拒",
    priority="P0",
)
def inspection_only(ctx: Context) -> None:
    project = ctx.need("project")
    for role in ("contractor", "ndt", "owner"):
        ctx.session(role).denied(
            "GET",
            f"/api/projects/{project}/inspection/audit-overview",
            codes={401, 403, 40301, 40404},
        )


@api_case(
    "PERM-03",
    "FDE 治理台不给业务角色",
    role="contractor,owner,inspection",
    steps=["施工方、建设方、监检 GET /api/fde/dashboard"],
    expected="全部被拒",
    priority="P1",
)
def fde_only(ctx: Context) -> None:
    for role in ("contractor", "owner", "inspection"):
        ctx.session(role).denied("GET", "/api/fde/dashboard")


@api_case(
    "PERM-04",
    "建设方不能上传资料",
    role="owner",
    steps=["建设方 POST /api/projects/{项目}/documents/upload-session"],
    expected="被拒绝",
    priority="P0",
)
def owner_cannot_upload(ctx: Context) -> None:
    project = ctx.need("project")
    ctx.session("owner").denied(
        "POST",
        f"/api/projects/{project}/documents/upload-session",
        json={"files": [{"fileName": "x.pdf", "fileSize": 10, "contentType": "application/pdf"}]},
        codes={401, 403, 40301, 40404},
    )


@api_case(
    "PERM-05",
    "施工方不能下审查结论、不能打回",
    role="contractor",
    steps=[
        "施工方 POST …/inspection/nodes/{节点}/review-opinions",
        "施工方 POST …/inspection/nodes/{节点}/actions/return-correction",
    ],
    expected="都被拒绝，节点状态不变",
    priority="P0",
)
def contractor_cannot_conclude(ctx: Context) -> None:
    project, node = ctx.need("project"), ctx.need("node")
    contractor = ctx.session("contractor")
    before = ctx.session("inspection").ok_get(f"/api/projects/{project}/tree")
    contractor.denied(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{node}/review-opinions",
        json={"result": "满足要求", "opinion": "越权测试"},
        codes={401, 403, 40301, 40404},
    )
    contractor.denied(
        "POST",
        f"/api/projects/{project}/inspection/nodes/{node}/actions/return-correction",
        json={"reason": "越权测试"},
        codes={401, 403, 40301, 40404},
    )
    after = ctx.session("inspection").ok_get(f"/api/projects/{project}/tree")
    check(before == after, "越权请求不该改动项目树")


@api_case(
    "PERM-06",
    "看不到未授权的项目",
    role="contractor",
    steps=[
        "施工方 GET /api/auth/me 看自己被授权的项目",
        "对一个未授权项目 GET /api/projects/{项目}/tree",
    ],
    expected="未授权项目返回 403/404，列表里也没有它",
    priority="P0",
)
def project_isolation(ctx: Context) -> None:
    contractor = ctx.session("contractor")
    me = contractor.ok_get("/api/auth/me")
    mine = {str(item.get("projectId")) for item in me.get("projectAuthorizations") or []}
    others = [pid for pid in ctx.need("projects") if pid not in mine]
    if not others:
        skip("施工方被授权了全部演示项目，没有可测的未授权项目")
    target = others[0]
    contractor.denied("GET", f"/api/projects/{target}/tree", codes={401, 403, 40301, 40404})
    listed = items_of(contractor.ok_get("/api/workbench/projects", role="contractor"))
    check(
        target not in {str(item.get("id")) for item in listed},
        f"施工方列表里出现了未授权项目 {target}",
    )
