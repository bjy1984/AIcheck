"""设计类节点的事实登记：把设计文件引用的标准编号登记成带页码和引文的 claimedFacts。

设计节点的 businessFacts 原来没有 judgment，execution 把 evidenceFacts 建成空列表，
validate_evidence_grounding 拿到 0 条事实，一律回证据不足，聚合时一票否决，业务工具判出的
不符合（ECD202 储罐 8 的 GB/T 12771-2008 已废止）被盖成「证据不足」。证书节点
（certificate_facts._certificate_judgment）和材料节点（material_facts.build_material_judgment）
09-11 修过同样的毛病，这里同构。

第一阶段登记节点 8（R08 标准版本）：它的不符合来自官方平台核实的废止，精确。
第二阶段登记节点 9（R09 专项要求）：登记前先让 R09 的规则按审查日期选标准、没抽到的值算证据不足
（business_tools.evaluate_design_special_requirements），否则假的不符合会被登记后的事实放出来。
别的设计节点的业务工具有假的不符合，登记前要先修，见 design_facts.build_design_business_facts。

MinerU 不给置信度（quality.reasons 含 provider_confidence_unavailable，片段 confidence 恒 0.0），
事实如实标 confidenceUnavailable，锚定门因此回 human_review_required（交人核对引文），
业务工具判的不符合不再被盖住，业务工具判的通过也只会是需人工，不会冒充通过。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from libs.review_grounding import REGULATION_CODE_RE

_QUOTE_RADIUS = 40


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("fieldValue") or item.get("value") or "")
    return str(item or "")


def _confidence_unavailable(parse_result: dict[str, Any]) -> bool:
    quality = parse_result.get("quality") if isinstance(parse_result.get("quality"), dict) else {}
    return "provider_confidence_unavailable" in (quality.get("reasons") or [])


def _page_sources(parse_result: dict[str, Any]):
    """(页码, 文字, bbox, 片段 confidence)：文字片段、表格行、抽取字段，都带页码才返回——没有页码的证据定位不了。"""
    for fragment in parse_result.get("fragments") or []:
        if isinstance(fragment, dict) and fragment.get("pageNo") is not None:
            yield int(fragment["pageNo"]), _text_of(fragment), fragment.get("bbox"), fragment.get("confidence")
    for table in parse_result.get("tables") or []:
        if not isinstance(table, dict) or table.get("pageNo") is None:
            continue
        for row in table.get("normalizedRows") or table.get("rows") or []:
            if isinstance(row, dict):
                yield int(table["pageNo"]), " ".join(str(value) for value in row.values() if value not in (None, "")), None, None
    for field in parse_result.get("fields") or []:
        if isinstance(field, dict) and field.get("pageNo") is not None:
            yield int(field["pageNo"]), _text_of(field), field.get("bbox"), field.get("confidence")


def locate_standard_codes(parse_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{编号: 第一处出现（页码、引文、bbox、片段分数）}。编号写法与 design_standard_references 一致。"""
    found: dict[str, dict[str, Any]] = {}
    for page_no, text, bbox, confidence in sorted(_page_sources(parse_result), key=lambda item: item[0]):
        for match in REGULATION_CODE_RE.finditer(text or ""):
            code = " ".join(match.group(0).split())
            if code in found:
                continue
            start, end = max(match.start() - _QUOTE_RADIUS, 0), match.end() + _QUOTE_RADIUS
            found[code] = {"pageNo": page_no, "quotedText": re.sub(r"\s+", " ", text[start:end]).strip(),
                           "bbox": bbox, "confidence": confidence}
    return found


def _ref_id(version_id: str, page_no: int, quoted: str) -> str:
    digest = hashlib.sha256(json.dumps([version_id, page_no, quoted], ensure_ascii=False).encode()).hexdigest()
    return "STDEV-" + digest[:12].upper()


