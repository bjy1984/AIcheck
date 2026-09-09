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


def test_pipe_limits_cover_six_standards_and_keep_them_apart():
    """同一牌号在不同管材标准下限值不同——质保书核对必须按管材标准分开查。"""
    from libs.regulatory_tables import pipe_material_limits, table

    standards = {item["standard"] for item in table("pipeMaterialLimits")["standards"]}
    assert standards == {
        "GB/T 8163-2018", "GB/T 3087-2022", "GB/T 14976-2025",
        "GB/T 12771-2019", "GB/T 5310-2023", "GB/T 13296-2023",
    }
    assert sum(len(item["grades"]) for item in table("pipeMaterialLimits")["standards"]) >= 42

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


def test_wps_thickness_coverage_follows_table6_and_impact_rule():
    """NB/T 47014-2023 表 6/表 7 + 6.1.5.2：一份评定报告能覆盖多厚的焊件。"""
    from libs.regulatory_tables import wps_thickness_coverage

    # 表 6 常规行：T=12 落在 10<T<20，母材 5~2T，焊缝金属 ≤2t
    normal = wps_thickness_coverage(12, weld_metal_thickness_mm=12, welding_method="焊条电弧焊")
    assert normal["specimenRange"] == "10<T<20"
    assert (normal["baseMetalMinMm"], normal["baseMetalMaxMm"]) == (5.0, 24.0)
    assert normal["weldMetalMaxMm"] == 24.0 and normal["notes"] == []

    # 6.1.5.2：有冲击试验且 T≥6 → 母材最小值取 T 与 16 的较小值
    impact = wps_thickness_coverage(12, weld_metal_thickness_mm=12, welding_method="焊条电弧焊", impact_tested=True)
    assert impact["baseMetalMinMm"] == 12.0 and "6.1.5.2" in impact["notes"][0]
    # T<6 → 最小值为 T/2
    thin = wps_thickness_coverage(4, weld_metal_thickness_mm=4, welding_method="埋弧焊", impact_tested=True)
    assert thin["baseMetalMinMm"] == 2.0

    # 闭区间边界：T=10 归 1.5<=T<=10 那一行，不掉进 10<T<20
    edge = wps_thickness_coverage(10, weld_metal_thickness_mm=10, welding_method="埋弧焊")
    assert edge["specimenRange"] == "1.5<=T<=10" and edge["baseMetalMinMm"] == 1.5

    # 38<=T<=150 的上限是 200mm（注 a），只限四种电弧焊
    thick = wps_thickness_coverage(40, weld_metal_thickness_mm=25, welding_method="焊条电弧焊")
    assert thick["baseMetalMaxMm"] == 200.0 and thick["weldMetalMaxMm"] == 200.0
    other = wps_thickness_coverage(40, weld_metal_thickness_mm=25, welding_method="摩擦焊")
    assert other["baseMetalMaxMm"] is None, "注 a 不适用的方法不给上限，不猜"
    assert any("注 a" in note for note in other["notes"])

    # 表 7（纵向弯曲）只有三行，T>10 一律 5~2T
    longitudinal = wps_thickness_coverage(12, weld_metal_thickness_mm=12, bend="longitudinal")
    assert longitudinal["specimenRange"] == ">10" and longitudinal["baseMetalMaxMm"] == 24.0

    # 没给焊缝金属厚度就说清算不出，不猜
    partial = wps_thickness_coverage(12, welding_method="焊条电弧焊")
    assert partial["weldMetalMaxMm"] is None and "算不出" in partial["notes"][0]
    assert wps_thickness_coverage(0) is None and wps_thickness_coverage("x") is None


