"""Read explicit percentages/grades from a uniquely mapped inspection record."""
import re
from copy import deepcopy

from libs.review_orchestrator.r39_reference_fields import _field


def supplement_ocr_parameters(parses, run, groups):
    fields, issues = [], []
    if groups["values"]:
        return fields, issues
    for parse in parses:
        if parse.get("tenantId") != run["tenantId"] or parse.get("profileId") not in {"ndt_rt_report_v1", "ndt_ut_report_v1"}:
            continue
        identity = {code: _field(parse, code, evidence_prefix="R40-FIELD-") for code in
                    ("ndt_document_kind", "weld_no", "detection_method", "detection_event_no", "record_no")}
        if (identity.get("ndt_document_kind") or {}).get("value") != "检测记录" or any(value is None for value in identity.values()):
            continue
        scope = {"projectId": run["projectId"], "objectId": identity["weld_no"]["value"],
                 "method": identity["detection_method"]["value"], "eventId": identity["detection_event_no"]["value"]}
        members = [row for row in groups["members"] if all(row.get(key) == value for key, value in scope.items())]
        records = [row for row in groups["records"] if all(row.get(key) == value for key, value in scope.items())
                   and row.get("recordId") == identity["record_no"]["value"]]
        if len(members) != 1 or len(records) != 1 or scope["method"] not in {"RT", "UT"}:
            continue
        for name in ("detection_ratio", "technical_grade"):
            if name not in (members[0].get("requiredParameters") or []):
                continue
            field = _field(parse, name, evidence_prefix="R40-FIELD-")
            if field is None:
                continue
            raw = field["value"]
            if name == "detection_ratio":
                match = re.fullmatch(r"(\d{1,3}(?:\.\d{1,6})?)\s*[%％]", raw)
                if not match or not 0 <= float(match[1]) <= 100:
                    issues.append({"code": "r40_ocr_percentage_not_explicit", "documentVersionId": parse["documentVersionId"]})
                    continue
                value, unit = float(match[1]), "%"
            else:
                value, unit = raw, ""
            sources = [*identity.values(), field]
            fields.extend(sources)
            groups["values"].append({**scope, "recordId": identity["record_no"]["value"], "parameter": name,
                "value": value, "unit": unit, "documentVersionId": parse["documentVersionId"],
                "evidence": deepcopy(field["evidence"]), "evidenceRefs": [deepcopy(item["evidence"]) for item in sources]})
    return fields, issues
