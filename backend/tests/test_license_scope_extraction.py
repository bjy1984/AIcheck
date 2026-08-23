"""许可范围要从表格取，抽不到就说抽不到（0817 第 6 条）。

## 用户报的问题

界面上「许可范围」显示成 **「以下特种设备生产活动」** —— 这是
「经审查，获准从事以下特种设备生产活动：」这句**引导语**的后半截，
不是许可范围。真正的许可范围在下面那张表里：

    许可项目      许可子项目
    压力管道安装   长输管道安装（GA2）
                  公用管道安装（GB1、GB2）
                  工业管道安装（GC1、GC2）

## 两层原因

1. 「获准从事」被列进了字段标签。它是引导语，不是标签。
2. 标签分支先返回了一个「看起来有值」的结果，于是真正会去找许可项目的
   find_license_scope_fragment 根本没机会跑。

## 最重要的一条判据

**抽不到要标成抽不到，不能拿相邻正文行凑一个值。**
错值在界面上和正确值长得一模一样（后面照样跟着「可定位」），
这比留空危险得多——没有人会去核对一个看起来已经填好的字段。
"""

from __future__ import annotations

from apps.ocr_service.service import (
    license_scope_from_tables,
    license_scope_text_is_usable,
    qualification_scope_candidate,
)

# 真实的许可证正文（取自 output/ocr/raw_ocr_pages.json 里那张贵州化工的证）
LICENSE_LINES = [
    "中华人民共和国",
    "特种设备生产许可证",
    "编号；TS3810436-2025",
    "单位名称：贵州化工建设有限责任公司",
    "住所：贵州省贵阳市乌当区洛湾",
    "办公地址：贵州省贵阳市南明区花果园中央商务区P5第32层",
    "经审查，获准从事以下特种设备生产活动：",
    "许可项目",
    "许可子项目",
    "许可参数",
    "备注",
    "发证机关：国家市场监督管理总局",
    "有效期至：2025年04月27日",
]

# 线上真实结构（MinerU）：rows 是**行数**不是行数组，单元格在扁平的 cells 里。
# 第一版按「rows 是行数组」写，整张表被跳过 —— 「有表格却抽不到」，
# 比抽错更隐蔽。这份夹具照抄线上 DOC-AB0A3AA4 的形状。
SCOPE_TABLE = {
    "bbox": [87.465, 374.245, 498.61, 481.893],
    "pageNo": 1,
    "rows": 4,
    "columns": 4,
    "normalizedRows": [
        {"许可项目": "压力管道安装", "许可子项目": "长输管道安装(GA2)", "许可参数": "—"},
        {"许可子项目": "公用管道安装(GB1、GB2)", "许可参数": "—"},
        {"许可子项目": "工业管道安装(GC1、GC2)", "许可参数": "—"},
    ],
    "cells": [
        {"row": 0, "col": 0, "text": "许可项目", "isHeader": True},
        {"row": 0, "col": 1, "text": "许可子项目", "isHeader": True},
        {"row": 1, "col": 0, "text": "压力管道安装", "isHeader": False},
        {"row": 1, "col": 1, "text": "长输管道安装(GA2)", "isHeader": False},
        {"row": 2, "col": 1, "text": "公用管道安装(GB1、GB2)", "isHeader": False},
        {"row": 3, "col": 1, "text": "工业管道安装(GC1、GC2)", "isHeader": False},
    ],
}

# 江苏 TS3832083-2026 的真实形状：子项目列表头是「子项目」，没有「许可」前缀；
# 而「许可项目」列填的是「承压类特种设备安装、修理、改造」——一个不含任何项目名的类别词。
# 这两件事叠在一起，恰好构成第二次失手的条件。
SCOPE_TABLE_SHORT_HEADER = {
    "bbox": [37.845, 180.688, 212.976, 265.696],
    "pageNo": 1,
    "rows": 3,
    "columns": 4,
    "normalizedRows": [
        {
            "许可项目": "承压类特种设备安装、修理、改造",
            "子项目": "公用管道安装(GB2)",
            "许可参数": "—",
            "备注": "/",
        },
        {
            "许可项目": "承压类特种设备安装、修理、改造",
            "子项目": "工业管道安装(GC2)",
            "许可参数": "—",
            "备注": "/",
        },
    ],
    "cells": [
        {"row": 0, "col": 0, "text": "许可项目", "isHeader": True},
        {"row": 0, "col": 1, "text": "子项目", "isHeader": True},
        {"row": 0, "col": 2, "text": "许可参数", "isHeader": True},
        {"row": 0, "col": 3, "text": "备注", "isHeader": True},
        {"row": 1, "col": 0, "text": "承压类特种设备安装、修理、改造", "isHeader": False},
        {"row": 1, "col": 1, "text": "公用管道安装(GB2)", "isHeader": False},
        {"row": 1, "col": 2, "text": "—", "isHeader": False},
        {"row": 1, "col": 3, "text": "/", "isHeader": False},
        {"row": 2, "col": 0, "text": "承压类特种设备安装、修理、改造", "isHeader": False},
        {"row": 2, "col": 1, "text": "工业管道安装(GC2)", "isHeader": False},
        {"row": 2, "col": 2, "text": "—", "isHeader": False},
        {"row": 2, "col": 3, "text": "/", "isHeader": False},
    ],
}