def test_filler_class_matches_base_material_group():
    """NB/T 47014-2023 表 2~表 4：焊材分类代号与母材组别的对应，供焊材选用判定。"""
    from libs.regulatory_tables import filler_classes_for_group, filler_matches_base_material, table

    tables = table("nbt47014FillerClasses")["tables"]
    assert {v["codePrefix"] for v in tables.values()} == {"FeT", "FeS", "FeMSG"}
    assert sum(len(v["entries"]) for v in tables.values()) == 73

    # 三张表同一个母材组各有一条，前缀不同
    assert [item["fillerClass"] for item in filler_classes_for_group("Fe-1-2")] == ["FeT-1-2", "FeS-1-2", "FeMSG-1-2"]
    # 给了方法就只给那张表：焊条走表 2、埋弧焊走表 4、钨极走表 3
    assert [i["fillerClass"] for i in filler_classes_for_group("Fe-1-2", welding_method="焊条电弧焊")] == ["FeT-1-2"]
    assert [i["fillerClass"] for i in filler_classes_for_group("Fe-1-2", welding_method="埋弧焊")] == ["FeMSG-1-2"]
    assert [i["fillerClass"] for i in filler_classes_for_group("Fe-1-2", welding_method="钨极气体保护焊")] == ["FeS-1-2"]

    # Fe-1-x 按强度分档，抗拉强度下限跟着组别走
    by_code = {i["fillerClass"]: i for i in filler_classes_for_group("Fe-1-1") + filler_classes_for_group("Fe-1-3")}
    assert by_code["FeT-1-1"]["tensileMPaMin"] == 430
    assert by_code["FeT-1-3"]["tensileMPaMin"] == 550

    # 端到端：Q345R 属 Fe-1-2，配 FeT-1-2 匹配、配 FeT-1-1 不匹配
    ok = filler_matches_base_material("FeT-1-2", "Q345R")
    assert ok["matched"] is True and ok["baseMaterialGroup"] == "Fe-1-2"
    assert filler_matches_base_material("FeT-1-1", "Q345R")["matched"] is False

    # 母材查不到组别时不给结论
    assert filler_matches_base_material("FeT-1-1", "X99NotAGrade") is None
    assert filler_classes_for_group("") == [] and filler_classes_for_group("Fe-99") == []


def test_product_inspection_rules_cover_all_pipe_standards():
    """R14 判「这个产品标准要求做哪些出厂检验」——此前只写死了一本标准。"""
    from libs.regulatory_tables import product_inspection_rules

    rules = product_inspection_rules()
    assert len(rules) == 6
    # 逐根强制的才进 requiredItems
    assert rules["GB/T 12771-2019"]["requiredItems"] == ["nondestructive_testing"]
    assert rules["GB/T 13296-2023"]["requiredItems"] == ["pressure_test"]
    assert rules["GB/T 5310-2023"]["requiredItems"] == ["hardness_test"]
    # 「根据需方要求、经协商」的选项不进 requiredItems，只作条件项——拿它判不符合会冤枉人
    assert rules["GB/T 3087-2022"]["requiredItems"] == []
    assert rules["GB/T 3087-2022"]["conditionalItems"][0]["item"] == "高温拉伸"
    assert rules["GB/T 8163-2018"]["conditionalItems"][0]["item"] == "纵向冲击试验"
    assert all(rule["basis"] for rule in rules.values()), "每条都要有条款出处"


def test_annex_b_gives_a_path_when_the_material_is_not_in_table1():
    """表 1 查不到母材不等于判不了——附录 B 是规范性的，规定了替代路径和归类报告的必备内容。"""
    from libs.regulatory_tables import base_material_classification_requirement

    assert base_material_classification_requirement("Q345R") is None, "表 1 里的牌号走正常组别比对"
    requirement = base_material_classification_requirement("某进口未列入牌号")
    assert requirement is not None
    assert requirement["requiredReport"] == "母材归类报告"
    assert len(requirement["reportContents"]) == 9
    assert "存档备查" in requirement["retention"]


def test_annex_b_filler_metal_requirement_checks_class_and_standard():
    """表 2~表 4 列的是类别代号与 NB/T 47018 系列标准，型号（E5015）不在其中，别拿型号去比。"""
    from libs.regulatory_tables import filler_metal_classification_requirement

    assert filler_metal_classification_requirement(filler_class="FeT-1-1", standard="NB/T 47018.2") is None
    # 类别在表里但执行的不是表中所列标准 → B.3.1.1
    other_standard = filler_metal_classification_requirement(filler_class="FeT-1-1", standard="GB/T 5117")
    assert other_standard is not None and other_standard["requiredReport"] == "填充金属归类报告"
    # 类别代号根本不在表里
    unknown = filler_metal_classification_requirement(filler_class="ZZ-9-9")
    assert unknown is not None and len(unknown["reportContents"]) == 8
    # 什么都不给不该凭空产生要求
    assert filler_metal_classification_requirement() is None


