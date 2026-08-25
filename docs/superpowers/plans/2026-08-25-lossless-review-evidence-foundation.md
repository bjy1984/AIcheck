# Lossless Review Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical cumulative EvidenceSnapshot, EvidenceManifest, and EvidenceShard foundation so every active OCR artifact for a node is accounted for without silent array, table, or character truncation.

**Architecture:** A focused `review_evidence.py` module derives an immutable cumulative snapshot from all active node-mounted document versions, inventories every OCR artifact into a manifest, and partitions the manifest into lossless shards. Existing ReviewRun creation records the snapshot identity; prompt construction consumes complete shard payloads in later orchestration phases instead of dropping evidence.

**Tech Stack:** Python 3, FastAPI repository state collections, PostgreSQL JSONB state persistence, pytest, existing `stable_hash_payload` and ReviewRun contracts.

**Spec:** `docs/superpowers/specs/2026-08-25-project-auto-review-design.md`

## Global Constraints

- Automatic review remains advisory and must not change formal business state.
- A later upload triggers review, but the logical input is every currently active mounted document version for that node.
- A running ReviewRun uses an immutable snapshot; later evidence creates a different snapshot hash.
- No OCR field, table, seal, fragment, or evidence link may disappear through slicing or silent character truncation.
- Provider context limits are handled by creating more EvidenceShards, never by dropping artifacts.
- Historical document versions and ReviewRuns remain available for audit; only current active versions enter a new snapshot.
- Every task follows red-green-refactor and commits independently.

---

### Task 1: Canonical EvidenceSnapshot Contract

**Files:**
- Create: `backend/libs/review_evidence.py`
- Modify: `backend/libs/db/repository.py`
- Test: `backend/tests/test_review_evidence_snapshot.py`

**Interfaces:**
- Consumes: repository state collections `node_evidence_links`, `documents`, `document_versions`, `ocr_parse_results`, `rule_check_results`, and a `project_id/node_id` pair.
- Produces: `active_node_document_versions(state, project_id, node_id) -> list[dict[str, Any]]` and `build_evidence_snapshot(state, project_id, node_id, *, rule_version, clause_package_version, prompt_version, strategy_version) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing cumulative-snapshot tests**

```python
def test_snapshot_contains_all_current_mounted_documents():
    state = snapshot_state_with_versions("DV-LICENSE-V1", "DV-DRAWING-V1", "DV-SEAL-V1")
    snapshot = build_evidence_snapshot(
        state,
        "P-1",
        1,
        rule_version="r1",
        clause_package_version="c1",
        prompt_version="p1",
        strategy_version="s1",
    )
    assert [row["documentVersionId"] for row in snapshot["documentVersions"]] == [
        "DV-DRAWING-V1",
        "DV-LICENSE-V1",
        "DV-SEAL-V1",
    ]


def test_new_version_replaces_old_version_without_erasing_history():
    state = snapshot_state_with_superseded_version("DOC-1", "DV-1-V1", "DV-1-V2")
    snapshot = build_evidence_snapshot(
        state,
        "P-1",
        1,
        rule_version="r1",
        clause_package_version="c1",
        prompt_version="p1",
        strategy_version="s1",
    )
    assert [row["documentVersionId"] for row in snapshot["documentVersions"]] == ["DV-1-V2"]
    assert any(row["id"] == "DV-1-V1" for row in state["document_versions"])


def test_rejected_or_unmounted_links_are_not_active():
    state = snapshot_state_with_rejected_link()
    snapshot = build_evidence_snapshot(
        state,
        "P-1",
        1,
        rule_version="r1",
        clause_package_version="c1",
        prompt_version="p1",
        strategy_version="s1",
    )
    assert snapshot["documentVersions"] == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `cd backend && pytest -q tests/test_review_evidence_snapshot.py`

Expected: FAIL because `libs.review_evidence` does not exist.

