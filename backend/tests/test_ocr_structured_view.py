"""OCR 结构化视图（线上审计后续）。

线上一份资料后端已抽出 layoutBlocks 261 条、tables 1 张（带 normalizedRows）、
seals 2 枚、pages 19 页，而文件详情右侧只显示了 9 个字段——表格、印章、版面结构
一条都没露出来。

监检核对「焊丝牌号与母材是否匹配」靠的就是表格，确认「有没有盖章」靠的就是印章。
"""

from __future__ import annotations

from typing import Any

from libs.ocr_structured_view import (
    MAX_LAYOUT_BLOCKS,
    build_ocr_structured_view,
    structured_layout_blocks,
    structured_seals,
    structured_tables,
)


class _Repo:
    def __init__(self, parse_result: dict[str, Any] | None) -> None:
        self.state = {"ocr_parse_results": [parse_result] if parse_result else []}


def test_blocks_follow_reading_order_across_pages() -> None:
    """正文要按阅读顺序呈现，否则读起来是乱的。"""
    result = {
        "layoutBlocks": [
            {"blockId": "b3", "blockType": "text", "text": "第二页开头", "pageNo": 2, "readingOrder": 1},
            {"blockId": "b2", "blockType": "text", "text": "第一页第二段", "pageNo": 1, "readingOrder": 2},
            {"blockId": "b1", "blockType": "title", "text": "标题", "pageNo": 1, "readingOrder": 1},
        ]
    }
    blocks = structured_layout_blocks(result)
    assert [b["blockId"] for b in blocks] == ["b1", "b2", "b3"]
    assert blocks[0]["blockType"] == "title", "块类型要保留，界面据此区分标题与正文"


def test_page_number_blocks_are_dropped() -> None:
    """页码是版面元素不是内容，混在正文里只会干扰阅读。"""
    result = {
        "layoutBlocks": [
            {"blockId": "p", "blockType": "page_number", "text": "- 7 -", "pageNo": 7, "readingOrder": 1},
            {"blockId": "t", "blockType": "text", "text": "正文", "pageNo": 7, "readingOrder": 2},
        ]
    }
    assert [b["blockId"] for b in structured_layout_blocks(result)] == ["t"]


def test_empty_text_blocks_are_dropped() -> None:
    result = {
        "layoutBlocks": [
            {"blockId": "a", "blockType": "text", "text": "   ", "pageNo": 1, "readingOrder": 1},
            {"blockId": "b", "blockType": "text", "text": "有内容", "pageNo": 1, "readingOrder": 2},
        ]
    }
    assert [b["blockId"] for b in structured_layout_blocks(result)] == ["b"]


def test_tables_expose_structured_rows_not_engine_html() -> None:
    """不下发引擎产出的 html。

    直接 v-html 渲染引擎输出是 XSS 面；normalizedRows 已经是 {列名: 值}，
    前端按结构自己画更安全，也更容易做列对齐与高亮。
    """
    result = {
        "tables": [
            {
                "tableId": "T1",
                "pageNo": 2,
                "rows": 2,
                "columns": 3,
                "html": '<table><script>alert(1)</script></table>',
                "normalizedRows": [
                    {"序号": "1", "管道材料": "A106、A105、20#", "焊丝牌号": "TIG50"},
                ],
                "matchedRequired": True,
            }
        ]
    }
    tables = structured_tables(result)
    assert len(tables) == 1
    assert "html" not in tables[0], "引擎 html 不得下发"
    assert tables[0]["columnNames"] == ["序号", "管道材料", "焊丝牌号"]
    assert tables[0]["normalizedRows"][0]["焊丝牌号"] == "TIG50"
    assert tables[0]["matchedRequired"] is True


def test_tables_fall_back_to_cells_when_rows_are_not_normalized() -> None:
    """有些表格只有单元格没有归一化行，也要能展示，而不是整张丢掉。"""
    result = {"tables": [{"tableId": "T2", "cells": [{"text": "序号"}, {"text": "1"}]}]}
    tables = structured_tables(result)
    assert tables[0]["cells"] == ["序号", "1"]


def test_seals_and_signatures_are_merged_with_their_kind() -> None:
    """印章与签名都是「盖没盖章」这件事的证据，合成一区但要能分辨。"""
    result = {
        "seals": [
            {
                "sealId": "s1",
                "sealName": "省特检院质量专用章",
                "sealType": "quality_seal",
                "pageNo": 7,
                "ocrConfidence": 0.82,
                "sealEvidenceLevel": "visual_plus_page_text",
                "canSatisfyRequiredSeal": True,
            }
        ],
        "signatures": [{"signatureId": "g1", "text": "张工", "pageNo": 3}],
    }
    seals = structured_seals(result)
    assert [x["kind"] for x in seals] == ["seal", "signature"]
    assert seals[0]["canSatisfyRequired"] is True
    assert seals[0]["evidenceLevel"] == "visual_plus_page_text"