def test_acceptance_limits_respect_the_standard_s_applicability_rules():
    """标准不要求的项不该下发限值——下发了就会拿它去要证据，本该通过的项掉进证据不足。

    GB/T 5310：冲击按 7.4.2 要外径≥76 且壁厚≥14；布氏按 7.4.3 a）要壁厚≥5.0；
    维氏按 7.4.3 c）只在合同注明时做。
    """
    from libs.review_orchestrator.material_facts import _enrich_material_design_item

    def limits_of(spec: str) -> tuple[set[str], str]:
        item = _enrich_material_design_item({"sourceRow": {"材料牌号": "20G", "执行标准": "GB/T 5310-2023", "规格": spec}})
        names = {entry["name"] for entry in item.get("acceptanceLimits") or []}
        return names, " ".join(item.get("acceptanceLimitsNotApplicable") or [])

    # 够粗够厚：冲击要做，布氏要做，维氏仍然不做
    thick, thick_skipped = limits_of("φ108×16")
    assert {"抗拉强度", "屈服强度", "断后伸长率", "冲击吸收能量", "布氏硬度"} <= thick
    assert "维氏硬度" not in thick and "7.4.3 c）" in thick_skipped

    # 壁厚 5：冲击不做，布氏仍要做
    medium, medium_skipped = limits_of("φ57×5")
    assert "冲击吸收能量" not in medium and "布氏硬度" in medium
    assert "7.4.2" in medium_skipped

    # 壁厚 4：冲击与布氏都不做
    thin, thin_skipped = limits_of("φ108×4")
    assert "冲击吸收能量" not in thin and "布氏硬度" not in thin
    assert "7.4.3 a）" in thin_skipped

    # 规格串同时给出外径与壁厚
    parsed = _enrich_material_design_item({"sourceRow": {"材料牌号": "20G", "执行标准": "GB/T 5310-2023", "规格": "φ108×16"}})
    assert (parsed["outerDiameterMm"], parsed["wallThicknessMm"]) == (108.0, 16.0)


def test_quality_level_reaches_the_limit_lookup():
    """Q345 这类分质量等级的牌号：伸长率与冲击写在等级层，等级传不进去就一条都取不到。

    设计资料上写的是"质量等级"，此前别名表里没有它，`pipe_material_limits` 永远按 None 查，
    只拿得到各级共有的抗拉与屈服。
    """
    from libs.review_orchestrator.material_facts import _enrich_material_design_item

    def limits_of(level: str | None, spec: str = "φ108×8") -> dict[str, float]:
        row = {"材料牌号": "Q345", "执行标准": "GB/T 8163-2018", "规格": spec}
        if level:
            row["质量等级"] = level
        item = _enrich_material_design_item({"sourceRow": row})
        return {entry["name"]: entry.get("minimum") for entry in item.get("acceptanceLimits") or []}

    assert limits_of("B")["断后伸长率"] == 20
    assert limits_of("D")["断后伸长率"] == 21, "D 级比 B 级多一个点，取错等级就判错"
    assert limits_of("B")["冲击吸收能量"] == 34

    # 5.4.2.1：外径<70 或壁厚<6.5 不做冲击
    assert "冲击吸收能量" not in limits_of("B", "φ57×4")

    # 没写等级时只给各级共有的两项，不猜等级
    common = limits_of(None)
    assert {name for name in common if not name.startswith("化学成分")} == {"抗拉强度", "屈服强度"}


def _limits(row: dict) -> dict:
    from libs.review_orchestrator.material_facts import _enrich_material_design_item

    item = _enrich_material_design_item({"sourceRow": row})
    return {
        "limits": {entry["name"]: (entry.get("minimum"), entry.get("maximum")) for entry in item.get("acceptanceLimits") or []},
        "notes": " ".join(item.get("acceptanceLimitsNotes") or []),
        "unresolved": " ".join(item.get("acceptanceLimitsUnresolved") or []),
    }


