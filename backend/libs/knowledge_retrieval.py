from __future__ import annotations

import json
import os
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


@lru_cache(maxsize=1)
def _jieba_module() -> Any:
    try:
        import jieba  # type: ignore

        jieba.setLogLevel(60)
        return jieba
    except Exception:
        return None


@lru_cache(maxsize=20000)
def lexical_terms(text: str) -> tuple[str, ...]:
    """Word-level terms for BM25: jieba search-mode segmentation when available,
    falling back to sliding CJK bigrams + ASCII tokens. Sliding bigrams (not the
    greedy 1-4 char chunker) keep query/document terms alignable at any offset."""
    raw = str(text or "").lower()
    if not raw.strip():
        return ()
    jieba = _jieba_module()
    if jieba is not None:
        terms = [term.strip() for term in jieba.cut_for_search(raw)]
        return tuple(term for term in terms if term and (len(term) > 1 or term.isascii()))
    terms: list[str] = []
    for run in re.findall(r"[一-鿿]+|[a-z0-9_.:/-]+", raw):
        if run[0].isascii():
            terms.append(run)
        elif len(run) == 1:
            terms.append(run)
        else:
            terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tuple(terms)


def clause_lexical_haystack(clause: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in [
            clause.get("clauseId"),
            clause.get("clauseNo"),
            clause.get("title"),
            clause.get("text"),
            " ".join(str(item or "") for item in clause.get("tags") or []),
        ]
    )


def bm25_scores_for_texts(
    items: list[tuple[str, str]],
    query: str,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> dict[str, float]:
    """Okapi BM25 over an (id, text) corpus: per-query IDF, term-frequency
    saturation, and document-length normalization."""
    import math

    query_terms = [term for term in dict.fromkeys(lexical_terms(str(query or ""))) if term]
    if not items or not query_terms:
        return {}
    doc_terms: list[tuple[str, dict[str, int], int]] = []
    for doc_id, text in items:
        terms = lexical_terms(str(text or ""))
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        doc_terms.append((str(doc_id), counts, len(terms)))
    total_docs = len(doc_terms)
    avg_len = max(1.0, sum(length for _, _, length in doc_terms) / total_docs)
    df: dict[str, int] = {}
    for term in query_terms:
        df[term] = sum(1 for _, counts, _ in doc_terms if term in counts)
    scores: dict[str, float] = {}
    for clause_id, counts, length in doc_terms:
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf <= 0:
                continue
            idf = math.log(1.0 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * length / avg_len))
        if score > 0:
            scores[clause_id] = score
    return scores


