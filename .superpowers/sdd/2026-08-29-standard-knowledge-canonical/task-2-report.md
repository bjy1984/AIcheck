# Task 2: 全来源收集与规范化适配器

## Delivered

Implemented `collect_standard_sources(state, file_id, repo_root)` in
`backend/libs/standard_knowledge_canonical.py`. The adapter validates that the
requested record is a `KS-STANDARD-RULES` knowledge file bound to its current
document and version, then returns a fresh, immutable source snapshot.

The snapshot contains every required group:

- file, document, version, newest sidecar-imported parse, and legacy parses;
- legacy fields and evidence;
- optional visual-extraction and rule-sidecar JSON;
- chunks, clauses, and PageIndex nodes;
- standard versions, clause references, and clause locators; and
- business-pack catalog items and rule references.

All state-derived records are deep-copied. The JSON sidecars are read as
objects and rejected if their top-level value is not an object. Page-index path
matching normalizes slash direction and leading `./` for stable matching.

The data fixture reflects the required tenant, document/version relationship,
source path, current MinerU parse, legacy OCR data, structural records, and
business references. The complete-source test exercises every output group and
the immutability test proves byte-identical serialized input state before and
after collection.

## Relationship note

The supplied canonical fixture stores standard versions, clause references,
and clause locators under `knowledgeFileId`. The repository's real standard
catalog YAML uses the same key. `_by_file` therefore supports `knowledgeFileId`
alongside the required direct `fileId` and scoped `fileId` forms; otherwise
these documented source groups would never be collected from the fixture or
production catalog-derived state.

## TDD evidence

RED:

```text
ImportError: cannot import name 'collect_standard_sources'
```

This was observed when running the new source-collection test before adding
the collector.

GREEN:

```text
pytest -q tests/test_standard_knowledge_canonical.py -k 'collect_standard_sources or source_collection_does_not_mutate'
2 passed, 2 deselected

pytest -q tests/test_standard_knowledge_canonical.py
4 passed
```

Both commands used `/Volumes/7up/github/knowledgetools/backend/.venv/bin/python`.
The worktree itself has no `backend/.venv`, so activating the task-brief's
relative path is not available; the requested absolute interpreter was used.

## Scope and concerns

No source fixtures or unrelated code were changed. The task only collects and
normalizes source inputs; it does not yet construct or persist canonical
records, which remains for subsequent tasks.

## Fix Round 1: cross-document version validation

Review found that a version ID selected from `document.currentVersionId` could
belong to another document while still matching `file.documentVersionId`.
`collect_standard_sources` now requires `version.documentId == document.id`
before it reads or returns any source group.

RED:

```text
test_collect_standard_sources_rejects_cross_document_version
Failed: DID NOT RAISE ValueError
```

The test modifies only the fixture version's `documentId` to `KDOC-OTHER`,
retaining its ID as the current document's version ID. Before the fix, the
collector accepted this corrupt cross-document relationship.

GREEN:

```text
pytest -q tests/test_standard_knowledge_canonical.py::test_collect_standard_sources_rejects_cross_document_version
1 passed

pytest -q tests/test_standard_knowledge_canonical.py -k 'collect_standard_sources or source_collection_does_not_mutate'
3 passed, 2 deselected
```