def test_bbox_is_validated_not_passed_through() -> None:
    """零宽/反向框画出来是错的，宁可不给坐标。"""
    result = {
        "layoutBlocks": [
            {"blockId": "a", "blockType": "text", "text": "x", "bbox": [10, 20, 10, 70], "readingOrder": 1},
            {"blockId": "b", "blockType": "text", "text": "y", "bbox": [10, 20, 110, 70], "readingOrder": 2},
        ]
    }
    blocks = structured_layout_blocks(result)
    assert blocks[0]["bbox"] is None
    assert blocks[1]["bbox"] == [10.0, 20.0, 110.0, 70.0]


def test_truncation_is_reported_so_users_know_there_is_more() -> None:
    """截断必须说出来，否则用户会以为「这份资料就这些内容」。"""
    result = {
        "documentVersionId": "DV-1",
        "layoutBlocks": [
            {"blockId": f"b{i}", "blockType": "text", "text": f"第{i}段", "pageNo": 1, "readingOrder": i}
            for i in range(MAX_LAYOUT_BLOCKS + 30)
        ],
        "pages": [{}] * 3,
    }
    view = build_ocr_structured_view(_Repo(result), {"currentVersionId": "DV-1"})
    assert view["available"] is True
    assert len(view["layoutBlocks"]) == MAX_LAYOUT_BLOCKS
    assert view["truncated"] is True
    assert view["totalBlockCount"] == MAX_LAYOUT_BLOCKS + 30


def test_missing_parse_result_reports_unavailable_not_empty_success() -> None:
    """没有 OCR 产物和「产物为空」是两回事，界面要能分辨。"""
    view = build_ocr_structured_view(_Repo(None), {"currentVersionId": "DV-X"})
    assert view["available"] is False
    assert view["layoutBlocks"] == []
    assert view["pageCount"] == 0


def test_column_order_comes_from_header_cells_not_dict_keys() -> None:
    """列序取自表头单元格的 col 下标，不取字典键序。

    state 存在 Postgres 的 jsonb 列里，jsonb 不保留对象键序。线上这张焊材表
    存进去是「序号 / 管道材料 / …」，取出来键序变成了「备注 / 序号 / 焊条 / …」。
    用例里的 normalizedRows 就按取出来的乱序写，确保修复真的生效。
    """
    parse_result = {
        "tables": [
            {
                "tableId": "T-1",
                "pageNo": 3,
                "cells": [
                    {"row": 0, "col": 0, "text": "序号", "isHeader": True},
                    {"row": 0, "col": 1, "text": "管道材料", "isHeader": True},
                    {"row": 0, "col": 2, "text": "焊丝牌号", "isHeader": True},
                    {"row": 1, "col": 0, "text": "1", "isHeader": False},
                ],
                # jsonb 取回后的键序：按键长 + 字节序重排
                "normalizedRows": [{"序号": "1", "焊丝牌号": "TIG50", "管道材料": "A106"}],
            }
        ]
    }
    table = structured_tables(parse_result)[0]
    assert table["columnNames"] == ["序号", "管道材料", "焊丝牌号"]


def test_column_order_falls_back_to_keys_when_header_missing() -> None:
    """没有表头单元格时退回键序——列序不理想，但一列都不能丢。"""
    parse_result = {
        "tables": [
            {
                "tableId": "T-2",
                "cells": [],
                "normalizedRows": [{"甲": "1", "乙": "2"}],
            }
        ]
    }
    assert structured_tables(parse_result)[0]["columnNames"] == ["甲", "乙"]


def test_columns_absent_from_header_are_appended_not_dropped() -> None:
    """表头对不上的列补在后面。合并单元格会让表头缺项，丢列等于丢证据。"""
    parse_result = {
        "tables": [
            {
                "tableId": "T-3",
                "cells": [{"row": 0, "col": 0, "text": "序号", "isHeader": True}],
                "normalizedRows": [{"备注": "√", "序号": "1"}],
            }
        ]
    }
    assert structured_tables(parse_result)[0]["columnNames"] == ["序号", "备注"]


