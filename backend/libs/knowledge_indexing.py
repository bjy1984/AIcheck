from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

OFFLINE_EMBEDDING_MODEL = "offline-hash-v1"
OFFLINE_VECTOR_DIMENSIONS = 1024
STANDARD_INDEX_VERSION = "knowledge-index-offline-hash-v1@1024"
QWEN3_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
QWEN3_INDEX_VERSION = "knowledge-index-qwen3-0.6b@1024"
PAGE_INDEX_VERSION = "pageindex-standard-rules-v1"
EMBED_BATCH_SIZE = 32
MAX_CHUNK_CHARS = 1800
NOISE_TEXT_MARKERS = ("bzfxw", "标准分享网", "免费下载", "kqqw", "库七七", "提供下载")
PUBLISHER_METADATA_RE = re.compile(
    r"(出版社|出版发行|书号|定价[:：]?\s*\d|侵权必究|版权专有|新华书店|印刷有限|"
    r"如有印装质量问题|封面无防伪标均为盗版|举报电话)"
)
WEB_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
SYMBOL_ASCII_ONLY_RE = re.compile(r"[\W\dA-Za-z\s\./:;_\-—+|`$]+")

# 语义结构化块：检索里要当整体保留，不能按正文规则切碎或按短文本隔离。
STRUCTURED_BLOCK_TYPES = frozenset({"equation", "interline_equation", "inline_equation", "table"})
EQUATION_BLOCK_TYPES = frozenset({"equation", "interline_equation", "inline_equation"})

TEXT_FILE_SUFFIXES = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv"}
DOCX_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}

TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/-]+|[\u4e00-\u9fff]")
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|第[一二三四五六七八九十百千万\d]+[章节篇部分]\s*|"
    r"(?:\d+)(?:\.\d+){0,6}\s+|[A-Z][A-Z0-9_.-]{0,16}\s+)(.+?)\s*$"
)


def stable_id(prefix: str, *parts: Any, length: int = 14) -> str:
    raw = ":".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def compact_text(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def noise_like_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in NOISE_TEXT_MARKERS):
        return True
    compact = re.sub(r"\s+", "", text)
    return bool(compact.startswith("www.") and len(compact) <= 32)


def knowledge_interference_reasons(
    value: Any,
    *,
    context_type: str | None = None,
    block_type: str | None = None,
) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return ["empty_text"]
    reasons: list[str] = []
    if noise_like_text(text):
        reasons.append("noise_like_watermark")
    if PUBLISHER_METADATA_RE.search(text):
        reasons.append("publisher_metadata")
    if WEB_URL_RE.search(text):
        reasons.append("web_url_metadata")
    # 公式/表格块天生就是短的、满是 ASCII 符号的（`E = \frac{P D}{2 \delta}` 之类），
    # 按普通正文的短文本/纯符号规则判会被整条隔离掉，标准里的计算式一条都留不下。
    if str(block_type or "").strip().lower() in STRUCTURED_BLOCK_TYPES:
        return reasons
    chinese_count = len(CHINESE_CHAR_RE.findall(text))
    if len(text) < 8 or (len(text) < 24 and chinese_count < 8):
        reasons.append("low_value_short")
    if len(text) < 140 and SYMBOL_ASCII_ONLY_RE.fullmatch(text):
        reasons.append("symbol_ascii_only")
    if context_type == "business_rule_context" and (
        len(text) < 40 or (len(text) < 180 and SYMBOL_ASCII_ONLY_RE.fullmatch(text))
    ):
        reasons.append("business_rule_low_value")
    return reasons


def quarantine_interference_reasons(
    value: Any, *, context_type: str | None = None, block_type: str | None = None
) -> list[str]:
    reasons = knowledge_interference_reasons(value, context_type=context_type, block_type=block_type)
    return [
        reason
        for reason in reasons
        if reason in {"empty_text", "noise_like_watermark", "symbol_ascii_only", "business_rule_low_value"}
    ]


def metadata_interference_reasons(
    value: Any, *, context_type: str | None = None, block_type: str | None = None
) -> list[str]:
    reasons = knowledge_interference_reasons(value, context_type=context_type, block_type=block_type)
    if quarantine_interference_reasons(value, context_type=context_type, block_type=block_type):
        return []
    return [reason for reason in reasons if reason in {"publisher_metadata", "web_url_metadata"}]


