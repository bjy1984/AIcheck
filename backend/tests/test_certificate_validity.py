"""证书有效性：事实抽取 → 确定性核验 → 进提示词，三段都要能跑通。

2026-09-03 审计：规则对齐后节点 24/38 的核验工具被调了，却全部证据不足——事实为空。
"""

from __future__ import annotations

from copy import deepcopy

from libs.business_pack import load_business_pack
from libs.business_pack.clause_store import (
    bind_project_node_clause_packages,
    publish_standard_clause_release,
    resolve_project_node_clause_package,
)
from libs.review_orchestrator.certificate_facts import (
    build_certificate_facts,
    certificate_profile_for_node,
)
from libs.review_orchestrator.deterministic_tools import (
    check_certificate_validity,
    check_design_license_scope,
)
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


def test_设计许可证GC1覆盖GC2时证照与范围工具结论一致():
    facts = build_certificate_facts(_state_with_design_license(), "P-1", 1, ["DV-1"])
    cert = facts["certificateFacts"]["certificates"][0]
    validity = check_certificate_validity({
        **facts["certificateFacts"], **facts["certificateFacts"]["period"], "requiredScopes": ["GC2"]
    })
    scope = check_design_license_scope({"licenseScopes": cert["scopes"], "requiredPipelineGrades": ["GC2"]})

    assert validity["result"] == scope["result"] == "passed"
    assert validity["facts"]["certificates"][0]["acceptedScopesByRequired"] == {"GC2": ["GC1", "GC2"]}
    assert validity["ruleVersion"] == "certificate-validity-cn-v2"


def test_r01_新版GCD覆盖GC2_旧版仍按冻结规则判断():
    base = {"referenceDate": "2026-09-23", "requiredScopes": ["GC2"], "certificateType": "design_license",
            "certificates": [{"certificateNo": "TS-1", "validUntil": "2028-01-01", "scopes": ["GCD"]}]}
    scope_args = {"licenseScopes": ["GCD"], "requiredPipelineGrades": ["GC2"]}

    assert check_design_license_scope(scope_args)["result"] == "failed"
    assert check_certificate_validity(base)["result"] == "failed"
    new_profile = {"scopeProfile": "design-license-scope-cn-v2"}
    scope = check_design_license_scope({**scope_args, **new_profile})
    validity = check_certificate_validity({**base, **new_profile})
    assert scope["result"] == validity["result"] == "passed"
    assert scope["ruleVersion"] == "design-license-scope-cn-v2"
    assert validity["ruleVersion"] == "certificate-validity-cn-v3"
    assert validity["facts"]["certificates"][0]["acceptedScopesByRequired"] == {
        "GC2": ["GC1", "GC2", "GCD"]
    }


def test_r01_新版不反向覆盖且未知版本不放行():
    profile = {"scopeProfile": "design-license-scope-cn-v2"}
    assert check_design_license_scope({**profile, "licenseScopes": ["GC2"],
                                       "requiredPipelineGrades": ["GCD"]})["result"] == "failed"
    assert check_design_license_scope({**profile, "licenseScopes": ["GCD"],
                                       "requiredPipelineGrades": ["GC1"]})["result"] == "failed"
    assert check_design_license_scope({**profile, "licenseScopes": ["GCD"],
                                       "requiredPipelineGrades": []})["result"] == "evidence_insufficient"
    assert check_design_license_scope({"scopeProfile": "unknown", "licenseScopes": ["GCD"],
                                       "requiredPipelineGrades": ["GC2"]})["result"] == "evidence_insufficient"


