from __future__ import annotations

import inspect

from apps.worker import tasks as worker_tasks
from libs.official_ocr_control import official_ocr_control_status


def test_model_attempt_database_flush_is_outside_global_lock() -> None:
    source = inspect.getsource(worker_tasks._persist_official_ocr_attempt)
    lock_block, persist_block = source.split("    _persist_model_call_attempt(attempt)", maxsplit=1)

    assert "with _MODEL_CALL_LEDGER_LOCK:" in lock_block
    assert lock_block.rstrip().endswith('run.setdefault("modelCallAttemptIds", []).append(attempt["id"])')
    assert "return attempt[\"id\"]" in persist_block


def test_capacity_status_does_not_scan_redis_keyspace_with_keys() -> None:
    source = inspect.getsource(official_ocr_control_status)

    assert ".keys(" not in source
