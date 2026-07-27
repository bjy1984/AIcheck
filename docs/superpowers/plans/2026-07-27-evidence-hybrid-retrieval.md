# Evidence Hybrid Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one project-evidence BM25 + Dense + RRF service and connect ReviewRun, `/检索证据`, and the review conversation Agent to it.

**Architecture:** `libs/evidence_retrieval.py` owns scope resolution, BM25 and dense ranking, RRF fusion, eligibility classification, and trace construction. Repository vector searches gain an explicit document-version allowlist. The three consumers remain thin adapters and retain precomputed `nodeEvidenceLinks` as their failure fallback.

**Tech Stack:** Python 3.12, pytest, FastAPI, pgvector/PostgreSQL, existing Qwen/Infinity embedding client, existing in-memory repository fallback.

## Global Constraints

- Live evidence retrieval must require an explicit non-empty `document_version_ids` allowlist.
- Every returned candidate must belong to `project_id` and the explicit version allowlist.
- Dense retrieval failure must degrade to BM25 without failing the consumer.
- A live candidate is always pending and requires human confirmation.
- Missing page, valid bbox, quoted text, or source chunk keeps a candidate advisory.
- Existing confirmed evidence wins when merged with live pending candidates.
- Standard-clause retrieval behavior must remain unchanged.
- No consumer may implement its own evidence ranking.

---

### Task 1: Version-scoped vector search

**Files:**
- Modify: `backend/libs/db/repository.py:3785-3902`
- Modify: `backend/libs/knowledge_dense.py:35-113`
- Test: `backend/tests/test_evidence_retrieval.py`

**Interfaces:**
- Produces: a `document_version_ids: list[str] | None = None` keyword argument on `Repository.search_knowledge_vectors`
- Produces: the same keyword argument on `Repository.search_local_knowledge_vectors`
- Produces: the same keyword argument on `dense_knowledge_hits`
- Guarantee: both PostgreSQL and local paths enforce the same allowlist.

- [ ] **Step 1: Write failing local-vector allowlist test**

```python
def test_local_dense_search_rejects_vectors_outside_version_allowlist() -> None:
    repository = Repository()
    repository.state["knowledge_vectors"] = [
        vector_row("KV-ALLOWED", "DV-ALLOWED", [1.0, 0.0]),
        vector_row("KV-BLOCKED", "DV-BLOCKED", [1.0, 0.0]),
    ]

    hits = repository.search_local_knowledge_vectors(
        [1.0, 0.0],
        document_version_ids=["DV-ALLOWED"],
    )

    assert [item["documentVersionId"] for item in hits] == ["DV-ALLOWED"]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_retrieval.py::test_local_dense_search_rejects_vectors_outside_version_allowlist
```

Expected: failure because `document_version_ids` is not accepted.

- [ ] **Step 3: Implement the local and PostgreSQL filters**

Add the optional argument to both repository methods. The local loop skips rows
outside the set. PostgreSQL adds:

```python
if document_version_ids is not None:
    version_ids = sorted({str(item) for item in document_version_ids if item})
    if not version_ids:
        return []
    filters.append("document_version_id = ANY(%s)")
    params.append(version_ids)
```

Pass the same argument through `dense_knowledge_hits`.

- [ ] **Step 4: Add and run a PostgreSQL SQL-contract test**

Use a recording fake cursor and assert that the generated query contains
`document_version_id = ANY(%s)` and the allowlist is present in parameters.

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_retrieval.py -k 'dense_search'
```

Expected: all dense-search tests pass.

- [ ] **Step 5: Run existing dense retrieval regression tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_knowledge_rrf_fusion.py tests/test_knowledge_p1_retrieval.py
```

Expected: pass without changes to standard retrieval ordering.

---

### Task 2: Unified Evidence Retrieval service

**Files:**
- Create: `backend/libs/evidence_retrieval.py`
- Modify: `backend/libs/knowledge_retrieval.py` only if a small public RRF helper is required
- Test: `backend/tests/test_evidence_retrieval.py`

