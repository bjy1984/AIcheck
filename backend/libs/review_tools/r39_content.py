"""NB/T 47013.1-2015 document content coverage, not technical compliance."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = ("projectId", "organizationId", "documentId", "documentVersionId", "documentKind", "method")
# Each leaf is checked separately; an equipment name cannot satisfy calibration details.
PROCEDURE_CONTENT = {
    "a": ("procedureVersion",), "b": ("applicableScope",), "c": ("referenceDocuments",),
    "d": ("personnelQualificationRequirements",),
    "e": ("equipmentAndMaterials", "calibrationOrVerificationRequirements", "operationalCheckItems", "operationalCheckIntervals", "operationalCheckPerformance"),
    "f": ("relevantFactors", "relevantFactorRanges"),
    "g": ("objectSpecificTechniqueSelection", "instructionRequirements"),
    "h": ("inspectionTiming", "surfacePreparation", "inspectionMarking", "postInspectionTreatment"),
    "i": ("resultAssessment", "qualityGrading"), "j": ("recordRequirements",), "k": ("reportRequirements",),
    "l": ("author", "authorLevel", "reviewer", "reviewerLevel", "approver"), "m": ("compilationDate",),
}
INSTRUCTION_CONTENT = {
    "a": ("instructionNumber",), "b": ("referencedProcedure", "referencedProcedureVersion"),
    "c": ("executionStandard", "inspectionTiming", "inspectionRatio", "acceptanceLevel", "surfacePreparation"),
    "d": ("equipmentCategory", "objectName", "objectNumber", "objectDimensions", "objectMaterial", "heatTreatmentState", "inspectionLocationAndRange"),
    "e": ("equipmentAndMaterialsNames", "equipmentAndMaterialsModels", "performanceCheckItems", "performanceCheckTiming", "performanceCheckIndicators"),
    "f": ("processParameters",), "g": ("inspectionSteps",), "h": ("inspectionDiagram",), "i": ("dataRecordingRules",),
    "j": ("author", "authorLevel", "reviewer", "reviewerLevel"), "k": ("compilationDate",),
}


def content_requirements(kind):
    clause, groups = ("7.2.2", PROCEDURE_CONTENT) if kind == "procedure" else ("7.2.3", INSTRUCTION_CONTENT)
    return {name: clause + "." + letter for letter, names in groups.items() for name in names}


def evaluate_r39_document_content(arguments: dict[str, Any]) -> dict[str, Any]:
    if "inventory" in arguments or "documents" in arguments:
        from libs.review_tools.r39_document_inventory import evaluate_document_inventory
        return evaluate_document_inventory(arguments, SCOPE_FIELDS, evaluate_r39_document_content)
    rows = []

    def add(code, status, refs=None, clause=None):
        rows.append({"code": code, "result": status, "clause": clause, "evidenceRefs": deepcopy(refs or [])})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_r39_document_content", status,
                        facts={"contentChecks": rows, "technicalCompliance": "not_evaluated", "wholeRuleAcceptance": "not_evaluated", "evidenceVerified": False},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r39-nbt47013-common-document-content-v2")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope.get("documentKind") not in {"procedure", "instruction"} or arguments.get("projectId") != scope["projectId"]):
        add("r39_content_scope_missing", "evidence_insufficient")
        return finish()

    def matches(record):
        return isinstance(record, dict) and all(record.get(key) == scope[key] for key in SCOPE_FIELDS)

    requirements = content_requirements(scope["documentKind"])
    base_clause = "7.2.2" if scope["documentKind"] == "procedure" else "7.2.3"
    basis = arguments.get("basis")
    if (not matches(basis) or basis.get("standard") != "NB/T 47013.1-2015" or basis.get("clause") != base_clause
            or type(basis.get("applicable")) is not bool or not _refs(basis)):
        add("r39_content_basis_missing", "evidence_insufficient")
        return finish()
    supplied = arguments.get("contentInventory")
    if "contentInventory" in arguments:
        if not matches(supplied) or not isinstance(supplied.get("fields"), list):
            add("r39_supplied_content_scope_conflict", "evidence_insufficient", _refs(basis))
            return finish()
        seen = set()
        for field in supplied["fields"]:
            if (not matches(field) or not isinstance(field.get("fieldId"), str)
                    or field["fieldId"] not in requirements or field["fieldId"] in seen):
                add("r39_supplied_content_field_conflict", "evidence_insufficient", _refs(basis))
                return finish()
            seen.add(field["fieldId"])
    if not basis["applicable"]:
        add("r39_content_clause_not_applicable", "not_applicable", _refs(basis), base_clause)
        return finish()
    inventory = arguments.get("contentInventory")
    if not matches(inventory) or not _refs(inventory) or not isinstance(inventory.get("fields"), list):
        add("r39_content_inventory_missing", "evidence_insufficient", _refs(basis))
        return finish()
    fields = {}
    for field in inventory["fields"]:
        if (not matches(field) or not isinstance(field.get("fieldId"), str)
                or field["fieldId"] not in requirements or field["fieldId"] in fields):
            add("r39_content_field_unknown_duplicate_or_mismatched", "evidence_insufficient", _refs(inventory))
            return finish()
        fields[field["fieldId"]] = field
    for name, clause in requirements.items():
        field = fields.get(name, {})
        refs = [*_refs(basis), *_refs(inventory)]
        field_refs = _refs(field)
        # Content facts must cite this document version, never a template or another revision.
        if not field_refs or any(ref["documentVersionId"] != scope["documentVersionId"] for ref in field_refs):
            add(name, "evidence_insufficient", refs, clause)
            continue
        refs.extend(field_refs)
        presence = field.get("presence")
        if presence == "present" and _text(field.get("value")):
            status = "passed"
        elif presence == "absent" and inventory.get("completeDocumentReview") is True and field.get("value") in (None, ""):
            # This is a sourced, explicit absence finding after a complete document review;
            # an omitted OCR field alone is not evidence that the document lacks the content.
            status = "failed"
        else:
            status = "evidence_insufficient"
        add(name, status, refs, clause)
    return finish()
