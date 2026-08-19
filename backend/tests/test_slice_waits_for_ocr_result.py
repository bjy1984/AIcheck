"""切片必须等到派发方写下的那条 OCR 解析结果**可见**才开工。

## 一次毫秒级竞态，被固化成永久故障

切片是在 OCR 任务内部派发的。线上实测：OCR 03:33:07 完成并派发，
切片同一秒开工，读库时那次提交还没可见。于是切片读到 0 片段、
按「没有文字」处理，写出一个 0 分块的**成功**结果：
chunkCount=0 → 向量化失败 → 报审永久卡住，任务日志里却写着 succeeded。

## 为什么不能靠状态推断

第一版判据写的是「文档状态是已识别却读不到解析结果 → 重试」，**没用**：
文档状态和解析结果是同一次提交写的，一个看不见另一个也看不见。
用一个同样看不见的东西去判断另一个看不见的东西，判不出来。

所以改成派发方直接传具体的 parseResultId，切片比对这条 id 是否可见。
"""

from __future__ import annotations

from apps.worker import tasks
from libs.db.repository import InMemoryRepository


def _repo(parse_results: list[dict]) -> InMemoryRepository:
    repository = InMemoryRepository()
    repository.state["knowledge_files"] = [
        {"id": "KF-1", "documentId": "DOC-1", "documentVersionId": "DV-1", "fileName": "x.pdf"}
    ]
    repository.state["ocr_parse_results"] = parse_results
    return repository


def test_那条解析结果还看不见时判为不可见(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "repo", _repo([]))
    assert tasks.parse_result_visible("KF-1", "PARSE-NEW") is False


def test_解析结果到位后判为可见(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "repo",
        _repo([{"parseResultId": "PARSE-NEW", "documentVersionId": "DV-1", "status": "success"}]),
    )
    assert tasks.parse_result_visible("KF-1", "PARSE-NEW") is True


def test_别的版本的同名结果不算数(monkeypatch) -> None:
    """只比对 id 不比对版本的话，另一份文档的结果会被误当成「已可见」。"""
    monkeypatch.setattr(
        tasks,
        "repo",
        _repo([{"parseResultId": "PARSE-NEW", "documentVersionId": "DV-OTHER", "status": "success"}]),
    )
    assert tasks.parse_result_visible("KF-1", "PARSE-NEW") is False


def test_派发时带上解析结果id() -> None:
    """派发方不传 id 的话，切片无从判断可见性——这条链就退回竞态状态。"""
    import inspect

    from libs.integrations import task_dispatcher

    assert "expect_parse_result_id" in inspect.signature(task_dispatcher.dispatch_slice).parameters
    source = inspect.getsource(tasks._execute_mineru_ocr_extract)
    assert "expect_parse_result_id" in source, "MinerU 派发切片时没有带上 parseResultId"
