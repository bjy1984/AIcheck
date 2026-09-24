"""OCR pipeline stage records never replace the authoritative parse as current evidence."""

from libs.review_input_data import current_selected_parse_results, latest_selected_parses

RUN = {"inputDocumentVersionIds": ["V"]}


def _baseline():
    return {"id": "BASE", "parseResultId": "BASE", "documentVersionId": "V",
            "finishedAt": "2026-09-01T00:00:00Z", "status": "success",
            "fields": [{"fieldCode": "grade", "fieldValue": "BASELINE"}]}


def _stage(stage, stamp, **extra):
    return {"id": f"PARSE-STAGE-{stage}", "parseResultId": f"PARSE-STAGE-{stage}",
            "documentVersionId": "V", "finishedAt": stamp, "status": "success",
            "pipelineStage": stage, "pipelineRunId": "RUN-1",
            "fields": [{"fieldCode": "grade", "fieldValue": "SHADOW"}], **extra}


def test_shadow_stage_records_do_not_replace_baseline():
    state = {"ocr_parse_results": [
        _baseline(),
        _stage("structure_scan", "2026-09-02T00:00:00Z"),
        _stage("evidence_fusion", "2026-09-03T00:00:00Z"),
    ]}
    selected = current_selected_parse_results(state, {}, context={"reviewRun": RUN})
    assert [item["id"] for item in selected] == ["BASE"]
    assert latest_selected_parses(state, RUN, {"V"})["V"]["id"] == "BASE"


def test_unusable_newest_stage_record_does_not_remove_evidence():
    state = {"ocr_parse_results": [
        _baseline(), _stage("seal_signature_scan", "2026-09-02T00:00:00Z", status="failed"),
    ]}
    selected = current_selected_parse_results(state, {}, context={"reviewRun": RUN})
    assert [item["id"] for item in selected] == ["BASE"]


def test_active_finalized_record_without_stage_marker_is_current():
    authoritative = {**_baseline(), "id": "BASE-QWEN", "parseResultId": "BASE-QWEN",
                     "finishedAt": "2026-09-04T00:00:00Z"}
    state = {"ocr_parse_results": [
        _baseline(), _stage("evidence_fusion", "2026-09-03T00:00:00Z"), authoritative,
    ]}
    selected = current_selected_parse_results(state, {}, context={"reviewRun": RUN})
    assert [item["id"] for item in selected] == ["BASE-QWEN"]
