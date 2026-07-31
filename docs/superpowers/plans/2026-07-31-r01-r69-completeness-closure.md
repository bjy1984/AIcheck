# R01-R69 Completeness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing acceptance pack to 76 logical documents and 136 generated files, bind 12 immutable source PDFs, close data discrepancies, add safe test-only signature forms and R69 execution evidence, and pass automated plus visual QA.

**Architecture:** Keep the existing deterministic catalog/content/render/build/validate pipeline. Add image-only evidence documents, source-evidence and closure payloads, and a reusable test-seal renderer; compute source and output digests during the build so generated ledgers remain reproducible. Treat original PDFs as referenced evidence outside the generated subtree to avoid duplicating about 110 MB.

**Tech Stack:** Bundled Python 3.12, `unittest`, `python-docx`, Pillow, ReportLab, pypdf, Poppler, bundled Node.js, and `@oai/artifact-tool` 2.8.6+.

## Global Constraints

- Work only in `/Volumes/7up/github/knowledgetools/.worktrees/r01-r69-pr-clean` on `codex/r01-r69-acceptance-pack-pr`.
- Output root remains exactly `files/R01-R69全节点业务验收测试包/`.
- Existing source drawings, certificates, scans, and OCR files remain byte-for-byte unchanged.
- Final generated counts are exactly 76 logical documents and 136 physical files: 31 DOCX, 29 XLSX, 61 PDF, and 15 JPG.
- Bind exactly 12 existing source PDFs, yielding a 148-file evidence universe without copying them into the generated subtree.
- Keep exactly 69 nodes, 166 external-material requirements, 11 lines, 30 welds, and 5 primary material batches.
- Every synthetic seal/signature must visibly contain `TEST` or `测试专用`; never imitate an official seal, real handwriting, QR code, or anti-counterfeit feature.
- Never emit full national ID numbers into generated artifacts.
- Construction-photo OCR attempts remain exactly 0.
- Use the bundled runtime paths returned by `load_workspace_dependencies`; do not mutate the managed dependency directory.
- Use `@oai/artifact-tool` for XLSX authoring and visually render every populated sheet before export.

---

### Task 1: Make LibreOffice Conversion First-Run Safe

**Files:**
- Modify: `scripts/r01_r69_pack/convert_pdf.py`
- Modify: `scripts/r01_r69_pack/tests/test_renderers.py`

**Interfaces:**
- Produces: `libreoffice_environment(font_root: Path) -> dict[str, str]`
- Preserves: `convert_office_to_pdf(source: Path, output_dir: Path) -> Path`

- [x] **Step 1: Write a failing regression test**

```python
def test_libreoffice_font_setup_uses_writable_temp_directory(self):
    with TemporaryDirectory() as tmp:
        env = libreoffice_environment(Path(tmp))
        font_dir = Path(env["SAL_FONTPATH"])
        self.assertTrue(font_dir.is_dir())
        self.assertTrue(font_dir.joinpath("ArialUnicode.ttf").exists())
        self.assertFalse(str(font_dir).startswith(str(LO_FONT_DIR)))
```

- [x] **Step 2: Run the targeted test and verify RED**

Run:

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers.RendererTest.test_libreoffice_font_setup_uses_writable_temp_directory -v
```

Expected: FAIL because `libreoffice_environment` does not exist.

- [x] **Step 3: Implement one writable-font environment**

Copy the available CJK font with `shutil.copyfile` into a temporary `fonts/` directory owned by the conversion call, set `SAL_FONTPATH` for the subprocess, and remove `ensure_libreoffice_cjk_font()` plus all writes to `LO_FONT_DIR`. Pass the prepared environment only to the `soffice` subprocess.

- [x] **Step 4: Run renderer tests and verify GREEN**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers -v
```

Expected: all renderer tests pass on a clean first invocation.

- [x] **Step 5: Commit**

```bash
git add scripts/r01_r69_pack/convert_pdf.py scripts/r01_r69_pack/tests/test_renderers.py
git commit -m "fix: isolate LibreOffice font setup"
```

### Task 2: Expand the Catalog and Evidence Attachment Contract

**Files:**
- Modify: `scripts/r01_r69_pack/catalog.py`
- Modify: `scripts/r01_r69_pack/data/document_catalog.json`
- Modify: `scripts/r01_r69_pack/tests/test_catalog.py`

