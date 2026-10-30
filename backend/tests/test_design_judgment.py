"""节点 8 的标准引用登记成带页码和引文的事实：锚定门有东西可核，业务工具的不符合不再被盖成证据不足。

ECD202 储罐 8：check_standard_version_active 在线核出 GB/T 12771-2008 已废止（failed），
validate_evidence_grounding 因为 0 条事实回证据不足，整项被一票否决。"""
from __future__ import annotations

from libs import standard_online_lookup as online
from libs.business_pack import load_business_pack
from libs.review_orchestrator.design_facts import (
    build_design_business_facts,
    design_standard_references,
)
from libs.review_orchestrator.design_judgment import (
    locate_standard_codes,
    standard_reference_judgment,
)
from libs.review_orchestrator.deterministic_tools import validate_evidence_grounding
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

UNSCORED = {"reasons": ["provider_confidence_unavailable"]}


def parse(version_id: str, *pages: tuple[int, str], quality=None) -> dict:
    return {"documentVersionId": version_id, "status": "success", "quality": quality if quality is not None else UNSCORED,
            "tables": [], "fields": [],
            "fragments": [{"pageNo": no, "text": text, "bbox": [0, 0, 1, 1], "confidence": 0.0} for no, text in pages]}


def test_first_occurrence_page_and_quote_of_each_standard_code():
    found = locate_standard_codes(parse("V1", (3, "设计依据：GB/T 20801.1-2025 压力管道规范"), (18, "焊接钢管 GB/T 12771-2008 DN500-600；GB/T 20801.1-2025")))
    assert found["GB/T 20801.1-2025"]["pageNo"] == 3, "取第一处"
    assert found["GB/T 12771-2008"]["pageNo"] == 18 and "GB/T 12771-2008" in found["GB/T 12771-2008"]["quotedText"]


def test_codes_in_table_rows_are_found_when_the_table_has_a_page_and_skipped_when_it_has_none():
    result = parse("V1")
    result["tables"] = [{"pageNo": 34, "normalizedRows": [{"材料": "钢管", "标准": "GB/T 8163-2018"}]},
                        {"normalizedRows": [{"标准": "GB/T 14976-2025"}]}]
    found = locate_standard_codes(result)
    assert found["GB/T 8163-2018"]["pageNo"] == 34
    assert "GB/T 14976-2025" not in found, "没有页码的证据定位不了，不登记"


def test_judgment_registers_one_fact_per_code_with_unscored_confidence():
    judgment = standard_reference_judgment(
        {"V1": parse("V1", (3, "GB/T 20801.1-2025"), (18, "GB/T 12771-2008")), "V2": parse("V2", (3, "GB/T 20801.1-2025"))},
        {"V1": {"id": "D1", "fileName": "施工图.pdf"}, "V2": {"id": "D2", "fileName": "施工图-副本.pdf"}})
    assert sorted(fact["value"] for fact in judgment["claimedFacts"]) == ["GB/T 12771-2008", "GB/T 20801.1-2025"], "两份相同文件里的同一编号只登记一次"
    ref_ids = {ref["evidenceRefId"] for ref in judgment["evidenceRefs"]}
    for fact in judgment["claimedFacts"]:
        assert fact["confidenceUnavailable"] is True and fact["confidence"] is None and fact["conflicted"] is False
        assert set(fact["evidenceRefIds"]) <= ref_ids
    ref = judgment["evidenceRefs"][0]
    assert ref["pageNo"] and ref["quotedText"] and ref["fileName"] and ref["source"] == "ocr_text"


def test_gate_hands_unscored_facts_to_a_human_instead_of_failing():
    judgment = standard_reference_judgment({"V1": parse("V1", (18, "GB/T 12771-2008"))}, {"V1": {"id": "D1", "fileName": "施工图.pdf"}})
    gate = validate_evidence_grounding({"facts": judgment["claimedFacts"], "evidenceRefs": judgment["evidenceRefs"]})
    assert gate["result"] == "human_review_required" and gate["facts"]["factCount"] == 1
    scored = standard_reference_judgment({"V1": parse("V1", (18, "GB/T 12771-2008"), quality={"reasons": []})}, {"V1": {}})
    assert validate_evidence_grounding({"facts": scored["claimedFacts"], "evidenceRefs": scored["evidenceRefs"]})["result"] == "evidence_insufficient", \
        "有分但只有 0.0，照旧是置信度不够"


def test_only_node_8_gets_the_judgment():
    state = {"documents": [{"id": "D-1", "projectId": "P-1", "currentVersionId": "V1", "fileName": "施工图.pdf", "materialTypeCode": "design_document"}],
             "versions": [], "ocr_parse_results": [parse("V1", (3, "GB/T 20801.1-2025"))]}
    eight = build_design_business_facts(state, {"projectId": "P-1", "nodeId": 8, "inputDocumentVersionIds": ["V1"]})
    four = build_design_business_facts(state, {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": ["V1"]})
    assert eight["judgment"]["claimedFacts"] and "judgment" not in four


def run_r08_plan(monkeypatch, verdicts: dict):
    monkeypatch.setenv(online.ENABLE_ENV, "1")
    monkeypatch.setattr(online, "INTERVAL_SECONDS", 0)
    monkeypatch.setattr(online, "query_standard_status", lambda ref, review_date=None: verdicts[ref])
    online.clear_cache()
    texts = {"V1": "设计依据 GB/T 12771-2008、GB/T 8163-2018"}
    design = design_standard_references(texts, "2026-03-25")
    judgment = standard_reference_judgment({"V1": parse("V1", (18, texts["V1"]))}, {"V1": {"id": "D1", "fileName": "施工图.pdf"}})
    pack = load_business_pack("engineering_inspection_v1")
    plan = compile_node_tool_plan(pack, "R08", available_tools={item["name"] for item in runtime_tool_catalog()})
    return execute_node_tool_plan(
        plan, facts={"design": design, "project": {"constructionStart": "2026-03-25"}},
        tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args), document_version_ids=["V1"],
        evidence_facts=judgment["claimedFacts"], evidence_refs=judgment["evidenceRefs"])


def verdict(kind: str, code: str, withdrawn=None) -> dict:
    return {"verdict": kind, "reviewDate": "2026-03-25",
            "standardReferences": [{"standardRef": code, "status": "废止" if kind == "superseded" else "现行", "effectiveFrom": "2009-04-01", "withdrawnOn": withdrawn}]}


def test_withdrawn_standard_reaches_the_verdict_and_a_clean_set_goes_to_a_human(monkeypatch):
    output = run_r08_plan(monkeypatch, {"GB/T 12771-2008": verdict("superseded", "GB/T 12771-2008", "2020-09-01"),
                                        "GB/T 8163-2018": verdict("current", "GB/T 8163-2018")})
    results = {item["atomicCheckId"]: item["result"] for item in output["atomicResults"]}
    assert results["AC-R08-01"] == "failed", "官方平台核实的作废标准不再被盖成证据不足"
    assert results["AC-R08-02"] == "human_review_required", "证据位置齐全、只是引擎没给分：交人核对引文"

    clean = run_r08_plan(monkeypatch, {"GB/T 12771-2008": verdict("current", "GB/T 12771-2008"), "GB/T 8163-2018": verdict("current", "GB/T 8163-2018")})
    assert {item["atomicCheckId"]: item["result"] for item in clean["atomicResults"]}["AC-R08-01"] != "passed", "没有置信度时不冒充通过"
