# 标准规范信息最全集合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 59 份标准规范生成新值优先、旧值补缺、完整可追溯的 canonical 信息全集，并让详情、检索和 AI 审查统一消费该全集。

**Architecture:** 新增只读来源适配器和派生 `standard_knowledge_records` 集合；canonical builder 从 OCR、视觉抽取、切片、条款、PageIndex、版本、定位和业务规则中收集候选，按稳定身份去重并按来源优先级选择当前值。来源集合保持不可变，迁移器仅幂等写派生记录；API、前端、检索和 AI 逐步切换到 canonical，同时保留旧 `ocrStructured` 兼容路径。

**Tech Stack:** Python 3.12、FastAPI、PostgreSQL JSONB、pytest、Vue 3、TypeScript、Element Plus、现有独立 TypeScript 单测运行器。

**Spec:** `docs/superpowers/specs/2026-08-29-standard-knowledge-canonical-design.md`

## Global Constraints

- 同一语义字段新旧都有时必须使用新 MinerU 结果。
- 只有旧来源存在的信息必须保留并标记 `authority="legacy_only"`。
- 不得修改或删除 OCR、字段、证据、切片、条款、PageIndex、标准版本和业务规则来源记录。
- 59/59 必须生成 canonical 记录；`业务规则.md` 使用 `context_only` 模式。
- 任一来源读取失败不得覆盖上一份有效 canonical；输出必须标记 `partial` 和失败来源。
- 每项字段、条款、表格、公式、图片、印章和关系都必须带来源身份；有页码/bbox 时必须保留，缺失时不得伪造。
- 重复生成不得增加重复记录，来源不变时 `sourceFingerprint` 必须稳定。
- 旧冲突值不得进入当前检索文本；`legacy_only` 只能作为降权补充证据。
- 迁移期保留现有 `ocrStructured` 和旧详情契约。

---

### Task 1: Canonical 持久化与核心选择规则

**Files:**
- Create: `backend/libs/standard_knowledge_canonical.py`
- Create: `backend/tests/test_standard_knowledge_canonical.py`
- Modify: `backend/libs/db/repository.py:181-205`
- Modify: `backend/libs/db/seed.py:2495-2515`

**Interfaces:**
- Produces: `CANONICAL_VERSION = "standard-knowledge-canonical@1"`
- Produces: `SOURCE_PRIORITY: dict[str, int]`
- Produces: `canonical_item_id(kind: str, identity: list[object]) -> str`
- Produces: `select_canonical_field(key: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None`
- Produces: persistence state key `standard_knowledge_records` mapped to PostgreSQL collection of the same name.

- [ ] **Step 1: Write failing priority and persistence tests**

```python
from libs.db.repository import STATE_COLLECTIONS, repo
from libs.standard_knowledge_canonical import select_canonical_field


def test_new_mineru_value_wins_and_old_only_value_survives():
    selected = select_canonical_field(
        "publicationDate",
        [
            {"value": "2014-01-01", "sourceType": "legacy_ocr", "sourceId": "OLD"},
            {"value": "2015-04-02", "sourceType": "new_mineru", "sourceId": "NEW"},
        ],
    )
    assert selected["value"] == "2015-04-02"
    assert selected["authority"] == "current"
    assert selected["selectedSourceId"] == "NEW"
    assert {item["sourceId"] for item in selected["sources"]} == {"OLD", "NEW"}

    legacy_only = select_canonical_field(
        "filingNumber",
        [{"value": "61188-2018", "sourceType": "legacy_ocr", "sourceId": "OLD"}],
    )
    assert legacy_only["value"] == "61188-2018"
    assert legacy_only["authority"] == "legacy_only"


def test_canonical_collection_is_persisted_state():
    assert STATE_COLLECTIONS["standard_knowledge_records"] == "standard_knowledge_records"
    assert "standard_knowledge_records" in repo.state
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py -k 'new_mineru_value or canonical_collection'
```

Expected: import failure for `libs.standard_knowledge_canonical` or missing `standard_knowledge_records` mapping.

- [ ] **Step 3: Implement stable IDs and field selection**

```python
CANONICAL_VERSION = "standard-knowledge-canonical@1"
SOURCE_PRIORITY = {
    "new_mineru": 500,
    "visual_extraction": 400,
    "standard_catalog": 300,
    "legacy_ocr": 200,
    "filename_inference": 100,
}


def canonical_item_id(kind: str, identity: list[object]) -> str:
    normalized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20].upper()
    return f"SKI-{kind.upper()}-{digest}"


def select_canonical_field(key: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    usable = [item for item in candidates if str(item.get("value") or "").strip()]
    if not usable:
        return None
    ordered = sorted(
        usable,
        key=lambda item: (
            SOURCE_PRIORITY.get(str(item.get("sourceType") or ""), 0),
            str(item.get("createdAt") or ""),
        ),
        reverse=True,
    )
    selected = ordered[0]
    return {
        "id": canonical_item_id("field", [key]),
        "key": key,
        "value": selected["value"],
        "authority": "legacy_only" if selected.get("sourceType") == "legacy_ocr" else "current",
        "selectedSourceId": selected.get("sourceId"),
        "sources": ordered,
    }
```

Add `"standard_knowledge_records": "standard_knowledge_records"` to `STATE_COLLECTIONS` and an empty list to seed state.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py -k 'new_mineru_value or canonical_collection'
```

Expected: 2 passed.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/libs/standard_knowledge_canonical.py backend/tests/test_standard_knowledge_canonical.py backend/libs/db/repository.py backend/libs/db/seed.py
git commit -m "feat: add canonical standard knowledge foundation"
```

---

### Task 2: 全来源收集与规范化适配器

**Files:**
- Modify: `backend/libs/standard_knowledge_canonical.py`
- Modify: `backend/tests/test_standard_knowledge_canonical.py`
- Read: `backend/data/visual_extractions/*.json`
- Read: `backend/data/rules_ocr_sidecars/*.json`
- Read: `backend/business_packs/engineering_inspection_v1/standard_clause_catalog.yaml`
- Read: `backend/business_packs/engineering_inspection_v1/rules.yaml`

**Interfaces:**
- Consumes: `canonical_item_id` and `SOURCE_PRIORITY` from Task 1.
- Produces: `collect_standard_sources(state: dict[str, Any], file_id: str, repo_root: Path) -> dict[str, Any]`
- Produces source groups: `file`, `document`, `version`, `newParse`, `legacyParses`, `legacyFields`, `legacyEvidence`, `visualExtraction`, `legacyRuleSidecar`, `chunks`, `clauses`, `pageIndexNodes`, `standardVersions`, `clauseReferences`, `clauseLocators`, `catalogItems`, `ruleReferences`.

Define the test fixture in `backend/tests/test_standard_knowledge_canonical.py` with this exact minimum shape; individual tests may override values through keyword arguments but must not omit source collections:

```python
def canonical_source_fixture(*, without_references: bool = False) -> dict[str, Any]:
    file = {
        "id": "KF-KB-TEST", "sourceId": "KS-STANDARD-RULES", "sourceType": "standard",
        "documentId": "KDOC-TEST", "documentVersionId": "KDV-TEST-V1",
        "fileName": "NB_T 47013.10-2015.pdf", "sourceRelativePath": "rules/standards/NB_T 47013.10-2015.pdf",
        "tenantId": "TENANT-DEFAULT",
    }
    state = {
        "knowledge_files": [file],
        "documents": [{"id": "KDOC-TEST", "currentVersionId": "KDV-TEST-V1", "tenantId": "TENANT-DEFAULT"}],
        "versions": [{"id": "KDV-TEST-V1", "documentId": "KDOC-TEST", "isCurrent": True, "tenantId": "TENANT-DEFAULT"}],
        "ocr_parse_results": [
            {
                "id": "PARSE-NEW", "parseResultId": "PARSE-NEW", "documentVersionId": "KDV-TEST-V1",
                "createdAt": "2026-08-29 12:00:00", "metadata": {"sidecarImported": True},
                "fields": [{"fieldName": "发布日期", "fieldValue": "2015-04-02", "pageNo": 1}],
                "layoutBlocks": [{"blockId": "B-NEW", "blockType": "text", "text": "1.1 范围正文", "pageNo": 7}],
                "tables": [], "seals": [], "pages": [{"pageNo": 1}, {"pageNo": 7}],
            },
            {
                "id": "PARSE-OLD", "parseResultId": "PARSE-OLD", "documentVersionId": "KDV-TEST-V1",
                "createdAt": "2026-07-01 12:00:00", "metadata": {},
                "fields": [
                    {"fieldName": "发布日期", "fieldValue": "2014-01-01", "pageNo": 1},
                    {"fieldName": "备案号", "fieldValue": "61188-2018", "pageNo": 1},
                ],
                "layoutBlocks": [], "tables": [], "seals": [], "pages": [],
            },
        ],
        "extracted_fields": [{"id": "FIELD-OLD", "documentVersionId": "KDV-TEST-V1", "fieldName": "OCR文本", "fieldValue": "旧正文"}],
        "evidence_links": [{"id": "EV-OLD", "documentVersionId": "KDV-TEST-V1", "fieldName": "OCR文本", "quotedText": "旧正文", "pageNo": 7}],
        "knowledge_chunks": [{"id": "CHK-TEST", "fileId": "KF-KB-TEST", "text": "1.1 范围正文", "pageNo": 7}],
        "knowledge_clauses": [{"id": "KC-TEST", "fileId": "KF-KB-TEST", "clauseNo": "1.1", "text": "1.1 范围正文", "pageNo": 7}],
        "knowledge_page_index_nodes": [{"id": "PIN-TEST", "sourceRelativePath": file["sourceRelativePath"], "title": "1 范围", "startPage": 7, "endPage": 7}],
        "standard_document_versions": [{"id": "SDV-TEST", "knowledgeFileId": "KF-KB-TEST", "standardRef": "STD-TEST", "code": "NB/T 47013.10-2015", "name": "衍射时差法超声检测"}],
        "standard_clause_references": [] if without_references else [{"id": "SCR-TEST", "knowledgeFileId": "KF-KB-TEST", "standardRef": "STD-TEST", "clauseNo": "1.1", "sourcePage": 7}],
        "standard_clause_locators": [] if without_references else [{"id": "SCL-TEST", "knowledgeFileId": "KF-KB-TEST", "standardRef": "STD-TEST", "clauseNo": "1.1", "sourcePage": 7, "bbox": [10, 20, 300, 80]}],
        "rule_versions": [{"id": "RULE-1", "nodeIds": [40], "referencedStandards": [{"knowledgeFileId": "KF-KB-TEST", "standardRef": "STD-TEST", "clauseNo": "1.1"}]}],
        "business_packs": [{"id": "engineering_inspection_v1", "standardCatalog": [{"id": "STD-TEST", "code": "NB/T 47013.10-2015", "name": "衍射时差法超声检测"}]}],
    }
    return state
```

