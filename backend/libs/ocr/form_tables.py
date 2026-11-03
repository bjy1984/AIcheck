"""把扫描件上的固定表格按表头锚点重建成表，只用 OCR 记录下来的原字。

为什么要有这一层：交工资料多是扫描件，OCR（macOS Vision、PaddleOCR）只给一个个带
座标的文字片段，不给表格；而安装、试验类规则的事实构建只读表格，于是整本施工记录
一条都读不到（2026-09-24 在七项目快照上，恒基达鑫交工资料 24 页、1961 个片段、0 张表）。

做法刻意保守，全部由签名宣告，不靠猜：
- 表名：签名给出表号与表名的正则，页上要有一个片段对得上，这一页才重建。
- 栏位：签名按左到右列出表头字样；同名的表头（两个「材质」）用 occurrence 指第几个。
  任何一栏在页上找不到表头，整张表不重建——少一栏就可能把值放错栏。
- 列：只收「行键」栏有值且符合 rowKeyPattern 的列；表尾的签字、日期落不进行键栏，
  自然被排除。没有行键的行只在紧贴某条数据行（折行的储存格）时并回那一行，
  离得远的一律不收，不把别处的字并进来。
- 储存格：OCR 常把相邻两格认成一个片段（「0.2 洁净水」「2 PL8306-100」）。片段先按
  空白与「|」切成词，按字宽估每个词的横向位置，再归到最近的表头。
- 引文：html 的每一格都是 OCR 原字，只做切分与拼接，不改写、不正规化。
"""
from __future__ import annotations

import math
import re
from typing import Any

from libs.table_schema_mapping import normalize_header

_TOKEN_RE = re.compile(r"[^\s|｜]+")
_WIDE_RE = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def _width(text: str) -> float:
    """字宽权重：全形字记 1，半形字记 0.55。只用来把片段按比例切成词。"""
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
    """每一栏的表头词；表头区在表名之下、行键表头之下不远处。缺任何一栏就放弃整张表。"""
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
        # 表头顺序和签名不一致（或两栏叠在一起）：版式不是签名描述的那张表。
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
    """表头写页上印的字（两个「规格」就是两个「规格」），不写签名里的栏名——栏名是
    为了对映起的，原文没有这几个字，放进引文就是编造。"""
    def cell(text: str) -> str:
        return "<td>" + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</td>"

    lines = ["<tr>" + "".join(cell(anchor["printed"]) for anchor in anchors) + "</tr>"]
    lines += ["<tr>" + "".join(cell(row.get(anchor["name"], "")) for anchor in anchors) + "</tr>" for row in rows]
    return "<table>" + "".join(lines) + "</table>"


def _turned(fragments: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    """把竖排的页转正：横向表格直著扫描时，文字沿页高方向排。

    ccw：文字由下往上读（页面逆时针转了 90°）；cw：由上往下读。转正后的座标只用来
    分栏分列，表格的 bbox 仍取片段在原页上的位置（pageBbox）。
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
    """一页的片段 → 一张表；认不出表名、缺表头、没有数据列都回 None。

    表名是竖的（高大于宽），就两个方向都转正试一次；只有一个方向的表头顺序对得上
    签名才采用，两个都对得上（或都对不上）就不重建。
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
    keyed: list[list[dict[str, Any]]] = []
    loose: list[list[dict[str, Any]]] = []
    for line in _rows([token for token in tokens if _middle(token) > body_top]):
        key = " ".join(token["text"] for token in line if _nearest(anchors, token)["name"] == form["rowKey"])
        (keyed if key_pattern.search(key) else loose).append(line)
    # 折行的储存格（「四区交／换站」）第二行没有行键：紧贴某条数据行（间距不超过半个行高）的，
    # 并回那一行；否则丢掉那半格会把「四区交换站」读成「四区交」——那不是少读，是读错。
    # 离得远的（表尾签字、日期）照旧不收。
    for line in loose:
        height = max(max(token["y1"] - token["y0"] for token in line), 1.0)
        gaps = [(max(min(item["y0"] for item in row) - max(token["y1"] for token in line),
                      min(token["y0"] for token in line) - max(item["y1"] for item in row), 0.0), index)
                for index, row in enumerate(keyed)]
        gap, index = min(gaps, default=(math.inf, -1))
        if gap <= 0.5 * height:
            keyed[index] = [*keyed[index], *line]
    rows, confidences, kept = [], [], []
    for line in keyed:
        cells: dict[str, list[dict[str, Any]]] = {}
        for token in sorted(line, key=lambda item: (item["y0"], _centre(item))):
            cells.setdefault(_nearest(anchors, token)["name"], []).append(token)
        rows.append({name: " ".join(token["text"] for token in items) for name, items in cells.items()})
        kept.extend(line)
        scores = [token["confidence"] for token in line if isinstance(token["confidence"], (int, float))]
        confidences.append(min(scores) if scores else None)
    if not rows:
        return None
    # 表的范围：各栏表头到最后一列，不含表名、表尾的签字与日期。
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
    """一份 OCR 结果里所有签名宣告过的表格：[(重建的表, 签名)]。"""
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