def chunk_quality_fields(
    text: Any, *, context_type: str | None = None, block_type: str | None = None
) -> dict[str, Any]:
    metadata_reasons = metadata_interference_reasons(text, context_type=context_type, block_type=block_type)
    if not metadata_reasons:
        return {}
    return {
        "qualityFlags": metadata_reasons,
        "evidenceUsable": False,
        "evidenceStatusReason": "metadata_not_standard_clause",
        "retrievalWeightTier": "metadata",
    }


def chinese_ngrams(text: str) -> list[str]:
    if not text:
        return []
    grams = list(text)
    for size in (2, 3, 4):
        if len(text) >= size:
            grams.extend(text[index : index + size] for index in range(len(text) - size + 1))
    return grams


def offline_hash_tokens(text: str) -> list[str]:
    raw_tokens = [item.lower() for item in TOKEN_RE.findall(str(text or "")) if item.strip()]
    tokens: list[str] = []
    chinese_buffer: list[str] = []
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]", token):
            chinese_buffer.append(token)
            continue
        if chinese_buffer:
            tokens.extend(chinese_ngrams("".join(chinese_buffer)))
            chinese_buffer = []
        tokens.append(token)
    if chinese_buffer:
        tokens.extend(chinese_ngrams("".join(chinese_buffer)))
    return tokens


def offline_hash_embedding(text: str, *, dimensions: int = OFFLINE_VECTOR_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = offline_hash_tokens(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        bucket = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        weight = 1.0 + min(len(token), 12) / 12.0
        vector[bucket] += sign * weight
    norm = sum(value * value for value in vector) ** 0.5
    if norm <= 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def offline_hash_embeddings(texts: list[str]) -> list[dict[str, Any]]:
    return [{"index": index, "embedding": offline_hash_embedding(text)} for index, text in enumerate(texts)]


def active_embedding_target() -> dict[str, Any]:
    model_id = str(os.getenv("AICHECK_EMBEDDING_MODEL_ID") or QWEN3_EMBEDDING_MODEL).strip()
    if model_id == QWEN3_EMBEDDING_MODEL:
        return {
            "embeddingModel": QWEN3_EMBEDDING_MODEL,
            "indexVersion": QWEN3_INDEX_VERSION,
            "dimensions": OFFLINE_VECTOR_DIMENSIONS,
        }
    safe_model = re.sub(r"[^a-z0-9]+", "-", model_id.lower()).strip("-") or "custom"
    return {
        "embeddingModel": model_id,
        "indexVersion": f"knowledge-index-{safe_model}@{OFFLINE_VECTOR_DIMENSIONS}",
        "dimensions": OFFLINE_VECTOR_DIMENSIONS,
    }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right))