**Interfaces:**
- Consumes: version-scoped `dense_knowledge_hits`
- Consumes: `bm25_scores_for_texts` and `rrf_fusion_config`
- Produces:

```python
def search_project_evidence(
    repo: Any,
    *,
    project_id: str,
    node_id: int,
    document_version_ids: list[str],
    query: str,
    top_k: int = 20,
    review_run_id: str | None = None,
    persist_trace: bool = True,
) -> dict[str, Any]:
    return {
        "formalCandidates": formal_candidates,
        "advisoryCandidates": advisory_candidates,
        "allCandidates": ranked_candidates,
        "trace": trace,
        "degraded": bool(trace.get("degraded")),
        "fallbackReason": trace.get("fallbackReason"),
    }
```

- [ ] **Step 1: Write failing BM25 scope and classification tests**

```python
def test_evidence_bm25_is_project_and_version_scoped() -> None:
    repository = evidence_repository()

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证 有效期",
    )

    assert {item["documentVersionId"] for item in result["allCandidates"]} == {"DV-P1"}
    assert result["formalCandidates"][0]["quotedText"] == "许可证有效期至 2028-12-31"
    assert result["trace"]["queryType"] == "material_evidence_search"


def test_evidence_without_bbox_is_advisory() -> None:
    repository = evidence_repository(chunk_bbox=None)
    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证",
    )

    assert result["formalCandidates"] == []
    assert result["advisoryCandidates"][0]["rejectionReasons"] == ["missing_bbox"]
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_retrieval.py -k 'evidence_bm25 or evidence_without_bbox'
```

Expected: import failure because `libs.evidence_retrieval` does not exist.

- [ ] **Step 3: Implement scoped corpus and BM25 ranking**

Implement focused helpers named `scoped_evidence_chunks`,
`evidence_lexical_text`, `evidence_eligibility`, and
`normalize_evidence_candidate`. Their inputs are repository records plus the
explicit project/version scope; their outputs are respectively a scoped chunk
list, searchable text, `(eligible, rejection_reasons)`, and the normalized
candidate dictionary defined by the design.

Resolve project/file/document metadata from repository collections. Never trust
vector payload metadata for scope authorization.

- [ ] **Step 4: Write failing Dense + RRF disagreement test**

```python
def test_evidence_rrf_fuses_bm25_and_dense_rankings(monkeypatch) -> None:
    repository = evidence_repository(two_chunks=True)
    monkeypatch.setattr(
        evidence_retrieval,
        "dense_knowledge_hits",
        lambda *args, **kwargs: (
            [{"chunkId": "CHK-DENSE", "documentVersionId": "DV-P1"}],
            {"status": "ok", "denseDegraded": False, "hitCount": 1},
        ),
    )

    result = search_project_evidence(
        repository,
        project_id="P-1",
        node_id=1,
        document_version_ids=["DV-P1"],
        query="许可证 有效期",
    )

    candidates = {item["chunkId"]: item for item in result["allCandidates"]}
    assert candidates["CHK-BM25"]["bm25Rank"] == 1
    assert candidates["CHK-DENSE"]["denseRank"] == 1
    assert all(item["fusedScore"] > 0 for item in candidates.values())
    assert result["trace"]["fusion"]["method"] == "rrf"
```

- [ ] **Step 5: Run the RRF test and verify RED**

Expected: failure because Dense ranks and RRF are not implemented.

- [ ] **Step 6: Implement Dense intersection and RRF**

Call:

```python
dense_hits, dense_meta = dense_knowledge_hits(
    repo,
    query,
    top_k=max(top_k * 2, 20),
    source_id="KS-PROJECT-FILE",
    document_version_ids=allowed_versions,
)
```

Intersect hits with the scoped chunk map, calculate the two rank maps, and apply
the formula defined in the design. Persist the trace only after candidate
construction succeeds.