def test_r01_业务包新旧发布版本并存且原文保留():
    pack = load_business_pack()
    assert pack["version"] == "2026.09.23"
    r01 = next(item for item in pack["ruleSets"] if item["sourceRuleId"] == "R01")
    assert r01["version"] == "engineering-inspection-r01-v20260923"
    assert "GC2 管道可由 GC2、GC1 或 GCD 许可覆盖" in r01["witnessText"]
    assert "GC2级别管道要有GC2或者GC1的资质" in r01["sourceWitness"]
    bindings = {item["atomicCheckId"]: item for item in pack["atomicCheckToolBindings"]}
    for identity in ("AC-R01-02", "AC-R01-03", "AC-R01-04"):
        assert bindings[identity]["parameters"]["scopeProfile"] == "design-license-scope-cn-v2"

    old_pack = deepcopy(pack)
    old_pack["version"] = "2026.07.16"
    old_r01 = next(item for item in old_pack["standardClausePackages"] if item["sourceRuleId"] == "R01")
    old_r01["requiredEvidence"] = ["previous-r01-evidence"]
    state: dict = {}
    publish_standard_clause_release(state, old_pack)
    project = {"id": "P-OLD", "businessPackId": old_pack["id"],
               "businessPackVersion": "2026.07.16", "updatedAt": "2026-09-22"}
    bind_project_node_clause_packages(state, project, old_pack)
    old_project_package = resolve_project_node_clause_package(state, "P-OLD", 1)
    old_release = deepcopy([row for row in state["standard_clause_packages_db"]
                            if row["releaseId"] == "engineering_inspection_v1@2026.07.16"])
    publish_standard_clause_release(state, pack)
    assert [row for row in state["standard_clause_packages_db"]
            if row["releaseId"] == "engineering_inspection_v1@2026.07.16"] == old_release
    assert len({row["releaseId"] for row in state["standard_clause_packages_db"]}) == 2
    assert project["businessPackVersion"] == "2026.07.16"
    assert resolve_project_node_clause_package(state, "P-OLD", 1) == old_project_package


def test_设计证照范围不覆盖时仍判失败_非设计证不套设计规则():
    base = {"referenceDate": "2026-09-23", "requiredScopes": ["GC2"],
            "certificates": [{"certificateNo": "TS-1", "validUntil": "2028-01-01", "scopes": ["GB1"]}]}
    assert check_certificate_validity({**base, "certificateType": "design_license"})["result"] == "failed"
    other = {**base, "certificateType": "ndt_personnel_certificate"}
    other["certificates"] = [{**base["certificates"][0], "scopes": ["GC1"]}]
    assert check_certificate_validity(other)["result"] == "failed"


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


def test_证书证据登记为证据链后守卫放行引用():
    from libs.review_grounding import apply_grounding_guardrails
    from libs.review_orchestrator.certificate_facts import attach_certificate_evidence

    verification = {
        "result": "passed",
        "certificates": [
            {
                "certificateNo": "TS1844171-2028",
                "holder": "广东政和工程有限公司",
                "validUntil": "2028-01-17",
                "scopes": ["GC1"],
                "checks": [{"code": "x", "passed": True, "actual": "2028-01-17", "expected": "2026-09-03"}],
                "evidenceRefs": [
                    {"documentVersionId": "DV-1", "fileName": "设计资质.png", "pageNo": 1, "bbox": [1, 2, 3, 4], "quotedText": "有效期至：2028年1月17日"}
                ],
            }
        ],
    }
    context = {
        "certificateVerification": verification,
        "evidenceLinks": [],
        "groundingInput": {"documentVersionIds": ["DV-1"], "groundingStatus": "grounded", "evidenceLinks": [], "evidenceTextCorpus": ["压力管道设计许可证 有效期至：2028年1月17日 核验"], "fields": [], "tables": [], "seals": [], "fragments": []},
    }
    attach_certificate_evidence(context)
    assert context["evidenceLinks"][0]["id"] == "EVL-CERT-1-1"
    assert verification["certificates"][0]["evidenceRefs"][0]["evidenceLinkId"] == "EVL-CERT-1-1"
    assert "2028-01-17" in context["groundingInput"]["evidenceTextCorpus"]

    draft = {
        "findingType": "design_license_validity_period",
        "severity": "low",
        "title": "设计许可证有效期覆盖",
        "description": "许可证 TS1844171-2028 有效期至 2028-01-17，核验通过。",
        "evidenceRefs": [{"evidenceLinkId": "EVL-CERT-1-1", "documentVersionId": "DV-1", "pageNo": 1, "quotedText": "有效期至：2028年1月17日"}],
        "ruleRefs": [],
        "kbRefs": [],
        "confidence": 0.8,
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
    }
    [result] = apply_grounding_guardrails([draft], context["groundingInput"])
    assert result["groundingStatus"] == "grounded", result
    assert result["evidenceLinkIds"] == ["EVL-CERT-1-1"]