def bm25_scores_for_clauses(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> dict[str, float]:
    return bm25_scores_for_texts(
        [(str(clause.get("clauseId")), clause_lexical_haystack(clause)) for clause in candidates],
        query,
        k1=k1,
        b=b,
    )


def page_index_node_haystack(node: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in [
            node.get("title"),
            node.get("summary"),
            " ".join(str(item or "") for item in node.get("sectionPath") or []),
            " ".join(str(item or "") for item in node.get("tags") or []),
        ]
    )


def page_index_node_bonus(
    node: dict[str, Any],
    *,
    node_id: int | None = None,
    business_pack_id: str | None = None,
) -> float:
    """Structural bonuses/penalties for PageIndex nodes, shared by the BM25
    node scorer (token-overlap logic lives in page_index_node_score)."""
    score = 0.0
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


def clause_scope_bonus(
    clause: dict[str, Any],
    *,
    node_id: int | None = None,
    business_pack_id: str | None = None,
) -> float:
    scope = clause.get("scope") or {}
    node_ids = {int(item) for item in scope.get("nodeIds") or [] if str(item).isdigit()}
    score = 0.0
    if node_id is not None and (scope.get("nodeId") == node_id or node_id in node_ids):
        score += 3.0
    if business_pack_id and scope.get("businessPackId") == business_pack_id:
        score += 1.0
    if clause.get("sourceEvidenceLinkId"):
        score += 0.5
    return score


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


STANDARD_FILE_SUFFIX_RE = re.compile(r"\.(pdf|docx|doc|txt|md|markdown)$", re.IGNORECASE)


def auto_alias_rules_from_state(state: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Mine standard-name ↔ standard-number alias rules from indexed file names,
    so natural-language queries reach the right standard without a hand-written
    registry entry per document. Auto rules use a lower boost than curated ones."""
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for file in state.get("knowledge_files", []) or []:
        if not isinstance(file, dict):
            continue
        name = str(file.get("fileName") or file.get("sourceRelativePath") or "")
        if not name:
            continue
        refs = standard_refs_from_text(name)
        if not refs:
            continue
        ref = refs[0]
        key = (ref["prefix"], ref["number"], ref["year"])
        if key in seen:
            continue
        base_name = STANDARD_FILE_SUFFIX_RE.sub("", name.rsplit("/", 1)[-1])
        phrases = [segment for segment in re.findall(r"[一-鿿]{4,}", base_name)]
        if not phrases:
            continue
        seen.add(key)
        normalized = normalize_alias_rule(
            {
                "id": f"auto-file-{file.get('id')}",
                "source": "auto_file_name",
                "phrases": phrases,
                "prefix": ref["prefix"],
                "number": ref["number"],
                "year": ref["year"],
                "boost": 60.0,
            }
        )
        if normalized:
            rules.append(normalized)
    return tuple(rules)


def standard_alias_matches(query: str, *, extra_rules: tuple[dict[str, Any], ...] | None = None) -> list[dict[str, Any]]:
    normalized_query = normalized_business_phrase(query)
    matches: list[dict[str, Any]] = []
    for rule in tuple(standard_alias_rules()) + tuple(extra_rules or ()):
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


_CANDIDATE_CACHE: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
_CANDIDATE_CACHE_MAX_ENTRIES = 8


def candidate_cache_enabled() -> bool:
    value = os.getenv("AICHECK_RETRIEVAL_CANDIDATE_CACHE")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _candidates_fingerprint(state: dict[str, Any]) -> tuple[Any, ...]:
    """Cheap fingerprint of the state collections that feed candidate
    normalization: lengths plus a rolling hash of (id, updatedAt) per row.
    Mutations in this codebase bump updatedAt (or change row counts/ids), so
    this catches real changes without re-running regex normalization."""
    parts: list[Any] = []
    for key in ("knowledge_clauses", "knowledge_chunks", "knowledge_files", "knowledge_sources", "evidence_links"):
        rows = state.get(key) or []
        rolling = len(rows)
        for row in rows:
            if isinstance(row, dict):
                rolling = (rolling * 1000003) ^ (
                    hash((row.get("id"), row.get("updatedAt"), row.get("indexEnabled"), row.get("status")))
                    & 0xFFFFFFFFFFFFFF
                )
        parts.append(rolling)
    return tuple(parts)


def knowledge_clause_candidates_cached(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    """LRU-cached wrapper around knowledge_clause_candidates. Retrieval reads
    candidates without mutating them, so identical state can reuse the
    normalized list instead of re-normalizing every clause per query.
    Disable with AICHECK_RETRIEVAL_CANDIDATE_CACHE=false."""
    if not candidate_cache_enabled():
        return knowledge_clause_candidates(state, kb_version=kb_version)
    key = (kb_version, _candidates_fingerprint(state))
    cached = _CANDIDATE_CACHE.get(key)
    if cached is not None:
        return cached
    candidates = knowledge_clause_candidates(state, kb_version=kb_version)
    _CANDIDATE_CACHE[key] = candidates
    while len(_CANDIDATE_CACHE) > _CANDIDATE_CACHE_MAX_ENTRIES:
        _CANDIDATE_CACHE.pop(next(iter(_CANDIDATE_CACHE)))
    return candidates


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
    query: str | None = None,
) -> dict[str, Any]:
    nodes = page_index_node_candidates(state, kb_version=kb_version)
    query_text = str(query if query is not None else " ".join(tokens or ""))
    container_nodes = [node for node in nodes if node.get("children")]
    node_by_pin = {str(node.get("pageIndexNodeId")): node for node in nodes}

    def score_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # BM25 over node title/summary/section-path text plus structural bonuses,
        # replacing the substring token-overlap scorer.
        bm25 = bm25_scores_for_texts(
            [(str(node.get("pageIndexNodeId")), page_index_node_haystack(node)) for node in pool],
            query_text,
        )
        pool_scored: list[dict[str, Any]] = []
        for node in pool:
            lexical = bm25.get(str(node.get("pageIndexNodeId")), 0.0)
            if tokens and lexical <= 0:
                continue
            score = lexical + page_index_node_bonus(node, node_id=node_id, business_pack_id=business_pack_id)
            if score <= 0 and tokens:
                continue
            pool_scored.append({**node, "score": round(score or 0.1, 4)})
        return pool_scored

    search_strategy = "flat_scan"
    candidate_pool = nodes
    if container_nodes and any(node.get("parentNodeId") for node in nodes):
        # Hierarchical two-stage search: score container (file-level) nodes on
        # their titles/summaries first, then descend into only the best files'
        # children instead of flat-scanning every page node.
        scored_containers = score_pool(container_nodes)
        scored_containers.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        top_containers = scored_containers[:3]
        if top_containers:
            child_ids: list[str] = []
            for container in top_containers:
                for child_id in container.get("children") or []:
                    if child_id and str(child_id) not in child_ids:
                        child_ids.append(str(child_id))
            descended = [node_by_pin[child_id] for child_id in child_ids if child_id in node_by_pin]
            if descended:
                candidate_pool = descended
                search_strategy = "hierarchical_two_stage"
    scored = score_pool(candidate_pool)
    if not scored and search_strategy == "hierarchical_two_stage":
        # The chosen files' pages had no token match; fall back to the flat scan.
        search_strategy = "hierarchical_flat_fallback"
        scored = score_pool(nodes)
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
        seen_lineage: set[str] = set()
        while current:
            current_pin = str(current.get("pageIndexNodeId"))
            if current_pin in seen_lineage:
                break
            seen_lineage.add(current_pin)
            lineage.append(
                {
                    "pageIndexNodeId": current.get("pageIndexNodeId"),
                    "nodeId": current.get("nodeId"),
                    "title": current.get("title"),
                }
            )
            parent_id = current.get("parentNodeId")
            if parent_id is None:
                current = None
            else:
                # Parent links carry pageIndexNodeIds; fall back to nodeId keys
                # for legacy nodes.
                current = node_by_pin.get(str(parent_id)) or node_by_id.get(str(parent_id))
        tree_path.extend(reversed(lineage))
    return {
        "candidateNodeCount": len(nodes),
        "searchStrategy": search_strategy,
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


def rrf_fusion_config() -> dict[str, float]:
    try:
        k = float(os.getenv("AICHECK_RETRIEVAL_RRF_K", "60"))
    except (TypeError, ValueError):
        k = 60.0
    try:
        dense_weight = float(os.getenv("AICHECK_RETRIEVAL_DENSE_WEIGHT", "0.7"))
    except (TypeError, ValueError):
        dense_weight = 0.7
    return {"k": max(1.0, k), "denseWeight": max(0.0, dense_weight)}


def dense_rank_map(
    dense_hits: list[dict[str, Any]] | None,
    dense_chunk_ids: list[str] | None,
) -> dict[str, int]:
    """Ordered chunkId -> 1-based rank from dense hits (or the legacy id list)."""
    ranks: dict[str, int] = {}
    if dense_hits:
        ordered: list[str] = []
        for item in dense_hits:
            if isinstance(item, dict):
                ordered.append(str(item.get("chunkId") or ""))
            else:
                ordered.append(str(item or ""))
        for chunk_id in ordered:
            if chunk_id and chunk_id not in ranks:
                ranks[chunk_id] = len(ranks) + 1
        return ranks
    for chunk_id in dense_chunk_ids or []:
        key = str(chunk_id or "")
        if key and key not in ranks:
            ranks[key] = len(ranks) + 1
    return ranks


def apply_cross_encoder_rerank(
    state: dict[str, Any],
    query: str,
    scored: list[dict[str, Any]],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Rerank the fused top window with a cross-encoder when configured.

    Controlled by knowledge_config.rerankEnabled (default on) plus the
    AICHECK_RERANK_API_BASE endpoint; degrades gracefully — a failed or absent
    reranker leaves the fused ordering untouched and records why.
    """
    info: dict[str, Any] = {
        "configEnabled": True,
        "endpointConfigured": False,
        "applied": False,
        "status": "skipped",
        "model": None,
        "windowSize": 0,
        "reason": None,
    }
    config = state.get("knowledge_config") if isinstance(state.get("knowledge_config"), dict) else {}
    if config.get("rerankEnabled") is False:
        info.update({"configEnabled": False, "reason": "rerank_disabled_by_config"})
        return info
    if not scored:
        info["reason"] = "no_candidates"
        return info
    try:
        from libs.integrations.reranker_client import RerankerClient

        client = RerankerClient()
    except Exception:
        info.update({"status": "degraded", "reason": "reranker_client_unavailable"})
        return info
    info["endpointConfigured"] = client.enabled
    if not client.enabled:
        info["reason"] = "rerank_endpoint_not_configured"
        return info
    window = scored[: max(int(top_k or 5) * 4, 20)]
    documents = [
        " ".join(
            part
            for part in [
                str(item.get("title") or ""),
                str(item.get("text") or "")[:1200],
            ]
            if part
        )
        for item in window
    ]
    try:
        results = client.rerank(str(query or ""), documents)
    except Exception as exc:
        info.update({"status": "degraded", "reason": exc.__class__.__name__})
        return info
    for result in results:
        index = int(result.get("index", -1))
        if 0 <= index < len(window):
            window[index]["rerankScore"] = round(float(result.get("relevanceScore") or 0.0), 6)
    scored.sort(
        key=lambda item: (
            item.get("retrievalMode") == "exact_clause_lookup",
            item.get("retrievalMode") == "pageindex_tree_local",
            item.get("rerankScore") is not None,
            float(item.get("rerankScore") if item.get("rerankScore") is not None else 0.0),
            float(item.get("fusedScore") or 0),
        ),
        reverse=True,
    )
    info.update(
        {
            "applied": True,
            "status": "ok",
            "model": client.model_id,
            "windowSize": len(window),
        }
    )
    return info


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
    dense_hits: list[dict[str, Any]] | None = None,
    dense_meta: dict[str, Any] | None = None,
    preferred_route: str | None = None,
) -> dict[str, Any]:
    tokens = query_tokens(query)
    router_signals = build_router_signals(query, tokens)
    selected_route = classify_retrieval_route(query, tokens)
    if preferred_route and selected_route != "exact_clause_lookup":
        # Callers such as the review orchestrator use long, content-rich queries;
        # a route hint keeps them on the hybrid route instead of tripping the
        # query-length PageIndex heuristic. Exact clause lookups always win.
        selected_route = preferred_route
        router_signals["preferredRoute"] = preferred_route
    exact_refs = list(router_signals.get("exactClauseRefs") or [])
    auto_rules = auto_alias_rules_from_state(state)
    query_alias_matches = standard_alias_matches(query, extra_rules=auto_rules)
    router_signals["standardAliases"] = query_alias_matches
    dense_ranks = dense_rank_map(dense_hits, dense_chunk_ids)
    dense_ids = set(dense_ranks)
    fusion = rrf_fusion_config()
    candidates = knowledge_clause_candidates_cached(state, kb_version=kb_version)
    page_index_result = (
        page_index_tree_search(
            state,
            tokens,
            business_pack_id=business_pack_id,
            node_id=node_id,
            kb_version=kb_version,
            top_k=top_k,
            query=query,
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
    bm25_by_clause = bm25_scores_for_clauses(candidates, query)
    scored: list[dict[str, Any]] = []
    for clause in candidates:
        bm25_score = bm25_by_clause.get(str(clause.get("clauseId")), 0.0)
        base_score = bm25_score + clause_scope_bonus(clause, node_id=node_id, business_pack_id=business_pack_id)
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
        dense_rank = dense_ranks.get(str(clause.get("clauseId")))
        if dense_rank is not None and retrieval_mode == "hybrid_bm25_dense_local":
            # Tag as dense-assisted, but never demote exact/pageindex route modes,
            # which carry sort priority and audit meaning.
            retrieval_mode = "hybrid_dense_local"
        alias_matches = standard_alias_candidate_matches(clause, query, query_matches=query_alias_matches)
        score += standard_number_match_score(clause, query)
        score += max((float(match.get("boost") or 0.0) for match in alias_matches), default=0.0)
        score += source_title_overlap_score(clause, query)
        score += retrieval_quality_bias(clause, query)
        if score <= 0 and tokens and dense_rank is None:
            continue
        scored.append(
            {
                **clause,
                "score": round(score or 0.1, 4),
                "bm25Score": round(bm25_score, 4),
                "retrievalMode": retrieval_mode,
                "aliasMatches": alias_matches,
                "denseRank": dense_rank,
            }
        )
    # Reciprocal Rank Fusion: fuse the lexical ranking with the dense ranking
    # instead of adding incomparable score scales. Without dense hits this
    # reduces exactly to the lexical ordering.
    lexical_sorted = sorted(scored, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    for lexical_rank, item in enumerate(lexical_sorted, start=1):
        fused = 1.0 / (fusion["k"] + lexical_rank)
        dense_rank = item.get("denseRank")
        if dense_rank is not None:
            fused += fusion["denseWeight"] / (fusion["k"] + float(dense_rank))
        item["lexicalRank"] = lexical_rank
        item["fusedScore"] = round(fused, 8)
    scored.sort(
        key=lambda item: (
            item.get("retrievalMode") == "exact_clause_lookup",
            item.get("retrievalMode") == "pageindex_tree_local",
            float(item.get("fusedScore") or 0),
            float(item.get("score") or 0),
            item.get("sourceEvidenceLinkId") is not None,
        ),
        reverse=True,
    )
    rerank_info = apply_cross_encoder_rerank(state, query, scored, top_k=top_k)
    selected = scored[: max(1, int(top_k or 5))]
    # No arbitrary candidates[0] fallback: an empty result with an explicit
    # no_basis_found marker beats a wrong-but-confident-looking citation.
    no_basis_found = not selected
    trace_id = f"RTR-{uuid4().hex[:8].upper()}"
    trace = {
        "id": trace_id,
        "retrievalTraceId": trace_id,
        "reviewRunId": review_run_id,
        "query": query,
        "queryType": query_type,
        "routerVersion": "knowledge-router-v3-rrf",
        "selectedRoute": selected_route,
        "routerSignals": router_signals,
        "denseRetrieval": dense_meta
        or {"status": "not_provided", "denseDegraded": False, "hitCount": len(dense_ids)},
        "fusion": {"method": "rrf", "k": fusion["k"], "denseWeight": fusion["denseWeight"]},
        "rerank": rerank_info,
        "noBasisFound": no_basis_found,
        "aliasSources": sorted({str(match.get("source") or "") for match in query_alias_matches if match.get("source")}),
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
            {
                "type": "hybrid_bm25_dense",
                "topK": top_k,
                "implementation": "rrf_bm25_dense_pgvector_or_json",
                "lexicalScoring": "okapi_bm25_jieba_or_ngram",
                "denseHitCount": len(dense_ids),
                "fusion": {"method": "rrf", "k": fusion["k"], "denseWeight": fusion["denseWeight"]},
                "denseRetrieval": dense_meta
                or {"status": "not_provided", "denseDegraded": False, "hitCount": len(dense_ids)},
            },
            {
                "type": "cross_encoder_rerank",
                "enabled": bool(rerank_info.get("endpointConfigured")) and bool(rerank_info.get("configEnabled")),
                "applied": bool(rerank_info.get("applied")),
                "model": rerank_info.get("model"),
                "windowSize": rerank_info.get("windowSize"),
                "status": rerank_info.get("status"),
            },
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
                "bm25Score": item.get("bm25Score"),
                "fusedScore": item.get("fusedScore"),
                "lexicalRank": item.get("lexicalRank"),
                "denseRank": item.get("denseRank"),
                "rerankScore": item.get("rerankScore"),
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