**Interfaces:**
- Produces: 76 `DocumentSpec` rows and 136 physical extensions.
- Adds image logical IDs: `S01-PHOTO-001`, `B00-PHOTO-001` through `B00-PHOTO-004`, `S04-PHOTO-002` through `S04-PHOTO-006`, `B00-FILM-001`, `B00-FILM-002`, `S06-FILM-001`, and `B00-QUERY-001`.
- Adds control logical IDs: `M00-SOURCE-001`, `M00-DATA-001`, `M00-SEAL-001`, and `V00-R69-001`.

- [x] **Step 1: Change count tests first**

```python
def test_exact_logical_and_physical_counts(self):
    catalog = load_catalog(CATALOG_PATH)
    self.assertEqual(len(catalog.documents), 76)
    self.assertEqual(catalog.expected_physical_file_count(), 136)
    self.assertEqual(
        catalog.logical_counts_by_folder(),
        {"M00": 7, "B00": 19, "S01": 8, "S02": 5,
         "S03": 9, "S04": 11, "S05": 5, "S06": 6, "V00": 6},
    )
```

Add a second test asserting 11 photo IDs, 3 film IDs, 1 query ID, and `V00-R69-001.r_nodes == (69,)`.

- [x] **Step 2: Run and verify RED**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_catalog -v
```

Expected: FAIL with the old 58/114 counts and missing logical IDs.

- [x] **Step 3: Add catalog rows and safe R69 validation**

Allow R69 only on `V00-R69-001` in folder `V00`; keep the snapshot requirement list for R69 empty. Keep every other R69 file binding invalid. Generate the JSON catalog from `catalog.py`.

- [x] **Step 4: Run catalog tests and verify GREEN**

```bash
$PACK_PY -m scripts.r01_r69_pack.catalog
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_catalog -v
```

- [x] **Step 5: Commit**

```bash
git add scripts/r01_r69_pack/catalog.py scripts/r01_r69_pack/data/document_catalog.json scripts/r01_r69_pack/tests/test_catalog.py
git commit -m "feat: define comprehensive evidence attachments"
```

### Task 3: Bind Requirements, Source Identities, and Standards Correctly

**Files:**
- Modify: `scripts/r01_r69_pack/node_snapshot.py`
- Modify: `scripts/r01_r69_pack/data/requirement_map.json`
- Modify: `scripts/r01_r69_pack/data/project_master.json`
- Modify: `scripts/r01_r69_pack/content_factory.py`
- Modify: `scripts/r01_r69_pack/data/content/M00.json`
- Modify: `scripts/r01_r69_pack/tests/test_node_snapshot.py`
- Modify: `scripts/r01_r69_pack/tests/test_model.py`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`

**Interfaces:**
- Produces: `_attachment_for(node: int, material_type: str) -> str | None`
- Produces: `_evidence_locator(node: int, material_type: str, logical_id: str) -> str`
- Adds raw master sections `sourceEvidence` and `sourceTruth` while preserving the typed model's 11/30/5 object counts.

- [x] **Step 1: Write failing requirement-binding tests**

```python
def test_visual_requirements_bind_independent_attachments(self):
    snapshot = load_node_snapshot(REQUIREMENT_MAP)
    photos = [r.logical_document_id for r in snapshot.requirements
              if r.material_type_code == "field_photo"]
    films = [r.logical_document_id for r in snapshot.requirements
             if r.material_type_code == "radiographic_film"]
    queries = [r.logical_document_id for r in snapshot.requirements
               if r.material_type_code == "external_query_screenshot"]
    self.assertEqual(len(photos), 11)
    self.assertEqual(len(set(photos)), 11)
    self.assertEqual(len(films), 3)
    self.assertEqual(len(set(films)), 3)
    self.assertEqual(queries, ["B00-QUERY-001"])
```

Add tests asserting source locators contain a repository-relative PDF path and page locator for source-backed base requirements; generated master data contains the six source organizations, source people/certificates without a full 18-digit national ID; and standard rows use the exact names `工业管道安全技术规程`, `承压类特种设备安全附件安全技术规程`, and `特种设备使用管理规则`.

