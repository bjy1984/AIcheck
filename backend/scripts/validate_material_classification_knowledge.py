from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.material_classification_knowledge import (
    DEFAULT_KNOWLEDGE_PATH,
    DEFAULT_MAPPING_PATH,
    material_type_definitions_from_mapping,
    validate_material_classification_knowledge,
)


def validation_report(knowledge_path: Path, mapping_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(knowledge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "cardCount": 0,
            "standardSupportedCount": 0,
            "businessDefinedCount": 0,
            "errors": [{"code": "KNOWLEDGE_READ_FAILED", "message": exc.__class__.__name__}],
        }
    cards = payload.get("cards") if isinstance(payload, dict) else []
    cards = cards if isinstance(cards, list) else []
    expected_definitions = material_type_definitions_from_mapping(mapping_path)
    errors = validate_material_classification_knowledge(
        payload,
        expected_type_codes=set(expected_definitions),
        expected_definitions=expected_definitions,
    )
    return {
        "ok": not errors,
        "cardCount": len(cards),
        "standardSupportedCount": len(
            [item for item in cards if isinstance(item, dict) and item.get("basisLevel") == "standard_supported"]
        ),
        "businessDefinedCount": len(
            [item for item in cards if isinstance(item, dict) and item.get("basisLevel") == "business_defined"]
        ),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the auditable 60-card material classification knowledge.")
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    args = parser.parse_args()
    report = validation_report(args.knowledge, args.mapping)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
