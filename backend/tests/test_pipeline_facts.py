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
