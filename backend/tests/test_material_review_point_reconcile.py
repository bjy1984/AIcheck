"""配置文件改了，线上必须跟着变。

## 线上实测（2026-08-17）

把两条 manufacturing_license 的资料类别从「资质证照」改成「材料验收与复验」，
部署完成，**容器内的配置文件确认已更新**，接口却一直返回「资质证照」。

原因：`materialReviewPoints` 只在「库里为空」时从配置文件播种一次。
播过种之后，改配置文件永远不生效——而且不报错。

    文件是新的 → 容器是新的 → 接口是旧的 → 没有任何提示

**配置文件看起来是真相，实际只是初始值。** 这个误解很贵，因为它让
「我改了」和「线上变了」之间断开，中间没有任何东西会提醒你。

## 判据

- 库里已有条目的派生字段要被对齐到配置
- 只对齐**生成字段**：备注、启用状态之类的人工内容不许被覆盖
- 库里多出来的条目原样保留——对齐不该变成清空
"""

from __future__ import annotations

from libs.db.repository import InMemoryRepository


def _repo() -> InMemoryRepository:
    return InMemoryRepository.__new__(InMemoryRepository)


def test_派生字段被对齐到配置():
    repo = _repo()
    loaded = {
        "admin_config": {
            "materialReviewPoints": [
                {
                    "id": "MRP-12-manufacturing_license-6948A2",
                    "materialCategory": "资质证照",  # 库里的旧值
                    "businessModule": "材料",
                }
            ]
        }
    }
    seeded = {
        "admin_config": {
            "materialReviewPoints": [
                {
                    "id": "MRP-12-manufacturing_license-6948A2",
                    "materialCategory": "材料验收与复验",  # 配置里的新值
                    "businessModule": "材料",
                }
            ]
        }
    }
    assert repo.reconcile_material_review_points(loaded, seeded) is True
    assert (
        loaded["admin_config"]["materialReviewPoints"][0]["materialCategory"]
        == "材料验收与复验"
    ), "改了配置文件却没生效——这正是线上踩到的那个坑"


def test_一致时不写任何东西():
    """没有漂移就不该报告有改动，否则每次启动都白写一遍库。"""
    repo = _repo()
    point = {"id": "MRP-1", "materialCategory": "材料验收与复验"}
    loaded = {"admin_config": {"materialReviewPoints": [dict(point)]}}
    seeded = {"admin_config": {"materialReviewPoints": [dict(point)]}}
    assert repo.reconcile_material_review_points(loaded, seeded) is False


def test_非派生字段不许被覆盖():
    """人工填的东西不能被配置文件冲掉。

    对齐的正当性来自「这些字段是生成的」；一旦越界去改人工内容，
    这一步就从修 bug 变成了丢数据。
    """
    repo = _repo()
    loaded = {
        "admin_config": {
            "materialReviewPoints": [
                {
                    "id": "MRP-1",
                    "materialCategory": "资质证照",
                    "remark": "现场约定：这一项由甲方代传",
                    "enabled": False,
                }
            ]
        }
    }
    seeded = {
        "admin_config": {
            "materialReviewPoints": [
                {
                    "id": "MRP-1",
                    "materialCategory": "材料验收与复验",
                    "remark": "",
                    "enabled": True,
                }
            ]
        }
    }
    repo.reconcile_material_review_points(loaded, seeded)
    item = loaded["admin_config"]["materialReviewPoints"][0]
    assert item["materialCategory"] == "材料验收与复验"
    assert item["remark"] == "现场约定：这一项由甲方代传", "人工备注被配置文件冲掉了"
    assert item["enabled"] is False, "人工的启用状态被配置文件冲掉了"


def test_库里多出来的条目原样保留():
    """可能是配置包导入的。对齐不该变成清空。"""
    repo = _repo()
    loaded = {
        "admin_config": {
            "materialReviewPoints": [
                {"id": "MRP-1", "materialCategory": "资质证照"},
                {"id": "MRP-CUSTOM", "materialCategory": "自定义类别"},
            ]
        }
    }
    seeded = {
        "admin_config": {
            "materialReviewPoints": [{"id": "MRP-1", "materialCategory": "材料验收与复验"}]
        }
    }
    repo.reconcile_material_review_points(loaded, seeded)
    ids = [item["id"] for item in loaded["admin_config"]["materialReviewPoints"]]
    assert ids == ["MRP-1", "MRP-CUSTOM"]
    assert loaded["admin_config"]["materialReviewPoints"][1]["materialCategory"] == "自定义类别"


def test_配置为空时不动库():
    """配置读不出来时保持原样——宁可不改，也不要把线上清成空的。"""
    repo = _repo()
    loaded = {"admin_config": {"materialReviewPoints": [{"id": "MRP-1", "materialCategory": "甲"}]}}
    assert repo.reconcile_material_review_points(loaded, {"admin_config": {}}) is False
    assert loaded["admin_config"]["materialReviewPoints"][0]["materialCategory"] == "甲"
