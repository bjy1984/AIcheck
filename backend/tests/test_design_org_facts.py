"""节点 1 的一致性核对终于有了另一侧：图签设计单位与设计章单位。

AC-R01-01 用 check_all_equal 比 designLicense.holderName / designDocument.titleBlockOrganization /
designDocument.designSealOrganization。2026-09-11 全节点扫描：后两处全库没有任何地方产出，
执行器只读不写——这条核对永远只有许可证一侧、永远 fewer_than_two_comparable_values。

样本按生产原样：地上甲类储罐区2（含泵区）施工图.pdf 首页「项目名称」字段与 seals[]。
"""
from __future__ import annotations

from libs.review_orchestrator.certificate_facts import merge_certificate_facts
from libs.review_orchestrator.design_org_facts import build_design_org_facts
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
    assert all(item["confidenceUnavailable"] for item in merged["judgment"]["claimedFacts"] if item.get("label"))


def test_节点2不产设计单位事实():
    assert "designDocument" not in merge_certificate_facts(_state(), {**_run(), "nodeId": 2}, {})
