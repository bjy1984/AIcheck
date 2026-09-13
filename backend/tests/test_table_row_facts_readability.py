"""一张表被拆成 N 行事实时，界面上不能出现「N 条一模一样」和读不懂的引文。

2026-09-13 用户截图（P-2026-ECD202 节点 25，9.1金辉焊接工艺评定20.pdf 第 3 页）：

    焊接工艺规程  1 条
    焊接工艺规程 WPS 焊接工艺评定任务书    另有 18 条同样内容
    「■拉伸试验 试验报告编号:BA2310077：试样编号 · ■拉伸试验 试验报告编号:BA2310077_2：
      试样宽度(mm) · ■拉伸试验 试验报告编号:BA2310077_3：试样厚度(mm) · …」

两个毛病，都在这里钉住：

1. 引文的键是表格抽取器给重名列自动编号出来的（`X`、`X_2`、`X_3`…），
   七个键说的是同一件事，键比值还长。
2. 19 行的标签和取值全都一样，因为 `_extract_records` 把文档级字段并进了每一行，
   行自己没抽到业务字段时文档标题就顶上来当身份。
"""
from __future__ import annotations

from libs.review_orchestrator.material_facts import build_material_judgment
from libs.review_orchestrator.r13_facts import _row_quote

# 生产原样：OCR 把表格标题格并进了每一个表头
_HEADER_ROW = {
    "■拉伸试验 试验报告编号:BA2310077": "试样编号",
    "■拉伸试验 试验报告编号:BA2310077_2": "试样宽度(mm)",
    "■拉伸试验 试验报告编号:BA2310077_3": "试样厚度(mm)",
    "■拉伸试验 试验报告编号:BA2310077_4": "横截面积( $mm^2$ )",
}
_DATA_ROW = {
    "■拉伸试验 试验报告编号:BA2310077": "LS-1",
    "■拉伸试验 试验报告编号:BA2310077_8": "断母材",
}


def test_自动编号的重名列只给值():
    assert _row_quote(_DATA_ROW) == "LS-1 · 断母材"
    assert _row_quote(_HEADER_ROW) == "试样编号 · 试样宽度(mm) · 试样厚度(mm) · 横截面积( $mm^2$ )"


def test_真正的列名照常带上():
    """别把这条规则用过头：列名不同的时候「键：值」还是最好读的形式。"""
    row = {"焊缝编号": "GH-01", "焊工姓名": "姜军", "母材牌号": "Q345R"}
    assert _row_quote(row) == "焊缝编号：GH-01 · 焊工姓名：姜军 · 母材牌号：Q345R"


def test_同名但只有一列时不动():
    assert _row_quote({"试样编号": "LS-1"}) == "试样编号：LS-1"


def _wps_record(sample: str) -> dict:
    """一行力学性能数据：行自己没有业务字段，documentNo 来自文档级抽取，19 行全一样。"""
    return {
        "documentNo": "焊接工艺评定任务书",
        "documentVersionId": "DV-EE3CC820-V1",
        "evidence": {"evidenceRefId": "R25EV-" + sample, "quotedText": sample, "pageNo": 3},
    }


def test_每行都一样的文档级取值不能当行身份():
    """19 行取值全是「焊接工艺评定任务书」——那是文档标题，区分不了行。"""
    records = [_wps_record(name) for name in ("LS-1", "LS-2", "MW-1", "BW-1")]
    facts = build_material_judgment([("r25-wpsItems", records, ("procedureNo", "wpsNo"))])["judgment"]["claimedFacts"]

    assert len(facts) == 4
    assert {fact["value"] for fact in facts} == {None}, "文档级常量不该顶替行身份"
    assert {fact["label"] for fact in facts} == {"焊接工艺规程 WPS"}, "标签不该带上文档标题"


def test_行自己有身份时照常显示():
    """反过来要成立：documentNo 各不相同就是真的行身份，不能一起清掉。"""
    records = [
        {"documentNo": f"WPS-{index}", "evidence": {"evidenceRefId": f"E{index}"}}
        for index in (1, 2, 3)
    ]
    facts = build_material_judgment([("r25-wpsItems", records, ("procedureNo",))])["judgment"]["claimedFacts"]
    assert [fact["value"] for fact in facts] == ["WPS-1", "WPS-2", "WPS-3"]
    assert facts[0]["label"] == "焊接工艺规程 WPS WPS-1"


def test_只有两条时不判文档级():
    """两条恰好相同太常见（同一批的两个试样），误伤比漏判贵。"""
    records = [{"documentNo": "同一个编号", "evidence": {"evidenceRefId": f"E{i}"}} for i in (1, 2)]
    facts = build_material_judgment([("r25-wpsItems", records, ("procedureNo",))])["judgment"]["claimedFacts"]
    assert [fact["value"] for fact in facts] == ["同一个编号", "同一个编号"]
