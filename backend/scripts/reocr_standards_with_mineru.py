#!/usr/bin/env python3
"""标准库专用重建：从 MinerU sidecar 重建分块 / 条款，并触发向量化。

**不得**调用 dispatch_knowledge_file_index_pipeline。

用法示例（`--embed` 要生效必须是 `AICHECK_TASK_DISPATCH`，不带 `_MODE`）：
  AICHECK_DATABASE_URL=... AICHECK_TASK_DISPATCH=inline \\
    .venv/bin/python scripts/reocr_standards_with_mineru.py --file-id KF-KB-xxx --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_SIDECAR = REPO_ROOT / "rules" / "results" / "mineru_sidecar"
SOURCE_ID = "KS-STANDARD-RULES"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from apps.ocr_service.engines import html_table_to_text  # noqa: E402
from libs.db.repository import repo  # noqa: E402
from libs.knowledge_indexing import (  # noqa: E402
    STANDARD_INDEX_VERSION,
    build_chunks_for_file,
    clause_from_chunk,
)
from libs.contracts.responses import server_time  # noqa: E402
from libs.mineru_ocr import (  # noqa: E402
    MinerUNormalizationError,
    build_mineru_result,
    mineru_pages,
)
from libs.security.tenant import configured_tenant_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "",
    )
    parser.add_argument("--sidecar-dir", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--file-id", action="append", default=[], help="只处理指定 KF，可重复；默认全部有 sidecar 的")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--embed", action="store_true", help="重建后 dispatch_embed")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="只把 sidecar 写入 ocr_parse_results，不改写切片、条款和向量",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _content_text(item: dict[str, Any]) -> str:
    for key in ("text", "latex", "content", "code_body", "code"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _content_latex(item: dict[str, Any]) -> str:
    """MinerU 的 equation 块把 LaTeX 放在 text 里，用 text_format 标注，没有 latex 字段。"""
    value = item.get("latex")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if str(item.get("text_format") or "").strip().lower() == "latex":
        value = item.get("text")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


SKIP_BLOCK_TYPES = {"header", "footer", "page_number", "page-number"}
STRUCTURED_SIDECAR_TYPES = {"equation", "interline_equation", "table"}


def _page_no(item: dict[str, Any]) -> int:
    if "page_idx" in item:
        try:
            return max(1, int(item["page_idx"]) + 1)
        except (TypeError, ValueError):
            return 1
    raw = item.get("pageNo", item.get("page"))
    try:
        return max(1, int(raw)) if raw is not None else 1
    except (TypeError, ValueError):
        return 1


def _html_to_text(html: Any) -> str:
    if not isinstance(html, str) or not html.strip():
        return ""
    return html_table_to_text(html)


def _caption(item: dict[str, Any]) -> str:
    for key in ("table_caption", "img_caption", "caption"):
        value = item.get(key)
        if isinstance(value, list):
            joined = " ".join(str(part).strip() for part in value if str(part or "").strip())
            if joined:
                return joined
        elif isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _section_path(heading_stack: dict[int, str]) -> list[str]:
    return [heading_stack[level] for level in sorted(heading_stack) if heading_stack.get(level)]


def fragments_from_content_list(items: list[Any]) -> list[dict[str, Any]]:
    """把 MinerU content_list 拆成「正文段 + 公式块 + 表格块」。

    公式和表格必须单独成块：一旦被合进大段正文，LaTeX 与表格 HTML 就再也无法
    从分块里还原，渲染和按类型检索都做不成。

    正文仍然**只按页**合并，标题层级（text_level）只用来填 sectionPath、不作为
    切分边界。按标题切过一版：sidecar 里 text_level=2 出现 8606 次，正文分块从
    3100 涨到 11209，正是护栏文档里记着的那种粒度爆炸。Track 2 要解决的是公式
    和表格的结构，不是把全库正文重新切一遍。
    """
    fragments: list[dict[str, Any]] = []
    heading_stack: dict[int, str] = {}
    buffer: list[str] = []
    buffer_page: int | None = None
    buffer_section: list[str] = []

    def flush() -> None:
        nonlocal buffer, buffer_page, buffer_section
        merged = "\n".join(buffer).strip()
        if merged and buffer_page is not None:
            fragments.append(
                {
                    "text": merged,
                    "pageNo": buffer_page,
                    "bbox": None,
                    "sourceMethod": "mineru_ocr",
                    "ocrEngine": "mineru",
                    "sectionPath": list(buffer_section),
                }
            )
        buffer = []
        buffer_page = None
        buffer_section = []

    for item in items:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").lower()
        if block_type in SKIP_BLOCK_TYPES:
            continue
        page_no = _page_no(item)

        if block_type in STRUCTURED_SIDECAR_TYPES:
            flush()
            caption = _caption(item)
            if block_type == "table":
                html = str(item.get("table_body") or item.get("html") or "")
                body = _html_to_text(html)
                footnote = _caption({"caption": item.get("table_footnote")})
                text = "\n".join(part for part in (caption, body, footnote) if part).strip()
                if not text:
                    continue
                fragments.append(
                    {
                        "text": text,
                        "pageNo": page_no,
                        "bbox": item.get("bbox"),
                        "sourceMethod": "mineru_ocr",
                        "ocrEngine": "mineru",
                        "sectionPath": _section_path(heading_stack),
                        "blockType": "table",
                        "tableHtml": html,
                        "caption": caption,
                    }
                )
                continue
            latex = _content_latex(item)
            text = latex or _content_text(item)
            if not text:
                continue
            fragments.append(
                {
                    "text": text,
                    "pageNo": page_no,
                    "bbox": item.get("bbox"),
                    "sourceMethod": "mineru_ocr",
                    "ocrEngine": "mineru",
                    "sectionPath": _section_path(heading_stack),
                    "blockType": "equation",
                    "latex": latex,
                    "caption": caption,
                }
            )
            continue

        text = _content_text(item) or _html_to_text(item.get("table_body") or item.get("html"))
        if not text:
            continue

        try:
            level = int(item.get("text_level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level > 0:
            heading_stack[level] = text
            for deeper in [key for key in heading_stack if key > level]:
                heading_stack.pop(deeper)

        if buffer_page is not None and buffer_page != page_no:
            flush()
        if buffer_page is None:
            buffer_page = page_no
            buffer_section = _section_path(heading_stack)
        buffer.append(text)

    flush()
    return fragments


def fragments_from_markdown(text: str) -> list[dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("{"):
        # meta.json 前缀：取正文
        parts = cleaned.split("\n\n# OCR 提取结果\n\n", 1)
        cleaned = parts[1] if len(parts) == 2 else cleaned
    cleaned = cleaned.strip()
    if not cleaned or cleaned == "(empty)":
        return []
    # 无页结构时整篇作为第 1 页；后续 Track 2 再用 content_list
    return [
        {
            "text": cleaned,
            "pageNo": 1,
            "bbox": None,
            "sourceMethod": "mineru_ocr",
            "ocrEngine": "mineru",
            "sectionPath": [],
        }
    ]


def load_fragments(sidecar_dir: Path, file_id: str) -> tuple[list[dict[str, Any]], str]:
    directory = sidecar_dir / file_id
    content_list_path = directory / "content_list.json"
    full_md_path = directory / "full.md"
    if content_list_path.exists():
        raw = json.loads(content_list_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            fragments = fragments_from_content_list(raw)
            if fragments:
                return fragments, "content_list.json"
    if full_md_path.exists():
        return fragments_from_markdown(full_md_path.read_text(encoding="utf-8")), "full.md"
    return [], "missing"


def discover_targets(sidecar_dir: Path, file_ids: list[str]) -> list[str]:
    if file_ids:
        return file_ids
    if not sidecar_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in sidecar_dir.iterdir()
        if path.is_dir() and not path.name.startswith("_") and (path / "meta.json").exists()
    )


def _fallback_pages(content: list[Any]) -> list[dict[str, Any]]:
    page_indexes = []
    for item in content:
        if not isinstance(item, dict):
            continue
        try:
            page_indexes.append(max(0, int(item.get("page_idx") or 0)))
        except (TypeError, ValueError):
            page_indexes.append(0)
    page_count = max(page_indexes, default=0) + 1
    return [
        {
            "pageNo": page_no,
            "width": None,
            "height": None,
            "coordinateSystem": None,
            "sourceCoordinateSystem": "mineru_normalized_1000",
        }
        for page_no in range(1, page_count + 1)
    ]


def build_sidecar_parse_result(
    sidecar_dir: Path,
    file: dict[str, Any],
    document: dict[str, Any],
    version: dict[str, Any],
) -> dict[str, Any]:
    """把落盘 MinerU sidecar 转成详情页可直接消费的正式 OCR 结果。"""
    file_id = str(file["id"])
    directory = sidecar_dir / file_id
    content_path = directory / "content_list.json"
    if not content_path.is_file():
        raise ValueError(f"content_list.json missing for {file_id}")
    content = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(content, list) or not content:
        raise ValueError(f"content_list.json is empty for {file_id}")

    layout_path = directory / "layout.json"
    layout_missing = not layout_path.is_file()
    if layout_missing:
        pages = _fallback_pages(content)
    else:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        if not isinstance(layout, dict):
            raise ValueError(f"layout.json is invalid for {file_id}")
        pages = mineru_pages(layout)

    result = build_mineru_result(
        content,
        pages=pages,
        storage_key=str(version.get("storageKey") or ""),
        file_name=str(file.get("fileName") or document.get("fileName") or file_id),
        profile_id="generic_document_v1",
        document_type="standard_reference",
        provider_task_id=f"standard-sidecar:{file_id}",
        markdown_present=(directory / "full.md").is_file(),
    )
    version_id = str(version["id"])
    parse_result_id = f"PARSE-STANDARD-{version_id.removeprefix('KDV-')}"
    sidecar_hash = hashlib.sha256(
        content_path.read_bytes() + (layout_path.read_bytes() if layout_path.is_file() else b"")
    ).hexdigest()
    now = server_time()
    result.update(
        {
            "id": parse_result_id,
            "parseResultId": parse_result_id,
            "documentId": str(document["id"]),
            "documentVersionId": version_id,
            "tenantId": configured_tenant_id(),
            "finishedAt": now,
            "createdAt": now,
        }
    )
    result.setdefault("metadata", {}).update(
        {
            "sidecarSource": f"rules/results/mineru_sidecar/{file_id}",
            "sidecarImported": True,
            "sidecarContentHash": sidecar_hash,
            "layoutFallback": layout_missing,
        }
    )
    if layout_missing:
        quality = result.setdefault("quality", {})
        quality["reasons"] = list(
            dict.fromkeys([*(quality.get("reasons") or []), "sidecar_layout_missing"])
        )
    return result


def merge_ocr_status_payload(
    current: dict[str, Any],
    *,
    expected_id: str,
    status_field: str,
    now: str,
) -> dict[str, Any]:
    if str(current.get("id") or "") != str(expected_id):
        raise ValueError(f"identity mismatch: expected {expected_id}")
    return {**current, status_field: "已识别", "updatedAt": now}


def should_sync_page_index(args: argparse.Namespace, results: list[dict[str, Any]]) -> bool:
    return bool(
        args.apply
        and not args.parse_only
        and any(item.get("status") == "applied" for item in results)
    )


def persist_parse_result(
    parse_result: dict[str, Any],
    file: dict[str, Any],
    document: dict[str, Any],
    version: dict[str, Any],
    database_url: str,
) -> None:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    now = server_time()
    tenant_id = configured_tenant_id()
    for record_name, record in (("file", file), ("document", document), ("version", version)):
        payload_tenant = str(record.get("tenantId") or tenant_id)
        if payload_tenant != tenant_id:
            raise ValueError(f"tenant mismatch for {record_name}: {payload_tenant}")

    with psycopg.connect(database_url, autocommit=False) as connection:
        locked: dict[str, dict[str, Any]] = {}
        for collection, object_id in (
            ("documents", str(document["id"])),
            ("document_versions", str(version["id"])),
            ("knowledge_files", str(file["id"])),
        ):
            row = connection.execute(
                """
                SELECT payload FROM aicheck_state
                WHERE tenant_id=%s AND collection=%s AND object_id=%s
                FOR UPDATE
                """,
                (tenant_id, collection, object_id),
            ).fetchone()
            if not row or not isinstance(row[0], dict):
                raise ValueError(f"missing locked record: {collection}/{object_id}")
            locked[collection] = dict(row[0])

        locked_document = locked["documents"]
        locked_version = locked["document_versions"]
        locked_file = locked["knowledge_files"]
        if str(locked_document.get("currentVersionId") or "") != str(version["id"]):
            raise ValueError("current version changed during sidecar import")
        if str(locked_version.get("documentId") or "") != str(document["id"]):
            raise ValueError("version/document relationship mismatch")
        if (
            str(locked_file.get("documentId") or "") != str(document["id"])
            or str(locked_file.get("documentVersionId") or "") != str(version["id"])
        ):
            raise ValueError("knowledge file relationship mismatch")

        merged_records = (
            (
                "documents",
                merge_ocr_status_payload(
                    locked_document,
                    expected_id=str(document["id"]),
                    status_field="currentOcrStatus",
                    now=now,
                ),
            ),
            (
                "document_versions",
                merge_ocr_status_payload(
                    locked_version,
                    expected_id=str(version["id"]),
                    status_field="ocrStatus",
                    now=now,
                ),
            ),
            (
                "knowledge_files",
                merge_ocr_status_payload(
                    locked_file,
                    expected_id=str(file["id"]),
                    status_field="ocrStatus",
                    now=now,
                ),
            ),
        )
        for collection, merged in merged_records:
            connection.execute(
                """
                UPDATE aicheck_state SET payload=%s, updated_at=now()
                WHERE tenant_id=%s AND collection=%s AND object_id=%s
                """,
                (Jsonb(merged), tenant_id, collection, str(merged["id"])),
            )

        parse_result["tenantId"] = tenant_id
        existing_parse = connection.execute(
            """
            SELECT payload FROM aicheck_state
            WHERE tenant_id=%s AND collection='ocr_parse_results' AND object_id=%s
            FOR UPDATE
            """,
            (tenant_id, str(parse_result["id"])),
        ).fetchone()
        if existing_parse and isinstance(existing_parse[0], dict):
            previous = dict(existing_parse[0])
            if (
                (previous.get("metadata") or {}).get("sidecarContentHash")
                == (parse_result.get("metadata") or {}).get("sidecarContentHash")
            ):
                parse_result["createdAt"] = previous.get("createdAt") or parse_result["createdAt"]
                parse_result["finishedAt"] = previous.get("finishedAt") or parse_result["finishedAt"]
        connection.execute(
            """
            INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
            VALUES (%s, 'ocr_parse_results', %s, %s, now())
            ON CONFLICT (tenant_id, collection, object_id)
            DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()
            """,
            (tenant_id, str(parse_result["id"]), Jsonb(parse_result)),
        )
        connection.commit()

    document.update(merge_ocr_status_payload(document, expected_id=str(document["id"]), status_field="currentOcrStatus", now=now))
    version.update(merge_ocr_status_payload(version, expected_id=str(version["id"]), status_field="ocrStatus", now=now))
    file.update(merge_ocr_status_payload(file, expected_id=str(file["id"]), status_field="ocrStatus", now=now))

    existing = [
        item
        for item in repo.state.get("ocr_parse_results", [])
        if str(item.get("id") or item.get("parseResultId") or "") != parse_result["id"]
    ]
    repo.state["ocr_parse_results"] = [parse_result, *existing]


def rebuild_file(file: dict[str, Any], fragments: list[dict[str, Any]]) -> dict[str, Any]:
    file_id = str(file["id"])
    old_chunk_ids = [
        str(item.get("id"))
        for item in repo.state.get("knowledge_chunks", [])
        if item.get("fileId") == file_id
    ]
    old_vector_ids = [
        str(item.get("id"))
        for item in repo.state.get("knowledge_vectors", [])
        if item.get("fileId") == file_id
    ]
    old_clause_ids = [
        str(item.get("id"))
        for item in repo.state.get("knowledge_clauses", [])
        if item.get("fileId") == file_id
        or (item.get("scope") or {}).get("fileId") == file_id
    ]

    chunks = build_chunks_for_file(file, fragments, index_version=STANDARD_INDEX_VERSION)
    now = server_time()
    for chunk in chunks:
        chunk["createdAt"] = now
        chunk["updatedAt"] = now

    source = repo.find_one("knowledge_sources", file.get("sourceId") or SOURCE_ID)
    source_version = str((source or {}).get("version") or "inspection_kb@1.0.0")
    clauses = [clause_from_chunk(file, chunk, source_version) for chunk in chunks]

    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") != file_id
    ]
    repo.state["knowledge_vectors"] = [
        item for item in repo.state.get("knowledge_vectors", []) if item.get("fileId") != file_id
    ]
    repo.state["knowledge_clauses"] = [
        item
        for item in repo.state.get("knowledge_clauses", [])
        if item.get("fileId") != file_id and (item.get("scope") or {}).get("fileId") != file_id
    ]
    repo.state.setdefault("knowledge_chunks", []).extend(chunks)
    repo.state.setdefault("knowledge_clauses", []).extend(clauses)

    file["sliceStatus"] = "已切片" if chunks else "切片失败"
    file["chunkCount"] = len(chunks)
    file["vectorStatus"] = "待向量化" if chunks else "向量化失败"
    file["vectorCount"] = 0
    file["indexVersion"] = STANDARD_INDEX_VERSION
    file["ocrStatus"] = "已识别"
    file["updatedAt"] = now

    return {
        "fileId": file_id,
        "chunkCount": len(chunks),
        "clauseCount": len(clauses),
        "deletedChunkIds": old_chunk_ids,
        "deletedVectorIds": old_vector_ids,
        "deletedClauseIds": old_clause_ids,
        "newChunkIds": [chunk["id"] for chunk in chunks],
        "newClauseIds": [clause["id"] for clause in clauses],
    }


def persist(plan: dict[str, Any], file: dict[str, Any], database_url: str) -> None:
    """离线重建走直连 SQL，避开同 ID「先删后写」触发的 ConcurrentPersistenceError。"""
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    file_id = plan["fileId"]
    chunks = [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == file_id]
    clauses = [
        item
        for item in repo.state.get("knowledge_clauses", [])
        if item.get("fileId") == file_id or (item.get("scope") or {}).get("fileId") == file_id
    ]
    tenant_id = str(file.get("tenantId") or "TENANT-DEFAULT")

    with psycopg.connect(database_url, autocommit=False) as connection:
        for collection, object_ids in (
            ("knowledge_chunks", plan["deletedChunkIds"]),
            ("knowledge_vectors", plan["deletedVectorIds"]),
            ("knowledge_clauses", plan["deletedClauseIds"]),
        ):
            for object_id in object_ids:
                connection.execute(
                    "DELETE FROM aicheck_state WHERE tenant_id=%s AND collection=%s AND object_id=%s",
                    (tenant_id, collection, object_id),
                )
        for collection, docs in (
            ("knowledge_chunks", chunks),
            ("knowledge_clauses", clauses),
            ("knowledge_files", [file]),
        ):
            for doc in docs:
                object_id = str(doc.get("id") or "")
                if not object_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, collection, object_id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (tenant_id, collection, object_id, Jsonb(doc)),
                )
        connection.commit()


def persist_page_index(database_url: str, source_id: str = SOURCE_ID) -> dict[str, Any]:
    """重建后补齐 page_index 节点。

    路径 B 的 persist() 用直连 SQL 写分块，内存与 Postgres 一致，但
    assert_persistence_baseline 的基线还是旧的——再走 flush_to_sync_postgres
    会触发 ConcurrentPersistenceError。所以 page_index 也走直连 SQL。
    """
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(f"psycopg is required: {exc}") from exc

    repo.sync_standard_page_index_for_source(source_id)
    nodes = [
        item
        for item in repo.state.get("knowledge_page_index_nodes", [])
        if item.get("kbDocId") == source_id
    ]
    # sync_standard_page_index_for_source 也会按当前 chunks 重写 clauses；
    # 结构字段经 clause_from_chunk 带回来，需要一并落库。
    clauses = [
        item
        for item in repo.state.get("knowledge_clauses", [])
        if item.get("kbDocId") == source_id
        or (item.get("scope") or {}).get("sourceId") == source_id
    ]
    tenant_id = "TENANT-DEFAULT"
    for file in repo.state.get("knowledge_files", []):
        if file.get("sourceId") == source_id and file.get("tenantId"):
            tenant_id = str(file["tenantId"])
            break

    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute(
            """
            DELETE FROM aicheck_state
            WHERE tenant_id=%s AND collection='knowledge_page_index_nodes'
              AND payload->>'kbDocId'=%s
            """,
            (tenant_id, source_id),
        )
        for collection, docs in (
            ("knowledge_page_index_nodes", nodes),
            ("knowledge_clauses", clauses),
        ):
            for doc in docs:
                object_id = str(doc.get("id") or doc.get("pageIndexNodeId") or "")
                if not object_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (tenant_id, collection, object_id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (tenant_id, collection, object_id, Jsonb(doc)),
                )
        connection.commit()
    return {"pageIndexNodes": len(nodes), "clauses": len(clauses)}


def main() -> int:
    args = parse_args()
    if args.dry_run:
        args.apply = False
    if not args.database_url:
        raise SystemExit("AICHECK_DATABASE_URL or --database-url is required")

    repo.configure_sync_postgres(args.database_url)
    repo.load_from_sync_postgres()

    targets = discover_targets(args.sidecar_dir, args.file_id)
    if args.limit > 0:
        targets = targets[: args.limit]

    results: list[dict[str, Any]] = []
    for file_id in targets:
        file = repo.find_one("knowledge_files", file_id)
        if not file or file.get("sourceType") != "standard":
            results.append({"fileId": file_id, "status": "skipped", "reason": "not_a_standard_knowledge_file"})
            continue
        document = repo.find_one("documents", file.get("documentId"))
        version_id = str((document or {}).get("currentVersionId") or "")
        version = repo.find_one("versions", version_id) if version_id else None
        if not document or not version:
            results.append({"fileId": file_id, "status": "skipped", "reason": "document_or_version_missing"})
            continue
        if args.parse_only:
            try:
                parse_result = build_sidecar_parse_result(args.sidecar_dir, file, document, version)
            except (OSError, ValueError, json.JSONDecodeError, MinerUNormalizationError) as exc:
                results.append({"fileId": file_id, "status": "skipped", "reason": f"parse_result:{exc}"})
                continue
            if args.apply:
                persist_parse_result(parse_result, file, document, version, args.database_url)
            results.append(
                {
                    "fileId": file_id,
                    "status": "applied" if args.apply else "planned",
                    "parseResultId": parse_result["parseResultId"],
                    "layoutBlocks": len(parse_result.get("layoutBlocks") or []),
                    "tables": len(parse_result.get("tables") or []),
                    "seals": len(parse_result.get("seals") or []),
                    "pages": len(parse_result.get("pages") or []),
                }
            )
            continue
        fragments, source_kind = load_fragments(args.sidecar_dir, file_id)
        if not fragments:
            results.append({"fileId": file_id, "status": "skipped", "reason": f"no_fragments:{source_kind}"})
            continue
        plan = rebuild_file(file, fragments)
        plan.update(
            {
                "status": "planned" if not args.apply else "applied",
                "fragmentSource": source_kind,
                "fragmentCount": len(fragments),
            }
        )
        if args.apply:
            persist(plan, file, args.database_url)
            if args.embed:
                from libs.integrations import task_dispatcher

                plan["embedDispatch"] = task_dispatcher.dispatch_embed(file_id)
        results.append(plan)

    # 路径 B 原先不写 page_index，Track 1/2 换了 CHK-* 之后节点上的
    # linkedClauseIds 指向已不存在的分块——pageindex_tree_search 对标准库
    # 等于白给。重建后必须把 page_index 与新分块对齐。
    page_index_synced = None
    if should_sync_page_index(args, results):
        page_index_synced = persist_page_index(args.database_url)

    payload = {
        "mode": "apply" if args.apply else "dry-run",
        "processed": len(results),
        "pageIndexSynced": page_index_synced,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
