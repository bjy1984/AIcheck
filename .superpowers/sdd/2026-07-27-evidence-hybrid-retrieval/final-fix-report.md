# Final fix report — Evidence Hybrid Retrieval

## Status

DONE_WITH_CONCERNS. All three Important findings from `final-fix-brief.md`
were reproduced independently with failing tests, fixed with minimal
production changes, and verified by the full Task 6 backend targeted suite.

## Changes

### 1. Slash live no-hit semantics

- Updated the existing successful no-live-hit regression to require an empty
  live card with `fallbackUsed = false`.
- `review_assistant_deterministic_blocks` now uses precomputed fallback only
  for a service exception, an empty visible scope, or a degraded response with
  no usable live candidates.
- A degraded response with usable candidates remains live, and a successful
  non-degraded no-hit no longer exposes unrelated precomputed evidence.

### 2. Finite bbox eligibility

- `_valid_bbox` now requires all four converted coordinates to satisfy
  `math.isfinite` before applying positive-area checks.
- Focused service tests cover NaN, positive infinity, negative infinity, and a
  valid finite positive-area control.
- Non-finite candidates remain visible only as advisory evidence with
  `invalid_bbox`; they cannot be classified as formal.

### 3. Agent advisory-visible version scope

- The request-filtered `advisory_evidence_links` snapshot now flows separately
  through `review_conversation/execution.py` and
  `review_conversation/loop.py` into `search_node_evidence`.
- Advisory links expand only the explicit document-version allowlist. They are
  not merged into the formal model context, manual-status identity map, or
  exception fallback candidates.
- The end-to-end Agent regression starts at the message route, uses a version
  represented only by an advisory missing-bbox link, verifies the service
  receives that version, accepts an in-scope formal live candidate, and proves
  a service result from another version is still excluded.

No consumer-side ranking, standard-clause retrieval, frontend code, public
response shape, or live-candidate confirmation status was changed.

## Strict TDD evidence

### Finding 1 RED

```text
.venv/bin/pytest -q \
  tests/test_review_b_workspace.py::test_review_b_search_evidence_successful_no_hit_renders_empty_live_result

FAILED
assert card["items"] == []
Left contains NEL-REVIEW-B-NO-LIVE-HIT
```

GREEN:

```text
.venv/bin/pytest -q tests/test_review_b_workspace.py -k 'search_evidence'
5 passed, 42 deselected, 1 warning
```

### Finding 2 RED

```text
.venv/bin/pytest -q tests/test_evidence_retrieval.py \
  -k 'non_finite_bbox or finite_positive_bbox'

2 failed, 2 passed, 18 deselected
- positive-infinity remained formal
- negative-infinity remained formal
```

The NaN and finite positive-area controls already behaved correctly, isolating
the missing finite-coordinate check.

GREEN:

```text
.venv/bin/pytest -q tests/test_evidence_retrieval.py -k 'bbox'
5 passed, 17 deselected
```

### Finding 3 RED

```text
.venv/bin/pytest -q \
  tests/test_review_b_workspace.py::test_review_b_agent_search_includes_advisory_only_visible_version

FAILED
KeyError: 'document_version_ids'
```

The unified service was not called because the advisory-only version had been
dropped before the Agent tool received its scope.

GREEN:

```text
.venv/bin/pytest -q \
  tests/test_review_b_workspace.py::test_review_b_agent_search_includes_advisory_only_visible_version
1 passed, 1 warning

.venv/bin/pytest -q tests/test_review_b_workspace.py -k 'agent or search_evidence'
22 passed, 26 deselected, 1 warning
```

## Verification

Full Task 6 backend targeted suite:

```text
.venv/bin/pytest -q \
  tests/test_evidence_retrieval.py \
  tests/test_evidence_retrieval_review_run.py \
  tests/test_material_targeting.py \
  tests/test_knowledge_rrf_fusion.py \
  tests/test_knowledge_p1_retrieval.py \
  tests/test_review_runtime_tool_dispatcher.py \
  tests/test_material_review_agent.py \
  tests/test_review_b_workspace.py

138 passed, 1 warning in 12.06s
```

Core Ruff:

```text
uvx ruff check \
  libs/evidence_retrieval.py \
  libs/review_conversation/tools.py \
  tests/test_evidence_retrieval.py \
  tests/test_review_b_workspace.py \
  --ignore UP037

All checks passed!
```

Additional checks:

```text
.venv/bin/python -m py_compile \
  libs/evidence_retrieval.py \
  libs/review_conversation/execution.py \
  libs/review_conversation/loop.py \
  libs/review_conversation/tools.py \
  apps/api/routes.py \
  tests/test_evidence_retrieval.py \
  tests/test_review_b_workspace.py

passed

git diff --check
passed
```

Frontend checks were not required because no frontend file changed.

## Commit

The report and exact final-fix code/tests are committed together with subject:

```text
fix: address final evidence retrieval findings
```

The resulting commit hash is recorded in the task handoff.

## Concerns

- The complete Task 6 suite emits the existing FastAPI/Starlette `httpx`
  deprecation warning.
- A broader Ruff run over the pre-existing
  `review_conversation/execution.py` and `review_conversation/loop.py` files
  reports 14 existing import/S110/B023/RUF100/BLE001 findings on unchanged
  lines. They were not expanded into this fix. The modified lines compile,
  the core Ruff set passes, and the full backend targeted suite passes.
