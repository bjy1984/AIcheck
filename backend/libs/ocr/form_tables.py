"""把掃描件上的固定表格按表頭錨點重建成表，只用 OCR 記錄下來的原字。

為什麼要有這一層：交工資料多是掃描件，OCR（macOS Vision、PaddleOCR）只給一個個帶
座標的文字片段，不給表格；而安裝、試驗類規則的事實構建只讀表格，於是整本施工記錄
一條都讀不到（2026-09-24 在七項目快照上，恒基達鑫交工資料 24 頁、1961 個片段、0 張表）。

做法刻意保守，全部由簽名宣告，不靠猜：
- 表名：簽名給出表號與表名的正則，頁上要有一個片段對得上，這一頁才重建。
- 欄位：簽名按左到右列出表頭字樣；同名的表頭（兩個「材质」）用 occurrence 指第幾個。
  任何一欄在頁上找不到表頭，整張表不重建——少一欄就可能把值放錯欄。
- 列：只收「行鍵」欄有值且符合 rowKeyPattern 的列；表尾的簽字、日期落不進行鍵欄，
  自然被排除。沒有行鍵的續行一律不併，寧可少讀，不把別處的字併進來。
- 儲存格：OCR 常把相鄰兩格認成一個片段（「0.2 洁净水」「2 PL8306-100」）。片段先按
  空白與「|」切成詞，按字寬估每個詞的橫向位置，再歸到最近的表頭。
- 引文：html 的每一格都是 OCR 原字，只做切分與拼接，不改寫、不正規化。
"""
from __future__ import annotations

import re
from typing import Any

from libs.table_schema_mapping import normalize_header

_TOKEN_RE = re.compile(r"[^\s|｜]+")
_WIDE_RE = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def _width(text: str) -> float:
    """字寬權重：全形字記 1，半形字記 0.55。只用來把片段按比例切成詞。"""
    return sum(1.0 if _WIDE_RE.match(char) else 0.55 for char in text) or 1.0


def _tokens(fragment: dict[str, Any]) -> list[dict[str, Any]]:
    bbox = fragment.get("bbox")
    text = str(fragment.get("text") or "")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox) or not text.strip()):
        return []
    x0, y0, x1, y1 = (float(value) for value in bbox)
    total = _width(text)
    tokens = []
    for match in _TOKEN_RE.finditer(text):
        before = _width(text[:match.start()]) if match.start() else 0.0
        span = _width(match.group())
        tokens.append({"text": match.group(), "x0": x0 + (x1 - x0) * before / total,
                       "x1": x0 + (x1 - x0) * (before + span) / total, "y0": y0, "y1": y1,
                       "confidence": fragment.get("confidence"), "fragmentId": fragment.get("id"),
                       "pageBbox": fragment.get("pageBbox") or [x0, y0, x1, y1]})
    return tokens


def _centre(token: dict[str, Any]) -> float:
    return (token["x0"] + token["x1"]) / 2


def _middle(token: dict[str, Any]) -> float:
    return (token["y0"] + token["y1"]) / 2


def _anchors(tokens: list[dict[str, Any]], columns: list[dict[str, Any]], *, top: float, bottom: float
             ) -> list[dict[str, Any]] | None:
    """每一欄的表頭詞；表頭區在表名之下、行鍵表頭之下不遠處。缺任何一欄就放棄整張表。"""
    header = sorted((token for token in tokens if top <= _middle(token) <= bottom), key=_centre)
    anchors = []
    for column in columns:
        label = normalize_header(column["label"])
        hits = [token for token in header if normalize_header(token["text"]) == label]
        occurrence = int(column.get("occurrence") or 1)
        if len(hits) < occurrence:
            return None
        hit = hits[occurrence - 1]
        anchors.append({**column, "x": _centre(hit), "y1": hit["y1"], "printed": hit["text"],
                        "pageBbox": hit["pageBbox"]})
    xs = [anchor["x"] for anchor in anchors]
    if xs != sorted(xs) or len({round(x) for x in xs}) != len(xs):
        # 表頭順序和簽名不一致（或兩欄疊在一起）：版式不是簽名描述的那張表。
        return None
    return anchors


