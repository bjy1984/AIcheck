"""Jev confirms whether the facts a rule used match the source documents.

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
import re
from datetime import date
from typing import Any

from libs.jev_evaluation_input import approved_ocr_text
from libs.review_input_data import latest_selected_parses
from libs.review_orchestrator.certificate_facts import CERTIFICATE_NODE_PROFILES
from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_usage_policy import LOW_CONFIDENCE

TEMPLATE_VERSION = "jev-fact-check-v4"
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


def _renderings(field: str, value: str) -> list[str]:
    """Ways the same value can be written in the original text (dates vary most)."""
    compact = re.sub(r"\s+", "", value)
    if field in {"validUntil", "validFrom"}:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return [compact]
        y, m, d = parsed.year, parsed.month, parsed.day
        # 只写到月的有效期（「2022年11月至2027年10月」）抽成月初/月末；整日写法都找不到时才认月份写法。
        return [f"{y}年{m}月{d}日", f"{y}年{m:02d}月{d:02d}日", f"{y}-{m:02d}-{d:02d}", f"{y}.{m:02d}.{d:02d}",
                f"{y}/{m:02d}/{d:02d}", f"{y}.{m}.{d}", f"{y}年{m}月", f"{y}年{m:02d}月"]
    return [compact]


def locate_value(state: dict[str, Any], review_run: dict[str, Any], versions: list[str],
                 field: str, value: str) -> dict[str, Any] | None:
    """First page and surrounding words where the value is literally written; None if it is nowhere."""
    parses = latest_selected_parses(state, {**review_run, "inputDocumentVersionIds": versions}, set(versions))
    needles = [item for item in _renderings(field, value) if item]
    fragments = [(version_id, fragment) for version_id in versions
                 for fragment in (parses.get(version_id) or {}).get("fragments") or [] if isinstance(fragment, dict)]
    for needle in needles:
        for version_id, fragment in fragments:
            body = re.sub(r"\s+", "", str(fragment.get("text") or ""))
            # 月份写法后面紧跟数字就是整日（「2022年11月9日」），不能当成只写到月。
            found = re.search(re.escape(needle) + (r"(?!\d)" if needle.endswith("月") else ""), body)
            hit = (found.start(), needle) if found else None
            if hit:
                start = max(hit[0] - 20, 0)
                return {"documentVersionId": version_id, "pageNo": fragment.get("pageNo"),
                        "quote": body[start:hit[0] + len(hit[1]) + 20], "matched": hit[1]}
    return None


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


# 设计说明里的耐压／泄漏试验要求（design_facts.design_special_requirements）。
# 只核对原文写明的内容；倍数是否达标等计算仍由确定性判据做。
DESIGN_FACT_FIELDS: tuple[tuple[str, str, str, str], ...] = (
    ("pressureTest", "method", "耐压试验", "试验方式"),
    ("pressureTest", "testPressure", "耐压试验", "试验压力"),
    ("pressureTest", "gaugeAccuracyClass", "耐压试验", "压力表精度等级"),
    ("pressureTest", "gaugeCount", "耐压试验", "压力表数量"),
    ("pressureTest", "acceptanceCriteria", "耐压试验", "合格标准"),
    ("leakTest", "method", "泄漏试验", "试验方式"),
    ("leakTest", "testPressure", "泄漏试验", "试验压力"),
    ("leakTest", "acceptanceCriteria", "泄漏试验", "合格标准"),
)
_DESIGN_TOOL = "evaluate_design_special_requirements"
_EVIDENCE_GATE_ONLY = frozenset({"locate_evidence_fragment", "validate_evidence_grounding"})


def certificate_fact_items(verification: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One item per certificate fact the rule used, with a fixed-template question."""
    items: list[dict[str, Any]] = []
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
            # 问持证人时用证号点名：合订本里「这张」指哪一张说不清，换成别人的名字也能答「是」。
            target = (f"{who}的{kind}" if holder and key != "holder"
                      else f"证件编号为{number}的{kind}" if key == "holder" and number else f"这张{kind}")
            items.append({
                "atomicCheckId": (verification or {}).get("atomicCheckId"), "documentVersionIds": versions,
                "certificateIndex": index, "certificateLabel": kind, "field": key, "value": value,
                "suspectLabel": f"{kind}·{_FIELD_LABELS[key]}={value}",
                "instructions": f"只看{target}：它的{name}是否为{_render(key, value)}？{guard}",
            })
    return items


