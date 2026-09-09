"""P11 N-02：project.pipelines 由本工程所有设计资料的管道特性表构建，R04/R06/R07 才能逐管线判。"""

from __future__ import annotations

from libs.review_orchestrator.pipeline_facts import build_project_pipelines, merge_project_pipelines
from libs.review_tools.executor import project_pipeline_facts


def _state() -> dict:
    return {
        "documents": [
            {"id": "D-DESIGN", "projectId": "P-1", "currentVersionId": "V-DESIGN", "fileName": "管道特性表.pdf"},
            {"id": "D-OTHER", "projectId": "P-2", "currentVersionId": "V-OTHER", "fileName": "别的工程.pdf"},
        ],
        "versions": [],
        "ocr_parse_results": [
            {
                "documentId": "D-DESIGN",
                "documentVersionId": "V-DESIGN",
                "documentType": "pipeline_characteristic_table",
                "tables": [
                    {
                        "tableId": "T-1",
                        "title": "管道特性表",
                        "pageNo": 2,
                        "normalizedRows": [
                            {"管线号": "PL-101", "管道级别": "gc1", "设计压力": "1.6MPa", "设计温度": "80", "材质": "20#", "规格": "DN100", "介质": "蒸汽"},
                            {"管线号": "PL-101", "管道级别": "GC1", "设计压力": "1.6"},
                            {"管线号": "PL-202", "管道级别": "GC2", "设计压力": "0.8", "设计温度": "40", "材质": "S30408"},
                            {"备注": "空行"},
                        ],
                    }
                ],
            },
            {
                "documentId": "D-OTHER",
                "documentVersionId": "V-OTHER",
                "tables": [{"tableId": "T-X", "title": "管道特性表", "normalizedRows": [{"管线号": "PL-999", "设计压力": "9"}]}],
            },
        ],
    }


def test_pipelines_are_deduplicated_by_line_number_keeping_the_richer_row() -> None:
    pipelines = build_project_pipelines(_state(), "P-1")
    by_id = {item["pipelineId"]: item for item in pipelines}
    assert set(by_id) == {"PL-101", "PL-202"}, "别的工程的表不算；空行不算"
    first = by_id["PL-101"]
    assert first["pipelineGrade"] == "GC1" and first["designPressureMPa"] == 1.6 and first["designTemperatureC"] == 80.0
    assert first["material"] == "20#" and first["specification"] == "DN100" and first["medium"] == "蒸汽"
    assert first["source"]["fileName"] == "管道特性表.pdf" and first["source"]["pageNo"] == 2
    assert first["evidence"]["documentVersionId"] == "V-DESIGN"


def test_merge_fills_project_pipelines_and_grades_but_never_overrides_upstream() -> None:
    state = _state()
    run = {"projectId": "P-1", "nodeId": 4}
    facts = merge_project_pipelines(state, run, {"designDocuments": {"documents": []}})
    assert facts["project"]["pipelineCount"] == 2
    assert facts["project"]["pipelineGrades"] == ["GC1", "GC2"]
    assert [item["pipelineId"] for item in project_pipeline_facts(facts)] == ["PL-101", "PL-202"], "executor 直接拿到逐管线事实"
    upstream = {"project": {"pipelines": [{"pipelineId": "X"}], "pipelineGrade": "GC1"}}
    assert merge_project_pipelines(state, run, upstream)["project"]["pipelines"] == [{"pipelineId": "X"}]
    assert merge_project_pipelines({"documents": [], "ocr_parse_results": []}, run, None) == {}


