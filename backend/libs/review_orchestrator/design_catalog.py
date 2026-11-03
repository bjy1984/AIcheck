"""设计图纸目录对照：目录列了哪些文件、各几页（张），实际交了几页，缺的是哪几份。

## 为什么必须有

缺资料原来只有两条路判：`check_document_set_completeness` 按资料「类别」比（有没有传管道特性表），
和分片审查的 LLM 自己说「缺少……」。前者不知道一份资料里缺了哪几页；后者每片只看到一部分
资料，2026-11-02 实测把 GDLNG 节点 4 正确的「缺三类设计文件」弄丢、把特性表在别片的事项说成缺。
设计单位自己的图纸目录写明了每份文件的编号和页数，是整节点判缺页最硬的依据。

## 怎么数（两份生产样本）

- ECD202 整本施工图 PDF（两份 sha256 相同，只算一份）：目录 p2 列 12 项、页数合计 38，PDF 只有 37 页。
  图号只在部分页的图签读得出（说明书 p5–11、轴测图 p23–30 没读出），所以按装订顺序归页：
  读不出图号的页归到它前面那份文件、那份够数了再按目录顺序往后补。归完只有管道壁厚表 S015
  少 1 页（页眉只见「2/2」）——与标准答案一致。
- GDLNG 七张照片：目录 Y-00 列 10 项、自然张数合计 18，只交 7 张；3 张读不出图号，
  照片之间没有装订顺序，不归页，只记「认不出的张数」。至少缺 18 − 7 = 11 张。

## 边界

- 只认目录表头里同时有「页数/自然张数/张数」和「编号/图号」两栏的表；读不出目录就不出结论。
- 缺页算「证据不足」不算「不符合」（skill 口径：缺资料、读不清不是不符合；标准答案也这样判），
  但缺的是哪几份、少几页写清楚，交监检去要。
- 交的页数不少于目录合计就不说缺，哪怕有几页认不出图号。
"""
from __future__ import annotations

import re
from typing import Any

from libs.ocr.text_line_tables import _HTML_TABLE_RE, _TAG_RE, _html_rows

_COUNT_HEADERS = ("自然张数", "页数", "张数")
_NUMBER_HEADERS = ("文档编号", "图号或编号", "图纸编号", "图号", "编号")
_NAME_HEADERS = ("文档名称", "名称", "图名")
_DOC_NO_RE = re.compile(r"[A-Z0-9]{2,}(?:-[A-Z0-9]{1,6}){1,6}")
# 图签里「图号 / 图纸编号 / DWG NO.」后面紧跟的编号才是本页自己的编号；正文里引用的别的编号不算。
_TITLE_NUMBER_RE = re.compile(r"(?:图号|图纸编号|文档编号|DWG\.?\s*No\.?)[^A-Z0-9]{0,40}([A-Z0-9]{2,}(?:-[A-Z0-9]{1,6}){1,6})",
                              re.IGNORECASE)


_PAGE_MARKER_RE = re.compile(r"(?<![\d./])(\d{1,2})\s*/\s*(\d{1,2})(?![\d./])")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        for index, cell in enumerate(header):
            if name in _compact(cell):
                return index
    return None


def _fragment_tables(fragment: dict[str, Any]) -> list[str]:
    html = str(fragment.get("tableHtml") or "")
    text = str(fragment.get("text") or "")
    return [html] if html else _HTML_TABLE_RE.findall(text)


