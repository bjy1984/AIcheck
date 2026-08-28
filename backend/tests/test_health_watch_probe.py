"""health_watch 的探针新鲜度判定：缺失/过期/有失败步必须告警，健康必须安静。

探针只在夜里跑，坏了没人看日志等于没跑——「不会报警的监控比没有监控更糟」。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

_SPEC = importlib.util.spec_from_file_location(
    "health_watch",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "health_watch.py",
)
health_watch = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(health_watch)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def _write(tmp_path, payload) -> str:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_missing_probe_file_alerts(tmp_path) -> None:
    alert = health_watch.probe_status_alert("写审计探针", str(tmp_path / "absent.json"), NOW)
    assert alert and "缺失" in alert


def test_stale_probe_alerts(tmp_path) -> None:
    path = _write(tmp_path, {"at": "2026-08-26 03:00:00", "total": 38, "failed": 0})
    alert = health_watch.probe_status_alert("写审计探针", path, NOW)
    assert alert and "未跑" in alert


def test_failed_steps_alert_with_names(tmp_path) -> None:
    path = _write(
        tmp_path,
        {"at": "2026-08-28 04:10:00", "total": 38, "failed": 2, "failedSteps": ["报审提交", "驳回"]},
    )
    alert = health_watch.probe_status_alert("写审计探针", path, NOW)
    assert alert and "2/38" in alert and "报审提交" in alert


def test_fresh_green_probe_is_quiet(tmp_path) -> None:
    path = _write(tmp_path, {"at": "2026-08-28 04:10:00", "total": 38, "failed": 0})
    assert health_watch.probe_status_alert("写审计探针", path, NOW) is None
