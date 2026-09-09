"""R39 scoped source adapters; ambiguous single-event inputs remain unavailable."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.r39_application_facts import application_input
from libs.review_orchestrator.r39_approval_facts import build_approval_inputs
from libs.review_orchestrator.r39_content_inventory_facts import build_content_inputs
from libs.review_orchestrator.r39_pt_facts import pt_application_input
from libs.review_orchestrator.r39_reference_facts import reference_input
from libs.review_orchestrator.r39_source_validation import gate_r39_inputs
from libs.review_tools.r39_content import SCOPE_FIELDS as CONTENT_SCOPE_FIELDS

R39_TABLES = {
    "ndt_approval_cycle_inventory": "approvalCycleInventories", "ndt_approval_cycle_members": "approvalCycleMembers",
    "ndt_application_inventory": "applicationInventories", "ndt_application_members": "applicationMembers",
    "ndt_content_document_inventory": "contentDocumentInventories", "ndt_content_document_members": "contentDocumentMembers",
    "ndt_pt_context": "ptContexts", "ndt_pt_basis": "ptBases", "ndt_pt_process": "ptProcesses",
    "ndt_reference_inventory": "referenceInventories", "ndt_reference_members": "referenceMembers",
    "ndt_reference_context": "referenceContexts", "ndt_reference_basis": "referenceBases",
    "ndt_instruction_reference": "instructionReferences", "ndt_procedure_identity": "procedureIdentities",
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
    pt_input = pt_application_input(state, run, groups, _approval_record, _reviewed_document_valid)
    if pt_input is not None:
        facts["ptEmulsifierApplication"] = pt_input
    else:
        issues.append("r39_pt_application_missing_or_ambiguous")
    reference = reference_input(state, run, groups, _clean)
    if reference is not None:
        facts["procedureReference"] = reference
    else:
        issues.append("r39_reference_pair_missing_or_ambiguous")
    build_content_inputs(state, run, groups, facts, _approval_record, _content_input)
    first_use = application_input(run, groups, _clean)
    if first_use is not None:
        facts["firstUseValidation"] = first_use
    else:
        issues.append("r39_application_missing_or_ambiguous")
    build_approval_inputs(state, run, groups, facts, _approval_record, _reviewed_document_valid)
    return finish()
