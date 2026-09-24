from __future__ import annotations

from scripts import evaluate_jev_fact_check_template as probe


def test_cases_cover_old_extractor_errors_and_only_fictional_text():
    rows = probe.cases()
    assert {row["kind"] for row in rows} == {"correct", "year_off", "old_extractor_start_date"}
    assert all("完全虚构" in row["text"] for row in rows)
    assert sum(row["kind"] == "old_extractor_start_date" for row in rows) == 7


def test_score_counts_flags_per_fact():
    def fact(field, suspect):
        return {"field": field, "suspect": suspect, "lowConfidence": False}

    results = [
        {"kind": "old_extractor_start_date", "wrongUntil": True, "status": "completed",
         "facts": [fact("validUntil", True), fact("certificateNo", False), fact("holder", False)]},
        {"kind": "correct", "wrongUntil": False, "status": "completed",
         "facts": [fact("validUntil", False), fact("certificateNo", True), fact("holder", False)]},
    ]
    report = probe.score(results)
    assert report["wrongEndDateFlagged"] == "1/1"
    assert report["oldExtractorErrorFlagged"] == "1/1"
    assert report["correctEndDateFlagged"] == "0/1"
    assert report["correctNumberOrHolderFlagged"] == "1/4"
