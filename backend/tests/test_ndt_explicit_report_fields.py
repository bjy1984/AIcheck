import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for


def source(*lines):
    return {"fields": [], "tables": [], "fragments": [
        {"text": line, "pageNo": 1, "bbox": [10, 20 + index * 30, 300, 40 + index * 30],
         "confidence": .91, "coordinateSystem": "pixel", "sourceEngine": "fixture"}
        for index, line in enumerate(lines)]}


@pytest.mark.parametrize("profile", ["ndt_rt_report_v1", "ndt_ut_report_v1"])
@pytest.mark.parametrize("conclusion", ["合格", "不合格", "符合", "不符合", "待复核"])
def test_explicit_conclusion_preserves_original_polarity_and_location(profile, conclusion):
    parse = source(f"检测结论：{conclusion}", "合格级别：II", "评定级别：III", "技术等级：AB")
    before = deepcopy(parse["fragments"])
    apply_profile_postprocessing(parse, profile_for(profile))
    fields = {row["fieldCode"]: row for row in parse["fields"]}
    assert fields["conclusion"]["fieldValue"] == conclusion
    assert fields["conclusion"]["bbox"] == before[0]["bbox"]
    assert fields["conclusion"]["confidence"] == .91
    assert fields["evaluation_level"]["fieldValue"] == "III"
    assert fields["acceptance_level"]["fieldValue"] == "II"
    assert fields["technical_grade"]["fieldValue"] == "AB"
    assert parse["fragments"] == before


@pytest.mark.parametrize("line", ["合格级别：II", "不合格产品必须返修", "射线检测报告", "RT: I级 合格"])
def test_unlabelled_mentions_do_not_manufacture_conclusions(line):
    parse = source(line)
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert not any(row["fieldCode"] == "conclusion" for row in parse["fields"])


def test_report_identity_is_not_record_or_event_identity_and_dates_are_separate():
    parse = source("报告编号：2023SHZH-022RTBG-01", "报告日期：2023年10月23日", "检测日期：2023年10月22日")
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    fields = {row["fieldCode"]: row["fieldValue"] for row in parse["fields"]}
    assert fields == {"report_no": "2023SHZH-022RTBG-01", "report_date": "2023年10月23日", "detection_date": "2023年10月22日"}


def test_separate_table_fragments_are_not_joined_without_cell_evidence():
    parse = source("报告编号", "2023SHZH-0", "单元名称：/", "承包单位", "22RTBG-01")
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert not any(row["fieldCode"] == "report_no" for row in parse["fields"])


def test_existing_conflicting_conclusion_is_flagged_not_overwritten():
    parse = source("检测结论：不合格")
    parse["fields"] = [{"fieldCode": "conclusion", "fieldValue": "合格"}]
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert parse["fields"][0]["fieldValue"] == "合格"
    assert "field_value_conflict" in parse["fields"][0]["qualityFlags"]
    assert any(row["code"] == "NDT_REPORT_LABEL_CONFLICT" for row in parse["diagnostics"])


def test_multiple_report_numbers_remain_ambiguous():
    parse = source("报告编号：R-1", "报告编号：R-2")
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert not any(row["fieldCode"] == "report_no" for row in parse["fields"])
    assert any(row["code"] == "NDT_REPORT_LABEL_CONFLICT" for row in parse["diagnostics"])


def test_procedure_does_not_fall_through_to_generic_table_processing(monkeypatch):
    def unexpected(*args):
        pytest.fail("procedure must finish in its own profile branch")

    monkeypatch.setattr("apps.ocr_service.service.align_grid_tables_with_fragments", unexpected)
    parse = source("文件编号：P-1", "报告编号：R-1")
    apply_profile_postprocessing(parse, profile_for("ndt_procedure_v1"))
    assert {row["fieldCode"] for row in parse["fields"]} == {"procedure_no"}


def test_real_scanned_cover_reads_report_number_without_truncated_project_name():
    sample = json.loads((Path(__file__).parent / "fixtures" / "ndt_real_cover_fields.json").read_text())
    parse = {"fields": [], "tables": [], "fragments": deepcopy(sample["fragments"])}
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    fields = {row["fieldCode"]: row for row in parse["fields"]}
    assert set(fields) == {"report_no"}
    assert fields["report_no"]["fieldValue"] == "2023SHZH-022RTBG-01"
    assert fields["report_no"]["pageNo"] == 10
    origin = next(row for row in sample["fragments"] if "报告编号" in row["text"])
    assert fields["report_no"]["bbox"] == origin["bbox"]
    assert fields["report_no"]["confidence"] == origin["confidence"]
    assert parse["fragments"] == sample["fragments"]
