"""把 OCR 表格认成 businessSchema，并把表头对映成判据读的栏位路径。

这是冻结判据的**生产侧**。判据宣告要读什么（actualPath），fact builder 宣告要哪
张表（businessSchema），这个模组把真实的 OCR 表格接到那两者上。

贯穿全档的一条规矩：**对映不上就不写**。判据那边「该写没写」判不符合、「取不到
值」判证据不足，两种结果都比塞一个猜的值进去好。所以每个 parse 函式在拿不准时
一律回 None，让栏位缺席，而不是回一个看起来合理的东西。
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

PACK_ROOT = Path(__file__).resolve().parents[1] / "business_packs"
SIGNATURE_FILE = "table_schema_signatures.yaml"
SCHEMA_VERSION = "table-schema-signatures-v1"

_PERCENT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


def load_signatures(pack_id: str = "engineering_inspection_v1") -> list[dict[str, Any]]:
    document = yaml.safe_load((PACK_ROOT / pack_id / SIGNATURE_FILE).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("table_schema_signatures_version_unsupported")
    signatures = document.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise ValueError("table_schema_signatures_empty")
    names = [item.get("businessSchema") for item in signatures]
    if len(names) != len(set(names)) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("table_schema_signatures_duplicate_or_unnamed")
    return signatures


def normalize_header(value: Any) -> str:
    """去掉空白与全形标点差异；OCR 的表头常带零宽空白和不同的括号。"""
    text = str(value or "")
    for wide, narrow in (("（", "("), ("）", ")"), ("：", ":"), ("／", "/"), ("，", ","), ("、", "/")):
        text = text.replace(wide, narrow)
    return re.sub(r"[\s\u200b　]+", "", text)


def table_headers(table: dict[str, Any]) -> set[str]:
    """表头以第一列的键为准——normalizedRows 的键就是 OCR 认出的栏名。"""
    rows = [row for row in table.get("normalizedRows") or [] if isinstance(row, dict)]
    return {normalize_header(key) for row in rows[:1] for key in row}


def _matches(signature: dict[str, Any], headers: set[str]) -> bool:
    match = signature.get("match") or {}
    required = {normalize_header(item) for item in match.get("required") or []}
    if not required or not required <= headers:
        return False
    optional = {normalize_header(item) for item in match.get("any") or []}
    minimum = match.get("minAny") or 0
    return len(optional & headers) >= minimum


def classify_table(table: dict[str, Any], signatures: list[dict[str, Any]]) -> str | None:
    """认不出、或同时符合两条签名，都回 None。

    含糊的时候宁可不贴标签：贴错的表会被 fact builder 当成真资料读，
    比没有这张表更难查。
    """
    headers = table_headers(table)
    if not headers:
        return None
    hits = [item for item in signatures if _matches(item, headers)]
    return hits[0]["businessSchema"] if len(hits) == 1 else None


# 表格里的「/」「—」是「本栏不填」的记号，不是值；当成有值会让「该写没写」看起来写了。
_BLANK_MARKS = frozenset({"/", "／", "-", "—", "--", "——", "\\"})
_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(.*?)\s*$")


def _parse_text(value: Any, _field: dict[str, Any]) -> Any:
    text = str(value or "").strip()
    return text if text and text not in _BLANK_MARKS else None


def _parse_number(value: Any, field: dict[str, Any]) -> Any:
    """只收一个干净的数，后面只许跟签名宣告的单位（units，不分大小写）。

    「约」「≤」「0.02~0.03」、单位不对（压力栏写了 kPa）与 OCR 夹杂的字一律不收——
    换算单位是判据的事，这里不代算。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    found = _NUMBER_RE.match(str(value or ""))
    if not found:
        return None
    unit = found.group(2).casefold()
    allowed = {str(item).casefold() for item in field.get("units") or []}
    return float(found.group(1)) if not unit or unit in allowed else None


