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
    # 2026-09-07 采信策略改为 accept_without_human_signoff：未签字的表也可用于判定
    assert is_verified(table("tsgZ6002_2026", "materialCategories")) is True
    assert table("tsgZ6002_2026", "materialCategories").get("verifiedBy") is None, "采信不等于伪造签字：verifiedBy 仍为空"
    assert table("tsg31_2025", "designApproval")["fourLevelTriggers"][0] == "GC1 级管道"


def test_material_lookups_are_case_and_hyphen_insensitive() -> None:
    assert welder_material_category("Q235B") == "FeⅠ"
    assert welder_material_category("12cr1mov") == "FeⅡ"
    assert welder_material_category("06Cr19Ni10") == "FeⅣ"
    assert welder_material_category("ZZZ") is None
    assert wps_base_material_group("20G") == "Fe-1-1" and wps_base_material_group("Q345R") == "Fe-1-2"
    # 表 1 已是全表：S31603 抄到了；查不到的牌号仍然不猜
    assert wps_base_material_group("S31603") == "Fe-8-1"
    assert wps_base_material_group("X99NotAGrade") is None, "查不到的牌号不猜"


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

    # GB/T 5117-2012 表 6/表 7 正文值；冲击按 4.5.2 是 ≥27J，只有带 U 代号才 ≥47J
    j422 = welding_consumable_spec("J422")
    assert j422 and j422["designation"] == "E4303"
    assert j422["mechanical"] == {"tensileMPaMin": 430, "yieldMPaMin": 330, "elongationPctMin": 20, "impactTemperatureC": 0, "kv2JMin": 27, "kv2JMinWithU": 47}
    assert j422["depositedMetalComposition"]["Mn"] == "<=1.20"
    j507 = welding_consumable_spec("e5015")
    assert j507["commonName"] == "J507" and j507["mechanical"]["impactTemperatureC"] == -30
    assert j507["mechanical"]["kv2JMin"] == 27 and j507["depositedMetalComposition"]["Mn"] == "<=1.60"
    assert welding_consumable_spec("J506")["designation"] == "E5016"
    wire = welding_consumable_spec("ER50-6")
    assert wire and wire["wireComposition"]["Mn"] == "1.40-1.85" and wire["mechanical"]["yieldMPaMin"] == 390
    assert welding_consumable_spec("S6") is wire
    assert is_verified(wire) and wire.get("verifiedBy") is None  # 采信策略生效，但没有假签字
    assert welding_consumable_spec("E9999") is None


def test_nbt47014_base_material_groups_cover_the_whole_table_1():
    """NB/T 47014-2023 表 1 全表（含 Ti/Zr/Cu/Ni），组别边界按合并单元格居中规则还原。"""
    from libs.regulatory_tables import table, wps_base_material_group

    section = table("nbt47014_2023", "baseMaterialGroups")
    groups = {item["group"]: item["grades"] for item in section["groups"]}
    assert len(groups) >= 38 and sum(len(v) for v in groups.values()) >= 380
    assert {"Fe-1-1", "Fe-8-1", "Fe-11A", "Ti-1", "Zr-3", "Cu-1", "Ni-1"} <= set(groups)
    # 已知归属：错了就是块边界推歪了
    assert wps_base_material_group("Q345R") == "Fe-1-2"
    assert wps_base_material_group("Q245R") == "Fe-1-1"
    assert wps_base_material_group("S30408") == "Fe-8-1" == wps_base_material_group("06Cr19Ni10")
    assert wps_base_material_group("12Cr5Mo") == "Fe-5B-1"
    assert wps_base_material_group("06Ni9DR") == "Fe-11A"
    assert wps_base_material_group("12Cr13") == "Fe-6"
    # GB/T 9711 双写牌号两种写法都能查到
    assert wps_base_material_group("L245") == wps_base_material_group("L245/B") == "Fe-1-1"
    assert not section.get("verifiedBy"), "数值已对照正版 PDF，但仍等法规核对人签字"


