"""OCR 说识别成功却读不到解析结果时，切片要**重试**，不能当成「没有文字」。

## 一次 3 毫秒的竞态，固化成永久故障

切片是在 OCR 任务内部派发的。0819 线上实测：切片任务 03:13:30.306 开始，
OCR 任务 03:13:30.309 才结束——相差 3 毫秒，切片读库时那条解析结果还没落定。

原先的处理是默默往下走，最后按 0 分块「成功」收场。于是：
chunkCount=0 → 向量化失败 → **报审永久卡住**，而且全程没有任何报错，
任务日志里写的是 succeeded。

六角色写操作审计连续两轮都卡在这一步，才把它揪出来。

## 判据

不是「重试了几次」，而是**不许把读不到当成没有**：
文档标着「已识别」却取不到解析结果时，必须抛出重试，
而不是走到 apply_slice_result 去写一个 0 分块的成功结果。
"""

from __future__ import annotations

from apps.worker import tasks
from libs.db.repository import InMemoryRepository


def _repo_with_recognized_document() -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.state["documents"] = [{"id": "DOC-1", "currentOcrStatus": "已识别"}]
    repository.state["versions"] = [{"id": "DV-1", "documentId": "DOC-1"}]
    repository.state["knowledge_files"] = [
        {"id": "KF-1", "documentId": "DOC-1", "documentVersionId": "DV-1", "fileName": "x.pdf"}
    ]
    repository.state["ocr_parse_results"] = []  # 还没落定
    return repository


def test_识别成功但取不到解析结果时判定为时序问题(monkeypatch) -> None:
    repository = _repo_with_recognized_document()
    monkeypatch.setattr(tasks, "repo", repository)
    file = repository.state["knowledge_files"][0]
    assert tasks.ocr_says_recognized_but_result_missing(file) is True


def test_解析结果到位后不再判为时序问题(monkeypatch) -> None:
    repository = _repo_with_recognized_document()
    repository.state["ocr_parse_results"] = [
        {"documentVersionId": "DV-1", "status": "success", "fragments": [{"text": "有内容"}]}
    ]
    monkeypatch.setattr(tasks, "repo", repository)
    file = repository.state["knowledge_files"][0]
    assert tasks.ocr_says_recognized_but_result_missing(file) is False


def test_OCR真的失败时不重试(monkeypatch) -> None:
    """OCR 状态不是「已识别」，那就是真的没有内容——重试多少次都一样，
    此时应该走原来的兜底路径，而不是无谓地重试三轮。"""
    repository = _repo_with_recognized_document()
    repository.state["documents"][0]["currentOcrStatus"] = "识别失败"
    monkeypatch.setattr(tasks, "repo", repository)
    file = repository.state["knowledge_files"][0]
    assert tasks.ocr_says_recognized_but_result_missing(file) is False
