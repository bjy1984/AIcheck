#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import urllib.request


def verify_restored_files(manifest: dict[str, object], restored_root: pathlib.Path) -> int:
    checked = 0
    for relative, metadata in manifest["files"].items():  # type: ignore[union-attr]
        if not relative.startswith("files/") or relative.endswith("/.migration-root"):
            continue
        path = restored_root / relative.removeprefix("files/")
        if not path.is_file():
            raise RuntimeError(f"restored file is missing: {relative}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != metadata["size"] or "sha256:" + digest != metadata["sha256"]:
            raise RuntimeError(f"restored file differs: {relative}")
        checked += 1
    return checked


def _psql(database: str, query: str, container: str, user: str) -> str:
    return subprocess.check_output(
        ["docker", "exec", container, "psql", "-U", user, "-d", database, "-Atc", query],
        text=True,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=pathlib.Path, required=True)
    parser.add_argument("--data-root", type=pathlib.Path, required=True)
    parser.add_argument("--receipt", type=pathlib.Path, required=True)
    parser.add_argument("--ready-url", default="http://127.0.0.1:8000/readyz")
    parser.add_argument("--postgres-container", default="aicheck-postgres")
    parser.add_argument("--postgres-user", default="aicheck")
    args = parser.parse_args()
    manifest = json.loads((args.bundle_root / "manifest.json").read_text(encoding="utf-8"))
    files_checked = verify_restored_files(manifest, args.data_root)
    for database in ("aicheck", "litellm", "workflow"):
        _psql(database, "select 1", args.postgres_container, args.postgres_user)
    business_rows = int(
        _psql(
            "aicheck",
            "select count(*) from aicheck_state where collection <> 'audit_logs'",
            args.postgres_container,
            args.postgres_user,
        )
    )
    historical_documents = int(
        _psql(
            "aicheck",
            "select count(*) from aicheck_state where collection = 'documents'",
            args.postgres_container,
            args.postgres_user,
        )
    )
    ready = json.loads(urllib.request.urlopen(args.ready_url, timeout=15).read())
    if not ready.get("ready") or not ready.get("authRequired"):
        raise RuntimeError("application readiness or authentication check failed")
    if business_rows <= 0 or historical_documents <= 0:
        raise RuntimeError("historical business data is missing")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    receipt.update(
        applicationRestart="complete",
        verification="pass",
        businessStateRows=business_rows,
        historicalDocuments=historical_documents,
        restoredFilesChecked=files_checked,
    )
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
