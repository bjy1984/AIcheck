"""法规数值表：预填值可读、未核对的表标 verified=False；代码里的焊工覆盖常量与 TSG Z6002-2026 表 A-7/A-8 一致。"""

from __future__ import annotations

from decimal import Decimal

from libs.regulatory_tables import (
    inspection_level_for_grade,
    is_verified,
    pressure_test_ratios,
    table,
    volumetric_ndt_ratio,
    welder_material_category,
    wps_base_material_group,
)
from libs.review_orchestrator.deterministic_tools import decode_welder_code


def test_tables_load_with_verification_flags() -> None:
    assert is_verified(table("tsg31_2025", "designApproval")) is True
    assert is_verified(table("tsgZ6002_2026", "materialCategories")) is False, "OCR 预填，写入判定前须人工核对"
    assert table("tsg31_2025", "designApproval")["fourLevelTriggers"][0] == "GC1 级管道"


def test_material_lookups_are_case_and_hyphen_insensitive() -> None:
    assert welder_material_category("Q235B") == "FeⅠ"
    assert welder_material_category("12cr1mov") == "FeⅡ"
    assert welder_material_category("06Cr19Ni10") == "FeⅣ"
    assert welder_material_category("ZZZ") is None
    assert wps_base_material_group("20G") == "Fe-1-1" and wps_base_material_group("Q345R") == "Fe-1-2"
    assert wps_base_material_group("S31603") is None, "未抄到的牌号不猜"


def test_inspection_levels_and_ratios_follow_gbt20801_1_2025() -> None:
    """GB/T 20801.1-2025 8.3.1：GC1 整级为 Ⅰ 级（2020 版是"剧毒 GC1 才 Ⅰ 级"）；GC2 按介质细分。"""
    assert inspection_level_for_grade("GC1") == "Ⅰ"
    assert inspection_level_for_grade("GC1", toxic=True) == "Ⅰ", "GC1 无论介质都是 Ⅰ 级"
    assert inspection_level_for_grade("GC2") == "Ⅳ"
    assert inspection_level_for_grade("GC2", leak_hazard=True) == "Ⅱ"
    assert inspection_level_for_grade("GC2", toxic=True) == "Ⅲ"
    assert inspection_level_for_grade("GC3") == "Ⅴ"
    assert volumetric_ndt_ratio("Ⅰ") == 100 and volumetric_ndt_ratio("Ⅱ") == 20
    assert volumetric_ndt_ratio("Ⅳ") == 5 and volumetric_ndt_ratio("Ⅴ") == 0
    # 8.6.1.4 e)：气压试验有上限，超过 1.33 倍设计压力是不符合
    assert pressure_test_ratios() == {"hydro": 1.5, "pneumatic": 1.1, "pneumaticMax": 1.33}


def test_welder_code_decoder_matches_tables_a7_and_a8() -> None:
    thin = decode_welder_code("GTAW-FeⅡ-6G-3/57-FefS-02/11/12")
    assert thin["thicknessMax"] == Decimal(6) and thin["diameterMin"] == Decimal(25), "T<12 → 2T；25≤D<76 → 25"
    thick = decode_welder_code("SMAW-FeⅡ-6G-12/159-Fef3J")
    assert thick["thicknessMax"] is None and thick["diameterMin"] == Decimal(76), "T≥12 → 不限；D≥76 → 76"
    small = decode_welder_code("GTAW-FeⅠ-6G-2/20-FefS")
    assert small["diameterMin"] == Decimal(20), "D<25 → D"


def test_deterministic_category_lookup_reads_table_a2() -> None:
    from libs.review_orchestrator.deterministic_tools import material_category_for_grade

    assert material_category_for_grade("12Cr1MoV") == "FeII"
    assert material_category_for_grade("06Cr19Ni10") == "FeIV"
    assert material_category_for_grade("12Cr5Mo") == "FeIII"
    assert material_category_for_grade("Q235B") == "FeI"


def test_welding_consumable_lookup_by_designation_alias_and_wire_class():
    from libs.regulatory_tables import is_verified, welding_consumable_spec

    j422 = welding_consumable_spec("J422")
    assert j422 and j422["designation"] == "E4303" and j422["mechanical"]["tensileMPaMin"] == 430
    assert welding_consumable_spec("e5015")["commonName"] == "J507"
    wire = welding_consumable_spec("ER50-6")
    assert wire and wire["wireComposition"]["Mn"] == "1.40-1.85" and wire["mechanical"]["yieldMPaMin"] == 390
    assert welding_consumable_spec("S6") is wire
    assert not is_verified(wire)  # 预填值未核对：只能预警
    assert welding_consumable_spec("E9999") is None