def design_fact_items(business_facts: dict[str, Any] | None,
                      rule_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pressure and leak test requirements the design rule read from the design specification."""
    domains = (((business_facts or {}).get("designSpecialRequirements") or {}).get("domains") or {})
    atomic_id = next((str(item.get("atomicCheckId")) for record in rule_results
                      for item in record.get("atomicCheckResults") or []
                      if any(isinstance(tool, dict) and tool.get("toolName") == _DESIGN_TOOL
                             for tool in item.get("toolResults") or [])), None)
    items: list[dict[str, Any]] = []
    for domain_key, field, test_name, field_name in DESIGN_FACT_FIELDS:
        domain = domains.get(domain_key) or {}
        versions = sorted({str(item) for item in (domain.get("source") or {}).get("documentVersionIds") or [] if item})
        value = (domain.get("requirements") or {}).get(field)
        # 多条陈述归属不清时判据会留空，这里同样不问；来源不明的也不问。
        if not atomic_id or not versions or value in (None, "") or isinstance(value, (dict, list, bool)):
            continue
        value_text = str(int(value)) if isinstance(value, float) and value.is_integer() and field == "gaugeCount" \
            else str(value)
        items.append({
            "atomicCheckId": atomic_id, "documentVersionIds": versions, "certificateLabel": "设计说明",
            "field": f"{domain_key}.{field}", "value": value_text,
            "suspectLabel": f"设计说明·{test_name}{field_name}={value_text}",
            "instructions": (f"只看设计文件中关于{test_name}的要求：{field_name}是否写为{value_text}？"
                             "只核对原文写明的内容，不做换算或推算；其他试验的要求不算。"),
        })
    return items


_WELDER_TOOL = "extract_welder_certificate"


def welder_fact_items(business_facts: dict[str, Any] | None,
                      rule_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Welder certificate facts nodes 24/29 use: ID number, expiry and qualified item codes."""
    atomic_id = next((str(item.get("atomicCheckId")) for record in rule_results
                      for item in record.get("atomicCheckResults") or []
                      if any(isinstance(tool, dict) and tool.get("toolName") == _WELDER_TOOL
                             for tool in item.get("toolResults") or [])), None)
    certificates = [cert for key in ("r24", "r29")
                    for cert in ((business_facts or {}).get(key) or {}).get("certificates") or [] if isinstance(cert, dict)]
    names_by_version: dict[str, set[str]] = {}
    for cert in certificates:
        if cert.get("welderName") and cert.get("documentVersionId"):
            names_by_version.setdefault(str(cert["documentVersionId"]), set()).add(str(cert["welderName"]))
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for cert in certificates:
        version, name = str(cert.get("documentVersionId") or ""), str(cert.get("welderName") or "").strip()
        number = str(cert.get("welderCertificateNo") or "").strip()
        # 平台登记补上的代号不是 OCR 抽的，不拿来问原文。
        if not atomic_id or not version or not name or (cert.get("sources") or {}).get("qualificationCodes") == "cnse_platform":
            continue
        look_alike = any(name != other and name in other for other in names_by_version.get(version, set()))
        who = f"{name}（证件编号{number}）" if look_alike and number else name
        valid_until = str(cert.get("validUntil") or "").replace(".", "-")
        facts = [("certificateNo", "证件编号", number, "只看{who}的焊工资格证：它的证件编号是否为{value}？其他焊工的编号不算。"),
                 ("validUntil", "有效期截止日", valid_until,
                  "只看{who}的焊工资格证：它的有效期截止日是否为{value}？批准日期和其他焊工的日期都不是截止日。")]
        facts += [("qualificationCode", "合格项目", str(code),
                   "只看{who}的焊工资格证：考试合格作业项目中是否写有{value}？只核对原文写明的代号。")
                  for code in (cert.get("qualificationCodes") or [])[:3] if str(code).strip()]
        for field, label, value, template in facts:
            if not value or (version, field, f"{name}:{value}") in seen:
                continue
            seen.add((version, field, f"{name}:{value}"))
            shown = _render("validUntil", value) if field == "validUntil" else value
            items.append({"atomicCheckId": atomic_id, "documentVersionIds": [version], "certificateLabel": "焊工资格证",
                          "field": field, "value": value, "suspectLabel": f"焊工资格证·{name}·{label}={value}",
                          "instructions": template.format(who=who, value=shown)})
    return items


# 材料／元件类节点（R12–R23）记录上的标识性事实：编号、制造单位、产品、材质。
# 2026-09-23 本地快照：R16 的「证书编号」抽成了表头「监督检验证书编号 产品质量证明书编号」，
# 「制造单位」装进了整张表，R13 的产品名带着「（品种）」标签残留。
RECORD_FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("certificateNo", "证书编号"), ("reportNo", "报告编号"), ("manufacturerName", "制造单位"),
    ("productName", "产品名称"), ("material", "材质"),
    # 焊接工艺与施工记录（R25–R34）：工艺文件编号、母材与焊材。
    ("wpsNo", "焊接工艺规程（WPS）编号"), ("pqrNo", "焊接工艺评定（PQR）编号"),
    ("materialGrade", "母材牌号"), ("fillerMetal", "焊接材料"),
)
# 焊工证（r24/r29 的 certificates）由 welder_fact_items 按人核对，这里不重复。
_RECORD_NODES = frozenset({*(f"r{number}" for number in range(12, 24)), *(f"r{number}" for number in range(25, 35))})
_SKIPPED_COLLECTIONS = frozenset({("r29", "certificates")})
_MAX_FIELD_CHARS = 60


