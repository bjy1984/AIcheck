from copy import deepcopy

import pytest

from apps.ocr_service.service import apply_profile_postprocessing
from libs.ocr.profiles import profile_for


def fixture():
    return {"fields": [], "fragments": [
        {"text": text, "bbox": box, "pageNo": 11, "coordinateSystem": "pixel", "confidence": .9}
        for text, box in [("报告编号", [5, 20, 75, 35]), ("2023SHZH-0", [105, 5, 190, 20]),
                          ("22RTBG-01", [105, 25, 190, 40]), ("承包单位", [210, 20, 275, 35])]],
        "tables": [{"tableId": "T", "pageNo": 11, "sourceEngine": "opencv_table_grid_subprocess",
                    "bbox": [0, 0, 300, 50], "closedCellsTableBBox": [0, 0, 300, 50],
                    "closedCellsCoordinateSystem": "pixel", "closedCells": [
                        {"cellId": "label", "bbox": [0, 0, 100, 50]},
                        {"cellId": "value", "bbox": [100, 0, 200, 50]},
                        {"cellId": "other", "bbox": [200, 0, 300, 50]}]}]}


def test_same_closed_cell_joins_lines_and_retains_all_source_parts():
    parse = fixture()
    before = deepcopy(parse)
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    row = next(row for row in parse["fields"] if row["fieldCode"] == "report_no")
    assert row["fieldValue"] == "2023SHZH-022RTBG-01"
    assert row["sourceFragments"] == before["fragments"][1:3]
    assert row["sourceCellId"] == "value"
    assert row["bbox"] == [100, 0, 200, 50]
    assert row["pageNo"] == 11
    assert "layout_join_requires_source_review" in row["qualityFlags"]
    assert parse["fragments"] == before["fragments"]


@pytest.mark.parametrize("case", ["crosses_border", "low_confidence", "wrong_page", "normalized", "transformed",
                                  "rescaled_table", "duplicate_cell", "parallel_values", "non_identifier", "missing_boundary"])
def test_ambiguous_geometry_or_source_cannot_produce_report_number(case):
    parse = fixture()
    if case == "crosses_border": parse["fragments"][1]["bbox"][2] = 205
    if case == "low_confidence": parse["fragments"][1]["confidence"] = .5
    if case == "wrong_page": parse["tables"][0]["pageNo"] = 12
    if case == "normalized":
        for row in parse["fragments"]: row["coordinateSystem"] = "normalized"
    if case == "transformed": parse["tables"][0]["coordinateTransform"] = {"scale": 2}
    if case == "rescaled_table": parse["tables"][0]["bbox"][2] = 600
    if case == "duplicate_cell": parse["tables"][0]["closedCells"].append(deepcopy(parse["tables"][0]["closedCells"][1]))
    if case == "parallel_values": parse["fragments"][2]["bbox"][1] = 10
    if case == "non_identifier": parse["fragments"][2]["text"] = "承包单位"
    if case == "missing_boundary": parse["tables"][0].pop("closedCellsTableBBox")
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert not any(row["fieldCode"] == "report_no" for row in parse["fields"])


def test_conflicting_existing_number_is_retained_with_conflict_warning():
    parse = fixture()
    parse["fields"] = [{"fieldCode": "report_no", "fieldValue": "R-OTHER"}]
    apply_profile_postprocessing(parse, profile_for("ndt_rt_report_v1"))
    assert parse["fields"][0]["fieldValue"] == "R-OTHER"
    assert "field_value_conflict" in parse["fields"][0]["qualityFlags"]
    assert any(row["code"] == "NDT_REPORT_CELL_CONFLICT" for row in parse["diagnostics"])


@pytest.mark.parametrize("cell_limit", [1800, 1])
def test_grid_engine_preserves_a_merged_cell(tmp_path, monkeypatch, cell_limit):
    import sys

    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from apps.ocr_service.engines import OpenCvTableGridSubprocessEngine

    image = np.full((210, 360, 3), 255, dtype=np.uint8)
    for y in (20, 70, 120, 170):
        cv2.line(image, (20, y), (320, y), (0, 0, 0), 2)
    for x in (20, 120, 220, 320):
        cv2.line(image, (x, 70 if x == 220 else 20), (x, 170), (0, 0, 0), 2)
    path = tmp_path / "merged.png"
    cv2.imwrite(str(path), image)
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", sys.executable)
    monkeypatch.setenv("AICHECK_OPENCV_TABLE_GRID_MAX_CELLS", str(cell_limit))
    output = OpenCvTableGridSubprocessEngine().parse(path)
    assert output["ok"] is True
    table = output["tables"][0]
    assert table["closedCellsTableBBox"] == table["bbox"]
    assert table["closedCellsCoordinateSystem"] == "pixel"
    if cell_limit == 1:
        assert table["closedCells"] == []
        assert any(row["code"] == "OPENCV_CLOSED_CELLS_TRUNCATED" for row in output["diagnostics"])
        return
    assert any(cell["bbox"][2] - cell["bbox"][0] > 180 and cell["bbox"][1] < 30 for cell in table["closedCells"])