def test_pipe_material_limits_merge_level_rows_and_never_guess():
    """P10 管材限值：Q345 这类分质量等级的牌号，取到的是共有值 + 该级独有值合并后的一份。"""
    from libs.regulatory_tables import pipe_material_limits

    q345b = pipe_material_limits("GB/T 8163-2018", "Q345", "B")
    assert q345b["mechanical"] == {"tensileMPa": "470-630", "yieldMPaMin": 345, "elongationPctMin": 20, "impactTemperatureC": 20, "kv2JMin": 34}
    assert q345b["composition"]["C"] == "<=0.20" and q345b["composition"]["Mn"] == "<=1.70"
    assert q345b["verified"] is True, "采信策略开着：可用于判定"

    q345e = pipe_material_limits("GB/T 8163-2018", "Q345", "E")
    assert q345e["composition"]["C"] == "<=0.18" and q345e["composition"]["S"] == "<=0.020"
    assert q345e["mechanical"]["impactTemperatureC"] == -40 and q345e["mechanical"]["kv2JMin"] == 27

    # 同为 20 钢，GB/T 3087 的 P/S 比 GB/T 8163 严，屈服强度还按壁厚分档
    assert pipe_material_limits("GB/T 8163-2018", "20")["composition"]["S"] == "<=0.030"
    t3087 = pipe_material_limits("GB/T 3087-2022", "20")
    assert t3087["composition"]["S"] == "<=0.020"
    assert t3087["mechanical"]["yieldMPaMinByThickness"] == {"<=16mm": 245, ">16mm": 235}
    assert t3087["hotYieldRp02MPa"][300] == 149

    # 不给等级时回报有哪些等级；查不到的牌号/标准返回 None
    assert pipe_material_limits("GB/T 8163-2018", "Q345")["availableLevels"] == ["A", "B", "C", "D", "E"]
    assert pipe_material_limits("GB/T 8163-2018", "Q460")["availableLevels"] == ["C", "D", "E"], "Q460 没有 A/B 级"
    assert pipe_material_limits("GB/T 8163-2018", "X99") is None
    assert pipe_material_limits("GB/T 9999-2099", "20") is None


def test_austenitic_pipe_limits_accept_both_code_and_grade_name():
    """质保书上写 S30408 还是 06Cr19Ni10 都能查到；伸长率分纵向/横向不是版本冲突。"""
    from libs.regulatory_tables import pipe_material_limits, table

    by_code = pipe_material_limits("GB/T 14976-2025", "S30408")
    by_name = pipe_material_limits("GB/T 14976-2025", "06Cr19Ni10")
    assert by_code == by_name and by_code["mechanical"]["tensileMPaMin"] == 520
    assert by_code["mechanical"]["elongationPctMinLongitudinal"] == 35
    assert by_code["mechanical"]["elongationPctMinTransverse"] == 30

    # 低碳的 022 系列强度低一档、伸长率高一档
    low_carbon = pipe_material_limits("GB/T 14976-2025", "022Cr17Ni12Mo2")
    assert low_carbon["grade"] == "S31603" and low_carbon["composition"]["C"] == "<=0.030"
    assert low_carbon["mechanical"]["tensileMPaMin"] == 480
    assert low_carbon["mechanical"]["elongationPctMinLongitudinal"] == 40

    # 附录 A：设计温度低于 -101℃ 时另有一套值，-196℃ 冲击
    annex = next(item for item in table("pipeMaterialLimits")["standards"] if item["standard"] == "GB/T 14976-2025")["lowTemperatureAnnex"]
    assert annex["tensile"]["tensileMPaMin"] == 520 and annex["impact"]["temperatureC"] == -196
    assert annex["impact"]["10x10"]["avgLongitudinalJMin"] == 60


