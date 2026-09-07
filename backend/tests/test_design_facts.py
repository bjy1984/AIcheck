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


def test_calculation_and_design_change_facts_feed_r06_and_r07() -> None:
    from libs.review_tools.business_tools import (
        evaluate_calculation_document_consistency,
        evaluate_design_change_approval,
    )

    state = _state()
    state["projects"] = [{"id": "P-1", "designOrgName": "广东政和工程有限公司"}]
    state["documents"].append({"id": "D-CHG", "projectId": "P-1", "currentVersionId": "V-CHG", "fileName": "设计变更通知单.pdf", "materialTypeCode": "design_change_document"})
    state["ocr_parse_results"].append(
        {
            "documentVersionId": "V-CHG",
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "设计变更通知单 涉及 管道布置图 图号：PID-001 管线 PL-101 原设计单位：广东政和工程有限公司 批准单位：广东政和工程有限公司 同意变更 设计：张三 校核：李四 审核：王五 审定：赵六"}],
            "seals": [{"sealName": "广东政和工程有限公司压力管道设计许可印章"}],
        }
    )
    # 强度计算书写了设计压力 1.6 / 设计温度 90（管道特性表 80）
    calc = next(item for item in state["ocr_parse_results"] if item["documentVersionId"] == "V-CALC")
    calc["fragments"][0]["text"] += " 设计压力：1.6MPa 设计温度：90℃ 图号：PID-001"
    run = {"projectId": "P-1", "nodeId": 6, "inputDocumentVersionIds": ["V-CAT", "V-DS", "V-CALC", "V-MYST", "V-CHG"]}
    facts = merge_project_pipelines(state, run, build_design_business_facts(state, run))

    calc_facts = facts["calculationDocuments"]
    assert calc_facts["requiredPipelineIds"] == ["PL-101"] and calc_facts["uncoveredRequiredPipelineIds"] == []
    comparisons = {item["code"]: item for item in calc_facts["documents"][0]["parameterComparisons"]}
    assert comparisons["designPressureMPa"]["documentValue"] == "1.6" and comparisons["designPressureMPa"]["designValue"] == 1.6
    consistency = evaluate_calculation_document_consistency({"documents": calc_facts["documents"], "targetDocumentTypes": ["strength_calculation"]})
    assert consistency["result"] == "failed", "设计温度 90 ≠ 特性表 80"

    changes = facts["designChanges"]
    assert changes["hasDesignChanges"] is True
    change = changes["documents"][0]
    assert change["changedDocumentType"] == "pipeline_layout_drawing"
    assert change["writtenApproval"] is True and change["designLicenseSeal"] is True
    assert change["originalDesignOrganizationName"] == "广东政和工程有限公司" == change["approvingOrganizationName"]
    assert change["referencedDrawingsFound"] == ["PID-001"] and change["referencedDrawingsMissing"] == []
    approval = evaluate_design_change_approval({"hasDesignChanges": True, "documents": changes["documents"], "pipelines": project_pipeline_facts(facts)})
    assert approval["result"] == "passed", approval
    assert approval["documentResults"][0]["requiredApprovalLevel"] == 4, "变更的是布置图且覆盖 GC1 管线 → 四级"


def test_design_special_requirements_feed_r09_frozen_rules() -> None:
    from libs.review_orchestrator.design_facts import (
        design_special_requirements,
        frozen_special_requirement_rules,
        standard_ref_id,
    )
    from libs.review_tools.business_tools import evaluate_design_special_requirements

    assert standard_ref_id("GB/T 20801.1-2025") == "STD-GBT-20801.1-2025" and standard_ref_id("TSG 31-2025") == "STD-TSG-31-2025"
    text = (
        "设计说明 依据 GB/T 20801.1-2025 与 TSG 31-2025。无损检测：焊缝采用射线检测(RT)，检测比例不低于 20%，Ⅱ级合格。"
        "防腐：管道外表面喷砂除锈 Sa2.5，环氧富锌底漆两道，涂层厚度不小于 200μm。"
        "耐压试验：液压试验，试验压力为设计压力的 1.5 倍，保压 10 min 无泄漏无变形。"
        "泄漏试验：气密性试验，泄漏试验压力 1.6MPa，采用发泡剂检查无泄漏。"
    )
    pipelines = [{"pipelineId": "PL-101", "designPressureMPa": 1.6, "pipelineGrade": "GC1"}]
    requirements = design_special_requirements(text, pipelines)
    domains = requirements["domains"]
    assert domains["ndt"]["specified"] and domains["ndt"]["requirements"]["coverage"] == "20%" and domains["ndt"]["requirements"]["acceptanceCriteria"] == "Ⅱ级"
    assert "STD-GBT-20801.1-2025" in domains["ndt"]["standardRefs"] and "STD-TSG-31-2025" in domains["ndt"]["standardRefs"]
    assert domains["pressureTest"]["requirements"]["testPressureRatio"] == 1.5 and domains["pressureTest"]["requirements"]["testPressureMeetsRatio"] is True
    assert domains["leakTest"]["requirements"]["leakPressureNotBelowDesign"] is True
    assert "喷砂" in domains["corrosion"]["requirements"]["protectionMethod"]

    rules = frozen_special_requirement_rules()
    assert set(rules) == {"ndt", "corrosion", "pressureTest", "leakTest"}
    outcome = evaluate_design_special_requirements(
        {
            "requirements": domains,
            "standardRules": rules,
            "domains": ["ndt", "corrosion", "pressureTest", "leakTest"],
            "requiredPathsByDomain": {
                "ndt": ["requirements.method", "requirements.coverage", "requirements.acceptanceCriteria"],
                "corrosion": ["requirements.protectionMethod", "requirements.acceptanceCriteria"],
                "pressureTest": ["requirements.method", "requirements.testPressure", "requirements.acceptanceCriteria"],
                "leakTest": ["requirements.method", "requirements.testPressure", "requirements.acceptanceCriteria"],
            },
        }
    )
    assert outcome["result"] == "passed", outcome

    # 只写了"耐压试验压力 1.6MPa"（= 设计压力，倍数 1.0）→ 试验压力倍数不满足 → 不符合
    weak = design_special_requirements("依据 GB/T 20801.1-2025。液压试验，试验压力 1.6MPa，保压 10min 无泄漏。", pipelines)
    assert weak["domains"]["pressureTest"]["requirements"]["testPressureMeetsRatio"] is False


