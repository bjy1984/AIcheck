# Project Analysis Blind Routing Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run an isolated A/B/C replay for “测试项目三” that compares hard-bound evidence, full-OCR Map/Reduce routing, and hybrid BM25+dense+LLM routing without mutating formal project state.

**Architecture:** Add a focused `libs.project_analysis_replay` package and one CLI. The package freezes a project snapshot, builds three evidence routes, executes the existing project-analysis review contract through injected model clients, validates citations, anonymizes outputs for blind judging, and writes artifacts only beneath `output/project-analysis-routing-replay/`. Production one-click-analysis code remains unchanged.

**Tech Stack:** Python 3.12, existing repository state adapter, `QwenRuntimeClient`, `EmbeddingClient`, pytest, JSON/Markdown artifacts.

**Spec:** `docs/superpowers/specs/2026-09-01-project-analysis-blind-routing-replay-design.md`

## Global Constraints

- Project is exactly `P-2026-FDBB4B` unless the CLI explicitly receives another ID.
- Candidate files must be uploaded successfully, current, stored, and not deleted or voided.
- A/B/C each run three real model replays.
- B must route 100% of cleaned OCR text through full-OCR Map calls.
- C must use a configured semantic Embedding service; `offline-hash-v1` is forbidden.
- Cross-node routed evidence is silently available to review but never persisted as a formal binding.
- No formal project collection may change during replay.
- Blind-judge scores are relative model preferences, never absolute accuracy.

---

### Task 1: Frozen experiment snapshot and mutation guard

**Files:**
- Create: `backend/libs/project_analysis_replay/__init__.py`
- Create: `backend/libs/project_analysis_replay/snapshot.py`
- Test: `backend/tests/test_project_analysis_replay_snapshot.py`

**Interfaces:**
- Produces: `build_experiment_snapshot(state, project_id) -> dict[str, Any]`
- Produces: `formal_state_fingerprint(state) -> str`
- Snapshot fields: `schemaVersion`, `project`, `nodes`, `files`, `priorityRoutes`, `sourceStateFingerprint`, `snapshotHash`.

- [ ] **Step 1: Write failing candidate-pool and fingerprint tests**

```python
def test_snapshot_only_includes_uploaded_current_stored_files(replay_state):
    snapshot = build_experiment_snapshot(replay_state, "P-TEST")
    assert [row["fileId"] for row in snapshot["files"]] == ["DOC-READY"]

def test_formal_fingerprint_ignores_experiment_artifacts(replay_state):
    before = formal_state_fingerprint(replay_state)
    replay_state.setdefault("project_analysis_replay_runs", []).append({"id": "EXP-1"})
    assert formal_state_fingerprint(replay_state) == before
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_snapshot.py -q`

Expected: import failure because `libs.project_analysis_replay.snapshot` does not exist.

- [ ] **Step 3: Implement deterministic snapshot creation**

```python
FORMAL_COLLECTIONS = (
    "projects", "documents", "versions", "bindings", "node_evidence_links",
    "tree_nodes", "requirements", "ocr_parse_results", "review_findings",
    "review_opinions", "project_analysis_runs", "project_analysis_snapshots",
)

def eligible_file(document, version):
    return (
        document.get("fileStatus") == "已上传"
        and version
        and version.get("isCurrent") is True
        and bool(version.get("storageKey"))
        and document.get("status") not in {"已删除", "已作废"}
    )
```

Reuse `clean_project_ocr_text`, `_latest_parse_result`, `_node_rule_text`, and `_node_requirements`; store hashes and text in the experiment snapshot, not new production records.

