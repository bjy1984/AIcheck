"""worker 刷新状态时，调用方点名的集合必须确定地被刷新。

原实现在集合「已加载」时一律走 refresh_stale_state_from_postgres——
它靠两级探针自己猜哪些集合变了，**点名的范围被丢弃**。探针有秒级时间窗，
派发方刚 flush 的行可能落在窗外：ocr-remote worker 因此读不到 business worker
刚建的 ocr_job，直接报 MINERU_JOB_NOT_FOUND，而记录在库里好好地躺着
（2026-08-29 实测 2 份资料如此）。
"""

from __future__ import annotations

import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_named_scope_is_refreshed_deterministically() -> None:
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def refresh_worker_state", 1)[1].split("\ndef ", 1)[0]
    assert "refresh_collections_incrementally" in body, "点名的集合要确定刷新，不能交给探针猜"
    # 必须是「有点名范围就直接返回」，不落到探针回退
    # （锚在实际调用上，不是注释——注释里也会提到探针函数名）
    assert "repo.refresh_collections_incrementally(set(selected_state_keys))" in body
    scoped_call = body.index("repo.refresh_collections_incrementally(")
    probe_call = body.index("repo.refresh_stale_state_from_postgres(force=True)")
    assert scoped_call < probe_call, "点名范围的刷新要先于探针回退"
    assert "return" in body[scoped_call:probe_call], "刷完点名范围必须返回，不能再走探针"


def test_probe_fallback_kept_for_unscoped_calls() -> None:
    """没点名时仍走探针——那条路径是对的，不要一起改掉。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def refresh_worker_state", 1)[1].split("\ndef ", 1)[0]
    assert "refresh_stale_state_from_postgres(force=True)" in body


def test_first_load_still_falls_back_to_full_load() -> None:
    """从没加载过的集合，增量拉等于什么都没拉——必须整表加载。"""
    source = (BACKEND_ROOT / "apps" / "worker" / "tasks.py").read_text(encoding="utf-8")
    body = source.split("def refresh_worker_state", 1)[1].split("\ndef ", 1)[0]
    assert "if pending:" in body and "load_state(" in body
