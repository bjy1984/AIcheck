"""标准版本时间线（P11 N-03）：本地优先判 TSG 规范的现行 / 过渡期作废 / 已废止 / 未收录。

数据在 business_packs/engineering_inspection_v1/standard_version_timeline.yaml，由
scripts/sync_tsg_catalog.py 同步目录与公告，人工核对后写 verifiedBy。GB/NB 条目仍走
std.samr.gov.cn（lookup_standard_status），核到的结果也可以落进同一张表。
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

TIMELINE_PATH = Path(__file__).resolve().parents[1] / "business_packs" / "engineering_inspection_v1" / "standard_version_timeline.yaml"
_TSG_RE = re.compile(r"TSG\s*([A-Z]{0,2}\s?\d{2,5})\s*[-—–－]\s*(\d{4})", re.IGNORECASE)
_GENERIC_RE = re.compile(r"([A-Z]+(?:/T)?)\s*(\d[\d.]*)\s*[-—–－]\s*(\d{4})", re.IGNORECASE)

STATUS_CURRENT = "current"
STATUS_NOT_YET = "not_yet_effective"
STATUS_GRACE = "superseded_grace"
STATUS_WITHDRAWN = "withdrawn"
STATUS_UNKNOWN = "unknown"
STATUS_LABELS = {
    STATUS_CURRENT: "现行",
    STATUS_NOT_YET: "尚未实施",
    STATUS_GRACE: "过渡期内作废（预警）",
    STATUS_WITHDRAWN: "已废止",
    STATUS_UNKNOWN: "未收录",
}


def normalize_code(value: str) -> str:
    """"TSG Z6002—2026" / "tsg z6002-2026" / "TSGZ6002－2026" → "TSG Z6002-2026"。非 TSG 编号按 家族 编号-年份 规范化。"""
    text = str(value or "").strip()
    match = _TSG_RE.search(text)
    if match:
        return f"TSG {match.group(1).replace(' ', '').upper()}-{match.group(2)}"
    generic = _GENERIC_RE.search(text.upper().replace("—", "-").replace("－", "-"))
    if generic:
        return f"{generic.group(1)} {generic.group(2)}-{generic.group(3)}"
    return text


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    match = re.match(r"(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries: dict[str, dict[str, Any]] = {}
    for item in payload.get("entries") or []:
        if isinstance(item, dict) and item.get("code"):
            entries[normalize_code(str(item["code"]))] = item
    return entries


def load_timeline(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return _load(str(path or TIMELINE_PATH))


def timeline_status(code: str, on_date: date | str | None = None, *, path: Path | None = None) -> dict[str, Any]:
    """按时间线判一个编号在某天的状态。未收录 → unknown（调用方走在线查询 + 人工）。"""
    normalized = normalize_code(code)
    entry = load_timeline(path).get(normalized)
    day = _parse_date(on_date) if on_date else datetime.now(UTC).date()
    if entry is None:
        return {"code": normalized, "status": STATUS_UNKNOWN, "label": STATUS_LABELS[STATUS_UNKNOWN], "onDate": day.isoformat() if day else None, "verified": False}
    effective = _parse_date(entry.get("effectiveFrom"))
    withdrawn = _parse_date(entry.get("withdrawnOn"))
    grace = _parse_date(entry.get("graceUntil"))
    verified = bool(entry.get("verifiedBy")) and str(entry.get("extractionMethod") or "") != "ocr_unverified"
    if effective is None and withdrawn is None:
        # 只有目录行（sync 抓来的、没人核过公告与附则）："在列"不等于"现行"，按未收录处理，但把目录信息带出去
        return {
            "code": normalized,
            "name": entry.get("name"),
            "status": STATUS_UNKNOWN,
            "label": STATUS_LABELS[STATUS_UNKNOWN],
            "onDate": day.isoformat() if day else None,
            "catalogListed": True,
            "catalogDate": entry.get("catalogDate"),
            "sourceUrls": dict(entry.get("sourceUrls") or {}),
            "extractionMethod": entry.get("extractionMethod"),
            "verified": False,
        }
    if withdrawn and day and day >= withdrawn:
        status = STATUS_GRACE if grace and day <= grace else STATUS_WITHDRAWN
    elif effective and day and day < effective:
        status = STATUS_NOT_YET
    else:
        status = STATUS_CURRENT
    return {
        "code": normalized,
        "name": entry.get("name"),
        "status": status,
        "label": STATUS_LABELS[status],
        "onDate": day.isoformat() if day else None,
        "effectiveFrom": entry.get("effectiveFrom"),
        "withdrawnOn": entry.get("withdrawnOn"),
        "graceUntil": entry.get("graceUntil"),
        "replacedBy": entry.get("replacedBy"),
        "supersedes": list(entry.get("supersedes") or []),
        "sourceUrls": dict(entry.get("sourceUrls") or {}),
        "extractionMethod": entry.get("extractionMethod"),
        "verified": verified,
        "verifiedBy": entry.get("verifiedBy"),
    }


def standard_reference_fact(code: str, on_date: date | str | None = None) -> dict[str, Any]:
    """给 check_standard_version_active 用的一条：{standardRef, effectiveFrom, withdrawnOn, status}。

    过渡期内作废与 OCR 未核对的条目按 active 交给规则（只预警不判不符合），timelineStatus 保留真实状态供展示。
    """
    info = timeline_status(code, on_date)
    withdrawn_for_rule = info.get("withdrawnOn") if info["status"] == STATUS_WITHDRAWN and info.get("verified") else None
    return {
        "standardRef": info["code"],
        "effectiveFrom": info.get("effectiveFrom"),
        "withdrawnOn": withdrawn_for_rule,
        "status": "withdrawn" if withdrawn_for_rule else ("unknown" if info["status"] == STATUS_UNKNOWN else "active"),
        "timelineStatus": info["status"],
        "timelineLabel": info["label"],
        "replacedBy": info.get("replacedBy"),
        "verified": info.get("verified", False),
        "requiresOnlineLookup": info["status"] == STATUS_UNKNOWN,
    }