- [ ] **Step 4: Run snapshot tests and full related tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_snapshot.py tests/test_project_analysis_prompt.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/libs/project_analysis_replay backend/tests/test_project_analysis_replay_snapshot.py
git commit -m "feat: freeze isolated project analysis replay inputs"
```

### Task 2: Artifact store and measured model-call wrapper

**Files:**
- Create: `backend/libs/project_analysis_replay/artifacts.py`
- Create: `backend/libs/project_analysis_replay/model_calls.py`
- Test: `backend/tests/test_project_analysis_replay_artifacts.py`

**Interfaces:**
- Consumes: snapshot from Task 1.
- Produces: `ReplayArtifactStore(root: Path, experiment_id: str)`.
- Produces: `MeasuredChatClient.call(stage, messages, **kwargs) -> dict[str, Any]`.
- Every call record contains `stage`, request/response hashes, provider/model, usage, normalized cost, elapsed milliseconds, and error.

- [ ] **Step 1: Write failing artifact isolation and usage tests**

```python
def test_store_rejects_paths_outside_experiment_root(tmp_path):
    store = ReplayArtifactStore(tmp_path, "EXP-1")
    with pytest.raises(ValueError):
        store.write_json("../escape.json", {})

def test_measured_call_records_usage_and_elapsed(fake_chat_client):
    result = MeasuredChatClient(fake_chat_client).call("route", [{"role": "user", "content": "x"}])
    assert result["measurement"]["usage"]["inputTokens"] == 11
    assert result["measurement"]["elapsedMs"] >= 0
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_artifacts.py -q`

- [ ] **Step 3: Implement atomic artifact writes and measured calls**

Use a temporary sibling file followed by `Path.replace`. Reuse `normalize_model_usage` and `model_cost_cny`. Store full prompts and raw responses because the user explicitly requested comprehensive replay evidence.

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_artifacts.py -q`

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/libs/project_analysis_replay/artifacts.py backend/libs/project_analysis_replay/model_calls.py backend/tests/test_project_analysis_replay_artifacts.py
git commit -m "feat: record isolated replay model calls"
```

### Task 3: Shared review request and Arm A baseline

**Files:**
- Create: `backend/libs/project_analysis_replay/review.py`
- Create: `backend/libs/project_analysis_replay/arm_a.py`
- Test: `backend/tests/test_project_analysis_replay_review.py`

**Interfaces:**
- Produces: `build_review_request(snapshot, routes, *, hard_bound: bool) -> dict`.
- Produces: `run_review_arm(snapshot, routes, measured_client, arm, repeat) -> dict`.
- A routes equal `snapshot["priorityRoutes"]` and preserve the current hard-bound system instruction.

- [ ] **Step 1: Write failing parity and routed-union tests**

```python
def test_arm_a_messages_match_existing_builder(project_state, model_route):
    snapshot = build_experiment_snapshot(project_state, "P-TEST")
    actual = build_review_request(snapshot, snapshot["priorityRoutes"], hard_bound=True)
    expected_snapshot = build_project_analysis_snapshot(
        project_state,
        "P-TEST",
        business_pack_id="engineering_inspection_v1",
        model_route=model_route,
    )
    expected = build_project_analysis_request(project_state, expected_snapshot)
    assert actual["messages"] == expected["messages"]

def test_soft_route_unions_priority_and_routed_files(snapshot):
    request = build_review_request(snapshot, {"1": ["DOC-NEW"]}, hard_bound=False)
    payload = json.loads(request["messages"][1]["content"])
    assert payload["project"]["nodes"][0]["fileRefs"] == [{"fileId": "DOC-OLD"}, {"fileId": "DOC-NEW"}]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_review.py -q`

- [ ] **Step 3: Implement the shared review executor**

For soft routes replace the two hard-bound rules with:

```text
priorityFileIds are preferred evidence, not an exclusive boundary.
routedFileIds are allowed evidence recovered from the same project's eligible current files.
Use only the union of priorityFileIds and routedFileIds for the current node.
```

Keep the existing output schema and validation path.

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_review.py tests/test_project_analysis_validation.py -q`

- [ ] **Step 5: Commit Task 3**

```bash
git add backend/libs/project_analysis_replay/review.py backend/libs/project_analysis_replay/arm_a.py backend/tests/test_project_analysis_replay_review.py
git commit -m "feat: replay the hard-bound analysis baseline"
```

