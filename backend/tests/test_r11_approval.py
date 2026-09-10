from copy import deepcopy

import pytest
from test_r11_parameters import fixture

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.design_facts import build_design_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def body():
    def refs(version):
        return [{"documentVersionId": version, "pageNo": 1, "quotedText": "Sourced approval record"}]
    scope = {"projectId": "P", "planVersionId": "PLAN", "ownerOrganizationId": "OWNER", "approvalCycleId": "C1"}
    return {"profile": "construction_plan_approval", "projectId": "P",
        "scope": {**scope, "completePlanSet": True, "planVersionIds": ["PLAN"], "evidenceRefs": refs("PLAN")},
        "signatures": [{**scope, "role": role, "signerName": name, "signatureStatus": "present", "evidenceRefs": refs("PLAN")}
                       for role, name in [("编制", "张一"), ("审核", "李二"), ("审批", "王三")]],
        "ownerApproval": {**scope, "decision": "approved", "documentVersionId": "DESIGN", "approvedAt": "2026-09-01",
                          "evidenceRefs": [{"documentVersionId": "DESIGN", "pageNo": 1, "quotedText": "批复日期：2026-09-01"}]},
        "planUsage": {**scope, "documentVersionId": "PLAN", "usageStatus": "started", "startedAt": "2026-09-02",
                      "evidenceRefs": [{"documentVersionId": "PLAN", "pageNo": 1, "quotedText": "采用日期：2026-09-02"}]}}


@pytest.mark.parametrize("case,expected", [("complete", "passed"), ("missing_role", "evidence_insufficient"),
    ("duplicate_role", "evidence_insufficient"), ("absent", "failed"), ("no_name", "evidence_insufficient"),
    ("other_cycle", "evidence_insufficient"), ("other_version", "evidence_insufficient"),
    ("owner_pending", "evidence_insufficient"), ("owner_rejected", "failed"), ("owner_wrong_identity", "evidence_insufficient"),
    ("no_source", "evidence_insufficient"), ("multiple_plans", "evidence_insufficient"), ("page_gap", "evidence_insufficient")])
def test_documented_approval_does_not_infer_missing_or_valid_signatures(case, expected):
    args = body()
    if case == "missing_role": args["signatures"].pop()
    if case == "duplicate_role": args["signatures"].append(deepcopy(args["signatures"][0]))
    if case == "absent": args["signatures"][0]["signatureStatus"] = "absent"
    if case == "no_name": args["signatures"][0]["signerName"] = ""
    if case == "other_cycle": args["signatures"][0]["approvalCycleId"] = "C2"
    if case == "other_version": args["signatures"][0]["evidenceRefs"][0]["documentVersionId"] = "OLD"
    if case == "owner_pending": args["ownerApproval"]["decision"] = "pending"
    if case == "owner_rejected": args["ownerApproval"]["decision"] = "rejected"
    if case == "owner_wrong_identity": args["ownerApproval"]["ownerOrganizationId"] = "OTHER"
    if case == "no_source": args["scope"]["evidenceRefs"] = []
    if case == "multiple_plans": args["scope"]["planVersionIds"].append("OTHER")
    if case == "page_gap": args["selectionIssues"] = [{"code": "r11_selected_pages_incomplete"}]
    before = deepcopy(args)
    output = dispatch_runtime_tool({}, "evaluate_construction_plan", args)
    assert output["result"] == expected
    assert output["facts"]["evidenceVerified"] is False
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert args == before


@pytest.mark.parametrize("case,expected", [("complete", "passed"), ("low_confidence", "evidence_insufficient"),
                                          ("rejected", "failed"), ("wrong_cycle", "evidence_insufficient")])
def test_frozen_source_to_real_r11_atomic_plan(case, expected):
    state, run = fixture()
    args = body()
    if case == "rejected": args["ownerApproval"]["decision"] = "rejected"
    if case == "wrong_cycle": args["signatures"][0]["approvalCycleId"] = "OLD"
    for schema, values, parse in [("construction_approval_context", [args["scope"]], state["ocr_parse_results"][0]),
        ("construction_approval_signatures", args["signatures"], state["ocr_parse_results"][0]),
        ("construction_owner_approval", [args["ownerApproval"]], state["ocr_parse_results"][1])]:
        table = deepcopy(parse["tables"][0])
        table.update(tableId=schema, businessSchema=schema, normalizedRows=values)
        if case == "low_confidence": table["structureConfidence"] = .4
        parse["tables"].append(table)
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    before = deepcopy(state)
    facts = build_design_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R11",
                                  available_tools={row["name"] for row in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, arguments: dispatch_runtime_tool(state, name, arguments, context={"reviewRun": run}))
    atomic = next(row for row in output["atomicResults"] if row["atomicCheckId"] == "AC-R11-01")
    # The documented tool may pass, but the atomic capability gap must remain visible.
    assert atomic["result"] == ("evidence_insufficient" if expected == "passed" else expected)
    assert output["result"] != "passed"
    assert state == before


def test_approval_profile_does_not_accept_generic_presence_checks():
    output = dispatch_runtime_tool({}, "evaluate_construction_plan", {
        "profile": "construction_plan_approval", "facts": {"document": {"id": "D"}},
        "requiredFields": ["document.id"], "ruleChecks": [{"operator": "present", "actual": "D"}]})
    assert output["result"] == "evidence_insufficient"


def test_missing_owner_reply_keeps_explicit_signature_absence():
    args = body()
    args["ownerApproval"] = None
    args["signatures"][0]["signatureStatus"] = "absent"
    output = dispatch_runtime_tool({}, "evaluate_construction_plan", args)
    assert output["result"] == "failed"
    assert any(row["result"] == "evidence_insufficient" for row in output["facts"]["approvalChecks"])
