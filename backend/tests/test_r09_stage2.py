"""R09 第二阶段：规则按审查日期选标准、没抽到的值算证据不足，再把四个专项领域登记成带页码引文的事实。

GDLNG 节点 9（2021 年的工程，照片 OCR）：规则要求设计引用 2025 版的 GB/T 20801.1，设计不可能引用，
又有一堆「值是空的」，15 项不过项全是假的；标准答案是证据不足。"""
from __future__ import annotations

from libs.review_orchestrator.design_facts import build_design_business_facts
from libs.review_orchestrator.design_judgment import special_requirement_judgment
from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_tools.business_tools import (
    evaluate_design_special_requirements,
    standard_code_from_id,
    standard_not_yet_effective,
)
from libs.review_tools.executor import build_tool_arguments

GBT_2025 = "STD-GBT-20801.1-2025"
PATHS = {"ndt": ["requirements.method", "requirements.coverage"], "corrosion": ["requirements.protectionMethod"],
         "pressureTest": ["requirements.method"], "leakTest": ["requirements.method"]}


def rules(standard_ref: str = GBT_2025) -> dict:
    return {
        "ndt": {"checks": [{"code": "coverage_specified", "actualPath": "requirements.coverage", "operator": "present", "standardRef": standard_ref},
                           {"code": "coverage_ok", "actualPath": "requirements.coverageOk", "operator": "equals", "expected": True, "standardRef": standard_ref}]},
        "corrosion": {"checks": [{"code": "method_specified", "actualPath": "requirements.protectionMethod", "operator": "present", "standardRef": standard_ref}]},
        "pressureTest": {"checks": [{"code": "method_specified", "actualPath": "requirements.method", "operator": "present", "standardRef": standard_ref}]},
        "leakTest": {"checks": [{"code": "method_specified", "actualPath": "requirements.method", "operator": "present", "standardRef": standard_ref}]},
    }


def domains(*, refs: list[str], coverage=None) -> dict:
    base = {"specified": True, "standardRefs": refs}
    return {
        "ndt": {**base, "requirements": {"method": "RT", "coverage": coverage, "coverageOk": True if coverage else None}},
        "corrosion": {**base, "requirements": {"protectionMethod": "环氧"}},
        "pressureTest": {**base, "requirements": {"method": "水压"}},
        "leakTest": {**base, "requirements": {"method": "泄漏性试验"}},
    }


def run(requirements: dict, review_date: str | None, standard_rules: dict | None = None) -> dict:
    return evaluate_design_special_requirements({
        "requirements": requirements, "standardRules": standard_rules or rules(), "requiredPathsByDomain": PATHS,
        "domains": ["ndt", "corrosion", "pressureTest", "leakTest"], **({"reviewDate": review_date} if review_date else {})})


def test_standard_id_maps_to_its_code_and_the_timeline_decides_if_it_is_in_force():
    assert standard_code_from_id("STD-GBT-20801.1-2025") == "GB/T 20801.1-2025"
    assert standard_code_from_id("STD-TSG-31-2025") == "TSG 31-2025"
    assert standard_code_from_id("STD-GB-50236") == "GB 50236"
    assert standard_code_from_id("STD-LEAK") is None
    assert standard_not_yet_effective("STD-GBT-20801.1-2025", "2021-03-24") is True
    assert standard_not_yet_effective("STD-GBT-20801.1-2025", "2026-09-06") is False
    assert standard_not_yet_effective("STD-LEAK", "2021-03-24") is False, "查不到的按现行，保持原有口径"
    assert standard_not_yet_effective("STD-GB-50236-1899", "2021-03-24") is False


def test_rules_of_a_standard_not_yet_in_force_are_skipped_when_the_design_does_not_cite_it():
    out = run(domains(refs=["STD-GB-50235-2010"], coverage="10%"), "2021-03-24")
    by_domain = {item["domain"]: item for item in out["domainResults"]}
    assert out["result"] == "passed"
    assert all(item["violations"] == [] for item in by_domain.values()), "2021 年的设计不会引用 2025 版标准"
    assert by_domain["ndt"]["notApplicableRules"] == ["coverage_specified", "coverage_ok"]


def test_the_same_rules_apply_once_the_standard_is_in_force_or_the_design_cites_it():
    in_force = run(domains(refs=["STD-GB-50235-2010"], coverage="10%"), "2026-09-06")
    assert in_force["result"] == "failed"
    assert "standard_not_referenced:" + GBT_2025 in in_force["domainResults"][0]["violations"]

    cited_early = run(domains(refs=[GBT_2025], coverage="10%"), "2021-03-24")
    assert cited_early["result"] == "passed", "设计自己采用了新版，就按新版要求"
    assert cited_early["domainResults"][0]["notApplicableRules"] == []

    no_date = run(domains(refs=["STD-GB-50235-2010"], coverage="10%"), None)
    assert no_date["result"] == "failed", "没有审查日期就不判日期，沿用原口径"


