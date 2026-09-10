from copy import deepcopy

import pytest

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for
from libs.review_page_scope import restrict_parse_result


def fragment(text, page=1, confidence=.93):
    return {"text": text, "pageNo": page, "confidence": confidence, "bbox": [10, 10, 300, 30], "coordinateSystem": "pixel"}


@pytest.mark.parametrize("title,kind", [
    ("焊接工艺评定报告（PQR）", "pqr"), ("预焊接工艺规程（pWPS）", "pwps"),
    ("焊接工艺规程（WPS）", "wps"), ("焊接工艺卡", "wps"),
    ("焊接工艺评定焊接及检验记录", "welding_record"),
    ("射线检测报告书", "rt_report"), ("射线检测报告（主页）", "rt_report"),
    ("超声波检测报告（附页）", "ut_report"),
])
def test_title_classification_preserves_source_without_changing_profile(title, kind):
    parse = {"profileId": "welding_procedure_qualification_v1", "fields": [], "tables": [], "fragments": [fragment(title)]}
    before = deepcopy(parse)
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    result = parse["documentPageClassification"]
    assert result["complete"] is False
    assert result["pages"][0]["documentKind"] == kind
    assert result["pages"][0]["titleEvidence"][0]["source"] == before["fragments"][0]
    assert parse["profileId"] == before["profileId"]
    assert parse["fragments"] == before["fragments"]


def test_unknown_continuation_and_conflicting_titles_are_not_assigned_by_neighbour():
    parse = {"fields": [], "tables": [], "fragments": [fragment("射线检测报告书", 1), fragment("检测数据", 2),
        fragment("焊接工艺评定报告", 3), fragment("射线检测报告书", 3)]}
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    pages = parse["documentPageClassification"]["pages"]
    assert [row["status"] for row in pages] == ["identified", "unknown", "ambiguous"]
    assert [row["documentKind"] for row in pages] == ["rt_report", None, None]
    assert len(pages[2]["titleEvidence"]) == 2


@pytest.mark.parametrize("text,confidence", [("应提供射线检测报告", .99), ("1.2 射线检测报告", .99),
    ("射线检测报告", .5), ("射线检测报告", True), ("焊接工艺评定", .99)])
def test_mentions_contents_and_low_confidence_are_unknown(text, confidence):
    parse = {"fields": [], "tables": [], "fragments": [fragment(text, confidence=confidence)]}
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert parse["documentPageClassification"]["pages"][0]["status"] == "unknown"


def test_page_selection_rebuilds_classification_from_selected_sources_only():
    parse = {"fields": [], "tables": [], "fragments": [fragment("射线检测报告书", 1), fragment("焊接记录", 2)]}
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    before = deepcopy(parse)
    selected = restrict_parse_result(parse, {"start": 2, "end": 2})
    pages = selected["documentPageClassification"]["pages"]
    assert [row["pageNo"] for row in pages] == [2]
    assert pages[0]["documentKind"] == "welding_record"
    assert "射线" not in str(selected)
    assert parse == before
