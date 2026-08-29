"""OCR 运行体检的短 TTL 缓存。

这是一次同步跨服务 HTTP 往返（实测 495ms），占 /fde/ocr-quality 总耗时 82%——
而体检结果不是实时量。没有缓存时每次刷新、每个用户都各打一次 OCR 服务。

关键约束：**失败结果不缓存**——故障恢复后要立刻反映，不能被缓存粘住。
"""

from __future__ import annotations

import libs.fde_console_views as views


def _reset() -> None:
    views._OCR_DOCTOR_CACHE["report"] = None
    views._OCR_DOCTOR_CACHE["at"] = 0.0


def test_successful_report_is_cached_within_ttl(monkeypatch) -> None:
    _reset()
    calls = []
    monkeypatch.setattr(
        views,
        "_fde_ocr_runtime_doctor_report_uncached",
        lambda: calls.append(1) or {"ok": True, "checks": [{"name": "ocr.base-url"}]},
    )
    first = views.fde_ocr_runtime_doctor_report()
    second = views.fde_ocr_runtime_doctor_report()
    assert len(calls) == 1  # 第二次走缓存，不再打 OCR 服务
    assert first == second
    # 返回的是副本：调用方改动不得污染缓存
    second["checks"].append({"name": "tampered"})
    assert len(views.fde_ocr_runtime_doctor_report()["checks"]) == 1


def test_failed_report_is_never_cached(monkeypatch) -> None:
    _reset()
    calls = []
    monkeypatch.setattr(
        views,
        "_fde_ocr_runtime_doctor_report_uncached",
        lambda: calls.append(1) or {"ok": False, "checks": []},
    )
    views.fde_ocr_runtime_doctor_report()
    views.fde_ocr_runtime_doctor_report()
    assert len(calls) == 2  # 每次都重打：故障恢复要立刻反映


def test_ttl_expiry_refetches(monkeypatch) -> None:
    _reset()
    calls = []
    monkeypatch.setattr(
        views,
        "_fde_ocr_runtime_doctor_report_uncached",
        lambda: calls.append(1) or {"ok": True, "checks": []},
    )
    views.fde_ocr_runtime_doctor_report()
    views._OCR_DOCTOR_CACHE["at"] -= 999  # 假装很久以前
    views.fde_ocr_runtime_doctor_report()
    assert len(calls) == 2


def test_ttl_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_DOCTOR_CACHE_SECONDS", "5")
    assert views._ocr_doctor_cache_ttl() == 5.0
    monkeypatch.setenv("AICHECK_OCR_DOCTOR_CACHE_SECONDS", "not-a-number")
    assert views._ocr_doctor_cache_ttl() == 30.0
