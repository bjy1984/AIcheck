from copy import deepcopy

import pytest

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r39_tools import IDENTITY_FIELDS


def arguments():
    scope = dict(zip(IDENTITY_FIELDS, ("P1", "ORG1", "INS1", "V1", "UT", "W1", "EVENT1"), strict=True))

    def record(version, **values):
        return {**scope, **values, "evidenceRefs": [{"documentVersionId": version, "pageNo": 2, "quotedText": "Synthetic sourced fact"}]}

    return {"projectId": "P1", "scope": scope,
            "basis": record("STD1", standard="NB/T 47013.1-2015", clause="4.3.2.3", applicable=True),
            "application": record("APP1", firstUse=True, completed=True),
            "validation": record("VAL1", performed=True, atFirstUse=True)}


def run(body):
    return dispatch_runtime_tool({}, "evaluate_r39_first_use_validation", body)


def test_four_states_and_no_whole_rule_claim():
    body = arguments()
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed"
    assert body == before
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert output["facts"]["evidenceVerified"] is False
    assert {ref["documentVersionId"] for ref in output["evidenceRefs"]} == {"STD1", "APP1", "VAL1"}
    body["validation"]["performed"] = False
    assert run(body)["result"] == "failed"
    body.pop("validation")
    assert run(body)["result"] == "evidence_insufficient"
    body["application"]["firstUse"] = False
    assert run(body)["result"] == "not_applicable"
    body["application"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("record", ["basis", "application", "validation"])
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_no_cross_scope_or_version_records(record, field):
    body = arguments()
    body[record][field] = "OTHER"
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("record", ["basis", "application", "validation"])
@pytest.mark.parametrize("change", [{"pageNo": True}, {"pageNo": 0}, {"quotedText": ""}, {"documentVersionId": ""}])
def test_evidence_requires_version_page_and_quote(record, change):
    body = arguments()
    body[record]["evidenceRefs"][0].update(change)
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
@pytest.mark.parametrize("value", [None, "", " P1", 1])
def test_incomplete_application_identity(field, value):
    body = arguments()
    body["scope"][field] = value
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("value,expected", [(True, "passed"), (False, "failed"), (None, "evidence_insufficient"), (1, "evidence_insufficient"), ("true", "evidence_insufficient")])
def test_sourced_timing_and_strict_booleans(value, expected):
    body = arguments()
    body["validation"]["atFirstUse"] = value
    assert run(body)["result"] == expected


@pytest.mark.parametrize("performed", [True, False, None, "false", 0])
@pytest.mark.parametrize("completed", [False, None, "true", 1])
def test_ongoing_or_unknown_application_cannot_fail_prematurely(performed, completed):
    body = arguments()
    body["application"]["completed"] = completed
    body["validation"]["performed"] = performed
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("change", [{"standard": "OTHER"}, {"clause": "7.2.3"}, {"applicable": False}, {"applicable": 1}])
def test_unknown_standard_applicability_not_silently_not_applicable(change):
    body = arguments()
    body["basis"].update(change)
    assert run(body)["result"] == "evidence_insufficient"


def test_no_invented_exclusive_validation_method_or_before_start_requirement():
    body = arguments()
    body["validation"].update(validationMethod="other_sourced_method", occurredBeforeApplicationStart=False)
    assert run(body)["result"] == "passed"
    body["validation"]["performed"] = "false"
    assert run(body)["result"] == "evidence_insufficient"
