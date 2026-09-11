"""TSG Z6002 两版覆盖表的差异，逐条钉住。

条号出自 TSG Z6002-2026 附件 A，与调研报告《研究-焊接材料设计节点审查原则》§1.3
互相印证。2026-09-11 之前这些规则在代码里根本不存在——8 月 1 日后所有焊工判定
都被一道过渡闸门挡掉了。
"""
from __future__ import annotations

from libs.review_orchestrator import welder_coverage
from libs.review_orchestrator.deterministic_tools import qualification_coverage_outcome

V2010 = welder_coverage.RULE_VERSION_2010
V2026 = welder_coverage.RULE_VERSION_2026


def _outcome(qualification: dict, work: dict, version: str) -> str:
    return qualification_coverage_outcome(qualification, work, rule_version=version)


def _base_qualification(**overrides) -> dict:
    item = {
        "weldingMethod": "GTAW",
        "materialCategory": "FEII",
        "position": "6G",
        "thicknessMin": 0,
        "thicknessMax": 12,
        "diameterMin": 25,
        "diameterMax": None,
        "fillerMetal": "FEFS",
        "processFactors": ["02", "11", "12"],
    }
    item.update(overrides)
    return item


def _base_work(**overrides) -> dict:
    item = {
        "weldingMethod": "GTAW",
        "materialCategory": "FEII",
        "position": "6G",
        "thickness": 4.5,
        "diameter": 89,
    }
    item.update(overrides)
    return item


def test_材料类别_2026三类互认_2010只允许高覆盖低():
    """A4.3.2.1.1(1)：FeⅠ、FeⅡ、FeⅢ 任一合格即视为三类均通过。

    2010 版是 FeⅢ⊇FeⅡ⊇FeⅠ 的单向覆盖，所以 FeⅠ 证遇 FeⅢ 母材判不覆盖。
    """
    fe1_cert = _base_qualification(materialCategory="FEI")
    fe3_work = _base_work(materialCategory="FEIII")
    assert _outcome(fe1_cert, fe3_work, V2026) == welder_coverage.COVERED
    assert _outcome(fe1_cert, fe3_work, V2010) == welder_coverage.NOT_COVERED

    # (2) FeⅣ 两版都要单独取证，FeⅠ~Ⅲ 一律不覆盖。
    fe4_work = _base_work(materialCategory="FEIV")
    assert _outcome(fe1_cert, fe4_work, V2026) == welder_coverage.NOT_COVERED
    assert _outcome(_base_qualification(materialCategory="FEIII"), fe4_work, V2026) == welder_coverage.NOT_COVERED