def test_welded_pipe_elongation_follows_the_delivery_condition():
    """GB/T 12771 的伸长率分热处理/非热处理两列，此前两列都读不到，九个牌号一条限值都出不来。"""
    base = {"材料牌号": "S30408", "执行标准": "GB/T 12771-2019", "规格": "φ108×4"}

    heat_treated = _limits({**base, "交货状态": "固溶热处理"})
    assert heat_treated["limits"]["断后伸长率"] == (40, None)

    as_welded = _limits({**base, "交货状态": "焊态"})
    assert as_welded["limits"]["断后伸长率"] == (35, None)

    # 交货状态没写就不选档，记成未决而不是随便挑一列
    unknown = _limits(base)
    assert "断后伸长率" not in unknown["limits"]
    assert "选不出档" in unknown["unresolved"]


def test_rockwell_hardness_is_parsed_for_thin_wall_pipe():
    """GB/T 5310 7.4.3 b）：壁厚小于 5.0mm 做的是洛氏。"85-97 HRBW" 这种写法此前解析不了，
    薄壁管等于一项硬度都不核。"""
    thin = _limits({"材料牌号": "12Cr2MoWVTiB", "执行标准": "GB/T 5310-2023", "规格": "φ60×4"})
    assert thin["limits"]["洛氏硬度（HRBW）"] == (85.0, 97.0)
    assert "布氏硬度" not in thin["limits"], "壁厚 4mm 不做布氏"


def test_elongation_picks_the_sampling_direction_when_the_document_states_it():
    """无缝不锈钢管的伸长率分纵/横向：横向下限低一档，写了方向就按方向取。"""
    base = {"材料牌号": "S30408", "执行标准": "GB/T 14976-2025", "规格": "φ108×4"}

    transverse = _limits({**base, "取样方向": "横向"})
    assert transverse["limits"]["断后伸长率"] == (30, None)
    assert "按横向取样" in transverse["notes"]

    # 没写方向时取纵向（较严的一档）并说明，不悄悄放宽
    unstated = _limits(base)
    assert unstated["limits"]["断后伸长率"] == (35, None)
    assert "未写取样方向" in unstated["notes"]


def test_gc2_inspection_level_follows_the_medium_hazard():
    """GB/T 20801.1-2025 8.3.1：GC2 管道的检查等级看介质——有毒 Ⅲ 级、泄漏危害性 Ⅱ 级，
    都比缺省的 Ⅳ 级严，对应的体积检测比例也更高。按 Ⅳ 级一口咬定会把比例要求降下来。"""
    from libs.regulatory_tables import (
        inspection_level_for_grade,
        medium_hazard_flags,
        volumetric_ndt_ratio,
    )

    assert inspection_level_for_grade("GC2") == "Ⅳ"
    assert inspection_level_for_grade("GC2", toxic=True) == "Ⅲ"
    assert inspection_level_for_grade("GC2", leak_hazard=True) == "Ⅱ"
    # 等级更严，比例要求也更高
    assert volumetric_ndt_ratio("Ⅱ") > volumetric_ndt_ratio("Ⅲ") > volumetric_ndt_ratio("Ⅳ")

    # 只认资料上明确写的分级用语
    assert medium_hazard_flags(toxicity="中度危害")["toxic"] is True
    assert medium_hazard_flags(toxicity="无毒")["toxic"] is False
    assert medium_hazard_flags(leak_hazard="泄漏危害性介质")["leakHazard"] is True

    # 介质名称本身不拿来猜——判一种介质有没有毒要查物质清单
    guessed = medium_hazard_flags(medium="液氨")
    assert guessed["toxic"] is None and guessed["determined"] is False