def test_frozen_run_pipeline_merge_cannot_reuse_unselected_upstream_facts():
    import pytest

    from libs.review_document_scope import freeze_document_scope

    state = _state()
    run = {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": []}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    upstream = {"project": {"pipelines": [{"pipelineId": "UNSELECTED"}], "pipelineGrades": ["GC1"]}}
    assert merge_project_pipelines(state, run, upstream)["project"] == {
        "pipelines": [], "pipelineGrades": [], "pipelineCount": 0}
    assert upstream["project"]["pipelines"][0]["pipelineId"] == "UNSELECTED"
    run["inputDocumentVersionIds"] = ["V-DESIGN"]
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    assert merge_project_pipelines(state, run, upstream)["project"]["pipelineCount"] == 2
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][0]["设计压力"] = "99"
    with pytest.raises(ValueError, match="sources_changed"):
        merge_project_pipelines(state, run, upstream)


def _scoped_run(state):
    from libs.review_document_scope import freeze_document_scope

    run = {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": ["V-DESIGN"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    return run


def test_scoped_pipeline_conflicts_cannot_be_hidden_by_richer_row_or_order():
    from copy import deepcopy

    import pytest

    from libs.review_orchestrator.pipeline_facts import PipelineFactsConflict

    for reverse in (False, True):
        state = _state()
        rows = state["ocr_parse_results"][0]["tables"][0]["normalizedRows"]
        rows[1]["设计压力"] = "2.5"
        if reverse:
            rows.reverse()
        before = deepcopy(state)
        run = _scoped_run(state)
        with pytest.raises(PipelineFactsConflict) as error:
            merge_project_pipelines(state, run, {"project": {"pipelines": [{"pipelineId": "OLD"}]}})
        assert error.value.reason == "REVIEW_PIPELINE_FACTS_CONFLICT"
        conflict = error.value.conflicts[0]
        assert conflict["pipelineId"] == "PL-101" and conflict["field"] == "designPressureMPa"
        assert {item["value"] for item in conflict["sources"]} == {1.6, 2.5}
        assert all(item["source"]["documentVersionId"] == "V-DESIGN" for item in conflict["sources"])
        assert state == before


def test_scoped_conflicts_check_all_candidates_even_if_richest_row_has_no_value():
    import pytest

    from libs.review_orchestrator.pipeline_facts import PipelineFactsConflict

    state = _state()
    rows = state["ocr_parse_results"][0]["tables"][0]["normalizedRows"]
    rows.extend([{"管线号": "PL-101", "毒性程度": "高度危害"}, {"管线号": "PL-101", "毒性程度": "中度危害"}])
    with pytest.raises(PipelineFactsConflict) as error:
        build_project_pipelines(state, "P-1", review_run=_scoped_run(state))
    assert error.value.conflicts[0]["field"] == "mediumToxicity"


def test_scoped_identical_and_complementary_rows_and_unselected_conflicts():
    state = _state()
    # Equal normalized pressure and grade are accepted; unrelated project is excluded.
    state["ocr_parse_results"][1]["tables"][0]["normalizedRows"] = [{"管线号": "PL-101", "设计压力": "99"}]
    result = build_project_pipelines(state, "P-1", review_run=_scoped_run(state))
    assert next(row for row in result if row["pipelineId"] == "PL-101")["designPressureMPa"] == 1.6
    # Legacy calls retain the previous richer-row behavior.
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][1]["设计压力"] = "99"
    assert build_project_pipelines(state, "P-1")[0]["designPressureMPa"] == 1.6


def test_runtime_context_stops_on_pipeline_conflict_without_retry(monkeypatch):
    import pytest

    from libs.review_orchestrator import execution
    from libs.review_orchestrator.failure_policy import review_failure_retryable
    from libs.review_orchestrator.pipeline_facts import PipelineFactsConflict

    state = _state()
    state["ocr_parse_results"][0]["tables"][0]["normalizedRows"][1]["设计压力"] = "99"
    monkeypatch.setattr(execution.repo, "state", state)
    monkeypatch.setattr(execution.repo, "require_project", lambda *_: {})
    monkeypatch.setattr(execution.repo, "node", lambda *_: {})
    context = {}
    with pytest.raises(PipelineFactsConflict) as error:
        execution.run_step(_scoped_run(state), "load_context", context)
    assert not review_failure_retryable(error.value)
    assert "businessFacts" not in context