- [ ] **Step 3: Add the snapshot collections to repository state**

Add these mappings and `setdefault` calls in `backend/libs/db/repository.py`:

```python
"evidence_snapshots": "evidence_snapshots",
"evidence_manifests": "evidence_manifests",
"evidence_shards": "evidence_shards",
```

- [ ] **Step 4: Implement active cumulative document selection**

```python
def active_node_document_versions(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    links = [
        row
        for row in state.get("node_evidence_links", [])
        if str(row.get("projectId")) == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
        and str(row.get("manualStatus") or "").lower() != "rejected"
        and row.get("documentVersionId")
    ]
    documents = {
        str(row.get("id")): row
        for row in state.get("documents", [])
        if str(row.get("projectId")) == str(project_id)
    }
    active: dict[str, dict[str, Any]] = {}
    for link in links:
        document = documents.get(str(link.get("documentId")))
        if not document:
            continue
        current_version_id = str(document.get("currentVersionId") or "")
        if current_version_id and str(link.get("documentVersionId")) != current_version_id:
            continue
        active[current_version_id or str(link["documentVersionId"])] = {
            "documentId": document["id"],
            "documentVersionId": current_version_id or str(link["documentVersionId"]),
            "mountRevision": int(link.get("revision") or 0),
        }
    return sorted(active.values(), key=lambda row: row["documentVersionId"])
```

- [ ] **Step 5: Implement immutable snapshot hashing**

```python
def build_evidence_snapshot(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    rule_version: str,
    clause_package_version: str,
    prompt_version: str,
    strategy_version: str,
) -> dict[str, Any]:
    document_versions = active_node_document_versions(state, project_id, node_id)
    payload = {
        "projectId": project_id,
        "nodeId": int(node_id),
        "documentVersions": enrich_with_ocr_hashes(state, document_versions),
        "ruleVersion": rule_version,
        "clausePackageVersion": clause_package_version,
        "promptVersion": prompt_version,
        "strategyVersion": strategy_version,
    }
    snapshot_hash = stable_hash_payload(payload)
    return {
        "evidenceSnapshotId": f"ESNAP-{snapshot_hash[7:23].upper()}",
        **payload,
        "snapshotHash": snapshot_hash,
        "createdAt": server_time(),
    }
```

- [ ] **Step 6: Run tests and verify GREEN**

Run: `cd backend && pytest -q tests/test_review_evidence_snapshot.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/libs/review_evidence.py backend/libs/db/repository.py backend/tests/test_review_evidence_snapshot.py
git commit -m "feat: add cumulative review evidence snapshots"
```

---

### Task 2: Lossless EvidenceManifest Inventory

**Files:**
- Modify: `backend/libs/review_evidence.py`
- Test: `backend/tests/test_review_evidence_manifest.py`

**Interfaces:**
- Consumes: an EvidenceSnapshot and matching `ocr_parse_results`, `extracted_fields`, and `evidence_links`.
- Produces: `build_evidence_manifest(state, snapshot) -> dict[str, Any]` with stable artifact IDs and exact expected counts.

- [ ] **Step 1: Write failing manifest completeness tests**

```python
def test_manifest_inventories_every_artifact_without_caps():
    state, snapshot = manifest_state(
        fields=95,
        tables=24,
        seals=23,
        fragments=130,
        evidence_links=90,
    )
    manifest = build_evidence_manifest(state, snapshot)
    assert manifest["counts"] == {
        "fields": 95,
        "tables": 24,
        "seals": 23,
        "fragments": 130,
        "evidenceLinks": 90,
        "total": 362,
    }
    assert len(manifest["artifacts"]) == 362


def test_manifest_preserves_full_table_rows_and_cells():
    state, snapshot = manifest_state_with_table(rows=75, cells=205)
    manifest = build_evidence_manifest(state, snapshot)
    table = next(row for row in manifest["artifacts"] if row["artifactType"] == "table")
    assert len(table["payload"]["rows"]) == 75
    assert len(table["payload"]["cells"]) == 205
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest -q tests/test_review_evidence_manifest.py`

