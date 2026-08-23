#!/usr/bin/env python3
"""从标准库下线 NB／T 47013-2015 修订版合集（已被 NB_T_47013_split 取代）。

默认 dry-run；加 --apply 才写库。只动 knowledge_files / chunks / clauses / vectors，
不改 rules.yaml 里的业务规则文件引用（那是另一条人工维护线）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

TARGET_FILE_ID = "KF-KB-B4C51A523B"
TARGET_NAME_SUFFIX = "承压设备无损检测-修订版.pdf"
SOURCE_ID = "KS-STANDARD-RULES"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--file-id", default=TARGET_FILE_ID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _payload(row: Any) -> dict[str, Any]:
    payload = row[1] if not isinstance(row, dict) else row
    if isinstance(payload, str):
        payload = json.loads(payload)
    return dict(payload)


def plan_offline(connection, file_id: str) -> dict[str, Any]:
    file_row = connection.execute(
        "SELECT object_id, payload FROM aicheck_state WHERE collection='knowledge_files' AND object_id=%s",
        (file_id,),
    ).fetchone()
    if not file_row:
        return {"status": "missing", "fileId": file_id, "error": "knowledge_files record not found"}
    file_payload = _payload(file_row)
    file_name = str(file_payload.get("fileName") or "")
    if TARGET_NAME_SUFFIX not in file_name:
        return {
            "status": "refused",
            "fileId": file_id,
            "fileName": file_name,
            "error": f"fileName does not contain expected suffix {TARGET_NAME_SUFFIX!r}",
        }

    chunk_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT object_id FROM aicheck_state
            WHERE collection='knowledge_chunks'
              AND payload->>'sourceId'=%s
              AND payload->>'fileId'=%s
            """,
            (SOURCE_ID, file_id),
        ).fetchall()
    ]
    clause_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT object_id FROM aicheck_state
            WHERE collection='knowledge_clauses'
              AND payload->'scope'->>'sourceId'=%s
              AND (payload->>'fileId'=%s OR payload->'scope'->>'fileId'=%s)
            """,
            (SOURCE_ID, file_id, file_id),
        ).fetchall()
    ]
    vector_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT object_id FROM aicheck_state
            WHERE collection='knowledge_vectors'
              AND payload->>'sourceId'=%s
              AND payload->>'fileId'=%s
            """,
            (SOURCE_ID, file_id),
        ).fetchall()
    ]
    locator_hits = connection.execute(
        """
        SELECT count(*) FROM aicheck_state
        WHERE collection='standard_clause_locators'
          AND payload->>'knowledgeFileId'=%s
        """,
        (file_id,),
    ).fetchone()[0]

    return {
        "status": "planned",
        "fileId": file_id,
        "fileName": file_name,
        "documentVersionId": file_payload.get("documentVersionId"),
        "delete": {
            "knowledge_files": 1,
            "knowledge_chunks": len(chunk_ids),
            "knowledge_clauses": len(clause_ids),
            "knowledge_vectors": len(vector_ids),
        },
        "chunkIds": chunk_ids,
        "clauseIds": clause_ids,
        "vectorIds": vector_ids,
        "locatorReferences": int(locator_hits),
        "warning": None
        if int(locator_hits) == 0
        else "this file still has locators; refuse apply until locators are retargeted",
    }


def apply_offline(connection, plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("status") != "planned":
        raise SystemExit(f"cannot apply: {plan}")
    if plan.get("locatorReferences"):
        raise SystemExit("refusing to offline a file that still has standard_clause_locators")
    file_id = plan["fileId"]
    deleted = {"knowledge_files": 0, "knowledge_chunks": 0, "knowledge_clauses": 0, "knowledge_vectors": 0}
    for collection, ids in (
        ("knowledge_chunks", plan["chunkIds"]),
        ("knowledge_clauses", plan["clauseIds"]),
        ("knowledge_vectors", plan["vectorIds"]),
    ):
        for object_id in ids:
            connection.execute(
                "DELETE FROM aicheck_state WHERE collection=%s AND object_id=%s",
                (collection, object_id),
            )
            deleted[collection] += 1
    connection.execute(
        "DELETE FROM aicheck_state WHERE collection='knowledge_files' AND object_id=%s",
        (file_id,),
    )
    deleted["knowledge_files"] = 1
    # 同步 source 计数（若存在）
    source = connection.execute(
        "SELECT payload FROM aicheck_state WHERE collection='knowledge_sources' AND object_id=%s",
        (SOURCE_ID,),
    ).fetchone()
    if source:
        payload = _payload((SOURCE_ID, source[0]))
        try:
            payload["fileCount"] = max(0, int(payload.get("fileCount") or 0) - 1)
        except (TypeError, ValueError):
            pass
        connection.execute(
            """
            UPDATE aicheck_state
            SET payload=%s::jsonb, updated_at=now()
            WHERE collection='knowledge_sources' AND object_id=%s
            """,
            (json.dumps(payload, ensure_ascii=False), SOURCE_ID),
        )
    connection.commit()
    return {"status": "applied", "fileId": file_id, "deleted": deleted}


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    with psycopg.connect(args.database_url, autocommit=False) as connection:
        plan = plan_offline(connection, args.file_id)
        result: dict[str, Any] = {"plan": plan, "applied": None}
        if args.apply:
            if plan.get("status") != "planned":
                print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
                return 1
            result["applied"] = apply_offline(connection, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if plan.get("status") == "planned" or result.get("applied") else 1


if __name__ == "__main__":
    raise SystemExit(main())