def _parse_percent(value: Any, _field: dict[str, Any]) -> Any:
    """只收干净的「10%」。「约10%」「10~20%」这种一律不收——范围和约数不是判据要的数。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        found = _PERCENT_RE.match(str(value or ""))
        if not found:
            return None
        number = float(found.group(1))
    return number if 0 <= number <= 100 else None


def _parse_labelled(value: Any, field: dict[str, Any]) -> Any:
    """从「材质:S30408标准:GB/T14976-2025」这种黏在一起的值里切出指定标签的部分。"""
    text = normalize_header(value)
    label = normalize_header(field.get("label"))
    if not text or not label:
        return None
    head = text.split(label + ":", 1)
    if len(head) != 2:
        return None
    tail = head[1]
    for stop in field.get("stopLabels") or []:
        tail = tail.split(normalize_header(stop) + ":", 1)[0]
    tail = tail.strip(" ,，;；")
    return tail or None


def _parse_keyword(value: Any, field: dict[str, Any]) -> Any:
    """栏里逐字写了宣告的关键词之一 → True；写了别的 → False；没写或「/」→ 不出现。

    只用来从原文写明的值判断某条判据适用与否（例如吹洗介质写「洁净水」→ 水冲洗适用）。
    """
    text = _parse_text(value, field)
    if text is None:
        return None
    return any(str(word) in text for word in field.get("keywords") or [])


def _parse_filled(value: Any, _field: dict[str, Any]) -> Any:
    """栏里写了内容 → True；明确写「/」（本项不做）→ False；空着 → 不出现。"""
    text = str(value or "").strip()
    if not text:
        return None
    return text not in _BLANK_MARKS


_PARSERS = {"text": _parse_text, "number": _parse_number, "percent": _parse_percent, "labelled": _parse_labelled,
            "keyword": _parse_keyword, "filled": _parse_filled}


def _assign(target: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value


def map_row(row: dict[str, Any], signature: dict[str, Any]) -> dict[str, Any]:
    """只放对映得到的栏位；取不到的路径整个不出现。"""
    headers = {normalize_header(key): value for key, value in row.items()}
    mapped: dict[str, Any] = {}
    for field in signature.get("fields") or []:
        parser = _PARSERS.get(str(field.get("parse") or "text"))
        if parser is None:
            raise ValueError("table_schema_signature_unknown_parser:" + str(field.get("parse")))
        for column in field.get("columns") or []:
            key = normalize_header(column)
            if key not in headers:
                continue
            value = parser(headers[key], field)
            if value is not None:
                _assign(mapped, str(field["path"]), value)
                break
    return mapped


def build_domain_rows(
    table: dict[str, Any],
    signature: dict[str, Any],
    *,
    project_id: str,
    document_version_id: str,
) -> list[dict[str, Any]]:
    """把一张认出来的表转成 frozen_domain_checks 收的 domain row。

    scope 四栏、domain 名、evidenceRefs 都由这里补齐；判据栏位只放对映得到的。
    `applicable` 只有签名里明写 `applicableWhen: table_present` 才给 True——
    适用性是判断，不能因为「表在」就默默当成适用而不留痕迹。
    """
    rows = [item for item in table.get("normalizedRows") or [] if isinstance(item, dict)]
    object_columns = [normalize_header(item) for item in signature.get("objectIdColumns") or []]
    built = []
    for index, row in enumerate(rows):
        headers = {normalize_header(key): value for key, value in row.items()}
        object_id = next(
            (str(headers[key]).strip() for key in object_columns if str(headers.get(key) or "").strip()),
            "",
        )
        if not object_id:
            # 没有对象识别，这一列无法归属到任何被审查对象，宁可不产生。
            continue
        reference = {
            "documentVersionId": document_version_id,
            "pageNo": table.get("pageNo"),
            "tableId": table.get("tableId") or table.get("id"),
            "rowIndex": index,
        }
        built.append({
            "projectId": project_id,
            "objectType": signature.get("objectType"),
            "objectId": object_id,
            "recordVersionId": document_version_id,
            **({"domain": signature["domain"]} if signature.get("domain") else {}),
            # applicable 只属于 frozen_domain_checks 的 domain row；plan item 这类
            # 表没有 domain，挂上去只会多一个没人读的栏位。
            **({"applicable": True}
               if signature.get("domain") and signature.get("applicableWhen") == "table_present"
               else {}),
            "evidenceRefs": [reference],
            "evidence": deepcopy(reference),
            **map_row(row, signature),
        })
    return built