def standard_reference_judgment(
    parse_by_version: dict[str, dict[str, Any]], versions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """每个能在文件里定位到页码和引文的标准编号登记一条事实；定位不到的不登记（没有证据的事实会让锚定门整体不通过）。"""
    claimed: list[dict[str, Any]] = []
    refs: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for version_id in sorted(parse_by_version):
        parse_result = parse_by_version[version_id]
        document = versions.get(version_id) or {}
        unavailable = _confidence_unavailable(parse_result)
        for code, where in locate_standard_codes(parse_result).items():
            if code in seen:
                continue
            seen.add(code)
            ref_id = _ref_id(version_id, where["pageNo"], where["quotedText"])
            try:
                score = None if unavailable else float(where["confidence"])
            except (TypeError, ValueError):
                score = None
            refs[ref_id] = {
                "id": ref_id, "evidenceRefId": ref_id, "documentVersionId": version_id,
                "documentId": document.get("id"), "fileName": document.get("fileName") or parse_result.get("fileName"),
                "pageNo": where["pageNo"], "bbox": where["bbox"], "quotedText": where["quotedText"],
                "source": "ocr_text", "confidence": score, "confidenceUnavailable": unavailable or score is None,
            }
            claimed.append({
                "factId": f"standard-{len(claimed) + 1}", "label": f"引用标准 {code}", "value": code,
                "standardRef": code, "documentVersionId": version_id, "evidenceRefIds": [ref_id],
                "confidence": score, "confidenceUnavailable": unavailable or score is None, "conflicted": False,
            })
    return {"claimedFacts": claimed, "evidenceRefs": list(refs.values())}


# 节点 9：四个专项领域各登记一条「设计里有这项要求」的事实，证据是设计文件里第一处提到它的页码和原句。
_DOMAIN_PATTERNS = {
    "ndt": re.compile(r"无损检测|射线检测|超声检测|磁粉检测|渗透检测|\bRT\b|\bUT\b"),
    "corrosion": re.compile(r"防腐|除锈|涂层|油漆|刷漆"),
    "pressureTest": re.compile(r"耐压试验|强度试验|水压试验|压力试验|气压试验|液压试验"),
    "leakTest": re.compile(r"泄漏性试验|泄漏试验|气密性试验|严密性试验"),
}
_DOMAIN_LABELS = {"ndt": "无损检测要求", "corrosion": "防腐要求", "pressureTest": "压力试验要求", "leakTest": "泄漏试验要求"}


def _first_domain_hit(parse_result: dict[str, Any], pattern: re.Pattern[str]) -> dict[str, Any] | None:
    for page_no, text, bbox, confidence in sorted(_page_sources(parse_result), key=lambda item: item[0]):
        match = pattern.search(text or "")
        if match:
            start, end = max(match.start() - _QUOTE_RADIUS, 0), match.end() + _QUOTE_RADIUS
            return {"pageNo": page_no, "quotedText": re.sub(r"\s+", " ", text[start:end]).strip(), "bbox": bbox, "confidence": confidence}
    return None


def special_requirement_judgment(
    parse_by_version: dict[str, dict[str, Any]], versions: dict[str, dict[str, Any]], domains: dict[str, Any],
) -> dict[str, Any]:
    """specified 为 True 的领域，在它的来源文件里找第一处提到该要求的页和原句，登记成事实；找不到的不登记。"""
    claimed: list[dict[str, Any]] = []
    refs: dict[str, dict[str, Any]] = {}
    for domain_name, pattern in _DOMAIN_PATTERNS.items():
        domain = domains.get(domain_name) if isinstance(domains.get(domain_name), dict) else {}
        if domain.get("specified") is not True:
            continue
        source_ids = [str(item) for item in (domain.get("source") or {}).get("documentVersionIds") or [] if str(item) in parse_by_version]
        for version_id in source_ids or sorted(parse_by_version):
            where = _first_domain_hit(parse_by_version[version_id], pattern)
            if where is None:
                continue
            unavailable = _confidence_unavailable(parse_by_version[version_id])
            try:
                score = None if unavailable else float(where["confidence"])
            except (TypeError, ValueError):
                score = None
            document = versions.get(version_id) or {}
            ref_id = _ref_id(version_id, where["pageNo"], where["quotedText"])
            refs[ref_id] = {
                "id": ref_id, "evidenceRefId": ref_id, "documentVersionId": version_id, "documentId": document.get("id"),
                "fileName": document.get("fileName") or parse_by_version[version_id].get("fileName"),
                "pageNo": where["pageNo"], "bbox": where["bbox"], "quotedText": where["quotedText"],
                "source": "ocr_text", "confidence": score, "confidenceUnavailable": unavailable or score is None,
            }
            claimed.append({
                "factId": f"requirement-{domain_name}", "label": _DOMAIN_LABELS[domain_name], "value": where["quotedText"][:80],
                "documentVersionId": version_id, "evidenceRefIds": [ref_id],
                "confidence": score, "confidenceUnavailable": unavailable or score is None, "conflicted": False,
            })
            break
    return {"claimedFacts": claimed, "evidenceRefs": list(refs.values())}
