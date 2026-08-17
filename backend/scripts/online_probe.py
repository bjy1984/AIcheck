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


CHECKS = {"material-category": check_material_category}


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
