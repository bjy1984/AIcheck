"""证书有效性：事实抽取 → 确定性核验 → 进提示词，三段都要能跑通。

2026-09-03 审计：规则对齐后节点 24/38 的核验工具被调了，却全部证据不足——事实为空。
"""

from __future__ import annotations

from libs.review_orchestrator.certificate_facts import (
    build_certificate_facts,
    certificate_profile_for_node,
)
from libs.review_orchestrator.deterministic_tools import check_certificate_validity
from libs.review_tools.executor import build_tool_arguments


def _state_with_design_license(valid_until="2028年1月17日", org="广东政和工程有限公司"):
    return {
        "projects": [{"id": "P-1", "designOrgName": org, "constructionStart": "2025-04-01", "plannedConstructionEnd": "2026-04-30"}],
        "documents": [
            {"id": "DOC-1", "projectId": "P-1", "fileName": "设计资质.png", "materialTypeCode": "design_license", "currentVersionId": "DV-1"},
            {"id": "DOC-2", "projectId": "P-1", "fileName": "施工图.pdf", "materialTypeCode": "construction_drawing", "currentVersionId": "DV-2"},
        ],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-1",
                "status": "success",
                "profileId": "qualification_certificate_v1",
                "fields": [
                    {"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": "TS1844171-2028", "pageNo": 1, "bbox": [1, 2, 3, 4]},
                    {"fieldCode": "organization_name", "fieldName": "单位名称", "fieldValue": org, "pageNo": 1},
                    {"fieldCode": "license_scope", "fieldName": "许可范围", "fieldValue": "压力管道设计 工业管道(GC1)", "pageNo": 1},
                ],
                "fragments": [
                    {"pageNo": 1, "text": f"发证机关：广东省市场监督管理局 有效期至：{valid_until}"},
                ],
            },
            {"documentVersionId": "DV-2", "status": "success", "fields": [], "fragments": [{"pageNo": 1, "text": "压力管道级别 GC2"}]},
        ],
    }


def test_设计许可证事实从字段与正文里抽齐():
    facts = build_certificate_facts(_state_with_design_license(), "P-1", 1, ["DV-1", "DV-2"])
    cert = facts["certificateFacts"]
    assert cert["certificateType"] == "design_license"
    assert len(cert["certificates"]) == 1, "施工图不是证书，不能被当成证"
    item = cert["certificates"][0]
    assert item["certificateNo"] == "TS1844171-2028"
    assert item["holder"] == "广东政和工程有限公司"
    assert item["validUntil"] == "2028-01-17", "有效期来自正文正则回退"
    assert item["issuer"] == "广东省市场监督管理局"
    assert "GC1" in item["scopes"]
    assert any(ev["quotedText"].startswith("有效期至") for ev in item["evidence"])
    assert cert["expectedHolder"] == "广东政和工程有限公司"
    assert cert["period"] == {"periodStart": "2025-04-01", "periodEnd": "2026-04-30", "referenceDate": cert["period"]["referenceDate"]}
    # 旧绑定表的命名也镜像了一份
    assert facts["designLicense"]["validUntil"] == "2028-01-17"
    assert facts["designLicense"]["holderName"] == "广东政和工程有限公司"
    assert facts["project"]["constructionStart"] == "2025-04-01"


def test_有效期覆盖施工期且主体一致则通过():
    facts = build_certificate_facts(_state_with_design_license(), "P-1", 1, ["DV-1"])
    args = build_tool_arguments(
        "check_certificate_validity",
        {"parameters": {"argumentProfile": "r01_certificate_validity"}},
        facts=facts,
        explicit={},
        document_version_ids=["DV-1"],
        evidence_facts=[],
        evidence_refs=[],
    )
    assert args["certificates"] and args["periodEnd"] == "2026-04-30" and args["expectedHolder"]
    output = check_certificate_validity(args)
    assert output["result"] == "passed", output
    codes = {item["code"] for item in output["checks"]}
    assert any(code.endswith("valid_until_covers_period_end") for code in codes)
    assert any(code.endswith("holder_matches_project") for code in codes)


def test_过期或主体不符判失败_缺有效期判证据不足():
    expired = build_certificate_facts(_state_with_design_license(valid_until="2025-12-31"), "P-1", 1, ["DV-1"])
    out = check_certificate_validity({**expired["certificateFacts"], **expired["certificateFacts"]["period"]})
    assert out["result"] == "failed"

    wrong_holder = build_certificate_facts(_state_with_design_license(org="别的设计院"), "P-1", 1, ["DV-1"])
    cf = wrong_holder["certificateFacts"]
    cf["expectedHolder"] = "广东政和工程有限公司"
    out = check_certificate_validity({**cf, **cf["period"]})
    assert out["result"] == "failed"

    state = _state_with_design_license()
    state["ocr_parse_results"][0]["fragments"] = [{"pageNo": 1, "text": "无日期"}]
    missing = build_certificate_facts(state, "P-1", 1, ["DV-1"])
    cf = missing["certificateFacts"]
    out = check_certificate_validity({**cf, **cf["period"]})
    assert out["result"] == "evidence_insufficient"
    assert any("valid_until_missing" in w for w in cf["extractionWarnings"])


def test_没有施工期时按当日判断并告警():
    state = _state_with_design_license()
    state["projects"][0].pop("constructionStart")
    state["projects"][0].pop("plannedConstructionEnd")
    facts = build_certificate_facts(state, "P-1", 1, ["DV-1"])
    cf = facts["certificateFacts"]
    out = check_certificate_validity({**cf, **cf["period"]})
    assert out["result"] == "passed"
    assert "construction_period_missing_using_reference_date" in out["warnings"]
    assert any(item["code"].endswith("not_expired_on_reference_date") for item in out["checks"])


def test_检测人员证走正文回退():
    state = {
        "projects": [{"id": "P-1"}],
        "documents": [{"id": "DOC-9", "projectId": "P-1", "fileName": "11.2检测人员资质.pdf", "materialTypeCode": "ndt_person_certificate", "currentVersionId": "DV-9"}],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-9",
                "status": "success",
                "profileId": "generic_document_v1",
                "fields": [],
                "fragments": [
                    {"pageNo": 1, "text": "特种设备无损检测人员证 姓名 张三 证书编号 TS6110123-2027 持证项目 RT-Ⅱ UT-Ⅱ 有效期至 2027年6月30日 发证机关 中国特种设备检验协会"},
                ],
            }
        ],
    }
    facts = build_certificate_facts(state, "P-1", 38, ["DV-9"])
    cert = facts["certificateFacts"]["certificates"]
    assert len(cert) == 1 and cert[0]["certificateNo"] == "TS6110123-2027" and cert[0]["validUntil"] == "2027-06-30"
    assert facts["ndtPersonnel"]["registration"] == ["TS6110123-2027"]
    assert certificate_profile_for_node(38)["certificateType"] == "ndt_personnel_certificate"


def test_非证书节点不产事实():
    assert build_certificate_facts(_state_with_design_license(), "P-1", 25, ["DV-1"]) == {}
    assert certificate_profile_for_node(25) is None


def test_一键分析节点块带证书核验结论():
    from libs.project_analysis.prompt import _certificate_verification_for_node

    block = _certificate_verification_for_node(_state_with_design_license(), "P-1", 1, ["DV-1", "DV-2"])
    assert block["result"] == "passed"
    assert block["certificates"][0]["validUntil"] == "2028-01-17"
    assert _certificate_verification_for_node(_state_with_design_license(), "P-1", 25, ["DV-1"]) is None
