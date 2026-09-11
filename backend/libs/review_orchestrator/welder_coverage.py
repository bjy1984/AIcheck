"""TSG Z6002 焊工合格项目覆盖表（2010 与 2026 两版并存）。

## 为什么单独成模

2026-08-01 起 TSG Z6002-2026 施行、2010 版同日废止（总局 2026 年第 12 号公告），
市监特设发〔2026〕85 号明确：有效期内的旧证继续有效，但**覆盖范围按新细则执行**。
所以覆盖表必须按「施焊/审查日期」选版，而不是按证书签发日期。

原来 `deterministic_tools` 只有一张 2010 表，并在 2026-08-01 后用
`ruleProfile2026Verified` 开关一律返回证据不足——节点 24/29 的焊工判定自 8 月 1 日
起实际停用。2026-09-11 生产实测：130 项证据不足里 36 项来自这道闸门。

## 三态，不是两态

`qualification_covers_work` 返回 covered / not_covered / **undecidable**。

这一条是本模块存在的第二个理由。原来只有 True/False：牌号查不到母材类别时返回
False，最终判成 **failed**——系统等于在说「这名焊工超范围作业」，而它其实只是
不认识那个牌号。2026-09-11 实测复现：牌号「某个表里没有的牌号X」→ failed。
认不出就该说认不出。

## 数据来源与信任边界

母材类别表（表 A-2，196 个牌号）在 `business_packs/.../regulatory_tables.yaml`，
`extractedFrom: ocr`、`verifiedBy: null`，表上自己写着「写入判定前须逐格核对」。
本模块因此**不拿它定罪**：查不到牌号 → undecidable，查得到才参与比较。
结构性规则（类别互认、位置、厚度、外径、填充金属链、工艺因素、衬垫）另有
调研报告《研究-焊接材料设计节点审查原则》§1.3 按条号逐条对照，与该 yaml 互为印证。

未纳入判定（数据结构里没有对应字段，宁可不判）：
- 异种钢接头（FeⅣ 证覆盖 FeⅣ 与 FeⅠ~Ⅲ 的异种接头）；
- 管板试件代号（6FG/5FG/2FRG/2FG）与「对接合格后角焊缝厚度管径不限」；
- 表 A-7「T≥12 且 t≥12、≥3 层」里的层数条件（代号串里没有层数）。
这些位置代号走精确匹配，匹配不上按 undecidable 处理，不按不覆盖。
"""
from __future__ import annotations

from typing import Any

COVERED = "covered"
NOT_COVERED = "not_covered"
UNDECIDABLE = "undecidable"

RULE_VERSION_2010 = "welder-qualification-tsg-z6002-2010-v2"
RULE_VERSION_2026 = "welder-qualification-tsg-z6002-2026-v1"

# 表 A-5 里参与「变更须重考」比较的工艺因素（A4.3.9.1）。
# 列表里没有 11（无背面保护气）：无背面充氩考试合格者改为有背面充氩不算变更，
# 反之（证书有 10、实际无）须重考。
GOVERNED_PROCESS_FACTORS_2026 = frozenset({"01", "02", "03", "10", "12", "13", "14", "23", "24"})
BACKING_GAS_FACTOR = "10"

# 表 A-3「适用范围」列。Fef3J（低氢碱性）向下覆盖 Fef3、Fef1，FefS 自成一体。
FILLER_COVERAGE_2026 = {
    "FEF1": {"FEF1"},
    "FEF2": {"FEF1", "FEF2"},
    "FEF3": {"FEF1", "FEF3"},
    "FEF3J": {"FEF1", "FEF3", "FEF3J"},
    "FEF4": {"FEF4"},
    "FEF4J": {"FEF4", "FEF4J"},
    "FEFS": {"FEFS"},
}

# A4.3.2.1.1(1)：FeⅠ、FeⅡ、FeⅢ 任一合格即视为三类均通过（2010 版是高覆盖低）。
# (2) FeⅣ 合格覆盖 FeⅣ 及 FeⅣ 与 FeⅠ~Ⅲ 的异种钢接头——异种接头本模块不判。
_FE_MUTUAL = frozenset({"FEI", "FEII", "FEIII"})
MATERIAL_COVERAGE_2026: dict[str, frozenset[str]] = {
    "FEI": _FE_MUTUAL,
    "FEII": _FE_MUTUAL,
    "FEIII": _FE_MUTUAL,
    "FEIV": frozenset({"FEIV"}),
}
# 有色：镍、铝、钛、锆取得某类别后可焊该种类各类别；铜同类别内覆盖。
for _prefix, _classes in (("NI", "I II III IV V"), ("AL", "I II III V"), ("TI", "I II"), ("ZR", "I II")):
    _all = frozenset(f"{_prefix}{item}" for item in _classes.split())
    for _code in _all:
        MATERIAL_COVERAGE_2026[_code] = _all
for _code in ("CUI", "CUII", "CUIII", "CUIV", "CUV"):
    MATERIAL_COVERAGE_2026[_code] = frozenset({_code})

MATERIAL_COVERAGE_2010 = {
    "FEI": frozenset({"FEI"}),
    "FEII": frozenset({"FEI", "FEII"}),
    "FEIII": frozenset({"FEI", "FEII", "FEIII"}),
    "FEIV": frozenset({"FEIV"}),
    "FEV": frozenset({"FEI", "FEII", "FEIII", "FEV"}),
    "FEVI": frozenset({"FEI", "FEII", "FEIII", "FEV", "FEVI"}),
}

