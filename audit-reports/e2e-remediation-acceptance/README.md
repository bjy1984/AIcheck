# E2E remediation acceptance artifacts

This directory is the fixed output contract for the formal project-registration release gate.
Generated reports are intentionally not checked in as acceptance evidence until the test has run
against an isolated release-candidate environment.

## Run contract

Run only with explicit `AICHECK_E2E_ADMIN_USERNAME`, `AICHECK_E2E_ADMIN_PASSWORD`,
`AICHECK_E2E_LEADER_USERNAME`, `AICHECK_E2E_LEADER_PASSWORD`, and
`AICHECK_E2E_LEADER_MEMBER_LABEL` (the existing leader's visible member-selector label), and
`AICHECK_E2E_BUILD_VERSION`, `AICHECK_E2E_BUILD_SHA`, and a unique
`AICHECK_E2E_RUN_MARKER`. `AICHECK_E2E_FIXTURE_ROOT` must point to the separately provisioned
23-file acceptance corpus; the gate never reads an untracked repository `test/` directory.
`AICHECK_TEST_POSTGRES_URL` must contain
`options=-c search_path=aicheck_test_<run>,public`; the API and every worker must use that same
scoped DSN. PostgreSQL target comparison ignores credentials and treats loopback spellings as the
same host. Do not reuse a live application database or put credentials in this directory.

Fixture provisioning is fail-closed at collection. The root must contain exactly the 15 contractor
relative paths and 8 NDT relative paths declared in
`frontend/e2e/project-registration-upload-review.spec.ts`, with no extra business files. Files whose
basename is exactly `.DS_Store` are ignored as macOS metadata; no other hidden file or metadata name
is ignored. Allowed suffixes are
PDF, DOC, DOCX, PNG, JPG, and JPEG; every file must have nonzero size. The gate always computes and
attaches `fixture-sha256-manifest.json`. To pin the corpus, set
`AICHECK_E2E_FIXTURE_CHECKSUM_MANIFEST` to an external JSON object whose keys are exactly the 23
forward-slash relative paths and whose values are lowercase SHA-256 digests.

The default browser target is local. A remote acceptance clone additionally requires
`AICHECK_E2E_ALLOW_EXTERNAL_NON_PRODUCTION=true`; this is only an opt-in to probe the target, not a
production bypass. `/api/runtime/ui-context` must report `strictProduction=false`, a non-production
environment, demo UI data disabled, and the exact requested build SHA. Production-like targets fail
before the first project mutation.

Production/strict/demo/build mismatches fail on the first response. Because worker heartbeats may
warm shortly after startup, only `databaseScope` identity/readiness is polled, for at most 30
seconds at 750 ms intervals. A timeout attaches `runtime-database-scope-timeout.json` containing the
expected scope, every remaining mismatch, and the latest non-secret runtime identity.

`/api/runtime/ui-context` must also return this exact non-secret contract. Database names are
compared lowercase; schema and run marker are exact. No DSN, username, or password may be returned.

```json
{
  "buildVersion": "<AICHECK_E2E_BUILD_VERSION>",
  "databaseScope": {
    "engine": "postgresql",
    "database": "<normalized database from AICHECK_TEST_POSTGRES_URL>",
    "schema": "aicheck_test_<run>",
    "runMarker": "<AICHECK_E2E_RUN_MARKER>",
    "participants": {
      "api": { "ready": true, "database": "<same>", "schema": "<same>", "runMarker": "<same>" },
      "processingWorker": { "ready": true, "database": "<same>", "schema": "<same>", "runMarker": "<same>" },
      "reviewWorker": { "ready": true, "database": "<same>", "schema": "<same>", "runMarker": "<same>" }
    }
  }
}
```

The release-candidate topology must report ready for API, PostgreSQL transactions, object storage,
OCR provider, OCR/slicing/vector worker, embedding provider, Temporal, workflow schema, and Review
Worker heartbeat. Formal AI review may not use inline or deterministic fallback.

```bash
cd frontend
pnpm playwright test e2e/project-registration-upload-review.spec.ts
```

Missing credentials, build identities, run marker, or test DSN fail Playwright collection with a
nonzero exit. A configured DSN without an
`aicheck_test_*` search path fails preflight before any browser mutation. Dependency readiness,
business-flow, permission, binding, processing, or AI agreement failures fail the test.

## Generated files

- `playwright-report.json`: machine-readable test status and attachment index.
- `html-report/`: human-readable Playwright report.
- `playwright-artifacts/`: per-test traces, videos/screenshots, and attachments.
- Named attachments `runtime-target.json` and `preflight-health.json` contain admission snapshots.
- Named attachment `fixture-sha256-manifest.json` records all 23 relative paths, sizes, and hashes.
- Failed identity warm-up adds named attachment `runtime-database-scope-timeout.json`.
- Named attachment `acceptance-summary.json` contains project/build identifiers, issuers and roles,
  file/isolation/readiness counts, authorization probe statuses, gate results, and the final AI
  result/evidence/rule contract.
- Named screenshot attachments `01-admin-registration-link.png` through
  `06-owner-upload-denied.png`.
- Named screenshot attachment `07-node36-evidence-confirmed.png`.
- Named screenshot attachment `08-formal-ai-result-and-timeline.png`.

Attachments live under the Playwright test result directory and are indexed by both JSON and HTML
reports; they are not promised as files at the acceptance-directory root. A release evidence bundle
is valid only when the indexed `acceptance-summary.json` attachment reports 15 contractor files, 8
NDT files with exact bindings, complete OCR/slice/vector counts, distinct contractor/NDT visible ID
sets, denied detail/preview/download/original/office-preview probes, zero owner upload controls,
confirmed formal evidence readiness, and a non-empty AI Run ID/result/evidence/rule contract. Its
`openRequiredGateCount` must be zero. `gateResults` and `defectInventory` are separate: the former is the required coverage
checklist; the latter contains only caught gate failures with severity/message/timestamp.
`openP0P1Defects` is derived only from open P0/P1 records in `defectInventory`, while
`openRequiredGateCount` is derived from the checklist.

## Release decision

Any registration failure, incomplete approved-member grant, cross-unit document exposure,
multi-file loss, incomplete NDT binding, owner upload capability, premature submission, formal
Temporal failure, or AI result/timeline/evidence mismatch blocks release. Preserve the failed
artifact directory and roll back the release candidate; do not convert the run to an inline
fallback acceptance.