- [ ] **Step 7: Write and pass degradation/no-hit tests**

Cover:

- Dense exception produces BM25 candidates and `denseDegraded = true`.
- Empty version scope returns no candidates.
- No lexical or Dense hit returns no arbitrary candidate.
- Cross-project chunks remain excluded even if a Dense hit references them.

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_retrieval.py
```

Expected: all service tests pass.

---

### Task 3: ReviewRun graph integration

**Files:**
- Modify: `backend/libs/review_orchestrator/execution.py:69-93`
- Modify: `backend/libs/review_orchestrator/execution.py:1982-2130`
- Modify: `backend/libs/review_orchestrator/execution.py:3512-3609`
- Test: `backend/tests/test_evidence_retrieval_review_run.py`

**Interfaces:**
- Consumes: `search_project_evidence`
- Produces: graph node `retrieve_material_evidence`
- Produces: `context["materialEvidenceRetrieval"]`
- Produces: merged `context["evidenceLinks"]`

- [ ] **Step 1: Write failing graph-order and frozen-scope test**

```python
def test_review_graph_retrieves_material_evidence_after_ocr(monkeypatch) -> None:
    calls = []

    def fake_search(repo, **kwargs):
        calls.append(kwargs)
        return live_result("RTR-MATERIAL-1")

    monkeypatch.setattr(execution, "search_project_evidence", fake_search)
    run = prepared_review_run(input_versions=["DV-FROZEN"])
    context = prepared_context()

    execution.run_step(run, "retrieve_material_evidence", context)

    keys = [item["key"] for item in execution.REVIEW_GRAPH_STEPS]
    assert keys.index("retrieve_material_evidence") == keys.index("load_ocr_result") + 1
    assert calls[0]["document_version_ids"] == ["DV-FROZEN"]
    assert context["materialEvidenceRetrieval"]["retrievalTraceId"] == "RTR-MATERIAL-1"
```

- [ ] **Step 2: Run the test and verify RED**

Expected: failure because the graph step and import do not exist.

- [ ] **Step 3: Implement query building, step execution, and merge**

Add `build_material_evidence_query(review_run, context) -> str` and
`merge_material_evidence(existing, live_candidates) -> list[dict[str, Any]]`.
The query builder combines node name, review-point text, and fact-target terms.
The merge helper uses evidence ID first and
`(documentVersionId, pageNo, bbox, quotedText)` second as its deduplication key.

Confirmed existing evidence sorts first and is never overwritten. Live
candidates remain pending. The graph-view artifact counter associates material
traces with `retrieve_material_evidence`.

- [ ] **Step 4: Write and pass fallback test**

Monkeypatch the service to raise and assert that the step succeeds, keeps the
precomputed evidence list unchanged, and returns `fallbackUsed = true`.

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_evidence_retrieval_review_run.py
```

Expected: pass.

- [ ] **Step 5: Run ReviewRun regressions**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_review_p0_correctness.py \
  tests/test_review_runtime_tool_dispatcher.py \
  tests/test_material_review_agent.py
```

Expected: pass with the new graph step included.

---

### Task 4: Slash command live retrieval

**Files:**
- Modify: `backend/apps/api/routes.py:8477-8585`
- Test: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Consumes: `search_project_evidence`
- Produces: live `evidence_card` blocks with `retrievalTraceId`
- Preserves: precomputed formal/advisory fallback.

- [ ] **Step 1: Write failing live-command test**

Extend `test_review_b_search_evidence_separates_located_candidates_and_advisory_files`
to monkeypatch `search_project_evidence`, send `/检索证据 许可证有效期`, and assert:

```python
assert live_call["document_version_ids"] == ["DV-ALLOWED"]
assert evidence_card["retrievalTraceId"] == "RTR-LIVE-1"
assert evidence_card["items"][0]["fusedScore"] > 0
```

- [ ] **Step 2: Run the test and verify RED**

Expected: the mock is not called because the command only reads readiness.

- [ ] **Step 3: Implement live command execution**

Pass the command tail as the query. Derive version scope from request-visible
node evidence; when no explicit query exists, build a deterministic node query.
Render formal and advisory results separately.

- [ ] **Step 4: Add fallback test and make both pass**

Raise from the service and assert the original precomputed cards are returned
with `fallbackUsed = true`.

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_review_b_workspace.py -k 'search_evidence'
```

