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


def api(path: str, username: str = "admin", payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {_token(username)}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
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


CHECKS = {
    "material-category": check_material_category,
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
