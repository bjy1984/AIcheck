from __future__ import annotations

from scripts import evaluate_jev_fact_check_real as probe


def _snapshot():
    text = ("安装许可证 证书编号：TS3841999-2028 单位名称：甲公司 有效期：2024年9月7日至2028年9月6日\n"
            "另附检测机构证书 证书编号：TS7310417-2026 单位名称：乙公司 有效期至：2026年12月10日")
    return {"documents": [{"id": "D", "projectId": "P", "fileName": "合订本.pdf"}],
            "versions": [{"id": "V", "documentId": "D"}],
            "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "status": "success",
                                   "fragments": [{"pageNo": 1, "text": text}]}]}


def _rows():
    first = {"certificateType": "installation_license", "holder": "甲公司", "certificateNo": "TS3841999-2028",
             "validFrom": "2024-09-07", "validUntil": "2028-09-06"}
    second = {"certificateType": "installation_license", "holder": "乙公司", "certificateNo": "TS7310417-2026",
              "validUntil": "2026-12-10"}
    return [{"projectId": "P", "nodeId": 2, "version": "V", "tenantId": None, "cert": cert} for cert in (first, second)]


def test_true_claims_are_literal_and_wrong_claims_cover_each_error_kind():
    rows = probe.claims(_rows(), _snapshot())
    first = [row for row in rows if row["cert"]["holder"] == "甲公司"]
    assert {(row["field"], row["claimed"]) for row in first if row["expected"] == "yes"} == {
        ("validUntil", "2028-09-06"), ("validFrom", "2024-09-07"), ("certificateNo", "TS3841999-2028"),
        ("holder", "甲公司")}
    wrong = {(row["kind"], row["claimed"]) for row in first if row["expected"] == "no"}
    assert ("range_start_as_end", "2024-09-07") in wrong
    assert ("end_shifted_one_year", "2027-09-06") in wrong
    assert ("other_certificate_date", "2026-12-10") in wrong
    assert ("other_certificate_holder", "乙公司") in wrong
    assert ("mutated_number", "TS3841999-2021") in wrong


def test_requests_never_ask_two_values_of_the_same_field_of_one_certificate_together():
    for group in probe._requests(probe.claims(_rows(), _snapshot())):
        keys = [(id(row["cert"]), row["field"]) for row in group]
        assert len(keys) == len(set(keys))
        assert len({row["expected"] for row in group}) == 1


def test_score_reports_catches_false_alarms_and_intervals():
    results = [{"expected": "no", "kind": "range_start_as_end", "choice": "no", "suspect": True},
               {"expected": "no", "kind": "range_start_as_end", "choice": "yes", "suspect": False},
               {"expected": "yes", "kind": "literal_value", "choice": "yes", "suspect": False},
               {"expected": "yes", "kind": "literal_value", "status": "request_overlong"}]
    report = probe.score(results)
    assert report["wrongFlaggedAsSuspect"].startswith("1/2 ")
    assert report["correctFlaggedAsSuspect"].startswith("0/1 ")
    assert report["unanswered"] == {"request_overlong": 1}
