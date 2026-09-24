"""R47／R68 等施工記錄（選定對象後）抽出的值，也請 Jev 對原文核一遍；推導的旗標不問。"""
from __future__ import annotations

from libs.review_orchestrator.jev_fact_check import domain_record_fact_items
from tests.test_form_tables import BLOWING_PAGE, GROUNDING_PAGE
from tests.test_record_applicability import _facts

RULES = [{"atomicCheckResults": [{"atomicCheckId": "AC-R47-01",
                                  "toolResults": [{"toolName": "evaluate_r47_static_grounding"}]}]}]


def test_grounding_record_values_become_questions_about_the_selected_pipeline():
    items = domain_record_fact_items(_facts(47, GROUNDING_PAGE, "PL8306-100"), RULES)
    by_field = {item["field"]: item for item in items}
    assert set(by_field) == {"installation.connectionMethod", "measurement.maxJointBondingResistanceOhm",
                             "measurement.groundResistanceOhm"}
    resistance = by_field["measurement.maxJointBondingResistanceOhm"]
    assert resistance["value"] == "0.019" and resistance["documentVersionIds"] == ["V"]
    assert resistance["atomicCheckId"] == "AC-R47-01"
    assert resistance["instructions"].startswith("只看这份资料：管线PL8306-100的跨线接头电阻值是否写为0.019？")


def test_flags_derived_from_the_record_are_not_asked():
    items = domain_record_fact_items(_facts(68, BLOWING_PAGE, "PL8303-100"), RULES)
    assert sorted(item["field"] for item in items) == ["acceptance.conclusion", "medium.name"]
    assert {item["value"] for item in items} == {"洁净水", "合格"}


def test_nothing_is_asked_before_an_object_is_chosen_or_without_a_rule_check():
    unselected = _facts(47, GROUNDING_PAGE, "PL8306-100")
    unselected["r47"]["staticGrounding"]["domains"] = []  # 两条管线未选定时构建器不给 domains
    assert domain_record_fact_items(unselected, RULES) == []
    assert domain_record_fact_items(_facts(47, GROUNDING_PAGE, "PL8306-100"), []) == []


def test_coating_and_support_records_are_asked_by_their_own_column_and_object():
    from tests.test_support_and_installation_records import COATING_PAGE, SUPPORT_PAGE, _run

    coating = domain_record_fact_items(_run(44, COATING_PAGE, "PL8306-100"), RULES)
    assert [(item["field"], item["value"]) for item in coating] == [("coating.coatingType", "丙烯酸聚氨脂面漆")]
    support = domain_record_fact_items(_run(55, SUPPORT_PAGE, "PL8306/PS-1"), RULES)
    assert [(item["field"], item["value"]) for item in support] == [("support.type", "G1,T形支架，BL.2.1m")]
    assert support[0]["instructions"].startswith("只看这份资料：支架PL8306/PS-1的结构型式、型号、规格是否写为")
