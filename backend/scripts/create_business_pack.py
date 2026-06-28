from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.business_pack.loader import BUSINESS_PACK_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a new business pack from an existing template.")
    parser.add_argument("--id", required=True, help="New business pack id, for example: device_audit_v1.")
    parser.add_argument(
        "--template",
        default="compliance_audit_v1",
        help="Existing business pack to copy. Defaults to compliance_audit_v1.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing destination directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be copied without writing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = BUSINESS_PACK_ROOT / args.template
    target = BUSINESS_PACK_ROOT / args.id
    if not source.is_dir():
        print(f"template business pack not found: {args.template}", file=sys.stderr)
        return 2
    if target.exists() and not args.force:
        print(f"target business pack already exists: {args.id}", file=sys.stderr)
        return 3
    if args.dry_run:
        print(f"would copy {source} -> {target}")
        return 0
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    manifest = target / "manifest.yaml"
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8")
        text = text.replace(f"id: {args.template}", f"id: {args.id}", 1)
        text = text.replace("name: 合规审计业务包", f"name: {args.id}", 1)
        manifest.write_text(text, encoding="utf-8")
    print(f"created business pack: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
