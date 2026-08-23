#!/usr/bin/env python3
"""给标准库文件逐份重建向量。

## 为什么单独一个脚本

通用重建管线（`dispatch_knowledge_file_index_pipeline`）对标准库是禁止的——它会
先清派生索引再用通用切片器重建，把标准库的分块粒度整个换掉，而且**不报错**。
换向量的正确姿势是 `dispatch_embed`：它只重算向量、保留分块。

Track 1 的批量嵌入是一段临时 heredoc，跑完就没了；Track 2 重灌后又要再跑一遍，
所以固化成脚本。逐份 dispatch 而不是一次性全量，是为了让某一份失败时其余仍然
落库，日志里能直接看出是哪一份。

用法（注意是 `AICHECK_TASK_DISPATCH`，不带 `_MODE`；写错了 dispatch_mode() 会
静默返回 disabled，每份文件都"成功"返回空结果而一个向量都不写）：
  AICHECK_DATABASE_URL=... \\
  AICHECK_TASK_DISPATCH=inline \\
  AICHECK_EMBEDDING_PROVIDER=official \\
  AICHECK_EMBEDDING_MODEL_ID=text-embedding-v4 \\
  AICHECK_EMBEDDING_SERVED_MODEL_NAME=text-embedding-v4 \\
    .venv/bin/python scripts/embed_standard_library.py --apply
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

from libs.db.repository import repo  # noqa: E402

SOURCE_ID = "KS-STANDARD-RULES"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--file-id", action="append", default=[], help="只处理指定 KF，可重复")
    parser.add_argument("--only-pending", action="store_true", help="跳过 vectorStatus 已向量化的文件")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def target_files(file_ids: list[str], *, only_pending: bool) -> list[dict[str, Any]]:
    files = [
        item
        for item in repo.state.get("knowledge_files", [])
        if isinstance(item, dict) and item.get("sourceType") == "standard"
    ]
    if file_ids:
        wanted = set(file_ids)
        files = [item for item in files if str(item.get("id")) in wanted]
    if only_pending:
        files = [item for item in files if item.get("vectorStatus") != "已向量化"]
    return sorted(files, key=lambda item: str(item.get("id")))


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")

    repo.configure_sync_postgres(args.database_url)
    repo.load_from_sync_postgres()

    files = target_files(args.file_id, only_pending=args.only_pending)
    if args.limit > 0:
        files = files[: args.limit]
    print(f"pending_embed={len(files)}", flush=True)
    if not args.apply:
        for file in files:
            print(f"[dry-run] {file.get('id')} chunks={file.get('chunkCount')}", flush=True)
        return 0

    from libs.integrations import task_dispatcher

    # dispatch_mode() 读的是 AICHECK_TASK_DISPATCH。变量名写错时它返回 disabled，
    # dispatch_embed 会对每份文件都返回 {"taskId": None} 且不抛错——看上去跑完了，
    # 实际一个向量都没写。所以在动手前先把这种情况变成硬失败。
    mode = task_dispatcher.dispatch_mode()
    if mode not in {"inline", "celery"}:
        raise SystemExit(
            f"task dispatch mode is {mode!r}: 向量不会被写入。请设 AICHECK_TASK_DISPATCH=inline"
        )

    failures: list[str] = []
    for index, file in enumerate(files, start=1):
        file_id = str(file.get("id"))
        try:
            outcome = task_dispatcher.dispatch_embed(file_id)
        except Exception as exc:  # noqa: BLE001 - 单份失败不能中断整批
            failures.append(file_id)
            print(f"[{index}/{len(files)}] FAILED: {file_id} {type(exc).__name__}: {exc}", flush=True)
            continue
        result = (outcome or {}).get("result") or {}
        status = result.get("status") or outcome.get("mode") or "dispatched"
        vectors = result.get("vectorCount")
        if status not in {"success", "succeeded", "已向量化"}:
            failures.append(file_id)
            print(f"[{index}/{len(files)}] {status}: {file_id} {json.dumps(result, ensure_ascii=False)[:300]}", flush=True)
            continue
        print(f"[{index}/{len(files)}] success: {file_id} vectors={vectors}", flush=True)

    print(f"done total={len(files)} failed={len(failures)}", flush=True)
    if failures:
        print("failed_file_ids=" + ",".join(failures), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