- [ ] **Step 1: Write a complete-source fixture test**

```python
def test_collect_standard_sources_maps_every_supported_source(tmp_path):
    state = canonical_source_fixture()
    visual_dir = tmp_path / "backend/data/visual_extractions"
    visual_dir.mkdir(parents=True)
    (visual_dir / "KF-KB-TEST.json").write_text(
        json.dumps(
            {
                "fileId": "KF-KB-TEST",
                "sourceMethod": "codex_visual_manual_extraction",
                "pages": [{"pageNo": 1, "title": "封面", "extractedText": "发布日期为 2015-04-02"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sources = collect_standard_sources(state, "KF-KB-TEST", tmp_path)
    assert sources["newParse"]["parseResultId"] == "PARSE-NEW"
    assert [item["parseResultId"] for item in sources["legacyParses"]] == ["PARSE-OLD"]
    assert len(sources["legacyFields"]) == 1
    assert len(sources["chunks"]) == 1
    assert len(sources["clauses"]) == 1
    assert len(sources["pageIndexNodes"]) == 1
    assert sources["visualExtraction"]["pages"][0]["title"] == "封面"
    assert sources["standardVersions"][0]["standardRef"] == "STD-TEST"
    assert sources["clauseReferences"][0]["clauseNo"] == "1.1"
```

The fixture must include every documented field used by the adapter, including tenant, document/version links and source paths.

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py::test_collect_standard_sources_maps_every_supported_source
```

Expected: `collect_standard_sources` is missing.

- [ ] **Step 3: Implement source collection without mutation**

```python
def collect_standard_sources(state: dict[str, Any], file_id: str, repo_root: Path) -> dict[str, Any]:
    file = _one(state.get("knowledge_files", []), id=file_id)
    if not file or file.get("sourceId") != "KS-STANDARD-RULES":
        raise ValueError(f"not a standard knowledge file: {file_id}")
    document = _one(state.get("documents", []), id=file.get("documentId"))
    version = _one(state.get("versions", []), id=(document or {}).get("currentVersionId"))
    if not document or not version or file.get("documentVersionId") != version.get("id"):
        raise ValueError(f"standard document/version relationship invalid: {file_id}")
    parses = [item for item in state.get("ocr_parse_results", []) if item.get("documentVersionId") == version["id"]]
    new_parse = max(
        [item for item in parses if (item.get("metadata") or {}).get("sidecarImported")],
        key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or ""),
        default=None,
    )
    legacy_parses = [item for item in parses if item is not new_parse]
    return {
        "file": copy.deepcopy(file),
        "document": copy.deepcopy(document),
        "version": copy.deepcopy(version),
        "newParse": copy.deepcopy(new_parse),
        "legacyParses": copy.deepcopy(legacy_parses),
        "legacyFields": _by_version(state.get("extracted_fields", []), version["id"]),
        "legacyEvidence": _by_version(state.get("evidence_links", []), version["id"]),
        "visualExtraction": _read_optional_json(repo_root / "backend/data/visual_extractions" / f"{file_id}.json"),
        "legacyRuleSidecar": _read_optional_json(repo_root / "backend/data/rules_ocr_sidecars" / f"{file_id}.json"),
        "chunks": _by_file(state.get("knowledge_chunks", []), file_id),
        "clauses": _by_file(state.get("knowledge_clauses", []), file_id),
        "pageIndexNodes": _page_nodes_for_path(state, file.get("sourceRelativePath")),
        "standardVersions": _by_file(state.get("standard_document_versions", []), file_id),
        "clauseReferences": _by_file(state.get("standard_clause_references", []), file_id),
        "clauseLocators": _by_file(state.get("standard_clause_locators", []), file_id),
        "catalogItems": _catalog_items_for_file(state, file),
        "ruleReferences": _rule_references_for_file(state, file),
    }