Expected: FAIL because `build_evidence_manifest` is missing.

- [ ] **Step 3: Implement normalized artifact records**

```python
def manifest_artifact(artifact_type, version_id, source_id, payload):
    artifact_hash = stable_hash_payload(
        {"artifactType": artifact_type, "documentVersionId": version_id, "payload": payload}
    )
    return {
        "artifactId": f"EART-{artifact_hash[7:23].upper()}",
        "artifactType": artifact_type,
        "documentVersionId": version_id,
        "sourceId": source_id,
        "payload": payload,
        "contentHash": artifact_hash,
    }
```

Fields, tables, seals, fragments, and evidence links must be traversed without `[:N]` slices. Table payloads must retain every row and cell supplied by OCR.

- [ ] **Step 4: Implement manifest count and hash verification**

```python
manifest = {
    "evidenceManifestId": f"EMAN-{snapshot['snapshotHash'][7:23].upper()}",
    "evidenceSnapshotId": snapshot["evidenceSnapshotId"],
    "documents": documents,
    "artifacts": artifacts,
    "counts": count_artifacts(artifacts),
}
manifest["manifestHash"] = stable_hash_payload(manifest)
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd backend && pytest -q tests/test_review_evidence_manifest.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/libs/review_evidence.py backend/tests/test_review_evidence_manifest.py
git commit -m "feat: inventory complete OCR evidence manifests"
```

---

### Task 3: EvidenceShard Partitioning and Coverage Gate

**Files:**
- Modify: `backend/libs/review_evidence.py`
- Test: `backend/tests/test_review_evidence_shards.py`

**Interfaces:**
- Consumes: EvidenceManifest and `max_shard_estimated_tokens` used only as a partition size.
- Produces: `build_evidence_shards(manifest, *, max_shard_estimated_tokens) -> list[dict[str, Any]]` and `evidence_coverage_report(manifest, shards) -> dict[str, Any]`.

- [ ] **Step 1: Write failing lossless partition tests**

```python
def test_sharding_changes_call_count_not_evidence_count():
    manifest = large_manifest(artifact_count=250)
    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=2000)
    report = evidence_coverage_report(manifest, shards)
    assert len(shards) > 1
    assert report["expectedArtifactCount"] == 250
    assert report["processedArtifactCount"] == 250
    assert report["missingArtifactIds"] == []
    assert report["duplicateArtifactIds"] == []
    assert report["coveragePassed"] is True


def test_one_oversized_table_is_split_by_rows_without_losing_cells():
    manifest = manifest_with_oversized_table(rows=150)
    shards = build_evidence_shards(manifest, max_shard_estimated_tokens=1200)
    reconstructed = reconstruct_table_rows(shards)
    assert reconstructed == manifest_table_rows(manifest)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest -q tests/test_review_evidence_shards.py`

Expected: FAIL because shard functions are missing.

- [ ] **Step 3: Implement natural-boundary partitioning**

Partition in this order:

1. document version;
2. page number;
3. table or certificate/report block;
4. fragment boundary;
5. table row groups only when one table exceeds the target shard size.

The size target may create more shards but must never omit an artifact.

- [ ] **Step 4: Implement coverage reporting**

```python
def evidence_coverage_report(manifest, shards):
    expected = [row["artifactId"] for row in manifest["artifacts"]]
    processed = [artifact_id for shard in shards for artifact_id in shard["artifactIds"]]
    return {
        "expectedShardCount": len(shards),
        "completedShardCount": sum(row.get("status") == "completed" for row in shards),
        "failedShardCount": sum(row.get("status") == "failed" for row in shards),
        "expectedArtifactCount": len(expected),
        "processedArtifactCount": len(set(processed)),
        "missingArtifactIds": sorted(set(expected) - set(processed)),
        "duplicateArtifactIds": duplicate_values(processed),
        "coveragePassed": set(expected) == set(processed) and len(processed) == len(set(processed)),
    }
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd backend && pytest -q tests/test_review_evidence_shards.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/libs/review_evidence.py backend/tests/test_review_evidence_shards.py
git commit -m "feat: partition lossless review evidence shards"
```

