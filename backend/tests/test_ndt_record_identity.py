from copy import deepcopy

import pytest
from test_ndt_procedure_ocr_profile import source

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for


@pytest.mark.parametrize("profile_id", ["ndt_rt_report_v1", "ndt_ut_report_v1"])
def test_explicit_identity_labels_retain_their_own_source_locations(profile_id):
    data = source("检测记录编号：REC-1", "引用记录编号：REC-2", "检测事件编号：EV-3", "文件类型：检测报告")
    before = deepcopy(data["fragments"])
    apply_profile_postprocessing(data, profile_for(profile_id))
    fields = {row["fieldCode"]: row for row in data["fields"]}
    for index, (key, expected) in enumerate([("record_no", "REC-1"), ("referenced_record_no", "REC-2"),
                                           ("detection_event_no", "EV-3"), ("ndt_document_kind", "检测报告")]):
        assert fields[key]["fieldValue"] == expected
        assert fields[key]["pageNo"] == index + 1
        assert fields[key]["bbox"] == [10, 20, 180, 40]
        assert fields[key]["confidence"] == .94
    assert data["fragments"] == before
    assert data["tables"] == []


def test_dates_report_numbers_and_unlabelled_next_pages_are_not_event_identity():
    data = source("报告编号：REP-1", "检测日期：2026-09-09", "焊口编号：W-1", "引用记录编号：", "REC-NEXT-PAGE")
    apply_profile_postprocessing(data, profile_for("ndt_rt_report_v1"))
    fields = {row["fieldCode"] for row in data["fields"]}
    assert not fields.intersection({"record_no", "referenced_record_no", "detection_event_no"})


def test_ambiguous_event_is_not_chosen_by_first_occurrence():
    data = source("检测事件编号：E1", "检测任务编号：E2")
    apply_profile_postprocessing(data, profile_for("ndt_ut_report_v1"))
    assert not any(row["fieldCode"] == "detection_event_no" for row in data["fields"])
    assert any(row["code"] == "NDT_RECORD_IDENTITY_CONFLICT" for row in data["diagnostics"])


def test_existing_disagreement_is_flagged_without_overwriting_original():
    data = source("引用记录编号：REC-NEW")
    data["fields"] = [{"fieldCode": "referenced_record_no", "fieldValue": "REC-OLD", "confidence": .9}]
    apply_profile_postprocessing(data, profile_for("ndt_rt_report_v1"))
    field = next(row for row in data["fields"] if row["fieldCode"] == "referenced_record_no")
    assert field["fieldValue"] == "REC-OLD"
    assert "field_value_conflict" in field["qualityFlags"]