def test_位置_5G按表A6覆盖平立仰():
    """表 A-6：管对接 5G→平、立、仰。2010 版表只映射到 {1G, 5G}，立焊、仰焊被漏掉。"""
    cert = _base_qualification(position="5G")
    for position in ("1G", "3G", "4G", "5G"):
        assert _outcome(cert, _base_work(position=position), V2026) == welder_coverage.COVERED, position
    assert _outcome(cert, _base_work(position="2G"), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(cert, _base_work(position="3G"), V2010) == welder_coverage.NOT_COVERED


def test_位置_向下焊与向上焊互不覆盖():
    """A4.3.5.1(3)。6G 是全部向上位置，不含向下立焊。"""
    assert _outcome(_base_qualification(position="6G"), _base_work(position="6GX"), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(_base_qualification(position="6GX"), _base_work(position="6G"), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(_base_qualification(position="6GX"), _base_work(position="3GX"), V2026) == welder_coverage.COVERED


def test_位置_没有覆盖表的代号说不准而不是不覆盖():
    """管板试件（6FG/5FG/2FRG/2FG）本模块没有表，不能因此判焊工超范围。"""
    cert = _base_qualification(position="6FG")
    assert _outcome(cert, _base_work(position="6FG"), V2026) == welder_coverage.COVERED
    assert _outcome(cert, _base_work(position="5FG"), V2026) == welder_coverage.UNDECIDABLE


def test_填充金属_按表A3覆盖链而不是完全相等():
    """Fef3J（低氢碱性）→ Fef1/Fef3/Fef3J；2010 版代码要求完全相等。"""
    cert = _base_qualification(fillerMetal="FEF3J")
    assert _outcome(cert, _base_work(fillerMetal="FEF3"), V2026) == welder_coverage.COVERED
    assert _outcome(cert, _base_work(fillerMetal="FEF1"), V2026) == welder_coverage.COVERED
    assert _outcome(cert, _base_work(fillerMetal="FEF4"), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(cert, _base_work(fillerMetal="FEF3"), V2010) == welder_coverage.NOT_COVERED
    # 反向不成立：Fef3 的证不能焊 Fef3J。
    assert _outcome(_base_qualification(fillerMetal="FEF3"), _base_work(fillerMetal="FEF3J"), V2026) == welder_coverage.NOT_COVERED


def test_工艺因素_加背面充氩不算变更_去掉才算():
    """A4.3.9.1 的受管辖清单里有 10（有背面保护气）、没有 11（无）。

    无背面充氩考出来的证，改为有背面充氩不算变更；反之须重考。
    """
    no_gas_cert = _base_qualification(processFactors=["02", "11", "12"])
    assert _outcome(no_gas_cert, _base_work(processFactors=["02", "10", "12"]), V2026) == welder_coverage.COVERED

    gas_cert = _base_qualification(processFactors=["02", "10", "12"])
    assert _outcome(gas_cert, _base_work(processFactors=["02", "11", "12"]), V2026) == welder_coverage.NOT_COVERED

    # FeⅢ 的 10 变更豁免，两个方向都不算变更。
    fe3_gas_cert = _base_qualification(materialCategory="FEIII", processFactors=["02", "10", "12"])
    fe3_work = _base_work(materialCategory="FEIII", processFactors=["02", "11", "12"])
    assert _outcome(fe3_gas_cert, fe3_work, V2026) == welder_coverage.COVERED


def test_工艺因素_极性与填充形式变更须重考():
    """12 直流正接 / 13 直流反接 / 14 交流任一变更、实心 02 改药芯 03，都要重考。"""
    cert = _base_qualification(processFactors=["02", "11", "12"])
    assert _outcome(cert, _base_work(processFactors=["02", "11", "13"]), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(cert, _base_work(processFactors=["03", "11", "12"]), V2026) == welder_coverage.NOT_COVERED
    # 不在受管辖清单里的代号不参与比较。
    assert _outcome(cert, _base_work(processFactors=["02", "11", "12", "99"]), V2026) == welder_coverage.COVERED


def test_厚度外径缺失是说不准而不是不覆盖():
    """焊接记录没写壁厚，说明资料不全，不说明焊工超范围。"""
    cert = _base_qualification()
    assert _outcome(cert, _base_work(thickness=None), V2026) == welder_coverage.UNDECIDABLE
    assert _outcome(cert, _base_work(diameter=None), V2026) == welder_coverage.UNDECIDABLE
    # 量得出来又超范围的，照旧判不覆盖（试件 t=3 时焊件最大 2t）。
    assert _outcome(_base_qualification(thicknessMax=6), _base_work(thickness=14), V2026) == welder_coverage.NOT_COVERED


def test_方法变更一律不覆盖_药芯归FCAW():
    """2026 版把 GMAW（实心）与 FCAW（药芯）拆成两个方法代号。"""
    cert = _base_qualification(weldingMethod="GMAW")
    assert _outcome(cert, _base_work(weldingMethod="药芯焊丝气体保护焊"), V2026) == welder_coverage.NOT_COVERED
    assert _outcome(cert, _base_work(weldingMethod="熔化极气体保护焊"), V2026) == welder_coverage.COVERED
