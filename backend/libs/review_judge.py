from __future__ import annotations

import json
import os
from typing import Any, Callable

JUDGE_SCHEMA_VERSION = "ReviewLlmJudge@1.0.0"
VALID_VERDICTS = {"supported", "unsupported", "insufficient_evidence"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def llm_judge_enabled() -> bool:
    """Opt-in: the judge adds one extra LLM call per review run."""
    return _env_bool("AICHECK_REVIEW_LLM_JUDGE", False)


def judge_limits() -> dict[str, int | float]:
    try:
        max_findings = max(1, int(os.getenv("AICHECK_REVIEW_JUDGE_MAX_FINDINGS", "5")))
    except (TypeError, ValueError):
        max_findings = 5
    try:
        max_tokens = max(256, int(os.getenv("AICHECK_REVIEW_JUDGE_MAX_TOKENS", "900")))
    except (TypeError, ValueError):
        max_tokens = 900
    try:
        timeout = max(10.0, float(os.getenv("AICHECK_REVIEW_JUDGE_TIMEOUT_SECONDS", "60")))
    except (TypeError, ValueError):
        timeout = 60.0
    return {"maxFindings": max_findings, "maxTokens": max_tokens, "timeoutSeconds": timeout}


def build_judge_messages(
    drafts: list[dict[str, Any]],
    retrieved_clauses: list[dict[str, Any]],
    evidence_texts: list[str],
) -> list[dict[str, str]]:
    findings_payload = [
        {
            "index": index,
            "title": str(draft.get("title") or "")[:200],
            "description": str(draft.get("description") or "")[:600],
            "kbRefs": draft.get("kbRefs") or [],
            "evidenceLinkIds": (draft.get("evidenceLinkIds") or [])[:5],
        }
        for index, draft in enumerate(drafts)
    ]
    clauses_payload = [
        {
            "clauseId": clause.get("clauseId"),
            "clauseNo": clause.get("clauseNo"),
            "title": clause.get("title"),
            "text": str(clause.get("text") or "")[:500],
        }
        for clause in retrieved_clauses[:8]
        if isinstance(clause, dict)
    ]
    user_payload = {
        "task": (
            "As an impartial audit judge, decide for every finding whether it is supported by "
            "the supplied standard clauses and OCR evidence. Judge only from the supplied "
            "material; never assume unstated facts."
        ),
        "verdicts": sorted(VALID_VERDICTS),
        "findings": findings_payload,
        "retrievedClauses": clauses_payload,
        "evidenceTexts": [str(text)[:400] for text in evidence_texts[:40]],
        "outputSchema": {
            "judgments": [
                {
                    "index": "number (finding index)",
                    "verdict": "supported|unsupported|insufficient_evidence",
                    "reason": "string (short, cite clauseId/evidence)",
                    "confidence": "0..1",
                }
            ]
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a strict evidence-groundedness judge for engineering-inspection review "
                "findings. Return JSON only, matching outputSchema exactly."
            ),
        },
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def parse_judge_response(text: str, *, finding_count: int) -> list[dict[str, Any]]:
    try:
        payload = json.loads(str(text or "").strip() or "{}")
    except ValueError:
        return []
    raw = payload.get("judgments") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    judgments: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= finding_count or index in seen:
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in VALID_VERDICTS:
            continue
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence"))))
        except (TypeError, ValueError):
            confidence = 0.5
        seen.add(index)
        judgments.append(
            {
                "index": index,
                "verdict": verdict,
                "reason": str(item.get("reason") or "")[:400],
                "confidence": confidence,
            }
        )
    return judgments


def apply_judgments_to_drafts(drafts: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> int:
    """Annotate drafts with judge verdicts; downgrade unsupported findings the
    same way the deterministic guardrails do. Returns the unsupported count."""
    unsupported = 0
    for judgment in judgments:
        index = int(judgment.get("index", -1))
        if not (0 <= index < len(drafts)):
            continue
        draft = drafts[index]
        draft["llmJudge"] = dict(judgment)
        if judgment.get("verdict") == "unsupported":
            unsupported += 1
            draft["groundingStatus"] = "insufficient_evidence"
            draft["suggestedAction"] = "human_confirm"
            draft["requiresHumanConfirmation"] = True
            try:
                draft["confidence"] = min(float(draft.get("confidence") or 0.55), 0.55)
            except (TypeError, ValueError):
                draft["confidence"] = 0.55
            draft.setdefault("llmGroundingWarnings", []).append(
                {
                    "code": "LLM_JUDGE_UNSUPPORTED",
                    "message": "LLM judge found this finding unsupported by the supplied clauses/evidence.",
                    "reason": judgment.get("reason"),
                }
            )
    return unsupported


def judge_review_findings(
    chat: Callable[..., str],
    drafts: list[dict[str, Any]],
    *,
    retrieved_clauses: list[dict[str, Any]] | None = None,
    evidence_texts: list[str] | None = None,
) -> dict[str, Any]:
    """Run the LLM judge over up to maxFindings drafts.

    ``chat(messages, max_tokens=..., timeout=...)`` must return the model's text.
    Always returns a summary; a failed call degrades (status=degraded) without
    raising, and judge results never block quality gates — they annotate drafts
    and surface warnings/metrics."""
    limits = judge_limits()
    window = [draft for draft in (drafts or []) if isinstance(draft, dict)][: int(limits["maxFindings"])]
    summary: dict[str, Any] = {
        "schemaVersion": JUDGE_SCHEMA_VERSION,
        "status": "skipped",
        "judgments": [],
        "warnings": [],
        "metrics": {
            "llmJudgeJudgedCount": 0,
            "llmJudgeUnsupportedCount": 0,
            "llmJudgeGroundedRate": None,
        },
        "limits": limits,
    }
    if not window:
        summary["warnings"].append({"code": "LLM_JUDGE_NO_FINDINGS"})
        return summary
    messages = build_judge_messages(
        window,
        retrieved_clauses or [],
        [str(item) for item in evidence_texts or []],
    )
    try:
        text = chat(messages, max_tokens=int(limits["maxTokens"]), timeout=float(limits["timeoutSeconds"]))
    except Exception as exc:
        summary["status"] = "degraded"
        summary["warnings"].append({"code": "LLM_JUDGE_DEGRADED", "reason": exc.__class__.__name__})
        return summary
    judgments = parse_judge_response(text, finding_count=len(window))
    if not judgments:
        summary["status"] = "degraded"
        summary["warnings"].append({"code": "LLM_JUDGE_UNPARSEABLE_RESPONSE"})
        return summary
    unsupported = apply_judgments_to_drafts(window, judgments)
    judged = len(judgments)
    summary.update(
        {
            "status": "ok",
            "judgments": judgments,
        }
    )
    summary["metrics"] = {
        "llmJudgeJudgedCount": judged,
        "llmJudgeUnsupportedCount": unsupported,
        "llmJudgeGroundedRate": round(1.0 - unsupported / judged, 4) if judged else None,
    }
    if unsupported:
        summary["warnings"].append({"code": "LLM_JUDGE_FOUND_UNSUPPORTED", "count": unsupported})
    return summary