### Task 4: Arm B full-OCR Map/Reduce router

**Files:**
- Create: `backend/libs/project_analysis_replay/arm_b.py`
- Test: `backend/tests/test_project_analysis_replay_arm_b.py`

**Interfaces:**
- Produces: `segment_full_ocr(snapshot, max_estimated_tokens) -> list[dict]`.
- Produces: `run_full_ocr_router(snapshot, measured_client, *, map_budget) -> dict`.
- Output fields: `routes`, `mapResults`, `coverage`, `validationErrors`, `fallbackUsed`.

- [ ] **Step 1: Write failing full-coverage and validation tests**

```python
def test_segments_cover_every_cleaned_character_once_except_declared_overlap(snapshot):
    segments = segment_full_ocr(snapshot, 4000)
    for file in snapshot["files"]:
        rebuilt = rebuild_without_overlap(segments, file["fileId"])
        assert rebuilt == file["cleanedOcrText"]

def test_map_quote_must_exist_in_segment(snapshot, fake_client):
    fake_client.response = {"fileRoutes": [{"fileId": "DOC-1", "segmentId": "S1", "matchedNodes": [{"nodeId": 1, "quotedText": "invented"}]}]}
    result = run_full_ocr_router(snapshot, fake_client, map_budget=4000)
    assert result["mapResults"][0]["validMatches"] == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_arm_b.py -q`

- [ ] **Step 3: Implement Map batching**

Every Map request carries all node profiles and whole files or continuous segments. Validate file, segment, node, score, reason code, and verbatim quote. Record `sourceChars`, `coveredChars`, `overlapChars`, and require `coverageRatio == 1.0` before review.

- [ ] **Step 4: Implement Reduce and deterministic fallback**

Reduce reads no OCR. It selects at most five added files per node. On invalid JSON or IDs, aggregate valid Map scores by `(nodeId, fileId)` and sort by descending max score, then file ID.

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_arm_b.py -q`

- [ ] **Step 6: Commit Task 4**

```bash
git add backend/libs/project_analysis_replay/arm_b.py backend/tests/test_project_analysis_replay_arm_b.py
git commit -m "feat: route full OCR with replay MapReduce"
```

### Task 5: Arm C hybrid retriever and LLM router

**Files:**
- Create: `backend/libs/project_analysis_replay/arm_c.py`
- Test: `backend/tests/test_project_analysis_replay_arm_c.py`

**Interfaces:**
- Produces: `chunk_snapshot_ocr(snapshot) -> list[dict]`.
- Produces: `HybridRetriever(embedding_client).retrieve(snapshot, top_files=8) -> dict[int, list[dict]]`.
- Produces: `run_hybrid_router(snapshot, candidates, measured_client) -> dict`.

- [ ] **Step 1: Write failing chunking, Top 8, and real-embedding guard tests**

```python
def test_hybrid_retriever_limits_each_node_to_eight_files(snapshot, semantic_embedder):
    result = HybridRetriever(semantic_embedder).retrieve(snapshot, top_files=8)
    assert all(len(files) <= 8 for files in result.values())

def test_hash_embedding_is_rejected(snapshot):
    with pytest.raises(RuntimeError, match="SEMANTIC_EMBEDDING_REQUIRED"):
        HybridRetriever(FakeEmbedder(model_id="offline-hash-v1")).retrieve(snapshot)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_arm_c.py -q`

- [ ] **Step 3: Implement stable OCR chunks and BM25**

Use 300–600 characters, page/table boundaries when present, and 80-character overlap. Build node queries from node name, criteria, check method, requirement names, and material type codes. Return Top 12 passages from BM25.

- [ ] **Step 4: Implement semantic retrieval and file aggregation**

Use `EmbeddingClient.embed_sync`; assert the configured model is not `offline-hash-v1`. Retrieve Top 12 dense passages, union with BM25, add a priority-binding bonus, retain three passages per file, then Top 8 files.

- [ ] **Step 5: Implement project-level LLM route and validation**

Deduplicate passages into one dictionary. The LLM may select at most five added files per node and only from that node's Top 8. Invalid output falls back to deterministic Top 3.

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_arm_c.py -q`

