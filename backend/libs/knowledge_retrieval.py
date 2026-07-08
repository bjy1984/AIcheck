from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time
from libs.knowledge_indexing import metadata_interference_reasons, noise_like_text, quarantine_interference_reasons


BACKEND_ROOT = Path(__file__).resolve().parents[1]
STANDARD_ALIAS_REGISTRY_PATH = BACKEND_ROOT / "config" / "standard_alias_registry.json"
TOKEN_RE = re.compile(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]{1,4}")
EXACT_CLAUSE_RE = re.compile(r"(?<![A-Za-z0-9_.:-])([A-Z]{2,}[-_][A-Z0-9_.:-]*\d[A-Z0-9_.:-]*|\d+(?:\.\d+){1,5})(?:\s*条)?", re.IGNORECASE)
STANDARD_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:GB|GB/T|GBT|NB/T|NB_T|NBT|JB/T|SY/T|TSG)\s*[A-Z0-9_.／/ -]*\d(?:[.-]\d+)*(?:[-—]\d{4})?",
    re.IGNORECASE,
)
STANDARD_REF_RE = re.compile(
    r"(?<![A-Z0-9])(?P<prefix>GB/T|GBT|GB|NB/T|NB_T|NBT|JB/T|JBT|SY/T|SYT|TSG)\s*(?P<number>[A-Z]*\d+(?:\.\d+)*)\s*(?:[-—](?P<year>(?:19|20)\d{2}))?",
    re.IGNORECASE,
)
OCR_STANDARD_CHAR_MAP = str.maketrans(
    {
        "犌": "G",
        "犅": "B",
        "犜": "T",
        "犖": "N",
        "犑": "J",
        "犛": "S",
        "犢": "Y",
    }
)
BUILTIN_STANDARD_ALIAS_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "gbt-3087-low-medium-boiler-tubes",
        "source": "builtin_fallback",
        "phrases": ("低中压锅炉用无缝钢管", "低中压锅炉管", "低中压锅炉钢管"),
        "prefix": "GBT",
        "number": "3087",
        "year": "2022",
        "boost": 120.0,
    },
    {
        "id": "gbt-3087-boiler-tube-acceptance",
        "source": "builtin_fallback",
        "phrases": ("锅炉管质量证明书", "锅炉管验收依据", "锅炉管验收", "锅炉管质量证明"),
        "exclude": ("高压",),
        "prefix": "GBT",
        "number": "3087",
        "year": "2022",
        "boost": 92.0,
    },
    {
        "id": "gbt-5310-high-pressure-boiler-tubes",
        "source": "builtin_fallback",
        "phrases": ("高压锅炉用无缝钢管", "高压锅炉用钢管", "高压锅炉管", "高压锅炉钢管"),
        "prefix": "GBT",
        "number": "5310",
        "year": "2023",
        "boost": 120.0,
    },
    {
        "id": "gbt-8110-solid-welding-wire",
        "source": "builtin_fallback",
        "phrases": ("气体保护电弧焊实心焊丝", "熔化极气体保护电弧焊", "熔化极气体保护焊丝", "实心焊丝"),
        "prefix": "GBT",
        "number": "8110",
        "year": "2020",
        "boost": 110.0,
    },
    {
        "id": "tsg31-pressure-piping-component-license",
        "source": "builtin_fallback",
        "phrases": ("压力管道元件型式试验", "压力管道元件许可", "型式试验"),
        "requireAny": ("压力管道", "管道元件", "许可"),
        "prefix": "TSG",
        "number": "31",
        "year": "2025",
        "boost": 115.0,
    },
    {
        "id": "nbt-47013-3-ut",
        "source": "builtin_fallback",
        "phrases": ("超声检测报告", "超声检测验收", "超声检测依据"),
        "exclude": ("衍射时差", "TOFD", "相控阵"),
        "prefix": "NBT",
        "number": "47013.3",
        "year": "2023",
        "boost": 105.0,
    },
)
PAGEINDEX_QUERY_TERMS = (
    "附录",
    "跨章节",
    "跨章",
    "多章节",
    "长文档",
    "长手册",
    "章节",
    "正文",
    "引用",
    "条文之间",
)