```

Deep-copy every source group. Add a test that serializes `state` before and after collection and asserts byte-identical JSON.

Implement the referenced selectors as pure functions:

```python
def _one(items: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    return next((item for item in items if all(item.get(key) == value for key, value in match.items())), None)


def _by_version(items: list[dict[str, Any]], version_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy([item for item in items if item.get("documentVersionId") == version_id])


def _by_file(items: list[dict[str, Any]], file_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy([
        item for item in items
        if item.get("fileId") == file_id or (item.get("scope") or {}).get("fileId") == file_id
    ])


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _page_nodes_for_path(state: dict[str, Any], source_path: str | None) -> list[dict[str, Any]]:
    normalized = str(source_path or "").replace("\\", "/").lstrip("./")
    return copy.deepcopy([
        item for item in state.get("knowledge_page_index_nodes", [])
        if str(item.get("sourceRelativePath") or "").replace("\\", "/").lstrip("./") == normalized
    ])


def _catalog_items_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for pack in state.get("business_packs", []):
        for item in pack.get("standardCatalog") or []:
            if item.get("knowledgeFileId") == file["id"] or str(item.get("fileName") or "") == file_name:
                result.append({**copy.deepcopy(item), "businessPackId": pack.get("id")})
    return result


def _rule_references_for_file(state: dict[str, Any], file: dict[str, Any]) -> list[dict[str, Any]]:
    file_name = str(file.get("fileName") or "")
    result = []
    for rule in state.get("rule_versions", []):
        for reference in rule.get("referencedStandards") or []:
            if reference.get("knowledgeFileId") == file["id"] or str(reference.get("fileName") or "") == file_name:
                result.append({**copy.deepcopy(reference), "ruleId": rule.get("id"), "nodeIds": list(rule.get("nodeIds") or [])})
    return result
```

- [ ] **Step 4: Run source tests**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py -k 'collect_standard_sources or source_collection_does_not_mutate'
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/libs/standard_knowledge_canonical.py backend/tests/test_standard_knowledge_canonical.py
git commit -m "feat: collect canonical standard knowledge sources"
```

---

### Task 3: Canonical 合并、结构去重与完整度

**Files:**
- Modify: `backend/libs/standard_knowledge_canonical.py`
- Modify: `backend/tests/test_standard_knowledge_canonical.py`

**Interfaces:**
- Consumes: `collect_standard_sources` from Task 2.
- Produces: `build_standard_knowledge_record(state: dict[str, Any], file_id: str, repo_root: Path) -> dict[str, Any]`
- Produces: `canonical_completeness(record: dict[str, Any]) -> dict[str, Any]`
- Produces top-level `kbVersion` copied from the standard knowledge source version; `canonicalVersion` continues to identify the builder schema.
- Produces canonical arrays: `sections`, `clauses`, `blocks`, `tables`, `equations`, `images`, `seals`, `normativeReferences`, `replacementRelations`, `businessRelations`, `evidence`, `provenance`, `history`.

- [ ] **Step 1: Write merge and completeness tests**

```python
def test_build_record_uses_new_values_and_keeps_old_only_information(tmp_path):
    record = build_standard_knowledge_record(canonical_source_fixture(), "KF-KB-TEST", tmp_path)
    assert record["identity"]["standardCode"]["value"] == "NB/T 47013.10-2015"
    assert record["version"]["publicationDate"]["value"] == "2015-04-02"
    assert record["version"]["publicationDate"]["selectedSourceId"] == "PARSE-NEW"
    assert record["identity"]["filingNumber"]["value"] == "61188-2018"
    assert record["identity"]["filingNumber"]["authority"] == "legacy_only"


def test_structure_is_deduplicated_but_all_sources_are_retained(tmp_path):
    record = build_standard_knowledge_record(canonical_source_fixture(), "KF-KB-TEST", tmp_path)
    matching = [item for item in record["clauses"] if item["clauseNo"] == "1.1"]
    assert len(matching) == 1
    assert {source["sourceType"] for source in matching[0]["sources"]} == {
        "new_mineru",
        "knowledge_clause",
        "visual_extraction",
    }


def test_completeness_names_specific_missing_categories(tmp_path):
    record = build_standard_knowledge_record(canonical_source_fixture(without_references=True), "KF-KB-TEST", tmp_path)
    assert record["completeness"]["normativeReferences"]["status"] == "missing"
    assert record["completeness"]["overall"] == "partial"
    assert "normativeReferences" in record["completeness"]["missingCategories"]
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py -k 'build_record or structure_is_deduplicated or completeness_names'
```

Expected: builder and completeness functions are missing.

- [ ] **Step 3: Implement normalized canonical items**

Use these stable shapes:

```python
CanonicalEvidence = {
    "sourceType": str,
    "sourceId": str,
    "parseResultId": str | None,
    "documentVersionId": str,
    "pageNo": int | None,
    "bbox": list[float] | None,
    "quotedText": str,
    "confidence": float | None,
    "needsHumanVerification": bool,
    "authority": "current" | "legacy_only" | "supporting",
    "contentHash": str,
}


def merge_structured_items(kind: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        identity = structured_identity(kind, item)
        grouped.setdefault(identity, []).append(item)
    return [select_structured_item(kind, identity, values) for identity, values in sorted(grouped.items())]


def structured_identity(kind: str, item: dict[str, Any]) -> str:
    if kind == "clause" and item.get("clauseNo"):
        identity = [item.get("standardCode"), item.get("edition"), item.get("clauseNo")]
    elif kind == "reference":
        identity = [item.get("sourceStandardCode"), item.get("sourceClauseNo"), item.get("targetStandardCode"), item.get("targetClauseNo")]
    else:
        identity = [
            kind,
            item.get("pageNo"),
            normalized_content_hash(item),
            normalize_bbox(item.get("bbox")),
            item.get("sectionPath") if kind == "clause" else None,
        ]
    return canonical_item_id(kind, identity)


def select_structured_item(kind: str, identity: str, values: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(values, key=lambda item: SOURCE_PRIORITY.get(item.get("sourceType"), 0), reverse=True)
    selected = ordered[0]
    authority = "legacy_only" if selected.get("sourceType") == "legacy_ocr" else "current"
    return {
        **canonical_public_content(kind, selected),
        "id": identity,
        "authority": authority,
        "selectedSourceId": selected.get("sourceId"),
        "sources": [canonical_evidence(item, authority="supporting" if item is not selected else authority) for item in ordered],
    }


def normalized_content_hash(item: dict[str, Any]) -> str:
    content = item.get("normalizedRows") or item.get("latex") or item.get("text") or item.get("caption") or ""
    normalized = re.sub(r"\s+", " ", json.dumps(content, ensure_ascii=False, sort_keys=True)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    bbox = [float(part) for part in value[:4]]
    return bbox if bbox[2] > bbox[0] and bbox[3] > bbox[1] else None


def canonical_evidence(item: dict[str, Any], *, authority: str) -> dict[str, Any]:
    return {
        "sourceType": str(item.get("sourceType") or ""),
        "sourceId": str(item.get("sourceId") or ""),
        "parseResultId": item.get("parseResultId"),
        "documentVersionId": str(item.get("documentVersionId") or ""),
        "pageNo": item.get("pageNo"),
        "bbox": normalize_bbox(item.get("bbox")),
        "quotedText": str(item.get("quotedText") or item.get("text") or ""),
        "confidence": item.get("confidence"),
        "needsHumanVerification": bool(item.get("needsHumanVerification")),
        "authority": authority,
        "contentHash": normalized_content_hash(item),
    }


def canonical_public_content(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "title", "text", "clauseNo", "sectionPath", "pageNo", "bbox", "caption",
        "columnNames", "normalizedRows", "cells", "headerReliable", "latex",
        "sourceStandardCode", "sourceClauseNo", "targetStandardCode", "targetClauseNo",
        "nodeIds", "materialTypes", "purpose",
    }
    return {key: copy.deepcopy(value) for key, value in item.items() if key in allowed}
```

Implement `structured_identity` exactly as the spec defines:

- clause: standard code + edition + clause number; fallback section path + normalized text hash + page.
- table/equation/image: block type + page + normalized content hash + normalized bbox.
- reference: source standard code + source clause + target standard code + target clause.

Strip raw table HTML from canonical API-facing tables; retain it only in source provenance. Preserve `normalizedRows`, `cells`, `columnNames` and `headerReliable`.

- [ ] **Step 4: Implement completeness rules**

```python
REQUIRED_CATEGORIES = (
    "identity", "version", "metadata", "fullText", "sections", "clauses",
    "tables", "equations", "images", "seals", "normativeReferences",
    "replacementRelations", "businessRelations", "evidenceLocation", "history",
)


def canonical_completeness(record: dict[str, Any]) -> dict[str, Any]:
    categories = {
        "identity": require_keys(record["identity"], ("standardCode", "standardNameZh")),
        "version": require_keys(record["version"], ("status",)),
        "metadata": require_keys(record["metadata"], ("scope",)),
        "fullText": list_status(record["blocks"]),
        "sections": list_status(record["sections"]),
        "clauses": list_status(record["clauses"]),
        "tables": applicable_list_status(record["tables"], record["provenance"], "table"),
        "equations": applicable_list_status(record["equations"], record["provenance"], "equation"),
        "images": applicable_list_status(record["images"], record["provenance"], "image"),
        "seals": applicable_list_status(record["seals"], record["provenance"], "seal"),
        "normativeReferences": list_status(record["normativeReferences"]),
        "replacementRelations": applicable_list_status(record["replacementRelations"], record["provenance"], "replacement"),
        "businessRelations": list_status(record["businessRelations"]),
        "evidenceLocation": evidence_location_status(record),
        "history": list_status(record["history"]),
    }
    missing = [key for key, item in categories.items() if item["status"] in {"missing", "partial"}]
    return {**categories, "overall": "complete" if not missing else "partial", "missingCategories": missing}


def require_keys(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    missing = [key for key in keys if not str((values.get(key) or {}).get("value") or "").strip()]
    return {"status": "complete" if not missing else "partial", "missing": missing}


def list_status(values: list[Any]) -> dict[str, Any]:
    return {"status": "complete" if values else "missing", "count": len(values)}


def applicable_list_status(values: list[Any], provenance: list[dict[str, Any]], capability: str) -> dict[str, Any]:
    attempted = any(capability in set(item.get("capabilities") or []) for item in provenance)
    if values:
        return {"status": "complete", "count": len(values)}
    return {"status": "missing" if attempted else "not_applicable", "count": 0}


def evidence_location_status(record: dict[str, Any]) -> dict[str, Any]:
    items = [
        *record.get("clauses", []), *record.get("tables", []), *record.get("equations", []),
        *record.get("images", []), *record.get("seals", []),
    ]
    if not items:
        return {"status": "missing", "located": 0, "total": 0}
    located = len([item for item in items if item.get("pageNo") and (item.get("bbox") or item.get("locatorIds"))])
    return {"status": "complete" if located == len(items) else "partial", "located": located, "total": len(items)}
```

- [ ] **Step 5: Verify all builder tests**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add backend/libs/standard_knowledge_canonical.py backend/tests/test_standard_knowledge_canonical.py
git commit -m "feat: build complete canonical standard records"
```

---

### Task 4: Dry-run、幂等迁移与完整度验证器

**Files:**
- Create: `backend/scripts/rebuild_standard_knowledge_canonical.py`
- Create: `backend/scripts/verify_standard_knowledge_canonical.py`
- Create: `backend/tests/test_standard_knowledge_canonical_migration.py`

**Interfaces:**
- Consumes: `build_standard_knowledge_record` from Task 3.
- Produces CLI: `rebuild_standard_knowledge_canonical.py --database-url URL [--dry-run|--apply] [--file-id ID] [--output PATH]`
- Produces CLI: `verify_standard_knowledge_canonical.py --database-url URL --require-count 59 --json`
- Produces: `persist_canonical_record(connection, tenant_id: str, record: dict[str, Any]) -> Literal["inserted", "updated", "unchanged"]`

Define migration test helpers in `backend/tests/test_standard_knowledge_canonical_migration.py`:

```python
def run_rebuild(database_url: str, *args: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BACKEND_ROOT / "scripts/rebuild_standard_knowledge_canonical.py"),
        "--database-url", database_url,
        "--json",
        *args,
    ]
    completed = subprocess.run(command, cwd=BACKEND_ROOT, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def count_collection(database_url: str, collection: str) -> int:
    with psycopg.connect(database_url) as connection:
        return int(connection.execute(
            "SELECT count(*) FROM aicheck_state WHERE tenant_id=%s AND collection=%s",
            ("TENANT-DEFAULT", collection),
        ).fetchone()[0])


def seed_standard_fixture(database_url: str, *, count: int) -> None:
    records = canonical_postgres_fixture_records(count=count)
    with psycopg.connect(database_url, autocommit=False) as connection:
        for collection, object_id, payload in records:
            connection.execute(
                "INSERT INTO aicheck_state (tenant_id,collection,object_id,payload,updated_at) VALUES (%s,%s,%s,%s,now())",
                ("TENANT-DEFAULT", collection, object_id, Jsonb(payload)),
            )
        connection.commit()


def canonical_postgres_fixture_records(*, count: int) -> list[tuple[str, str, dict[str, Any]]]:
    records = []
    for index in range(1, count + 1):
        suffix = f"{index:03d}"
        file_id, document_id, version_id = f"KF-KB-{suffix}", f"KDOC-{suffix}", f"KDV-{suffix}-V1"
        records.extend(
            [
                ("knowledge_files", file_id, {"id": file_id, "sourceId": "KS-STANDARD-RULES", "sourceType": "standard", "documentId": document_id, "documentVersionId": version_id, "fileName": f"STD-{suffix}.pdf", "sourceRelativePath": f"rules/standards/STD-{suffix}.pdf", "tenantId": "TENANT-DEFAULT"}),
                ("documents", document_id, {"id": document_id, "currentVersionId": version_id, "tenantId": "TENANT-DEFAULT"}),
                ("document_versions", version_id, {"id": version_id, "documentId": document_id, "isCurrent": True, "tenantId": "TENANT-DEFAULT"}),
                ("ocr_parse_results", f"PARSE-{suffix}", {"id": f"PARSE-{suffix}", "parseResultId": f"PARSE-{suffix}", "documentId": document_id, "documentVersionId": version_id, "metadata": {"sidecarImported": True}, "fields": [{"fieldName": "标准编号", "fieldValue": f"STD-{suffix}"}], "layoutBlocks": [{"blockId": f"B-{suffix}", "blockType": "text", "text": "1 范围", "pageNo": 1}], "tables": [], "seals": [], "pages": [{"pageNo": 1}], "tenantId": "TENANT-DEFAULT"}),
            ]
        )
    return records


SOURCE_COLLECTIONS = (
    "knowledge_files", "documents", "document_versions", "ocr_parse_results",
    "extracted_fields", "evidence_links", "knowledge_chunks", "knowledge_clauses",
    "knowledge_page_index_nodes", "standard_document_versions",
    "standard_clause_references", "standard_clause_locators", "rule_versions",
)


def source_collection_digests(database_url: str) -> dict[str, str]:
    with psycopg.connect(database_url) as connection:
        return {
            collection: str(connection.execute(
                """
                SELECT md5(coalesce(string_agg(object_id || payload::text, '' ORDER BY object_id), ''))
                FROM aicheck_state WHERE tenant_id=%s AND collection=%s
                """,
                ("TENANT-DEFAULT", collection),
            ).fetchone()[0])
            for collection in SOURCE_COLLECTIONS
        }


def seed_valid_canonical(database_url: str, *, file_id: str, fingerprint: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        connection.execute(
            "INSERT INTO aicheck_state (tenant_id,collection,object_id,payload,updated_at) VALUES (%s,'standard_knowledge_records',%s,%s,now())",
            (
                "TENANT-DEFAULT",
                file_id,
                Jsonb({"id": f"SKR-{file_id}", "knowledgeFileId": file_id, "canonicalVersion": "standard-knowledge-canonical@1", "sourceFingerprint": fingerprint}),
            ),
        )
        connection.commit()


def seed_broken_standard_source(database_url: str, *, file_id: str) -> None:
    with psycopg.connect(database_url, autocommit=False) as connection:
        file_payload = connection.execute(
            "SELECT payload FROM aicheck_state WHERE tenant_id=%s AND collection='knowledge_files' AND object_id=%s FOR UPDATE",
            ("TENANT-DEFAULT", file_id),
        ).fetchone()[0]
        document_id = file_payload["documentId"]
        document_payload = connection.execute(
            "SELECT payload FROM aicheck_state WHERE tenant_id=%s AND collection='documents' AND object_id=%s FOR UPDATE",
            ("TENANT-DEFAULT", document_id),
        ).fetchone()[0]
        document_payload["currentVersionId"] = "KDV-MISSING"
        connection.execute(
            "UPDATE aicheck_state SET payload=%s,updated_at=now() WHERE tenant_id=%s AND collection='documents' AND object_id=%s",
            (Jsonb(document_payload), "TENANT-DEFAULT", document_id),
        )
        connection.commit()


def canonical_record(database_url: str, file_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url) as connection:
        return dict(connection.execute(
            "SELECT payload FROM aicheck_state WHERE tenant_id=%s AND collection='standard_knowledge_records' AND object_id=%s",
            ("TENANT-DEFAULT", file_id),
        ).fetchone()[0])
```

`source_collection_digests` must hash, in object-ID order, the JSONB payload of every source collection listed in the spec. It must exclude only `standard_knowledge_records`.

- [ ] **Step 1: Write migration safety tests**

```python
def test_dry_run_writes_nothing_and_reports_all_records(isolated_postgres_url, tmp_path):
    seed_standard_fixture(isolated_postgres_url, count=2)
    report = run_rebuild(isolated_postgres_url, "--dry-run", "--output", str(tmp_path / "report.json"))
    assert report["processed"] == 2
    assert report["written"] == 0
    assert count_collection(isolated_postgres_url, "standard_knowledge_records") == 0


def test_apply_is_idempotent_and_preserves_source_digests(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=2)
    before = source_collection_digests(isolated_postgres_url)
    first = run_rebuild(isolated_postgres_url, "--apply")
    second = run_rebuild(isolated_postgres_url, "--apply")
    assert first["inserted"] == 2
    assert second["unchanged"] == 2
    assert count_collection(isolated_postgres_url, "standard_knowledge_records") == 2
    assert source_collection_digests(isolated_postgres_url) == before


def test_failed_record_does_not_replace_previous_valid_record(isolated_postgres_url):
    seed_standard_fixture(isolated_postgres_url, count=1)
    seed_valid_canonical(isolated_postgres_url, file_id="KF-KB-001", fingerprint="sha256:good")
    seed_broken_standard_source(isolated_postgres_url, file_id="KF-KB-001")
    report = run_rebuild(isolated_postgres_url, "--apply", "--file-id", "KF-KB-001")
    assert report["failed"] == 1
    assert canonical_record(isolated_postgres_url, "KF-KB-001")["sourceFingerprint"] == "sha256:good"
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical_migration.py
```

Expected: scripts or helpers are missing.

- [ ] **Step 3: Implement locked, scoped upsert**

```python
def persist_canonical_record(connection, tenant_id: str, record: dict[str, Any]) -> str:
    row = connection.execute(
        """
        SELECT payload FROM aicheck_state
        WHERE tenant_id=%s AND collection='standard_knowledge_records' AND object_id=%s
        FOR UPDATE
        """,
        (tenant_id, record["knowledgeFileId"]),
    ).fetchone()
    previous = dict(row[0]) if row else None
    if previous and previous.get("sourceFingerprint") == record["sourceFingerprint"]:
        return "unchanged"
    connection.execute(
        """
        INSERT INTO aicheck_state (tenant_id, collection, object_id, payload, updated_at)
        VALUES (%s, 'standard_knowledge_records', %s, %s, now())
        ON CONFLICT (tenant_id, collection, object_id)
        DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()
        """,
        (tenant_id, record["knowledgeFileId"], Jsonb(record)),
    )
    return "updated" if previous else "inserted"
```

Use `configured_tenant_id()` as authoritative tenant. Before each record, verify file/document/current-version links inside the same transaction. Commit each standard independently so one failure does not roll back successful siblings.

- [ ] **Step 4: Implement verifier gates**

The verifier must fail nonzero unless all conditions hold:

```python
assertions = {
    "canonical_count": actual_count == args.require_count,
    "mineru_coverage": mineru_covered == 58,
    "context_only_count": context_only_count == 1,
    "duplicate_ids": duplicate_ids == 0,
    "missing_provenance": missing_provenance == 0,
    "unmapped_sources": unmapped_sources == 0,
    "source_digest_unchanged": before_digests == after_digests,
}
```

Output per-standard missing categories and an aggregate coverage matrix in JSON.

- [ ] **Step 5: Run migration tests and verifier fixture**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical_migration.py
python scripts/verify_standard_knowledge_canonical.py --database-url "$AICHECK_TEST_POSTGRES_URL" --require-count 2 --json
```

Expected: tests pass; fixture verifier reports all gates true.

- [ ] **Step 6: Commit Task 4**

```bash
git add backend/scripts/rebuild_standard_knowledge_canonical.py backend/scripts/verify_standard_knowledge_canonical.py backend/tests/test_standard_knowledge_canonical_migration.py
git commit -m "feat: add safe canonical standard migration"
```

---

### Task 5: Canonical API 与旧详情兼容

**Files:**
- Modify: `backend/apps/api/knowledge_admin_routes.py:724-758`
- Modify: `backend/tests/test_contract.py`
- Modify: `frontend/src/api/aicheck/index.ts:344-366,1085-1089,4254-4260`

**Interfaces:**
- Consumes: `standard_knowledge_records` from Task 4.
- Produces: `GET /api/knowledge/files/{file_id}/canonical`
- Produces: `GET /api/knowledge/files/{file_id}/canonical/sources/{source_id}`
- Extends `KnowledgeFileDetailPayload` with `canonical`, `canonicalSummary`, `activeParseResultId`, `completeness`.
- Preserves `ocrStructured`, `extractedFields`, `evidenceLinks`, preview and download fields.

Define this fixture in the contract test module:

```python
def canonical_record_fixture(file_id: str = "KF-KB-TEST") -> dict[str, Any]:
    return {
        "id": f"SKR-{file_id}",
        "knowledgeFileId": file_id,
        "documentId": "KDOC-TEST",
        "documentVersionId": "KDV-TEST-V1",
        "canonicalVersion": "standard-knowledge-canonical@1",
        "identity": {"standardCode": {"id": "SKI-FIELD-CODE", "key": "standardCode", "value": "NB/T 47013.10-2015", "authority": "current", "selectedSourceId": "PARSE-NEW", "sources": []}},
        "version": {}, "metadata": {}, "sections": [], "clauses": [], "blocks": [],
        "tables": [], "equations": [], "images": [], "seals": [],
        "normativeReferences": [], "replacementRelations": [], "businessRelations": [],
        "evidence": [], "provenance": [],
        "completeness": {"overall": "complete", "missingCategories": []},
        "history": [{"sourceId": "PARSE-OLD", "sourceType": "legacy_ocr", "authority": "legacy_only"}],
        "activeParseResultId": "PARSE-NEW",
        "sourceFingerprint": "sha256:test",
    }


def seed_canonical_record(file_id: str = "KF-KB-TEST") -> None:
    repo.state.setdefault("standard_knowledge_records", []).append(canonical_record_fixture(file_id))
```

- [ ] **Step 1: Write API contract tests**

```python
def test_standard_canonical_endpoint_returns_complete_record():
    seed_canonical_record("KF-KB-TEST")
    data = assert_ok(client.get("/api/knowledge/files/KF-KB-TEST/canonical"))
    assert data["knowledgeFileId"] == "KF-KB-TEST"
    assert data["canonicalVersion"] == "standard-knowledge-canonical@1"
    assert data["identity"]["standardCode"]["value"] == "NB/T 47013.10-2015"


def test_file_detail_exposes_canonical_and_keeps_ocr_structured():
    seed_canonical_record("KF-KB-TEST")
    data = assert_ok(client.get("/api/knowledge/files/KF-KB-TEST"))
    assert data["canonical"]["knowledgeFileId"] == "KF-KB-TEST"
    assert "blocks" not in data["canonical"]
    assert data["canonicalSummary"]["overall"] == "complete"
    assert data["activeParseResultId"] == "PARSE-NEW"
    assert "ocrStructured" in data


def test_canonical_source_endpoint_is_read_only_and_scoped():
    seed_canonical_record("KF-KB-TEST")
    source = assert_ok(client.get("/api/knowledge/files/KF-KB-TEST/canonical/sources/PARSE-OLD"))
    assert source["sourceId"] == "PARSE-OLD"
    assert source["authority"] == "legacy_only"
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_contract.py -k 'standard_canonical_endpoint or file_detail_exposes_canonical or canonical_source_endpoint'
```

Expected: 404 or missing canonical fields.

- [ ] **Step 3: Implement API reads**

```python
def standard_canonical_for_file(request: Request, file_id: str) -> dict[str, Any] | None:
    resolved = resolve_knowledge_file_id(file_id)
    file = repo.find_one("knowledge_files", resolved)
    if not file or file.get("sourceType") != "standard":
        return None
    scope_error = scope_error_for_record(request, file)
    if scope_error:
        raise CanonicalScopeError(scope_error)
    return repo.find_one("standard_knowledge_records", resolved)
```

Return `NOT_FOUND` when canonical is absent; do not silently build inside GET. Add `includeBlocks`, `includeHistory`, `section` and `pageNo` filtering without mutating stored payload.

The main file-detail response must keep `canonical` bounded to identity, version, metadata, relation counts, completeness, history summary, `canonicalVersion`, `kbVersion` and `sourceFingerprint`. It must omit full `blocks`, `clauses`, `tables`, `equations`, `images`, `seals` and provenance arrays. Those arrays are fetched from the dedicated canonical endpoint only when the corresponding UI section opens.

- [ ] **Step 4: Add frontend types and API methods**

```ts
export type StandardCanonicalField = {
  id: string
  key: string
  value: unknown
  authority: 'current' | 'legacy_only'
  selectedSourceId: string
  sources: StandardCanonicalEvidence[]
}

export type StandardCanonicalEvidence = {
  sourceType: string
  sourceId: string
  parseResultId?: string
  documentVersionId: string
  pageNo?: number
  bbox?: number[] | null
  quotedText?: string
  value?: unknown
  confidence?: number
  needsHumanVerification: boolean
  authority: 'current' | 'legacy_only' | 'supporting'
  contentHash: string
}

export type StandardCanonicalContentItem = {
  id: string
  title?: string
  text?: string
  clauseNo?: string
  pageNo?: number
  bbox?: number[] | null
  authority: 'current' | 'legacy_only'
  sources: StandardCanonicalEvidence[]
}

export type StandardCanonicalRelation = StandardCanonicalContentItem & {
  sourceStandardCode?: string
  targetStandardCode?: string
  nodeIds?: number[]
}

export type StandardCanonicalCompleteness = {
  overall: 'complete' | 'partial'
  missingCategories: string[]
  [category: string]: unknown
}

export type StandardCanonicalHistory = {
  sourceId: string
  sourceType: string
  createdAt?: string
  fieldCount: number
  blockCount: number
  tableCount: number
  sealCount: number
}

export type StandardKnowledgeRecord = {
  id: string
  knowledgeFileId: string
  canonicalVersion: string
  identity: Record<string, StandardCanonicalField>
  version: Record<string, StandardCanonicalField>
  metadata: Record<string, StandardCanonicalField>
  sections: StandardCanonicalContentItem[]
  clauses: StandardCanonicalContentItem[]
  blocks: OcrLayoutBlock[]
  tables: OcrStructuredTable[]
  equations: StandardCanonicalContentItem[]
  images: StandardCanonicalContentItem[]
  seals: OcrSealItem[]
  normativeReferences: StandardCanonicalRelation[]
  replacementRelations: StandardCanonicalRelation[]
  businessRelations: StandardCanonicalRelation[]
  completeness: StandardCanonicalCompleteness
  provenance: StandardCanonicalEvidence[]
  history: StandardCanonicalHistory[]
}
```

Add `getKnowledgeFileCanonicalApi(fileId, params)` and `getKnowledgeFileCanonicalSourceApi(fileId, sourceId)`.

- [ ] **Step 5: Run backend and TypeScript checks**

```bash
cd backend && source .venv/bin/activate && pytest -q tests/test_contract.py -k 'canonical'
cd ../frontend && pnpm run ts:check
```

Expected: all pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add backend/apps/api/knowledge_admin_routes.py backend/tests/test_contract.py frontend/src/api/aicheck/index.ts
git commit -m "feat: expose canonical standard knowledge API"
```

---

### Task 6: 标准详情全集展示

**Files:**
- Create: `frontend/src/views/AICheck/components/StandardCanonicalDetail.vue`
- Create: `frontend/src/views/AICheck/components/standardCanonicalPresentation.ts`
- Create: `frontend/src/views/AICheck/standardCanonicalDetail.test.ts`
- Modify: `frontend/src/views/AICheck/components/FileDetailDialog.vue:684-990`
- Modify: `frontend/src/views/AICheck/KnowledgeOverview.vue:2460-2513`

**Interfaces:**
- Consumes: `StandardKnowledgeRecord` from Task 5.
- Produces component props: `{ record: StandardKnowledgeRecord; onLocate: (evidence) => void }`
- Produces tabs: `概览`, `章节条款`, `表格公式`, `引用关系`, `完整度`, `来源历史`.
- Keeps the existing project-document field UI for non-standard documents.
- Loads the bounded detail record first and calls `getKnowledgeFileCanonicalApi` lazily for `章节条款`, `表格公式`, `引用关系` and `来源历史` sections.

- [ ] **Step 1: Write display-behavior tests**

```ts
import assert from 'node:assert/strict'
import {
  canonicalOverviewRows,
  canonicalWarningMessages,
  visibleCanonicalSourceValues
} from './components/standardCanonicalPresentation'

const record = canonicalFixture()

assert.deepEqual(canonicalOverviewRows(record).map((row) => row.label), [
  '标准编号', '标准名称', '发布日期', '实施日期', '发布机构', '状态'
])
assert.equal(canonicalOverviewRows(record)[2].value, '2015-04-02')
assert.deepEqual(canonicalWarningMessages(record), ['缺少规范性引用关系'])
assert.deepEqual(
  visibleCanonicalSourceValues(record.identity.standardCode),
  [
    { value: 'NB/T 47013.10-2015', sourceType: 'new_mineru', selected: true },
    { value: 'NB/T 47013.10-2010', sourceType: 'legacy_ocr', selected: false }
  ]
)
```

Add a source-text regression assertion that standard mode does not render the project-document warning `没有识别出证书编号、设计压力`.

- [ ] **Step 2: Verify RED**

```bash
cd frontend
pnpm run test:unit
```

Expected: presentation module or component is missing.

- [ ] **Step 3: Implement presentation helpers and component**

Create `frontend/src/views/AICheck/components/standardCanonicalPresentation.ts` with pure helpers:

```ts
export const CANONICAL_WARNING_COPY: Record<string, string> = {
  identity: '标准编号或标准名称不完整',
  version: '标准版本信息不完整',
  metadata: '标准适用范围等元数据不完整',
  fullText: '标准全文结构不完整',
  sections: '章节结构不完整',
  clauses: '条款结构不完整',
  tables: '表格结构不完整',
  equations: '公式结构不完整',
  images: '图片信息不完整',
  seals: '印章信息不完整',
  normativeReferences: '缺少规范性引用关系',
  replacementRelations: '标准替代关系不完整',
  businessRelations: '关联业务规则或监检节点不完整',
  evidenceLocation: '部分信息无法定位原文',
  history: '历史识别来源不完整'
}

export const canonicalOverviewRows = (record: StandardKnowledgeRecord) => [
  { label: '标准编号', value: String(record.identity.standardCode?.value ?? '-') },
  { label: '标准名称', value: String(record.identity.standardNameZh?.value ?? '-') },
  { label: '发布日期', value: String(record.version.publicationDate?.value ?? '-') },
  { label: '实施日期', value: String(record.version.effectiveDate?.value ?? '-') },
  { label: '发布机构', value: String(record.version.issuingAuthority?.value ?? '-') },
  { label: '状态', value: String(record.version.status?.value ?? '-') }
]

export const canonicalWarningMessages = (record: StandardKnowledgeRecord): string[] =>
  record.completeness.missingCategories.map((key) => CANONICAL_WARNING_COPY[key])

export const visibleCanonicalSourceValues = (field: StandardCanonicalField) =>
  field.sources.map((source) => ({
    value: String(source.value ?? ''),
    sourceType: source.sourceType,
    selected: source.sourceId === field.selectedSourceId
  }))
```

`StandardCanonicalDetail.vue` must:

- render selected new value in the main row;
- show `legacy_only` badge only for old-only current fields;
- keep conflicting old values inside a collapsed source panel;
- render normalized tables without `v-html`;
- render equations with existing KaTeX utilities;
- emit evidence on field, clause, table, equation, image and seal clicks;
- list completeness categories and exact missing reason;
- lazy-load source history through the API.

- [ ] **Step 4: Integrate into FileDetailDialog**

```vue
<StandardCanonicalDetail
  v-if="detail?.canonical && document.materialTypeCode === 'standard_reference'"
  :record="detail.canonical"
  @locate="handleCanonicalLocate"
/>
<template v-else>
  <!-- existing project-document OCR field presentation -->
</template>
```

Map canonical evidence to the existing `activeLocatable` shape, preserving PDF page jump and image bbox highlighting.

- [ ] **Step 5: Run frontend verification**

```bash
cd frontend
pnpm run test:unit
pnpm run ts:check
pnpm exec eslint src/views/AICheck/components/StandardCanonicalDetail.vue src/views/AICheck/components/standardCanonicalPresentation.ts src/views/AICheck/components/FileDetailDialog.vue
pnpm run build:pro
```

Expected: tests, typecheck, lint and production build pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add frontend/src/views/AICheck/components/StandardCanonicalDetail.vue frontend/src/views/AICheck/components/standardCanonicalPresentation.ts frontend/src/views/AICheck/standardCanonicalDetail.test.ts frontend/src/views/AICheck/components/FileDetailDialog.vue frontend/src/views/AICheck/KnowledgeOverview.vue
git commit -m "feat: display complete canonical standard details"
```

---

### Task 7: Canonical 检索候选与旧内容降权

**Files:**
- Modify: `backend/libs/knowledge_retrieval.py:519-620,884-950`
- Create: `backend/tests/test_standard_canonical_retrieval.py`

**Interfaces:**
- Consumes: canonical clauses, tables, equations and references from Task 3.
- Produces: `canonical_clause_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]`
- Extends normalized clause fields: `canonicalRecordId`, `canonicalItemId`, `canonicalVersion`, `sourceFingerprint`, `authority`, `sourceIds`.
- `knowledge_clause_candidates` prefers canonical candidates for standard files and keeps old candidates only when no canonical record exists.

Define retrieval fixtures in `backend/tests/test_standard_canonical_retrieval.py`:

```python
def retrieval_state_with_canonical_conflict() -> dict[str, Any]:
    return {
        "standard_knowledge_records": [{
            "id": "SKR-KF-KB-TEST", "knowledgeFileId": "KF-KB-TEST",
            "canonicalVersion": "standard-knowledge-canonical@1", "sourceFingerprint": "sha256:test",
            "clauses": [{"id": "SKI-CLAUSE-1", "text": "发布日期 2015-04-02", "authority": "current", "pageNo": 1, "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}]}],
            "tables": [], "equations": [],
        }],
        "knowledge_files": [{"id": "KF-KB-TEST", "sourceType": "standard", "documentVersionId": "KDV-TEST-V1"}],
        "knowledge_clauses": [{"id": "KC-OLD", "fileId": "KF-KB-TEST", "text": "发布日期 2014-01-01"}],
        "knowledge_sources": [],
    }


def retrieval_state_with_legacy_only_clause() -> dict[str, Any]:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"][0]["clauses"] = [{"id": "SKI-CLAUSE-OLD", "text": "备案号 61188-2018", "authority": "legacy_only", "pageNo": 1, "sources": [{"sourceId": "PARSE-OLD", "sourceType": "legacy_ocr"}]}]
    return state


def retrieval_state_with_canonical_and_old_chunks() -> dict[str, Any]:
    state = retrieval_state_with_canonical_conflict()
    state["knowledge_chunks"] = [{"id": "CHK-OLD", "fileId": "KF-KB-TEST", "text": "发布日期 2014-01-01"}]
    return state
```

- [ ] **Step 1: Write retrieval tests**

```python
def test_canonical_current_value_is_retrieved_and_old_conflict_is_not():
    state = retrieval_state_with_canonical_conflict()
    candidates = canonical_clause_candidates(state)
    texts = [item["text"] for item in candidates]
    assert "2015-04-02" in "\n".join(texts)
    assert "2014-01-01" not in "\n".join(texts)


def test_legacy_only_information_is_retrievable_with_lower_weight():
    state = retrieval_state_with_legacy_only_clause()
    item = next(x for x in canonical_clause_candidates(state) if x["authority"] == "legacy_only")
    assert item["retrievalWeightTier"] == "legacy_supplemental"
    assert item["formalEvidenceEligible"] is False


def test_standard_candidates_are_not_duplicated_when_canonical_exists():
    state = retrieval_state_with_canonical_and_old_chunks()
    candidates = knowledge_clause_candidates(state)
    ids = [item["canonicalItemId"] for item in candidates if item.get("canonicalItemId")]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_canonical_retrieval.py
```

Expected: canonical retrieval functions are missing or old conflicting text is present.

- [ ] **Step 3: Implement canonical candidate projection**

```python
def canonical_clause_candidates(state: dict[str, Any], *, kb_version: str | None = None) -> list[dict[str, Any]]:
    candidates = []
    for record in state.get("standard_knowledge_records", []):
        if kb_version and record.get("kbVersion") != kb_version:
            continue
        for item in [*record.get("clauses", []), *record.get("tables", []), *record.get("equations", [])]:
            authority = str(item.get("authority") or "current")
            candidates.append(
                normalize_clause(
                    {
                        **item,
                        "canonicalRecordId": record["id"],
                        "canonicalItemId": item["id"],
                        "canonicalVersion": record["canonicalVersion"],
                        "sourceFingerprint": record["sourceFingerprint"],
                        "authority": authority,
                        "retrievalWeightTier": "legacy_supplemental" if authority == "legacy_only" else "canonical_current",
                        "formalEvidenceEligible": authority != "legacy_only" and bool(item.get("pageNo") or item.get("locatorIds")),
                    }
                )
            )
    return candidates
```

Exclude old standard `knowledge_chunks/knowledge_clauses` for file IDs that already have canonical records; retain project-file candidates unchanged.

- [ ] **Step 4: Run retrieval regression suite**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_canonical_retrieval.py tests/test_knowledge_structured_blocks.py tests/test_knowledge_indexing.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 7**

```bash
git add backend/libs/knowledge_retrieval.py backend/tests/test_standard_canonical_retrieval.py
git commit -m "feat: retrieve canonical standard knowledge"
```

---

### Task 8: AI 审查记录 canonical 来源版本

**Files:**
- Modify: `backend/libs/review_orchestrator/execution.py:2320-2500`
- Modify: `backend/libs/review_grounding.py`
- Create: `backend/tests/test_standard_canonical_review_grounding.py`

**Interfaces:**
- Consumes canonical fields added to retrieval clauses in Task 7.
- Produces AI grounding metadata: `canonicalRecordIds`, `canonicalItemIds`, `canonicalVersions`, `canonicalSourceFingerprints`, `legacySupplementalCount`.
- Formal conclusions must reject `legacy_only` as sole evidence.

Define review fixtures in `backend/tests/test_standard_canonical_review_grounding.py`:

```python
def canonical_review_fixture() -> list[dict[str, Any]]:
    return [{
        "id": "CLAUSE-CURRENT", "text": "当前条款", "authority": "current",
        "canonicalRecordId": "SKR-KF-KB-TEST", "canonicalItemId": "SKI-CLAUSE-ABC",
        "canonicalVersion": "standard-knowledge-canonical@1",
        "sourceFingerprint": "sha256:test", "pageNo": 7,
    }]


def legacy_only_review_fixture() -> list[dict[str, Any]]:
    return [{
        "id": "CLAUSE-LEGACY", "text": "旧独有补充", "authority": "legacy_only",
        "canonicalRecordId": "SKR-KF-KB-TEST", "canonicalItemId": "SKI-CLAUSE-OLD",
        "canonicalVersion": "standard-knowledge-canonical@1",
        "sourceFingerprint": "sha256:test", "pageNo": 1,
    }]
```

- [ ] **Step 1: Write grounding and formal-evidence tests**

```python
def test_review_grounding_records_canonical_versions_and_items():
    grounded = canonical_grounding_metadata(canonical_review_fixture())
    assert grounded["canonicalRecordIds"] == ["SKR-KF-KB-TEST"]
    assert grounded["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert grounded["canonicalVersions"] == ["standard-knowledge-canonical@1"]
    assert grounded["canonicalSourceFingerprints"] == ["sha256:test"]


def test_legacy_only_cannot_be_the_only_formal_evidence():
    grounded = canonical_grounding_metadata(legacy_only_review_fixture())
    assert grounded["formalEvidenceReady"] is False
    assert grounded["blockingReasons"] == ["CANONICAL_LEGACY_ONLY_EVIDENCE"]
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_canonical_review_grounding.py
```

Expected: provenance keys or blocking reason are missing.

- [ ] **Step 3: Implement provenance aggregation**

```python
def canonical_grounding_metadata(clauses: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = [item for item in clauses if item.get("canonicalRecordId")]
    legacy = [item for item in canonical if item.get("authority") == "legacy_only"]
    current = [item for item in canonical if item.get("authority") != "legacy_only"]
    return {
        "canonicalRecordIds": sorted({item["canonicalRecordId"] for item in canonical}),
        "canonicalItemIds": sorted({item["canonicalItemId"] for item in canonical}),
        "canonicalVersions": sorted({item["canonicalVersion"] for item in canonical}),
        "canonicalSourceFingerprints": sorted({item["sourceFingerprint"] for item in canonical}),
        "legacySupplementalCount": len(legacy),
        "formalEvidenceReady": bool(current),
        "blockingReasons": [] if current or not legacy else ["CANONICAL_LEGACY_ONLY_EVIDENCE"],
    }
```

Persist this metadata into retrieval traces and review run input summaries. Do not place full standard text into Temporal workflow history.

- [ ] **Step 4: Run review regression tests**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_canonical_review_grounding.py tests/test_review_grounding.py tests/test_review_runtime_tool_dispatcher.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 8**

```bash
git add backend/libs/review_orchestrator/execution.py backend/libs/review_grounding.py backend/tests/test_standard_canonical_review_grounding.py
git commit -m "feat: trace canonical standards in AI review"
```

---

### Task 9: 标准语义专项补齐

**Files:**
- Modify: `backend/libs/standard_knowledge_canonical.py`
- Create: `backend/libs/standard_semantic_extraction.py`
- Create: `backend/config/standard_canonical_extraction_v1.json`
- Create: `backend/scripts/enrich_standard_knowledge_canonical.py`
- Create: `backend/tests/test_standard_semantic_extraction.py`

**Interfaces:**
- Consumes canonical records from Task 3 and `LiteLLMClient.chat_sync`.
- Produces: `extract_deterministic_standard_metadata(record: dict[str, Any]) -> dict[str, list[dict[str, Any]]]`
- Produces: `extract_standard_semantics(record: dict[str, Any], client: LiteLLMClient) -> dict[str, Any]`
- Produces CLI: `enrich_standard_knowledge_canonical.py --database-url URL [--dry-run|--apply] [--file-id ID] [--only-missing] --output PATH`
- Adds source type `new_mineru_semantic`, priority 550, with prompt version `standard-canonical-extraction-v1`.

- [ ] **Step 1: Write deterministic and model-response tests**

```python
def test_deterministic_metadata_extracts_code_dates_authority_and_replacement():
    record = semantic_record_fixture(
        text=(
            "中华人民共和国能源行业标准 NB/T 47013.10-2015 承压设备无损检测 第10部分。"
            "发布日期：2015-04-02；实施日期：2015-09-01；发布机构：国家能源局。"
            "代替 NB/T 47013.10-2010。"
        )
    )
    extracted = extract_deterministic_standard_metadata(record)
    assert extracted["standardCode"][0]["value"] == "NB/T 47013.10-2015"
    assert extracted["publicationDate"][0]["value"] == "2015-04-02"
    assert extracted["effectiveDate"][0]["value"] == "2015-09-01"
    assert extracted["issuingAuthority"][0]["value"] == "国家能源局"
    assert extracted["replaces"][0]["value"] == "NB/T 47013.10-2010"


def test_model_semantics_are_schema_validated_and_evidence_grounded():
    client = FakeLiteLLMClient(
        {
            "standardNameZh": "承压设备无损检测 第10部分：衍射时差法超声检测",
            "scope": {"value": "适用于12mm至400mm低碳钢或低合金钢全焊透对接接头。", "pageNo": 7, "quotedText": "适用于低碳钢或低合金钢材料"},
            "normativeReferences": [{"standardCode": "NB/T 47013.3", "clauseNo": "", "pageNo": 7, "quotedText": "按NB/T 47013.3检测"}],
            "replacementRelations": [{"relation": "replaces", "standardCode": "NB/T 47013.10-2010", "pageNo": 1, "quotedText": "代替NB/T 47013.10-2010"}],
        }
    )
    extracted = extract_standard_semantics(semantic_record_fixture(text="标准正文"), client)
    assert extracted["promptVersion"] == "standard-canonical-extraction-v1"
    assert extracted["scope"]["pageNo"] == 7
    assert extracted["normativeReferences"][0]["sourceType"] == "new_mineru_semantic"
    assert extracted["normativeReferences"][0]["quotedText"] == "按NB/T 47013.3检测"


def test_ungrounded_model_item_is_rejected():
    client = FakeLiteLLMClient({"normativeReferences": [{"standardCode": "GB/T 99999"}]})
    with pytest.raises(ValueError, match="pageNo and quotedText are required"):
        extract_standard_semantics(semantic_record_fixture(text="标准正文"), client)
```

Define the external-boundary fake and canonical fixture in the test module:

```python
class FakeLiteLLMClient:
    def __init__(self, content: dict[str, Any]) -> None:
        self.content = content

    def chat_sync(self, messages, model="review-chat", **kwargs):
        return {"choices": [{"message": {"content": json.dumps(self.content, ensure_ascii=False)}}]}

    @staticmethod
    def first_message_text(response):
        return str(response["choices"][0]["message"]["content"])


def semantic_record_fixture(*, text: str) -> dict[str, Any]:
    return {
        "id": "SKR-KF-KB-TEST", "knowledgeFileId": "KF-KB-TEST",
        "documentVersionId": "KDV-TEST-V1", "canonicalVersion": "standard-knowledge-canonical@1",
        "identity": {}, "version": {}, "metadata": {},
        "blocks": [{"id": "B-1", "text": text, "pageNo": 1, "authority": "current", "sources": [{"sourceType": "new_mineru", "sourceId": "PARSE-NEW"}]}],
        "clauses": [], "tables": [], "equations": [], "images": [], "seals": [],
        "normativeReferences": [], "replacementRelations": [], "businessRelations": [],
        "evidence": [], "provenance": [], "history": [],
        "completeness": {"overall": "partial", "missingCategories": ["version", "metadata", "normativeReferences"]},
        "sourceFingerprint": "sha256:test",
    }
```

- [ ] **Step 2: Verify RED**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_semantic_extraction.py
```

Expected: semantic extraction module is missing.

- [ ] **Step 3: Add strict extraction schema**

Create `backend/config/standard_canonical_extraction_v1.json`:

```json
{
  "schemaVersion": "standard-canonical-extraction-v1",
  "required": [
    "standardCode", "standardNameZh", "standardNameEn", "publicationDate",
    "effectiveDate", "issuingAuthority", "proposingOrganization",
    "administeringOrganization", "draftingOrganizations", "draftingPeople",
    "scope", "purpose", "applicability", "keywords", "abstract", "foreword",
    "introduction", "termsAndDefinitionsSummary", "normativeReferences",
    "replacementRelations"
  ],
  "evidenceRequired": [
    "standardCode", "publicationDate", "effectiveDate", "issuingAuthority",
    "scope", "normativeReferences", "replacementRelations"
  ]
}
```

Validate every evidence-required value has `pageNo` and `quotedText`, and verify `quotedText` is a normalized substring of the selected page text. Reject unsupported values instead of storing ungrounded metadata.

- [ ] **Step 4: Implement deterministic-first extraction**

```python
def extract_standard_semantics(record: dict[str, Any], client: LiteLLMClient) -> dict[str, Any]:
    deterministic = extract_deterministic_standard_metadata(record)
    page_digest = canonical_page_digest(record)
    response = client.chat_sync(
        standard_extraction_messages(record, deterministic),
        model="review-chat",
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=8192,
    )
    payload = json.loads(client.first_message_text(response))
    validate_standard_semantics(payload, page_digest)
    return merge_deterministic_and_model_semantics(
        deterministic,
        payload,
        source_type="new_mineru_semantic",
        prompt_version="standard-canonical-extraction-v1",
    )
```

Deterministic values win model values for the same key because both derive from new MinerU text and deterministic parsing has an exact format contract.

- [ ] **Step 5: Implement safe enrichment CLI**

The CLI must:

- load only `standard_knowledge_records` for `configured_tenant_id()`;
- skip `context_only` records;
- with `--only-missing`, call the model only for categories currently `partial` or `missing`;
- write semantic candidates into canonical fields/relations and rerun `canonical_completeness`;
- lock the canonical row and compare `sourceFingerprint` before update;
- preserve `generatedAt` and write `semanticExtractionVersion`, `semanticExtractedAt`, model route and prompt hash;
- commit each standard independently;
- never mutate source collections.

- [ ] **Step 6: Run semantic extraction tests**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_semantic_extraction.py tests/test_standard_knowledge_canonical.py
```

Expected: all pass.

- [ ] **Step 7: Commit Task 9**

```bash
git add backend/libs/standard_knowledge_canonical.py backend/libs/standard_semantic_extraction.py backend/config/standard_canonical_extraction_v1.json backend/scripts/enrich_standard_knowledge_canonical.py backend/tests/test_standard_semantic_extraction.py
git commit -m "feat: enrich canonical standard semantics"
```

---

### Task 10: 59 份真实数据迁移与端到端验收

**Files:**
- Create: `audit-reports/standard-knowledge-canonical-20260829/README.md`
- Create: `audit-reports/standard-knowledge-canonical-20260829/canonical-verification.json`
- Create: `audit-reports/standard-knowledge-canonical-20260829/screenshots/01-standard-overview.png`
- Create: `audit-reports/standard-knowledge-canonical-20260829/screenshots/02-clauses-tables.png`
- Create: `audit-reports/standard-knowledge-canonical-20260829/screenshots/03-history-completeness.png`

**Interfaces:**
- Consumes migration and verifier CLIs from Task 4, APIs from Task 5, UI from Task 6, retrieval from Task 7 and provenance from Task 8.
- Produces 59 canonical database records and an evidence-backed acceptance report.

- [ ] **Step 1: Capture pre-migration backup and source digests**

```bash
mkdir -p tmp/backups audit-reports/standard-knowledge-canonical-20260829
pg_dump --format=custom --no-owner \
  --file tmp/backups/aicheck-before-standard-canonical-20260829.dump \
  "$AICHECK_DATABASE_URL"
python backend/scripts/verify_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --require-count 0 \
  --json > audit-reports/standard-knowledge-canonical-20260829/pre-migration.json
```

Verify `pg_restore --list` succeeds before continuing.

- [ ] **Step 2: Run 59-record dry-run**

```bash
cd backend
source .venv/bin/activate
python scripts/rebuild_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --dry-run \
  --output ../audit-reports/standard-knowledge-canonical-20260829/dry-run.json
```

Expected report:

```json
{
  "processed": 59,
  "planned": 59,
  "failed": 0,
  "contextOnly": 1
}
```

- [ ] **Step 3: Apply canonical migration**

```bash
python scripts/rebuild_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --apply \
  --output ../audit-reports/standard-knowledge-canonical-20260829/apply.json
```

Expected: 59 inserted or updated, 0 failed. Run the same command again and require 59 unchanged.

- [ ] **Step 4: Enrich missing standard semantics**

```bash
python scripts/enrich_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --dry-run \
  --only-missing \
  --output ../audit-reports/standard-knowledge-canonical-20260829/semantic-dry-run.json
python scripts/enrich_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --apply \
  --only-missing \
  --output ../audit-reports/standard-knowledge-canonical-20260829/semantic-apply.json
```

Expected: 58 source-document standards processed, one `context_only` skipped, zero ungrounded values written. Run the apply command again and require every unchanged input to be skipped by prompt/content hash.

- [ ] **Step 5: Run strict verifier**

```bash
python scripts/verify_standard_knowledge_canonical.py \
  --database-url "$AICHECK_DATABASE_URL" \
  --require-count 59 \
  --json > ../audit-reports/standard-knowledge-canonical-20260829/canonical-verification.json
```

Require all gates true, including `unmapped_sources=0`, `duplicate_ids=0`, `missing_provenance=0`, `mineru_coverage=58`, `context_only_count=1`, and unchanged source digests.

- [ ] **Step 6: Verify API for every standard**

Run an authenticated read-only probe over all 59 file IDs. Assert:

```python
assert len(results) == 59
assert all(item["code"] == 0 for item in results)
assert all(item["canonicalVersion"] == "standard-knowledge-canonical@1" for item in results)
assert sum(item["contextType"] == "context_only" for item in results) == 1
assert all(item["sourceFingerprint"] for item in results)
```

Store only aggregate results and file IDs in the report; never store access tokens.

- [ ] **Step 7: Run full automated verification**

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_standard_knowledge_canonical.py \
  tests/test_standard_knowledge_canonical_migration.py \
  tests/test_standard_semantic_extraction.py \
  tests/test_standard_canonical_retrieval.py \
  tests/test_standard_canonical_review_grounding.py \
  tests/test_contract.py -k 'canonical or knowledge_file_detail'
cd ../frontend
pnpm run test:unit
pnpm run ts:check
pnpm run build:pro
```

Expected: zero failures and successful production build.

- [ ] **Step 8: Browser acceptance with current-run screenshots**

Use the authenticated local admin session and capture these states:

1. `NB/T 47013.10-2015`: overview fields, dates, issuing authority and replacement relation.
2. `TSG D7006-2020`: normalized table, seal and page-locating behavior.
3. `GB/T 20801.1-2025`: missing-layout fallback, equations, completeness and truncation disclosure.
4. One record with `legacy_only` information: selected new value and collapsed old source.
5. `业务规则.md`: explicit `context_only` state.

Save and inspect every screenshot before accepting it. Reject blank, loading, unauthorized or cropped captures.

- [ ] **Step 9: Write acceptance report**

The report must contain:

- migration counts;
- source coverage matrix;
- completeness distribution;
- every verifier gate;
- source-digest comparison;
- automated test commands and results;
- five accepted screenshots;
- explicit remaining `partial` categories per standard;
- backup path and rollback command.

- [ ] **Step 10: Commit Task 10 artifacts**

```bash
git add audit-reports/standard-knowledge-canonical-20260829
git commit -m "test: verify complete canonical standard knowledge"
```

---

## Spec Coverage Map

| Spec requirement | Implementation task |
|---|---|
| 原始来源不可变、派生集合、字段优先级 | Tasks 1-4 |
| 12 类来源收集与来源追溯 | Task 2 |
| identity/version/metadata 与全部结构内容 | Task 3 |
| 稳定身份、去重、完整度 | Task 3 |
| 幂等迁移、失败隔离、来源摘要保护 | Task 4 |
| canonical API、历史来源和旧详情兼容 | Task 5 |
| 概览、条款、表格公式、关系、完整度和历史 UI | Task 6 |
| canonical 检索与 `legacy_only` 降权 | Task 7 |
| AI grounding 版本和正式证据约束 | Task 8 |
| 缺失版本、元数据、引用与替代关系专项补齐 | Task 9 |
| 59 份真实迁移、严格验证、浏览器验收和回滚证据 | Task 10 |

---

## Final Completion Gate

Do not declare the objective complete until all of the following are proven from current state:

- `standard_knowledge_records` contains exactly 59 unique records.
- Every effective source maps to a canonical entry or a documented rejection.
- 58 source documents contain new MinerU structure; one rule document is `context_only`.
- New values win every tested conflict; old-only values survive with `legacy_only`.
- All canonical items carry provenance; no bbox/page is fabricated.
- Canonical detail API succeeds for all 59 records.
- Canonical UI displays overview, structures, relations, completeness and history.
- Retrieval uses canonical current values and does not duplicate old standard candidates.
- AI grounding records canonical record/item/version/fingerprint and rejects legacy-only formal proof.
- Source collections have identical pre/post record counts and payload digests.
- Automated tests and production build pass.
- Browser screenshots prove the requested user-visible states.
