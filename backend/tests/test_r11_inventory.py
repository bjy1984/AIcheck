from copy import deepcopy

import pytest
from test_r11_parameters import arguments, call


def batch():
    first = arguments()
    second = deepcopy(first)
    second["scope"]["objectId"] = "L2"
    second["basis"]["objectId"] = "L2"
    for row in second["parameters"]:
        row["objectId"] = "L2"
    return {"projectId": "P", "inventory": {"projectId": "P", "complete": True,
            "evidenceRefs": deepcopy(first["basis"]["evidenceRefs"]),
            "members": [{**item["scope"], "evidenceRefs": deepcopy(item["basis"]["evidenceRefs"])} for item in (first, second)]},
            "objectComparisons": [first, second]}


@pytest.mark.parametrize("case,expected", [("all", "passed"), ("missing_object", "evidence_insufficient"),
    ("different", "failed"), ("duplicate", "evidence_insufficient"), ("partial_inventory", "evidence_insufficient"),
    ("unknown_object", "evidence_insufficient"), ("no_member_source", "evidence_insufficient"),
    ("all_na", "not_applicable")])
def test_inventory_reconciles_every_object(case, expected):
    body = batch()
    if case == "missing_object":
        body["objectComparisons"].pop()
    elif case == "different":
        body["objectComparisons"][1]["parameters"][0]["value"] = "16Mn"
    elif case == "duplicate":
        body["objectComparisons"].append(deepcopy(body["objectComparisons"][0]))
    elif case == "partial_inventory":
        body["inventory"]["complete"] = False
    elif case == "unknown_object":
        body["objectComparisons"][1]["scope"]["objectId"] = "L3"
    elif case == "no_member_source":
        body["inventory"]["members"][1]["evidenceRefs"] = []
    elif case == "all_na":
        for item in body["objectComparisons"]:
            item["basis"]["applicable"] = False
    original = deepcopy(body)
    assert call(body)["result"] == expected
    assert body == original


@pytest.mark.parametrize("case,expected", [("two", "passed"), ("missing", "evidence_insufficient"), ("no_inventory", "evidence_insufficient")])
def test_multi_object_frozen_source_builder(case, expected):
    from test_r11_parameters import fixture

    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator.design_facts import build_design_business_facts
    state, review = fixture()
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            rows = table["normalizedRows"]
            for row in list(rows):
                if row.get("objectId") == "L1":
                    second = deepcopy(row)
                    second["objectId"] = "L2"
                    rows.append(second)
            if case == "missing" and table["businessSchema"] == "construction_comparison_parameters":
                table["normalizedRows"] = [row for row in rows if row["objectId"] != "L2"]
            if case == "no_inventory" and table["businessSchema"] == "construction_comparison_inventory":
                table["normalizedRows"] = []
    review["documentScopeSnapshot"] = freeze_document_scope(review, state)
    facts = build_design_business_facts(state, review)
    assert call(facts["r11"].get("projectParameters", {}))["result"] == expected


def test_nested_comparison_envelope_is_not_recursively_executed():
    body = batch()
    body["objectComparisons"][0]["objectComparisons"] = []
    assert call(body)["result"] == "evidence_insufficient"