- [x] **Step 2: Run targeted tests and verify RED**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_node_snapshot scripts.r01_r69_pack.tests.test_model scripts.r01_r69_pack.tests.test_scenarios -v
```

Expected: attachment uniqueness, source identities, and corrected standards assertions fail.

- [x] **Step 3: Implement attachment mapping and page locators**

Map `field_photo` by R node, map film nodes R41/R42/R65, and map R24 query evidence. Keep generated scenario files as the logical document for other requirements, but enrich base-source locators with paths such as `files/设计资料.pdf#p1-p10` or `Scan/20260623105636.pdf#p1-p5`.

- [x] **Step 4: Add source identities and truth domains**

Add source-era organizations and certificates for 贵州化工建设有限责任公司, 南京金鑫检测工程有限责任公司, 广州声华科技股份有限公司, 广东省特种设备检测研究院珠海检测院, 河北广浩管件有限公司, and 烟台鲁宝钢管有限责任公司. Add source-era people only where OCR evidence is explicit; never store full national IDs. Add `sourceTruth` records for design wall thickness, as-built wall thickness, medium confidence, line aliases, NDT role split, and certificate validity scope.

- [x] **Step 5: Correct the standards table**

Use explicit identifiers, exact titles, implementation dates, project/scenario applicability, and official URLs. Record TSG Z6002-2026 as published but not effective on the pack date 2026-07-15.

- [x] **Step 6: Regenerate JSON and verify GREEN**

```bash
$PACK_PY -m scripts.r01_r69_pack.node_snapshot
$PACK_PY -m scripts.r01_r69_pack.content_factory
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_node_snapshot scripts.r01_r69_pack.tests.test_model scripts.r01_r69_pack.tests.test_scenarios -v
```

- [x] **Step 7: Commit**

```bash
git add scripts/r01_r69_pack/node_snapshot.py scripts/r01_r69_pack/content_factory.py \
  scripts/r01_r69_pack/data/project_master.json scripts/r01_r69_pack/data/requirement_map.json \
  scripts/r01_r69_pack/data/content scripts/r01_r69_pack/tests/test_node_snapshot.py \
  scripts/r01_r69_pack/tests/test_model.py scripts/r01_r69_pack/tests/test_scenarios.py
git commit -m "feat: reconcile source evidence and standards"
```

### Task 4: Render Safe Test Seals and Evidence Images

**Files:**
- Create: `scripts/r01_r69_pack/test_seal.py`
- Modify: `scripts/r01_r69_pack/render_docx.py`
- Modify: `scripts/r01_r69_pack/render_xlsx.py`
- Modify: `scripts/r01_r69_pack/render_xlsx.mjs`
- Modify: `scripts/r01_r69_pack/render_graphics.py`
- Modify: `scripts/r01_r69_pack/render_common.py`
- Modify: `scripts/r01_r69_pack/tests/test_renderers.py`

**Interfaces:**
- Produces: `render_test_seal_png(label: str, role: str) -> bytes`
- Produces: `signature_contract(content: dict) -> dict[str, str]`
- Extends: `render_test_photo` to support `graphic_kind` values `field_photo`, `radiographic_film`, and `external_query_screenshot`.

- [x] **Step 1: Write failing signature and image tests**

Add tests that render one DOCX, one XLSX, one diagram PDF, one photo, one film, and one query screenshot. Assert every artifact has the warning; DOCX and XLSX ZIP packages contain embedded PNG media; extracted text/metadata includes `电子签署（测试）` or `测试专用章`; and all three image types open with different dimensions/content metadata.

- [x] **Step 2: Run and verify RED**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers -v
```

Expected: missing seal module, no embedded sheet/document image, and unsupported image kinds.

- [x] **Step 3: Implement deterministic test seal graphics**

Generate a rectangular or rounded badge containing `TEST`, `测试专用`, the synthetic responsibility role, and `不得用于真实工程`. Use a fixed typeface and no official-emblem, statutory company-name ring, serial security pattern, or handwriting simulation.

- [x] **Step 4: Embed the contract in DOCX and XLSX**

DOCX approval tables receive three small signature badges plus one category badge. The artifact-tool builder adds a badge image and signed-status cells to every populated worksheet without covering business data. All paired PDFs inherit the same visuals.

- [x] **Step 5: Implement three evidence-image layouts**

Field-photo images use neutral engineering diagrams and an explicit no-OCR statement. Film images use a simulated radiographic panel with weld/film IDs and a non-evidence warning. Query screenshots use an offline test UI with a masked certificate query and `非官方查询结果`.

- [x] **Step 6: Run renderer tests and verify GREEN**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers -v
```