def test_drawing_review_witness_facts_feed_r05() -> None:
    from libs.review_orchestrator.design_facts import drawing_review_witness
    from libs.review_tools.business_tools import evaluate_drawing_review_witness

    project = {"name": "地上甲类储罐区2（含泵区）压力管道安装", "constructionStart": "2026-03-01"}
    documents = [
        {"documentId": "D-W", "documentVersionId": "V-W", "documentType": "drawing_review_record", "fileName": "施工图审查合格书.pdf", "bodyUploaded": True, "signatureRoles": [], "sealTexts": ["XX施工图审查中心审图专用章"], "evidenceRefs": []},
        {"documentId": "D-DS", "documentVersionId": "V-DS", "documentType": "pipeline_data_sheet", "fileName": "管道特性表.pdf", "bodyUploaded": True, "signatureRoles": [], "sealTexts": [], "evidenceRefs": []},
    ]
    texts = {
        "V-W": "施工图审查合格书 工程名称：地上甲类储罐区2（含泵区）压力管道安装 审查机构：广东省施工图审查中心 审查日期：2026-01-15 版次：A",
        "V-DS": "管道特性表 版次：A",
    }
    witness = drawing_review_witness(documents, texts, project)
    assert witness["witnessTypes"] == ["review_approval_certificate"]
    assert witness["issuer"]["projectNameMatches"] is True and witness["issuer"]["name"] == "广东省施工图审查中心"
    assert witness["reviewBeforeConstruction"] is True and witness["drawingVersionConsistent"] is True
    assert witness["signatures"]["sealPresent"] is True
    outcome = evaluate_drawing_review_witness({"witness": witness, "acceptedTypes": ["review_approval_certificate", "review_opinion", "design_reply", "owner_filing_receipt"]})
    assert outcome["result"] == "passed", outcome

    # 只有审查意见书、没有设计回复，且审查日期晚于开工 → 不符合
    late = drawing_review_witness([documents[0] | {"fileName": "审查意见书.pdf"}], {"V-W": "审查意见书 工程名称：地上甲类储罐区2（含泵区）压力管道安装 审查日期：2026-04-01"}, project)
    assert late["witnessTypes"] == ["review_opinion"] and late["reviewBeforeConstruction"] is False
    failed = evaluate_drawing_review_witness({"witness": late})
    assert failed["result"] == "failed"
    codes = {item["code"] for item in failed["checks"] if not item["passed"]}
    assert {"design_reply_present", "review_before_construction"} <= codes

    # 工程名称都没识别到 → 证据不足，不猜
    unknown = drawing_review_witness([documents[0]], {"V-W": "施工图审查合格书 审查日期：2026-01-15"}, {"name": "别的工程", "constructionStart": "2026-03-01"})
    assert unknown["issuer"]["projectNameMatches"] is None
    assert evaluate_drawing_review_witness({"witness": unknown})["result"] == "evidence_insufficient"


def test_design_standard_references_feed_r08_version_check() -> None:
    from libs.review_orchestrator.design_facts import design_standard_references
    from libs.review_tools.business_tools import check_standard_version_active

    facts = design_standard_references({"V-1": "设计依据：TSG D0001—2009、GB/T 20801.1-2025", "V-2": "焊工按 TSG Z6002-2026 考核"}, "2026-09-06")
    refs = {item["standardRef"]: item for item in facts["standardReferences"]}
    assert refs["TSG D0001-2009"]["timelineStatus"] == "withdrawn" and refs["TSG Z6002-2026"]["timelineStatus"] == "current"
    assert refs["GB/T 20801.1-2025"]["timelineStatus"] == "current"
    assert facts["requiresOnlineLookup"] == []
    outcome = check_standard_version_active({"standardReferences": facts["standardReferences"], "reviewDate": "2026-09-06"})
    assert outcome["result"] == "failed", "引用了已废止的 TSG D0001-2009"
    failed = [item for item in outcome["checks"] if not item["passed"]]
    assert [item["code"] for item in failed] == ["TSG D0001-2009"]
