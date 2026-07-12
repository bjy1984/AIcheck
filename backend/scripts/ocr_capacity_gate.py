from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.capacity_guard import GIB, disk_capacity_status, swap_capacity
from libs.contracts.responses import server_time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report OCR host disk and swap release capacity gates.")
    parser.add_argument("--path", default="/")
    parser.add_argument("--strict-release", action="store_true")
    parser.add_argument("--minimum-swap-gib", type=float, default=8.0)
    parser.add_argument("--output")
    return parser.parse_args()


def build_report(path: str, minimum_swap_gib: float) -> dict:
    disk = disk_capacity_status(path)
    swap = swap_capacity()
    swap_passed = int(swap["totalBytes"]) >= int(max(0.0, minimum_swap_gib) * GIB)
    blockers = []
    if not disk["releaseTargetPassed"]:
        blockers.append(
            {
                "code": "ROOT_DISK_RELEASE_TARGET_NOT_MET",
                "message": "根盘必须低于发布使用率目标，且满足最小可用空间。",
            }
        )
    if not swap_passed:
        blockers.append(
            {
                "code": "SWAP_CAPACITY_NOT_MET",
                "message": f"服务器 swap 必须不少于 {minimum_swap_gib:g} GiB。",
            }
        )
    return {
        "schemaVersion": "aicheck-ocr-capacity-gate@1",
        "generatedAt": server_time(),
        "passed": not blockers,
        "disk": disk,
        "swap": {**swap, "minimumGiB": minimum_swap_gib, "passed": swap_passed},
        "blockingReasons": blockers,
    }


def main() -> int:
    args = parse_args()
    report = build_report(args.path, args.minimum_swap_gib)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if args.strict_release and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