def test_undetermined_gc2_pipelines_are_listed_instead_of_silently_defaulted():
    """资料没写毒性/泄漏危害性的 GC2 管线要点名，让人去补，而不是按最宽的 Ⅳ 级悄悄过去。"""
    from libs.review_orchestrator.design_facts import design_special_requirements

    text = "管道采用射线检测 RT，检测比例 5%，验收等级 Ⅲ级"
    pipelines = [
        {"pipelineId": "P-101", "pipelineGrade": "GC2", "medium": "液氨"},
        {"pipelineId": "P-102", "pipelineGrade": "GC2", "mediumToxicity": "中度危害", "leakHazard": "否", "medium": "液氨"},
        {"pipelineId": "P-103", "pipelineGrade": "GC3", "medium": "循环水"},
    ]
    facts = design_special_requirements(text, pipelines)
    ndt = facts["domains"]["ndt"]["requirements"]
    assert ndt["inspectionLevelUndeterminedPipelines"] == ["P-101"]
    # P-102 写了中度危害 → Ⅲ 级，比 GC3 的 Ⅴ 级严，取最严的一条
    assert ndt["requiredInspectionLevel"] == "Ⅲ"


def test_ndt_acceptance_level_depends_on_the_examination_ratio():
    """GB/T 20801.1-2025 8.3.2：合格级别按检查比例定。100% 射线要 Ⅱ 级、局部才是 Ⅲ 级；
    100% 超声要 Ⅰ 级、局部是 Ⅱ 级。设计写"验收等级 Ⅲ级"配 100% 射线是不合格的。"""
    from libs.regulatory_tables import acceptance_level_meets, ndt_acceptance_level

    assert ndt_acceptance_level("RT", coverage_percent=100)["level"] == "不低于 Ⅱ 级"
    assert ndt_acceptance_level("射线检测", coverage_percent=5)["level"] == "不低于 Ⅲ 级"
    assert ndt_acceptance_level("UT", coverage_percent=100)["level"] == "Ⅰ 级"
    assert ndt_acceptance_level("超声", coverage_percent=20)["level"] == "不低于 Ⅱ 级"
    # 比例不明就判不了，不猜是全检还是抽检
    assert ndt_acceptance_level("RT") is None
    # 认不出的方法也不猜
    assert ndt_acceptance_level("敲一敲听声音", coverage_percent=100) is None

    assert acceptance_level_meets("Ⅱ级", "不低于 Ⅱ 级") is True
    assert acceptance_level_meets("Ⅲ级", "不低于 Ⅱ 级") is False
    assert acceptance_level_meets("看不懂", "不低于 Ⅱ 级") is None


def test_design_acceptance_level_is_compared_against_the_standard():
    """此前只把"验收等级 Ⅲ级"抄进事实，没有任何地方拿它跟标准比。"""
    from libs.review_orchestrator.design_facts import design_special_requirements

    pipelines = [{"pipelineId": "P-1", "pipelineGrade": "GC2", "mediumToxicity": "无毒"}]

    # 100% 射线配 Ⅲ 级 → 不达标
    bad = design_special_requirements("管道采用射线检测 RT，检测比例 100%，验收等级 Ⅲ级", pipelines)
    ndt = bad["domains"]["ndt"]["requirements"]
    assert ndt["requiredAcceptanceLevel"] == "不低于 Ⅱ 级"
    assert ndt["acceptanceLevelMeetsRequirement"] is False

    # 局部检查配 Ⅲ 级 → 达标
    good = design_special_requirements("管道采用射线检测 RT，检测比例 20%，验收等级 Ⅲ级", pipelines)
    assert good["domains"]["ndt"]["requirements"]["acceptanceLevelMeetsRequirement"] is True


def test_filler_class_matching_handles_the_coarser_group_codes_in_tables_2_to_4():
    """表 1 的组别写到 Fe-8-1、Fe-5B-1，表 2~表 4 只写到 Fe-8、Fe-5B。

    只做全等匹配时，奥氏体不锈钢、铬钼钢等 15 个组别一条焊材类别都取不到，
    配套性判定会把每一种焊材都判成"不配套"——那是假的不符合。
    """
    from libs.regulatory_tables import (
        filler_classes_for_group,
        filler_matches_base_material,
        wps_base_material_group,
    )

    assert wps_base_material_group("S30408") == "Fe-8-1"
    assert [item["fillerClass"] for item in filler_classes_for_group("Fe-8-1")] == ["FeT-8", "FeS-8"]
    assert filler_matches_base_material("FeT-8", "S30408")["matched"] is True
    assert filler_matches_base_material("FeT-1-1", "S30408")["matched"] is False

    # 细组别优先：Fe-1-2 在表 2~4 里有自己的条目，不该退到 Fe-1
    assert [item["fillerClass"] for item in filler_classes_for_group("Fe-1-2")] == ["FeT-1-2", "FeS-1-2", "FeMSG-1-2"]

    # 表 2~表 4 根本没列的组别返回 None（判不了），不是"不配套"
    from libs.regulatory_tables import table

    groups = table("nbt47014_2023", "baseMaterialGroups").get("groups") or []
    unlisted = [g["group"] for g in groups if not filler_classes_for_group(g["group"])]
    assert set(unlisted) == {"Fe-11A", "Cu-5", "Ni-2", "Ni-3", "Ni-4", "Ni-5"}


