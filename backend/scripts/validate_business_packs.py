from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.business_pack import validate_all_business_packs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate all AIcheck business packs.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_all_business_packs()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"business-pack validation: {status}")
        for item in result["results"]:
            summary = item["summary"]
            validation = item["validation"]
            print(
                f"- {summary['id']} {summary['version']}: "
                f"{'ok' if validation['ok'] else 'failed'}; "
                f"errors={len(validation['errors'])}; warnings={len(validation['warnings'])}"
            )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
