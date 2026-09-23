"""Small, deliberately gated client for TypeSafe System One (Jev 1.13.0).

No production material is sent unless both the feature and the independently
recorded data-egress approval are enabled. The previously exposed key is not
read from any legacy JEV_KEY variable.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from typing import Any
from urllib.parse import urlsplit

MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_REQUEST_CHARS = 40_000
MAX_QUESTIONS_PER_REQUEST = 50


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
    if stage not in {"TABLE_CLASSIFICATION", "SECOND_OPINION", "CLAIM_SHADOW", "DOCUMENT_ROUTING"}:
        raise ValueError("unknown_jev_stage")
    return jev_enabled() and os.getenv(f"AICHECK_JEV_{stage}_ENABLED", "").lower() in {"1", "true", "yes"}


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
        payload = {"state": state, "model": MODEL, "questions": candidate}
        size = len(json.dumps(payload, ensure_ascii=False))
        if len(candidate) > max_questions or size > MAX_REQUEST_CHARS:
            if not batch:
                raise ValueError("jev_request_overlong")
            batches.append(batch)
            batch = {key: question}
            size = len(json.dumps({"state": state, "model": MODEL, "questions": batch}, ensure_ascii=False))
            if size > MAX_REQUEST_CHARS:
                raise ValueError("jev_request_overlong")
        else:
            batch = candidate
    if batch:
        batches.append(batch)
    return batches


def ask_jev(state: str, questions: dict[str, dict[str, Any]], *, timeout: float = 15.0) -> dict[str, Any]:
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
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
        all_answers.update(answers)
    return all_answers