---

### Task 4: Record Snapshot, Manifest, and Shards on Node ReviewRun

**Files:**
- Modify: `backend/apps/api/routes.py`
- Modify: `backend/libs/review_orchestrator/execution.py`
- Modify: `backend/libs/db/repository.py`
- Test: `backend/tests/test_review_evidence_run_integration.py`

**Interfaces:**
- Consumes: snapshot, manifest, and shard builders from Tasks 1-3.
- Produces: ReviewRun fields `evidenceSnapshotId`, `evidenceSnapshotHash`, `evidenceManifestId`, `evidenceShardIds`, and `evidenceCoverage`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_later_upload_review_run_uses_all_active_node_documents(client):
    mount_and_ocr(client, node_id=1, version_id="DV-LICENSE-V1")
    first = start_review(client, node_id=1)
    mount_and_ocr(client, node_id=1, version_id="DV-DRAWING-V1")
    second = start_review(client, node_id=1)
    assert first["evidenceSnapshotHash"] != second["evidenceSnapshotHash"]
    assert second["inputDocumentVersionIds"] == ["DV-DRAWING-V1", "DV-LICENSE-V1"]


def test_review_run_persists_manifest_and_all_shard_ids(client):
    run = start_large_review(client)
    assert run["evidenceManifestId"]
    assert len(run["evidenceShardIds"]) > 1
    assert run["evidenceCoverage"]["coveragePassed"] is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest -q tests/test_review_evidence_run_integration.py`

Expected: FAIL because ReviewRun lacks evidence snapshot fields.

- [ ] **Step 3: Build and persist the immutable evidence package during ReviewRun creation**

After selecting all current node document versions, call:

```python
snapshot = build_evidence_snapshot(
    repo.state,
    project_id,
    node_id,
    rule_version=str(rule.get("version") or "ruleset-v1"),
    clause_package_version=str((clause_package_snapshot or {}).get("snapshotHash") or "none"),
    prompt_version=f"node-{node_id}-v1",
    strategy_version="node-review-strategy-v1",
)
manifest = build_evidence_manifest(repo.state, snapshot)
shards = build_evidence_shards(manifest, max_shard_estimated_tokens=review_shard_target_tokens())
coverage = evidence_coverage_report(manifest, shards)
```

Persist all records before dispatch and add their IDs and hashes to the ReviewRun.

- [ ] **Step 4: Load the new collections in ReviewRun worker scope**

Add `evidence_snapshots`, `evidence_manifests`, and `evidence_shards` to `load_review_run_state` and all ReviewRun flush/persistence scopes.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd backend && pytest -q tests/test_review_evidence_run_integration.py`

Expected: PASS.

- [ ] **Step 6: Run existing ReviewRun regressions**