def detect_heading(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip()[:120] or None
    match = HEADING_RE.match(stripped)
    if match and len(stripped) <= 140:
        return stripped
    return None


def read_text_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    units: list[dict[str, Any]] = []
    section_path = [path.name]
    buffer: list[str] = []
    page_no = 1

    def flush() -> None:
        nonlocal buffer, page_no
        text_block = "\n".join(line for line in buffer if line.strip()).strip()
        if text_block:
            units.append(
                {
                    "pageNo": page_no,
                    "text": text_block,
                    "sectionPath": list(section_path),
                    "source": "text_file",
                    "sourceMethod": "deterministic_text_parse",
                    "ocrEngine": "python_text_reader",
                    "ocrConfidence": 1.0,
                }
            )
            page_no += 1
        buffer = []

    for line in text.splitlines():
        heading = detect_heading(line)
        if heading:
            flush()
            section_path = [path.name, heading]
        buffer.append(line)
        if sum(len(item) for item in buffer) >= MAX_CHUNK_CHARS:
            flush()
    flush()
    return units


def read_docx_file(path: Path) -> list[dict[str, Any]]:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(texts).strip()
        if text:
            paragraphs.append(text)
    units: list[dict[str, Any]] = []
    section_path = [path.name]
    buffer: list[str] = []
    page_no = 1

    def flush() -> None:
        nonlocal buffer, page_no
        text_block = "\n".join(buffer).strip()
        if text_block:
            units.append(
                {
                    "pageNo": page_no,
                    "text": text_block,
                    "sectionPath": list(section_path),
                    "source": "docx_text",
                    "sourceMethod": "deterministic_docx_parse",
                    "ocrEngine": "python_docx_xml",
                    "ocrConfidence": 1.0,
                }
            )
            page_no += 1
        buffer = []

    for paragraph in paragraphs:
        heading = detect_heading(paragraph)
        if heading:
            flush()
            section_path = [path.name, heading]
        buffer.append(paragraph)
        if sum(len(item) for item in buffer) >= MAX_CHUNK_CHARS:
            flush()
    flush()
    return units


def read_pdf_text_layer(path: Path) -> list[dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []

    units: list[dict[str, Any]] = []
    with fitz.open(str(path)) as document:
        for index, page in enumerate(document, start=1):
            blocks = page.get_text("blocks") or []
            block_units: list[dict[str, Any]] = []
            for block_index, block in enumerate(blocks, start=1):
                if len(block) < 5:
                    continue
                text = str(block[4] or "").strip()
                if not text or quarantine_interference_reasons(text):
                    continue
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                heading = next((detected for line in lines[:10] if (detected := detect_heading(line))), None)
                section_path = [path.name]
                if heading:
                    section_path.append(heading)
                block_units.append(
                    {
                        "pageNo": index,
                        "text": "\n".join(lines),
                        "bbox": [float(block[0]), float(block[1]), float(block[2]), float(block[3])],
                        "sectionPath": section_path,
                        "source": "pymupdf_text_layer",
                        "sourceMethod": "pymupdf_text_layer_block",
                        "ocrEngine": "pymupdf_text_layer",
                        "ocrConfidence": 1.0,
                        "sourceFragmentId": f"pdf-page-{index}-block-{block_index}",
                    }
                )
            units.extend(block_units)
    return units


def units_from_local_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in TEXT_FILE_SUFFIXES:
        return read_text_file(path)
    if suffix in DOCX_SUFFIXES:
        return read_docx_file(path)
    if suffix in PDF_SUFFIXES:
        return read_pdf_text_layer(path)
    return []


def local_path_from_storage_key(storage_key: str | None, workspace_root: Path) -> Path | None:
    raw = str(storage_key or "")
    if not raw.startswith("local://"):
        return None
    relative = raw.removeprefix("local://").lstrip("/")
    target = (workspace_root / relative).resolve()
    try:
        target.relative_to(workspace_root.resolve())
    except ValueError:
        return None
    return target if target.exists() else None


def units_from_fragments(file: dict[str, Any], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for fragment in fragments:
        text = str(fragment.get("text") or fragment.get("fieldValue") or "").strip()
        if not text or quarantine_interference_reasons(text, block_type=fragment.get("blockType")):
            continue
        page_no = int(fragment.get("pageNo") or 1)
        grouped[page_no].append(fragment)
    units: list[dict[str, Any]] = []
    file_name = str(file.get("fileName") or file.get("originalFileName") or file.get("id") or "标准文件")
    for page_no in sorted(grouped):
        page_fragments = grouped[page_no]
        page_fragments.sort(key=lambda item: (int(item.get("wordIndex") or item.get("lineIndex") or item.get("sequence") or 0), str(item.get("text") or "")))
        for fragment_index, fragment in enumerate(page_fragments, start=1):
            text = str(fragment.get("text") or fragment.get("fieldValue") or "").strip()
            if not text:
                continue
            confidence_raw = fragment.get("ocrConfidence") or fragment.get("confidence")
            try:
                confidence = float(confidence_raw) if str(confidence_raw or "").strip() else None
            except (TypeError, ValueError):
                confidence = None
            heading = detect_heading(text)
            section_path = [file_name, heading] if heading else [file_name, f"第 {page_no} 页"]
            source_method = fragment.get("sourceMethod") or "remote_ocr_fragments"
            fragment_id = fragment.get("id") or fragment.get("fragmentId") or f"p{page_no}-f{fragment_index}"
            units.append(
                {
                    "pageNo": page_no,
                    "text": text,
                    "bbox": fragment.get("bbox"),
                    "roi": {
                        "schemaVersion": "FdeRoi@1.0.0",
                        "pageNo": page_no,
                        "sourceMethod": source_method,
                        "boxes": [
                            {
                                "id": str(fragment_id),
                                "pageNo": page_no,
                                "bbox": fragment.get("bbox"),
                                "polygon": fragment.get("polygon") or fragment.get("bbox"),
                                "text": text,
                                "confidence": confidence,
                                "sourceFragmentId": fragment_id,
                                "sourceMethod": source_method,
                            }
                        ],
                        "qualityWarnings": [],
                    },
                    "sectionPath": section_path,
                    **structure_fields_for_unit(fragment),
                    "source": "ocr_fragments",
                    "sourceMethod": source_method,
                    "ocrEngine": fragment.get("ocrEngine") or fragment.get("sourceEngine") or "ocr_service",
                    "ocrConfidence": confidence,
                    "sourceFragmentId": fragment_id,
                }
            )
    return units


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    pieces: list[str] = []
    current = ""
    for part in re.split(r"(?<=[。；;.!?？])\s*|\n+", normalized):
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 1 > max_chars and current:
            pieces.append(current)
            current = part
        else:
            current = f"{current}\n{part}".strip() if current else part
    if current:
        pieces.append(current)
    if not pieces:
        pieces = [normalized[index : index + max_chars] for index in range(0, len(normalized), max_chars)]
    return pieces


def table_view_fields_from_html(html: str) -> dict[str, Any]:
    """HTML → 前端可画的结构化行。

    与 OCR 详情页的约定一致：接口不下发引擎 html（XSS 面），只给列名和行。
    `tableHtml` 仍然可以留在存储层做溯源，但渲染路径只认这里产出的字段。
    """
    from apps.ocr_service.engines import html_table_to_structure

    structure = html_table_to_structure(str(html or ""))
    normalized = [row for row in structure.get("normalizedRows") or [] if isinstance(row, dict)]
    cells = [cell for cell in structure.get("cells") or [] if isinstance(cell, dict)]
    if not normalized and not cells:
        return {}

    marked = any(cell.get("isHeader") is not None for cell in cells)
    header: list[tuple[int, str]] = []
    for cell in cells:
        is_header = cell.get("isHeader") if marked else int(cell.get("row") or 0) == 0
        if not is_header:
            continue
        text = str(cell.get("text") or "").strip()
        if text:
            header.append((int(cell.get("col") or 0), text))
    ordered = [text for _, text in sorted(header, key=lambda pair: pair[0])]
    if normalized:
        keys = set(normalized[0].keys())
        column_names = [name for name in ordered if name in keys]
        column_names.extend(name for name in normalized[0].keys() if name not in column_names)
    else:
        column_names = ordered

    column_count = int(structure.get("columns") or len(column_names) or 0)
    if all(cell.get("isHeader") is None for cell in cells):
        header_reliable = True
    elif column_count <= 0:
        header_reliable = False
    else:
        header_cols = {int(cell.get("col") or 0) for cell in cells if cell.get("isHeader")}
        header_reliable = len(header_cols) * 2 >= column_count

    return {
        "tableColumns": column_names,
        "tableRows": normalized,
        "tableHeaderReliable": header_reliable,
    }


def structure_fields_for_unit(unit: dict[str, Any]) -> dict[str, Any]:
    """把 MinerU 的块类型/LaTeX/表格结构原样带到分块上。

    只在确实有结构信息时写字段，避免给纯正文分块塞一堆 None——那会让
    「这条有没有结构」变得不可判断。

    表格：`tableHtml` 留在存储层做溯源；同时算出 `tableColumns` / `tableRows`
    给渲染与检索接口用——接口层不下发 html。
    """
    block_type = str(unit.get("blockType") or "").strip().lower()
    fields: dict[str, Any] = {}
    if block_type:
        fields["blockType"] = block_type
    latex = str(unit.get("latex") or "").strip()
    if latex:
        fields["latex"] = latex
    caption = str(unit.get("caption") or "").strip()
    if caption:
        fields["caption"] = caption

    existing_columns = unit.get("tableColumns")
    existing_rows = unit.get("tableRows")
    if isinstance(existing_columns, list) and isinstance(existing_rows, list) and existing_columns:
        fields["tableColumns"] = [str(item) for item in existing_columns]
        fields["tableRows"] = [dict(row) for row in existing_rows if isinstance(row, dict)]
        if "tableHeaderReliable" in unit:
            fields["tableHeaderReliable"] = bool(unit.get("tableHeaderReliable"))
    table_html = str(unit.get("tableHtml") or "").strip()
    if table_html:
        fields["tableHtml"] = table_html
        if "tableColumns" not in fields:
            fields.update(table_view_fields_from_html(table_html))
    return fields


def embedding_text_for_chunk(chunk: dict[str, Any]) -> str:
    """构造送去向量化的文本。

    公式块的 `text` 就是 LaTeX，直接嵌入等于让模型去理解一串反斜杠，检索基本
    命不中。这里补上所在条款路径与「公式」字样，让它落在语义空间的正确位置。
    """
    text = str(chunk.get("text") or "").strip()
    block_type = str(chunk.get("blockType") or "").strip().lower()
    if block_type not in STRUCTURED_BLOCK_TYPES:
        return text
    prefix_parts = [str(item).strip() for item in (chunk.get("sectionPath") or [])[-2:] if str(item or "").strip()]
    caption = str(chunk.get("caption") or "").strip()
    if caption:
        prefix_parts.append(caption)
    label = "公式" if block_type in EQUATION_BLOCK_TYPES else "表格"
    prefix = " / ".join(prefix_parts)
    return f"{prefix}\n{label}：{text}".strip() if prefix else f"{label}：{text}"


def build_chunks_for_file(file: dict[str, Any], units: list[dict[str, Any]], *, index_version: str = STANDARD_INDEX_VERSION) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    sequence = 1
    context_type = str(file.get("contextType") or "standard_reference")
    for unit in units:
        section_path = [str(item) for item in unit.get("sectionPath") or [] if str(item or "").strip()]
        structure = structure_fields_for_unit(unit)
        block_type = structure.get("blockType")
        unit_text = str(unit.get("text") or "")
        # 公式/表格必须整条留着：LaTeX 从中间切开再也渲染不回来；表格被句读
        # 规则拆开后行与列也对不齐了。
        pieces = [unit_text.strip()] if block_type in STRUCTURED_BLOCK_TYPES else chunk_text(unit_text)
        for piece in pieces:
            if quarantine_interference_reasons(piece, context_type=context_type, block_type=block_type):
                continue
            page_no = int(unit.get("pageNo") or 1)
            text = piece[:MAX_CHUNK_CHARS]
            chunks.append(
                {
                    
                        "id": f"CHK-{file['id']}-{sequence}",
                        "fileId": file["id"],
                        "documentId": file.get("documentId"),
                        "documentVersionId": file.get("documentVersionId"),
                        "sourceId": file.get("sourceId"),
                        "projectId": file.get("projectId"),
                        "materialCategory": file.get("materialCategory"),
                        "materialTypeCode": file.get("materialTypeCode"),
                        "materialTypeName": file.get("materialTypeName"),
                        "classificationStatus": file.get("classificationStatus"),
                        "classificationConfidence": file.get("classificationConfidence"),
                        "sourceRelativePath": file.get("sourceRelativePath"),
                        "chunkNo": sequence,
                        "text": text,
                        "pageNo": page_no,
                        "bbox": unit.get("bbox"),
                        "sectionPath": section_path or [str(file.get("fileName") or file["id"]), f"第 {page_no} 页"],
                        "tokenCount": max(1, len(piece) // 2),
                        "indexVersion": index_version,
                        "pageIndexNodeIds": [],
                        "sourceMethod": unit.get("sourceMethod") or unit.get("source") or "unknown",
                        "ocrEngine": unit.get("ocrEngine") or unit.get("source") or "unknown",
                        "ocrConfidence": unit.get("ocrConfidence"),
                        "contextType": context_type,
                        "createdAt": None
                    ,
                    **structure,
                    **chunk_quality_fields(text, context_type=context_type, block_type=block_type),
                }
            )
            sequence += 1
    return chunks


def page_index_node_for_chunk(file: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    node_id = stable_id("PIN-PAGE", file.get("sourceId"), file.get("sourceRelativePath"), chunk.get("pageNo"), chunk.get("chunkNo"))
    context_type = str(chunk.get("contextType") or file.get("contextType") or "")
    source_method = str(chunk.get("sourceMethod") or "")
    if context_type == "business_rule_context":
        node_type = "business_rule_context_page"
    elif context_type == "visual_extracted_reference":
        node_type = "visual_extracted_reference_page"
    else:
        node_type = "standard_page"
    return {
        "id": node_id,
        "pageIndexNodeId": node_id,
        "kbDocId": file.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": file.get("kbVersion") or file.get("sourceVersion") or "inspection_kb@1.0.0",
        "nodeId": f"{file.get('id')}:{chunk.get('pageNo')}:{chunk.get('chunkNo')}",
        "parentNodeId": None,
        "title": " / ".join(str(item) for item in (chunk.get("sectionPath") or [])[-2:]) or str(file.get("fileName") or chunk.get("id")),
        "summary": compact_text(chunk.get("text"), 220),
        "startPage": chunk.get("pageNo"),
        "endPage": chunk.get("pageNo"),
        "sectionPath": chunk.get("sectionPath") or [],
        "children": [],
        "linkedClauseIds": [chunk.get("id")],
        "qualityFlags": chunk.get("qualityFlags") or [],
        "evidenceUsable": chunk.get("evidenceUsable", True),
        "evidenceStatusReason": chunk.get("evidenceStatusReason"),
        "retrievalWeightTier": chunk.get("retrievalWeightTier") or "default",
        "businessPackId": file.get("businessPackId"),
        "nodeTypes": [node_type],
        "materialTypes": [context_type or "standard_reference"],
        "tags": [
            "业务规则上下文" if context_type == "business_rule_context" else "视觉提取" if context_type == "visual_extracted_reference" else "标准规范",
            "PageIndex",
            str(file.get("fileName") or ""),
            source_method,
        ],
        "status": "effective",
        "sourceRelativePath": file.get("sourceRelativePath"),
        "indexVersion": PAGE_INDEX_VERSION,
    }


def build_page_index_nodes_for_source(source: dict[str, Any], files: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_id = str(source.get("id") or "KS-STANDARD-RULES")
    source_version = str(source.get("version") or "inspection_kb@1.0.0")
    root_id = stable_id("PIN-ROOT", source_id, source_version)
    nodes: list[dict[str, Any]] = [
        {
            "id": root_id,
            "pageIndexNodeId": root_id,
            "kbDocId": source_id,
            "kbVersion": source_version,
            "nodeId": "root",
            "parentNodeId": None,
            "title": source.get("name") or "标准规范库",
            "summary": f"由 rules 导入的 {len(files)} 个标准和业务规则上下文文件。",
            "startPage": 1,
            "endPage": max([int(item.get("pageNo") or 1) for item in chunks] or [1]),
            "sectionPath": [str(source.get("name") or source_id)],
            "children": [],
            "linkedClauseIds": [],
            "businessPackId": "engineering_inspection_v1",
            "nodeTypes": ["standard_library_root"],
            "materialTypes": ["standard_reference", "business_rule_context"],
            "tags": ["rules", "rules/standards", "PageIndex"],
            "status": "effective",
            "indexVersion": PAGE_INDEX_VERSION,
        }
    ]
    chunks_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_file[str(chunk.get("fileId") or "")].append(chunk)
    for file in sorted(files, key=lambda item: str(item.get("sourceRelativePath") or item.get("fileName") or "")):
        file_chunks = sorted(chunks_by_file.get(str(file.get("id")), []), key=lambda item: int(item.get("chunkNo") or 0))
        if not file_chunks:
            continue
        file_node_id = stable_id("PIN-FILE", source_id, file.get("sourceRelativePath") or file.get("id"))
        page_node_ids: list[str] = []
        linked_ids: list[str] = []
        for chunk in file_chunks:
            page_node = page_index_node_for_chunk(file, chunk)
            page_node["parentNodeId"] = file_node_id
            page_node["kbVersion"] = source_version
            page_node_ids.append(page_node["pageIndexNodeId"])
            linked_ids.extend(str(item) for item in page_node.get("linkedClauseIds") or [] if item)
            nodes.append(page_node)
            chunk["pageIndexNodeIds"] = [page_node["pageIndexNodeId"]]
        context_type = str(file.get("contextType") or "")
        nodes.append(
            {
                "id": file_node_id,
                "pageIndexNodeId": file_node_id,
                "kbDocId": source_id,
                "kbVersion": source_version,
                "nodeId": str(file.get("id")),
                "parentNodeId": root_id,
                "title": file.get("fileName") or file.get("originalFileName") or str(file.get("id")),
                "summary": compact_text(" ".join(str(item.get("text") or "") for item in file_chunks[:2]), 260),
                "startPage": min(int(item.get("pageNo") or 1) for item in file_chunks),
                "endPage": max(int(item.get("pageNo") or 1) for item in file_chunks),
                "sectionPath": [str(source.get("name") or source_id), str(file.get("fileName") or file.get("id"))],
                "children": page_node_ids,
                "linkedClauseIds": linked_ids[:200],
                "businessPackId": file.get("businessPackId") or "engineering_inspection_v1",
                "nodeTypes": ["business_rule_context_file" if context_type == "business_rule_context" else "standard_file"],
                "materialTypes": [context_type or "standard_reference"],
                "tags": ["业务规则上下文" if context_type == "business_rule_context" else "标准规范", str(file.get("sourceRelativePath") or ""), str(file.get("fileName") or "")],
                "status": "effective",
                "sourceRelativePath": file.get("sourceRelativePath"),
                "indexVersion": PAGE_INDEX_VERSION,
            }
        )
        nodes[0]["children"].append(file_node_id)
        nodes[0]["linkedClauseIds"].extend(linked_ids[:200])
    return nodes


def clause_from_chunk(file: dict[str, Any], chunk: dict[str, Any], source_version: str) -> dict[str, Any]:
    context_type = str(chunk.get("contextType") or file.get("contextType") or "")
    source_method = str(chunk.get("sourceMethod") or "")
    structure = structure_fields_for_unit(chunk)
    block_type = str(structure.get("blockType") or "").strip().lower()
    return {
        **structure,
        "id": f"KC-{chunk['id']}",
        "clauseId": chunk["id"],
        "kbDocId": file.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": source_version,
        "clauseNo": f"p{chunk.get('pageNo')}-c{chunk.get('chunkNo')}",
        "title": " / ".join(str(item) for item in (chunk.get("sectionPath") or [])[-2:]) or str(file.get("fileName") or chunk["id"]),
        "text": chunk.get("text") or "",
        "pageNo": chunk.get("pageNo"),
        "bbox": chunk.get("bbox"),
        "roi": chunk.get("roi"),
        "qualityFlags": chunk.get("qualityFlags") or [],
        "evidenceUsable": chunk.get("evidenceUsable", True),
        "evidenceStatusReason": chunk.get("evidenceStatusReason"),
        "retrievalWeightTier": chunk.get("retrievalWeightTier") or "default",
        "sectionPath": chunk.get("sectionPath") or [],
        "scope": {
            "sourceId": file.get("sourceId"),
            "fileId": file.get("id"),
            "contextType": context_type or "standard_reference",
            "sourceMethod": source_method,
            "ocrEngine": chunk.get("ocrEngine"),
            "ocrConfidence": chunk.get("ocrConfidence"),
        },
        "tags": [
            "business_rule_context"
            if context_type == "business_rule_context"
            else "visual_extracted_reference"
            if context_type == "visual_extracted_reference"
            else "standard_chunk",
            file.get("fileName"),
            file.get("sourceRelativePath"),
            source_method,
            *(
                [f"block_type:{block_type}"]
                if block_type in STRUCTURED_BLOCK_TYPES
                else []
            ),
        ],
        "status": "effective",
        "documentVersionId": file.get("documentVersionId"),
        "fileId": file.get("id"),
        "chunkId": chunk.get("id"),
        "pageIndexNodeIds": chunk.get("pageIndexNodeIds") or [],
    }


def build_vector_rows(
    file: dict[str, Any],
    chunks: list[dict[str, Any]],
    vectors: list[dict[str, Any]],
    *,
    embedding_model: str,
    index_version: str = STANDARD_INDEX_VERSION,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    vectors_by_index = {int(item.get("index") or index): item for index, item in enumerate(vectors)}
    expected_dimensions = None
    for index, chunk in enumerate(chunks):
        chunk_context_type = str(chunk.get("contextType") or file.get("contextType") or "standard_reference")
        source_method = str(chunk.get("sourceMethod") or "")
        vector = vectors_by_index.get(index) or {}
        embedding = vector.get("embedding") if isinstance(vector, dict) else None
        if not isinstance(embedding, list) or not embedding:
            continue
        if expected_dimensions is None:
            expected_dimensions = len(embedding)
        if len(embedding) != expected_dimensions:
            continue
        rows.append(
            {
                "id": f"KV-{chunk['id']}",
                "fileId": file["id"],
                "chunkId": chunk["id"],
                "documentId": file.get("documentId"),
                "documentVersionId": file.get("documentVersionId"),
                "projectId": file.get("projectId"),
                "sourceId": file.get("sourceId"),
                "sourceRelativePath": file.get("sourceRelativePath"),
                "vectorNo": index + 1,
                "embedding": embedding,
                "dimensions": len(embedding),
                "embeddingModel": embedding_model,
                "indexVersion": index_version,
                "pageNo": chunk.get("pageNo"),
                "bbox": chunk.get("bbox"),
                "roi": chunk.get("roi"),
                "sectionPath": chunk.get("sectionPath") or [],
                "pageIndexNodeIds": chunk.get("pageIndexNodeIds") or [],
                "qualityFlags": chunk.get("qualityFlags") or [],
                "evidenceUsable": chunk.get("evidenceUsable", True),
                "evidenceStatusReason": chunk.get("evidenceStatusReason"),
                "retrievalWeightTier": chunk.get("retrievalWeightTier") or "default",
                "textHash": hashlib.sha256(str(chunk.get("text") or "").encode("utf-8")).hexdigest(),
                "payload": {
                    "text": chunk.get("text"),
                    "fileName": file.get("fileName"),
                    "projectId": chunk.get("projectId") or file.get("projectId"),
                    "materialCategory": chunk.get("materialCategory") or file.get("materialCategory"),
                    "materialTypeCode": chunk.get("materialTypeCode") or file.get("materialTypeCode"),
                    "materialTypeName": chunk.get("materialTypeName") or file.get("materialTypeName"),
                    "classificationStatus": chunk.get("classificationStatus") or file.get("classificationStatus"),
                    "classificationConfidence": (
                        chunk.get("classificationConfidence")
                        if chunk.get("classificationConfidence") is not None
                        else file.get("classificationConfidence")
                    ),
                    "sourceRelativePath": file.get("sourceRelativePath"),
                    "contextType": chunk_context_type,
                    "sourceMethod": source_method,
                    "ocrEngine": chunk.get("ocrEngine"),
                    "ocrConfidence": chunk.get("ocrConfidence"),
                    "needsHumanVerification": chunk.get("needsHumanVerification"),
                    "qualityFlags": chunk.get("qualityFlags") or [],
                    "evidenceUsable": chunk.get("evidenceUsable", True),
                    "evidenceStatusReason": chunk.get("evidenceStatusReason"),
                    "retrievalWeightTier": chunk.get("retrievalWeightTier") or "default",
                    "pageNo": chunk.get("pageNo"),
                    "bbox": chunk.get("bbox"),
                    "roi": chunk.get("roi"),
                    "sectionPath": chunk.get("sectionPath") or [],
                    "pageIndexNodeIds": chunk.get("pageIndexNodeIds") or [],
                },
            }
        )
    return rows


def vector_payload_for_pg(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "file_id": row.get("fileId"),
        "chunk_id": row.get("chunkId"),
        "document_id": row.get("documentId"),
        "document_version_id": row.get("documentVersionId"),
        "source_id": row.get("sourceId"),
        "embedding": row.get("embedding"),
        "dimensions": row.get("dimensions"),
        "embedding_model": row.get("embeddingModel"),
        "index_version": row.get("indexVersion"),
        "metadata": json.dumps({key: value for key, value in row.items() if key != "embedding"}, ensure_ascii=False),
    }


# --------------------------------------------------------------------------
# 哪些知识文件不许走通用重建管线
# --------------------------------------------------------------------------

#: 分块由专用摄取路径生成、通用切片器重建不出来的来源类型。
DEDICATED_INGESTION_SOURCE_TYPES = frozenset({"standard"})


def reject_if_dedicated_ingestion(file: dict[str, Any]) -> None:
    """标准条款库不许走通用重建管线（dispatch_knowledge_file_index_pipeline）。

    那条管线会先清掉派生索引、再用**通用切片器**重建。项目资料没问题
    （OCR 正文按长度切），标准库不行：它的分块由专用摄取路径生成、与条款
    一一对齐。

    0819 拿它给标准库换向量模型，结果 31 份标准的分块直接归零，另 29 份被切成
    完全不同的粒度（13594 个碎块），靠迁移前的备份才救回来。

    最难受的是**它不报错**：切片任务返回 succeeded，只是 chunkCount 为 0。
    所以这道拦截必须在入口，而且要在清空之前——先清后拒等于照样丢了分块。

    正确做法：
    - 只换向量模型用 dispatch_embed（保留分块）
    - 只把 JSONB 向量回填到 pgvector 用 scripts/backfill_knowledge_pgvector.py
    - 要重建分块走 scripts/reocr_standards_with_mineru.py（见
      docs/标准规范MinerU重识别与语义结构化方案.md）
    """
    source_type = str(file.get("sourceType") or "")
    if source_type in DEDICATED_INGESTION_SOURCE_TYPES:
        raise ValueError(
            "standard_library_uses_dedicated_ingestion: "
            f"{source_type} 类知识文件的分块由专用摄取路径生成，通用切片器重建不出来。"
            "只换向量模型请用 dispatch_embed（保留分块），"
            "只回填 pgvector 请走 scripts/backfill_knowledge_pgvector.py，"
            "要重建分块请走 scripts/reocr_standards_with_mineru.py。"
        )
