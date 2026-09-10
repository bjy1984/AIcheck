"""今天栽的是「没分清失效和欠费」，所以测试主要测归类分不分得清。"""

import pytest

from libs.model_reachability import classify_failure, probe_provider, summarize


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_mean_the_key_is_wrong(status):
    assert classify_failure(status, "Incorrect API key provided") == "invalid_key"


def test_payment_required_means_no_money():
    assert classify_failure(402, "") == "no_balance"


def test_a_provider_that_reports_balance_in_a_400_is_still_no_balance():
    """DeepSeek 用 400 报欠费；光看状态码会误判成请求写错了。"""
    assert classify_failure(400, '{"error":{"message":"Insufficient Balance"}}') == "no_balance"
    assert classify_failure(200, "余额不足") == "no_balance"


@pytest.mark.parametrize("status", [500, 502, 503, 429, 408, None])
def test_server_side_and_timeouts_are_transient(status):
    assert classify_failure(status, "") == "unreachable"


def test_an_unrecognised_client_error_is_not_forced_into_a_bucket():
    """判不出来就说判不出来；猜一个会把人引到错误的处置上。"""
    assert classify_failure(404, "no such model") == "unknown"


def test_one_healthy_provider_makes_the_whole_thing_healthy():
    outcome = summarize([
        {"provider": "primary", "ok": False, "reason": "invalid_key", "status": 401},
        {"provider": "vision", "ok": True},
    ])
    assert outcome["ok"] is True
    assert outcome["healthyProviders"] == ["vision"]
    # 回退能用不代表主供应商坏了没人该管。
    assert outcome["failures"][0]["provider"] == "primary"


def test_when_everything_is_down_the_message_says_so_plainly():
    outcome = summarize([
        {"provider": "primary", "ok": False, "reason": "invalid_key", "status": 401},
        {"provider": "vision", "ok": False, "reason": "no_balance", "status": 402},
    ])
    assert outcome["ok"] is False
    assert "primary=invalid_key" in outcome["message"]
    assert "vision=no_balance" in outcome["message"]


def test_a_provider_with_no_key_is_reported_not_probed():
    result = probe_provider("primary", "https://x", "", "m", opener=lambda *a: None)
    assert result["reason"] == "not_configured"
    assert result["ok"] is False


def test_a_successful_ping_is_healthy():
    assert probe_provider("primary", "https://x", "k", "m", opener=lambda *a: b"{}")["ok"] is True


def test_the_probe_never_raises_even_when_the_call_explodes():
    """探针自己炸掉就等于没有探针。"""

    def boom(*_args):
        raise RuntimeError("socket closed")

    result = probe_provider("primary", "https://x", "k", "m", opener=boom)
    assert result["ok"] is False and result["reason"] == "unreachable"


def test_the_real_production_failure_is_classified_as_a_bad_key():
    """2026-09-10 阿里云的原文，逐字。"""
    body = ('{"error":{"message":"Incorrect API key provided. For details, see: '
            'https://help.aliyun.com/zh/model-studio/error-code#apikey-error",'
            '"type":"invalid_request_error","code":"invalid_api_key"}}')
    assert classify_failure(401, body) == "invalid_key"
