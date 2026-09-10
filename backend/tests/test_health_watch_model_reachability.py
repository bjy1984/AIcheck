"""密钥失效整整一天没人发现，这条测试守的就是"别再发生一次"。"""

from datetime import datetime, timedelta

import pytest

from libs.contracts.responses import SERVER_TZ
from scripts.health_watch import model_reachability_alerts, recent_model_success

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=SERVER_TZ)


def attempt(status, minutes_ago):
    at = NOW - timedelta(minutes=minutes_ago)
    return {"status": status, "createdAt": at.strftime("%Y-%m-%d %H:%M:%S")}


def test_a_recent_success_counts_as_proof_and_costs_nothing():
    """真实流量成功过就不必再探——探针要便宜到可以每 10 分钟跑。"""
    assert recent_model_success([attempt("success", 30)], NOW) is True
    assert model_reachability_alerts([attempt("success", 30)], NOW) == []


def test_an_old_success_is_not_proof():
    """2026-09-09 04:11 那次成功之后就一直坏着；只看"曾经成功过"等于不看。"""
    assert recent_model_success([attempt("success", 60 * 24)], NOW) is False


def test_failures_alone_are_not_proof():
    assert recent_model_success([attempt("failed", 5), attempt("running", 5)], NOW) is False


def test_an_unparseable_timestamp_does_not_count_as_success():
    assert recent_model_success([{"status": "success", "createdAt": "昨天"}], NOW) is False


def test_a_malformed_row_does_not_crash_the_audit():
    assert recent_model_success([None, "x", {"status": "success"}], NOW) is False


@pytest.mark.parametrize(
    "reason,status,hint",
    [
        ("invalid_key", 401, "重新签发"),
        ("no_balance", 402, "充值"),
        ("not_configured", None, "没配"),
        ("unreachable", 503, "先观察"),
    ],
)
def test_each_failure_says_what_to_actually_do(monkeypatch, reason, status, hint):
    """失效、欠费、连不上处置方式完全不同——2026-09-10 差点因为混淆而修错方向。"""
    import scripts.health_watch as hw

    monkeypatch.setattr(
        "libs.model_reachability.probe_provider",
        lambda *a, **k: {"provider": "primary", "ok": False, "reason": reason,
                         "status": status, "detail": ""},
    )
    monkeypatch.setattr("libs.qwen_runtime.qwen_runtime_config", lambda *a, **k: {"baseUrl": "https://x", "models": {}})
    monkeypatch.setattr("libs.qwen_runtime.official_api_key", lambda *a, **k: "k")
    alerts = hw.model_reachability_alerts([], NOW)
    assert len(alerts) == 1
    assert reason in alerts[0] and hint in alerts[0]


def test_a_reachable_model_produces_no_alert(monkeypatch):
    import scripts.health_watch as hw

    monkeypatch.setattr(
        "libs.model_reachability.probe_provider",
        lambda *a, **k: {"provider": "primary", "ok": True, "reason": None, "status": 200},
    )
    monkeypatch.setattr("libs.qwen_runtime.qwen_runtime_config", lambda *a, **k: {"baseUrl": "https://x", "models": {}})
    monkeypatch.setattr("libs.qwen_runtime.official_api_key", lambda *a, **k: "k")
    assert hw.model_reachability_alerts([], NOW) == []


def test_the_check_failing_is_reported_not_swallowed(monkeypatch):
    """巡检里一个检查坏了要说出来，不能让它看起来像"一切正常"。"""
    import scripts.health_watch as hw

    monkeypatch.setattr("libs.qwen_runtime.qwen_runtime_config",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    alerts = hw.model_reachability_alerts([], NOW)
    assert len(alerts) == 1 and "无法执行" in alerts[0]
