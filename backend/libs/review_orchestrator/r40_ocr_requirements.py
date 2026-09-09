"""Read requirements only from the version explicitly assigned by a sourced event member."""
import re
from copy import deepcopy

from libs.review_orchestrator.r39_reference_fields import _field

OPERATORS = {">=": "gte", "≥": "gte", "至少": "gte", "不低于": "gte", "不少于": "gte",
             "<=": "lte", "≤": "lte", "不超过": "lte", "最多": "lte", "=": "eq", "等于": "eq"}


def supplement_ocr_requirements(parses, run, groups):
    fields, issues = [], []
    if groups["requirements"]:
        return fields, issues
    for member in groups["members"]:
        version = member.get("requirementsVersionId")
        if not isinstance(version, str) or not version:
            continue
        candidates = [parse for parse in parses if parse.get("documentVersionId") == version
                      and parse.get("tenantId") == run["tenantId"] and parse.get("profileId") == "ndt_procedure_v1"]
        if len(candidates) != 1:
            issues.append({"code": "r40_requirement_version_unavailable"})
            continue
        parse = candidates[0]
        identity = {code: _field(parse, code, evidence_prefix="R40-FIELD-") for code in ("document_kind", "method")}
        if (any(value is None for value in identity.values()) or identity["document_kind"]["value"] not in {"工艺规程", "操作指导书"}
                or identity["method"]["value"] != member.get("method") or member.get("projectId") != run["projectId"]):
            issues.append({"code": "r40_requirement_method_or_kind_ambiguous", "documentVersionId": version})
            continue
        for parameter in ("detection_ratio", "technical_grade"):
            if parameter not in (member.get("requiredParameters") or []):
                continue
            field = _field(parse, parameter + "_requirement", evidence_prefix="R40-FIELD-")
            if field is None:
                continue
            raw = field["value"]
            if parameter == "detection_ratio":
                match = re.fullmatch(r"(>=|<=|≥|≤|至少|不低于|不少于|不超过|最多|=|等于)\s*(\d{1,3}(?:\.\d{1,6})?)\s*[%％]", raw)
                if not match or not 0 <= float(match[2]) <= 100:
                    issues.append({"code": "r40_requirement_operator_or_percentage_unknown", "documentVersionId": version})
                    continue
                value, operator, unit = float(match[2]), OPERATORS[match[1]], "%"
            else:
                match = re.fullmatch(r"(?:=|等于)\s*(\S+)", raw)
                if not match:
                    issues.append({"code": "r40_requirement_grade_operator_unknown", "documentVersionId": version})
                    continue
                value, operator, unit = match[1], "eq", ""
            sources = [*identity.values(), field]
            fields.extend(sources)
            scope = {key: member.get(key) for key in ("projectId", "objectId", "method", "eventId")}
            groups["requirements"].append({**scope, "parameter": parameter, "operator": operator,
                "value": value, "unit": unit, "documentVersionId": version, "evidence": deepcopy(field["evidence"]),
                "evidenceRefs": [deepcopy(item["evidence"]) for item in sources]})
    return fields, issues
