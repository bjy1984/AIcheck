#!/usr/bin/env python3
"""冻结 / 校验标准库 MinerU 重识别基线。

用法：
  # 导出快照（只读）
  AICHECK_DATABASE_URL=... .venv/bin/python scripts/standards_mineru_baseline.py freeze

  # 断言当前库相对快照（只读；白名单断引用只告警）
  AICHECK_DATABASE_URL=... .venv/bin/python scripts/standards_mineru_baseline.py assert
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_BASELINE_DIR = BACKEND_ROOT / "data" / "standards_mineru_baseline"
DEFAULT_UPLOADS = REPO_ROOT / "output" / "knowledge_uploads" / "KS-STANDARD-RULES"
SOURCE_ID = "KS-STANDARD-RULES"

# 断引用修复后白名单为空。若再发现存量缺陷，按 locatorId 登记于此。
KNOWN_BROKEN_LOCATORS: frozenset[str] = frozenset()


def _connect(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc
    return psycopg.connect(database_url)


def _fetch_rows(connection, collection: str, *, source_filter: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    if collection == "knowledge_files":
        cur = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE collection = %s AND payload->>'sourceType' = 'standard'
            ORDER BY object_id
            """,
            (collection,),
        )
    elif collection == "knowledge_chunks":
        cur = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE collection = %s AND payload->>'sourceId' = %s
            ORDER BY object_id
            """,
            (collection, source_filter or SOURCE_ID),
        )
    elif collection == "knowledge_vectors":
        cur = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE collection = %s AND payload->>'sourceId' = %s
            ORDER BY object_id
            """,
            (collection, source_filter or SOURCE_ID),
        )
    elif collection == "knowledge_clauses":
        cur = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE collection = %s AND payload->'scope'->>'sourceId' = %s
            ORDER BY object_id
            """,
            (collection, source_filter or SOURCE_ID),
        )
    elif collection == "standard_clause_locators":
        cur = connection.execute(
            """
            SELECT object_id, payload
            FROM aicheck_state
            WHERE collection = %s
            ORDER BY object_id
            """,
            (collection,),
        )
    else:
        raise ValueError(f"unsupported collection: {collection}")
    rows: list[tuple[str, dict[str, Any]]] = []
    for object_id, payload in cur.fetchall():
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows.append((str(object_id), dict(payload)))
    return rows


def _pdf_page_count(path: Path) -> int | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(path)
        count = int(doc.page_count)
        doc.close()
        return count
    except Exception:
        return None


def _upload_file_for_kf(uploads_root: Path, knowledge_file_id: str) -> Path | None:
    directory = uploads_root / knowledge_file_id
    if not directory.is_dir():
        return None
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".doc", ".md"}
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.name)[0]


def freeze(connection, baseline_dir: Path, uploads_root: Path) -> dict[str, Any]:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    files = _fetch_rows(connection, "knowledge_files")
    chunks = _fetch_rows(connection, "knowledge_chunks")
    clauses = _fetch_rows(connection, "knowledge_clauses")
    vectors = _fetch_rows(connection, "knowledge_vectors")
    locators = _fetch_rows(connection, "standard_clause_locators")

    file_summaries = []
    for object_id, payload in files:
        upload = _upload_file_for_kf(uploads_root, object_id)
        pages = _pdf_page_count(upload) if upload else None
        file_summaries.append(
            {
                "knowledgeFileId": object_id,
                "fileName": payload.get("fileName"),
                "documentId": payload.get("documentId"),
                "documentVersionId": payload.get("documentVersionId"),
                "chunkCount": payload.get("chunkCount"),
                "vectorCount": payload.get("vectorCount"),
                "uploadPath": str(upload.relative_to(REPO_ROOT)) if upload else None,
                "pageCount": pages,
            }
        )

    locator_triples = []
    for _, payload in locators:
        locator_triples.append(
            {
                "locatorId": payload.get("locatorId") or payload.get("id"),
                "knowledgeFileId": payload.get("knowledgeFileId"),
                "documentVersionId": payload.get("documentVersionId"),
                "standardRef": payload.get("standardRef"),
                "clauseNo": payload.get("clauseNo"),
                "startPage": payload.get("startPage"),
                "endPage": payload.get("endPage"),
                "sourcePage": payload.get("sourcePage"),
                "precision": payload.get("precision"),
                "businessPackId": payload.get("businessPackId"),
                "releaseId": payload.get("releaseId"),
            }
        )

    id_lists = {
        "knowledge_chunks": [object_id for object_id, _ in chunks],
        "knowledge_clauses": [object_id for object_id, _ in clauses],
        "knowledge_vectors": [object_id for object_id, _ in vectors],
    }

    summary = {
        "frozenAt": datetime.now(timezone.utc).isoformat(),
        "sourceId": SOURCE_ID,
        "counts": {
            "knowledge_files": len(files),
            "knowledge_chunks": len(chunks),
            "knowledge_clauses": len(clauses),
            "knowledge_vectors": len(vectors),
            "standard_clause_locators": len(locators),
            "locator_files": len({item["knowledgeFileId"] for item in locator_triples}),
            "known_broken_locators": len(KNOWN_BROKEN_LOCATORS),
            "effective_locators": len(locators) - len(KNOWN_BROKEN_LOCATORS),
        },
        "expectedVectorCount": len(vectors),
        "knownBrokenLocators": sorted(KNOWN_BROKEN_LOCATORS),
        "offlineCandidates": [
            item
            for item in file_summaries
            if str(item.get("fileName") or "").endswith("承压设备无损检测-修订版.pdf")
        ],
    }

    (baseline_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (baseline_dir / "files.json").write_text(
        json.dumps(file_summaries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (baseline_dir / "locator_triples.json").write_text(
        json.dumps(locator_triples, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (baseline_dir / "id_lists.json").write_text(
        json.dumps(id_lists, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (baseline_dir / "known_broken_locators.json").write_text(
        json.dumps(
            {
                "note": "改造前存量断引用；修复后应从白名单移除并重新 freeze",
                "locatorIds": sorted(KNOWN_BROKEN_LOCATORS),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_structured_blocks(
    chunks: list[tuple[str, dict[str, Any]]],
    clauses: list[tuple[str, dict[str, Any]]],
    errors: list[str],
) -> dict[str, Any]:
    """公式/表格块必须带着 LaTeX 与表格 HTML 落到条款层。

    结构丢失是**静默**的：分块数照常、向量照常、检索照常返回，只是公式渲染不出
    来。所以这里逐条查「标了 equation 却没有 latex」这类自相矛盾的记录，让它在
    校验阶段就失败，而不是等前端渲染出一串反斜杠时才发现。
    """
    counts: dict[str, int] = {}
    missing_latex = 0
    missing_html = 0
    for _, payload in chunks:
        block_type = str(payload.get("blockType") or "").strip().lower()
        if not block_type:
            continue
        counts[block_type] = counts.get(block_type, 0) + 1
        if block_type == "equation" and not str(payload.get("latex") or "").strip():
            missing_latex += 1
        if block_type == "table" and not str(payload.get("tableHtml") or "").strip():
            missing_html += 1

    clause_structured = sum(1 for _, payload in clauses if str(payload.get("blockType") or "").strip())
    chunk_structured = sum(counts.values())

    if missing_latex:
        errors.append(f"{missing_latex} equation chunks carry no latex")
    if missing_html:
        errors.append(f"{missing_html} table chunks carry no tableHtml")
    if chunk_structured and clause_structured != chunk_structured:
        errors.append(
            f"structured chunks not fully mirrored on clauses: chunks={chunk_structured} clauses={clause_structured}"
        )
    return {
        "chunkBlockTypes": counts,
        "clauseStructured": clause_structured,
        "missingLatex": missing_latex,
        "missingTableHtml": missing_html,
    }


def assert_baseline(connection, baseline_dir: Path, uploads_root: Path) -> dict[str, Any]:
    summary = _load_json(baseline_dir / "summary.json")
    locator_baseline = _load_json(baseline_dir / "locator_triples.json")
    whitelist = set(_load_json(baseline_dir / "known_broken_locators.json").get("locatorIds") or [])

    files = {object_id: payload for object_id, payload in _fetch_rows(connection, "knowledge_files")}
    chunks = _fetch_rows(connection, "knowledge_chunks")
    clauses = _fetch_rows(connection, "knowledge_clauses")
    vectors = _fetch_rows(connection, "knowledge_vectors")
    locators = _fetch_rows(connection, "standard_clause_locators")

    errors: list[str] = []
    warnings: list[str] = []

    if len(chunks) != len(clauses) or len(chunks) != len(vectors):
        errors.append(
            f"derived index count mismatch: chunks={len(chunks)} clauses={len(clauses)} vectors={len(vectors)}"
        )

    page_failures: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for _, payload in locators:
        locator_id = str(payload.get("locatorId") or "")
        knowledge_file_id = str(payload.get("knowledgeFileId") or "")
        end_page = payload.get("endPage")
        file_payload = files.get(knowledge_file_id)
        if not file_payload:
            item = {
                "locatorId": locator_id,
                "knowledgeFileId": knowledge_file_id,
                "standardRef": payload.get("standardRef"),
            }
            if locator_id in whitelist:
                warnings.append(f"known broken locator (whitelisted): {locator_id} -> {knowledge_file_id}")
            else:
                broken.append(item)
                errors.append(f"locator points to missing knowledge file: {locator_id} -> {knowledge_file_id}")
            continue
        upload = _upload_file_for_kf(uploads_root, knowledge_file_id)
        pages = _pdf_page_count(upload) if upload else None
        if pages is not None and end_page is not None:
            try:
                end_page_int = int(end_page)
            except (TypeError, ValueError):
                end_page_int = -1
            if end_page_int > pages:
                page_failures.append(
                    {
                        "locatorId": locator_id,
                        "knowledgeFileId": knowledge_file_id,
                        "endPage": end_page_int,
                        "pageCount": pages,
                        "fileName": file_payload.get("fileName"),
                    }
                )
                errors.append(
                    f"page overflow: {locator_id} endPage={end_page_int} > pageCount={pages} ({knowledge_file_id})"
                )

    by_file: dict[str, list[dict[str, Any]]] = {}
    for item in page_failures:
        by_file.setdefault(str(item["knowledgeFileId"]), []).append(item)

    structured = _assert_structured_blocks(chunks, clauses, errors)

    result = {
        "status": "PASS" if not errors else "FAIL",
        "baselineFrozenAt": summary.get("frozenAt"),
        "counts": {
            "knowledge_files": len(files),
            "knowledge_chunks": len(chunks),
            "knowledge_clauses": len(clauses),
            "knowledge_vectors": len(vectors),
            "standard_clause_locators": len(locators),
            "baseline_locators": len(locator_baseline),
            "whitelisted_broken": len(whitelist),
        },
        "pageFailuresByFile": {key: len(value) for key, value in by_file.items()},
        "structuredBlocks": structured,
        "warnings": warnings,
        "errors": errors,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "assert"))
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--uploads-root", type=Path, default=DEFAULT_UPLOADS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")
    with _connect(args.database_url) as connection:
        if args.command == "freeze":
            result = freeze(connection, args.baseline_dir, args.uploads_root)
        else:
            result = assert_baseline(connection, args.baseline_dir, args.uploads_root)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    if args.command == "assert":
        return 0 if result.get("status") == "PASS" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
