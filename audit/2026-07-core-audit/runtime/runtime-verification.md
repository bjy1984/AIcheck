# Runtime verification

## Scope

- Uncommitted worktree diff against HEAD: 32 tracked files changed at verification start, 0 commits ahead of upstream.
- Surface: running FastAPI server on `127.0.0.1:8011`; release-gate CLI.

## Observations

1. `GET /api/healthz` returned `code=0` and exposed OCR child readiness plus top-level runtime readiness.
2. `GET /api/operations/tasks?area=fde` returned canonical `statusCode=waiting_human` alongside the legacy `status=waiting_human_review`.
3. `GET /api/fde/cost-budgets` returned normalized attempt completeness fields (`modelAttemptCount`, `normalizedAttemptCount`, `unknownCostAttemptCount`, `complete`).
4. Invalid human edit with `correctedOutput=[]` returned `VALIDATION_ERROR / invalid_corrected_output / CORRECTED_OUTPUT_REQUIRED`.
5. Valid partial edit returned `code=0`, `status=edited_by_human`, and feedback containing the corrected description. Temporal was unavailable, so the business mutation succeeded while `temporalSignal.status=failed` was reported instead of crashing the request.
6. Reusing the same idempotency key and same body replayed the successful response. Reusing it with a different body returned `IDEMPOTENCY_KEY_CONFLICT`.
7. Review rerun returned a new child ReviewRun and `dispatch={mode:inline,status:completed}`; missing rerun reason returned `VALIDATION_ERROR`.
8. Reviewed-label CLI returned exit 1 in certification mode and exit 0 only with explicit `--draft`.

## Verification finding and fix

The first valid human-edit probe exposed two runtime issues that were fixed during verification:

- Sparse corrected output inherited legacy projected drafts that lacked new schema fields; the edit path now supplies safe defaults before validation.
- Temporal connection failure was caught as `RuntimeError` and retried via a second event loop, escaping the error handler and producing HTTP 500. Temporal start/signal helpers now catch the original exception once and return structured failure state.

## Environment limitation

A strict-production API instance could not be kept running with an intentionally unavailable Redis because startup correctly requires the Redis security backend before the readiness route is reachable. The strict OCR-control readiness behavior remains covered by the focused runtime-status contract, while the observed startup failure itself confirms security fail-closed behavior.
