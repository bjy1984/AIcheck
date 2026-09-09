import pytest
from test_r39_content_facts import fixture
from test_r39_facts import evaluate
from test_r39_tools import arguments, run

from libs.review_tools.r39_tools import IDENTITY_FIELDS

INPUT_TO_TOOL = {"firstUseValidation": "evaluate_r39_first_use_validation", "approvalChain": "evaluate_r39_approval_chain", "documentContent": "evaluate_r39_document_content"}
SCHEMAS = {"firstUseValidation": "ndt_first_use_validation", "approvalChain": "ndt_approval_steps", "documentContent": "ndt_content_fields"}


def source_table(state, schema):
    return next(table for parse in state["ocr_parse_results"] for table in parse["tables"] if table["businessSchema"] == schema)


@pytest.mark.parametrize("input_name", INPUT_TO_TOOL)
@pytest.mark.parametrize("confidence", [None, .74, 0, -1, 1.01, float("nan"), float("inf"), True, ".95", 10**400])
def test_unreliable_or_malformed_sources_block_tool_inputs(input_name, confidence):
    state, review_run = fixture()
    source_table(state, SCHEMAS[input_name])["normalizedRows"][0]["confidence"] = confidence
    facts, output = evaluate(state, review_run, INPUT_TO_TOOL[input_name])
    assert output["result"] == "evidence_insufficient"
    assert input_name not in facts["r39"]
    assert facts["r39"]["sourceValidation"][input_name]["result"] == "evidence_insufficient"
    assert facts["r39"]["sourceRecords"]


@pytest.mark.parametrize("input_name", INPUT_TO_TOOL)
@pytest.mark.parametrize("conflict", [True, "false", 0, None])
def test_conflicts_and_malformed_conflict_declarations_block(input_name, conflict):
    state, review_run = fixture()
    source_table(state, SCHEMAS[input_name])["normalizedRows"][0]["conflicted"] = conflict
    assert evaluate(state, review_run, INPUT_TO_TOOL[input_name])[1]["result"] == "evidence_insufficient"


@pytest.mark.parametrize("input_name", INPUT_TO_TOOL)
def test_confidence_boundary_and_explicit_false_conflict_remain_usable(input_name):
    state, review_run = fixture()
    source_table(state, SCHEMAS[input_name])["normalizedRows"][0].update(confidence=.75, conflicted=False)
    assert evaluate(state, review_run, INPUT_TO_TOOL[input_name])[1]["result"] == "passed"


def test_unrelated_content_problem_does_not_block_other_inputs():
    state, review_run = fixture()
    source_table(state, "ndt_content_fields")["normalizedRows"][0]["conflicted"] = True
    facts, output = evaluate(state, review_run, "evaluate_r39_approval_chain")
    assert output["result"] == "passed"
    assert facts["r39"]["sourceValidation"]["documentContent"]["result"] == "evidence_insufficient"
    assert evaluate(state, review_run, "evaluate_r39_first_use_validation")[1]["result"] == "passed"


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_single_supplied_cross_scope_record_cannot_hide_in_not_applicable(field):
    body = arguments()
    body["application"]["firstUse"] = False
    body["validation"][field] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"


def test_not_first_use_does_not_require_a_validation_record():
    body = arguments()
    body["application"]["firstUse"] = False
    body.pop("validation")
    assert run(body)["result"] == "not_applicable"


def test_non_first_use_low_confidence_source_is_not_accepted():
    state, review_run = fixture()
    source_table(state, "ndt_instruction_application")["normalizedRows"][0].update(firstUse=False, confidence=.2)
    assert evaluate(state, review_run, "evaluate_r39_first_use_validation")[1]["result"] == "evidence_insufficient"


@pytest.mark.parametrize("inventory_change", ["scope", "field_scope", "duplicate", "unknown"])
def test_non_applicable_content_does_not_hide_supplied_scope_conflicts(inventory_change):
    from test_r39_content import arguments as content_arguments

    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool

    body = content_arguments()
    body["basis"]["applicable"] = False
    inventory = body["contentInventory"]
    if inventory_change == "scope":
        inventory["documentVersionId"] = "OTHER"
    elif inventory_change == "field_scope":
        inventory["fields"][0]["documentVersionId"] = "OTHER"
    elif inventory_change == "duplicate":
        inventory["fields"].append(dict(inventory["fields"][0]))
    else:
        inventory["fields"][0]["fieldId"] = "OTHER"
    assert dispatch_runtime_tool({}, "evaluate_r39_document_content", body)["result"] == "evidence_insufficient"


def test_first_use_requires_matching_top_level_project_and_valid_supplied_reference():
    body = arguments()
    body["projectId"] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"
    body["projectId"] = "P1"
    body["application"]["firstUse"] = False
    body["validation"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"
