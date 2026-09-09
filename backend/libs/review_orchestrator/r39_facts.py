"""R39 scoped source adapters; ambiguous single-event inputs remain unavailable."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.r39_source_validation import gate_r39_inputs
from libs.review_tools.r39_approval import SCOPE_FIELDS
from libs.review_tools.r39_content import SCOPE_FIELDS as CONTENT_SCOPE_FIELDS
from libs.review_tools.r39_tools import IDENTITY_FIELDS

R39_TABLES = {
    "ndt_content_context": "contentContexts", "ndt_content_basis": "contentBases",
    "ndt_content_inventory": "contentInventories", "ndt_content_fields": "contentFields",
    "ndt_instruction_application": "applications", "ndt_first_use_basis": "bases",
    "ndt_first_use_validation": "validations", "ndt_approval_context": "approvalContexts",
    "ndt_approval_requirements": "requirements", "ndt_approval_steps": "steps",
    "ndt_signature_inventory": "signatureInventories", "ndt_approval_signatures": "signatures",
}
PROVENANCE = {"evidence", "documentVersionId", "confidence", "conflicted"}


def _clean(row):
    return {key: deepcopy(value) for key, value in row.items() if key not in PROVENANCE}


def _approval_record(row):
    record = _clean(row)
    # The reviewed document and the document containing this fact are different.
    record["documentVersionId"] = record.pop("reviewedDocumentVersionId", None)
    return record



def _reviewed_document_valid(state, run, scope):
    versions = [version for version in state.get("versions", [])
                if version.get("id") == scope["documentVersionId"] and version.get("documentId") == scope["documentId"]
                and version.get("tenantId") == run["tenantId"]]
    documents = [document for document in state.get("documents", []) if document.get("id") == scope["documentId"]
                 and document.get("projectId") == run["projectId"] and document.get("tenantId") == run["tenantId"]]
    return (scope["projectId"] == run["projectId"] and scope["documentVersionId"] in run.get("inputDocumentVersionIds", [])
            and len(versions) == 1 and len(documents) == 1)


def _content_input(state, run, groups, facts):
    issues = facts["sourceIssues"]
    if any(len(groups[key]) != 1 for key in ("contentContexts", "contentBases", "contentInventories")):
        issues.append("r39_content_header_missing_or_ambiguous")
        return
    context = _approval_record(groups["contentContexts"][0])
    scope = {key: context.get(key) for key in CONTENT_SCOPE_FIELDS}
    if not _reviewed_document_valid(state, run, scope):
        issues.append("r39_content_document_not_in_selected_project_scope")
        return
    records = {key: [_approval_record(row) for row in groups[key]]
               for key in ("contentBases", "contentInventories", "contentFields")}
    if any(any(row.get(key) != scope[key] for key in CONTENT_SCOPE_FIELDS) for rows in records.values() for row in rows):
        issues.append("r39_content_source_scope_conflict")
        return
    inventory = records["contentInventories"][0]
    inventory["fields"] = records["contentFields"]
    facts["documentContent"] = {"projectId": run["projectId"], "scope": scope,
                                "basis": records["contentBases"][0], "contentInventory": inventory}


def build_r39_business_facts(state: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    groups = read_ndt_tables(state, run, R39_TABLES, node_id=39)
    judgment = build_material_judgment([(f"r39-{kind}", rows, ("instructionId", "projectId")) for kind, rows in groups.items()])
    facts: dict[str, Any] = {"sourceIssues": [], "sourceRecords": deepcopy(groups)}
    def finish():
        gate_r39_inputs(groups, facts)
        return {"r39": facts, **judgment}

    issues = facts["sourceIssues"]
    _content_input(state, run, groups, facts)
    applications = groups["applications"]
    if len(applications) == 1 and applications[0].get("projectId") == run["projectId"]:
        application = _clean(applications[0])
        first_use = {"projectId": run["projectId"], "scope": {key: application.get(key) for key in IDENTITY_FIELDS}, "application": application}
        for group, key in (("bases", "basis"), ("validations", "validation")):
            if len(groups[group]) == 1:
                first_use[key] = _clean(groups[group][0])
            elif len(groups[group]) > 1:
                issues.append("r39_" + group + "_ambiguous")
        # Do not let non-first-use short-circuit hide conflicting supplied records.
        if not any(len(groups[key]) > 1 for key in ("bases", "validations")):
            facts["firstUseValidation"] = first_use
    else:
        issues.append("r39_application_missing_or_ambiguous")
    contexts = groups["approvalContexts"]
    if len(contexts) != 1:
        issues.append("r39_approval_context_missing_or_ambiguous")
        return finish()
    context = _approval_record(contexts[0])
    scope = {key: context.get(key) for key in SCOPE_FIELDS}
    if not _reviewed_document_valid(state, run, scope):
        issues.append("r39_reviewed_document_not_in_selected_project_scope")
        return finish()
    records = {key: [_approval_record(row) for row in groups[key]]
               for key in ("requirements", "steps", "signatureInventories", "signatures")}
    if any(len(records[key]) != 1 for key in ("requirements", "signatureInventories")):
        issues.append("r39_approval_header_missing_or_ambiguous")
        return finish()
    if any(any(row.get(key) != scope[key] for key in SCOPE_FIELDS) for rows in records.values() for row in rows):
        issues.append("r39_approval_source_scope_conflict")
        return finish()
    requirements = records["requirements"][0]
    inventory = records["signatureInventories"][0]
    # Embedded child records cannot manufacture evidence; independent rows are required.
    requirements["steps"] = [{key: value for key, value in row.items() if key not in SCOPE_FIELDS}
                             for row in records["steps"]]
    inventory["signatures"] = records["signatures"]
    facts["approvalChain"] = {"projectId": run["projectId"], "scope": scope,
                              "requirements": requirements, "signatureInventory": inventory}
    return finish()
