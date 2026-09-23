"""Small, deliberately gated client for TypeSafe System One (Jev 1.13.0).

No production material is sent unless both the feature and the independently
recorded data-egress approval are enabled. The previously exposed key is not
read from any legacy JEV_KEY variable.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

MODEL = "jev-1.13.0"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"


def jev_enabled() -> bool:
    enabled = os.getenv("AICHECK_JEV_ENABLED", "").lower() in {"1", "true", "yes"}
    approved = os.getenv("AICHECK_JEV_DATA_EGRESS_APPROVED", "").lower() in {"1", "true", "yes"}
    return enabled and approved and bool(os.getenv("AICHECK_JEV_API_KEY"))


def jev_stage_enabled(stage: str) -> bool:
    if stage not in {"TABLE_CLASSIFICATION", "SECOND_OPINION", "CLAIM_SHADOW"}:
        raise ValueError("unknown_jev_stage")
    return jev_enabled() and os.getenv(f"AICHECK_JEV_{stage}_ENABLED", "").lower() in {"1", "true", "yes"}


def ask_jev(state: str, questions: dict[str, dict[str, Any]], *, timeout: float = 15.0) -> dict[str, Any]:
    if not jev_enabled():
        raise RuntimeError("jev_data_egress_not_enabled")
    if not state or not questions:
        raise ValueError("jev_state_or_questions_empty")
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
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
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("jev_incomplete_answers")
    for key, question in questions.items():
        answer = answers[key]
        if not isinstance(answer, dict) or answer.get("type") != question.get("type"):
            raise ValueError("jev_invalid_answer_type")
        if question.get("type") == "choice":
            choice = answer.get("choice")
            confidence = answer.get("confidence")
            if choice not in question.get("criteria", {}) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("jev_invalid_choice_answer")
    return answers