def test_unrecognized_seals_are_flagged_not_silently_unnamed() -> None:
    """视觉检出但文字未识别的章要标出来，不能只显示成「（未命名）」。

    线上一份产品质量证明 9 枚章里 8 枚属于此类。显示成「未命名」会被当成
    数据缺失而略过；实际含义是「这里确实有一枚章，需要人工看图辨认」。
    """
    parse_result = {
        "seals": [
            {"candidateId": "CAND-1", "pageNo": 5, "visualRankScore": 0.8},
            {"sealId": "SEAL-1", "sealName": "质检专用章", "sealType": "quality_seal", "pageNo": 2},
        ]
    }
    seals = structured_seals(parse_result)
    # 已识别的排前面：认出文字的能直接核对，未识别的要人工看图
    assert [seal["recognized"] for seal in seals] == [True, False]
    assert seals[0]["name"] == "质检专用章"
    assert seals[1]["id"] == "CAND-1", "候选章要能用 candidateId 定位，否则点不了"


def test_recognized_seals_sort_by_page_within_group() -> None:
    """同组内按页码排——监检是顺着页码翻的。"""
    parse_result = {
        "seals": [
            {"sealId": "S-9", "sealName": "章九", "pageNo": 9},
            {"sealId": "S-2", "sealName": "章二", "pageNo": 2},
            {"candidateId": "C-7", "pageNo": 7},
            {"candidateId": "C-1", "pageNo": 1},
        ]
    }
    assert [s["pageNo"] for s in structured_seals(parse_result)] == [2, 9, 1, 7]


def test_signatures_stay_after_seals_even_on_earlier_pages() -> None:
    """印章与签名是不同性质的证据，不能因页码穿插而打散分组。"""
    parse_result = {
        "seals": [{"sealId": "s1", "sealName": "质检章", "pageNo": 7}],
        "signatures": [{"signatureId": "g1", "text": "张工", "pageNo": 3}],
    }
    assert [s["kind"] for s in structured_seals(parse_result)] == ["seal", "signature"]


def test_sparse_header_is_marked_unreliable() -> None:
    """键值式表格的零星 isHeader 不能当表头。

    照搬线上那份质量证明书的真实数字：网格 33 列，只有 4 个单元格标了 isHeader，
    其中「沈阳宝钢东北贸易有限公司」「输送管」明显是值不是列名；normalizedRows
    归出 6 个键。

    这组数字专门钉住覆盖率的**分母**：按 6 个渲染列算，4 个标记是 67%，稀疏表头
    照样被判可信（线上就是这么错的）；按 33 列网格算才是真相，12%。
    """
    parse_result = {
        "tables": [
            {
                "tableId": "T-KV",
                "columns": 33,
                "cells": [
                    {"row": 0, "col": 0, "text": "订货单位", "isHeader": True},
                    {"row": 0, "col": 4, "text": "沈阳宝钢东北贸易有限公司", "isHeader": True},
                    {"row": 0, "col": 19, "text": "产品名称", "isHeader": True},
                    {"row": 0, "col": 22, "text": "输送管", "isHeader": True},
                    {"row": 1, "col": 0, "text": "收货单位", "isHeader": False},
                ],
                "normalizedRows": [
                    {
                        "订货单位": "a",
                        "沈阳宝钢东北贸易有限公司": "b",
                        "产品名称": "c",
                        "输送管": "d",
                        "输送管_26": "e",
                        "输送管_29": "f",
                    }
                ],
            }
        ]
    }
    assert structured_tables(parse_result)[0]["headerReliable"] is False


def test_full_header_row_stays_reliable() -> None:
    """真数据网格标满表头，照常画表头行——焊材表不能被误伤。"""
    parse_result = {
        "tables": [
            {
                "tableId": "T-GRID",
                "columns": 2,
                "cells": [
                    {"row": 0, "col": 0, "text": "序号", "isHeader": True},
                    {"row": 0, "col": 1, "text": "管道材料", "isHeader": True},
                    {"row": 1, "col": 0, "text": "1", "isHeader": False},
                ],
                "normalizedRows": [{"序号": "1", "管道材料": "A106"}],
            }
        ]
    }
    assert structured_tables(parse_result)[0]["headerReliable"] is True


def test_engine_without_header_flags_keeps_row_zero_convention() -> None:
    """引擎完全没标 isHeader 时，退回「第 0 行即表头」的通行约定。"""
    parse_result = {
        "tables": [
            {
                "tableId": "T-NOFLAG",
                "columns": 2,
                "cells": [
                    {"row": 0, "col": 0, "text": "甲"},
                    {"row": 0, "col": 1, "text": "乙"},
                    {"row": 1, "col": 0, "text": "1"},
                ],
                "normalizedRows": [{"甲": "1", "乙": "2"}],
            }
        ]
    }
    table = structured_tables(parse_result)[0]
    assert table["headerReliable"] is True
    assert table["columnNames"] == ["甲", "乙"]
