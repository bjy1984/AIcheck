from __future__ import annotations

import csv
import json

from scripts import prepare_jev_fact_labels as prepare
from scripts import score_jev_fact_labels as score


def _item(item_id, **extra):
    return {"id": item_id, "projectId": "P", "tenantId": "T", "nodeId": 2, "documentVersionIds": ["V"],
            "field": "certificateNo", "value": "TS3844617-2026", "instructions": "只看这张许可证：…", **extra}


def test_packet_subject_names_the_record_or_says_how_to_find_it():
    assert prepare._subject({"instructions": "只看这份资料：不锈钢工业弯头的证书编号是否写为X？"}) == "不锈钢工业弯头"
    assert prepare._subject({"instructions": "只看这份资料：证书编号是否写为X？"}).startswith("（表格中的一条记录")
    assert prepare._subject({"instructions": "只看姜军的焊工资格证：它的证件编号是否为X？"}) == "姜军的焊工资格证"


def test_packet_rows_hold_no_model_answer_or_system_flag():
    snapshot = {"documents": [{"id": "D", "projectId": "P", "fileName": "许可证.pdf"}],
                "versions": [{"id": "V", "documentId": "D"}],
                "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "status": "success",
                                       "fragments": [{"pageNo": 3, "text": "许可证编号 TS3844617-2026"}]}]}
    rows = prepare.packet_rows(snapshot, [_item("F-1", plausible=False)])
    assert rows[0]["文件名"] == "许可证.pdf" and rows[0]["页码"] == "3"
    assert set(rows[0]) == set(prepare.COLUMNS)
    assert "False" not in json.dumps(rows, ensure_ascii=False)


def _sheet(path, verdicts):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=prepare.COLUMNS)
        writer.writeheader()
        for item_id, verdict in verdicts.items():
            writer.writerow({**{column: "" for column in prepare.COLUMNS}, "条目编号": item_id,
                             "判定（正确/错误/原文没有/看不清）": verdict})


def test_agreement_adjudication_and_metrics(tmp_path):
    _sheet(tmp_path / "a.csv", {"F-1": "错误", "F-2": "正确", "F-3": "正确", "F-4": "看不清"})
    _sheet(tmp_path / "b.csv", {"F-1": "错误", "F-2": "正确", "F-3": "错误", "F-4": "看不清"})
    a, b = score.read_sheet(tmp_path / "a.csv"), score.read_sheet(tmp_path / "b.csv")
    verdicts, open_ids = score.final_verdicts(a, b, None)
    assert open_ids == ["F-3"] and verdicts == {"F-1": "错误", "F-2": "正确", "F-4": "看不清"}
    _sheet(tmp_path / "adj.csv", {"F-3": "正确"})
    verdicts, open_ids = score.final_verdicts(a, b, score.read_sheet(tmp_path / "adj.csv"))
    assert not open_ids and verdicts["F-3"] == "正确"
    assert score.cohen_kappa([("错误", "错误"), ("正确", "正确"), ("正确", "错误")]) == 0.4
    items = {key: _item(key) for key in ("F-1", "F-2", "F-3", "F-4")}
    items["F-3"]["plausible"] = False
    answers = {"F-1": {"suspect": True}, "F-2": {"suspect": False}, "F-3": {"suspect": False},
               "F-4": {"suspect": True}}
    report = score.metrics(verdicts, items, answers)
    assert report["scoredItems"] == 3 and report["wrongExtractions"] == 1
    assert report["jevOnly"]["wrongCaught"].startswith("1/1 ") and report["jevOnly"]["correctFlagged"].startswith("0/2 ")
    assert report["jevPlusLocal"]["correctFlagged"].startswith("1/2 ")


def test_invalid_verdicts_and_missing_rows_are_reported(tmp_path):
    _sheet(tmp_path / "a.csv", {"F-1": "对的"})
    problems = score.validate(score.read_sheet(tmp_path / "a.csv"), {"F-1", "F-2"}, "A")
    assert problems == ["A:missing_rows:1", "A:F-1:invalid_verdict:对的"]
