# Task 1 Report: Canonical 持久化与核心选择规则

## Implementation

- Added `backend/libs/standard_knowledge_canonical.py` with:
  - `CANONICAL_VERSION = "standard-knowledge-canonical@1"`.
  - The required `SOURCE_PRIORITY` ordering (`new_mineru` through `filename_inference`).
  - Deterministic `canonical_item_id()` generation using canonical JSON and a SHA-256 digest.
  - `select_canonical_field()` with blank-value filtering, source-priority/date ordering, current-versus-legacy authority, and complete candidate-source retention.
- Added `standard_knowledge_records` to `STATE_COLLECTIONS`, mapping the state key to the PostgreSQL collection with the same name.
- Added an empty `standard_knowledge_records` collection to seeded state.
- Added focused tests covering new MinerU precedence, legacy-only retention, source provenance, and persisted state registration.

## TDD evidence

### RED

Before implementation, ran:

```text
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_standard_knowledge_canonical.py -k 'new_mineru_value or canonical_collection'
```

Result: collection failed during import with `ModuleNotFoundError: No module named 'libs.standard_knowledge_canonical'`, because the production module and collection registration did not yet exist.

### GREEN

After the minimal implementation, ran the same command:

```text
..                                                                       [100%]
2 passed in 0.93s
```

## Tests and results

Focused tests plus state-loading regression:

```text
/Volumes/7up/github/knowledgetools/backend/.venv/bin/python -m pytest -q tests/test_standard_knowledge_canonical.py tests/test_incremental_state_refresh.py
.........                                                                [100%]
9 passed in 1.71s
```

Additional checks passed:

- `git diff --check`
- Python `compileall` for all changed Python files.

## Files changed

- `backend/libs/standard_knowledge_canonical.py`
- `backend/libs/db/repository.py`
- `backend/libs/db/seed.py`
- `backend/tests/test_standard_knowledge_canonical.py`
- `.superpowers/sdd/2026-08-29-standard-knowledge-canonical/task-1-report.md`

## Self-review

The implementation follows the exact requested source priorities and canonical version. Empty or whitespace-only candidates are excluded; unsupported source types remain deterministic via priority `0`; ties are ordered by `createdAt`; all usable candidates remain in `sources`; and a legacy-only selected value is explicitly marked `legacy_only`. Both seeded and blank repository states receive the new collection through the explicit seed entry and `STATE_COLLECTIONS` initialization.

## Concerns

None identified for Task 1. The field selector intentionally implements only the specified selection foundation; full canonical record generation and API integration belong to later tasks.
