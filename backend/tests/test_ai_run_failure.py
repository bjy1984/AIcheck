"""AI 运行失败归因。

线上那条真实报错是这轮的起点：界面只显示「异常」两个字，而库里躺着完整的
Temporal 连接错误。这些用例钉住的不是措辞，是两个判断——谁的问题、重跑有没有用。
"""

from __future__ import annotations

from libs.ai_run_failure import (
    FAILED_STATUSES,
    FailureKind,
    ai_run_failure_view,
    classify_failure,
)


def test_real_online_temporal_error_is_classified_as_orchestration() -> None:
    """线上真实报错原文，一字未改。

    监检看到「异常」时不知道该不该重跑；这条属于环境问题，重跑只是再失败一次。
    """
    message = (
        "Failed client connect: Server connection error: "
        "tonic::transport::Error(Transport, ConnectError(ConnectionRefused))"
    )
    kind, reason, retryable = classify_failure(message)
    assert kind == FailureKind.ORCHESTRATION
    assert retryable is False, "编排服务没起来时，重跑无用——不能诱导用户白点"
    assert "编排" in reason


def test_model_errors_are_not_retryable() -> None:
    """模型没配好属于环境问题，同样不该让人反复重跑。"""
    for message in (
        "litellm.APIError: connection refused",
        "Invalid API key provided",
        "HTTP 401 Unauthorized from deepseek",
    ):
        kind, _, retryable = classify_failure(message)
        assert kind == FailureKind.MODEL, message
        assert retryable is False, message


def test_timeout_is_retryable() -> None:
    """超时是少数重跑真有用的情形。"""
    kind, _, retryable = classify_failure("Request timed out after 120s")
    assert kind == FailureKind.TIMEOUT
    assert retryable is True


def test_orchestration_wins_over_model_when_both_appear() -> None:
    """两者同时出现时归编排。

    Temporal 都没连上，模型配没配根本轮不到——先报模型会把人引到错的方向。
    """
    kind, _, _ = classify_failure(
        "litellm proxy unreachable: tonic::transport::Error ConnectionRefused"
    )
    assert kind == FailureKind.ORCHESTRATION


def test_unknown_failure_still_gets_a_next_step() -> None:
    """认不出来也要说下一步。只说「失败了」等于把问题原样丢回给用户。"""
    view = ai_run_failure_view({"status": "失败", "errorMessage": "某种没见过的错"})
    assert view is not None
    assert view["kind"] == FailureKind.UNKNOWN
    assert view["nextStep"], "任何分类都必须给出下一步"
    assert view["detail"] == "某种没见过的错", "原文要留给运维查"


def test_successful_run_has_no_failure_block() -> None:
    """没失败就不该出现 failure 字段，否则界面会误报。"""
    assert ai_run_failure_view({"status": "完成"}) is None
    assert ai_run_failure_view({"status": "待人工确认"}) is None


def test_all_failure_status_spellings_are_covered() -> None:
    """中英混用是历史遗留：ai_runs 写中文，review_runs 写英文。

    漏掉任何一种写法，那条链路的失败就继续静默——这正是本次要修的问题本身。
    """
    for status in ("失败", "failed", "failed_to_start", "error"):
        assert status in FAILED_STATUSES
        assert ai_run_failure_view({"status": status}) is not None


def test_missing_error_message_is_called_out_not_blanked() -> None:
    """没记原始报错时要明说。

    线上 review_runs 的 failed_to_start 和 ocr_jobs 的 failed 就是这样——
    连原因都没落库。给空字符串会让人以为是界面坏了，而不是数据本身缺失。
    """
    view = ai_run_failure_view({"status": "failed_to_start"})
    assert view is not None
    assert view["detailRecorded"] is False
    assert "未记录" in view["detail"]


def test_error_code_is_used_when_message_absent() -> None:
    """review_runs 的对账脚本写的是 errorCode 而非 errorMessage，两个都要认。"""
    view = ai_run_failure_view({"status": "failed_to_start", "errorCode": "TEMPORAL_UNREACHABLE"})
    assert view is not None
    assert view["kind"] == FailureKind.ORCHESTRATION
    assert view["detailRecorded"] is True


def test_bare_connection_refused_is_not_blamed_on_orchestration() -> None:
    """泛化的 "connection refused" 不能算编排问题。

    模型代理连不上也是这句话。第一版把它归给 Temporal，会让运维去查一个好好的
    服务——归错因比不归因更浪费时间。认不出来就老实说认不出来。
    """
    kind, _, _ = classify_failure("connection refused")
    assert kind == FailureKind.UNKNOWN
