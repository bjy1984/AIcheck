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


def header_row_texts(item: dict[str, Any]) -> list[str]:
    """表头行的文本，按 col 下标排。

    返回空表示这张表没有可当表头的单元格——此时列名只能来自 normalizedRows 的
    字典键，那些键从来不是某一行的内容，后面也就无所谓「把表头行补回数据」。
    """
    cells = [cell for cell in item.get("cells") or [] if isinstance(cell, dict)]
    marked = any(cell.get("isHeader") is not None for cell in cells)
    header: list[tuple[int, str]] = []
    for cell in cells:
        # 引擎标了 isHeader 就认它；整张表都没标才退回第 0 行
        is_header = cell.get("isHeader") if marked else int(cell.get("row") or 0) == 0
        if not is_header:
            continue
        text = str(cell.get("text") or "").strip()
        if text:
            header.append((int(cell.get("col") or 0), text))
    return [text for _, text in sorted(header, key=lambda pair: pair[0])]


def table_column_names(item: dict[str, Any], normalized: list[dict[str, Any]]) -> list[str]:
    """还原表格的真实列序。

    不能直接用 normalizedRows[0].keys()：state 存在 Postgres 的 jsonb 列里，
    而 jsonb 不保留对象键序（它按「键长 + 字节序」重排）。线上那张焊材表原本是
    「序号 / 管道材料 / 焊丝牌号 / 焊丝规格 / 焊条 / 备注」，取回来变成
    「备注 / 序号 / 焊条 / 焊丝牌号 / 焊丝规格 / 管道材料」——序号跑到第二列，
    监检对着这样的参数表核不了「焊丝牌号与母材是否匹配」。

    cells 是数组，jsonb 保留数组顺序，且每个单元格自带 row/col/isHeader，
    所以列序从表头行的 col 下标还原，而不是从字典键序。
    """
    ordered = header_row_texts(item)
    if not normalized:
        return ordered
    keys = set(normalized[0].keys())
    # 表头与 normalizedRows 的键未必完全一致（合并单元格、空表头），
    # 对得上的按表头排，对不上的补在后面，绝不丢列。
    names = [name for name in ordered if name in keys]
    names.extend(key for key in normalized[0] if key not in set(names))
    return names


def table_grid_columns(item: dict[str, Any]) -> int:
    """引擎网格的真实列数。

    覆盖率必须拿它当分母，不能拿渲染出来的列数。线上那份质量证明书网格是 33 列，
    但 normalizedRows 只归出 6 个键——按 6 算，4 个表头标记就成了 67% 覆盖率，
    稀疏表头照样被判成可信。按 33 算才是真相：12%。
    """
    declared = item.get("columns")
    if isinstance(declared, int) and declared > 0:
        return declared
    cols = [
        int(cell.get("col") or 0)
        for cell in item.get("cells") or []
        if isinstance(cell, dict)
    ]
    return max(cols) + 1 if cols else 0


def table_header_is_reliable(item: dict[str, Any], column_count: int) -> bool:
    """这张表到底有没有可用的表头。

    引擎对键值式表格（质量证明书抬头区那种「标签: 值」布局）会零星标几个
    isHeader，而不是标满一行。线上那份质量证明书 33 列只标了 4 个，其中
    「沈阳宝钢东北贸易有限公司」「输送管」明显是**值**不是列名。照单全收当表头，
    界面就会把一个供货单位名字印成列标题——凭空发明出一个并不存在的结构。

    实测分布是干净的两极：真数据网格标满（3/3、5/5、6/6），键值式表格稀疏
    （4/33、7/21）。所以按覆盖率判断：标到一半列以上才算表头。

    宁可不给表头、按原始网格展示——少一层解读，好过多一层错误解读。
    """
    if column_count <= 0:
        return False
    cells = [cell for cell in item.get("cells") or [] if isinstance(cell, dict)]
    if not cells:
        return False
    if all(cell.get("isHeader") is None for cell in cells):
        # 引擎完全没标——退回「第 0 行即表头」的通行约定
        return True
    header_cols = {int(cell.get("col") or 0) for cell in cells if cell.get("isHeader")}
    return len(header_cols) * 2 >= column_count


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
        column_names = table_column_names(item, normalized)
        header_reliable = table_header_is_reliable(item, table_grid_columns(item))
        header_texts = set(header_row_texts(item))
        if not header_reliable and normalized and header_texts:
            # 表头不可信时界面不画表头行，那被当成列名消费掉的那一行内容就得补回
            # 数据里——它们本来就是表格里的字（线上那张质量证明书的「订货单位 /
            # 沈阳宝钢东北贸易有限公司」就在这一行）。不补，18 行只显示 17 行，
            # 整行凭空消失：隐藏证据比错标一个表头更糟。
            #
            # 只补真来自表头行的列。引擎为重名列凭空造的键（输送管_26 之类）不是
            # 表格里的字，填进去就是伪造内容，留空。
            normalized = [
                {name: (name if name in header_texts else "") for name in column_names},
                *normalized,
            ]
        results.append(
            {
                "tableId": str(item.get("tableId") or item.get("candidateId") or ""),
                "pageNo": item.get("pageNo"),
                "rows": item.get("rows"),
                "columns": item.get("columns"),
                "columnNames": column_names,
                # 表头不可信时界面不画表头行——见 table_header_is_reliable
                "headerReliable": header_reliable,
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
    """印章与签名：监检确认「盖没盖章」的直接依据。

    引擎给的是两类记录，混在一起显示会误导：

      已识别章  带 sealName / sealType / sealEvidenceLevel，文字认出来了；
      候选章    只有 candidateId / visualRankScore / imagePath——视觉上确实
                检出一枚章，但文字没认出来。

    线上一份产品质量证明里 9 枚章有 8 枚是后者。之前一律显示成「（未命名）」，
    监检会当成数据缺失而略过；实际含义是「这里有一枚章，需要你自己看图辨认」，
    仍然是证据，只是要人工过一眼。recognized 字段把这个区别摆到台面上。
    """
    results: list[dict[str, Any]] = []
    for kind, key in (("seal", "seals"), ("signature", "signatures")):
        for item in parse_result.get(key) or []:
            if not isinstance(item, dict):
                continue
            # sealName 里有时塞的是整段上下文文本，界面要截断显示
            name = str(item.get("sealName") or item.get("text") or "").strip()
            results.append(
                {
                    "kind": kind,
                    "id": str(
                        item.get("sealId") or item.get("signatureId") or item.get("candidateId") or ""
                    ),
                    "name": name,
                    # 有文字 ≠ 已核实。云端视觉模型在压字、印泥不匀的章上会**编**
                    # 出一个像样的单位名——实测同一枚章在四页上给了四个公司名。
                    # 所以「已识别」以记录里的 recognized 为准，读数另标来源与提示。
                    "recognized": bool(name) and item.get("recognized") is not False,
                    "recognitionSource": str(item.get("recognitionSource") or ""),
                    "requiresHumanConfirmation": bool(item.get("requiresHumanConfirmation")),
                    "recognitionNote": str(item.get("recognitionNote") or ""),
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
    # 已识别的排前面：认出文字的能直接核对，未识别的要人工看图，成本高得多。
    # 印章仍排在签名前——两者是不同性质的证据，不能因页码穿插而打散。
    results.sort(
        key=lambda seal: (
            not seal["recognized"],
            0 if seal["kind"] == "seal" else 1,
            int(seal.get("pageNo") or 0),
        )
    )
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
