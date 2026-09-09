"""Classify review failures independently of the deployed retry consumer."""
from libs.integrations.errors import IntegrationServiceError

NON_RETRYABLE_REVIEW_REASONS = {
    "REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED",
    "REVIEW_COST_BUDGET_EXCEEDED",
    "REVIEW_MAX_ATTEMPTS_EXCEEDED",
    "LLM_OUTPUT_TRUNCATED",
    # 推理占满输出额度：重试只会再被吃光一次，要改的是预算不是次数
    "LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING",
    "LLM_OUTPUT_EMPTY",
    "LLM_OUTPUT_INVALID_JSON",
    "LLM_OUTPUT_INVALID_ENVELOPE",
    "LLM_OUTPUT_EMPTY_FINDINGS",
    "LLM_OUTPUT_INVALID_FINDING",
}


def review_failure_retryable(exc: Exception) -> bool:
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return False
    if isinstance(exc, IntegrationServiceError):
        if exc.reason in NON_RETRYABLE_REVIEW_REASONS:
            return False
        if exc.status_code in {408, 425, 429} or (exc.status_code is not None and exc.status_code >= 500):
            return True
        return bool(exc.reason and any(token in exc.reason for token in ("TIMEOUT", "UNAVAILABLE", "CONNECTION")))
    return isinstance(exc, (ConnectionError, TimeoutError, OSError, RuntimeError))

