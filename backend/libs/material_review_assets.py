from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ASSET_PATH = BACKEND_ROOT / "config" / "material_review_points.json"


def material_review_asset_path() -> Path:
    configured = os.getenv("AICHECK_MATERIAL_REVIEW_POINTS_ASSET", "").strip()
    return Path(configured) if configured else DEFAULT_ASSET_PATH


def source_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_material_review_asset(path: Path | None = None) -> dict[str, Any]:
    target = path or material_review_asset_path()
    if not target.exists():
        return {
            "schemaVersion": "aicheck-material-review-points@1",
            "version": "missing",
            "source": None,
            "sourceSha256": None,
            "itemCount": 0,
            "items": [],
            "assetPath": str(target),
        }
    payload = json.loads(target.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        **payload,
        "itemCount": len(items),
        "items": items,
        "assetPath": str(target),
    }


def material_review_asset_status(*, source_path: Path | None = None) -> dict[str, Any]:
    asset = load_material_review_asset()
    actual_source_hash = source_sha256(source_path) if source_path else None
    expected_source_hash = str(asset.get("sourceSha256") or "") or None
    return {
        "ready": bool(asset.get("itemCount")) and (
            actual_source_hash is None or actual_source_hash == expected_source_hash
        ),
        "schemaVersion": asset.get("schemaVersion"),
        "version": asset.get("version"),
        "source": asset.get("source"),
        "sourceSha256": expected_source_hash,
        "actualSourceSha256": actual_source_hash,
        "sourceMatches": actual_source_hash is None or actual_source_hash == expected_source_hash,
        "itemCount": int(asset.get("itemCount") or 0),
    }