- [ ] **Step 7: Commit Task 5**

```bash
git add backend/libs/project_analysis_replay/arm_c.py backend/tests/test_project_analysis_replay_arm_c.py
git commit -m "feat: add semantic hybrid evidence routing replay"
```

### Task 6: Citation verifier, anonymized judge, and comparison report

**Files:**
- Create: `backend/libs/project_analysis_replay/evaluation.py`
- Create: `backend/libs/project_analysis_replay/report.py`
- Test: `backend/tests/test_project_analysis_replay_evaluation.py`

**Interfaces:**
- Produces: `verify_review_citations(snapshot, review_output) -> dict`.
- Produces: `build_blind_manifest(experiment_id, arms, seed) -> dict`.
- Produces: `run_blind_judge(snapshot, anonymous_outputs, measured_client) -> dict`.
- Produces: `render_comparison_report(experiment) -> str`.

- [ ] **Step 1: Write failing quote, anonymity, and aggregate tests**

```python
def test_quote_verifier_rejects_non_verbatim_text(snapshot):
    result = verify_review_citations(snapshot, output_with_quote("not in OCR"))
    assert result["validRate"] == 0

def test_judge_payload_does_not_leak_arm_names(snapshot):
    manifest = build_blind_manifest("EXP-1", ["A", "B", "C"], seed=7)
    payload = build_judge_payload(snapshot, manifest, outputs)
    assert '"A"' not in json.dumps(payload)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_evaluation.py -q`

- [ ] **Step 3: Implement deterministic metrics**

Calculate evidence additions, cross-node recovery, result distributions, false-quote count, valid ID rates, per-arm repeat Jaccard, conclusion agreement, usage, latency, cost, retries, and failures. Do not emit an `accuracy` field.

- [ ] **Step 4: Implement three-order blind judging**

For each node, compare anonymous candidates three times with rotated order. Judge on evidence sufficiency, rule coverage, citation truth, caution, and omission risk. Store win/loss/tie, order, rationale, and consistency. Label all judge output `relativeModelPreference`.

- [ ] **Step 5: Implement Markdown and JSON reports**

Report every node's priority files, routed additions, result changes, citation checks, repeat stability, blind preferences, tokens, elapsed time, cost, and failures. Include the no-gold-standard limitation at the top and conclusion.

- [ ] **Step 6: Run tests and commit**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_evaluation.py -q`

```bash
git add backend/libs/project_analysis_replay/evaluation.py backend/libs/project_analysis_replay/report.py backend/tests/test_project_analysis_replay_evaluation.py
git commit -m "feat: blind judge project analysis replay outputs"
```

### Task 7: CLI orchestration and production-state zero-diff gate

**Files:**
- Create: `backend/scripts/run_project_analysis_routing_replay.py`
- Test: `backend/tests/test_project_analysis_routing_replay_cli.py`

**Interfaces:**
- CLI: `python scripts/run_project_analysis_routing_replay.py --project-id P-2026-FDBB4B --repeats 3 --output-dir ../output/project-analysis-routing-replay`
- Options: `--arms A,B,C`, `--map-input-tokens`, `--judge-repeats`, `--resume`.
- Produces: `assert_formal_state_unchanged(expected_fingerprint, state) -> None`.

- [ ] **Step 1: Write failing dry-run and zero-diff tests**

```python
def test_cli_dry_run_builds_snapshot_without_model_calls(tmp_path, monkeypatch):
    result = main(["--project-id", "P-TEST", "--dry-run", "--output-dir", str(tmp_path)])
    assert result == 0

