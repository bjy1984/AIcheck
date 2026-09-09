"""Bind explicitly labelled OCR records to an already sourced event inventory."""
from copy import deepcopy

from libs.review_orchestrator.r39_reference_fields import _field


def supplement_ocr_records(parses, run, groups):
    fields, issues = [], []
    # Explicit business tables own this path; never bypass partial or contradictory tables.
    if groups["records"] or groups["reports"]:
        return fields, issues
    for parse in parses:
        if parse.get("tenantId") != run["tenantId"] or parse.get("profileId") not in {"ndt_rt_report_v1", "ndt_ut_report_v1"}:
            continue
        identity = {code: _field(parse, code, evidence_prefix="R40-FIELD-") for code in
                    ("ndt_document_kind", "weld_no", "detection_method", "detection_event_no")}
        kind = (identity.get("ndt_document_kind") or {}).get("value")
        number_key = {"检测记录": "record_no", "检测报告": "referenced_record_no"}.get(kind)
        if number_key:
            identity[number_key] = _field(parse, number_key, evidence_prefix="R40-FIELD-")
        if not number_key or any(value is None for value in identity.values()):
            issues.append({"code": "r40_ocr_identity_missing_or_ambiguous", "documentVersionId": parse["documentVersionId"]})
            continue
        scope = {"projectId": run["projectId"], "objectId": identity["weld_no"]["value"],
                 "method": identity["detection_method"]["value"], "eventId": identity["detection_event_no"]["value"]}
        matches = [row for row in groups["members"] if all(row.get(key) == value for key, value in scope.items())]
        if len(matches) != 1 or scope["method"] not in {"RT", "UT"}:
            issues.append({"code": "r40_ocr_event_mapping_missing_or_ambiguous", "documentVersionId": parse["documentVersionId"]})
            continue
        conclusion = _field(parse, "conclusion", evidence_prefix="R40-FIELD-")
        values = [*identity.values(), *([conclusion] if conclusion else [])]
        fields.extend(values)
        record = {**scope, "recordId": identity[number_key]["value"], "documentVersionId": parse["documentVersionId"],
                  "evidence": deepcopy(identity[number_key]["evidence"]),
                  "evidenceRefs": [deepcopy(value["evidence"]) for value in values]}
        if conclusion:
            record.update(conclusion=conclusion["value"], conclusionEvidenceRefs=deepcopy(conclusion["evidenceRefs"]))
        groups["records" if kind == "检测记录" else "reports"].append(record)
    return fields, issues