Run: `cd backend && pytest -q tests/test_review_p0_correctness.py tests/test_review_input_budget_unlimited.py tests/test_contract.py -k 'grounded or ai_recheck or review_run'`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/api/routes.py backend/libs/review_orchestrator/execution.py backend/libs/db/repository.py backend/tests/test_review_evidence_run_integration.py
git commit -m "feat: persist lossless evidence packages on review runs"
```

---

### Task 5: Remove Silent Grounding Collection Caps

**Files:**
- Modify: `backend/libs/review_grounding.py`
- Modify: `backend/libs/review_orchestrator/evidence_budget.py`
- Test: `backend/tests/test_review_grounding_no_silent_truncation.py`
- Modify: `backend/tests/test_evidence_budget.py`

**Interfaces:**
- Consumes: exact document versions in the immutable EvidenceSnapshot.
- Produces: complete `EvidenceGroundedReviewInput@2.0.0` plus an EvidenceManifest reference; no document-dropping budget path.

- [ ] **Step 1: Write failing no-cap tests**

```python
def test_grounding_keeps_more_than_legacy_caps():
    state = grounding_state(fields=95, tables=24, seals=23, fragments=130, links=90)
    grounded = build_grounded_review_input(state, {"DV-1"})
    assert len(grounded["fields"]) == 95
    assert len(grounded["tables"]) == 24
    assert len(grounded["seals"]) == 23
    assert len(grounded["fragments"]) == 130
    assert len(grounded["evidenceLinks"]) == 90


def test_oversized_table_is_not_character_truncated():
    state = grounding_state_with_table(markdown="X" * 9000, rows=75, cells=205)
    grounded = build_grounded_review_input(state, {"DV-1"})
    table = grounded["tables"][0]
    assert len(table["contentMarkdown"]) == 9000
    assert len(table["rows"]) == 75
    assert len(table["cells"]) == 205
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest -q tests/test_review_grounding_no_silent_truncation.py`

Expected: FAIL at the legacy 80/20/60/160/6000 limits.

- [ ] **Step 3: Remove collection and table caps**

Remove the slices in `build_grounded_review_input`, `_table_evidence`, `_table_markdown`, `_markdown_from_rows`, `_markdown_from_cells`, and `_table_cells_summary`. Keep normalization but return every source artifact.

- [ ] **Step 4: Retire document-dropping budget behavior from active ReviewRun flow**

`AICHECK_REVIEW_MAX_INPUT_TOKENS=0` remains unlimited. Positive values may set the target shard size for compatibility, but `trim_evidence_to_budget` must no longer remove documents from an active ReviewRun. Replace active callers with EvidenceShard partitioning.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `cd backend && pytest -q tests/test_review_grounding_no_silent_truncation.py tests/test_review_input_budget_unlimited.py`

Expected: PASS.

- [ ] **Step 6: Run broader grounding regressions**

Run: `cd backend && pytest -q tests/test_review_p0_correctness.py tests/test_grounding_downgrade_keeps_diagnosis.py tests/test_evidence_budget.py`

Expected: PASS after updating legacy evidence-budget tests to assert shard partitioning rather than dropped document lists.

- [ ] **Step 7: Commit**

```bash
git add backend/libs/review_grounding.py backend/libs/review_orchestrator/evidence_budget.py backend/tests/test_review_grounding_no_silent_truncation.py backend/tests/test_evidence_budget.py
git commit -m "fix: remove silent review evidence truncation"
```

---

### Task 6: Generate Full Test/Test2 Evidence Packages from the Canonical Builder

**Files:**
- Create: `backend/scripts/export_review_evidence_package.py`
- Modify: `output/two_project_ai_review_20260825/ai_full_review_prompt.md`
- Modify: `output/two_project_ai_review_20260825/ai_full_review_prompt_test.md`
- Modify: `output/two_project_ai_review_20260825/ai_full_review_prompt_test2.md`
- Create: `output/two_project_ai_review_20260825/evidence_shards/test/manifest.json`
- Create: `output/two_project_ai_review_20260825/evidence_shards/test2/manifest.json`
- Test: `backend/tests/test_export_review_evidence_package.py`

**Interfaces:**
- Consumes: canonical EvidenceSnapshot/Manifest/Shard builders and project IDs `P-TEST-OCR-001`, `P-TEST-OCR-002`.
- Produces: deterministic Markdown entry prompts plus JSON shard packages whose manifests prove 100% artifact coverage.

- [ ] **Step 1: Write failing export tests**

```python
def test_exported_test_package_contains_full_design_license(tmp_path):
    export_project_review_package(state_for_test_project(), "P-TEST-OCR-001", tmp_path)
    payload = read_all_shards(tmp_path / "evidence_shards/test")
    assert "TS1844171-2028" in payload
    assert "工业管道(GC1)" in payload
    assert "GC1级覆盖GC2级" in payload


