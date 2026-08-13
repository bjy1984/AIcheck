"""提示词里的表格去重。

线上一张 17×6 的质量证明表在 groundedOcrEvidence 里占 25027 字符，其中：
  cells + cellsSummary  16162（同一对象，两个键名）
  rows  + normalizedRows 5906（同上）
  真实单元格值           1141
模型付三份 token 读同一张表。

这些用例钉的是「无损」：去掉的必须只有重复别名和 null，任何真实内容都不能少。
少一格内容 = 模型少一条证据 = 可能给出错结论，而且是静默的。
"""

from __future__ import annotations

import json

from libs.review_grounding import compact_tables_for_prompt, grounding_prompt_block

ROWS = [{"序号": "1", "材质": "20#"}]
CELLS = [
    {"rowIndex": 0, "columnIndex": 0, "text": "序号", "isHeader": True, "bbox": None, "confidence": None},
    {"rowIndex": 1, "columnIndex": 0, "text": "1", "isHeader": False, "bbox": None, "confidence": None},
]
TABLE = {
    "id": "T-1",
    "pageNo": 3,
    "contentMarkdown": "| 序号 | 材质 |\n| 1 | 20# |",
    "normalizedRows": ROWS,
    "rows": ROWS,
    "cells": CELLS,
    "cellsSummary": CELLS,
}


def test_alias_duplicates_are_dropped() -> None:
    """rows / cellsSummary 与 normalizedRows / cells 指向同一对象，发一份就够。"""
    out = compact_tables_for_prompt([TABLE])[0]
    assert "rows" not in out
    assert "cellsSummary" not in out
    assert out["normalizedRows"] == ROWS, "保留的那一份内容必须一字不差"
    assert [c["text"] for c in out["cells"]] == ["序号", "1"]


def test_null_cell_keys_are_dropped_but_real_values_kept() -> None:
    """bbox/confidence 为 null 时不发——「没有」这件事不值一份 token。

    但 isHeader=False 必须留下：它是真实取值，不是空。
    """
    out = compact_tables_for_prompt([TABLE])[0]
    first, second = out["cells"]
    assert "bbox" not in first and "confidence" not in first
    assert first["isHeader"] is True
    assert second["text"] == "1"
    assert second["rowIndex"] == 1


def test_no_content_is_lost() -> None:
    """压缩前后，所有真实文本必须一个不少——这是无损的定义。"""
    before = compact_tables_for_prompt.__doc__ and json.dumps(TABLE, ensure_ascii=False)
    after = json.dumps(compact_tables_for_prompt([TABLE])[0], ensure_ascii=False)
    for text in ("序号", "材质", "20#", "T-1", "contentMarkdown"):
        assert text in after, text
    assert len(after) < len(before), "没变小说明压缩没生效"


def test_non_table_payloads_pass_through_untouched() -> None:
    """形状不对时原样返回，不要在证据链上自作主张。"""
    assert compact_tables_for_prompt(None) is None
    assert compact_tables_for_prompt("not-a-list") == "not-a-list"
    assert compact_tables_for_prompt([None, 3]) == [None, 3]


def test_prompt_block_uses_the_compacted_tables() -> None:
    """接线检查：grounding_prompt_block 真的用了压缩版，不是只定义没调用。"""
    block = grounding_prompt_block({"groundingPolicy": "evidence_only", "tables": [TABLE]})
    table = block["groundedOcrEvidence"]["tables"][0]
    assert "cellsSummary" not in table
    assert "rows" not in table


def test_llm_only_branch_is_compacted_too() -> None:
    """另一条策略分支也要压——漏一条，那条链路的预算就白省了。"""
    block = grounding_prompt_block(
        {"groundingPolicy": "llm_only_human_review", "tables": [TABLE]}
    )
    table = block["groundedOcrEvidence"]["tables"][0]
    assert "cellsSummary" not in table
    assert "rows" not in table