def query_tokens(query: str) -> list[str]:
    tokens = [item.lower() for item in TOKEN_RE.findall(query or "") if item.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped


def normalize_clause_ref(value: Any) -> str:
    return str(value or "").strip().replace("第", "").replace("条", "").lower()


def canonical_standard_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(OCR_STANDARD_CHAR_MAP).upper()
    replacements = {
        "∕": "/",
        "／": "/",
        "\\": "/",
        "_": "/",
        "+": " ",
        "—": "-",
        "–": "-",
        "－": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text)


def normalized_business_phrase(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(OCR_STANDARD_CHAR_MAP)
    return re.sub(r"[\s,，。；;:：/／∕_+\-—–－·、()（）《》<>\"'“”‘’]+", "", text).lower()


def normalize_standard_prefix(value: str) -> str:
    prefix = value.upper().replace("_", "/")
    if prefix in {"GB/T", "GBT"}:
        return "GBT"
    if prefix in {"NB/T", "NBT"}:
        return "NBT"
    if prefix in {"JB/T", "JBT"}:
        return "JBT"
    if prefix in {"SY/T", "SYT"}:
        return "SYT"
    return prefix


def display_standard_number(prefix: str, number: str, year: str = "") -> str:
    display_prefix = {
        "GBT": "GB/T",
        "NBT": "NB/T",
        "JBT": "JB/T",
        "SYT": "SY/T",
    }.get(prefix, prefix)
    suffix = f"-{year}" if year else ""
    return f"{display_prefix} {number}{suffix}".strip()


def normalize_alias_rule(raw_rule: dict[str, Any]) -> dict[str, Any] | None:
    target = raw_rule.get("target") if isinstance(raw_rule.get("target"), dict) else raw_rule
    prefix = normalize_standard_prefix(str(target.get("prefix") or raw_rule.get("prefix") or ""))
    number = str(target.get("number") or raw_rule.get("number") or "").upper().strip()
    year = str(target.get("year") or raw_rule.get("year") or "").strip()
    phrases = tuple(str(item) for item in raw_rule.get("phrases") or [] if str(item).strip())
    if not prefix or not number or not phrases:
        return None
    return {
        "id": str(raw_rule.get("id") or f"{prefix}-{number}-{year}").strip(),
        "source": str(raw_rule.get("source") or "manual").strip(),
        "phrases": phrases,
        "exclude": tuple(str(item) for item in raw_rule.get("exclude") or [] if str(item).strip()),
        "requireAny": tuple(str(item) for item in raw_rule.get("requireAny") or [] if str(item).strip()),
        "prefix": prefix,
        "number": number,
        "year": year,
        "boost": float(raw_rule.get("boost") or 90.0),
    }


def standard_alias_registry_cache_key() -> int:
    try:
        return STANDARD_ALIAS_REGISTRY_PATH.stat().st_mtime_ns
    except OSError:
        return 0


@lru_cache(maxsize=8)
def load_standard_alias_rules(_cache_key: int) -> tuple[dict[str, Any], ...]:
    rules: list[dict[str, Any]] = []
    if STANDARD_ALIAS_REGISTRY_PATH.exists():
        try:
            payload = json.loads(STANDARD_ALIAS_REGISTRY_PATH.read_text(encoding="utf-8"))
            for raw_rule in payload.get("rules") or []:
                if isinstance(raw_rule, dict):
                    normalized = normalize_alias_rule(raw_rule)
                    if normalized:
                        rules.append(normalized)
        except (OSError, ValueError, TypeError):
            rules = []
    if not rules:
        rules = [rule for rule in (normalize_alias_rule(item) for item in BUILTIN_STANDARD_ALIAS_RULES) if rule]
    return tuple(rules)


def standard_alias_rules() -> tuple[dict[str, Any], ...]:
    return load_standard_alias_rules(standard_alias_registry_cache_key())


def standard_refs_from_text(value: Any) -> list[dict[str, str]]:
    text = canonical_standard_text(value)
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for match in STANDARD_REF_RE.finditer(text):
        prefix = normalize_standard_prefix(match.group("prefix"))
        number = str(match.group("number") or "").upper()
        year = str(match.group("year") or "")
        key = (prefix, number, year)
        if not number or key in seen:
            continue
        seen.add(key)
        refs.append({"prefix": prefix, "number": number, "base": number.split(".", 1)[0], "year": year})
    return refs


def standard_alias_matches(query: str) -> list[dict[str, Any]]:
    normalized_query = normalized_business_phrase(query)
    matches: list[dict[str, Any]] = []
    for rule in standard_alias_rules():
        excluded = [normalized_business_phrase(item) for item in rule.get("exclude") or []]
        if any(item and item in normalized_query for item in excluded):
            continue
        required = [normalized_business_phrase(item) for item in rule.get("requireAny") or []]
        if required and not any(item and item in normalized_query for item in required):
            continue
        phrase = next(
            (
                str(item)
                for item in rule.get("phrases") or []
                if normalized_business_phrase(item) and normalized_business_phrase(item) in normalized_query
            ),
            "",
        )
        if not phrase:
            continue
        matches.append(
            {
                "aliasId": str(rule.get("id") or ""),
                "source": str(rule.get("source") or ""),
                "phrase": phrase,
                "prefix": str(rule["prefix"]),
                "number": str(rule["number"]),
                "year": str(rule["year"]),
                "targetStandard": display_standard_number(str(rule["prefix"]), str(rule["number"]), str(rule["year"])),
                "boost": float(rule.get("boost") or 0.0),
            }
        )
    return matches


def standard_identifier_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in [
            candidate.get("sourceRelativePath"),
            candidate.get("title"),
            candidate.get("clauseId"),
            candidate.get("clauseNo"),
            " ".join(str(item or "") for item in candidate.get("tags") or []),
        ]
    )


def standard_number_match_score(candidate: dict[str, Any], query: str) -> float:
    query_refs = standard_refs_from_text(query)
    if not query_refs:
        return 0.0
    source_refs = standard_refs_from_text(standard_identifier_text(candidate))
    if not source_refs:
        return 0.0
    best = 0.0
    for query_ref in query_refs:
        for source_ref in source_refs:
            if query_ref["prefix"] != source_ref["prefix"]:
                continue
            if query_ref["number"] == source_ref["number"]:
                if query_ref["year"] and source_ref["year"]:
                    best = max(best, 90.0 if query_ref["year"] == source_ref["year"] else 15.0)
                else:
                    best = max(best, 70.0)
            elif query_ref["base"] == source_ref["base"] and query_ref["year"] and query_ref["year"] == source_ref["year"]:
                # A query for NB/T 47013-2015 should prefer the whole-volume file over split parts
                # such as NB/T 47013.6-2015, but the shared base still makes it a weak candidate.
                best = max(best, 12.0)
    return best


def standard_alias_candidate_matches(
    candidate: dict[str, Any],
    query: str,
    *,
    query_matches: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    matches = query_matches if query_matches is not None else standard_alias_matches(query)
    if not matches:
        return []
    source_refs = standard_refs_from_text(standard_identifier_text(candidate))
    if not source_refs:
        return []
    candidate_matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for match in matches:
        for source_ref in source_refs:
            if match["prefix"] != source_ref["prefix"]:
                continue
            if match["number"] != source_ref["number"]:
                continue
            if match["year"] and source_ref["year"] and match["year"] != source_ref["year"]:
                continue
            key = (str(match.get("aliasId") or ""), match["prefix"], match["number"], str(match.get("year") or ""))
            if key in seen:
                continue
            seen.add(key)
            candidate_matches.append(
                {
                    "aliasId": match.get("aliasId"),
                    "phrase": match.get("phrase"),
                    "source": match.get("source"),
                    "targetStandard": match.get("targetStandard"),
                    "prefix": match.get("prefix"),
                    "number": match.get("number"),
                    "year": match.get("year"),
                    "boost": float(match.get("boost") or 0.0),
                }
            )
    return candidate_matches


def standard_alias_match_score(candidate: dict[str, Any], query: str) -> float:
    matches = standard_alias_candidate_matches(candidate, query)
    return max((float(match.get("boost") or 0.0) for match in matches), default=0.0)


def chinese_ngrams(text: str) -> set[str]:
    compact = "".join(re.findall(r"[\u4e00-\u9fff]+", text or ""))
    grams: set[str] = set()
    for width in (2, 3, 4):
        for index in range(0, max(0, len(compact) - width + 1)):
            grams.add(compact[index : index + width])
    return grams


def source_title_overlap_score(candidate: dict[str, Any], query: str) -> float:
    query_grams = chinese_ngrams(query)
    if not query_grams:
        return 0.0
    source_text = " ".join(
        str(part or "")
        for part in [
            candidate.get("sourceRelativePath"),
            candidate.get("title"),
            " ".join(str(item or "") for item in candidate.get("tags") or []),
        ]
    )
    source_grams = chinese_ngrams(source_text)
    overlap = query_grams.intersection(source_grams)
    meaningful = {gram for gram in overlap if gram not in {"标准", "依据", "引用", "验收", "相关", "要求", "如何", "什么"}}
    if len(meaningful) < 3:
        return 0.0
    return min(45.0, len(meaningful) * 2.2)


def detect_exact_clause_refs(query: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    standard_spans = []
    for standard_match in STANDARD_NUMBER_RE.finditer(query or ""):
        value = standard_match.group(0)
        if re.search(r"[-_][A-Z]\d+(?:\.\d+)+", value, re.IGNORECASE):
            continue
        standard_spans.append(standard_match.span())
    for match in EXACT_CLAUSE_RE.finditer(query or ""):
        if any(match.start() >= start and match.end() <= end for start, end in standard_spans):
            continue
        ref = normalize_clause_ref(match.group(1))
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def build_router_signals(query: str, tokens: list[str]) -> dict[str, Any]:
    exact_refs = detect_exact_clause_refs(query)
    standard_numbers = [
        match.group(0).strip()
        for match in STANDARD_NUMBER_RE.finditer(query or "")
        if not re.search(r"[-_][A-Z]\d+(?:\.\d+)+", match.group(0), re.IGNORECASE)
    ]
    needs_pageindex = any(term in (query or "") for term in PAGEINDEX_QUERY_TERMS) or len(query or "") >= 80
    return {
        "exactClauseRefs": exact_refs,
        "standardNumbers": standard_numbers,
        "standardAliases": standard_alias_matches(query),
        "needsPageIndex": needs_pageindex,
        "tokenCount": len(tokens),
        "queryLength": len(query or ""),
    }


def classify_retrieval_route(query: str, tokens: list[str]) -> str:
    signals = build_router_signals(query, tokens)
    if signals["exactClauseRefs"]:
        return "exact_clause_lookup"
    if signals["needsPageIndex"]:
        return "pageindex_tree_search"
    return "hybrid_review_basis_search"


def source_version_by_id(state: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("version") or "kb@draft")
        for item in state.get("knowledge_sources", [])
        if isinstance(item, dict) and item.get("id")
    }


def normalize_clause(candidate: dict[str, Any], *, default_version: str = "inspection_kb@1.0.0") -> dict[str, Any]:
    clause_id = str(candidate.get("clauseId") or candidate.get("id") or candidate.get("objectId") or f"clause-{uuid4().hex[:8]}")
    text = str(candidate.get("text") or candidate.get("quotedText") or candidate.get("description") or "")
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    context_type = candidate.get("contextType") or metadata.get("contextType")
    source_method = candidate.get("sourceMethod") or metadata.get("sourceMethod")
    ocr_confidence = candidate.get("ocrConfidence") if candidate.get("ocrConfidence") is not None else metadata.get("ocrConfidence")
    scope = dict(candidate.get("scope") or {})
    if context_type and not scope.get("contextType"):
        scope["contextType"] = context_type
    if source_method and not scope.get("sourceMethod"):
        scope["sourceMethod"] = source_method
    quality_flags = list(candidate.get("qualityFlags") or metadata.get("qualityFlags") or [])
    if noise_like_text(text) and "noise_like_watermark" not in quality_flags:
        quality_flags.append("noise_like_watermark")
    for reason in metadata_interference_reasons(text, context_type=str(context_type or "")):
        if reason not in quality_flags:
            quality_flags.append(reason)
    evidence_usable = candidate.get("evidenceUsable")
    if evidence_usable is None:
        evidence_usable = metadata.get("evidenceUsable")
    if evidence_usable is None:
        evidence_usable = "publisher_metadata" not in quality_flags and "web_url_metadata" not in quality_flags
    return {
        "id": str(candidate.get("id") or clause_id),
        "clauseId": clause_id,
        "kbDocId": candidate.get("kbDocId") or candidate.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": candidate.get("kbVersion") or candidate.get("version") or default_version,
        "clauseNo": candidate.get("clauseNo") or clause_id.split("-")[-1],
        "title": candidate.get("title") or candidate.get("name") or clause_id,
        "text": text,
        "pageNo": candidate.get("pageNo"),
        "bbox": candidate.get("bbox"),
        "sectionPath": candidate.get("sectionPath") or [],
        "scope": scope,
        "tags": candidate.get("tags") or [],
        "status": candidate.get("status") or "effective",
        "sourceEvidenceLinkId": candidate.get("sourceEvidenceLinkId"),
        "documentVersionId": candidate.get("documentVersionId"),
        "fileId": candidate.get("fileId"),
        "sourceRelativePath": candidate.get("sourceRelativePath"),
        "pageIndexNodeIds": candidate.get("pageIndexNodeIds") or [],
        "contextType": context_type,
        "sourceMethod": source_method,
        "ocrConfidence": ocr_confidence,
        "qualityFlags": quality_flags,
        "evidenceUsable": bool(evidence_usable),
        "evidenceStatusReason": candidate.get("evidenceStatusReason") or metadata.get("evidenceStatusReason"),
        "retrievalWeightTier": candidate.get("retrievalWeightTier") or metadata.get("retrievalWeightTier") or "default",
    }


def knowledge_clause_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    source_versions = source_version_by_id(state)
    default_version = kb_version or next(iter(source_versions.values()), "inspection_kb@1.0.0")
    candidates: list[dict[str, Any]] = []
    files_by_id = {
        item.get("id"): item
        for item in state.get("knowledge_files", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    sources_by_id = {
        item.get("id"): item
        for item in state.get("knowledge_sources", []) or []
        if isinstance(item, dict) and item.get("id")
    }

    for clause in state.get("knowledge_clauses", []) or []:
        if isinstance(clause, dict):
            file = files_by_id.get(clause.get("fileId")) or {}
            context_type = clause.get("contextType") or file.get("contextType")
            if quarantine_interference_reasons(clause.get("text") or clause.get("quotedText") or "", context_type=str(context_type or "")):
                continue
            enriched_clause = {
                **clause,
                "sourceRelativePath": clause.get("sourceRelativePath") or file.get("sourceRelativePath"),
                "contextType": context_type,
                "sourceMethod": clause.get("sourceMethod") or file.get("sourceMethod"),
            }
            candidates.append(normalize_clause(enriched_clause, default_version=default_version))

    for link in state.get("evidence_links", []) or []:
        if not isinstance(link, dict) or link.get("objectType") != "knowledgeClause":
            continue
        candidates.append(
            normalize_clause(
                {
                    "id": f"KC-{link.get('objectId') or link.get('id')}",
                    "clauseId": link.get("objectId") or link.get("id"),
                    "kbDocId": link.get("kbDocId") or "KS-STANDARD-RULES",
                    "kbVersion": link.get("kbVersion") or source_versions.get("KS-STANDARD-RULES") or default_version,
                    "title": link.get("title") or link.get("objectId") or "知识条款",
                    "text": link.get("quotedText"),
                    "pageNo": link.get("pageNo"),
                    "bbox": link.get("bbox"),
                    "sourceEvidenceLinkId": link.get("id"),
                    "tags": [link.get("fieldName")] if link.get("fieldName") else [],
                },
                default_version=default_version,
            )
        )

    for chunk in state.get("knowledge_chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        context_type = chunk.get("contextType") or (files_by_id.get(chunk.get("fileId")) or {}).get("contextType")
        if quarantine_interference_reasons(chunk.get("text"), context_type=str(context_type or "")):
            continue
        file = files_by_id.get(chunk.get("fileId")) or {}
        source = sources_by_id.get(file.get("sourceId")) or {}
        if file.get("indexEnabled") is False or source.get("sourceType") == "rule":
            continue
        source_id = file.get("sourceId") or "KS-PROJECT-FILE"
        source_method = chunk.get("sourceMethod") or file.get("sourceMethod")
        candidates.append(
            normalize_clause(
                {
                    "id": f"KC-{chunk.get('id')}",
                    "clauseId": chunk.get("id"),
                    "kbDocId": source_id,
                    "kbVersion": source_versions.get(str(source_id)) or default_version,
                    "title": file.get("fileName") or chunk.get("id"),
                    "text": chunk.get("text"),
                    "pageNo": chunk.get("pageNo"),
                    "bbox": chunk.get("bbox"),
                    "fileId": chunk.get("fileId"),
                    "documentVersionId": chunk.get("documentVersionId"),
                    "sourceRelativePath": chunk.get("sourceRelativePath") or file.get("sourceRelativePath"),
                    "pageIndexNodeIds": chunk.get("pageIndexNodeIds") or [],
                    "contextType": context_type,
                    "sourceMethod": source_method,
                    "ocrConfidence": chunk.get("ocrConfidence"),
                    "qualityFlags": chunk.get("qualityFlags") or [],
                    "evidenceUsable": chunk.get("evidenceUsable", True),
                    "evidenceStatusReason": chunk.get("evidenceStatusReason"),
                    "retrievalWeightTier": chunk.get("retrievalWeightTier") or "default",
                    "scope": {
                        "projectId": file.get("projectId"),
                        "nodeId": file.get("nodeId"),
                        "contextType": context_type,
                        "sourceMethod": source_method,
                    },
                    "tags": [file.get("nodeName"), file.get("fileName")],
                },
                default_version=default_version,
            )
        )

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if candidate.get("status") in {"deprecated", "retired", "停用"}:
            continue
        clause_id = str(candidate["clauseId"])
        unique.setdefault(clause_id, candidate)
    return list(unique.values())


def normalize_page_index_node(candidate: dict[str, Any], *, default_version: str = "inspection_kb@1.0.0") -> dict[str, Any]:
    node_id = str(candidate.get("pageIndexNodeId") or candidate.get("id") or candidate.get("nodeId") or f"pin-{uuid4().hex[:8]}")
    return {
        "id": str(candidate.get("id") or node_id),
        "pageIndexNodeId": node_id,
        "kbDocId": candidate.get("kbDocId") or candidate.get("sourceId") or "KS-STANDARD-RULES",
        "kbVersion": candidate.get("kbVersion") or candidate.get("version") or default_version,
        "nodeId": str(candidate.get("nodeId") or node_id),
        "parentNodeId": candidate.get("parentNodeId"),
        "title": candidate.get("title") or candidate.get("name") or node_id,
        "summary": candidate.get("summary") or candidate.get("text") or "",
        "startPage": candidate.get("startPage"),
        "endPage": candidate.get("endPage"),
        "sectionPath": candidate.get("sectionPath") or [],
        "children": candidate.get("children") or [],
        "linkedClauseIds": candidate.get("linkedClauseIds") or [],
        "businessPackId": candidate.get("businessPackId") or (candidate.get("metadata") or {}).get("businessPackId"),
        "nodeTypes": candidate.get("nodeTypes") or (candidate.get("metadata") or {}).get("nodeTypes") or [],
        "materialTypes": candidate.get("materialTypes") or (candidate.get("metadata") or {}).get("materialTypes") or [],
        "tags": candidate.get("tags") or [],
        "status": candidate.get("status") or "effective",
        "qualityFlags": candidate.get("qualityFlags") or [],
        "evidenceUsable": candidate.get("evidenceUsable", True),
        "evidenceStatusReason": candidate.get("evidenceStatusReason"),
        "retrievalWeightTier": candidate.get("retrievalWeightTier") or "default",
    }


def page_index_node_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    source_versions = source_version_by_id(state)
    default_version = kb_version or next(iter(source_versions.values()), "inspection_kb@1.0.0")
    unique: dict[str, dict[str, Any]] = {}
    for node in state.get("knowledge_page_index_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        normalized = normalize_page_index_node(node, default_version=default_version)
        if normalized.get("status") in {"deprecated", "retired", "停用"}:
            continue
        unique.setdefault(str(normalized["pageIndexNodeId"]), normalized)
    return list(unique.values())


def clause_score(clause: dict[str, Any], tokens: list[str], *, node_id: int | None = None, business_pack_id: str | None = None) -> float:
    haystack = " ".join(
        str(part or "")
        for part in [
            clause.get("clauseId"),
            clause.get("clauseNo"),
            clause.get("title"),
            clause.get("text"),
            " ".join(str(item or "") for item in clause.get("tags") or []),
        ]
    ).lower()
    score = 0.0
    for token in tokens:
        if token and token in haystack:
            score += 2.0 if len(token) > 1 else 0.25
    scope = clause.get("scope") or {}
    node_ids = {int(item) for item in scope.get("nodeIds") or [] if str(item).isdigit()}
    if node_id is not None and (scope.get("nodeId") == node_id or node_id in node_ids):
        score += 3.0
    if business_pack_id and scope.get("businessPackId") == business_pack_id:
        score += 1.0
    if clause.get("sourceEvidenceLinkId"):
        score += 0.5
    return score


def retrieval_quality_bias(clause: dict[str, Any], query: str) -> float:
    scope = clause.get("scope") or {}
    context_type = str(scope.get("contextType") or clause.get("contextType") or "").lower()
    source_method = str(scope.get("sourceMethod") or clause.get("sourceMethod") or "").lower()
    tags = " ".join(str(item or "") for item in clause.get("tags") or [])
    source_path = str(clause.get("sourceRelativePath") or "")
    title = str(clause.get("title") or "")
    combined = f"{source_path} {title} {tags}"
    score = 0.0
    quality_flags = {str(item) for item in clause.get("qualityFlags") or []}
    if clause.get("evidenceUsable") is False or "publisher_metadata" in quality_flags or "web_url_metadata" in quality_flags:
        score -= 28.0
    if str(clause.get("retrievalWeightTier") or "") == "metadata":
        score -= 12.0
    if context_type == "business_rule_context" or source_path.endswith("rules/业务规则.md") or "业务规则.md" in source_path:
        score -= 40.0
    elif context_type == "visual_extracted_reference" or "visual" in source_method or "视觉" in tags:
        score -= 12.0
    elif context_type == "standard_reference":
        score += 4.0
    if source_method in {"remote_ocr", "remote_ocr_fragments", "pymupdf_text_layer"}:
        score += 3.0
    if any(marker in combined for marker in ["已被", "替代", "废止"]):
        years = set(re.findall(r"(?:19|20)\d{2}", query or ""))
        replacement_is_explicit = bool(years and any(year in combined for year in years))
        score += 1.0 if replacement_is_explicit else -8.0
    return score


def token_overlap_score(haystack: str, tokens: list[str]) -> float:
    lowered = haystack.lower()
    score = 0.0
    for token in tokens:
        if token and token in lowered:
            score += 2.0 if len(token) > 1 else 0.25
    return score


def exact_clause_score(clause: dict[str, Any], exact_refs: list[str]) -> float:
    if not exact_refs:
        return 0.0
    searchable = " ".join(
        normalize_clause_ref(part)
        for part in [
            clause.get("clauseId"),
            clause.get("clauseNo"),
            clause.get("id"),
            clause.get("title"),
            " ".join(str(item or "") for item in clause.get("tags") or []),
        ]
    )
    score = 0.0
    for ref in exact_refs:
        if ref and ref == normalize_clause_ref(clause.get("clauseNo")):
            score += 50.0
        elif ref and ref == normalize_clause_ref(clause.get("clauseId")):
            score += 45.0
        elif ref and ref in searchable:
            score += 30.0
    return score


def pageindex_clause_score(clause: dict[str, Any], tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    section_text = " ".join(str(item or "") for item in clause.get("sectionPath") or []).lower()
    page_score = 0.0
    for token in tokens:
        if token and token in section_text:
            page_score += 2.0
    if clause.get("pageNo") is not None:
        page_score += 0.5
    if clause.get("bbox"):
        page_score += 0.5
    return page_score


def page_index_node_score(
    node: dict[str, Any],
    tokens: list[str],
    *,
    node_id: int | None = None,
    business_pack_id: str | None = None,
) -> float:
    haystack = " ".join(
        str(part or "")
        for part in [
            node.get("pageIndexNodeId"),
            node.get("title"),
            node.get("summary"),
            " ".join(str(item or "") for item in node.get("sectionPath") or []),
            " ".join(str(item or "") for item in node.get("tags") or []),
            " ".join(str(item or "") for item in node.get("linkedClauseIds") or []),
        ]
    )
    score = token_overlap_score(haystack, tokens)
    if tokens and score <= 0:
        return 0.0
    if node.get("startPage") is not None and node.get("endPage") is not None:
        score += 0.5
    if business_pack_id and node.get("businessPackId") == business_pack_id:
        score += 1.0
    node_types = {str(item) for item in node.get("nodeTypes") or []}
    if node_id is not None and str(node_id) in node_types:
        score += 1.0
    quality_flags = {str(item) for item in node.get("qualityFlags") or []}
    if node.get("evidenceUsable") is False or "publisher_metadata" in quality_flags or "web_url_metadata" in quality_flags:
        score -= 4.0
    return score


def page_index_tree_search(
    state: dict[str, Any],
    tokens: list[str],
    *,
    business_pack_id: str | None = None,
    node_id: int | None = None,
    kb_version: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    nodes = page_index_node_candidates(state, kb_version=kb_version)
    scored: list[dict[str, Any]] = []
    for node in nodes:
        score = page_index_node_score(node, tokens, node_id=node_id, business_pack_id=business_pack_id)
        if score <= 0 and tokens:
            continue
        scored.append({**node, "score": round(score or 0.1, 4)})
    scored.sort(key=lambda item: (float(item.get("score") or 0), len(item.get("linkedClauseIds") or [])), reverse=True)
    selected_nodes = scored[: max(1, int(top_k or 5))]
    linked_clause_ids: list[str] = []
    for node in selected_nodes:
        for clause_id in node.get("linkedClauseIds") or []:
            if clause_id and clause_id not in linked_clause_ids:
                linked_clause_ids.append(str(clause_id))
    node_by_id = {str(node.get("nodeId")): node for node in nodes}
    tree_path: list[dict[str, Any]] = []
    for node in selected_nodes[:3]:
        current: dict[str, Any] | None = node
        lineage: list[dict[str, Any]] = []
        while current:
            lineage.append(
                {
                    "pageIndexNodeId": current.get("pageIndexNodeId"),
                    "nodeId": current.get("nodeId"),
                    "title": current.get("title"),
                }
            )
            parent_id = current.get("parentNodeId")
            current = node_by_id.get(str(parent_id)) if parent_id is not None else None
        tree_path.extend(reversed(lineage))
    return {
        "candidateNodeCount": len(nodes),
        "selectedNodes": [
            {
                "pageIndexNodeId": node.get("pageIndexNodeId"),
                "nodeId": node.get("nodeId"),
                "title": node.get("title"),
                "summary": node.get("summary"),
                "startPage": node.get("startPage"),
                "endPage": node.get("endPage"),
                "sectionPath": node.get("sectionPath"),
                "linkedClauseIds": node.get("linkedClauseIds"),
                "score": node.get("score"),
                "qualityFlags": node.get("qualityFlags") or [],
                "evidenceUsable": node.get("evidenceUsable", True),
                "evidenceStatusReason": node.get("evidenceStatusReason"),
                "retrievalWeightTier": node.get("retrievalWeightTier") or "default",
            }
            for node in selected_nodes
        ],
        "linkedClauseIds": linked_clause_ids,
        "treeSearchPath": tree_path,
    }


def retrieve_knowledge_clauses(
    state: dict[str, Any],
    *,
    query: str,
    review_run_id: str | None = None,
    business_pack_id: str | None = None,
    node_id: int | None = None,
    kb_version: str | None = None,
    top_k: int = 5,
    query_type: str = "review_basis_search",
    dense_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    tokens = query_tokens(query)
    router_signals = build_router_signals(query, tokens)
    selected_route = classify_retrieval_route(query, tokens)
    exact_refs = list(router_signals.get("exactClauseRefs") or [])
    query_alias_matches = list(router_signals.get("standardAliases") or [])
    dense_ids = {str(item) for item in dense_chunk_ids or [] if item}
    candidates = knowledge_clause_candidates(state, kb_version=kb_version)
    page_index_result = (
        page_index_tree_search(
            state,
            tokens,
            business_pack_id=business_pack_id,
            node_id=node_id,
            kb_version=kb_version,
            top_k=top_k,
        )
        if selected_route == "pageindex_tree_search"
        else {"candidateNodeCount": len(page_index_node_candidates(state, kb_version=kb_version)), "selectedNodes": [], "linkedClauseIds": [], "treeSearchPath": []}
    )
    page_index_clause_ids = {str(item) for item in page_index_result.get("linkedClauseIds") or []}
    page_index_node_ids_by_clause: dict[str, list[str]] = {}
    for node in page_index_result.get("selectedNodes") or []:
        node_ref = str(node.get("pageIndexNodeId") or "")
        for clause_id in node.get("linkedClauseIds") or []:
            if clause_id and node_ref:
                page_index_node_ids_by_clause.setdefault(str(clause_id), []).append(node_ref)
    scored: list[dict[str, Any]] = []
    for clause in candidates:
        base_score = clause_score(clause, tokens, node_id=node_id, business_pack_id=business_pack_id)
        route_score = 0.0
        retrieval_mode = "hybrid_bm25_dense_local"
        if selected_route == "exact_clause_lookup":
            route_score = exact_clause_score(clause, exact_refs)
            if route_score > 0:
                retrieval_mode = "exact_clause_lookup"
                base_score = (base_score * 0.1) + route_score + 100.0
        elif selected_route == "pageindex_tree_search":
            route_score = pageindex_clause_score(clause, tokens)
            if str(clause.get("clauseId")) in page_index_clause_ids:
                route_score += 50.0
                retrieval_mode = "pageindex_tree_local"
            if route_score > 0:
                retrieval_mode = "pageindex_tree_local"
        score = base_score + route_score
        if str(clause.get("clauseId")) in dense_ids:
            score += 35.0
            retrieval_mode = "hybrid_dense_local"
        alias_matches = standard_alias_candidate_matches(clause, query, query_matches=query_alias_matches)
        score += standard_number_match_score(clause, query)
        score += max((float(match.get("boost") or 0.0) for match in alias_matches), default=0.0)
        score += source_title_overlap_score(clause, query)
        score += retrieval_quality_bias(clause, query)
        if score <= 0 and tokens:
            continue
        scored.append({**clause, "score": round(score or 0.1, 4), "retrievalMode": retrieval_mode, "aliasMatches": alias_matches})
    scored.sort(
        key=lambda item: (
            item.get("retrievalMode") == "exact_clause_lookup",
            item.get("retrievalMode") == "pageindex_tree_local",
            float(item.get("score") or 0),
            item.get("sourceEvidenceLinkId") is not None,
        ),
        reverse=True,
    )
    selected = scored[: max(1, int(top_k or 5))]
    if not selected and candidates:
        selected = [{**candidates[0], "score": 0.1, "retrievalMode": "clause_fallback"}]
    trace_id = f"RTR-{uuid4().hex[:8].upper()}"
    trace = {
        "id": trace_id,
        "retrievalTraceId": trace_id,
        "reviewRunId": review_run_id,
        "query": query,
        "queryType": query_type,
        "routerVersion": "knowledge-router-v2",
        "selectedRoute": selected_route,
        "routerSignals": router_signals,
        "queryRouter": {
            "selectedRoute": selected_route,
            "signals": router_signals,
            "fallbackRoute": "hybrid_review_basis_search",
        },
        "filters": {
            "businessPackId": business_pack_id,
            "nodeId": node_id,
            "effectiveAt": server_time(),
        },
        "retrievers": [
            {"type": "exact_clause_lookup", "enabled": selected_route == "exact_clause_lookup", "clauseRefs": exact_refs},
            {"type": "standard_alias_registry", "enabled": bool(query_alias_matches), "matchCount": len(query_alias_matches), "matches": query_alias_matches[:5]},
            {"type": "clause_index", "topK": min(top_k, 5), "candidateCount": len(candidates)},
            {"type": "hybrid_bm25_dense", "topK": top_k, "implementation": "offline_hash_pgvector_or_json", "denseHitCount": len(dense_ids)},
            {
                "type": "pageindex_tree",
                "enabled": selected_route == "pageindex_tree_search",
                "implementation": "local_page_index_nodes",
                "candidateNodeCount": page_index_result.get("candidateNodeCount"),
                "selectedNodeCount": len(page_index_result.get("selectedNodes") or []),
            },
        ],
        "pageIndexTree": page_index_result,
        "selectedClauses": [
            {
                "clauseId": item.get("clauseId"),
                "kbDocId": item.get("kbDocId"),
                "kbVersion": item.get("kbVersion"),
                "clauseNo": item.get("clauseNo"),
                "title": item.get("title"),
                "text": item.get("text"),
                "pageNo": item.get("pageNo"),
                "bbox": item.get("bbox"),
                "score": item.get("score"),
                "retrievalMode": item.get("retrievalMode"),
                "aliasMatches": item.get("aliasMatches") or [],
                "qualityFlags": item.get("qualityFlags") or [],
                "evidenceUsable": item.get("evidenceUsable", True),
                "evidenceStatusReason": item.get("evidenceStatusReason"),
                "retrievalWeightTier": item.get("retrievalWeightTier") or "default",
                "pageIndexNodeIds": page_index_node_ids_by_clause.get(str(item.get("clauseId")), [])
                or item.get("pageIndexNodeIds")
                or [],
                "sourceRelativePath": item.get("sourceRelativePath"),
                "sourceEvidenceLinkId": item.get("sourceEvidenceLinkId"),
            }
            for item in selected
        ],
        "kbVersion": kb_version or (selected[0].get("kbVersion") if selected else "inspection_kb@1.0.0"),
        "createdAt": server_time(),
    }
    return {"trace": trace, "clauses": selected}


def answer_draft_from_clauses(question: str, clauses: list[dict[str, Any]]) -> str:
    if not clauses:
        return f"围绕“{question}”，未检索到可用条款，建议转人工补充依据。"
    first = clauses[0]
    return (
        f"围绕“{question}”，优先引用 {first.get('clauseNo') or first.get('clauseId')} "
        f"（{first.get('title')}）进行核验，并结合 OCR 证据、规则结果和人工确认形成正式结论。"
    )
