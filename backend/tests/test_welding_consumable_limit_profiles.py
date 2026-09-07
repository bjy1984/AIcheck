"""R26 焊材证明书的限值档案从法规表生成。

2026-09-07 线上审计前，evaluate_welding_consumable 拿不到 productStandardProfiles，
成分与力学每一项都报 product_standard_limit_profile_missing，整条判定只能停在证据不足——
而限值其实已经在 regulatory_tables 里。
"""

from __future__ import annotations

from libs.regulatory_tables import (
    welding_consumable_profile_for,
    welding_consumable_standard_profiles,
)
from libs.review_orchestrator.r24_r34_facts import _consumable_profiles_by_designation
from libs.review_tools.r24_r34_tools import evaluate_welding_consumable


def test_profiles_are_generated_per_designation_not_per_standard():
    profiles = welding_consumable_standard_profiles()
    assert {p["standard"] for p in profiles.values()} == {"GB/T 5117-2012", "GB/T 8110-2020"}
    designations = set(profiles["gbt51172012"]["byDesignation"])
    assert {"E4303", "E5015", "E5016", "E4315"} == designations

    e5015 = welding_consumable_profile_for("GB/T 5117-2012", "E5015")
    assert e5015["mechanicalProperties"]["tensileStrength"] == {"min": 490.0}
    assert e5015["chemicalComposition"]["Mn"] == {"max": 1.6}
    assert e5015["impactTemperatureC"] == -30
    # 商品牌号也能查到
    assert welding_consumable_profile_for("GB/T 5117-2012", "J507")["designation"] == "E5015"
    assert welding_consumable_profile_for("GB/T 9999-2099", "E4303") is None


def test_bare_standard_key_removed_when_a_standard_has_several_designations():
    """E4303 与 E5015 的抗拉强度差 60MPa——只按标准号取档案会把合格的判成不合格。"""
    keyed = _consumable_profiles_by_designation()
    assert "gbt51172012" not in keyed, "GB/T 5117-2012 有四个型号，裸标准键必须剔除"
    assert "gbt81102020" in keyed, "GB/T 8110-2020 只有一个型号，裸标准键可保留"
    assert keyed["gbt51172012e5015"]["mechanicalProperties"]["tensileStrength"] == {"min": 490.0}
    assert keyed["j507"]["designation"] == "E5015"


def test_out_of_range_consumable_is_now_judged():
    """端到端：焊条抗拉强度低于标准下限，现在能判不符合。"""
    profiles = _consumable_profiles_by_designation()
    certificate = {
        "certificateNo": "HC-1", "designation": "E5015", "brand": "J507",
        "standardRef": "GB/T 5117-2012 E5015",
        "batchNo": "B1", "originalSeen": True, "conclusion": "合格",
        "chemicalComposition": [{"element": "C", "value": 0.12}, {"element": "Mn", "value": 1.2},
                                {"element": "Si", "value": 0.5}, {"element": "P", "value": 0.02},
                                {"element": "S", "value": 0.02}, {"element": "Ni", "value": 0.1},
                                {"element": "Cr", "value": 0.1}, {"element": "Mo", "value": 0.1},
                                {"element": "V", "value": 0.01}],
        "mechanicalProperties": [{"element": "tensileStrength", "value": 430},  # 低于 490
                                 {"element": "yieldStrength", "value": 410},
                                 {"element": "elongation", "value": 22},
                                 {"element": "impactEnergy", "value": 40}],
    }
    outcome = evaluate_welding_consumable({
        "qualityCertificates": [certificate],
        "designRequirements": [{"itemId": "R1", "designation": "E5015", "standardRef": "GB/T 5117-2012 E5015"}],
        "physicalItems": [{"batchNo": "B1"}],
        "productStandardProfiles": profiles,
    })
    matrix = outcome["facts"]["consumableCertificateMatrix"]
    reasons = " ".join(str(row.get("reasonCodes")) for row in matrix)
    assert "product_standard_limit_profile_missing" not in reasons, "档案已提供，不该再报缺档案"
    assert "tensileStrength_out_of_range" in reasons
    assert outcome["result"] == "failed", outcome
