from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from libs.raw_vault_export import verify_export_bytes


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_raw_vault_export.py ARCHIVE.zip", file=sys.stderr)
        return 2
    result = verify_export_bytes(Path(sys.argv[1]).read_bytes())
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0 if result.status == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
