"""Small, deliberately gated client for TypeSafe System One (Jev 1.13.0).

No production material is sent unless both the feature and the independently
recorded data-egress approval are enabled. The previously exposed key is not
read from any legacy JEV_KEY variable.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_REQUEST_CHARS = 40_000
MAX_QUESTIONS_PER_REQUEST = 50
# 2026-09-23 实测：429/529（system_overloaded）是瞬时的，退避后重试即可；
# 400 max_tokens_exceeded 是输入超过约 32.8k token——密集中文约 3.3 万字就会撞上，
# 字符上限挡不住，重试也没用，要单独归为「请求超长」。
# 实测：密集中文 3.2 万字通过、3.5 万字被拒；真实资料混有数字和英文，约 0.63 token/字。
# 按中文 1 token/字、其余 0.35 token/字保守估算，超过就在送出前拦下。
MAX_ESTIMATED_INPUT_TOKENS = 32_000
RETRY_STATUSES = frozenset({429, 529})
RETRY_DELAYS_SECONDS = (2.0, 5.0)


def jev_endpoint() -> str:
    """Switch compatible Jev APIs through configuration, with an explicit host allowlist."""
    endpoint = str(os.getenv("AICHECK_JEV_API_URL") or ENDPOINT).strip()
    parsed = urlsplit(endpoint)
    approved = {
        host.strip().lower()
        for host in str(os.getenv("AICHECK_JEV_APPROVED_HOSTS") or "api.typesafe.ai").split(",")
        if host.strip()
    }
    if (parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in approved
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("jev_endpoint_not_approved")
    return endpoint


def jev_enabled() -> bool:
    enabled = os.getenv("AICHECK_JEV_ENABLED", "").lower() in {"1", "true", "yes"}
    approved = os.getenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "").lower() in {"1", "true", "yes"}
    return enabled and approved and bool(os.getenv("AICHECK_JEV_API_KEY"))


def jev_stage_enabled(stage: str) -> bool:
    if stage not in {"TABLE_CLASSIFICATION", "SECOND_OPINION", "CLAIM_SHADOW", "DOCUMENT_ROUTING",
                     "PRIMARY_DECISION", "FACT_CHECK"}:
        raise ValueError("unknown_jev_stage")
    return jev_enabled() and os.getenv(f"AICHECK_JEV_{stage}_ENABLED", "").lower() in {"1", "true", "yes"}


def estimated_input_tokens(text: str) -> int:
    """Conservative token estimate for Jev's input limit (about 32.8k tokens)."""
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff" or "\u3400" <= char <= "\u4dbf")
    return int(cjk + (len(text) - cjk) * 0.35) + 1


def _over_limit(state: str, batch: dict[str, dict[str, Any]]) -> bool:
    payload = json.dumps({"state": state, "model": MODEL, "questions": batch}, ensure_ascii=False)
    return len(payload) > MAX_REQUEST_CHARS or estimated_input_tokens(payload) > MAX_ESTIMATED_INPUT_TOKENS


def batch_jev_questions(
    state: str, questions: dict[str, dict[str, Any]],
    *, max_questions: int = MAX_QUESTIONS_PER_REQUEST,
) -> list[dict[str, dict[str, Any]]]:
    if not state or not questions:
        raise ValueError("jev_state_or_questions_empty")
    if max_questions < 1:
        raise ValueError("jev_invalid_batch_size")
    batches: list[dict[str, dict[str, Any]]] = []
    batch: dict[str, dict[str, Any]] = {}
    for key, question in questions.items():
        candidate = {**batch, key: question}
        if len(candidate) > max_questions or _over_limit(state, candidate):
            if not batch:
                raise ValueError("jev_request_overlong")
            batches.append(batch)
            batch = {key: question}
            if _over_limit(state, batch):
                raise ValueError("jev_request_overlong")
        else:
            batch = candidate
    if batch:
        batches.append(batch)
    return batches


def _post(request: urllib.request.Request, timeout: float) -> Any:
    for delay in (*RETRY_DELAYS_SECONDS, None):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and b"max_tokens_exceeded" in (exc.read() if exc.fp else b""):
                raise ValueError("jev_request_overlong") from exc
            if exc.code not in RETRY_STATUSES or delay is None:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def ask_jev(state: str, questions: dict[str, dict[str, Any]], *, timeout: float = 15.0,
            observe: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if not jev_enabled():
        raise RuntimeError("jev_data_egress_not_enabled")
    batches = batch_jev_questions(state, questions)
    endpoint = jev_endpoint()
    all_answers: dict[str, Any] = {}
    for batch in batches:
        body = json.dumps({"state": state, "model": MODEL, "questions": batch}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Authorization": f"Bearer {os.environ['AICHECK_JEV_API_KEY']}",
                     "Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            payload = _post(request, timeout)
            if not isinstance(payload, dict) or payload.get("model") != MODEL:
                raise ValueError("jev_unexpected_model_version")
            answers = payload.get("answers")
            if not isinstance(answers, dict) or set(answers) != set(batch):
                raise ValueError("jev_incomplete_answers")
            for key, question in batch.items():
                answer = answers[key]
                if not isinstance(answer, dict) or answer.get("type") != question.get("type"):
                    raise ValueError("jev_invalid_answer_type")
                if question.get("type") == "choice":
                    choice = answer.get("choice")
                    confidence = answer.get("confidence")
                    if (choice not in question.get("criteria", {}) or type(confidence) not in {int, float}
                            or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                        raise ValueError("jev_invalid_choice_answer")
        except (OSError, ValueError) as exc:
            if observe is not None:
                observe({"questionCount": len(batch), "elapsedSeconds": round(time.monotonic() - started, 3),
                         "usage": {}, "status": "transport_error" if isinstance(exc, OSError)
                         else "invalid_response"})
            raise
        all_answers.update(answers)
        if observe is not None:
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            allowed = {"input_tokens", "output_tokens", "total_tokens", "prompt_tokens",
                       "completion_tokens", "cost_usd", "total_cost_usd"}
            numeric_usage = {key: value for key, value in usage.items()
                             if key in allowed and type(value) in {int, float} and math.isfinite(value)}
            observe({"questionCount": len(batch), "elapsedSeconds": round(time.monotonic() - started, 3),
                     "usage": numeric_usage, "status": "completed"})
    return all_answers