# 另一种上游形状：行数组。两种都要认。
SCOPE_TABLE_ROW_ARRAY = {
    "rows": [
        ["许可项目", "许可子项目", "许可参数", "备注"],
        ["压力管道安装", "长输管道安装（GA2）", "", ""],
        ["", "工业管道安装（GC1、GC2）", "", ""],
    ]
}


def _items(lines: list[str]) -> list[tuple[str, dict]]:
    return [(line, {"text": line}) for line in lines]


def test_引导语后半截不算许可范围():
    """这是用户实际看到的那个错值。"""
    assert license_scope_text_is_usable("以下特种设备生产活动") is False
    assert license_scope_text_is_usable("以下特种设备生产活动：") is False
    assert license_scope_text_is_usable("如下生产活动") is False
    assert license_scope_text_is_usable("") is False


def test_真正的许可项目算许可范围():
    assert license_scope_text_is_usable("工业管道安装（GC1、GC2）") is True
    assert license_scope_text_is_usable("压力管道安装") is True
    assert license_scope_text_is_usable("长输管道安装（GA2）") is True


def test_从表格里取到全部许可子项目():
    found = license_scope_from_tables({"tables": [SCOPE_TABLE]})
    assert found, "表格里明明有许可项目，却没取到"
    text = found["text"]
    for expected in ("压力管道安装", "长输管道安装(GA2)", "公用管道安装(GB1、GB2)", "工业管道安装(GC1、GC2)"):
        assert expected in text, f"少了 {expected}"
    assert "许可项目" not in text, "表头被当成了范围"
    assert "备注" not in text


def test_有表格时表格优先():
    """正文里那句引导语仍然在，但不该再影响结果。"""
    found = qualification_scope_candidate(_items(LICENSE_LINES), {"tables": [SCOPE_TABLE]})
    assert found
    assert "GC1" in found["text"]
    assert "以下特种设备生产活动" not in found["text"]


def test_没有表格时宁可返回空也不要错值():
    """**最重要的一条。**

    没有表格、正文里只有引导语时，正确行为是返回 None（界面上显示未提取），
    而不是把「以下特种设备生产活动」填进去。
    """
    found = qualification_scope_candidate(_items(LICENSE_LINES), {"tables": []})
    assert found is None, f"抽不到却填了一个值：{found}"


def test_没有表格但正文里有真实项目时仍然能取到():
    """护栏不能把正确的路一起堵死。"""
    lines = [*LICENSE_LINES, "压力管道安装（GC1、GC2）"]
    found = qualification_scope_candidate(_items(lines), {"tables": []})
    assert found
    assert "GC1" in found["text"]


def test_只用normalizedRows时不把许可参数串进来():
    """「许可参数＝—」不是许可范围。"""
    text = license_scope_from_tables({"tables": [SCOPE_TABLE]})["text"]
    assert "—" not in text


def test_cells形状也能读():
    """normalizedRows 缺失时退回扁平 cells，并跳过表头。"""
    table = {k: v for k, v in SCOPE_TABLE.items() if k != "normalizedRows"}
    text = license_scope_from_tables({"tables": [table]})["text"]
    assert "工业管道安装(GC1、GC2)" in text
    assert "许可子项目" not in text, "表头被当成了范围"


def test_子项目列名没有许可前缀时也能读():
    """列名写死成「许可子项目」的话，这一整列读不到——而只有它带 GB2/GC2。"""
    found = license_scope_from_tables({"tables": [SCOPE_TABLE_SHORT_HEADER]})
    assert found, "「子项目」列被漏掉了"
    text = found["text"]
    assert "公用管道安装(GB2)" in text
    assert "工业管道安装(GC2)" in text
    assert "—" not in text, "许可参数被串进来了"
    assert "备注" not in text


def test_许可项目列不可用时不挡住cells兜底():
    """normalizedRows 吐出「承压类特种设备安装、修理、改造」——非空，但不含任何项目名。

    只要提前返回的条件是「有文字」而不是「有可用值」，这个类别词就会顶掉 cells 兜底，
    界面上变成「有表格却抽不到」。
    """
    table = {k: v for k, v in SCOPE_TABLE_SHORT_HEADER.items() if k != "normalizedRows"}
    table["normalizedRows"] = [{"许可项目": "承压类特种设备安装、修理、改造"}]
    found = license_scope_from_tables({"tables": [table]})
    assert found, "不可用的许可项目值把 cells 兜底挡掉了"
    assert "GC2" in found["text"]


def test_行数组形状也能读():
    text = license_scope_from_tables({"tables": [SCOPE_TABLE_ROW_ARRAY]})["text"]
    assert "工业管道安装（GC1、GC2）" in text
    assert "许可项目" not in text


def test_rows是行数时不会把整张表跳过():
    """第一版就是在这里失手的：rows=4 是行数，isinstance(rows, list) 为假，
    整张表被跳过 —— 界面上变成「有表格却抽不到」。"""
    assert isinstance(SCOPE_TABLE["rows"], int)
    assert license_scope_from_tables({"tables": [SCOPE_TABLE]}) is not None


def test_表格结构异常时不炸():
    for tables in (None, "x", [None], [{"rows": None}], [{"rows": [None, "x"]}]):
        assert license_scope_from_tables({"tables": tables}) is None


def test_获准从事不再是字段标签():
    """只要它还在标签名单里，标签分支就会先抢到一个错值。"""
    import inspect

    source = inspect.getsource(qualification_scope_candidate)
    labels = source.split("[", 1)[1].split("]", 1)[0] if "[" in source else ""
    assert "获准从事" not in labels, "「获准从事」又被当成字段标签了"
