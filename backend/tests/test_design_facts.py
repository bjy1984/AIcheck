"""P11 N-06/N-07：设计节点事实——目录对照集合 + 逐份设计文件（子类型、签字角色、覆盖管线）。"""

from __future__ import annotations

from libs.review_orchestrator.design_facts import (
    build_design_business_facts,
    classify_design_document,
)
from libs.review_orchestrator.pipeline_facts import merge_project_pipelines
from libs.review_tools.business_tools import (
    check_document_set_completeness,
    evaluate_design_document_approval,
)
from libs.review_tools.executor import project_pipeline_facts


def _state() -> dict:
    return {
        "documents": [
            {"id": "D-CAT", "projectId": "P-1", "currentVersionId": "V-CAT", "fileName": "图纸目录.pdf", "materialTypeCode": "design_document"},
            {"id": "D-DS", "projectId": "P-1", "currentVersionId": "V-DS", "fileName": "管道特性表.pdf", "materialTypeCode": "design_document"},
            {"id": "D-CALC", "projectId": "P-1", "currentVersionId": "V-CALC", "fileName": "L-101强度计算书.pdf", "materialTypeCode": "calculation_report"},
            {"id": "D-MYST", "projectId": "P-1", "currentVersionId": "V-MYST", "fileName": "扫描件001.pdf", "materialTypeCode": "design_document"},
        ],
        "versions": [],
        "ocr_parse_results": [
            {"documentVersionId": "V-CAT", "status": "success", "tables": [{"tableId": "T", "normalizedRows": [{"序号": "1", "图纸名称": "管道特性表"}, {"序号": "2", "图纸名称": "管道平面布置图"}, {"序号": "3", "图纸名称": "综合材料表"}]}]},
            {"documentVersionId": "V-DS", "status": "success", "tables": [{"tableId": "T-DS", "title": "管道特性表", "pageNo": 1, "normalizedRows": [{"管线号": "PL-101", "管道级别": "GC1", "设计压力": "1.6", "设计温度": "80"}, {"管线号": "PL-202", "管道级别": "GC2", "设计压力": "0.8", "设计温度": "40"}]}]},
            {"documentVersionId": "V-CALC", "status": "success", "fragments": [{"pageNo": 1, "text": "L-101 直管强度计算书 管线 PL-101 设计：张三 校核：李四 审核：王五"}], "signatures": [{"role": "审定", "name": "赵六"}]},
            {"documentVersionId": "V-MYST", "status": "failed", "fragments": [{"pageNo": 1, "text": ""}]},
        ],
    }


def test_classifier_prefers_file_name_then_first_page() -> None:
    assert classify_design_document("管道等级表.pdf", "") == "pipeline_material_grade_table"
    assert classify_design_document("扫描件.pdf", "XX 工程 管道应力分析报告") == "pipeline_stress_calculation"
    assert classify_design_document("扫描件.pdf", "") == "design_document_other"


def test_design_facts_feed_r04_completeness_and_approval_checks() -> None:
    state = _state()
    run = {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": ["V-CAT", "V-DS", "V-CALC", "V-MYST"]}
    facts = merge_project_pipelines(state, run, build_design_business_facts(state, run, known_pipeline_ids={"PL-101", "PL-202"}))
    document_set = facts["designDocumentSet"]
    assert document_set["catalogListedDocumentTypes"] == ["pipeline_data_sheet", "pipeline_layout_drawing", "pipeline_material_list"]
    assert set(document_set["uploadedDocumentTypes"]) == {"drawing_catalog", "pipeline_data_sheet", "strength_calculation", "design_document_other"}
    assert "design_document_other" in document_set["uploadedDocumentTypes"] and document_set["unclassified"][0]["fileName"] == "扫描件001.pdf"
    assert "design_document_other" not in document_set["parseableDocumentTypes"], "解析失败的不算可解析"

    calc = next(item for item in facts["designDocuments"]["documents"] if item["documentType"] == "strength_calculation")
    assert calc["signatureRoles"] == ["审定", "设计", "校核", "审核"]
    assert calc["coveredPipelineIds"] == ["PL-101"]

    completeness = check_document_set_completeness(
        {"requiredDocumentTypes": ["pipeline_data_sheet", "pipeline_layout_drawing"], "uploadedDocumentTypes": document_set["uploadedDocumentTypes"], "parseableDocumentTypes": document_set["parseableDocumentTypes"]}
    )
    assert completeness["result"] == "failed", "目录列了布置图但没上传 → 差集非空"

    approval = evaluate_design_document_approval(
        {
            "approvalMode": "four_level_conditional",
            "targetDocumentTypes": ["strength_calculation"],
            "requiredRoles": ["设计", "校核", "审核", "审定"],
            "documents": facts["designDocuments"]["documents"],
            "pipelines": project_pipeline_facts(facts),
        }
    )
    assert approval["result"] == "passed", approval
    assert approval["documentResults"][0]["triggerCodes"] == ["GC1_PIPELINE"], "PL-101 是 GC1，触发四级会签，逐管线判"
