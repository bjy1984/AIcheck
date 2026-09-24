"""把按行排成文字的表格（MinerU 等把整頁輸出為一段文字）按簽名重建成表。

設計文件裡的「管道特性表」常被 OCR 輸出成：表名一行、兩層表頭各一行、每條管線一行，
儲存格以空白分隔、空格子寫「/」。沒有座標，只能靠行與格數對齊，所以規矩很嚴：
- 表名、兩層表頭都要與簽名宣告的原字逐字相同（去掉空白後比），才認這張表；
- 數據行以行鍵（管線號）開頭，且格數必須與簽名的葉子欄位數完全相同才收——
  一格裡若 OCR 多出空白，格數就對不上，整行不收，寧可少讀，不把值錯位到別欄；
- 「$...$」公式（如 $\\phi 57\\times 4.0$）算一格；
- 引文就是 OCR 記錄下來的那幾行原文。

MinerU 的 markdown 版本則把同一張表嵌成 HTML（兩層表頭用 rowspan／colspan）。按原始
順序讀出表頭格子逐字比對同一組簽名；數據行格數要對上，數據行裡有合併格就整行不收。
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"\$[^$]*\$|\S+")


def _tokens(line: str) -> list[str]:
    return _TOKEN_RE.findall(line)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _fits(count: int, columns: list[str], variant: dict[str, Any]) -> bool:
    """格數要與葉子欄位數相同；只許少掉簽名宣告可空的結尾欄（例如常空的「备注」）。"""
    return len(columns) - int(variant.get("optionalTrailing") or 0) <= count <= len(columns)


def _table_from_lines(lines: list[str], spec: dict[str, Any], variant: dict[str, Any], start: int,
                      *, page_no: Any, name: str) -> dict[str, Any] | None:
    columns = list(variant["columns"])
    key = re.compile(spec["rowKeyPattern"])
    # 引文：兩層表頭（上一行若就是含表名的那行，一併帶上）與收下的數據行，都是 OCR 原文。
    head = start - 3 if start >= 3 and _compact(spec["title"]) in _compact(lines[start - 3]) else start - 2
    rows, quoted, rejected = [], lines[head:start], 0
    for line in lines[start:]:
        cells = _tokens(line)
        if not cells or not key.search(cells[0]):
            continue
        if not _fits(len(cells), columns, variant):
            rejected += 1
            continue
        rows.append(dict(zip(columns, cells, strict=False)))
        quoted.append(line)
    if not rows:
        return None
    return {"tableId": f"TEXT-{name}-{variant['id']}-P{page_no}", "pageNo": page_no, "title": spec["title"],
            "contentMarkdown": "\n".join(quoted), "normalizedRows": rows,
            "reconstructedFrom": "ocr_text_lines_by_signature", "rejectedRowCount": rejected}


_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_HTML_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


def _html_rows(html: str) -> list[list[tuple[str, bool]]]:
    """每一列的格子：(文字, 是否合併格)。"""
    rows = []
    for row in _ROW_RE.findall(html):
        rows.append([(_TAG_RE.sub("", body).strip(), bool(re.search(r"(?:row|col)span", attrs, re.IGNORECASE)))
                     for attrs, body in _CELL_RE.findall(row)])
    return rows


def _variant_for(header: str, sub_header: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    return next((item for item in spec["variants"] if _compact(header) == _compact(item["header"])
                 and _compact(sub_header) == _compact(item["subHeader"])), None)


def _html_table(html: str, spec: dict[str, Any], *, page_no: Any, name: str) -> dict[str, Any] | None:
    rows = _html_rows(html)
    for index, row in enumerate(rows[:-1]):
        variant = _variant_for("".join(text for text, _span in row),
                               "".join(text for text, _span in rows[index + 1]), spec)
        if variant is None:
            continue
        columns, key = list(variant["columns"]), re.compile(spec["rowKeyPattern"])
        records, rejected = [], 0
        for data in rows[index + 2:]:
            while data and not data[-1][0] and not data[-1][1]:
                data = data[:-1]  # 行尾多出的空格子（MinerU 常補一格）不算欄
            if not data or not key.search(data[0][0]):
                continue
            if not _fits(len(data), columns, variant) or any(span for _text, span in data):
                rejected += 1
                continue
            records.append(dict(zip(columns, (text for text, _span in data), strict=False)))
        if not records:
            return None
        return {"tableId": f"HTML-{name}-{variant['id']}-P{page_no}", "pageNo": page_no, "title": spec["title"],
                "html": html, "normalizedRows": records, "reconstructedFrom": "ocr_html_by_signature",
                "rejectedRowCount": rejected}
    return None


def text_line_tables(parse: dict[str, Any], signature: dict[str, Any]) -> list[dict[str, Any]]:
    """一份 OCR 結果裡，簽名宣告過的按行文字或 HTML 表格。

    以兩層表頭逐字吻合認表；表名要出現在同一頁（同一個片段）裡——圖紙上表名常夾在
    圖簽那一行，不一定獨佔一行。
    """
    spec = signature.get("textLines")
    if not isinstance(spec, dict):
        return []
    tables = []
    for fragment in parse.get("fragments") or []:
        if not isinstance(fragment, dict):
            continue
        text = str(fragment.get("text") or "")
        if _compact(spec["title"]) not in _compact(_TAG_RE.sub("", text)):
            continue
        for match in _HTML_TABLE_RE.finditer(text):
            table = _html_table(match.group(0), spec, page_no=fragment.get("pageNo"), name=signature["businessSchema"])
            if table:
                tables.append(table)
        lines = [line.strip() for line in text.split("\n")]
        for index in range(len(lines) - 1):
            variant = _variant_for(lines[index], lines[index + 1], spec)
            if variant is None:
                continue
            table = _table_from_lines(lines, spec, variant, index + 2,
                                      page_no=fragment.get("pageNo"), name=signature["businessSchema"])
            if table:
                tables.append(table)
    return tables
