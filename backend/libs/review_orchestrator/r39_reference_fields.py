"""Match selected instruction/procedure files by grounded OCR identity fields."""
from copy import deepcopy

from libs.ocr.page_coverage import review_coverage_gap
from libs.review_input_data import selected_parse_results
from libs.review_tools.r39_tools import _text
from libs.review_workstations import digest

FIELDS = ("procedure_no", "procedure_revision", "organization_name", "document_kind", "method")


def _field(parse, code, *, evidence_prefix="R39-FIELD-"):
    rows = [row for row in parse.get("fields", []) if isinstance(row, dict) and row.get("fieldCode") == code]
    if len(rows) != 1:
        return None
    row = rows[0]
    value, confidence, page = row.get("fieldValue"), row.get("confidence"), row.get("pageNo")
    if (not _text(value) or type(confidence) not in (int, float) or not .75 <= confidence <= 1
            or type(page) is not int or page < 1 or "field_value_conflict" in (row.get("qualityFlags") or [])
            or row.get("conflicted", False) is not False):
        return None
    fragments = [item for item in parse.get("fragments", []) if isinstance(item, dict)
                 and item.get("pageNo") == page and item.get("bbox") == row.get("bbox")
                 and _text(item.get("text")) and value in item["text"]]
    if len(fragments) != 1:
        return None
    ref = {"documentVersionId": parse["documentVersionId"], "pageNo": page, "bbox": deepcopy(row.get("bbox")),
           "quotedText": fragments[0]["text"], "confidence": confidence}
    ref["id"] = evidence_prefix + digest({"fieldCode": code, **ref})[:24]
    ref["evidenceRefId"] = ref["id"]
    return {"value": value, "documentVersionId": parse["documentVersionId"], "evidence": ref, "evidenceRefs": [ref]}


def _document(state, run, parse):
    if parse.get("tenantId") != run["tenantId"]:
        return None
    versions = [row for row in state.get("versions", []) if row.get("id") == parse.get("documentVersionId")
                and row.get("tenantId") == run["tenantId"]]
    if len(versions) != 1:
        return None
    documents = [row for row in state.get("documents", []) if row.get("id") == versions[0].get("documentId")
                 and row.get("projectId") == run["projectId"] and row.get("tenantId") == run["tenantId"]]
    if len(documents) != 1:
        return None
    fields = {code: _field(parse, code) for code in FIELDS}
    if any(value is None for value in fields.values()):
        return None
    kind = {"工艺规程": "procedure", "操作指导书": "instruction"}.get(fields["document_kind"]["value"])
    if kind is None:
        return None
    if kind == "instruction":
        fields.update({code: _field(parse, code) for code in ("referenced_procedure_no", "referenced_procedure_revision")})
    if any(value is None for value in fields.values()):
        return None
    return kind, (documents[0]["id"], versions[0]["id"], fields)


def _pair(run, instruction, procedure):
    records = [*instruction[2].values(), *procedure[2].values()]
    scope = {"projectId": run["projectId"], "organizationName": instruction[2]["organization_name"]["value"],
             "method": instruction[2]["method"]["value"], "instructionDocumentId": instruction[0],
             "instructionDocumentVersionId": instruction[1], "procedureDocumentId": procedure[0], "procedureDocumentVersionId": procedure[1]}
    def record(values, **extra):
        return {**scope, **extra, "evidenceRefs": [deepcopy(item["evidence"]) for item in values]}
    return {"projectId": run["projectId"], "identityMode": "exact_source_organization_name", "scope": scope,
            "basis": record(records, applicable=True),
            "instructionReference": record(instruction[2].values(), referencedProcedureNumber=instruction[2]["referenced_procedure_no"]["value"],
                                           referencedProcedureVersion=instruction[2]["referenced_procedure_revision"]["value"]),
            "procedureIdentity": record(procedure[2].values(), procedureNumber=procedure[2]["procedure_no"]["value"],
                                        procedureVersion=procedure[2]["procedure_revision"]["value"])}, records


def reference_from_fields(state, run):
    parses = [row for row in selected_parse_results(state, {}, context={"reviewRun": run})
              if row.get("profileId") == "ndt_procedure_v1"]
    by_version = {}
    for parse in parses:
        by_version.setdefault(parse.get("documentVersionId"), []).append(parse)
    selected = set(run.get("inputDocumentVersionIds", []))
    ndt_documents = {row.get("id") for row in state.get("documents", []) if row.get("tenantId") == run["tenantId"]
                     and row.get("projectId") == run["projectId"] and row.get("materialTypeCode") == "ndt_procedure"}
    for version in state.get("versions", []):
        if version.get("id") in selected and version.get("documentId") in ndt_documents:
            by_version.setdefault(version["id"], [])
    if not by_version:
        return None, []
    issues, documents, unresolved_targets = [], {"instruction": [], "procedure": []}, set()
    for version, candidates in sorted(by_version.items()):
        for parse in candidates:
            gap = review_coverage_gap(parse)
            if gap:
                issues.append({**gap, "documentVersionId": version, "code": "r39_ocr_page_coverage_incomplete"})
        value = _document(state, run, candidates[0]) if len(candidates) == 1 else None
        if value is None:
            # Missing revision data does not make a same-number alternative
            # disappear from candidate matching.
            for parse in candidates:
                identity = {key: _field(parse, key) for key in ("document_kind", "organization_name", "method", "procedure_no")}
                if all(identity.values()) and identity["document_kind"]["value"] == "工艺规程":
                    unresolved_targets.add(tuple(identity[key]["value"] for key in ("organization_name", "method", "procedure_no")))
            issues.append({"documentVersionId": version, "code": "r39_ocr_document_missing_or_ambiguous"})
            continue
        kind, document = value
        documents[kind].append(document)
    pairs, records, used = [], [], set()
    for instruction in documents["instruction"]:
        matches = [procedure for procedure in documents["procedure"] if all(
            instruction[2][key]["value"] == procedure[2][key]["value"] for key in ("organization_name", "method"))
            and instruction[2]["referenced_procedure_no"]["value"] == procedure[2]["procedure_no"]["value"]]
        target = tuple(instruction[2][key]["value"] for key in ("organization_name", "method", "referenced_procedure_no"))
        if len(matches) != 1 or target in unresolved_targets:
            issues.append({"documentVersionId": instruction[1], "code": "r39_ocr_reference_target_missing_or_ambiguous"})
            continue
        pair, source_records = _pair(run, instruction, matches[0])
        pairs.append(pair)
        records.extend(source_records)
        used.update((instruction[1], matches[0][1]))
    for procedure in documents["procedure"]:
        if procedure[1] not in used:
            issues.append({"documentVersionId": procedure[1], "code": "r39_ocr_procedure_not_linked"})
    if not pairs:
        return None, []
    if len(by_version) == 2 and len(pairs) == 1 and not issues:
        return pairs[0], records
    return {"projectId": run["projectId"], "fieldPairs": pairs,
            "selectedDocumentVersionIds": sorted(by_version), "selectionIssues": issues}, records
