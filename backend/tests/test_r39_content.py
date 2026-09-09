from copy import deepcopy

import pytest

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r39_content import SCOPE_FIELDS, content_requirements


def arguments(kind="instruction"):
    scope = dict(zip(SCOPE_FIELDS, ("P1", "ORG1", "DOC1", "DV1", kind, "UT"), strict=True))
    refs = [{"documentVersionId": "DV1", "pageNo": 2, "quotedText": "Synthetic content excerpt"}]
    fields = [{**scope, "fieldId": name, "presence": "present", "value": "Synthetic explicit content", "evidenceRefs": deepcopy(refs)}
              for name in content_requirements(kind)]
    return {"projectId": "P1", "scope": scope,
            "basis": {**scope, "standard": "NB/T 47013.1-2015", "clause": "7.2.2" if kind == "procedure" else "7.2.3",
                      "applicable": True, "evidenceRefs": [{**refs[0], "documentVersionId": "QMSV1"}]},
            "contentInventory": {**scope, "completeDocumentReview": True, "fields": fields, "evidenceRefs": refs}}


def run(body):
    return dispatch_runtime_tool({}, "evaluate_r39_document_content", body)


@pytest.mark.parametrize("kind", ["procedure", "instruction"])
def test_four_states_distinguish_missing_ocr_from_sourced_absence(kind):
    body = arguments(kind)
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed" and body == before
    assert output["facts"]["technicalCompliance"] == "not_evaluated"
    body["contentInventory"]["fields"][0].update(presence="absent", value=None)
    assert run(body)["result"] == "failed"
    body["contentInventory"]["completeDocumentReview"] = False
    assert run(body)["result"] == "evidence_insufficient"
    body["contentInventory"]["fields"].pop(0)
    assert run(body)["result"] == "evidence_insufficient"
    body["basis"]["applicable"] = False
    assert run(body)["result"] == "not_applicable"
    body["basis"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("kind,field", [("procedure", "operationalCheckIntervals"), ("procedure", "relevantFactorRanges"),
    ("procedure", "approver"), ("instruction", "referencedProcedureVersion"), ("instruction", "inspectionRatio"),
    ("instruction", "acceptanceLevel"), ("instruction", "inspectionDiagram"), ("instruction", "reviewerLevel")])
def test_individual_clause_leaves_are_required(kind, field):
    body = arguments(kind)
    body["contentInventory"]["fields"] = [row for row in body["contentInventory"]["fields"] if row["fieldId"] != field]
    output = run(body)
    assert output["result"] == "evidence_insufficient"
    assert any(row["code"] == field and row["result"] == "evidence_insufficient" and row["clause"] for row in output["facts"]["contentChecks"])


@pytest.mark.parametrize("field", SCOPE_FIELDS)
@pytest.mark.parametrize("target", ["basis", "contentInventory", "field"])
def test_wrong_identity_never_passes(field, target):
    body = arguments()
    record = body[target] if target != "field" else body["contentInventory"]["fields"][0]
    record[field] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case", ["duplicate", "unknown", "other_version", "blank_quote", "blank_value", "contradictory_absence", "unknown_presence", "bool_presence", "incomplete_review"])
def test_ambiguous_or_unsupported_field_facts(case):
    body = arguments()
    fields = body["contentInventory"]["fields"]
    if case == "duplicate":
        fields.append(deepcopy(fields[0]))
    elif case == "unknown":
        fields[0]["fieldId"] = "OTHER"
    elif case == "other_version":
        fields[0]["evidenceRefs"][0]["documentVersionId"] = "OLD"
    elif case == "blank_quote":
        fields[0]["evidenceRefs"][0]["quotedText"] = ""
    elif case == "blank_value":
        fields[0]["value"] = ""
    elif case == "contradictory_absence":
        fields[0]["presence"] = "absent"
    elif case == "unknown_presence":
        fields[0]["presence"] = "unknown"
    elif case == "bool_presence":
        fields[0]["presence"] = True
    else:
        fields[0].update(presence="absent", value=None)
        body["contentInventory"]["completeDocumentReview"] = 1
    assert run(body)["result"] == "evidence_insufficient"


def test_instruction_does_not_invent_approver_requirement_or_level_threshold():
    body = arguments()
    assert "approver" not in {row["fieldId"] for row in body["contentInventory"]["fields"]}
    for row in body["contentInventory"]["fields"]:
        if row["fieldId"] in {"authorLevel", "reviewerLevel"}:
            row["value"] = "II"
    assert run(body)["result"] == "passed"
    assert run(body)["facts"]["wholeRuleAcceptance"] == "not_evaluated"
