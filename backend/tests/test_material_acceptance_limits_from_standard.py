"""设计项没带验收限值时，按「执行标准 + 材料牌号」从法规数值表推导。

2026-09-07 线上审计前这一步没人做：R16 的数值比对要求调用方把 acceptanceLimits 传进来，
传不进来就返回 evidence_insufficient——于是质保书上的实测值再离谱也只会被判成"证据不足"。
"""

from __future__ import annotations

from libs.review_orchestrator.material_facts import _enrich_material_design_item
from libs.review_tools.r16_tools import evaluate_r16_quality_certificate_results


def test_limits_derived_from_standard_and_grade():
    item = _enrich_material_design_item({"standardRef": "GB/T 8163-2018", "materialGrade": "20"})
    by_code = {limit["itemCode"]: limit for limit in item["acceptanceLimits"]}
    assert by_code["tensileStrength"]["minimum"] == 410.0
    assert by_code["tensileStrength"]["maximum"] == 530.0
    assert by_code["yieldStrength"]["minimum"] == 245
    assert by_code["elongation"]["minimum"] == 20
    assert item["acceptanceLimitsSource"]["standard"] == "GB/T 8163-2018"
    assert item["acceptanceLimitsSource"]["derivedFrom"] == "regulatory_tables.pipeMaterialLimits"


def test_quality_level_picks_the_right_row():
    """Q345 分 A~E 级，限值随等级变——冲击温度与能量只有 B 级以上才有。"""
    b = _enrich_material_design_item({"standardRef": "GB/T 8163-2018", "materialGrade": "Q345", "qualityLevel": "B"})
    codes = {limit["itemCode"]: limit for limit in b["acceptanceLimits"]}
    assert codes["tensileStrength"]["minimum"] == 470.0 and codes["yieldStrength"]["minimum"] == 345
    assert codes["impactEnergy"]["minimum"] == 34
    e = _enrich_material_design_item({"standardRef": "GB/T 8163-2018", "materialGrade": "Q345", "qualityLevel": "E"})
    assert {limit["itemCode"]: limit for limit in e["acceptanceLimits"]}["impactEnergy"]["minimum"] == 27


def test_manual_limits_win_and_unknown_standard_adds_nothing():
    manual = _enrich_material_design_item(
        {"standardRef": "GB/T 8163-2018", "materialGrade": "20", "acceptanceLimits": [{"itemCode": "x", "minimum": 1}]}
    )
    assert manual["acceptanceLimits"] == [{"itemCode": "x", "minimum": 1}], "人工填的优先"
    assert "acceptanceLimitsSource" not in manual

    unknown = _enrich_material_design_item({"standardRef": "GB/T 9999-2099", "materialGrade": "20"})
    assert "acceptanceLimits" not in unknown, "查不到标准就什么都不填，不猜"
    assert "acceptanceLimits" not in _enrich_material_design_item({"materialGrade": "20"})


def test_certificate_below_limit_is_now_judged_not_evidence_insufficient():
    """端到端：以前只能报证据不足，现在能判不符合。"""
    item = _enrich_material_design_item(
        {"componentItemId": "C1", "productName": "无缝钢管", "standardRef": "GB/T 8163-2018",
         "materialGrade": "20", "requiredQuantitativeItems": ["tensileStrength"]}
    )
    certificate = {
        "certificateNo": "ZL-001", "productName": "无缝钢管", "materialGrade": "20",
        "standardRef": "GB/T 8163-2018",
        "testResults": [{"itemCode": "tensileStrength", "value": 380}],  # 低于下限 410
    }
    outcome = evaluate_r16_quality_certificate_results({"designItems": [item], "qualityCertificates": [certificate]})
    assert outcome["result"] == "failed", outcome
