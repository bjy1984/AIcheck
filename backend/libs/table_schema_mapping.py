"""把 OCR 表格認成 businessSchema，並把表頭對映成判據讀的欄位路徑。

這是凍結判據的**生產側**。判據宣告要讀什麼（actualPath），fact builder 宣告要哪
張表（businessSchema），這個模組把真實的 OCR 表格接到那兩者上。

貫穿全檔的一條規矩：**對映不上就不寫**。判據那邊「該寫沒寫」判不符合、「取不到
值」判證據不足，兩種結果都比塞一個猜的值進去好。所以每個 parse 函式在拿不準時
一律回 None，讓欄位缺席，而不是回一個看起來合理的東西。
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
    """去掉空白與全形標點差異；OCR 的表頭常帶零寬空白和不同的括號。"""
    text = str(value or "")
    for wide, narrow in (("（", "("), ("）", ")"), ("：", ":"), ("／", "/"), ("，", ","), ("、", "/")):
        text = text.replace(wide, narrow)
    return re.sub(r"[\s\u200b　]+", "", text)


def table_headers(table: dict[str, Any]) -> set[str]:
    """表頭以第一列的鍵為準——normalizedRows 的鍵就是 OCR 認出的欄名。"""
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
    """認不出、或同時符合兩條簽名，都回 None。

    含糊的時候寧可不貼標籤：貼錯的表會被 fact builder 當成真資料讀，
    比沒有這張表更難查。
    """
    headers = table_headers(table)
    if not headers:
        return None
    hits = [item for item in signatures if _matches(item, headers)]
    return hits[0]["businessSchema"] if len(hits) == 1 else None


def _parse_text(value: Any, _field: dict[str, Any]) -> Any:
    text = str(value or "").strip()
    return text or None


def _parse_percent(value: Any, _field: dict[str, Any]) -> Any:
    """只收乾淨的「10%」。「约10%」「10~20%」這種一律不收——範圍和約數不是判據要的數。"""
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
    """從「材质:S30408标准:GB/T14976-2025」這種黏在一起的值裡切出指定標籤的部分。"""
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


_PARSERS = {"text": _parse_text, "percent": _parse_percent, "labelled": _parse_labelled}


def _assign(target: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value


def map_row(row: dict[str, Any], signature: dict[str, Any]) -> dict[str, Any]:
    """只放對映得到的欄位；取不到的路徑整個不出現。"""
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
    """把一張認出來的表轉成 frozen_domain_checks 收的 domain row。

    scope 四欄、domain 名、evidenceRefs 都由這裡補齊；判據欄位只放對映得到的。
    `applicable` 只有簽名裡明寫 `applicableWhen: table_present` 才給 True——
    適用性是判斷，不能因為「表在」就默默當成適用而不留痕跡。
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
            # 沒有對象識別，這一列無法歸屬到任何被審查對象，寧可不產生。
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
            # applicable 只屬於 frozen_domain_checks 的 domain row；plan item 這類
            # 表沒有 domain，掛上去只會多一個沒人讀的欄位。
            **({"applicable": True}
               if signature.get("domain") and signature.get("applicableWhen") == "table_present"
               else {}),
            "evidenceRefs": [reference],
            "evidence": deepcopy(reference),
            **map_row(row, signature),
        })
    return built