def test_被分类成制造许可证的安装许可证按正文归入安装单位节点():
    """测试项目3 节点 2：江苏三江「特种设备生产许可证」写着「获准从事下列压力管道的安装」，
    词典把它分成 manufacturing_license，安装单位许可证 profile 原来直接拒收。"""
    state = {
        "projects": [{"id": "P-1", "constructionOrgName": "江苏三江机电工程有限公司"}],
        "documents": [
            {"id": "DOC-INS", "projectId": "P-1", "fileName": "江苏三江压力管道资质.jpg", "materialTypeCode": "manufacturing_license", "currentVersionId": "DV-INS"},
        ],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-INS",
                "status": "success",
                "profileId": "qualification_certificate_v1",
                "fields": [
                    {"fieldCode": "certificate_no", "fieldName": "编号", "fieldValue": "TS3832083-2026", "pageNo": 1},
                    {"fieldCode": "organization_name", "fieldName": "单位名称", "fieldValue": "江苏三江机电工程有限公司", "pageNo": 1},
                    {"fieldCode": "license_scope", "fieldName": "许可范围", "fieldValue": "公用管道安装(GB2)；工业管道安装(GC2)", "pageNo": 1},
                    {"fieldCode": "valid_until", "fieldName": "有效期至", "fieldValue": "2026年12月25日", "pageNo": 1},
                ],
                "fragments": [{"pageNo": 1, "text": "中华人民共和国 特种设备生产许可证 编号：TS3832083-2026 单位名称：江苏三江机电工程有限公司 经审查，获准从事下列压力管道的安装： 承压类特种设备安装、修理、改造 工业管道安装(GC2) 发证机关：江苏省市场监督管理局 有效期至：2026年12月25日"}],
            }
        ],
    }
    facts = build_certificate_facts(state, "P-1", 2, ["DV-INS"])
    certs = facts["certificateFacts"]["certificates"]
    assert len(certs) == 1 and certs[0]["certificateNo"] == "TS3832083-2026"
    assert certs[0]["validUntil"] == "2026-12-25" and certs[0]["holder"] == "江苏三江机电工程有限公司"
    # 设计单位节点不会误收：正文没有「设计」类标记
    assert build_certificate_facts(state, "P-1", 1, ["DV-INS"])["certificateFacts"]["certificates"] == []


def test_certificate_scope_rejects_foreign_documents_and_empty_inputs():
    from copy import deepcopy

    state = _state_with_design_license()
    foreign = deepcopy(state["ocr_parse_results"][0])
    foreign["documentVersionId"] = "FOREIGN"
    state["ocr_parse_results"].append(foreign)
    state["documents"].append({"id": "OTHER", "projectId": "OTHER", "currentVersionId": "FOREIGN"})
    assert build_certificate_facts(state, "P-1", 1, [])["certificateFacts"]["certificates"] == []
    assert build_certificate_facts(state, "P-1", 1, ["FOREIGN"])["certificateFacts"]["certificates"] == []


def test_certificate_merge_honors_frozen_sources_and_human_corrections():
    import pytest

    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator.certificate_facts import merge_certificate_facts

    state = _state_with_design_license()
    run = {"projectId": "P-1", "nodeId": 1, "inputDocumentVersionIds": ["DV-1"]}
    state["fact_corrections"] = [{"id": "C", "projectId": "P-1", "nodeId": 1, "documentVersionId": "DV-1",
        "fieldId": "F", "fieldName": "许可证编号", "correctedValue": "CORRECTED", "status": "active"}]
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    result = merge_certificate_facts(state, run, {})
    assert result["certificateFacts"]["certificates"][0]["certificateNo"] == "CORRECTED"
    state["fact_corrections"][0]["correctedValue"] = "CHANGED"
    with pytest.raises(ValueError, match="sources_changed"):
        merge_certificate_facts(state, run, {})



def test_frozen_empty_certificate_merge_clears_previous_certificates_without_mutating_input():
    from copy import deepcopy

    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator.certificate_facts import merge_certificate_facts

    state = _state_with_design_license()
    old = build_certificate_facts(state, "P-1", 1, ["DV-1"])
    original = deepcopy(old)
    run = {"projectId": "P-1", "nodeId": 1, "inputDocumentVersionIds": []}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    result = merge_certificate_facts(state, run, old)
    assert result["certificateFacts"]["certificates"] == []
    namespace = certificate_profile_for_node(1)["legacyNamespace"]
    assert result[namespace]["certificateNo"] is None
    assert result[namespace]["certificates"] == []
    assert old == original
