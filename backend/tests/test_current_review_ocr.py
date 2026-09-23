"""A selected document version contributes one current OCR attempt to a review."""

from copy import deepcopy

from test_pipeline_facts import _state as pipeline_state
from test_r19_semantic_agent import r19_state, review_run
from test_r40_record_correspondence import evaluate, fixture

from libs.review_document_scope import freeze_document_scope
from libs.review_input_data import current_selected_parse_results
from libs.review_orchestrator.pipeline_facts import build_project_pipelines
from libs.review_orchestrator.r19_agent import build_r19_agent_context
from libs.review_orchestrator.runtime_tools import extract_document_fields
from libs.review_orchestrator.source_coverage import selected_source_issues


def test_current_ocr_keeps_page_scope_and_human_correction_after_reparse():
    old = {"id": "OLD", "documentVersionId": "V", "finishedAt": "2026-09-01T00:00:00Z",
           "fields": [{"fieldName": "grade", "pageNo": 2, "value": "OLD"}]}
    new = {"id": "NEW", "documentVersionId": "V", "finishedAt": "2026-09-02T00:00:00Z",
           "fields": [{"fieldName": "grade", "pageNo": 2, "value": "NEW"},
                      {"fieldName": "grade", "pageNo": 4, "value": "OUTSIDE"}]}
    state = {"ocr_parse_results": [old, new], "fact_corrections": [
        {"projectId": "P", "nodeId": 14, "documentVersionId": "V", "fieldId": "F2",
         "status": "active", "fieldName": "grade", "correctedValue": "HUMAN", "pageNo": 2},
    ]}
    run = {"projectId": "P", "nodeId": 14, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 3}}}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    original = deepcopy(state)

    selected = current_selected_parse_results(state, {}, context={"reviewRun": run})
    assert len(selected) == 1 and selected[0]["id"] == "NEW"
    assert [(field["pageNo"], field["value"]) for field in selected[0]["fields"]] == [(2, "HUMAN")]
    assert selected[0]["fields"][0]["humanCorrected"] is True
    assert state == original


def test_latest_failed_ocr_never_falls_back_to_old_facts_or_runtime_fields():
    state = {"ocr_parse_results": [
        {"id": "OLD", "documentVersionId": "V", "finishedAt": "2026-09-01T00:00:00Z",
         "fields": [{"fieldCode": "license_no", "fieldValue": "STALE"}]},
        {"id": "NEW", "documentVersionId": "V", "finishedAt": "2026-09-02T00:00:00Z",
         "status": "failed", "fields": []},
    ]}
    run = {"inputDocumentVersionIds": ["V"]}
    assert current_selected_parse_results(state, {}, context={"reviewRun": run}) == []
    assert current_selected_parse_results(state, {}, context={"reviewRun": run},
                                          include_unusable=True)[0]["id"] == "NEW"
    assert extract_document_fields(state, {}, context={"reviewRun": run})["fields"] == []


def test_same_version_attempts_without_a_trustworthy_order_remain_ambiguous():
    state = {"ocr_parse_results": [
        {"id": "A", "documentVersionId": "V", "fields": [{"value": "A"}]},
        {"id": "B", "documentVersionId": "V", "fields": [{"value": "B"}]},
    ]}
    assert current_selected_parse_results(state, {}, context={"reviewRun": {"inputDocumentVersionIds": ["V"]}}) == []


def test_r40_uses_only_latest_attempt_but_still_requires_a_usable_source():
    state, run = fixture()
    old = state["ocr_parse_results"][0]
    old["finishedAt"] = "2026-09-01T00:00:00Z"
    old["tables"][3]["normalizedRows"][0]["recordId"] = "STALE"
    latest = deepcopy(old)
    latest["id"] = "NEW"
    latest["finishedAt"] = "2026-09-02T00:00:00Z"
    latest["tables"][3]["normalizedRows"][0]["recordId"] = "REC1"
    state["ocr_parse_results"].append(latest)

    assert evaluate(state, run)["result"] == "passed"
    latest["status"] = "failed"
    assert evaluate(state, run)["result"] == "evidence_insufficient"
    assert selected_source_issues(state, run, node_id=40)[0]["code"] == "r40_selected_source_missing_or_ambiguous"


def test_frozen_pipeline_facts_ignore_old_conflicting_ocr():
    state = pipeline_state()
    old = state["ocr_parse_results"][0]
    old["id"] = "OLD"
    old["finishedAt"] = "2026-09-01T00:00:00Z"
    latest = deepcopy(old)
    latest["id"] = "NEW"
    latest["finishedAt"] = "2026-09-02T00:00:00Z"
    latest["tables"][0]["normalizedRows"][0]["设计压力"] = "1.8MPa"
    latest["tables"][0]["normalizedRows"][1]["设计压力"] = "1.8"
    state["ocr_parse_results"].append(latest)
    run = {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": ["V-DESIGN"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    pipelines = build_project_pipelines(state, "P-1", review_run=run)
    assert next(row for row in pipelines if row["pipelineId"] == "PL-101")["designPressureMPa"] == 1.8
    latest["status"] = "failed"
    # Re-freeze a new review; a changed OCR is never silently reused by the old run.
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert build_project_pipelines(state, "P-1", review_run=run) == []


def test_r19_context_does_not_expose_stale_attempt_or_failed_latest():
    state = r19_state()
    old = state["ocr_parse_results"][0]
    old["id"] = "OLD"
    old["finishedAt"] = "2026-09-01T00:00:00Z"
    old["fragments"][0]["text"] = "STALE"
    latest = deepcopy(old)
    latest["id"] = "NEW"
    latest["finishedAt"] = "2026-09-02T00:00:00Z"
    latest["fragments"][0]["text"] = "CURRENT"
    state["ocr_parse_results"].append(latest)

    context = build_r19_agent_context(state, review_run())
    assert context["documentCount"] == 1
    assert any("CURRENT" in row["quotedText"] for row in context["evidenceIndex"].values())
    assert all("STALE" not in row["quotedText"] for row in context["evidenceIndex"].values())
    latest["status"] = "failed"
    assert build_r19_agent_context(state, review_run())["documentCount"] == 0