- [x] **Step 7: Commit**

```bash
git add scripts/r01_r69_pack/test_seal.py scripts/r01_r69_pack/render_docx.py \
  scripts/r01_r69_pack/render_xlsx.py scripts/r01_r69_pack/render_xlsx.mjs \
  scripts/r01_r69_pack/render_graphics.py scripts/r01_r69_pack/render_common.py \
  scripts/r01_r69_pack/tests/test_renderers.py
git commit -m "feat: add safe test-only signature forms"
```

### Task 5: Generate Source, Closure, Seal, and R69 Records

**Files:**
- Modify: `scripts/r01_r69_pack/content_factory.py`
- Modify: `scripts/r01_r69_pack/build_pack.py`
- Modify: `scripts/r01_r69_pack/data/content/M00.json`
- Modify: `scripts/r01_r69_pack/data/content/B00.json`
- Modify: `scripts/r01_r69_pack/data/content/S01.json`
- Modify: `scripts/r01_r69_pack/data/content/S04.json`
- Modify: `scripts/r01_r69_pack/data/content/S06.json`
- Modify: `scripts/r01_r69_pack/data/content/V00.json`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`

**Interfaces:**
- Produces: `populate_source_evidence_rows(content, workspace) -> None`
- Produces: `populate_seal_registry_rows(content, catalog) -> None`
- Produces scenario data keys `sourceEvidence`, `dataClosures`, `signatureRegistry`, and `r69Workflow`.

- [x] **Step 1: Write failing content-chain tests**

Assert exactly 12 source-evidence rows with non-empty paths/page counts/digests, five named data closures all in `已闭环`, 76 seal-registry rows, and an R69 timeline `发现定位缺页 -> 补录页码与哈希 -> 复核合格 -> 合格闭环`.

- [x] **Step 2: Run and verify RED**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_scenarios -v
```

- [x] **Step 3: Author the four new control documents**

Source ledger sheets: original files, page-level bindings, identity reuse, and privacy status. Data report sections: wall thickness, medium, scope aliases, NDT role split, and certificate validity. Seal registry sheets: 76 logical-document rows plus role/type definitions. R69 workbook sheets: execution summary, samples, finding closure, approvals, and final evaluation.

- [x] **Step 4: Author the 14 image payloads**

Give each attachment a unique object ID, node, caption, date, graphic kind, and warning. Ensure the existing `S04-PHOTO-001` remains the R48 attachment and new IDs cover the remaining requirements without cross-scenario references.

- [x] **Step 5: Populate dynamic SHA-256 rows during build**

Before rendering `M00-SOURCE-001`, hash the 12 source PDFs and verify page counts with pypdf. Before rendering `M00-SEAL-001`, populate all catalog rows. Preserve the existing self-reference exclusion only for `V00-CHECKSUM-001`.

- [x] **Step 6: Regenerate content and verify GREEN**

```bash
$PACK_PY -m scripts.r01_r69_pack.content_factory
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_scenarios -v
```

- [x] **Step 7: Commit**

```bash
git add scripts/r01_r69_pack/content_factory.py scripts/r01_r69_pack/build_pack.py \
  scripts/r01_r69_pack/data/content scripts/r01_r69_pack/tests/test_scenarios.py
git commit -m "feat: generate completeness closure records"
```

### Task 6: Enforce Comprehensive Validation

**Files:**
- Modify: `scripts/r01_r69_pack/validate_pack.py`
- Modify: `scripts/r01_r69_pack/tests/test_validate_pack.py`

**Interfaces:**
- Extends `ValidationReport.metrics` with `referenced_source_files`, `evidence_universe_files`, `field_photos`, `radiographic_films`, `external_query_screenshots`, and `signed_generated_files`.
- Preserves `photo_ocr_attempts == 0`.

- [x] **Step 1: Update the expected metrics test first**

```python
self.assertEqual(report.metrics["logical_documents"], 76)
self.assertEqual(report.metrics["physical_files"], 136)
self.assertEqual(report.metrics["referenced_source_files"], 12)
self.assertEqual(report.metrics["evidence_universe_files"], 148)
self.assertEqual(report.metrics["field_photos"], 11)
self.assertEqual(report.metrics["radiographic_films"], 3)
self.assertEqual(report.metrics["external_query_screenshots"], 1)
self.assertEqual(report.metrics["signed_generated_files"], 136)
```

