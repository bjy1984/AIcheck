"""增量刷新必须能补回被水位线跳过的行。

按 `updated_at > 水位线` 拉行有个致命前提：行的时间戳顺序等于它变得可见的
顺序。批量写入时不成立——updated_at 是写入时刻，可见却要等事务提交，
一行完全可能「时间戳早于水位线、可见却晚于上次刷新」。

那种行会被永久跳过：合并逻辑原本只删不补，水位线又单调前进，
于是它再也进不了内存。

线上实测（2026-08-30 测试项目3）：批量传 41 份，35 份的 ocr_job 对 worker
永久隐身，任务一律 MINERU_JOB_NOT_FOUND 立即失败、文档永远「排队中」，
重新派发也没用——水位线早已越过它们。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_SRC = (BACKEND_ROOT / "libs" / "db" / "repository.py").read_text(encoding="utf-8")
MERGE = REPO_SRC.split("def _merge_incremental_collection", 1)[1].split("\n    def ", 1)[0]


def test_merge_recovers_rows_present_in_db_but_missing_in_memory() -> None:
    assert "missing_ids" in MERGE, "内存缺行必须补回，否则被跳过的行永远进不来"
    assert "live_ids - present" in MERGE, "缺失集合 = 库里存在 - 内存已有"
    assert "object_id = ANY(" in MERGE, "补拉要按 id 精确查，不能再依赖水位线"


def test_recovered_rows_register_persistence_baseline() -> None:
    """补回来的行必须登记落库基线，否则下次写它就撞 ConcurrentPersistenceError。"""
    recovery = MERGE.split("missing_ids", 1)[1]
    assert "_persistence_baseline[(collection_name, key)]" in recovery


def test_recovery_advances_watermark() -> None:
    """补回的行也要参与水位线推进，否则每次刷新都重复补同一批。"""
    recovery = MERGE.split("missing_ids", 1)[1]
    assert "highest = updated_at" in recovery


def test_recovery_respects_pinned_objects() -> None:
    """钉住的对象（本进程未落库的在途写入）不能被库里的旧值覆盖。"""
    recovery = MERGE.split("missing_ids", 1)[1]
    assert "object_is_pinned" in recovery
