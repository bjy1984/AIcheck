"""Optional read-only standard corpus, independent of engineering persistence."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

SCHEMA = "inspection-standard-corpus-v1"


@lru_cache(maxsize=1)
def _read(path: str, modified: int, size: int) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != SCHEMA:
        raise ValueError("Unsupported inspection standard corpus schema")
    state = payload["state"]
    for collection in ("knowledge_files", "documents", "standard_knowledge_records"):
        if any(item.get("projectId") for item in state.get(collection, [])):
            raise ValueError("Inspection standard corpus must not contain project documents")
    ids = {file["id"] for file in state["knowledge_files"] if file.get("sourceType") == "standard"}
    if len(ids) != len(state["knowledge_files"]) or any(
        record.get("knowledgeFileId") not in ids for record in state["standard_knowledge_records"]
    ):
        raise ValueError("Invalid standard corpus file references")
    return state


def standard_state(fallback: dict) -> dict:
    configured = os.getenv("AICHECK_INSPECTION_CORPUS", "").strip()
    if not configured:
        default = Path("output/inspection-standard-corpus/corpus.json")
        if not default.is_file():
            return fallback
        configured = str(default)
    path = Path(configured).expanduser().resolve()
    info = path.stat()
    return _read(str(path), info.st_mtime_ns, info.st_size)