Expected: pass.

---

### Task 5: Conversation Agent unified retrieval

**Files:**
- Modify: `backend/libs/review_conversation/tools.py:42-67`
- Modify: `backend/libs/review_conversation/tools.py:358-444`
- Test: `backend/tests/test_review_b_workspace.py`

**Interfaces:**
- Consumes: `search_project_evidence`
- Produces: `search_node_evidence` result with `retrievalTraceId`, channel ranks,
  fused scores, and formal/advisory classification.

- [ ] **Step 1: Write failing Agent-tool test**

```python
def test_review_b_agent_search_uses_hybrid_evidence_service(monkeypatch) -> None:
    called = {}

    def fake_search(repo, **kwargs):
        called.update(kwargs)
        return live_result("RTR-AGENT-1")

    monkeypatch.setattr(routes, "search_project_evidence", fake_search)
    output = call_review_agent_tool(
        "search_node_evidence",
        {"query": "许可证有效期"},
    )

    assert called["project_id"] == output["projectId"]
    assert output["retrievalTraceId"] == "RTR-AGENT-1"
    assert output["candidates"][0]["denseRank"] == 1
```

- [ ] **Step 2: Run the test and verify RED**

Expected: service mock is not called because the tool uses token containment.

- [ ] **Step 3: Replace local scoring with the service call**

Use only request-visible evidence versions for the allowlist. Filter returned
candidates against that allowlist again. Remove query-miss return-all behavior.
On service exception, return scoped precomputed candidates with
`fallbackUsed = true`.

- [ ] **Step 4: Add no-hit regression test**

Assert a successful live no-hit result returns `candidateCount = 0` and does not
return every precomputed candidate.

- [ ] **Step 5: Run Agent tests**

```bash
cd backend
.venv/bin/pytest -q tests/test_review_b_workspace.py -k 'agent or search_evidence'
```

Expected: pass.

---

### Task 6: Full verification and acceptance audit

**Files:**
- Verify only; fix failures in the owning task's files.

**Interfaces:**
- Verifies all acceptance criteria from the design specification.

- [ ] **Step 1: Run formatting and static checks**

```bash
cd backend
.venv/bin/ruff check \
  libs/evidence_retrieval.py \
  libs/knowledge_dense.py \
  libs/db/repository.py \
  libs/review_orchestrator/execution.py \
  libs/review_conversation/tools.py \
  apps/api/routes.py \
  tests/test_evidence_retrieval.py \
  tests/test_evidence_retrieval_review_run.py
```

- [ ] **Step 2: Run the complete targeted suite**

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_evidence_retrieval.py \
  tests/test_evidence_retrieval_review_run.py \
  tests/test_material_targeting.py \
  tests/test_knowledge_rrf_fusion.py \
  tests/test_knowledge_p1_retrieval.py \
  tests/test_review_runtime_tool_dispatcher.py \
  tests/test_material_review_agent.py \
  tests/test_review_b_workspace.py
```

- [ ] **Step 3: Audit the implementation against the design**

Confirm from code and tests:

- All three consumers call `search_project_evidence`.
- Repository Dense paths enforce the explicit version allowlist.
- Trace exposes BM25 rank, Dense rank, and RRF score.
- Dense failure returns BM25 output.
- Missing locator candidates are advisory.
- Confirmed evidence is not overwritten.
- Live no-hit does not return arbitrary evidence.

- [ ] **Step 4: Inspect final diff**

```bash
git diff --check
git status --short
git diff --stat
```

Confirm unrelated user changes remain untouched.
