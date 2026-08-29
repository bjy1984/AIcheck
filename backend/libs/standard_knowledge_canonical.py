"""Canonical standard-knowledge identity and field selection helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


CANONICAL_VERSION = "standard-knowledge-canonical@1"
SOURCE_PRIORITY = {
    "new_mineru": 500,
    "visual_extraction": 400,
    "standard_catalog": 300,
    "legacy_ocr": 200,
    "filename_inference": 100,
}


def canonical_item_id(kind: str, identity: list[object]) -> str:
    normalized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20].upper()
    return f"SKI-{kind.upper()}-{digest}"


def select_canonical_field(key: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [item for item in candidates if str(item.get("value") or "").strip()]
    if not usable:
        return None
    ordered = sorted(
        usable,
        key=lambda item: (
            SOURCE_PRIORITY.get(str(item.get("sourceType") or ""), 0),
            str(item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    selected = ordered[0]
    return {
        "id": canonical_item_id("field", [key]),
        "key": key,
        "value": selected["value"],
        "authority": "legacy_only" if selected.get("sourceType") == "legacy_ocr" else "current",
        "selectedSourceId": selected.get("sourceId"),
        "sources": ordered,
    }