def test_exported_manifest_has_full_coverage(tmp_path):
    result = export_project_review_package(state_for_test_project(), "P-TEST-OCR-001", tmp_path)
    assert result["coverage"]["coveragePassed"] is True
    assert result["coverage"]["missingArtifactIds"] == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && pytest -q tests/test_export_review_evidence_package.py`

Expected: FAIL because the exporter does not exist.

- [ ] **Step 3: Implement deterministic export**

The exporter must write a small orchestration Markdown file and separate shard JSON files. It must not paste all OCR into one model request.

- [ ] **Step 4: Generate test and test2 packages**

Run:

```bash
cd backend
python scripts/export_review_evidence_package.py --project-id P-TEST-OCR-001 --output ../output/two_project_ai_review_20260825
python scripts/export_review_evidence_package.py --project-id P-TEST-OCR-002 --output ../output/two_project_ai_review_20260825
```

Expected: both manifests report `coveragePassed: true`.

- [ ] **Step 5: Run export tests and inspect manifests**

Run: `cd backend && pytest -q tests/test_export_review_evidence_package.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/export_review_evidence_package.py backend/tests/test_export_review_evidence_package.py output/two_project_ai_review_20260825
git commit -m "feat: export complete review evidence packages"
```

---

### Task 7: Foundation Verification Gate

**Files:**
- Modify: `backend/scripts/deployment_report.py`
- Test: `backend/tests/test_deployment_report.py`

**Interfaces:**
- Consumes: persisted evidence snapshots, manifests, shards, and coverage reports.
- Produces: deployment gate `review.lossless-evidence-coverage`.

- [ ] **Step 1: Write the failing deployment gate test**

```python
def test_lossless_evidence_gate_fails_for_missing_artifact():
    report = build_lossless_evidence_gate(
        manifests=[{"expectedArtifactCount": 10}],
        coverage=[{"processedArtifactCount": 9, "coveragePassed": False}],
    )
    assert report["status"] == "blocked"
    assert report["missingArtifactCount"] == 1
```

- [ ] **Step 2: Run test and verify RED**

Run: `cd backend && pytest -q tests/test_deployment_report.py -k lossless_evidence`

Expected: FAIL because the gate is missing.

- [ ] **Step 3: Implement the deployment gate**

The gate passes only when every reviewed manifest has `coveragePassed=true`, no missing artifact IDs, no duplicates, and no completed ReviewRun with incomplete shards.

- [ ] **Step 4: Run focused and full foundation tests**

Run:

```bash
cd backend
pytest -q tests/test_deployment_report.py -k lossless_evidence
pytest -q \
  tests/test_review_evidence_snapshot.py \
  tests/test_review_evidence_manifest.py \
  tests/test_review_evidence_shards.py \
  tests/test_review_evidence_run_integration.py \
  tests/test_review_grounding_no_silent_truncation.py \
  tests/test_export_review_evidence_package.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/deployment_report.py backend/tests/test_deployment_report.py
git commit -m "test: gate lossless review evidence coverage"
```

## Follow-on Plans

After this foundation is green, create and execute these plans against the same spec:

1. `2026-08-25-project-auto-review-orchestration.md` — AutoReviewPolicy, Outbox events, daily scanner, ProjectReviewRun parent, cumulative dirty/hash idempotency, and Celery tasks.
2. `2026-08-25-project-auto-review-workbench.md` — project-level enable/disable control, settings drawer, status display, permissions, API client, and UI tests.
3. `2026-08-25-project-auto-review-rollout.md` — migrations, observability, replay, failure recovery, end-to-end tests, and release gates.
