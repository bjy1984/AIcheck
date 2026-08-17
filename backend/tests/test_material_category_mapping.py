"""资料类别归属：元件制造许可证属于材料，不属于参与单位资质。

## 用户报的问题（0817）

    「元件制造许可证及相关证明的资料应该属于材料证明与复验的类别里」

配置里本来就自相矛盾：那两条 manufacturing_license 的 businessModule 写的是
**材料**，materialCategory 却落在**资质证照**。同一条记录，两个字段说了两件事。

## 为什么这不只是标签问题

materialCategory 同时决定「施工方按哪一类上传」和「规则按哪一类取证」。
分错的表现是：**许可证明明传了，却被判成缺项**——而界面上「传了」和
「传对了」长得完全一样，没有人会怀疑到分类头上。

## 前端也有一份

frontend/src/views/AICheck/contractorMaterialCategories.ts。
两边都改了才算改完；只改一边，施工方按一套分类传、规则按另一套取证。
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "material_review_points.json"

# 参与单位**自身**的资质：谁有资格干这个活。
QUALIFICATION_TYPES = {"design_license", "construction_license", "ndt_org_certificate"}
# 材料一侧：这批元件/材料本身的证明，包含它的制造方有没有制造许可。
MATERIAL_CATEGORY = "材料验收与复验"
QUALIFICATION_CATEGORY = "资质证照"


def _points() -> list[dict]:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    found: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "materialCategory" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def test_制造许可证归在材料类():
    points = [p for p in _points() if p.get("materialTypeCode") == "manufacturing_license"]
    assert points, "配置里找不到 manufacturing_license，用例本身失效了"
    for point in points:
        assert point["materialCategory"] == MATERIAL_CATEGORY, (
            f"{point.get('id')} 的资料类别是 {point['materialCategory']}；"
            "元件制造许可证属于材料证明，放在资质证照里会让规则取不到它"
        )


def test_参与单位资质仍留在资质证照():
    """别把整类都推到材料侧去——施工/设计/无损检测机构的资质本来就是资质。"""
    for point in _points():
        if point.get("materialTypeCode") in QUALIFICATION_TYPES:
            assert point["materialCategory"] == QUALIFICATION_CATEGORY, (
                f"{point.get('id')} 是参与单位资质，不该挪出资质证照"
            )


def test_业务模块与资料类别不再互相矛盾():
    """businessModule=材料 的条目，资料类别不该是资质证照。

    这正是这次的错法：同一条记录里两个字段各说各的。
    只要还有一条这样的记录，同样的分歧就会再次以「资料传了却判缺项」的形式出现。
    """
    conflicts = [
        point.get("id")
        for point in _points()
        if point.get("businessModule") == "材料"
        and point.get("materialCategory") == QUALIFICATION_CATEGORY
    ]
    assert not conflicts, f"这些条目的业务模块是材料、资料类别却是资质证照：{conflicts}"


def test_类别名取自固定集合():
    """类别名是拿来做匹配的，写错一个字就永远匹配不上，而且不会报错。"""
    categories = {point["materialCategory"] for point in _points()}
    assert MATERIAL_CATEGORY in categories
    assert QUALIFICATION_CATEGORY in categories
    for name in categories:
        assert name == name.strip(), f"类别名带首尾空白：{name!r}"
        assert name, "存在空的类别名"
