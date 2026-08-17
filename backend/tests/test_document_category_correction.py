"""自动分类必须能人工改（0817 第 2 条的配套）。

**自动分类一定会错**——第 1 条本身就是分类错的例子。
没有纠正出口的自动化，用户错一次就没有办法了：他看得见分错了，
却只能重新传一遍，或者眼睁睁看着规则去错的地方取证、把资料判成缺项。

## 两条判据

1. 只接受配置里存在的类别。允许任意字符串的话，规则按类别取证时永远取不到，
   而界面上看着「已经归好类了」——又一个静默失败。
2. 改完标 `materialCategorySource=manual`。「系统猜的」和「人改的」分不开的话，
   下次想批量重跑自动分类，没办法把人工改过的排除掉，会被一把冲掉。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.material_auto_classify import known_categories

client = TestClient(app)
HEADERS = {"X-Role": "contractor", "X-User-Id": "USER-CONTRACTOR-001"}
PROJECT_ID = "P-2026-HDCP-001"
DOC_ID = "DOC-CATEGORY-FIX-TEST"


@pytest.fixture(autouse=True)
def _document():
    doc = {
        "id": DOC_ID,
        "projectId": PROJECT_ID,
        "fileName": "扫描件001.pdf",
        "materialCategory": "资质证照",
        "autoClassification": {"matchedBy": "fileName"},
    }
    repo.state.setdefault("documents", []).insert(0, doc)
    yield doc
    repo.state["documents"] = [d for d in repo.state["documents"] if d.get("id") != DOC_ID]


def _patch(category: str):
    return client.patch(
        f"/api/projects/{PROJECT_ID}/documents/{DOC_ID}/material-category",
        json={"materialCategory": category},
        headers=HEADERS,
    ).json()


def test_可以把分错的类别改回来(_document):
    target = "材料验收与复验"
    assert target in known_categories(), "用例用的类别在配置里不存在"
    body = _patch(target)
    assert body["code"] == 0, body
    assert _document["materialCategory"] == target
    assert body["data"]["previousCategory"] == "资质证照", "没回报改之前是什么，无法核对"


def test_改完标成人工(_document):
    """分不开的话，下次批量重跑自动分类会把人工改过的一把冲掉。"""
    _patch("材料验收与复验")
    assert _document["materialCategorySource"] == "manual"


def test_不接受配置里没有的类别(_document):
    body = _patch("我随便写的类别")
    assert body["code"] != 0
    assert _document["materialCategory"] == "资质证照", "非法类别被写进去了"
    assert body["data"]["allowed"], "拒绝时没告诉调用方合法值是什么"


def test_空类别被拒(_document):
    assert _patch("")["code"] != 0


def test_不存在的资料返回未找到():
    body = client.patch(
        f"/api/projects/{PROJECT_ID}/documents/DOC-NOPE/material-category",
        json={"materialCategory": "材料验收与复验"},
        headers=HEADERS,
    ).json()
    assert body["code"] != 0


def test_不能跨项目改(_document):
    """项目 ID 对不上就当不存在——否则这是一条跨项目改数据的路。"""
    body = client.patch(
        f"/api/projects/P-OTHER/documents/{DOC_ID}/material-category",
        json={"materialCategory": "材料验收与复验"},
        headers=HEADERS,
    ).json()
    assert body["code"] != 0
    assert _document["materialCategory"] == "资质证照"
