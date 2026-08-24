#!/usr/bin/env python3
"""给存量表格分块补上结构化行字段，不重灌、不重嵌。

Track 2 落库时只写了 `tableHtml`。渲染约定是接口不下发 html，要给
`tableColumns` / `tableRows`。本次补字段不动 `text`，向量一个字都不会变。

用法：
  AICHECK_DATABASE_URL=... .venv/bin/python scripts/backfill_table_structure_fields.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.knowledge_indexing import table_view_fields_from_html  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def needs_backfill(payload: dict[str, Any]) -> bool:
    if str(payload.get("blockType") or "").strip().lower() != "table":
        return False
    if not str(payload.get("tableHtml") or "").strip():
        return False
    columns = payload.get("tableColumns")
    rows = payload.get("tableRows")
    return not (isinstance(columns, list) and columns and isinstance(rows, list))


def enrich(payload: dict[str, Any]) -> dict[str, Any] | None:
    view = table_view_fields_from_html(str(payload.get("tableHtml") or ""))
    if not view.get("tableColumns"):
        return None
    updated = dict(payload)
    updated.update(view)
    return updated


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    planned: list[tuple[str, str, dict[str, Any]]] = []
    with psycopg.connect(args.database_url) as connection:
        for collection in ("knowledge_chunks", "knowledge_clauses"):
            rows = connection.execute(
                """
                SELECT tenant_id, object_id, payload
                FROM aicheck_state
                WHERE collection = %s
                  AND payload->>'blockType' = 'table'
                ORDER BY object_id
                """,
                (collection,),
            ).fetchall()
            for tenant_id, object_id, payload in rows:
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict) or not needs_backfill(payload):
                    continue
                updated = enrich(payload)
                if not updated:
                    continue
                planned.append((collection, str(object_id), updated))
                if args.limit > 0 and len(planned) >= args.limit:
                    break
            if args.limit > 0 and len(planned) >= args.limit:
                break

    print(f"pending_backfill={len(planned)}", flush=True)
    if not args.apply:
        for collection, object_id, payload in planned[:5]:
            print(
                f"[dry-run] {collection}/{object_id} columns={payload.get('tableColumns')}",
                flush=True,
            )
        return 0

    with psycopg.connect(args.database_url, autocommit=False) as connection:
        for collection, object_id, payload in planned:
            connection.execute(
                """
                UPDATE aicheck_state
                SET payload = %s, updated_at = now()
                WHERE collection = %s AND object_id = %s
                """,
                (Jsonb(payload), collection, object_id),
            )
        connection.commit()
    print(f"applied={len(planned)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
