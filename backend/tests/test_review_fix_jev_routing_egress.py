"""文件归属路由只把 OCR 正文送给 Jev：工程号、节点、文件名、内部版本号留在本地。"""
from __future__ import annotations

from copy import deepcopy

import pytest

from libs import jev_document_routing as routing


class FakeRepo:
    def __init__(self, state):
        self.state = state

    def require_project(self, project_id):
        return next((item for item in self.state["projects"] if item["id"] == project_id), None)

    def find_one(self, collection, item_id):
        return next((item for item in self.state[collection] if item["id"] == item_id), None)

    def clone(self, value):
        return deepcopy(value)


@pytest.fixture
def repo(monkeypatch):
    monkeypatch.setenv("AICHECK_JEV_DOCUMENT_ROUTING_ALLOWED_PROJECTS", "PROJ-SECRET-9")
    monkeypatch.setattr(routing, "jev_stage_enabled", lambda _: True)
    return FakeRepo({
        "projects": [{"id": "PROJ-SECRET-9", "businessPackId": "engineering_inspection_v1"}],
        "documents": [{"id": "DOC-7", "projectId": "PROJ-SECRET-9", "fileName": "焊接工艺卡_内部编号.pdf",
                       "currentVersionId": "VER-INTERNAL-42"}],
        "versions": [{"id": "VER-INTERNAL-42", "documentId": "DOC-7"}],
        "ocr_parse_results": [{"documentVersionId": "VER-INTERNAL-42", "fragments": [
            {"pageNo": 1, "text": "焊接工艺卡 WPS-01 电流 90A"},
        ]}],
        "node_evidence_links": [],
        "admin_config": {"materialReviewPoints": [
            {"id": "P25", "nodeId": 25, "nodeName": "焊接工艺", "reviewContent": "核对 WPS",
             "materialTypeName": "焊接工艺卡", "businessPackId": "engineering_inspection_v1"},
        ]},
    })


def test_routing_sends_ocr_text_only(monkeypatch, repo):
    sent = []

    def fake_ask(state, questions):
        sent.append(state)
        return {key: {"type": "choice", "choice": "yes", "confidence": 0.95} for key in questions}

    monkeypatch.setattr(routing, "ask_jev", fake_ask)
    result = routing.classify_document_node_routing(repo, "PROJ-SECRET-9", "DOC-7", "VER-INTERNAL-42")

    assert result["status"] == "completed" and result["suggestedNodeIds"] == [25]
    assert sent == ["[第 1 页] 焊接工艺卡 WPS-01 电流 90A"]
    for local_only in ("PROJ-SECRET-9", "VER-INTERNAL-42", "DOC-7", "焊接工艺卡_内部编号", "待归属",
                       "工程：", "文件：", "规则检查"):
        assert local_only not in sent[0]


def test_ambiguous_latest_ocr_attempt_is_not_sent(monkeypatch, repo):
    repo.state["ocr_parse_results"] = [
        {"documentVersionId": "VER-INTERNAL-42", "createdAt": "2026-09-01", "fragments": [{"pageNo": 1, "text": "A"}]},
        {"documentVersionId": "VER-INTERNAL-42", "createdAt": "2026-09-01", "fragments": [{"pageNo": 1, "text": "B"}]},
    ]
    monkeypatch.setattr(routing, "ask_jev", lambda *_: 1 / 0)
    result = routing.classify_document_node_routing(repo, "PROJ-SECRET-9", "DOC-7", "VER-INTERNAL-42")
    assert result["status"] == "no_ocr_text"
