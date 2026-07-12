#!/usr/bin/env python3
"""Publish generated standard-clause artifacts into the current state database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.business_pack import list_business_packs, load_business_pack
from libs.business_pack.clause_store import (
    CLAUSE_STATE_COLLECTIONS,
    bind_project_node_clause_packages,
    publish_standard_clause_release,
)
from libs.db.repository import repo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    parser.add_argument("--sqlite", type=Path, default=Path("data/aicheck.sqlite3"))
    parser.add_argument("--database-url", default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def publish(pack_id: str) -> dict[str, Any]:
    available = {item["id"] for item in list_business_packs()}
    if pack_id not in available:
        raise ValueError(f"unknown business pack: {pack_id}")
    pack = load_business_pack(pack_id)
    counts = publish_standard_clause_release(repo.state, pack)
    bound_projects = 0
    bound_nodes = 0
    for project in repo.state.get("projects", []):
        if project.get("businessPackId") != pack["id"]:
            continue
        if project.get("businessPackVersion") not in {None, "", pack["version"]}:
            continue
        bound_projects += 1
        bound_nodes += bind_project_node_clause_packages(
            repo.state,
            project,
            pack,
            bound_at=project.get("updatedAt"),
        )
    return {
        "businessPackId": pack["id"],
        "businessPackVersion": pack["version"],
        "businessPackSnapshotHash": pack["snapshotHash"],
        "releaseCounts": counts,
        "boundProjects": bound_projects,
        "boundProjectNodes": bound_nodes,
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

    result = publish(args.pack_id)
    result.update({"mode": "apply" if args.apply else "dry-run", "backend": backend})
    if args.apply:
        records = {key: repo.state.get(key, []) for key in CLAUSE_STATE_COLLECTIONS}
        if backend == "postgres":
            repo.upsert_state_records_to_sync_postgres(records)
        else:
            repo.sync_state_records_to_sqlite(records, {})
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
