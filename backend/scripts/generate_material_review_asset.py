from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from libs.business_pack import DEFAULT_BUSINESS_PACK_ID
from libs.material_targeting import MAPPING_DOC_RELATIVE_PATH, load_review_points_from_mapping_doc

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
DEFAULT_SOURCE = WORKSPACE_ROOT / MAPPING_DOC_RELATIVE_PATH
DEFAULT_OUTPUT = BACKEND_ROOT / "config" / "material_review_points.json"


def build_payload(source: Path) -> dict:
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    items = load_review_points_from_mapping_doc(
        source,
        business_pack_id=DEFAULT_BUSINESS_PACK_ID,
        source=MAPPING_DOC_RELATIVE_PATH,
    )
    return {
        "schemaVersion": "aicheck-material-review-points@1",
        "version": f"engineering-inspection-material-map@{source_hash[:12]}",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "source": MAPPING_DOC_RELATIVE_PATH,
        "sourceSha256": source_hash,
        "itemCount": len(items),
        "items": items,
    }


def serialized(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the runtime material review point asset.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_payload(args.source)
    content = serialized(payload)
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != content:
            print(f"material review asset is stale: {args.output}")
            return 1
        print(f"material review asset is current: {payload['itemCount']} items")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"wrote {payload['itemCount']} items to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
