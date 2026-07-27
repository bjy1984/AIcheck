# Evidence Hybrid Retrieval Design

## Goal

Add a single project-evidence retrieval service that performs BM25 and dense
retrieval, fuses their rankings with RRF, and is used consistently by ReviewRun,
the `/检索证据` slash command, and the review conversation Agent.

The service returns evidence candidates only. It does not confirm evidence,
override deterministic tool results, or make final review decisions.

## Scope

This change includes:

- A new `backend/libs/evidence_retrieval.py` service.
- Reuse of the existing BM25 tokenization/scoring, dense embedding client,
  pgvector/local-vector search, and RRF configuration.
- Hard project and document-version filtering before candidates are exposed.
- Material retrieval traces persisted in the existing `retrieval_traces`
  collection.
- A new `retrieve_material_evidence` ReviewRun graph step.
- Live retrieval for `/检索证据`.
- Live retrieval for the conversation Agent `search_node_evidence` tool.
- Graceful fallback to existing precomputed `nodeEvidenceLinks`.

This change does not include FactTarget configuration, a cross-encoder evidence
reranker, table-cell indexing, a new UI coverage matrix, or automatic evidence
confirmation.

## Architecture

`evidence_retrieval.py` owns query execution and result normalization. Consumers
provide scope and presentation-specific context but do not implement ranking.

```text
ReviewRun / Slash Command / Conversation Agent
                    |
                    v
         evidence_retrieval.search(...)
                    |
       +------------+------------+
       |                         |
       v                         v
  BM25 over scoped chunks   Dense vector search
       |                    with version filters
       +------------+------------+
                    |
                    v
                  RRF
                    |
                    v
       formal/advisory candidates + trace
```

The service reuses helper functions from `knowledge_retrieval.py`, but it does
not call `retrieve_knowledge_clauses`. Standard clauses and project evidence
have different scope, locator, and eligibility rules.

## Service Interface

The public function will accept:

```python
search_project_evidence(
    repo,
    *,
    project_id: str,
    node_id: int,
    document_version_ids: list[str],
    query: str,
    top_k: int = 20,
    review_run_id: str | None = None,
) -> dict[str, Any]
```

The result contains:

```json
{
  "formalCandidates": [],
  "advisoryCandidates": [],
  "allCandidates": [],
  "trace": {},
  "degraded": false,
  "fallbackReason": null
}
```

Every candidate contains a stable candidate ID, project/document/version IDs,
file name, page number, bbox, quoted text, chunk/source identifiers, BM25 rank,
dense rank, fused score, and formal-eligibility status.

## Candidate Corpus

The initial corpus is `knowledge_chunks` belonging to project knowledge files.
A chunk is eligible for ranking only when all of the following are true:

- Its knowledge file belongs to `project_id`.
- Its `documentVersionId` is in the explicit input version allowlist.
- The associated document belongs to the same project.
- The version and document still exist.
- The document is not withdrawn, invalidated, or archived as ineffective.
- The chunk contains non-empty text.

The explicit version allowlist is mandatory. An empty allowlist returns no live
candidates and records the reason in the trace.

The service resolves file and document metadata from repository state rather
than trusting metadata embedded in a vector payload.

## BM25 Retrieval

BM25 uses the existing `bm25_scores_for_texts` implementation and its
jieba/CJK-ngram fallback. The searchable text is:

```text
fileName + sectionPath + chunk text
```

BM25 produces an independent ordered list and rank map. Zero-score chunks are
not included in the lexical ranking.

## Dense Retrieval

Dense query embedding follows the existing semantic-embedding behavior and
offline-hash fallback rules. Repository vector search is extended with an
explicit `document_version_ids` filter.

Both PostgreSQL and local-vector implementations must apply the same version
allowlist. Results are intersected again with the scoped candidate corpus after
retrieval, providing defense in depth.

Dense failure does not fail the request. The trace records the degradation and
the service continues with BM25.

## RRF Fusion

The service uses the existing `rrf_fusion_config()` values. For each candidate:

```text
fusedScore =
    1 / (rrfK + bm25Rank), when present
  + denseWeight / (rrfK + denseRank), when present
```

