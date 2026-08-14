from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from libs.db.repository import repo
from libs.db.seed import fresh_state

SYNC_COLLECTIONS = [
    "knowledge_sources",
    "knowledge_files",
    "knowledge_tasks",
    "knowledge_chunks",
    "knowledge_clauses",
    "knowledge_page_index_nodes",
    "rule_versions",
    "business_packs",
]

SYNC_SINGLETONS = ["admin_config", "knowledge_config"]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def sync_seeded_business_data() -> dict[str, Any]:
    seed = fresh_state()
    repo.configure_sqlite()
    repo.load_from_sqlite()
    for collection in SYNC_COLLECTIONS:
        repo.state[collection] = repo.clone(seed.get(collection, []))
    for singleton in SYNC_SINGLETONS:
        repo.state[singleton] = repo.clone(seed.get(singleton))
    repo.flush_to_sqlite()
    return seed


def sqlite_counts(sqlite_path: str) -> dict[str, int]:
    with sqlite3.connect(sqlite_path) as connection:
        state_rows = connection.execute(
            "SELECT collection, COUNT(*) FROM aicheck_state GROUP BY collection"
        ).fetchall()
        singletons = connection.execute("SELECT COUNT(*) FROM aicheck_singletons").fetchone()[0]
    counts = {collection: int(count) for collection, count in state_rows}
    counts["aicheck_singletons"] = int(singletons)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap AIcheck local SQLite persistence.")
    parser.add_argument(
        "--env-file",
        default=str(Path(__file__).resolve().parents[1] / ".env"),
        help="Optional env file used to resolve AICHECK_SQLITE_PATH.",
    )
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    seed = sync_seeded_business_data()
    if not repo.sqlite_path:
        raise SystemExit("SQLite persistence is not configured.")
    counts = sqlite_counts(repo.sqlite_path)
    summary = {
        "sqlitePath": repo.sqlite_path,
        "databaseConnected": True,
        "standardSources": len(seed.get("knowledge_sources", [])),
        "standardFiles": len(seed.get("knowledge_files", [])),
        "businessRuleVersions": len(seed.get("rule_versions", [])),
        "businessPacks": len(seed.get("business_packs", [])),
        "workflowStateMachines": len((seed.get("admin_config") or {}).get("workflowStateMachines") or []),
        "sqliteCollections": counts,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
