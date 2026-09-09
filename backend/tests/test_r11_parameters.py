from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.design_facts import build_design_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def arguments():
    scope = {"projectId": "P", "objectType": "pipeline", "objectId": "L1", "planVersionId": "PLAN", "designVersionId": "DESIGN"}
    def ref(version):
        return [{"documentVersionId": version, "pageNo": 1, "quotedText": "Synthetic measured parameter"}]
    return {"projectId": "P", "scope": scope,
            "basis": {**scope, "applicable": True, "completeRequirements": True, "requiredFields": ["material", "length"], "evidenceRefs": ref("DESIGN")},
            "parameters": [{**scope, "side": side, "field": field, "value": value, "evidenceRefs": ref(version), **({"unit": "m"} if field == "length" else {})}
                           for side, version in (("plan", "PLAN"), ("design", "DESIGN")) for field, value in (("material", "20"), ("length", 12))]}


def call(body):
    return dispatch_runtime_tool({}, "evaluate_r11_project_parameters", body)


@pytest.mark.parametrize("case,expected", [("same", "passed"), ("different", "failed"), ("missing", "evidence_insufficient"),
    ("not_applicable", "not_applicable"), ("unit", "evidence_insufficient"), ("object", "evidence_insufficient"),
    ("duplicate", "evidence_insufficient"), ("wrong_original", "evidence_insufficient"), ("incomplete_requirements", "evidence_insufficient"), ("numeric_without_unit", "evidence_insufficient")])
def test_four_states_and_object_unit_source_boundaries(case, expected):
    body = arguments()
    if case == "different":
        body["parameters"][0]["value"] = "16Mn"
    elif case == "missing":
        body["parameters"].pop()
    elif case == "not_applicable":
        body["basis"]["applicable"] = False
    elif case == "unit":
        body["parameters"][1]["unit"] = "cm"
    elif case == "object":
        body["parameters"][0]["objectId"] = "L2"
    elif case == "duplicate":
        body["parameters"].append(deepcopy(body["parameters"][0]))
    elif case == "wrong_original":
        body["parameters"][0]["evidenceRefs"][0]["documentVersionId"] = "DESIGN"
    elif case == "numeric_without_unit":
        body["parameters"][1].pop("unit")
        body["parameters"][3].pop("unit")
    elif case == "incomplete_requirements":
        body["basis"]["completeRequirements"] = False
    original = deepcopy(body)
    assert call(body)["result"] == expected
    assert body == original


def fixture():
    body = arguments()
    def table(name, rows):
        return {"tableId": name, "businessSchema": name, "normalizedRows": deepcopy(rows), "pageNo": 1,
                "contentMarkdown": "Synthetic measured parameter", "structureConfidence": .95}
    state = {"versions": [{"id": v, "documentId": v+"DOC", "tenantId": "T"} for v in ("PLAN", "DESIGN")],
             "documents": [{"id": v+"DOC", "projectId": "P", "tenantId": "T"} for v in ("PLAN", "DESIGN")],
             "ocr_parse_results": [
                 {"documentVersionId": "PLAN", "tenantId": "T", "tables": [
                     table("construction_comparison_context", [body["scope"]]),
                     table("construction_comparison_parameters", body["parameters"][:2])]},
                 {"documentVersionId": "DESIGN", "tenantId": "T", "tables": [
                     table("construction_comparison_basis", [body["basis"]]),
                     table("construction_comparison_inventory", [{"projectId": "P", "complete": True}]),
                     table("construction_comparison_members", [body["scope"]]),
                     table("construction_comparison_parameters", body["parameters"][2:])]}]}
    run = {"projectId": "P", "tenantId": "T", "nodeId": 11, "inputDocumentVersionIds": ["PLAN", "DESIGN"]}
    return state, run


@pytest.mark.parametrize("case,expected", [("same", "passed"), ("different", "failed"), ("unselected", "evidence_insufficient"),
    ("low_confidence", "evidence_insufficient"), ("other_object", "evidence_insufficient")])
def test_actual_r11_builder_and_atomic_binding(case, expected):
    state, run = fixture()
    table = state["ocr_parse_results"][0]["tables"][1]
    if case == "different":
        table["normalizedRows"][0]["value"] = "16Mn"
    elif case == "unselected":
        run["inputDocumentVersionIds"].remove("DESIGN")
    elif case == "low_confidence":
        table["structureConfidence"] = .4
    elif case == "other_object":
        table["normalizedRows"][0]["objectId"] = "L2"
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    original = deepcopy(state)
    facts = build_design_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R11", available_tools={item["name"] for item in runtime_tool_catalog()})
    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=facts["judgment"]["claimedFacts"], evidence_refs=facts["judgment"]["evidenceRefs"],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}))
    atom = next(item for item in output["atomicResults"] if item["atomicCheckId"] == "AC-R11-02")
    assert atom["result"] == expected, atom
    assert state == original
    assert output["result"] != "passed", "signature and technical requirements remain unverified"


@pytest.mark.parametrize("confidence", [True, float("nan"), float("inf"), "0.9"])
def test_malformed_confidence_never_reaches_numeric_grounding(confidence):
    state, run = fixture()
    state["ocr_parse_results"][0]["tables"][1]["structureConfidence"] = confidence
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = build_design_business_facts(state, run)
    assert "projectParameters" not in facts["r11"]
    assert "r11_source_confidence_invalid" in facts["r11"]["sourceIssues"]
