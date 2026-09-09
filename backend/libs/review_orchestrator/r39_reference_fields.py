"""Read one explicit instruction/procedure pair from frozen, grounded OCR fields."""
from copy import deepcopy

from libs.review_input_data import selected_parse_results
from libs.review_tools.r39_tools import _text
from libs.review_workstations import digest

FIELDS = ("procedure_no", "procedure_revision", "organization_name", "document_kind", "method")


def _field(parse, code):
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
    ref["id"] = "R39-FIELD-" + digest({"fieldCode": code, **ref})[:24]
    ref["evidenceRefId"] = ref["id"]
    return {"value": value, "documentVersionId": parse["documentVersionId"], "evidence": ref, "evidenceRefs": [ref]}


def reference_from_fields(state, run):
    parses = [row for row in selected_parse_results(state, {}, context={"reviewRun": run})
              if row.get("profileId") == "ndt_procedure_v1"]
    # A larger or partially parsed set needs an explicit inventory; no first-match fallback.
    if len(parses) != 2:
        return None, []
    documents, records = {}, []
    for parse in parses:
        if parse.get("tenantId") != run["tenantId"]:
            return None, []
        version = [row for row in state.get("versions", []) if row.get("id") == parse.get("documentVersionId")
                   and row.get("tenantId") == run["tenantId"]]
        if len(version) != 1:
            return None, []
        doc = [row for row in state.get("documents", []) if row.get("id") == version[0].get("documentId")
               and row.get("projectId") == run["projectId"] and row.get("tenantId") == run["tenantId"]]
        if len(doc) != 1:
            return None, []
        fields = {code: _field(parse, code) for code in FIELDS}
        if any(value is None for value in fields.values()):
            return None, []
        kind = {"工艺规程": "procedure", "操作指导书": "instruction"}.get(fields["document_kind"]["value"])
        if kind is None or kind in documents:
            return None, []
        if kind == "instruction":
            fields.update({code: _field(parse, code) for code in ("referenced_procedure_no", "referenced_procedure_revision")})
        if any(value is None for value in fields.values()):
            return None, []
        documents[kind] = (doc[0]["id"], version[0]["id"], fields)
        records.extend(fields.values())
    instruction, procedure = documents["instruction"], documents["procedure"]
    if any(instruction[2][key]["value"] != procedure[2][key]["value"] for key in ("organization_name", "method")):
        return None, []
    # Co-selection alone does not prove an intended reference relationship.
    # Match its explicit number before comparing the revision; never pick by revision.
    if instruction[2]["referenced_procedure_no"]["value"] != procedure[2]["procedure_no"]["value"]:
        return None, []
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
