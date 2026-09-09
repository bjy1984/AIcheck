from copy import deepcopy

import pytest
from test_r39_approval import arguments as approval_arguments
from test_r39_tools import arguments as first_use_arguments

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.r39_facts import build_r39_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.executor import build_tool_arguments
from libs.review_tools.r39_approval import SCOPE_FIELDS


def fixture():
    approval = approval_arguments()
    first = first_use_arguments()
    scope = approval["scope"]

    def target(row):
        row = deepcopy(row)
        row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        return row

    def table(schema, rows):
        return {"tableId": schema, "businessSchema": schema, "pageNo": 2,
                "structureConfidence": .95, "contentMarkdown": "Synthetic recorded source table",
                "normalizedRows": deepcopy(rows)}

    qms = [table("ndt_first_use_basis", [first["basis"]]),
           table("ndt_approval_requirements", [target(approval["requirements"])]),
           table("ndt_approval_steps", [target({**scope, **step}) for step in approval["requirements"]["steps"]])]
    document = [table("ndt_instruction_application", [first["application"]]),
                table("ndt_first_use_validation", [first["validation"]]),
                table("ndt_approval_context", [target(scope)]),
                table("ndt_signature_inventory", [target(approval["signatureInventory"])]),
                table("ndt_approval_signatures", [target(row) for row in approval["signatureInventory"]["signatures"]])]
    state = {"documents": [{"id": key, "projectId": "P1", "tenantId": "T1"} for key in ("DOC1", "QMS1")],
             "versions": [{"id": key, "documentId": doc, "tenantId": "T1"} for key, doc in (("DV1", "DOC1"), ("QMSV1", "QMS1"))],
             "ocr_parse_results": [{"documentVersionId": key, "tenantId": "T1", "tables": tables}
                                   for key, tables in (("QMSV1", qms), ("DV1", document))]}
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 39, "inputDocumentVersionIds": ["QMSV1", "DV1"]}
    return state, run


def evaluate(state, run, name):
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = NDT_FACT_BUILDERS[39](state, run)
    args = build_tool_arguments(name, {}, facts=facts, explicit={}, document_version_ids=run["inputDocumentVersionIds"],
                                evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"])
    return facts, dispatch_runtime_tool(state, name, args, context={"reviewRun": run})


@pytest.mark.parametrize("name", ["evaluate_r39_first_use_validation", "evaluate_r39_approval_chain"])
def test_frozen_source_to_executor_and_runtime(name):
    state, run = fixture()
    before = deepcopy(state)
    facts, output = evaluate(state, run, name)
    assert output["result"] == "passed", output
    assert state == before
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert facts["judgment"]["evidenceRefs"]
    assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"QMSV1", "DV1"}
    assert all(ref["quotedText"] == "Synthetic recorded source table" for ref in output["evidenceRefs"])
    if "approval" in name:
        req = facts["r39"]["approvalChain"]["requirements"]
        assert req["documentVersionId"] == "DV1"
        assert req["evidenceRefs"][0]["documentVersionId"] == "QMSV1"


@pytest.mark.parametrize("case", ["unselected", "tenant", "project", "duplicate_context", "duplicate_header", "missing_steps", "missing_signatures", "target_version", "unknown_condition", "missing_quote", "wrong_cycle"])
def test_approval_incomplete_or_conflicting_sources_do_not_pass(case):
    state, run = fixture()
    qms = state["ocr_parse_results"][0]["tables"]
    document = state["ocr_parse_results"][1]["tables"]
    if case == "unselected":
        run["inputDocumentVersionIds"] = ["DV1"]
    elif case == "tenant":
        state["ocr_parse_results"][0]["tenantId"] = "OTHER"
    elif case == "project":
        state["documents"][0]["projectId"] = "OTHER"
    elif case == "duplicate_context":
        document[2]["normalizedRows"] *= 2
    elif case == "duplicate_header":
        qms[1]["normalizedRows"] *= 2
    elif case == "missing_steps":
        qms[2]["normalizedRows"] = []
    elif case == "missing_signatures":
        document[4]["normalizedRows"] = []
    elif case == "target_version":
        document[2]["normalizedRows"][0]["reviewedDocumentVersionId"] = "UNSELECTED"
    elif case == "unknown_condition":
        qms[2]["normalizedRows"][0]["requiredLevel"] = "III"
    elif case == "missing_quote":
        qms[2].pop("contentMarkdown")
    elif case == "wrong_cycle":
        document[4]["normalizedRows"][0]["approvalCycleId"] = "OTHER"
    assert evaluate(state, run, "evaluate_r39_approval_chain")[1]["result"] == "evidence_insufficient"


@pytest.mark.parametrize("field", SCOPE_FIELDS)
def test_mismatched_step_scope_not_discarded(field):
    state, run = fixture()
    key = "reviewedDocumentVersionId" if field == "documentVersionId" else field
    state["ocr_parse_results"][0]["tables"][2]["normalizedRows"][0][key] = "OTHER"
    facts, output = evaluate(state, run, "evaluate_r39_approval_chain")
    assert output["result"] == "evidence_insufficient"
    assert "r39_approval_source_scope_conflict" in facts["r39"]["sourceIssues"]


def test_first_use_conflict_cannot_hide_behind_not_applicable():
    state, run = fixture()
    document = state["ocr_parse_results"][1]["tables"]
    document[0]["normalizedRows"][0]["firstUse"] = False
    document[1]["normalizedRows"] *= 2
    assert evaluate(state, run, "evaluate_r39_first_use_validation")[1]["result"] == "evidence_insufficient"


def test_nested_forged_evidence_is_replaced_by_separate_source_rows():
    state, run = fixture()
    qms = state["ocr_parse_results"][0]["tables"]
    qms[1]["normalizedRows"][0]["steps"][0]["role"] = "FORGED"
    qms[2]["normalizedRows"][0]["evidenceRefs"] = [{"documentVersionId": "OTHER", "pageNo": 999}]
    facts, output = evaluate(state, run, "evaluate_r39_approval_chain")
    assert output["result"] == "passed"
    assert facts["r39"]["approvalChain"]["requirements"]["steps"][0]["role"] == "author"
    assert all(ref["documentVersionId"] in run["inputDocumentVersionIds"] for ref in output["evidenceRefs"])
    state["ocr_parse_results"][0]["tables"][2]["normalizedRows"][0]["role"] = "CHANGED"
    with pytest.raises(ValueError, match="sources_changed"):
        build_r39_business_facts(state, run)