def catalog_entries(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    """目录表的每一行：序号、名称、编号、页数。表头要同时有页数栏和编号栏。"""
    entries: list[dict[str, Any]] = []
    for fragment in parse_result.get("fragments") or []:
        if not isinstance(fragment, dict):
            continue
        for html in _fragment_tables(fragment):
            rows = [[text for text, _span in row] for row in _html_rows(html)]
            for index, header in enumerate(rows):
                count_col, number_col = _column(header, _COUNT_HEADERS), _column(header, _NUMBER_HEADERS)
                if count_col is None or number_col is None:
                    continue
                name_col = _column(header, _NAME_HEADERS)
                for row in rows[index + 1:]:
                    if len(row) <= max(count_col, number_col) or not re.fullmatch(r"\d{1,3}", _compact(row[0])):
                        continue
                    number = _DOC_NO_RE.search(_compact(row[number_col]).upper())
                    count = re.fullmatch(r"(\d{1,3})", _compact(row[count_col]))
                    if not number or not count:
                        continue
                    entries.append({"seq": int(_compact(row[0])), "documentNo": number.group(0),
                                    "name": row[name_col].strip() if name_col is not None and name_col < len(row) else "",
                                    "pages": int(count.group(1)), "catalogPageNo": fragment.get("pageNo")})
                break
    unique: dict[str, dict[str, Any]] = {}
    for entry in entries:
        unique.setdefault(entry["documentNo"], entry)
    return sorted(unique.values(), key=lambda item: item["seq"])


def _page_texts(parse_result: dict[str, Any]) -> dict[int, str]:
    pages: dict[int, list[str]] = {}
    for fragment in parse_result.get("fragments") or []:
        if isinstance(fragment, dict) and fragment.get("pageNo") is not None:
            pages.setdefault(int(fragment["pageNo"]), []).append(_TAG_RE.sub(" ", str(fragment.get("text") or "")))
    return {page: "\n".join(parts) for page, parts in pages.items()}


def _page_number(text: str, known: set[str]) -> str | None:
    upper = text.upper()
    titled = [match.group(1) for match in _TITLE_NUMBER_RE.finditer(upper) if match.group(1) in known]
    if titled:
        return titled[0]
    found = {match.group(0) for match in _DOC_NO_RE.finditer(_compact(upper))} & known
    return found.pop() if len(found) == 1 else None


def catalog_completeness(parse_results: list[dict[str, Any]], content_keys: dict[str, str]) -> dict[str, Any] | None:
    """整节点对照目录。没有目录返回 None。

    parse_results：本节点设计文件的 OCR；content_keys：版本号 → 文件内容哈希（同一份文件交两次只算一份）。
    """
    entries: list[dict[str, Any]] = []
    for parse_result in parse_results:
        entries = entries or catalog_entries(parse_result)
    if not entries:
        return None
    order = [entry["documentNo"] for entry in entries]
    expected = {entry["documentNo"]: entry["pages"] for entry in entries}
    known = set(order)
    attributed = dict.fromkeys(order, 0)
    unplaced = 0
    seen_contents: set[str] = set()
    submitted = 0
    for parse_result in parse_results:
        version_id = str(parse_result.get("documentVersionId") or "")
        content = content_keys.get(version_id, version_id)
        if content in seen_contents:
            continue
        seen_contents.add(content)
        pages = _page_texts(parse_result)
        submitted += len(pages)
        # 装订顺序归页：读不出图号的页先归给前一份（还缺页的话），否则按目录顺序往后补；
        # 一个文件只有一页（照片）时没有顺序可言，读不出就记为认不出。
        current: str | None = None
        closed = False
        for page_no in sorted(pages):
            number = _page_number(pages[page_no], known)
            if number:
                current = number
                attributed[number] += 1
                # 页眉「2/2」说明这一份到此为止：后面读不出图号的页属于下一份，不回填给它
                marker = _PAGE_MARKER_RE.search(pages[page_no][:300])
                closed = bool(marker) and marker.group(1) == marker.group(2)
                continue
            if current is None or len(pages) == 1:
                unplaced += 1
                continue
            while current is not None and (closed or attributed[current] >= expected[current]):
                closed = False
                following = order.index(current) + 1
                current = order[following] if following < len(order) else None
            if current is None:
                unplaced += 1
            else:
                attributed[current] += 1
    total = sum(expected.values())
    short = [{"documentNo": entry["documentNo"], "name": entry["name"], "catalogPages": entry["pages"],
              "submittedPages": attributed[entry["documentNo"]]}
             for entry in entries if attributed[entry["documentNo"]] < entry["pages"]]
    return {
        "catalogDocumentNo": next((entry["documentNo"] for entry in entries if "目录" in entry["name"]), order[0]),
        "entries": [{**entry, "submittedPages": attributed[entry["documentNo"]]} for entry in entries],
        "catalogPageTotal": total,
        "submittedPageCount": submitted,
        "missingPageCount": max(total - submitted, 0),
        "unplacedPageCount": unplaced,
        # 页数够了就不列「可能缺的」：差额是图号没读出造成的，不是缺页
        "shortDocuments": short if total > submitted else [],
    }
