"""施工記錄的適用性（2026-09-24 業務確認）與「未抽取」守門。"""
from __future__ import annotations

from copy import deepcopy

import pytest

from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.record_applicability import apply_record_applicability
from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains
from libs.review_tools.installation_domain_rules import evaluate_r47_static_grounding
from libs.review_tools.r68_blowing_cleaning import evaluate_r68_blowing_cleaning
from libs.table_schema_mapping import map_row
from tests.test_form_tables import BLOWING_PAGE, GROUNDING_PAGE, _signature


def _facts(node, page, selected):
    state = {"documents": [{"id": "D", "projectId": "P", "tenantId": "T", "fileName": "交工资料.pdf"}],
             "versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
             "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "tenantId": "T", "status": "success",
                                    "fragments": page, "tables": []}]}
    run = {"projectId": "P", "tenantId": "T", "nodeId": node, "reviewMode": "formal",
           "inputDocumentVersionIds": ["V"], "reviewRunId": "RUN", "selectedObjectIds": [selected]}
    return NDT_FACT_BUILDERS[node](state, run)


def _results(tool, block):
    output = tool({"projectId": "P", **{key: block[key] for key in ("scope", "standardRules", "domains",
                                                                     "selectionIssues")}})
    return {row["code"]: row["result"] for row in output["facts"]["processChecks"]}


def test_a_blowing_record_is_applicable_and_reads_only_the_branches_its_medium_names():
    block = _facts(68, BLOWING_PAGE, "PL8303-100")["r68"]["blowingCleaning"]
    domain = block["domains"][0]
    assert domain["applicable"] is True
    assert domain["medium"] == {"name": "洁净水", "waterFlush": True, "airBlowing": False,
                                "steamBlowing": False, "chemicalCleaning": False}
    results = _results(evaluate_r68_blowing_cleaning, block)
    assert "failed" not in results.values(), "抽取缺口不能变成不符合"
    # 方案编号、方法要从吹扫方案抽，记录表上本来没有：未抽取，交人工。
    assert results["blowingcleaning_plan_documentno_not_extracted"] == "evidence_insufficient"
    assert results["blowingcleaning_medium_name"] == results["blowingcleaning_acceptance_conclusion"] == "passed"
    assert results["blowingcleaning_air_pressure_not_exceeding_design"] == "not_applicable"
    assert results["blowingcleaning_steam_heat_cool_reheat_cycle"] == "not_applicable"
    assert results["blowingcleaning_chemical_waste_disposal_compliant"] == "not_applicable"
    assert results["blowingcleaning_water_drained_after_flush"] == "evidence_insufficient"


def _domains_spec():
    return {"domains": {"d": {"requiredPaths": ["a.written", "b.elsewhere"], "checks": []}}}


def _evaluate(row):
    scope = {"projectId": "P", "objectType": "pipeline", "objectId": "L1", "recordVersionId": "V"}
    ref = {"documentVersionId": "V", "pageNo": 1, "quotedText": "L1"}
    return {item["code"]: item["result"] for item in evaluate_frozen_domains(
        "t", {"projectId": "P", "scope": scope, "standardRules": _domains_spec(),
              "domains": [{**scope, "domain": "d", "applicable": True, "evidenceRefs": [ref], **row}]},
        rule_version="v", scope_fields=tuple(scope), version_field="recordVersionId",
        code_prefix="t")["facts"]["processChecks"]}


def test_a_required_field_the_record_could_carry_but_does_not_still_fails():
    results = _evaluate({"extractedPaths": ["a.written"]})
    assert results == {"d_a_written": "failed", "d_b_elsewhere_not_extracted": "evidence_insufficient"}


def test_sources_that_do_not_declare_extracted_paths_keep_the_original_rule():
    assert _evaluate({}) == {"d_a_written": "failed", "d_b_elsewhere": "failed"}


def _pipeline_facts(node, **pipeline):
    page = GROUNDING_PAGE
    facts = deepcopy(_facts(node, page, "PL8303-100")) if node == 47 else {
        "r66": {"leakTestConditions": {"domains": [{"objectId": "PL8303-100", "domain": "leakTestConditions"}]}},
        "r67": {"leakTestMethod": {"domains": [{"objectId": "PL8303-100", "domain": "leakTestMethod"}]}}}
    facts["project"] = {"pipelines": [{"pipelineId": "PL8303-100", "source": {"fileName": "设计说明.pdf", "pageNo": 3},
                                       **pipeline}]}
    return apply_record_applicability(facts)


@pytest.mark.parametrize(("pipeline", "reason"), [
    ({"mediumToxicity": "中度危害"}, "medium_toxic"),
    ({"leakHazard": "泄漏危害性"}, "medium_leak_hazard"),
])
def test_leak_tests_apply_when_the_design_names_a_toxic_or_leak_hazard_medium(pipeline, reason):
    facts = _pipeline_facts(66, **pipeline)
    for namespace, key in (("r66", "leakTestConditions"), ("r67", "leakTestMethod")):
        domain = facts[namespace][key]["domains"][0]
        assert domain["applicable"] is True
        assert domain["applicabilityBasis"]["reason"] == reason
        assert domain["applicabilityBasis"]["source"] == {"fileName": "设计说明.pdf", "pageNo": 3}


