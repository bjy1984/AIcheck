"""线上验证探针：在 API 容器内自签会话令牌，直接打本机接口。

## 为什么要有它

线上确认必须走**真实接口**，而不是查配置文件——查文件只能证明「部署上去了」，
证明不了「接口按这份配置回答」。本项目吃过这个亏不止一次。

但走接口需要登录态，而口令不该出现在命令行、shell 历史或对话里。
这里用应用自己的 `issue_token()` 在容器内签发令牌：不碰任何口令，
令牌也不出容器——脚本在容器里跑，只回传断言结果。

## 用法

    docker exec aicheck-api python3 /app/scripts/online_probe.py <检查项> [参数...]

每个检查项自己打印「判据 -> 实测值」，并以退出码表示成败。
**没有判据的检查项不要加进来**：打印一堆数据而不下结论，等于没验。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/app")

BASE = os.getenv("AICHECK_PROBE_BASE", "http://127.0.0.1:8000")


_state_loaded = False


def _token(username: str = "admin") -> str:
    """签发令牌前必须先把状态加载进来。

    不加载的话 `user_auth_version()` 读到 0，而 API 进程里的用户记录不是 0，
    接口会以「登录身份已变化，请重新登录」拒掉——**看起来像鉴权坏了，
    其实是探针自己少了一步**。第一次跑就踩到了这个。
    """
    global _state_loaded
    from libs.security.auth import issue_token, user_record_by_username

    if not _state_loaded:
        from libs.db.repository import load_state

        load_state()
        _state_loaded = True

    user = user_record_by_username(username)
    if not user:
        raise SystemExit(f"找不到用户 {username}，无法签发令牌")
    return issue_token(user)


def api(
    path: str, username: str = "admin", payload: dict | None = None, method: str | None = None
) -> dict:
    """method 不给就按有没有 body 猜 GET/POST。

    **PATCH/PUT 必须显式传**：第一版只会 GET/POST，去打一个 PATCH 端点
    结果拿到 405，被判成「端点未挂载」——判据自己错了，却报得像代码有问题。
    """
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {_token(username)}",
            "Content-Type": "application/json",
        },
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:  # 业务错误也要看内容，不能只看状态码
        return json.loads(error.read().decode())


# --------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------


def check_material_category() -> bool:
    """0817 第 1 条：元件制造许可证要归在材料类，不是资质证照。

    判据取自**接口**而不是配置文件：接口才是施工方和规则实际读到的东西。
    """
    # 资料审查点挂在后台配置总览的分片里，没有独立路由
    body = api("/api/admin/config-overview?sections=materialReviewPoints")
    if body.get("code") != 0:
        print(f"接口未成功：code={body.get('code')} msg={body.get('message') or body.get('detail')}")
        return False

    points: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "materialCategory" in node:
                points.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body.get("data"))
    licences = [p for p in points if p.get("materialTypeCode") == "manufacturing_license"]
    conflicts = [
        p.get("id")
        for p in points
        if p.get("businessModule") == "材料" and p.get("materialCategory") == "资质证照"
    ]

    ok = bool(licences)
    print(f"接口返回条目数：{len(points)}")
    for point in licences:
        category = point.get("materialCategory")
        hit = category == "材料验收与复验"
        ok = ok and hit
        print(f"  {point.get('id')} -> {category} {'✓' if hit else '✗ 应为 材料验收与复验'}")
    print(f"业务模块=材料 却归资质证照的残留：{conflicts or '无'}")
    return ok and not conflicts


def check_license_scope() -> bool:
    """0817 第 6 条：许可范围要从表格取，抽不到就说抽不到。

    **在 ocr-service 容器里跑**，验的是线上那份代码的行为，
    不是仓库里的代码——两者不一致过（镜像没重建那次）。
    """
    from apps.ocr_service.service import qualification_scope_candidate

    lines = [
        "中华人民共和国",
        "特种设备生产许可证",
        "编号；TS3810436-2025",
        "单位名称：贵州化工建设有限责任公司",
        "住所：贵州省贵阳市乌当区洛湾",
        "经审查，获准从事以下特种设备生产活动：",
        "许可项目",
        "许可子项目",
        "发证机关：国家市场监督管理总局",
        "有效期至：2025年04月27日",
    ]
    items = [(line, {"text": line}) for line in lines]
    table = {
        "rows": [
            ["许可项目", "许可子项目", "许可参数", "备注"],
            ["压力管道安装", "长输管道安装（GA2）", "", ""],
            ["", "公用管道安装（GB1、GB2）", "", ""],
            ["", "工业管道安装（GC1、GC2）", "", ""],
        ]
    }

    with_table = qualification_scope_candidate(items, {"tables": [table]})
    scope = str((with_table or {}).get("text") or "")
    from_table = all(
        term in scope for term in ("压力管道安装", "长输管道安装（GA2）", "工业管道安装（GC1、GC2）")
    )
    print(f"有表格时抽到：{scope or '（空）'}")
    print(f"  三项许可子项目齐全：{'✓' if from_table else '✗'}")

    without_table = qualification_scope_candidate(items, {"tables": []})
    refused = without_table is None
    print(f"没有表格时抽到：{without_table if without_table else '（空，正确）'}")
    print(f"  引导语没被当成许可范围：{'✓' if refused else '✗ 又把「以下特种设备生产活动」填进去了'}")
    return from_table and refused


def check_confidence_threshold() -> bool:
    """0817 第 7 条：置信度阈值调低，且只有一份口径。"""
    from libs.field_confidence import field_confirm_confidence, field_review_status

    threshold = field_confirm_confidence()
    print(f"线上生效的阈值：{threshold}")
    lowered = threshold <= 0.70
    print(f"  已调低（<=0.70）：{'✓' if lowered else '✗'}")

    # 0.75 这一档原先会被判「低置信度」，现在应当算已确认
    status = field_review_status(0.75, confidence_unavailable=False)
    print(f"  0.75 的字段判为：{status}")
    unknown = field_review_status(None, confidence_unavailable=True)
    print(f"  没有分数的字段判为：{unknown}")
    return lowered and status == "已确认" and unknown == "置信度未知"


def check_inspection_visibility() -> bool:
    """0817 第 8 条：监检能看到未提交的资料，且看得出没提交。"""
    from libs.db.repository import repo

    project_id = next(
        (
            str(p.get("id"))
            for p in repo.state.get("projects", [])
            if any(
                str(b.get("projectId")) == str(p.get("id"))
                and str(b.get("bindingStatus") or "") not in {"已提交", "需补正", "已通过"}
                for b in repo.state.get("bindings", [])
            )
        ),
        "",
    )
    if not project_id:
        print("线上没有「未提交挂载」的项目，这条无法用真实数据验证")
        return False
    node_id = next(
        str(b.get("nodeId"))
        for b in repo.state.get("bindings", [])
        if str(b.get("projectId")) == project_id
        and str(b.get("bindingStatus") or "") not in {"已提交", "需补正", "已通过"}
    )
    body = api(f"/api/projects/{project_id}/nodes/{node_id}/package", username="inspection")
    if body.get("code") != 0:
        print(f"接口未成功：code={body.get('code')} msg={body.get('message')}")
        return False
    data = body.get("data") or {}
    bindings = data.get("bindings") or []
    marked = [b for b in bindings if "submittedToInspection" in b]
    unsubmitted = [b for b in marked if b.get("submittedToInspection") is False]
    print(f"项目 {project_id} 节点 {node_id}：监检拿到 {len(bindings)} 条挂载")
    print(f"  带提交标记的：{len(marked)}")
    print(f"  其中未提交（原先监检根本看不到）：{len(unsubmitted)}")
    return bool(bindings) and len(marked) == len(bindings) and bool(unsubmitted)


def check_auto_classify() -> bool:
    """0817 第 2 条：上传后自动识别类别，认不出来就不猜。"""
    from libs.material_auto_classify import classify_material

    cases = [
        ("特种设备生产许可证-贵州化工.pdf", "manufacturing_license", "材料验收与复验"),
        ("特种设备设计资质.png", "design_license", "资质证照"),
        ("材料复验报告-20260817.pdf", "material_retest_report", "材料验收与复验"),
    ]
    ok_all = True
    for file_name, code, category in cases:
        got = classify_material(file_name=file_name) or {}
        hit = got.get("materialTypeCode") == code and got.get("materialCategory") == category
        ok_all = ok_all and hit
        print(f"  {file_name} -> {got.get('materialCategory') or '（认不出）'} {'✓' if hit else '✗'}")

    unknown = classify_material(file_name="扫描件001.pdf")
    print(f"  认不出的文件不硬塞类别：{'✓' if unknown is None else '✗ 猜成了 ' + str(unknown)}")
    return ok_all and unknown is None


def check_batch_review() -> bool:
    """0817 第 3 条：一键审查端点可用，且跳过的都带理由。"""
    body = api(
        "/api/projects/P-2026-HDCP-001/inspection/ai-recheck-batch",
        username="inspection",
        payload={"nodeIds": [9998, 9999]},
    )
    if body.get("code") != 0:
        print(f"接口未成功：code={body.get('code')} msg={body.get('message') or body.get('detail')}")
        return False
    data = body.get("data") or {}
    skipped = data.get("skipped") or []
    print(f"发起 {data.get('startedCount')} 个，跳过 {data.get('skippedCount')} 个")
    for item in skipped:
        print(f"  节点 {item.get('nodeId')}: {item.get('reason')} · {item.get('message')}")
    all_explained = bool(skipped) and all(i.get("reason") and i.get("message") for i in skipped)
    print(f"  跳过都带理由：{'✓' if all_explained else '✗'}")
    print(f"  上限回给了前端：{'✓' if data.get('batchLimit') else '✗'}")
    return all_explained and bool(data.get("batchLimit"))


def check_org_delegation() -> bool:
    """0817 第 4、5 条：邀请与权限下放的**护栏**在线上真的挡得住。

    只验反向：能做什么由单测覆盖，线上要确认的是「不能做的确实做不到」。
    """
    from apps.api import org_delegation_routes as delegation
    from libs.db.repository import repo

    ok_all = True

    protected = delegation.PROTECTED_ROLES >= {"admin", "fde"}
    print(f"  受保护角色名单含 admin/fde：{'✓' if protected else '✗'}")
    ok_all = ok_all and protected

    ttl = delegation.INVITE_TTL_HOURS
    bounded = 0 < ttl <= 168
    print(f"  邀请有效期 {ttl} 小时（有上限）：{'✓' if bounded else '✗ 没有过期时间等于长期后门'}")
    ok_all = ok_all and bounded

    # 跨组织：造两个不同组织的用户对象，直接问护栏函数
    lead_a = {"id": "X", "username": "x", "role": "contractor", "orgId": "ORG-A", "isOrgLeader": True}
    cross = delegation._is_org_leader(lead_a, "ORG-B")
    print(f"  A 组织负责人对 B 组织无权：{'✓' if not cross else '✗ 跨组织越权'}")
    ok_all = ok_all and not cross

    plain = delegation._is_org_leader({**lead_a, "isOrgLeader": False}, "ORG-A")
    print(f"  普通成员不是负责人：{'✓' if not plain else '✗'}")
    ok_all = ok_all and not plain

    # 端点确实挂上了（拆模块最容易漏 include_router）。
    #
    # 第一版判据是扫 app.routes 里的 path——**错的**：app.routes 只有 21 条
    # 顶层挂载，子路由在里面展开，于是永远扫不到，报成「未挂载」。
    # 正确做法是真的调一次：路由不存在会回 FastAPI 的 detail=Not Found，
    # 路由存在但邀请无效会回业务码——两者分得开。
    body = api("/api/invitations/probe-nonexistent-token")
    mounted = "detail" not in body and body.get("code") is not None
    print(f"  邀请端点已挂载：{'✓' if mounted else '✗ 路由 404 且不会报错'}")
    print(f"    无效令牌回应：code={body.get('code')} msg={body.get('message') or body.get('detail')}")
    return ok_all and mounted


def check_category_correction() -> bool:
    """0817 第 2 条配套：自动分类必须能人工改。

    只验**拒绝**：非法类别不能被写进去。允许任意字符串的话，
    规则按类别取证时永远取不到，而界面上看着「已经归好类了」。
    """
    from libs.material_auto_classify import known_categories

    cats = known_categories()
    print(f"配置里的合法类别数：{len(cats)}")

    body = api(
        "/api/projects/P-2026-HDCP-001/documents/DOC-NOT-EXIST/material-category",
        payload={"materialCategory": "我随便写的类别"},
        method="PATCH",
    )
    # 端点存在（不是 FastAPI 的 detail=Not Found），且拒绝了这次调用
    mounted = "detail" not in body and body.get("code") is not None
    rejected = body.get("code") != 0
    print(f"  端点已挂载：{'✓' if mounted else '✗'}")
    print(f"  非法类别被拒：{'✓' if rejected else '✗'}（code={body.get('code')}）")
    return bool(cats) and mounted and rejected


def check_auto_review_status() -> bool:
    """0817 第 3 条：节点带自动审核状态，且每个状态说得出理由。"""
    from libs.auto_review_status import auto_review_status
    from libs.db.repository import repo

    # 先看纯口径：每个状态都必须有 reason
    cases = [
        auto_review_status(None),
        auto_review_status({"status": "运行中"}),
        auto_review_status({"status": "失败"}),
        auto_review_status({"status": "已完成", "conclusion": "满足要求"}),
        auto_review_status(None, {"conclusion": "满足要求"}),
    ]
    all_explained = all(item.get("reason") for item in cases)
    print(f"  每个状态都有理由：{'✓' if all_explained else '✗ 说不出理由的标签等于没有'}")

    # 再看接口真的把它带出来了
    project_id = next(
        (str(b.get("projectId")) for b in repo.state.get("bindings", []) if b.get("projectId")), ""
    )
    node_id = next(
        (str(b.get("nodeId")) for b in repo.state.get("bindings", []) if str(b.get("projectId")) == project_id),
        "",
    )
    body = api(f"/api/projects/{project_id}/nodes/{node_id}/package", username="inspection")
    # 状态挂在节点包顶层，不是 summary 里——第一版写 summary，
    # 那个 key 根本不存在，于是报成「接口没带出来」。判据自己找错了地方。
    status = (body.get("data") or {}).get("autoReviewStatus") or {}
    exposed = bool(status.get("status")) and bool(status.get("reason"))
    print(f"  节点 {project_id}/{node_id} 的状态：{status.get('status') or '（没有）'}")
    print(f"    理由：{status.get('reason') or '（没有）'}")
    print(f"  接口已带出：{'✓' if exposed else '✗'}")
    return all_explained and exposed


def check_org_leader_flag() -> bool:
    """0817 第 5 条前提：isOrgLeader 不传时保持原值，不能被顺手撤掉。"""
    from apps.api.routes import admin_user_projection, build_admin_user_record

    existing = {"id": "U1", "username": "u1", "role": "contractor", "isOrgLeader": True}
    kept = build_admin_user_record({"mobile": "13800000000"}, existing=existing)["isOrgLeader"]
    print(f"  只改手机号后仍是负责人：{'✓' if kept else '✗ 顺手把负责人身份撤了'}")
    exposed = admin_user_projection(existing)["isOrgLeader"] is True
    print(f"  投影里带得出来：{'✓' if exposed else '✗ 后台没法勾选'}")
    return kept and exposed


def check_project_registration() -> bool:
    """项目注册链接 → 自选角色 → 审核。只验**护栏**。

    最要紧的一条：**待审期间不能存在可用账号**。
    先建用户再标 pending 的话，只要哪个查询忘了过滤，人就登进来了。
    """
    from apps.api import project_registration_routes as reg

    ok_all = True

    no_admin = "admin" not in reg.SELECTABLE_ROLES and "fde" not in reg.SELECTABLE_ROLES
    print(f"  可选角色里没有 admin/fde：{'✓' if no_admin else '✗ 自选就能当管理员'}")
    ok_all = ok_all and no_admin

    bounded = 0 < reg.INVITE_TTL_HOURS <= 720 and 0 < reg.MAX_USES <= 1000
    print(f"  链接有效期 {reg.INVITE_TTL_HOURS}h、次数上限 {reg.MAX_USES}：{'✓' if bounded else '✗'}")
    ok_all = ok_all and bounded

    # 端点已挂载：拿一个不存在的 token 去看，应回业务码而不是 FastAPI 的 detail
    body = api("/api/registration-links/probe-nonexistent")
    mounted = "detail" not in body and body.get("code") is not None
    print(f"  端点已挂载：{'✓' if mounted else '✗ 路由 404 且不会报错'}")
    print(f"    无效链接回应：code={body.get('code')} msg={body.get('message') or body.get('detail')}")

    # 提交路径存在且拒绝非法角色
    apply_body = api(
        "/api/registration-links/probe-nonexistent/apply",
        payload={"username": "probe", "role": "admin", "password": "Aa!234567890x"},
    )
    rejected = apply_body.get("code") not in (0, None)
    print(f"  非法链接/角色被拒：{'✓' if rejected else '✗'}")
    return ok_all and mounted and rejected


CHECKS = {
    "material-category": check_material_category,
    "project-registration": check_project_registration,
    "auto-review-status": check_auto_review_status,
    "org-leader-flag": check_org_leader_flag,
    "category-correction": check_category_correction,
    "org-delegation": check_org_delegation,
    "batch-review": check_batch_review,
    "auto-classify": check_auto_classify,
    "inspection-visibility": check_inspection_visibility,
    "license-scope": check_license_scope,
    "confidence-threshold": check_confidence_threshold,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in CHECKS:
        print("可用检查项：" + ", ".join(sorted(CHECKS)))
        return 2
    name = sys.argv[1]
    print(f"== {name} ==")
    passed = CHECKS[name]()
    print("结论：" + ("通过" if passed else "未通过"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