def _plausible_field_value(value: str) -> bool:
    """一个字段值不该是一段表格或多行正文。"""
    return (0 < len(value) <= _MAX_FIELD_CHARS and "\n" not in value and "|" not in value
            and not re.search(r"</?\w+[^>]*>", value) and len(re.findall(r"编号|名称|规格|材质", value)) < 2)


def record_fact_items(business_facts: dict[str, Any] | None,
                      rule_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identifying facts on material and component records (nodes 12–23)."""
    atomic_id = next((str(item.get("atomicCheckId")) for record in rule_results
                      for item in record.get("atomicCheckResults") or []
                      if any(isinstance(tool, dict) and str(tool.get("toolName") or "") not in _EVIDENCE_GATE_ONLY
                             for tool in item.get("toolResults") or [])), None)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for namespace, facts in sorted((business_facts or {}).items()):
        if namespace not in _RECORD_NODES or not isinstance(facts, dict) or not atomic_id:
            continue
        for collection, records in facts.items():
            if (namespace, collection) in _SKIPPED_COLLECTIONS:
                continue
            for record in records if isinstance(records, list) else []:
                version = str((record or {}).get("documentVersionId") or "") if isinstance(record, dict) else ""
                if not version:
                    continue
                subject = str(record.get("productName") or record.get("componentType") or "").strip()
                subject = subject if _plausible_field_value(subject) else ""
                for field, label in RECORD_FACT_FIELDS:
                    value = str(record.get(field) or "").strip()
                    if not value or (version, field, value) in seen:
                        continue
                    seen.add((version, field, value))
                    target = f"{subject}的{label}" if subject and field != "productName" else label
                    number_field = field in {"certificateNo", "reportNo", "wpsNo", "pqrNo"}
                    items.append({
                        "atomicCheckId": atomic_id, "documentVersionIds": [version], "certificateLabel": namespace.upper(),
                        "field": field, "value": value,
                        # 汉字写成、又没有数字的「编号」是标题或栏目名，本地直接标可疑。
                        "plausible": _plausible_field_value(value) and not (
                            number_field and not re.search(r"\d", value) and re.search(r"[一-龥]", value)),
                        "suspectLabel": f"{namespace.upper()}·{label}={value[:40]}",
                        "instructions": f"只看这份资料：{target}是否写为{value}？只核对原文写明的内容，表头和栏目名称不算。",
                    })
    return items


def fact_questions(verification: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Certificate questions grouped by source document (kept for callers of the first version)."""
    return _group(certificate_fact_items(verification))


def _group(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault("|".join(item["documentVersionIds"]), []).append(item)
    return grouped


def check_certificate_facts(state: dict[str, Any], review_run: dict[str, Any],
                            verification: dict[str, Any] | None) -> dict[str, Any]:
    """Ask Jev about each extracted certificate fact; return per-fact answers and suspects."""
    return check_facts(state, review_run, certificate_fact_items(verification))


def _as_written(state: dict[str, Any], review_run: dict[str, Any], versions: list[str],
                item: dict[str, Any]) -> str:
    """原文只写到月时，题目也只问到月：不能把「2022年11月」问成「2022年11月1日」再判它不符。"""
    if item["field"] not in {"validUntil", "validFrom"}:
        return item["instructions"]
    located = locate_value(state, review_run, versions, item["field"], item["value"])
    matched = (located or {}).get("matched") or ""
    if not re.fullmatch(r"\d{4}年\d{1,2}月", matched):
        return item["instructions"]
    return item["instructions"].replace(_render(item["field"], item["value"]), matched, 1)


def check_facts(state: dict[str, Any], review_run: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask Jev whether each fact is what the source documents state; mark confident "no" as suspect."""
    base: dict[str, Any] = {"model": MODEL, "templateVersion": TEMPLATE_VERSION, "facts": []}
    if not jev_stage_enabled("FACT_CHECK"):
        return {**base, "status": "disabled"}
    if str(review_run.get("reviewMode") or "formal") != "formal" or review_run.get("advisoryOnly"):
        return {**base, "status": "nonformal_run"}
    allowed = {item.strip() for item in os.getenv("AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS", "").split(",")
               if item.strip()}
    if str(review_run.get("projectId") or "") not in allowed:
        return {**base, "status": "project_not_approved_for_jev"}
    # 一眼就不像单一字段的抽取值（整张表、多行正文）本地直接标可疑，不用问 Jev。
    local = [{key: item[key] for key in ("atomicCheckId", "certificateLabel", "field", "value") if key in item}
             | {"documentVersionId": "|".join(item["documentVersionIds"]), "status": "implausible_value",
                "suspect": True, "suspectLabel": item["suspectLabel"] + "（抽取值不像单一字段，未送 Jev）"}
             for item in items if item.get("plausible") is False]
    grouped = _group([item for item in items if item.get("plausible") is not False])
    if not grouped and not local:
        return {**base, "status": "no_certificate_facts"}
    facts: list[dict[str, Any]] = list(local)
    statuses: set[str] = {"completed"} if local and not grouped else set()
    for group_key, group in sorted(grouped.items()):
        versions = group[0]["documentVersionIds"]
        status, text = approved_ocr_text(state, {**review_run, "inputDocumentVersionIds": versions})
        rows = [{key: item[key] for key in ("atomicCheckId", "certificateLabel", "field", "value", "suspectLabel")
                 if key in item} | {"documentVersionId": group_key} for item in group]
        if status != "ready":
            statuses.add(status)
            facts.extend({**row, "status": status} for row in rows)
            continue
        questions = {f"f{index}": {"type": "choice", "instructions": _as_written(state, review_run, versions, item),
                                   "criteria": CHOICES}
                     for index, item in enumerate(group)}
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
            suspect = choice == "no" and confidence >= LOW_CONFIDENCE
            # 可疑项附上本地找到的原文位置，监检一眼能核；原文里根本找不到这个值本身就是线索。
            located = locate_value(state, review_run, versions, row["field"], row["value"]) if suspect else None
            where = (f"（原文第{located['pageNo']}页：「{located['quote']}」）" if located
                     else "（原文中找不到这个值）") if suspect else ""
            facts.append({**row, "status": "completed", "choice": choice, "confidence": confidence,
                          "suspect": suspect, "lowConfidence": confidence < LOW_CONFIDENCE,
                          **({"located": located} if located else {}),
                          **({"suspectLabel": row["suspectLabel"] + where} if suspect else {})})
    questions_hash = hashlib.sha256(json.dumps(
        {key: [item["instructions"] for item in group] for key, group in sorted(grouped.items())},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    atomic_ids = sorted({str(item["atomicCheckId"]) for item in items if item.get("atomicCheckId")})
    return {**base, "status": "completed" if statuses == {"completed"} else
            "partial" if "completed" in statuses else min(statuses),
            "questionHash": questions_hash, "facts": facts, "atomicCheckIds": atomic_ids,
            "atomicCheckId": atomic_ids[0] if len(atomic_ids) == 1 else None,
            "suspects": [row["suspectLabel"] for row in facts if row.get("suspect")]}
