"""周期任务锁的僵尸连接防御。

session 级 advisory lock 只在连接断开时释放。持锁的 worker 进程被强杀
（频繁部署重建时发生），连接留在 PG 侧成孤儿、锁永不释放——后续周期任务
全部 duplicate_inflight，自动派发永久卡死且无自愈
（2026-08-29 生产实测：僵尸锁卡死自动审查派发，候选一直 pending）。

修复：给锁连接设服务端 idle_session_timeout，孤儿连接被 PG 自动清理。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_lock_connection_sets_idle_session_timeout() -> None:
    source = (BACKEND_ROOT / "libs" / "pipeline_lock.py").read_text(encoding="utf-8")
    assert "idle_session_timeout" in source, "锁连接必须设服务端空闲超时，否则孤儿连接锁死周期任务"
    # 必须容错老版本 PG（<14 不支持该参数），不能因此阻断获锁
    block = source.split("pg_try_advisory_lock", 1)[0]
    assert "idle_session_timeout" in block, "超时必须在获锁之前设置"
    assert "except Exception:" in block or "try:" in block, "设置超时必须容错，老版 PG 不支持时不阻断"


def test_lock_still_releases_in_finally() -> None:
    """防御不能破坏正常释放路径。"""
    source = (BACKEND_ROOT / "libs" / "pipeline_lock.py").read_text(encoding="utf-8")
    assert "pg_advisory_unlock" in source
    assert "connection.close()" in source
