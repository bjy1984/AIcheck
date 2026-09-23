"""节点 1 的一致性核对终于有了另一侧：图签设计单位与设计章单位。

AC-R01-01 用 check_all_equal 比 designLicense.holderName / designDocument.titleBlockOrganization /
designDocument.designSealOrganization。2026-09-11 全节点扫描：后两处全库没有任何地方产出，
执行器只读不写——这条核对永远只有许可证一侧、永远 fewer_than_two_comparable_values。

样本按生产原样：地上甲类储罐区2（含泵区）施工图.pdf 首页「项目名称」字段与 seals[]。
"""
from __future__ import annotations

from libs.review_orchestrator.certificate_facts import merge_certificate_facts
from libs.review_orchestrator.design_org_facts import build_design_org_facts
from libs.review_orchestrator.deterministic_tools import check_design_license_scope
from libs.review_tools.executor import build_tool_arguments

TITLE_BLOCK = (
    "广东政和工程有限公司GEM-HORSE ENGINEERING CO.,LTD(原广东政和石油化工建筑设计有限公司) "
    "资质等级GRADE OF QUALIFICATION 甲级CLASS AA144003911 1/2\n专业DISC. 工艺\n建设单位CONSTR. UNIT 珠海海瑞德制药有限公司 图名DWG NAME"
)


