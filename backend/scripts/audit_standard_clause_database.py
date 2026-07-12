#!/usr/bin/env python3
"""Audit the database release and project-node bindings for fixed clauses."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.business_pack import load_business_pack
from libs.business_pack.clause_store import compile_standard_clause_release
from libs.db.repository import repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path(os.getenv("AICHECK_SQLITE_PATH") or "data/aicheck.local.sqlite3"),
    )
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def audit(pack_id: str) -> dict[str, object]:
    pack = load_business_pack(pack_id)
    expected = compile_standard_clause_release(pack)
    release_id = f"{pack['id']}@{pack['version']}"
    errors: list[str] = []
    counts: dict[str, int] = {}
    for key, expected_rows in expected.items():
        actual_rows = [item for item in repo.state.get(key, []) if item.get("releaseId") == release_id]
        counts[key] = len(actual_rows)
        expected_by_id = {item["id"]: item for item in expected_rows}
        actual_by_id = {item["id"]: item for item in actual_rows}
        if actual_by_id != expected_by_id:
            missing = sorted(set(expected_by_id) - set(actual_by_id))
            extra = sorted(set(actual_by_id) - set(expected_by_id))
            changed = sorted(
                item_id
                for item_id in set(expected_by_id) & set(actual_by_id)
                if expected_by_id[item_id] != actual_by_id[item_id]
            )
            errors.append(f"{key} differs from release: missing={missing[:3]} extra={extra[:3]} changed={changed[:3]}")

    package_by_id = {item["id"]: item for item in repo.state.get("standard_clause_packages_db", [])}
    projects = [
        item
        for item in repo.state.get("projects", [])
        if item.get("businessPackId") == pack["id"]
        and item.get("businessPackVersion") in {None, "", pack["version"]}
    ]
    bindings = [
        item
        for item in repo.state.get("project_node_clause_packages", [])
        if item.get("projectId") in {project["id"] for project in projects}
    ]
    bindings_by_project: dict[str, list[dict]] = {}
    for binding in bindings:
        bindings_by_project.setdefault(str(binding["projectId"]), []).append(binding)
        package = package_by_id.get(binding.get("packageId"))
        if not package:
            errors.append(f"project binding references missing package: {binding.get('id')}")
        elif package.get("snapshotHash") != binding.get("packageSnapshotHash"):
            errors.append(f"project binding snapshot hash mismatch: {binding.get('id')}")
    for project in projects:
        project_bindings = bindings_by_project.get(str(project["id"]), [])
        if len(project_bindings) != len(expected["standard_clause_packages_db"]):
            errors.append(f"project {project['id']} has {len(project_bindings)} clause bindings")

    for snapshot in repo.state.get("review_run_clause_snapshots", []):
        payload = snapshot.get("snapshotPayload") or {}
        if snapshot.get("packageSnapshotHash") != payload.get("snapshotHash"):
            errors.append(f"review snapshot hash mismatch: {snapshot.get('id')}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "businessPackId": pack["id"],
        "businessPackVersion": pack["version"],
        "releaseId": release_id,
        "counts": counts,
        "projectCount": len(projects),
        "projectNodeBindingCount": len(bindings),
        "reviewRunClauseSnapshotCount": len(repo.state.get("review_run_clause_snapshots", [])),
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    if args.database_url:
        repo.configure_sync_postgres(args.database_url)
        repo.load_from_sync_postgres()
        backend = "postgres"
    else:
        repo.configure_sqlite(args.sqlite)
        repo.load_from_sqlite()
        backend = "sqlite"
    result = audit(args.pack_id)
    result["backend"] = backend
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