Candidates appearing in either channel are retained. Sorting is by fused score,
then BM25 score, then locator completeness, with stable candidate ID as the
final tie-breaker.

## Evidence Eligibility

This phase classifies candidates without automatically confirming them.

A formal candidate requires:

- Valid `documentId` and `documentVersionId`.
- Positive page number.
- Valid four-coordinate bbox with positive width and height.
- Non-empty quoted text that is not only the file name.
- At least one chunk or fragment source identifier.

Candidates failing these checks are returned under `advisoryCandidates` with
explicit rejection reasons. All live candidates use `manualStatus = pending`
and `requiresHumanConfirmation = true`.

Existing manually confirmed precomputed evidence remains authoritative when
results are merged.

## Retrieval Trace

Each execution creates a trace with:

- `queryType = material_evidence_search`.
- Project, node, tenant, and document-version filters.
- BM25 and dense candidate counts and elapsed time.
- Embedding model and index version.
- RRF configuration.
- Channel ranks and fused score for returned candidates.
- Formal/advisory classification and rejection reasons.
- ReviewRun ID when applicable.
- Degradation and fallback reasons.

The trace is appended to `repo.state["retrieval_traces"]`. It contains
structured ranking evidence, not hidden model reasoning.

## ReviewRun Integration

The graph adds `retrieve_material_evidence` immediately after
`load_ocr_result`.

The step:

1. Uses only `review_run["inputDocumentVersionIds"]`.
2. Builds a query from the node name, current material review points, and
   existing fact-target terms.
3. Calls `search_project_evidence`.
4. Merges live candidates with existing context evidence by evidence ID or
   `(documentVersionId, pageNo, bbox, quotedText)`.
5. Preserves confirmed precomputed evidence over pending live candidates.
6. Stores the material trace alongside knowledge traces.
7. Continues with precomputed evidence if live retrieval fails.

The step does not block the graph on embedding or vector-store failure.

## Slash Command Integration

`/检索证据` performs live retrieval using the current node's allowed evidence
document versions. It renders formal and advisory cards from the live result.

If live retrieval raises an error or returns a degraded result with no
candidates, the command displays the existing precomputed candidates and marks
the response as fallback data.

## Conversation Agent Integration

`search_node_evidence` calls the same service with the current project/node and
request-visible document-version allowlist.

The tool no longer:

- Implements its own token-in-string scoring.
- Returns every candidate when a query misses.

The tool returns channel ranks, fused score, locator data, trace ID, and the
human-confirmation requirement. Request visibility filtering remains applied
before version IDs are passed to the service and again before results are
returned.

## Error Handling

- Empty query: build a deterministic node/material query.
- Empty version scope: return no live candidates and a degraded trace.
- Embedding unavailable: BM25-only response.
- Vector search failure: BM25-only response.
- No BM25 or dense hits: return an empty live result, not arbitrary candidates.
- Consumer-level service exception: fall back to precomputed evidence.
- Trace persistence failure: do not alter candidate eligibility; surface the
  trace persistence error in diagnostics.

## Testing

Unit tests cover:

- BM25-only retrieval.
- Dense-only candidate inclusion.
- Correct RRF ordering when channels disagree.
- PostgreSQL and local vector version filtering.
- Cross-project and cross-version exclusion.
- Formal versus advisory locator classification.
- Dense degradation to BM25.
- Empty-scope and no-hit behavior.

Integration tests cover:

- ReviewRun graph step order, frozen-version use, trace persistence, and
  precomputed fallback.
- `/检索证据` live result and fallback rendering.
- Conversation Agent use of the unified service and removal of return-all
  behavior.
- Existing material-targeting and evidence-readiness behavior remains
  unchanged.

## Acceptance Criteria

- All three consumers call `search_project_evidence`.
- No evidence candidate outside the explicit document-version allowlist can be
  returned.
- BM25 and Dense ranks are independently observable in the trace.
- RRF determines the combined ordering.
- Dense failure produces a usable BM25 response.
- Missing locators never become formal candidates.
- ReviewRun persists a material retrieval trace and continues when live
  retrieval is unavailable.
- Existing confirmed evidence is never demoted or overwritten by a live
  pending candidate.
