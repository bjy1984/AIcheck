# Task 4 Report — Slash command live retrieval

## Scope

- `/检索证据` and `/补充证据` now call `search_project_evidence`.
- The command tail is passed through as the query.
- A command without a tail deterministically combines node name, current task,
  and ordered review-point text.
- The explicit non-empty version allowlist is derived only from request-visible
  formal and advisory node evidence.
- Returned candidates are filtered against that allowlist again before cards
  are rendered.
- Live formal and advisory candidates render in separate `evidence_card`
  blocks carrying `retrievalTraceId`, `fusedScore` and rank metadata.
- Service exceptions, empty scope, and no usable in-scope live candidates fall
  back to the original precomputed cards with `fallbackUsed: true`.

## RED

Observed the following intended failures before implementing each behavior:

1. Live command test failed with `KeyError: 'query'` because the existing
   deterministic command never called the retrieval service.
2. Service-exception test failed with an uncaught `RuntimeError`.
3. No-tail command test failed because the service received an empty query.
4. Scope test failed because a deliberately returned out-of-allowlist
   candidate appeared in the formal card.
5. No-live-hit test failed because the precomputed evidence card was not used.
6. Empty-scope test failed because the service was called with an empty
   document-version allowlist.

## GREEN

Targeted result:

```text
.venv/bin/pytest -q tests/test_review_b_workspace.py -k 'search_evidence'
5 passed, 34 deselected, 1 warning
```

Full workspace test-file result:

```text
.venv/bin/pytest -q tests/test_review_b_workspace.py
39 passed, 1 warning
```

The warning is the existing FastAPI/Starlette `httpx` deprecation warning.

## Verification

- `git diff --check -- backend/apps/api/routes.py backend/tests/test_review_b_workspace.py`
  passed.
- Task-only diffs were compared against byte-for-byte baseline copies captured
  before implementation.
- Only the Task 4 delta is staged; pre-existing changes in both dirty files are
  intentionally excluded from the commit.

## Concerns

- `ruff` is not installed in the project virtual environment, so a Ruff run was
  unavailable. The focused and full review workspace pytest runs passed.
- Both owned source files had substantial pre-existing worktree changes. Those
  changes remain in the worktree and are not part of the Task 4 commit.
