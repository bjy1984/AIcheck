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


def test_reconciliation_is_unconditional_not_gated_on_row_count() -> None:
    """对账不能被「行数相等」的快速通道挡掉。

    第一版修复把补拉放在 `len(merged) != len(live_ids) or appended` 分支里，
    它假设「行数相同 = 内容相同」。可是「少了一行被水位线跳过的、同时多了一行
    已被别人删除的」行数恰好相等——既不删也不补，那条被跳过的行就和修复前一样
    永久隐身。行数是弱证据，id 集合才是。
    """
    assert "if len(merged) != len(live_ids) or appended:" not in MERGE, (
        "对账被行数快速通道挡住了：行数相等但内容不同时会漏检"
    )
    # present 的计算必须在无条件路径上
    before_missing = MERGE.split("missing_ids", 1)[0]
    assert "present.add(object_id)" in before_missing
    assert "for index, item in enumerate(merged):" in before_missing


def test_watermark_never_outruns_uncommitted_transactions() -> None:
    """水位线不能取 max(updated_at)——那会越过未提交事务写的行。

    updated_at 写的是 now()，而 PostgreSQL 的 now() 返回**事务开始时刻**，
    提交必然晚于它。取 max 会让水位线越过「已开始、尚未提交」的事务写的行：
    它们提交后 updated_at 已在水位线之下，增量永远拉不到——那才是
    2026-08-30 测试项目3 里 35 份文档永久隐身的源头。

    安全水位线取「最老活跃事务的开始时刻」：任何将来提交的事务，其行的
    updated_at >= 该事务的 xact_start >= 安全水位线，下次增量必定拉得到。
    """
    assert "_safe_incremental_watermark" in REPO_SRC, "必须有安全水位线的计算"
    impl = REPO_SRC.split("def _safe_incremental_watermark", 1)[1].split("\n    def ", 1)[0]
    assert "min(xact_start)" in impl, "安全水位线 = 最老活跃事务的开始时刻"
    assert "pg_stat_activity" in impl
    assert "state <> 'idle'" in impl, "空闲连接不算活跃事务，否则水位线永远不前进"

    # 合并时优先用安全水位线，拿不到才退回 max(updated_at)
    assert "if safe_watermark is not None:" in MERGE
    assert "elif highest is not None:" in MERGE, "探针失败要退回旧行为，不能让刷新停摆"


def test_watermark_advances_monotonically() -> None:
    """安全水位线只能前进不能后退，否则每次都重拉全部历史。"""
    assert "if previous is None or safe_watermark > previous:" in MERGE
