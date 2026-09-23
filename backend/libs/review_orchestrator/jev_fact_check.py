"""Jev confirms whether the certificate facts a rule used match the document.

This is the role Jev measured best at (docs/lab/verification/2026-09-23-jev-boundary-suite.md):
"is this value what the text states for this certificate" was right 32/32, and it
picked the named certificate out of a bundle 8/8. The one real rule error found
in the Lab (R02-02) was exactly this kind: the extractor read the start of a
validity range as its end.

Questions are built from the extracted values with a fixed template, so the same
facts always give the same questions; no model writes them. Only the document a
certificate came from is sent. A "no" at confidence >= 0.70 marks the fact as
suspect for a human to look at first; nothing here changes a rule result.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from typing import Any

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_orchestrator.certificate_facts import CERTIFICATE_NODE_PROFILES
from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_usage_policy import LOW_CONFIDENCE

TEMPLATE_VERSION = "jev-certificate-fact-check-v2"
CHOICES = {
    "yes": "原文明确写明这张证书的该项内容就是题目给出的值",
    "no": "原文写明的该项内容与题目给出的值不同，或题目给出的其实是别的日期、别的编号或其他证书的内容",
    "cannot_determine": "原文没有写明这张证书的该项内容，或文字无法辨认，无法判断",
}
# (fact key, how the question names it, extra wording that rules out look-alikes)
FACT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("validUntil", "有效期截止日", "起始日、发证日期和其他证书的日期都不是截止日。"),
    ("validFrom", "有效期起始日", "截止日和其他证书的日期都不是起始日。"),
    ("certificateNo", "证书编号", "其他证书的编号不算。"),
    ("holder", "持证单位或持证人", "其他证书的持证人不算。"),
)
_FIELD_LABELS = {key: label for key, label, _ in FACT_FIELDS}
_TYPE_LABELS = {profile["certificateType"]: profile["label"] for profile in CERTIFICATE_NODE_PROFILES.values()}


def _render(key: str, value: str) -> str:
    if key in {"validUntil", "validFrom"}:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return value
        return f"{parsed.year}年{parsed.month}月{parsed.day}日"
    return value


def _look_alike_holders(certificates: list[Any]) -> set[str]:
    """Holders whose name is part of another holder's name in the same document (李卫 / 李卫伍)."""
    by_version: dict[str, set[str]] = {}
    for cert in certificates:
        if not isinstance(cert, dict) or not str(cert.get("holder") or "").strip():
            continue
        for ref in cert.get("evidenceRefs") or []:
            if isinstance(ref, dict) and ref.get("documentVersionId"):
                by_version.setdefault(str(ref["documentVersionId"]), set()).add(str(cert["holder"]).strip())
    return {name for names in by_version.values() for name in names
            if any(name != other and name in other for other in names)}


def fact_questions(verification: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Fixed-template questions per source document version, from the rule's own certificate facts."""
    by_version: dict[str, list[dict[str, Any]]] = {}
    certificates = (verification or {}).get("certificates") or []
    # Jev 在同表「李卫／李卫伍」上以 0.41 答错过；名字互为包含时连证号一起点名。
    look_alike = _look_alike_holders(certificates)
    for index, cert in enumerate(certificates):
        if not isinstance(cert, dict):
            continue
        versions = sorted({str(ref.get("documentVersionId")) for ref in cert.get("evidenceRefs") or []
                           if isinstance(ref, dict) and ref.get("documentVersionId")})
        # A fact with no single source document cannot be checked against one text.
        if len(versions) != 1:
            continue
        kind = _TYPE_LABELS.get(str(cert.get("certificateType") or verification.get("certificateType") or ""), "证书")
        holder = str(cert.get("holder") or "").strip()
        for key, name, guard in FACT_FIELDS:
            value = str(cert.get(key) or "").strip()
            if not value:
                continue
            # 同一份资料里可能有几个人的证：除了问持证人本身，都点名是谁的证。
            number = str(cert.get("certificateNo") or "").strip()
            who = f"{holder}（证件编号{number}）" if holder in look_alike and number and key != "certificateNo" else holder
            target = f"{who}的{kind}" if holder and key != "holder" else f"这张{kind}"
            by_version.setdefault(versions[0], []).append({
                "certificateIndex": index, "certificateLabel": kind, "field": key, "value": value,
                "instructions": f"只看{target}：它的{name}是否为{_render(key, value)}？{guard}",
            })
    return by_version


def check_certificate_facts(state: dict[str, Any], review_run: dict[str, Any],
                            verification: dict[str, Any] | None) -> dict[str, Any]:
    """Ask Jev about each extracted certificate fact; return per-fact answers and suspects."""
    base: dict[str, Any] = {"model": MODEL, "templateVersion": TEMPLATE_VERSION, "facts": []}
    if not jev_stage_enabled("FACT_CHECK"):
        return {**base, "status": "disabled"}
    if str(review_run.get("reviewMode") or "formal") != "formal" or review_run.get("advisoryOnly"):
        return {**base, "status": "nonformal_run"}
    allowed = {item.strip() for item in os.getenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "").split(",")
               if item.strip()}
    if str(review_run.get("projectId") or "") not in allowed:
        return {**base, "status": "project_not_approved_for_jev"}
    by_version = fact_questions(verification)
    if not by_version:
        return {**base, "status": "no_certificate_facts"}
    facts: list[dict[str, Any]] = []
    statuses: set[str] = set()
    for version_id, items in sorted(by_version.items()):
        status, text = approved_ocr_text(state, {**review_run, "inputDocumentVersionIds": [version_id]})
        rows = [{key: item[key] for key in ("certificateIndex", "certificateLabel", "field", "value")}
                | {"documentVersionId": version_id} for item in items]
        if status != "ready":
            statuses.add(status)
            facts.extend({**row, "status": status} for row in rows)
            continue
        questions = {f"f{index}": {"type": "choice", "instructions": item["instructions"], "criteria": CHOICES}
                     for index, item in enumerate(items)}
        try:
            answers = ask_jev(text, questions)
        except (OSError, RuntimeError, ValueError) as exc:
            code = "request_overlong" if str(exc) == "jev_request_overlong" else "unavailable"
            statuses.add(code)
            facts.extend({**row, "status": code} for row in rows)
            continue
        statuses.add("completed")
        for index, row in enumerate(rows):
            answer = answers[f"f{index}"]
            choice, confidence = answer["choice"], float(answer["confidence"])
            facts.append({**row, "status": "completed", "choice": choice, "confidence": confidence,
                          "suspect": choice == "no" and confidence >= LOW_CONFIDENCE,
                          "lowConfidence": confidence < LOW_CONFIDENCE})
    questions_hash = hashlib.sha256(json.dumps(
        {version: [item["instructions"] for item in items] for version, items in sorted(by_version.items())},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {**base, "status": "completed" if statuses == {"completed"} else
            "partial" if "completed" in statuses else min(statuses),
            "questionHash": questions_hash, "facts": facts,
            "atomicCheckId": (verification or {}).get("atomicCheckId"),
            "suspects": [f"{row['certificateLabel']}·{_FIELD_LABELS[row['field']]}={row['value']}"
                         for row in facts if row.get("suspect")]}