@pytest.mark.parametrize("pipeline", [{"medium": "天然气"}, {"mediumToxicity": "无毒", "leakHazard": "无"}, {}])
def test_a_medium_name_or_a_negative_is_never_turned_into_applicability(pipeline):
    domain = _pipeline_facts(66, **pipeline)["r66"]["leakTestConditions"]["domains"][0]
    assert "applicable" not in domain, "判不了维持证据不足，也不宣告不适用"


def test_static_grounding_applies_to_a_flammable_class_medium_and_missing_fields_are_not_failures():
    facts = _pipeline_facts(47, fireHazard="甲B")
    block = facts["r47"]["staticGrounding"]
    assert block["domains"][0]["applicable"] is True
    results = _results(evaluate_r47_static_grounding, block)
    assert "failed" not in results.values()
    assert results["staticgrounding_installation_groundinglocation_not_extracted"] == "evidence_insufficient"
    assert results["staticgrounding_measurement_groundresistanceohm"] == "passed"


def test_a_pipeline_that_does_not_match_the_record_gives_no_applicability():
    facts = _pipeline_facts(66, mediumToxicity="高度危害")
    facts["project"]["pipelines"][0]["pipelineId"] = "PL9999-100"
    for domain in facts["r66"]["leakTestConditions"]["domains"]:
        domain.pop("applicable", None)
    assert "applicable" not in apply_record_applicability(facts)["r66"]["leakTestConditions"]["domains"][0]


@pytest.mark.parametrize(("value", "expected"), [("洁净水", True), ("空气", False), ("/", None), ("", None)])
def test_keyword_flags_come_only_from_what_the_cell_says(value, expected):
    mapped = map_row({"吹洗介质": value}, _signature("blowing_cleaning_domains"))
    assert (mapped.get("medium") or {}).get("waterFlush") == expected


@pytest.mark.parametrize(("value", "expected"), [("酸洗液", True), ("/", False), ("", None)])
def test_a_slash_in_the_chemical_cleaning_column_means_not_done(value, expected):
    mapped = map_row({"化学清洗介质": value}, _signature("blowing_cleaning_domains"))
    assert (mapped.get("medium") or {}).get("chemicalCleaning") == expected


@pytest.mark.parametrize(("record", "design", "specification", "matched"), [
    ("PL8303-100", "PL8303", "100", True),       # 去掉公称直径后对上，公称直径一致
    ("PL8303-100", "PL8303", "DN100", True),
    ("PL8303-100", "PL8303", None, True),        # 设计没写公称直径：按确认的口径去掉再比
    ("PL8303-100", "PL8303", "Φ108X8", True),   # 外径×壁厚不是公称直径，不拿来挡
    ("PL8303-100", "PL8303", "150", False),      # 公称直径不同：不是同一条
    ("PL8303-100", "PL8306", "100", False),
    ("PL8303-100", "PL8303-100", "100", True),   # 原样对得上就直接用
])
def test_a_record_line_number_with_its_nominal_diameter_matches_the_design_line(record, design, specification, matched):
    facts = {"r66": {"leakTestConditions": {"domains": [{"objectId": record, "domain": "leakTestConditions"}]}},
             "project": {"pipelines": [{"pipelineId": design, "specification": specification,
                                        "mediumToxicity": "中度危害", "source": {"pageNo": 4}}]}}
    domain = apply_record_applicability(facts)["r66"]["leakTestConditions"]["domains"][0]
    assert (domain.get("applicable") is True) is matched
    if matched:
        assert domain["applicabilityBasis"]["pipelineId"] == design


@pytest.mark.parametrize(("pipeline", "domains", "reason"), [
    ({"leakTestRequired": True}, (("r66", "leakTestConditions"), ("r67", "leakTestMethod")), "design_leak_test_required"),
    ({"mediumProperty": "有毒"}, (("r66", "leakTestConditions"),), "medium_toxic"),
    ({"mediumProperty": "可燃"}, (("r47", "staticGrounding"),), "medium_flammable"),
])
def test_the_design_table_columns_decide_applicability(pipeline, domains, reason):
    facts = {namespace: {key: {"domains": [{"objectId": "A01-PL-02", "domain": key}]}} for namespace, key in domains}
    facts["project"] = {"pipelines": [{"pipelineId": "A01-PL-02", "source": {"pageNo": 32}, **pipeline}]}
    for namespace, key in domains:
        domain = apply_record_applicability(facts)[namespace][key]["domains"][0]
        assert domain["applicable"] is True and domain["applicabilityBasis"]["reason"] == reason


@pytest.mark.parametrize("pipeline", [{"leakTestRequired": False}, {"mediumProperty": "腐蚀"}, {"leakTestRequired": None}])
def test_a_design_that_does_not_require_it_still_never_declares_not_applicable(pipeline):
    facts = {"r66": {"leakTestConditions": {"domains": [{"objectId": "A01-PL-02", "domain": "leakTestConditions"}]}},
             "project": {"pipelines": [{"pipelineId": "A01-PL-02", **pipeline}]}}
    assert "applicable" not in apply_record_applicability(facts)["r66"]["leakTestConditions"]["domains"][0]