def _rows(tokens: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for token in sorted(tokens, key=_middle):
        height = max(token["y1"] - token["y0"], 1.0)
        if rows:
            last = rows[-1]
            centre = sum(_middle(item) for item in last) / len(last)
            if abs(_middle(token) - centre) <= 0.6 * height:
                last.append(token)
                continue
        rows.append([token])
    return rows


def _nearest(anchors: list[dict[str, Any]], token: dict[str, Any]) -> dict[str, Any]:
    return min(anchors, key=lambda anchor: abs(anchor["x"] - _centre(token)))


def _html(anchors: list[dict[str, Any]], rows: list[dict[str, str]]) -> str:
    """表頭寫頁上印的字（兩個「规格」就是兩個「规格」），不寫簽名裡的欄名——欄名是
    為了對映起的，原文沒有這幾個字，放進引文就是編造。"""
    def cell(text: str) -> str:
        return "<td>" + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</td>"

    lines = ["<tr>" + "".join(cell(anchor["printed"]) for anchor in anchors) + "</tr>"]
    lines += ["<tr>" + "".join(cell(row.get(anchor["name"], "")) for anchor in anchors) + "</tr>" for row in rows]
    return "<table>" + "".join(lines) + "</table>"


def _turned(fragments: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    """把豎排的頁轉正：橫向表格直著掃描時，文字沿頁高方向排。

    ccw：文字由下往上讀（頁面逆時針轉了 90°）；cw：由上往下讀。轉正後的座標只用來
    分欄分列，表格的 bbox 仍取片段在原頁上的位置（pageBbox）。
    """
    boxes = [fragment["bbox"] for fragment in fragments if _box(fragment)]
    width = max(box[2] for box in boxes)
    height = max(box[3] for box in boxes)
    turned = []
    for fragment in fragments:
        if not _box(fragment):
            continue
        x0, y0, x1, y1 = (float(value) for value in fragment["bbox"])
        box = [height - y1, x0, height - y0, x1] if direction == "ccw" else [y0, width - x1, y1, width - x0]
        turned.append({**fragment, "bbox": box, "pageBbox": [x0, y0, x1, y1]})
    return turned


def _box(fragment: dict[str, Any]) -> bool:
    bbox = fragment.get("bbox")
    return (isinstance(bbox, list) and len(bbox) == 4
            and all(isinstance(value, (int, float)) for value in bbox))


def reconstruct_form_table(fragments: list[dict[str, Any]], form: dict[str, Any], *, page_no: int
                           ) -> dict[str, Any] | None:
    """一頁的片段 → 一張表；認不出表名、缺表頭、沒有數據列都回 None。

    表名是豎的（高大於寬），就兩個方向都轉正試一次；只有一個方向的表頭順序對得上
    簽名才採用，兩個都對得上（或都對不上）就不重建。
    """
    title_re = re.compile(form["title"])
    titles = [fragment for fragment in fragments
              if _box(fragment) and title_re.search(re.sub(r"\s+", "", str(fragment.get("text") or "")))]
    if len(titles) != 1:
        return None
    x0, y0, x1, y1 = titles[0]["bbox"]
    if y1 - y0 <= x1 - x0:
        return _reconstruct(fragments, titles[0], form, page_no=page_no)
    boxed = [fragment for fragment in fragments if _box(fragment)]
    index = next(position for position, fragment in enumerate(boxed) if fragment is titles[0])
    found = []
    for direction in ("ccw", "cw"):
        turned = _turned(boxed, direction)
        table = _reconstruct(turned, turned[index], form, page_no=page_no)
        if table is not None:
            found.append(table)
    return found[0] if len(found) == 1 else None


def _reconstruct(fragments: list[dict[str, Any]], title: dict[str, Any], form: dict[str, Any], *, page_no: int
                 ) -> dict[str, Any] | None:
    titles = [title]
    tokens = [token for fragment in fragments if fragment is not titles[0] for token in _tokens(fragment)]
    title_bottom = float(titles[0]["bbox"][3])
    columns = list(form["columns"])
    key_label = normalize_header(next(column["label"] for column in columns if column["name"] == form["rowKey"]))
    key_headers = [token for token in tokens if normalize_header(token["text"]) == key_label
                   and _middle(token) > title_bottom]
    if not key_headers:
        return None
    key_header = min(key_headers, key=_middle)
    anchors = _anchors(tokens, columns, top=title_bottom,
                       bottom=key_header["y1"] + float(form.get("headerDepth") or 40))
    if anchors is None:
        return None
    body_top = max(anchor["y1"] for anchor in anchors)
    key_pattern = re.compile(form["rowKeyPattern"])
    rows, confidences, kept = [], [], []
    for line in _rows([token for token in tokens if _middle(token) > body_top]):
        cells: dict[str, list[dict[str, Any]]] = {}
        for token in sorted(line, key=_centre):
            cells.setdefault(_nearest(anchors, token)["name"], []).append(token)
        key = " ".join(token["text"] for token in cells.get(form["rowKey"], []))
        if not key_pattern.search(key):
            continue
        rows.append({name: " ".join(token["text"] for token in items) for name, items in cells.items()})
        kept.extend(line)
        scores = [token["confidence"] for token in line if isinstance(token["confidence"], (int, float))]
        confidences.append(min(scores) if scores else None)
    if not rows:
        return None
    # 表的範圍：各欄表頭到最後一列，不含表名、表尾的簽字與日期。
    used = [anchor["pageBbox"] for anchor in anchors] + [token["pageBbox"] for token in kept]
    bbox = [min(box[0] for box in used), min(box[1] for box in used),
            max(box[2] for box in used), max(box[3] for box in used)]
    known = [score for score in confidences if score is not None]
    return {
        "tableId": f"FORM-{form['id']}-P{page_no}",
        "pageNo": page_no,
        "bbox": [round(value, 2) for value in bbox],
        "html": _html(anchors, rows),
        "normalizedRows": [{**row, **({"confidence": score} if score is not None else {})}
                           for row, score in zip(rows, confidences, strict=True)],
        "structureConfidence": min(known) if known else None,
        "reconstructedFrom": "ocr_fragments_by_form_signature",
        "formTitle": str(titles[0].get("text") or ""),
    }


def form_tables(parse: dict[str, Any], signatures: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """一份 OCR 結果裡所有簽名宣告過的表格：[(重建的表, 簽名)]。"""
    pages: dict[int, list[dict[str, Any]]] = {}
    for fragment in parse.get("fragments") or []:
        page = fragment.get("pageNo") if isinstance(fragment, dict) else None
        if type(page) is int and page > 0:
            pages.setdefault(page, []).append(fragment)
    found = []
    for signature in signatures:
        form = signature.get("form")
        if not isinstance(form, dict):
            continue
        for page_no in sorted(pages):
            table = reconstruct_form_table(pages[page_no], {**form, "id": signature["businessSchema"]},
                                           page_no=page_no)
            if table is not None:
                found.append((table, signature))
    return found