def test_nbt47014_table5_specific_factors_by_welding_method():
    """NB/T 47014-2023 表 5：67 条专用评定因素，按方法分重要/补加/次要。"""
    from libs.regulatory_tables import table, wps_factor_class, wps_specific_factors

    section = table("nbt47014SpecificFactors")
    assert len(section["factors"]) == 67
    assert section["methodOrder"][:3] == ["气焊", "焊条电弧焊", "埋弧焊"]
    assert all(len(item["methodsByClass"]) > 0 for item in section["factors"]), "每条因素至少属于一类"
    assert not section.get("verifiedBy")

    # 2023 版把焊条电弧焊「改变电流种类或极性」从次要改成重要（见前言）；其他方法仍是补加
    assert wps_factor_class("焊条电弧焊", "改变电流种类") == "重要因素"
    assert wps_factor_class("埋弧焊", "改变电流种类") == "补加因素"
    assert wps_factor_class("气焊", "改变电流种类") is None, "气焊没有电流"

    # 预热温度降低 55℃ 以上：除气焊外都是重要因素，气焊只是次要
    assert wps_factor_class("焊条电弧焊", "预热温度比已评定合格值降低") == "重要因素"
    assert wps_factor_class("气焊", "预热温度比已评定合格值降低") == "次要因素"

    # 埋弧焊特有：改变混合焊剂配比要重新评定
    assert wps_factor_class("埋弧焊", "改变混合焊剂") == "重要因素"
    assert wps_factor_class("焊条电弧焊", "改变混合焊剂") is None

    smaw = wps_specific_factors("焊条电弧焊")
    assert {"重要因素", "补加因素", "次要因素"} == set(smaw)
    assert all(item["category"] for group in smaw.values() for item in group)
    assert wps_specific_factors("") == {} and wps_factor_class("焊条电弧焊", "查无此因素") is None


def test_trust_policy_is_recorded_not_faked_and_can_be_switched_back():
    """"直接采信"是一条显式声明，不是往 verifiedBy 里填人名；改回 require_human_signoff 就恢复门禁。"""
    import copy

    from libs.regulatory_tables import accepts_without_signoff, is_verified, table, trust_policy

    policy = trust_policy()
    assert policy["mode"] == "accept_without_human_signoff"
    assert policy["decidedBy"] and policy["decidedOn"] and policy["rationale"]
    assert accepts_without_signoff() is True

    # 全表没有一处把人名写进 verifiedBy 来冒充核对
    unsigned = [item for item in table("pipeMaterialLimits").get("standards") or []]
    assert all(item.get("verifiedBy") is None for item in unsigned)

    # is_verified 对"已签字"和"策略采信"都返回 True，但两者可区分
    signed = table("tsg31_2025", "designApproval")
    assert signed.get("verifiedBy") and is_verified(signed)
    assert is_verified(copy.deepcopy(unsigned[0]))


def test_pipe_limits_cover_five_standards_and_keep_them_apart():
    """同一牌号在不同管材标准下限值不同——质保书核对必须按管材标准分开查。"""
    from libs.regulatory_tables import pipe_material_limits, table

    standards = {item["standard"] for item in table("pipeMaterialLimits")["standards"]}
    assert {"GB/T 8163-2018", "GB/T 3087-2022", "GB/T 14976-2025", "GB/T 12771-2019", "GB/T 5310-2023"} == standards

    # S30408：焊接管 515，无缝管 520，伸长率的口径也不同
    welded = pipe_material_limits("GB/T 12771-2019", "06Cr19Ni10")
    seamless = pipe_material_limits("GB/T 14976-2025", "06Cr19Ni10")
    assert welded["mechanical"]["tensileMPaMin"] == 515
    assert seamless["mechanical"]["tensileMPaMin"] == 520
    assert "elongationPctMinAsWelded" in welded["mechanical"]
    assert "elongationPctMinTransverse" in seamless["mechanical"]

    # GB/T 5310 的锅炉管另有硬度区间，质保书上也要核
    g20 = pipe_material_limits("GB/T 5310-2023", "20G")
    assert g20["mechanical"]["tensileMPa"] == "410-550"
    assert g20["mechanical"]["kv2JMinLongitudinal"] == 40 and g20["mechanical"]["kv2JMinTransverse"] == 27
    assert g20["hardness"] == {"HBW": "120-160", "HV": "125-170"}
    assert pipe_material_limits("GB/T 5310-2023", "12Cr1MoVG")["mechanical"]["yieldMPaMin"] == 255

    # 12771 的铁素体牌号非热处理态不作伸长率要求
    ferritic = pipe_material_limits("GB/T 12771-2019", "06Cr13Al")
    assert "elongationPctMinAsWelded" not in ferritic["mechanical"]
