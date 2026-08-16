"""后台总览按需下发重数据——但省略必须说出来。

## 线上实测（2026-08-16，admin 后台）

    /admin/config-overview  787 KB / 5.0~6.4 秒
        ruleVersions          375 KB
        materialReviewPoints  118 KB
        其余全部              ~14 KB

这两块只有业务规则那几页在用，而权限、Prompt、报告模板、联调每一页都要先等
它们传完。实测切页耗时：权限 7.98s、报告模板 6.74s、Prompt 5.98s、联调 5.99s
——PDF 里报的「切换加载时间长，在 8-9 秒」就是这件事。
（我此前认为这条已修，是错的：改过的是别的加载路径，这条一直没动。）

## 判据

- 不传 sections 仍下发全部：老调用方不能因为这次优化少拿数据
- 传了 sections 就只给要的那几节，**并在 omittedSections 里说明省了什么**
- 省略的节给空列表而不是删掉键：前端才分得清「没有数据」和「这次没要」

最后一条是这个改动的安全绳。为提速而悄悄少发，表现是表格默默变空——
用户看到的是「没有规则」，而不是「还没加载」，**比慢得多的加载更糟**。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def _overview(params: dict | None = None) -> dict:
    response = client.get("/api/admin/config-overview", params=params or {})
    assert response.status_code == 200
    return response.json().get("data") or {}


def test_不传参数仍下发全部():
    data = _overview()
    assert "ruleVersions" in data and "materialReviewPoints" in data
    assert "omittedSections" not in data, "没要求裁剪就不该出现省略声明"


def test_只要一节时另一节被省略且有声明():
    data = _overview({"sections": "ruleVersions"})
    assert data.get("materialReviewPoints") == [], "没要的节应给空列表而不是缺键"
    assert "materialReviewPoints" in (data.get("omittedSections") or [])
    assert "ruleVersions" not in (data.get("omittedSections") or [])


def test_两节都要就都不省():
    data = _overview({"sections": "ruleVersions,materialReviewPoints"})
    assert data.get("omittedSections") == []


def test_省略的节仍然保留键():
    """删掉键会让前端把「这次没要」误读成「后端没有这个字段」。"""
    data = _overview({"sections": "users"})
    assert "ruleVersions" in data and data["ruleVersions"] == []
    assert "materialReviewPoints" in data and data["materialReviewPoints"] == []
    assert set(data.get("omittedSections") or []) == {"ruleVersions", "materialReviewPoints"}


def test_轻量字段一直都在():
    """裁的是重数据，权限矩阵、用户、机构这些每页都要用，不能一起裁掉。"""
    data = _overview({"sections": "users"})
    for key in ("users", "orgUnits", "businessPacks", "permissionMatrix"):
        assert key in data, key
