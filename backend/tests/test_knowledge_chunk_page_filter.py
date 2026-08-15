"""按原文页码取规范切片。

证据定位对话框的「标准条款定位」原来只给一张 PDF，翻到第 N 页，
条款正文一个字都不显示。补正文要按页取 OCR 切片——一份 TSG 上万条，
不能整份拉回前端再自己挑。

这个端点上有两个都叫 page 的东西：

    page    分页页号
    pageNo  原文页码

名字撞车，接串了不会报错，只会安静地返回错的一页——所以钉在这里。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

client = TestClient(app)


def _seed(file_id: str) -> None:
    repo.state.setdefault("knowledge_chunks", [])
    repo.state["knowledge_chunks"] = [
        item for item in repo.state["knowledge_chunks"] if item.get("fileId") != file_id
    ]
    repo.state["knowledge_chunks"].extend(
        [
            {"id": f"{file_id}-1", "fileId": file_id, "pageNo": 7, "chunkNo": 2, "text": "第七页第二块"},
            {"id": f"{file_id}-2", "fileId": file_id, "pageNo": 7, "chunkNo": 1, "text": "第七页第一块"},
            {"id": f"{file_id}-3", "fileId": file_id, "pageNo": 8, "chunkNo": 1, "text": "第八页"},
        ]
    )


def test_按原文页码筛出该页全部切片():
    file_id = "KF-PAGE-FILTER-TEST"
    _seed(file_id)
    body = client.get(f"/api/knowledge/files/{file_id}/chunks", params={"pageNo": 7}).json()
    texts = [item["text"] for item in body["data"]["items"]]
    assert texts == ["第七页第一块", "第七页第二块"], "同页要按 chunkNo 排好，正文顺序不能乱"


def test_不传页码时仍返回整份():
    file_id = "KF-PAGE-FILTER-TEST"
    _seed(file_id)
    body = client.get(f"/api/knowledge/files/{file_id}/chunks", params={"pageSize": 50}).json()
    assert len(body["data"]["items"]) == 3


def test_分页页号与原文页码互不干扰():
    """page=2 是要第二页**分页结果**，不是原文第 2 页。"""
    file_id = "KF-PAGE-FILTER-TEST"
    _seed(file_id)
    body = client.get(
        f"/api/knowledge/files/{file_id}/chunks", params={"pageNo": 7, "page": 2, "pageSize": 1}
    ).json()
    assert [item["text"] for item in body["data"]["items"]] == ["第七页第二块"]


def test_该页没有切片时返回空而不是整份():
    """空结果要如实为空——回落成整份会让人以为看的是那一页。"""
    file_id = "KF-PAGE-FILTER-TEST"
    _seed(file_id)
    body = client.get(f"/api/knowledge/files/{file_id}/chunks", params={"pageNo": 99}).json()
    assert body["data"]["items"] == []
