"""规则升级与审查口径：旧项目升级到最新业务包、院级口径开关、平台默认口径。"""

from __future__ import annotations

from scripts.full_function_check.base import Context, api_case, check, items_of, skip

POLICY_KEY = "certificate_expired_without_construction_period"


@api_case(
    "RULE-01",
    "规则升级：列出与最新业务包有差异的项目",
    role="admin",
    steps=["管理员 GET /api/admin/business-pack/updates"],
    expected="列出每个项目当前用的业务包版本、与最新版的差异条数",
    priority="P1",
)
def list_updates(ctx: Context) -> None:
    data = ctx.session("admin").ok_get("/api/admin/business-pack/updates")
    ctx.store["pack_updates"] = data
    check(isinstance(data, dict | list), "规则升级接口格式不对")


@api_case(
    "RULE-02",
    "规则升级：选中项目升级后与最新版一致",
    role="admin",
    steps=[
        "POST /api/admin/business-pack/updates/apply（projectIds=[第二个演示项目]）",
        "再 GET …/updates",
    ],
    expected="升级成功；该项目不再出现在待升级列表里（或差异为 0）",
    priority="P1",
    writes=True,
)
def apply_update(ctx: Context) -> None:
    projects = [pid for pid in ctx.need("projects") if pid != ctx.need("project")]
    if not projects:
        skip("只有一个演示项目")
    target = "P-2026-GDLNG-002" if "P-2026-GDLNG-002" in projects else projects[0]
    admin = ctx.session("admin")
    admin.ok("POST", "/api/admin/business-pack/updates/apply", json={"projectIds": [target]})
    after = admin.ok_get("/api/admin/business-pack/updates")
    pending = [
        item
        for item in items_of(after if isinstance(after, list) else after.get("projects") or after)
        if str(item.get("projectId") or item.get("id")) == target
    ]
    for item in pending:
        changes = item.get("changeCount") or item.get("diffCount") or len(item.get("changes") or [])
        check(not changes or item.get("upToDate"), f"升级后 {target} 仍有差异：{item}")


@api_case(
    "RULE-03",
    "院级审查口径：查看、修改、恢复默认",
    role="admin",
    steps=[
        "GET /api/admin/review-policies",
        f"PUT /api/admin/review-policies/{POLICY_KEY}（value=human_review_required）",
        "用不允许的值再改一次",
        "PUT value=null 恢复默认",
    ],
    expected="列表含该口径和可选值；合法值保存成功并生效；非法值被拒；置空后回到平台默认",
    priority="P1",
    writes=True,
)
def institute_policy(ctx: Context) -> None:
    admin = ctx.session("admin")
    listed = admin.ok_get("/api/admin/review-policies")
    check(POLICY_KEY in str(listed), f"口径列表里没有 {POLICY_KEY}")
    path = f"/api/admin/review-policies/{POLICY_KEY}"
    admin.ok("PUT", path, json={"value": "human_review_required"})
    check(
        "human_review_required" in str(admin.ok_get("/api/admin/review-policies")),
        "改后读回不是新值",
    )
    bad = admin.call("PUT", path, json={"value": "not-a-valid-choice"})
    check(bad.code == 40001, f"非法值应被拒，实际 {bad.brief()}")
    admin.ok("PUT", path, json={"value": None})


@api_case(
    "RULE-04",
    "平台默认口径",
    role="admin",
    steps=[
        f"平台管理员 PUT /api/platform/review-policy-defaults/{POLICY_KEY}（value=evidence_insufficient）",
        "再改回 null",
    ],
    expected="保存成功；各院没单独设置时按平台默认",
    priority="P2",
    writes=True,
)
def platform_default(ctx: Context) -> None:
    admin = ctx.session("admin")
    path = f"/api/platform/review-policy-defaults/{POLICY_KEY}"
    admin.ok("PUT", path, json={"value": "evidence_insufficient"})
    admin.ok("PUT", path, json={"value": None})


@api_case(
    "RULE-05",
    "监检不能改审查口径",
    role="inspection",
    steps=[f"监检 PUT /api/admin/review-policies/{POLICY_KEY}"],
    expected="被拒（403）",
    priority="P1",
)
def inspection_cannot_change(ctx: Context) -> None:
    ctx.session("inspection").denied(
        "PUT", f"/api/admin/review-policies/{POLICY_KEY}", json={"value": "failed"}
    )