def _state(*, seals: list[dict] | None = None, title_block: str = TITLE_BLOCK) -> dict:
    return {
        "documents": [
            {"id": "DOC-DWG", "projectId": "P-1", "currentVersionId": "DV-DWG",
             "fileName": "地上甲类储罐区2（含泵区）施工图.pdf", "materialTypeCode": "design_document"},
            {"id": "DOC-LIC", "projectId": "P-1", "currentVersionId": "DV-LIC",
             "fileName": "广东政和设计院压力管道设计资质.png", "materialTypeCode": "design_license"},
        ],
        "versions": [{"id": "DV-DWG", "documentId": "DOC-DWG"}, {"id": "DV-LIC", "documentId": "DOC-LIC"}],
        "projects": [{"id": "P-1", "designOrgName": "广东政和工程有限公司"}],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-DWG", "status": "success", "profileId": "piping_characteristic_list_v1",
                "quality": {"reasons": ["provider_confidence_unavailable"]},
                "fields": [{"fieldCode": "project_name", "fieldName": "项目名称", "fieldValue": title_block, "pageNo": 1, "bbox": [41, 26, 567, 801], "confidence": 0.0}],
                "fragments": [],
                "seals": seals if seals is not None else [
                    {"text": "广东政和工程有限公司", "name": "广东政和工程有限公司", "pageNo": 1, "bbox": [1, 2, 3, 4]},
                    {"pageNo": 2},
                    {"text": "广东政和工程有限公司", "name": "广东政和工程有限公司", "pageNo": 3},
                ],
            },
            {
                "documentVersionId": "DV-LIC", "status": "success", "profileId": "qualification_certificate_v1",
                "quality": {"reasons": ["provider_confidence_unavailable"]},
                "fields": [
                    {"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": "TS1844171-2028", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                    {"fieldCode": "organization_name", "fieldName": "单位名称", "fieldValue": "广东政和工程有限公司", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                    {"fieldCode": "valid_until", "fieldName": "有效期至", "fieldValue": "2028年1月17日", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                ],
                "fragments": [],
                "seals": [{"text": "广东省市场监督管理局", "name": "广东省市场监督管理局", "pageNo": 1}],
            },
        ],
    }


def _run() -> dict:
    return {"projectId": "P-1", "nodeId": 1, "inputDocumentVersionIds": ["DV-DWG", "DV-LIC"]}


def test_图签设计单位从首页项目名称字段的开头取():
    facts = build_design_org_facts(_state(), _run())
    assert facts["designDocument"]["titleBlockOrganization"] == "广东政和工程有限公司"


def test_设计章只认单位章_发证机关的章不算():
    facts = build_design_org_facts(_state(), _run())
    assert facts["designDocument"]["designSealOrganization"] == "广东政和工程有限公司"
    # 许可证上的「广东省市场监督管理局」不是设计单位；设计文件里也不能被别的印章冒充。
    only_gov = _state(seals=[{"text": "广东省市场监督管理局", "pageNo": 1}])
    assert build_design_org_facts(only_gov, _run())["designDocument"]["designSealOrganization"] is None


def test_证据带页码与引文():
    facts = build_design_org_facts(_state(), _run())
    evidence = facts["designDocument"]["evidence"]
    assert len(evidence) == 2
    assert all(item["pageNo"] == 1 and item["quotedText"] and item["evidenceRefId"] for item in evidence)
    assert evidence[0]["quotedText"].startswith("广东政和工程有限公司GEM-HORSE")


def test_没有设计文件时不产出():
    state = _state()
    state["documents"][0]["materialTypeCode"] = "construction_organization_design"
    assert build_design_org_facts(state, _run()) == {}


def test_节点1合并后check_all_equal拿到三个值():
    """这就是 AC-R01-01 的输入：许可证持证单位 + 图签 + 设计章，三处同名。"""
    merged = merge_certificate_facts(_state(), _run(), {})
    arguments = build_tool_arguments(
        "check_all_equal",
        {"atomicCheckId": "AC-R01-01", "parameters": {"argumentProfile": "r01_design_org_identity", "normalizer": "organization_name"}},
        facts=merged, explicit={}, document_version_ids=["DV-DWG", "DV-LIC"], evidence_facts=[], evidence_refs=[],
    )
    values = {item["source"]: item["value"] for item in arguments["values"]}
    assert values == {
        "designLicense.holderName": "广东政和工程有限公司",
        "designDocument.titleBlockOrganization": "广东政和工程有限公司",
        "designDocument.designSealOrganization": "广东政和工程有限公司",
    }
    # 两条设计文件事实也进了 judgment，grounding 核得到。
    labels = {item.get("label") for item in merged["judgment"]["claimedFacts"]}
    assert {"图签设计单位", "设计章单位"} <= labels
    by_label = {item.get("label"): item for item in merged["judgment"]["claimedFacts"] if item.get("label")}
    # 图签来自「项目名称」字段 → 界面能让人核对无误；印章不是字段 → 没有可核条目。
    title_fields = by_label["图签设计单位"]["fields"]
    assert [(item["fieldName"], item["documentId"]) for item in title_fields] == [("项目名称", "DOC-DWG")]
    assert title_fields[0]["humanCorrected"] is False and title_fields[0]["quotedText"].startswith("广东政和工程有限公司")
    assert by_label["设计章单位"]["fields"] == []
    assert all(item["confidenceUnavailable"] for item in merged["judgment"]["claimedFacts"] if item.get("label"))


def test_节点2不产设计单位事实():
    assert "designDocument" not in merge_certificate_facts(_state(), {**_run(), "nodeId": 2}, {})


def test_设计文件级别从结构化字段进入R01_04并带原文定位():
    state = _state()
    state["ocr_parse_results"][0]["fields"].append({
        "fieldCode": "pressure_pipe_level", "fieldName": "压力管道级别", "fieldValue": "GC2",
        "pageNo": 23, "bbox": [10, 20, 30, 40], "confidence": 0.0,
    })
    state["ocr_parse_results"][1]["fields"].append({
        "fieldCode": "license_scope", "fieldName": "许可范围", "fieldValue": "GC1", "pageNo": 1,
    })
    facts = merge_certificate_facts(state, _run(), {})
    design = facts["designDocument"]
    assert design["pipelineGrades"] == ["GC2"]
    assert design["pipelineGradeIssues"] == []
    grade = next(item for item in facts["judgment"]["claimedFacts"] if item.get("label") == "设计文件管道级别")
    assert grade["value"] == "GC2" and grade["documentVersionId"] == "DV-DWG"
    assert grade["fields"][0]["fieldName"] == "压力管道级别"
    evidence = next(item for item in facts["judgment"]["evidenceRefs"]
                    if item["evidenceRefId"] in grade["evidenceRefIds"])
    assert evidence["pageNo"] == 23 and evidence["quotedText"] == "GC2"
    arguments = build_tool_arguments(
        "check_design_license_scope",
        {"atomicCheckId": "AC-R01-04", "parameters": {"argumentProfile": "r01_design_scope_documents",
                                                "scopeProfile": "design-license-scope-cn-v2"}},
        facts=facts, explicit={}, document_version_ids=["DV-DWG", "DV-LIC"],
        evidence_facts=[], evidence_refs=[],
    )
    assert arguments["requiredPipelineGrades"] == ["GC2"]
    assert check_design_license_scope(arguments)["result"] == "passed"


def test_一份设计文件没有级别时不拿另一份的级别冒充完整覆盖():
    state = _state()
    state["documents"].append({"id": "DOC-DWG-2", "projectId": "P-1", "currentVersionId": "DV-DWG-2",
                                "fileName": "另一份设计文件.pdf", "materialTypeCode": "design_document"})
    state["versions"].append({"id": "DV-DWG-2", "documentId": "DOC-DWG-2"})
    state["ocr_parse_results"].append({"documentVersionId": "DV-DWG-2", "status": "success", "fields": [],
                                       "fragments": []})
    state["ocr_parse_results"][0]["fields"].append({
        "fieldCode": "pressure_pipe_level", "fieldName": "压力管道级别", "fieldValue": "GC2", "pageNo": 23,
    })
    run = {**_run(), "inputDocumentVersionIds": ["DV-DWG", "DV-DWG-2", "DV-LIC"]}
    design = build_design_org_facts(state, run)["designDocument"]
    assert design["pipelineGrades"] == []
    assert design["pipelineGradeIssues"] == ["DV-DWG-2"]


def test_已选设计文件完全没有OCR时也不能报告级别覆盖():
    state = _state()
    state["ocr_parse_results"][0]["fields"].append({
        "fieldCode": "pressure_pipe_level", "fieldName": "压力管道级别", "fieldValue": "GC2", "pageNo": 23,
    })
    state["documents"].append({"id": "DOC-DWG-2", "projectId": "P-1", "currentVersionId": "DV-DWG-2",
                                "fileName": "尚未识别的设计文件.pdf", "materialTypeCode": "design_document"})
    state["versions"].append({"id": "DV-DWG-2", "documentId": "DOC-DWG-2"})
    run = {**_run(), "inputDocumentVersionIds": ["DV-DWG", "DV-DWG-2", "DV-LIC"]}
    design = build_design_org_facts(state, run)["designDocument"]
    assert design["pipelineGrades"] == []
    assert design["pipelineGradeIssues"] == ["DV-DWG-2"]


def test_设计文件OCR失败时不把残留字段当成已核完整资料():
    state = _state()
    state["ocr_parse_results"][0]["status"] = "failed"
    state["ocr_parse_results"][0]["fields"].append({
        "fieldCode": "pressure_pipe_level", "fieldName": "压力管道级别", "fieldValue": "GC2", "pageNo": 23,
    })
    design = build_design_org_facts(state, _run())["designDocument"]
    assert design["pipelineGrades"] == []
    assert design["pipelineGradeIssues"] == ["DV-DWG"]


def test_同一字段写多个级别但没有对象映射时不猜一种():
    state = _state()
    state["ocr_parse_results"][0]["fields"].append({
        "fieldCode": "pressure_pipe_level", "fieldName": "压力管道级别",
        "fieldValue": "GC1、GC2", "pageNo": 23,
    })
    design = build_design_org_facts(state, _run())["designDocument"]
    assert design["pipelineGrades"] == []
    assert design["pipelineGradeIssues"] == ["DV-DWG"]


def test_设计章按事实路径确认后有分():
    """印章不是抽取字段，只能按 factPath 确认；确认后证据 1.0，节点 1 才出得去「需人工判断」。"""
    state = _state()
    state["fact_corrections"] = [{
        "id": "FCOR-SEAL", "status": "active", "projectId": "P-1", "nodeId": 1,
        "factPath": "designDocument.designSealOrganization", "documentVersionId": "DV-DWG",
        "correctedValue": "广东政和工程有限公司", "reason": "人工核对无误",
    }]
    merged = merge_certificate_facts(state, _run(), {})
    by_label = {item.get("label"): item for item in merged["judgment"]["claimedFacts"] if item.get("label")}
    seal = by_label["设计章单位"]
    assert seal["confidence"] == 1.0 and seal["confidenceUnavailable"] is False
    assert seal["factPath"] == "designDocument.designSealOrganization"
    # 图签那条没确认，仍旧没分——一次确认只算一处。
    assert by_label["图签设计单位"]["confidenceUnavailable"] is True
