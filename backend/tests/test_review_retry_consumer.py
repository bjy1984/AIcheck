"""retry_pending 必须有人认领（issue #12 R-8 旁支）。

查 R-8 时发现的活 bug：retryable 的失败会把运行标成 retry_pending，而这个状态
的唯一消费方是 Temporal 的审查 worker（apps/review_worker/activities.py）。
线上跑的是 inline 编排、根本没起那个 worker——于是运行永远停在那儿，界面显示
「等待重试」，等的却是一个不存在的人。

这比 R-8 本身（重试重跑整图、成本翻倍）更要紧：成本翻倍看得见，
永远等待看不见。
"""

from __future__ import annotations

import pytest

from libs.integrations.errors import IntegrationServiceError
from libs.review_orchestrator.execution import review_failure_retryable
from libs.review_orchestrator.retry_policy import has_review_retry_consumer


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("temporal", True),
        ("inline", False),
        ("legacy", False),
        ("", False),
    ],
)
def test_retry_consumer_exists_only_under_temporal(monkeypatch, mode: str, expected: bool) -> None:
    """只有 Temporal 编排下才有东西会来重试。

    线上是 inline，所以这条的实际效果是：不再承诺一个没人兑现的重试。
    """
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", mode)
    assert has_review_retry_consumer() is expected


def test_transient_failures_are_still_classified_as_retryable() -> None:
    """判断「这次失败是不是瞬时的」本身不受编排模式影响。

    两件事要分开：失败的性质（瞬时/永久）是事实，有没有人来重试是部署状态。
    混在一起会让人以为超时变成了不可恢复的错误。
    """
    assert review_failure_retryable(IntegrationServiceError("Qwen", "chat", reason="TIMEOUT")) is True
    assert review_failure_retryable(ValueError("参数错")) is False


def test_non_retryable_reasons_stay_non_retryable(monkeypatch) -> None:
    """预算超限这类失败重跑必然再失败，任何编排模式下都不该标成可重试。"""
    monkeypatch.setenv("AICHECK_REVIEW_ORCHESTRATION", "temporal")
    exc = IntegrationServiceError("Qwen", "chat", reason="REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED")
    assert review_failure_retryable(exc) is False