def test_a_value_that_was_not_extracted_is_insufficient_evidence_not_a_violation():
    out = run(domains(refs=[GBT_2025], coverage=None), "2026-09-06")
    ndt = out["domainResults"][0]
    assert out["result"] == "evidence_insufficient"
    assert ndt["violations"] == [] and ndt["result"] == "evidence_insufficient"
    assert "coverage_specified" in ndt["unresolvedRules"]
    assert ndt["missingPaths"] == ["requirements.coverage"]
    missing = [item for item in out["checks"] if item.get("missing")]
    assert missing, "没抽到的项仍然列出来，让人看得见"


def test_a_present_value_that_violates_the_rule_still_fails():
    wrong = domains(refs=[GBT_2025], coverage="10%")
    wrong["ndt"]["requirements"]["coverageOk"] = False
    out = run(wrong, "2026-09-06")
    assert out["result"] == "failed" and out["domainResults"][0]["violations"] == ["coverage_ok"]


def test_not_specified_is_still_a_real_failure():
    unspecified = domains(refs=[GBT_2025], coverage="10%")
    unspecified["leakTest"]["specified"] = False
    out = run(unspecified, "2026-09-06")
    assert out["result"] == "failed" and out["domainResults"][3]["completenessResult"] == "failed"


def test_executor_hands_the_review_date_to_the_tool():
    facts = {"design": {"reviewDate": "2021-03-24"}, "designSpecialRequirements": {"domains": {}}, "fixedClauses": {"designSpecialRequirementRules": {}}}
    arguments = build_tool_arguments("evaluate_design_special_requirements", {"parameters": {}}, facts=facts, explicit={},
                                     document_version_ids=[], evidence_facts=[], evidence_refs=[])
    assert arguments["reviewDate"] == "2021-03-24"
    fallback = build_tool_arguments("evaluate_design_special_requirements", {"parameters": {}}, facts={"project": {"constructionStart": "2026-03-25"}},
                                    explicit={}, document_version_ids=[], evidence_facts=[], evidence_refs=[])
    assert fallback["reviewDate"] == "2026-03-25"


UNSCORED = {"reasons": ["provider_confidence_unavailable"]}


def parse(version_id: str, *pages: tuple[int, str]) -> dict:
    return {"documentVersionId": version_id, "status": "success", "quality": UNSCORED, "tables": [], "fields": [],
            "fragments": [{"pageNo": no, "text": text, "bbox": [0, 0, 1, 1], "confidence": 0.0} for no, text in pages]}


def test_requirement_facts_are_registered_per_specified_domain_with_page_and_quote():
    result = parse("V1", (3, "管道焊缝的射线检测应符合 NB/T 47013"), (8, "管道系统按设计压力 1.5 倍进行水压试验"), (9, "涂层：环氧底漆两遍"))
    judgment = special_requirement_judgment(
        {"V1": result}, {"V1": {"id": "D1", "fileName": "施工图.pdf"}},
        {"ndt": {"specified": True, "source": {"documentVersionIds": ["V1"]}}, "corrosion": {"specified": True},
         "pressureTest": {"specified": True}, "leakTest": {"specified": True}})
    facts = {fact["factId"]: fact for fact in judgment["claimedFacts"]}
    assert set(facts) == {"requirement-ndt", "requirement-corrosion", "requirement-pressureTest"}, "泄漏试验在文件里没有出现，不登记"
    refs = {ref["evidenceRefId"]: ref for ref in judgment["evidenceRefs"]}
    assert refs[facts["requirement-ndt"]["evidenceRefIds"][0]]["pageNo"] == 3
    assert refs[facts["requirement-pressureTest"]["evidenceRefIds"][0]]["pageNo"] == 8
    gate = validate_evidence_grounding({"facts": judgment["claimedFacts"], "evidenceRefs": judgment["evidenceRefs"]})
    assert gate["result"] == "human_review_required" and gate["facts"]["factCount"] == 3
    assert special_requirement_judgment({"V1": result}, {}, {"ndt": {"specified": False}})["claimedFacts"] == []


def test_only_nodes_8_and_9_get_a_judgment():
    state = {"documents": [{"id": "D-1", "projectId": "P-1", "currentVersionId": "V1", "fileName": "施工图.pdf", "materialTypeCode": "design_document"}],
             "versions": [], "ocr_parse_results": [parse("V1", (3, "设计依据 GB/T 8163-2018；无损检测按 NB/T 47013 射线检测 RT 10%；水压试验；泄漏性试验；防腐除锈"))]}
    nine = build_design_business_facts(state, {"projectId": "P-1", "nodeId": 9, "inputDocumentVersionIds": ["V1"]})
    five = build_design_business_facts(state, {"projectId": "P-1", "nodeId": 5, "inputDocumentVersionIds": ["V1"]})
    assert {fact["factId"] for fact in nine["judgment"]["claimedFacts"]} == {"requirement-ndt", "requirement-corrosion", "requirement-pressureTest", "requirement-leakTest"}
    assert "judgment" not in five
