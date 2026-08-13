"""把 OCR 产物整理成界面能直接用的结构化视图。

线上实测（贵州化工施工方案.pdf）后端已经抽出这些东西：

    layoutBlocks 261 条（blockType: text 234 / table 9 / image 1 / page_number 17）
    tables         1 张（带 html 与 normalizedRows，5 行 × 6 列）
    seals          2 枚（sealType / sealName / 证据级别 / 页码 / bbox）
    pages         19 页
    fragments    251 条
    fields         9 个

而文件详情右侧只显示了那 9 个字段——表格、印章、版面结构一条都没露出来。
监检核对「焊丝牌号与母材是否匹配」靠的就是表格，确认「有没有盖章」靠的就是印章。

这里做三件事：
1. 只挑界面要用的字段下发。原始 block 带 coordinateTransform、sourceEngine、
   qualityFlags 等实现细节，全量下发会把响应撑大好几倍（U-2 刚治过这个）。
2. 表格给 normalizedRows（已是 {列名: 值} 字典）与 rows/columns，**不下发 html**
   ——OCR 引擎产出的 html 直接渲染是 XSS 面，前端按结构自己画更安全。
3. 正文按 readingOrder 排序，保留 blockType，让界面能区分标题与正文。
"""

from __future__ import annotations

from typing import Any

# 单份资料下发上限。261 个 block 全发会让响应膨胀，而监检在右侧面板里
# 也不可能逐条读——超出部分由「查看原文」承担。
MAX_LAYOUT_BLOCKS = 120
MAX_TABLES = 20
MAX_SEALS = 20

# page_number 是版面元素不是内容，展示出来只会干扰阅读
SKIPPED_BLOCK_TYPES = {"page_number"}


def _clean_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        box = [float(x) for x in value[:4]]
    except (TypeError, ValueError):
        return None
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def structured_layout_blocks(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    """正文结构：按阅读顺序排列，保留块类型。"""
    blocks = [
        item
        for item in parse_result.get("layoutBlocks") or []
        if isinstance(item, dict)
        and str(item.get("blockType") or "") not in SKIPPED_BLOCK_TYPES
        and str(item.get("text") or "").strip()
    ]
    blocks.sort(key=lambda item: (int(item.get("pageNo") or 0), int(item.get("readingOrder") or 0)))
    return [
        {
            "blockId": str(item.get("blockId") or ""),
            "blockType": str(item.get("blockType") or "text"),
            "text": str(item.get("text") or "").strip(),
            "pageNo": item.get("pageNo"),
            "bbox": _clean_bbox(item.get("bbox")),
        }
        for item in blocks[:MAX_LAYOUT_BLOCKS]
    ]


def structured_tables(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    """表格：给结构化行，不给 html。

    引擎产出的 html 直接 v-html 渲染是 XSS 面；normalizedRows 已经是
    {列名: 值} 的字典数组，前端自己画表更安全，也更容易做列对齐与高亮。
    """
    results: list[dict[str, Any]] = []
    for item in parse_result.get("tables") or []:
        if not isinstance(item, dict):
            continue
        normalized = [row for row in item.get("normalizedRows") or [] if isinstance(row, dict)]
        cells = [
            str(cell.get("text") or "") if isinstance(cell, dict) else str(cell or "")
            for cell in item.get("cells") or []
        ]
        if not normalized and not cells:
            continue
        results.append(
            {
                "tableId": str(item.get("tableId") or item.get("candidateId") or ""),
                "pageNo": item.get("pageNo"),
                "rows": item.get("rows"),
                "columns": item.get("columns"),
                "columnNames": list(normalized[0].keys()) if normalized else [],
                "normalizedRows": normalized,
                "cells": cells if not normalized else [],
                "bbox": _clean_bbox(item.get("bbox")),
                "confidence": item.get("confidence"),
                # 这张表能不能充当规则要求的必备表格——监检据此判断还缺什么
                "matchedRequired": item.get("matchedRequired"),
                "candidateOnly": bool(item.get("candidateOnly")),
            }
        )
        if len(results) >= MAX_TABLES:
            break
    return results


def structured_seals(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    """印章与签名：监检确认「盖没盖章」的直接依据。"""
    results: list[dict[str, Any]] = []
    for kind, key in (("seal", "seals"), ("signature", "signatures")):
        for item in parse_result.get(key) or []:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "kind": kind,
                    "id": str(item.get("sealId") or item.get("signatureId") or ""),
                    # sealName 里有时塞的是整段上下文文本，界面要截断显示
                    "name": str(item.get("sealName") or item.get("text") or "").strip(),
                    "sealType": str(item.get("sealType") or ""),
                    "pageNo": item.get("pageNo"),
                    "bbox": _clean_bbox(item.get("bbox")),
                    "confidence": item.get("ocrConfidence") or item.get("confidence"),
                    "evidenceLevel": str(item.get("sealEvidenceLevel") or ""),
                    # 能否满足规则要求的「必须盖章」——不是所有识别到的章都算数
                    "canSatisfyRequired": bool(item.get("canSatisfyRequiredSeal")),
                }
            )
            if len(results) >= MAX_SEALS:
                return results
    return results


def build_ocr_structured_view(repo: Any, document: dict[str, Any]) -> dict[str, Any]:
    """文件详情右侧要用的 OCR 结构化视图。"""
    from libs.ocr_readiness import _latest_parse_result

    version_id = str(document.get("currentVersionId") or "") or None
    parse_result = _latest_parse_result(repo, version_id)
    if not parse_result:
        return {
            "available": False,
            "layoutBlocks": [],
            "tables": [],
            "seals": [],
            "pageCount": 0,
            "truncated": False,
        }

    blocks = structured_layout_blocks(parse_result)
    total_blocks = len(
        [
            item
            for item in parse_result.get("layoutBlocks") or []
            if isinstance(item, dict)
            and str(item.get("blockType") or "") not in SKIPPED_BLOCK_TYPES
            and str(item.get("text") or "").strip()
        ]
    )
    return {
        "available": True,
        "parseResultId": str(parse_result.get("parseResultId") or parse_result.get("id") or ""),
        "layoutBlocks": blocks,
        "tables": structured_tables(parse_result),
        "seals": structured_seals(parse_result),
        "pageCount": len(parse_result.get("pages") or []),
        # 截断要说出来，否则用户会以为「这份资料就这些内容」
        "truncated": total_blocks > len(blocks),
        "totalBlockCount": total_blocks,
    }
