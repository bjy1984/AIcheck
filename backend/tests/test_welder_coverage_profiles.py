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


def test_代号只校形状不够_OCR坏码不能报解码成功():
    """2026-09-11 生产实测：五个项目的合格项目代号全是 OCR 坏串，
    `decode_welder_qualification` 却一律 passed。

        CTAF-Fe II-6G-3/57-FetS-02/11/12和SHAV-Fe II-6G(K)-9/57-Fet3J
        SHAW-FeII-SFC-12/19-FefBJ
        PTAV-FeIV-50-5/57-FefBJ-02/16/12

    CTAF/PTAV/SHAV 不是表 A-1 里的任何方法，FetS/FefBJ 不是表 A-3 里的任何填充金属，
    SFC 不是表 A-4 里的任何位置。形状完好、内容全错——假通过比不判更贵。
    """
    from libs.review_orchestrator.deterministic_tools import decode_welder_code, decode_welder_qualification

    bad = decode_welder_code("CTAF-Fe II-6G-3/57-FetS-02/11/12")
    assert bad["parseStatus"] == "unsupported"
    assert bad["reason"] == "code_segments_not_in_profile"
    assert bad["unknownSegments"] == ["weldingMethod", "fillerMetal"]

    assert decode_welder_code("SHAW-FeII-SFC-12/19-FefBJ")["unknownSegments"] == [
        "weldingMethod",
        "position",
        "fillerMetal",
    ]

    # 真代号照旧解得出来，(K) 也不算未知位置。
    assert decode_welder_code("GTAW-FeII-6G-3/57-FefS-02/11/12")["parseStatus"] == "parsed"
    assert decode_welder_code("SMAW-FeII-6G(K)-9/57-Fef3J")["parseStatus"] == "parsed"

    output = decode_welder_qualification(
        {"qualificationCodes": ["CTAF-Fe II-6G-3/57-FetS-02/11/12"], "reviewDate": "2026-09-11"}
    )
    assert output["result"] == "evidence_insufficient"


def test_缺哪边要说出来():
    """界面只显示「证据不足」而不说缺什么时，监检人员没法知道该补什么。
    2026-09-11 归因：130 项证据不足里 85 项就是这样变成无法归因的。"""
    from libs.review_orchestrator.deterministic_tools import check_welder_work_coverage

    no_records = check_welder_work_coverage(
        {"qualificationCodes": ["GTAW-FeII-6G-3/57-FefS-02/11/12"], "workItems": [], "reviewDate": "2026-09-11"}
    )
    assert no_records["result"] == "evidence_insufficient"
    assert no_records["facts"]["reason"] == "welding_work_records_missing"

    nothing = check_welder_work_coverage({"qualificationCodes": [], "workItems": [], "reviewDate": "2026-09-11"})
    assert nothing["facts"]["reason"] == "welder_qualifications_and_welding_work_records_missing"


def test_工程范围不能漏到别的工程():
    """`_documents_by_version(state, projectId)` 的第二个循环原来把全库版本无条件补进来，
    把第一个循环的 projectId 过滤抵消掉。

    2026-09-11 全节点扫描实测：三个项目各自调用都返回 316 个版本（全库），交集 316。
    `pipeline_facts.build_project_pipelines` 与 `design_facts` 是全工程扫描，
    拿到的于是是别的工程的资料。projectId 为空的文档（生产有 60 份）不属于任何工程。
    """
    from libs.review_orchestrator.certificate_facts import _documents_by_version

    state = {
        "documents": [
            {"id": "DOC-A", "projectId": "P-A", "currentVersionId": "DV-A2"},
            {"id": "DOC-B", "projectId": "P-B", "currentVersionId": "DV-B1"},
            {"id": "DOC-NONE", "projectId": None, "currentVersionId": "DV-N1"},
        ],
        "versions": [
            {"id": "DV-A1", "documentId": "DOC-A"},
            {"id": "DV-A2", "documentId": "DOC-A"},
            {"id": "DV-B1", "documentId": "DOC-B"},
            {"id": "DV-N1", "documentId": "DOC-NONE"},
        ],
    }
    a = _documents_by_version(state, "P-A")
    # 当前版本与历史版本都要在，别的工程与无归属的都不能在。
    assert sorted(a) == ["DV-A1", "DV-A2"]
    assert sorted(_documents_by_version(state, "P-B")) == ["DV-B1"]
    assert not set(a) & set(_documents_by_version(state, "P-B"))
