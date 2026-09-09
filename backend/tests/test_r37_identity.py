import pytest

from libs.review_tools.r37_identity import matches_case_record


@pytest.mark.parametrize("left,right,expected", [({}, {}, True), ({"eventId": "E1"}, {"eventId": "E1"}, True),
    ({"eventId": "E1"}, {}, False), ({}, {"eventId": "E1"}, False), ({"eventId": "E2"}, {"eventId": "E1"}, False),
    ({"eventId": None}, {"eventId": None}, False), ({"eventId": " "}, {"eventId": " "}, False)])
def test_event_identity_does_not_use_partial_or_blank_matches(left, right, expected):
    assert matches_case_record({"caseId": "C1", **left}, {"caseId": "C1", **right}, ("caseId",)) is expected


def test_missing_identity_fields_are_not_equal_identities():
    assert not matches_case_record({}, {}, ("caseId",))
    assert not matches_case_record({"repairRound": True}, {"repairRound": 1}, ("repairRound",))