Add negative tests for a missing source PDF, a modified source digest, a missing signature marker, an omitted image attachment, an unclosed data discrepancy, and an unclosed R69 finding.

- [x] **Step 2: Run and verify RED**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_validate_pack -v
```

- [x] **Step 3: Implement validation checks**

Validate catalog paths, all 12 external source paths/page counts/digests, exact attachment sets, embedded seal/signature contract by file type, no national-ID regex matches in generated DOCX/XLSX/PDF text, all five data closures, correct standards, and the R69 final status. Do not OCR photos.

- [x] **Step 4: Run validator tests and verify GREEN**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_validate_pack -v
```

- [x] **Step 5: Commit**

```bash
git add scripts/r01_r69_pack/validate_pack.py scripts/r01_r69_pack/tests/test_validate_pack.py
git commit -m "test: enforce comprehensive pack evidence"
```

### Task 7: Full Rebuild and Visual QA

**Files:**
- Regenerate: `files/R01-R69全节点业务验收测试包/**`
- Update: `docs/superpowers/plans/2026-07-31-r01-r69-completeness-closure.md`

**Interfaces:**
- Produces final 136 generated files and final validation report with zero errors.

- [x] **Step 1: Rebuild the full pack**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack
```

Expected: `logical_documents=76`, `physical_files=136`, `build_errors=0`.

- [x] **Step 2: Run the complete automated suite**

```bash
$PACK_PY -m unittest discover -s scripts/r01_r69_pack/tests -v
$PACK_PY -m scripts.r01_r69_pack.validate_pack \
  files/R01-R69全节点业务验收测试包 \
  --render-qa-dir tmp/r01-r69-final-pdf-pages
```

Expected: all tests pass; `validation_errors=0`; all PDFs render to PNG pages.

- [x] **Step 3: Render every DOCX and inspect all pages**

Use the bundled document renderer in batches, with unique output folders under `tmp/r01-r69-final-docx-pages/`. Confirm page count, no clipped tables/text, no missing glyphs, and no seal overlap on every page.

- [x] **Step 4: Inspect every XLSX sheet preview**

Use the already generated artifact-tool previews under `tmp/r01-r69-xlsx-previews/`; require one preview per populated sheet, scan for formula errors, and inspect all previews at full resolution for clipping and badge overlap.

- [x] **Step 5: Inspect every PDF page and JPG**

Review all rendered PDF pages plus all 15 JPGs. Reject blank pages, broken CJK glyphs, illegible small text, or test marks/signatures that obscure evidence.

- [x] **Step 6: Re-run fresh verification after any visual fix**

```bash
$PACK_PY -m unittest discover -s scripts/r01_r69_pack/tests -v
$PACK_PY -m scripts.r01_r69_pack.validate_pack files/R01-R69全节点业务验收测试包
git diff --check
```

- [x] **Step 7: Commit final generated pack**

```bash
git add scripts/r01_r69_pack docs/superpowers/plans/2026-07-31-r01-r69-completeness-closure.md \
  files/R01-R69全节点业务验收测试包
git commit -m "feat: complete R01-R69 acceptance evidence pack"
```

### Task 8: Finish the Existing Pull Request

**Files:**
- No additional production files unless final verification finds a reproducible defect.

**Interfaces:**
- Pushes `codex/r01-r69-acceptance-pack-pr` and updates the existing pull request.

- [x] **Step 1: Review committed scope**

```bash
git status --short --branch
git log --oneline origin/codex/r01-r69-acceptance-pack-pr..HEAD
git diff --stat origin/codex/r01-r69-acceptance-pack-pr...HEAD
```

- [x] **Step 2: Run the final verification commands again**

Use the exact full-suite, validator, and `git diff --check` commands from Task 7. Do not push if any command fails.

- [x] **Step 3: Push and inspect PR status**

```bash
git push origin codex/r01-r69-acceptance-pack-pr
gh pr view 1 --json url,state,isDraft,headRefName,baseRefName,statusCheckRollup
```

Expected: the existing PR points to the updated branch and the local worktree is clean.