# 表 A-6。管对接试件：5G→平立仰、6G→平横立仰（全部向上位置）；
# 板试件 3G→平立、4G→平仰。向下焊（X 后缀）与向上焊互不覆盖（A4.3.5.1(3)），
# 立向下在本表里记作 3GX。
POSITION_COVERAGE_2026 = {
    "1G": frozenset({"1G"}),
    "2G": frozenset({"1G", "2G"}),
    "3G": frozenset({"1G", "3G"}),
    "4G": frozenset({"1G", "4G"}),
    "5G": frozenset({"1G", "3G", "4G", "5G"}),
    "6G": frozenset({"1G", "2G", "3G", "4G", "5G", "6G"}),
    "5GX": frozenset({"1G", "3GX", "4G", "5GX"}),
    "6GX": frozenset({"1G", "2G", "3GX", "4G", "6GX"}),
}

POSITION_COVERAGE_2010 = {
    "1G": frozenset({"1G"}),
    "2G": frozenset({"1G", "2G"}),
    "3G": frozenset({"3G"}),
    "4G": frozenset({"4G"}),
    "5G": frozenset({"1G", "5G"}),
    "6G": frozenset({"1G", "2G", "3G", "4G", "5G", "6G"}),
}


def profile_for_rule_version(rule_version: str) -> dict[str, Any]:
    if str(rule_version) == RULE_VERSION_2010:
        return {
            "material": MATERIAL_COVERAGE_2010,
            "position": POSITION_COVERAGE_2010,
            "filler": None,
            "governedFactors": None,
        }
    return {
        "material": MATERIAL_COVERAGE_2026,
        "position": POSITION_COVERAGE_2026,
        "filler": FILLER_COVERAGE_2026,
        "governedFactors": GOVERNED_PROCESS_FACTORS_2026,
    }


def material_covered(qualified: str, actual: str, profile: dict[str, Any]) -> str:
    """认不出任一侧的类别就是 undecidable——不认识材料不等于焊工超范围。"""
    if not qualified or not actual:
        return UNDECIDABLE
    table = profile["material"]
    allowed = table.get(qualified)
    if allowed is None:
        return UNDECIDABLE if qualified not in {item for values in table.values() for item in values} else NOT_COVERED
    return COVERED if actual in allowed else NOT_COVERED


def position_covered(qualified: str, actual: str, profile: dict[str, Any]) -> str:
    if not qualified or not actual:
        return UNDECIDABLE
    allowed = profile["position"].get(qualified)
    if allowed is None:
        # 管板（6FG/5FG/2FRG/2FG）等本模块没有覆盖表的代号：相同就算覆盖，
        # 不同不下「不覆盖」的结论，交人工。
        return COVERED if qualified == actual else UNDECIDABLE
    return COVERED if actual in allowed else NOT_COVERED


def filler_covered(qualified: str, actual: str, profile: dict[str, Any]) -> str:
    if not qualified or not actual:
        return UNDECIDABLE
    table = profile["filler"]
    if table is None:
        return COVERED if qualified == actual else NOT_COVERED
    allowed = table.get(qualified)
    if allowed is None:
        return COVERED if qualified == actual else UNDECIDABLE
    return COVERED if actual in allowed else NOT_COVERED


def backing_covered(qualified_backing: bool | None, actual_backing: bool | None) -> str:
    """A4.3.6.1：不带衬垫（单面焊全焊透）覆盖带衬垫，反之不可。两版一致。"""
    if qualified_backing is not True:
        # 证书不带 (K)，带不带衬垫的焊件都覆盖，实际值未知也不影响。
        return COVERED
    if actual_backing is None:
        return UNDECIDABLE
    return COVERED if actual_backing else NOT_COVERED


def process_factors_covered(
    qualified: set[str], actual: set[str], material_category: str, profile: dict[str, Any]
) -> str:
    """A4.3.9.1：只有受管辖的工艺因素参与比较；10 单独成规则。"""
    governed = profile["governedFactors"]
    if governed is None:
        return COVERED if not actual or actual <= qualified else NOT_COVERED
    exempt_backing_gas = material_category == "FEIII"
    left = {item for item in qualified if item in governed}
    right = {item for item in actual if item in governed}
    if exempt_backing_gas:
        left.discard(BACKING_GAS_FACTOR)
        right.discard(BACKING_GAS_FACTOR)
    # 加 10（改为有背面充氩）不算变更；去掉 10（证书有、实际没有）须重考。
    if BACKING_GAS_FACTOR in left and BACKING_GAS_FACTOR not in right and not exempt_backing_gas:
        return NOT_COVERED
    right.discard(BACKING_GAS_FACTOR)
    left.discard(BACKING_GAS_FACTOR)
    return COVERED if right <= left else NOT_COVERED


def combine(outcomes: list[str]) -> str:
    """任一维度明确不覆盖即不覆盖；否则只要有一维说不准，整体就说不准。"""
    if NOT_COVERED in outcomes:
        return NOT_COVERED
    if UNDECIDABLE in outcomes:
        return UNDECIDABLE
    return COVERED