def test_gc2_partial_negative_and_unknown_hazard_never_certify_lowest_level():
    from libs.regulatory_tables import medium_hazard_flags
    from libs.review_orchestrator.design_facts import design_special_requirements

    for toxicity, leak in [('无毒', None), (None, '否'), ('无毒', '待确认'), ('有毒', None)]:
        assert not medium_hazard_flags(toxicity=toxicity, leak_hazard=leak)['determined']
        requirements = design_special_requirements(
            '射线检测，检测比例 5%，验收等级 Ⅲ级',
            [{'pipelineId': 'P1', 'pipelineGrade': 'GC2', 'mediumToxicity': toxicity, 'leakHazard': leak}],
        )['domains']['ndt']['requirements']
        assert requirements['inspectionLevelUndeterminedPipelines'] == ['P1']
        assert 'coverageMeetsRequirement' not in requirements
    assert medium_hazard_flags(toxicity=False, leak_hazard=False)['determined']
    assert medium_hazard_flags(leak_hazard=True)['determined']
    assert medium_hazard_flags(leak_hazard='待确认')['leakHazard'] is None


def test_welding_method_aliases_and_missing_footnote_inputs():
    from libs.regulatory_tables import (
        filler_classes_for_group,
        wps_specific_factors,
        wps_thickness_coverage,
    )

    assert wps_specific_factors('SMAW') == wps_specific_factors('焊条电弧焊')
    assert filler_classes_for_group('Fe-1-2', welding_method='SMAW') == filler_classes_for_group(
        'Fe-1-2', welding_method='焊条电弧焊')
    assert filler_classes_for_group('Fe-1-2', welding_method='未知方法') == []
    assert wps_thickness_coverage(12, impact_tested=True, welding_method='SMAW')['baseMetalMinMm'] == 12
    assert wps_thickness_coverage(40, weld_metal_thickness_mm=25)['baseMetalMaxMm'] is None
    for value in [float('nan'), float('inf'), -1]:
        assert wps_thickness_coverage(value) is None
        assert wps_thickness_coverage(12, weld_metal_thickness_mm=value) is None


def test_ndt_special_techniques_do_not_match_generic_ut_substring():
    from libs.regulatory_tables import ndt_acceptance_level

    for label, method in (("PAUT", "phasedArray"), ("相控阵超声检测（PAUT）", "phasedArray"),
                          ("TOFD超声检测", "tofd"), ("衍射时差法", "tofd"), ("射线检测(RT)", "radiographic")):
        found = ndt_acceptance_level(label, coverage_percent=100)
        assert found and found["method"] == method
    assert ndt_acceptance_level("PAUT", coverage_percent=100)["level"] == "不低于 Ⅱ 级"
    assert ndt_acceptance_level("UT", coverage_percent=100)["level"] == "Ⅰ 级"
    for label in ("RT/UT", "RT + PAUT", "PAUT/TOFD", "UT/PAUT", "相控阵+常规超声", "OUTPUT", "SMART"):
        assert ndt_acceptance_level(label, coverage_percent=100) is None


def test_ndt_invalid_or_zero_ratio_does_not_select_a_partial_inspection_rule():
    from libs.regulatory_tables import ndt_acceptance_level

    for method in ("RT", "UT", "PAUT", "TOFD"):
        for ratio in (0, -1, 101, float("nan"), float("inf"), True, "100"):
            assert ndt_acceptance_level(method, coverage_percent=ratio) is None
    assert ndt_acceptance_level("PAUT")["method"] == "phasedArray"
    assert ndt_acceptance_level("TOFD")["method"] == "tofd"
