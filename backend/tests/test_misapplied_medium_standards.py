"""引用了只适用于别种介质的标准（ECD202：氢用管道标准 GB/T 20801.5-2025 当甲醇管道的检验、试压依据）。"""
from __future__ import annotations

from libs.review_orchestrator.design_facts import misapplied_medium_standards
from libs.review_tools.business_tools import evaluate_design_special_requirements

REF = "STD-GBT-20801.5-2025"


def test_介质都读得出且都不是氢_判引用对象不符():
    found = misapplied_medium_standards([REF, "STD-GBT-20801.1-2025"], [{"medium": "甲醇"}, {"medium": "正庚烷"}])
    assert found == [{"standardRef": REF, "title": "压力管道规范 工业管道 第5部分：氢用管道", "requiredMedium": "氢",
                      "projectMedia": ["正庚烷", "甲醇"]}]


def test_有氢气管线或介质读不出_不下结论():
    assert misapplied_medium_standards([REF], [{"medium": "甲醇"}, {"medium": "氢气"}]) == []
    assert misapplied_medium_standards([REF], [{"medium": "甲醇"}, {"medium": None}]) == []
    assert misapplied_medium_standards([REF], []) == []


def test_氢氧化钠和氯化氢不是氢():
    assert misapplied_medium_standards([REF], [{"medium": "氢氧化钠溶液"}, {"medium": "氯化氢"}])


def test_行间冲突置空的介质按冲突各方的值判():
    conflicted = {"medium": None, "fieldConflicts": [{"field": "medium", "sources": [{"value": "甲苯"}, {"value": "乙酸异丙酯"}]}]}
    assert misapplied_medium_standards([REF], [{"medium": "甲醇"}, conflicted])[0]["projectMedia"] == ["乙酸异丙酯", "甲苯", "甲醇"]


def test_2020版第5部分是检验与试验_不算():
    assert misapplied_medium_standards(["STD-GBT-20801.5-2020"], [{"medium": "甲醇"}]) == []


def test_工具把引用对象不符判为不符合():
    domain = {"specified": True, "requirements": {"method": "RT"}, "standardRefs": [REF]}
    output = evaluate_design_special_requirements({
        "requirements": {"ndt": domain}, "domains": ["ndt"],
        "requiredPathsByDomain": {"ndt": ["requirements.method"]},
        "standardRules": {"ndt": [{"code": "method", "actualPath": "requirements.method", "standardRef": REF, "operator": "present"}]},
        "misappliedStandards": misapplied_medium_standards([REF], [{"medium": "甲醇"}]),
    })
    assert output["result"] == "failed"
    item = next(check for check in output["checks"] if check["code"] == "standard_scope_matches_project_medium")
    assert item["passed"] is False and item["actual"][0]["projectMedia"] == ["甲醇"]
