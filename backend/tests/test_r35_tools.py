from copy import deepcopy

import pytest

from libs.review_tools.business_tools import dispatch_business_tool


def arguments():
    refs = [{"documentVersionId": "V1", "pageNo": 1}]
    record = {"projectId": "P1", "organizationId": "NDT1", "status": "conforming", "evidenceRefs": refs}
    return {"projectId": "P1", "organizationId": "NDT1", "activityDate": "2026-09-09",
            "applicability": {"required": True, "evidenceRefs": refs},
            **{key: [deepcopy(record)] for key in ("manual", "controlledForms", "appointments", "implementationRecords")},
            "equipmentIds": ["UT1"], "equipmentEvidenceRefs": refs,
            "calibrationReports": [{**deepcopy(record), "equipmentId": "UT1", "validFrom": "2026-01-01", "validUntil": "2026-12-31"}]}


def run(body):
    return dispatch_business_tool("evaluate_ndt_quality_system", body)


def test_r35_dedicated_four_states_and_does_not_mutate_input():
    body = arguments()
    before = deepcopy(body)
    output = run(body)
    assert output["result"] == "passed" and output["ruleVersion"] == "r35-site-quality-system-v1"
    assert output["evidenceRefs"] and body == before
    body["implementationRecords"][0]["status"] = "nonconforming"
    assert run(body)["result"] == "failed"
    body["implementationRecords"] = []
    assert run(body)["result"] == "evidence_insufficient"
    body["applicability"]["required"] = False
    assert run(body)["result"] == "not_applicable"
    body["applicability"]["evidenceRefs"] = []
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("field", ["manual", "controlledForms", "appointments", "implementationRecords", "calibrationReports", "equipmentIds", "equipmentEvidenceRefs"])
def test_r35_missing_required_evidence_never_passes(field):
    body = arguments()
    body[field] = []
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("change", ["other_project", "other_org", "template", "no_refs", "bad_page", "duplicate", "wrong_equipment", "invalid_dates", "unknown_date"])
def test_r35_missing_or_ambiguous_facts_never_become_conforming(change):
    body = arguments()
    record = body["calibrationReports"][0]
    if change == "other_project":
        record["projectId"] = "P2"
    elif change == "other_org":
        record["organizationId"] = "NDT2"
    elif change == "template":
        body["implementationRecords"][0]["status"] = "template"
    elif change == "no_refs":
        record["evidenceRefs"] = []
    elif change == "bad_page":
        record["evidenceRefs"] = [{"documentVersionId": "V1", "pageNo": True}]
    elif change == "duplicate":
        body["calibrationReports"].append(deepcopy(record))
    elif change == "wrong_equipment":
        record["equipmentId"] = "UT2"
    elif change == "invalid_dates":
        record["validFrom"] = "2027-01-01"
    elif change == "unknown_date":
        body["activityDate"] = None
    assert run(body)["result"] == "evidence_insufficient"


@pytest.mark.parametrize("day,expected", [("2026-01-01", "passed"), ("2026-12-31", "passed"), ("2025-12-31", "failed"), ("2027-01-01", "failed")])
def test_r35_calibration_validity_uses_activity_date_inclusive(day, expected):
    body = arguments()
    body["activityDate"] = day
    assert run(body)["result"] == expected


def test_r35_empty_arguments_and_generic_profile_cannot_bypass_site_checks():
    assert run({})["result"] == "evidence_insufficient"
    assert run({"applicable": True, "requiredFields": ["manual"], "facts": {"manual": True}, "ruleChecks": []})["result"] == "evidence_insufficient"
