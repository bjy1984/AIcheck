"""OCR 卡在「排队中」必须有收敛器捡起来。

2026-08-30 测试项目3：批量传 41 份，35 份因为增量刷新漏行（worker 读不到刚建
的 ocr_job）永久卡在「排队中」。当时 reconcile_stuck_index_tasks 只管
切片/向量化，**OCR 这一段完全没人管**——只能靠人发现。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (BACKEND_ROOT / "scripts" / "reconcile_stuck_index_tasks.py").read_text(encoding="utf-8")
DISPATCH = (BACKEND_ROOT / "libs" / "integrations" / "task_dispatcher.py").read_text(encoding="utf-8")


def test_reconciler_covers_stuck_ocr() -> None:
    assert "def reconcile_stuck_ocr_jobs" in SRC
    body = SRC.split("def reconcile_stuck_ocr_jobs", 1)[1]
    assert '"排队中"' in body, "判据是文档停在「排队中」"
    assert '"queued"' in body, "且 ocr_job 仍是 queued"


def test_reconciler_is_invoked_from_main() -> None:
    """加了函数却没人调，等于没加。"""
    main_body = SRC.split("def main(", 1)[1].split("\ndef ", 1)[0]
    assert "reconcile_stuck_ocr_jobs(" in main_body


def test_ocr_redispatch_uses_fresh_task_id() -> None:
    """确定性 task_id 会让重派被 celery 当成重复投递静默丢弃。

    实测：手工重派 17 个卡住的 job，只有 6 个真的被接收，其余 11 个凭空消失——
    运维以为派出去了，实际什么也没发生。重派必须走 retry 路径。
    """
    body = SRC.split("def reconcile_stuck_ocr_jobs", 1)[1]
    assert "retry=True" in body, "重派必须用全新 task_id，否则被去重丢弃"


def test_dispatch_supports_retry_path() -> None:
    body = DISPATCH.split("def dispatch_mineru_ocr", 1)[1].split("\ndef ", 1)[0]
    assert "retry: bool = False" in body
    assert "if not retry:" in body, "只有非重派才用确定性 id"
    assert 'apply_kwargs["task_id"]' in body


def test_reconciler_skips_recently_active() -> None:
    """正在正常处理的不能碰——重复派发会让同一份资料被识别两遍。"""
    body = SRC.split("def reconcile_stuck_ocr_jobs", 1)[1]
    assert "threshold" in body and "continue" in body
