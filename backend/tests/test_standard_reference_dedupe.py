"""同一份标准只发一次——去重在源头做。

## 线上实测（2026-08-16，NDT 节点 40）

    referencedStandards   发来 69 条 → 去重后 23 条 → **46 条是重复的**

每条 451 字节，白传约 20 KB。而前端已经在自己去重
（Workbench.vue nodeReferencedStandards 里那段 seen/Set）——
让每个调用方各去一遍，是把同一件事做 N 遍，还容易有人漏做。

## 一条更重要的判据

去重键取不到时**原样保留**，不能因为字段缺失把条目丢掉：
审查依据少一条，比多一条重复危险得多。少的那条可能正是判定所依赖的标准，
而没有人会发现它不见了。
"""

from __future__ import annotations

from apps.api.routes import dedupe_standard_references


def test_同一份标准只留一条():
    items = [
        {"reference": "NB/T 47013.1-2015", "sourceRelativePath": "rules/standards/a.md"},
        {"reference": "NB/T 47013.1-2015", "sourceRelativePath": "rules/standards/a.md"},
        {"reference": "NB/T 47013.1-2015", "sourceRelativePath": "rules/standards/a.md"},
        {"reference": "TSG D7006-2020", "sourceRelativePath": "rules/standards/b.md"},
    ]
    result = dedupe_standard_references(items)
    assert len(result) == 2
    assert [item["sourceRelativePath"] for item in result] == [
        "rules/standards/a.md",
        "rules/standards/b.md",
    ], "要保持原有顺序——顺序变了，界面上的引用清单会莫名其妙重排"


def test_去重键按前端同一优先级():
    """sourceRelativePath → file → fileName → reference。

    两边不一致时，后端以为去重了、前端又去一遍，
    最终显示的条数对不上——那种不一致最难查。
    """
    items = [
        {"file": "rules/x.md", "reference": "甲"},
        {"file": "rules/x.md", "reference": "乙"},  # file 相同 → 同一份
    ]
    assert len(dedupe_standard_references(items)) == 1

    items2 = [
        {"fileName": "x.md", "reference": "甲"},
        {"fileName": "y.md", "reference": "甲"},  # fileName 不同 → 两份
    ]
    assert len(dedupe_standard_references(items2)) == 2


def test_取不到键就原样保留():
    """**宁可多发一条，也不要把一条真实引用悄悄丢掉。**

    审查依据少一条，比多一条重复危险得多——少的那条可能正是判定所依赖的标准，
    而没有人会发现它不见了。
    """
    items = [{}, {}, {"note": "无任何标识字段"}]
    assert len(dedupe_standard_references(items)) == 3


def test_非字典条目跳过():
    assert dedupe_standard_references(["字符串", None, 123]) == []


def test_空输入不炸():
    assert dedupe_standard_references([]) == []