def test_cli_aborts_if_formal_state_changes(fake_repo, tmp_path):
    before = formal_state_fingerprint(fake_repo.state)
    fake_repo.state["projects"][0]["name"] = "changed"
    with pytest.raises(RuntimeError, match="FORMAL_STATE_CHANGED"):
        assert_formal_state_unchanged(before, fake_repo.state)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_routing_replay_cli.py -q`

- [ ] **Step 3: Implement resumable orchestration**

Write a stage completion manifest after each call. `--resume` validates snapshot hash, Git SHA, model routes, and completed artifact hashes before continuing. Never silently regenerate a completed stage with changed inputs.

- [ ] **Step 4: Implement final zero-diff gate**

Fingerprint formal state before snapshot and after all arms/judging. Abort the report as invalid if fingerprints differ. Artifact files are outside the fingerprint.

- [ ] **Step 5: Run CLI tests and all replay unit tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_project_analysis_replay_*.py tests/test_project_analysis_routing_replay_cli.py -q`

- [ ] **Step 6: Commit Task 7**

```bash
git add backend/scripts/run_project_analysis_routing_replay.py backend/tests/test_project_analysis_routing_replay_cli.py
git commit -m "feat: orchestrate isolated analysis routing replays"
```

### Task 8: Real service preflight and A/B/C replay execution

**Files:**
- Runtime: start the existing `backend/apps/embedding_service/main.py`; do not modify tracked configuration.
- Generate: `output/project-analysis-routing-replay/<experiment-id>/` and the artifact tree defined by the spec.

**Interfaces:**
- Consumes the Task 7 CLI.
- Produces three real repeats per arm plus blind judge and report artifacts.

- [ ] **Step 1: Verify local project and model services**

Run:

```bash
cd backend
.venv/bin/python scripts/run_project_analysis_routing_replay.py \
  --project-id P-2026-FDBB4B --repeats 3 --dry-run
```

Expected: 23 eligible files, 23 OCR-ready files, 30 included nodes, formal-state fingerprint present.

- [ ] **Step 2: Start and verify a real Embedding service**

Use `backend/apps/embedding_service/main.py` with the configured semantic model. Verify `/healthz` and one non-empty embedding. Record model ID, dimension, device, and service version in the experiment manifest. Reject `offline-hash-v1`.

- [ ] **Step 3: Run A/B/C three times**

```bash
cd backend
.venv/bin/python scripts/run_project_analysis_routing_replay.py \
  --project-id P-2026-FDBB4B \
  --arms A,B,C \
  --repeats 3 \
  --judge-repeats 3 \
  --output-dir ../output/project-analysis-routing-replay
```

The command may run for hours. Resume the same experiment ID after transient failures; never restart with a new snapshot unnoticed.

- [ ] **Step 4: Verify produced evidence**

Run a generated-artifact verifier that checks 3 successful repeats per arm, B coverage 100%, C semantic model not hash, all quote checks, all call measurements, three-order blind judging, and unchanged formal fingerprint.

- [ ] **Step 5: Run full regression verification**

Run:

```bash
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && pnpm test:unit && pnpm ts:check
```

- [ ] **Step 6: Commit implementation code only**

Do not commit OCR-bearing experiment artifacts unless explicitly requested.

```bash
git status --short
git log --oneline -8
```

### Task 9: Completion audit

**Files:**
- Inspect: spec, plan, experiment manifest, JSON metrics, Markdown report, test outputs, and Git diff.

- [ ] **Step 1: Verify each explicit objective requirement**

Confirm A hard binding, B full-OCR Map/Reduce, C Top 8 hybrid+LLM, same review constraints, no gold standard, three repeats, comprehensive metrics, zero formal writes, and reviewable report with direct artifact paths.

- [ ] **Step 2: Verify no unsupported accuracy claim**

Search report for `准确率` and `accuracy`; any occurrence must explicitly state that blind model preference is not ground-truth accuracy.

- [ ] **Step 3: Verify repository and runtime state**

Run `git diff --check`, targeted/full tests, artifact verifier, and formal fingerprint comparison fresh in the completion turn.

- [ ] **Step 4: Mark the active goal complete only after every gate passes**

Call the goal completion tool only when all three arms and the final report exist and every completion gate is proven.
