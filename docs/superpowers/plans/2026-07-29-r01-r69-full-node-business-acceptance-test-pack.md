# R01–R69 Full-Node Business Acceptance Test Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and verify a 58-document, 114-file mixed-format R01–R69 business-completeness test pack under `files/R01-R69全节点业务验收测试包/`.

**Architecture:** A deterministic standalone Python generator reads the existing OCR/project sources and business-pack node configuration, merges them with isolated S01–S06 test scenario data, and renders DOCX, XLSX, PDF, and marked JPG artifacts. A separate validator checks node coverage, object references, chronology, file pairing, test markings, and rendered-file health before producing the V00 completeness report.

**Tech Stack:** Python 3.11+, standard library `dataclasses`/`json`/`unittest`, `python-docx` 1.2.0, ReportLab 4.4.9, Pillow 12.2.0, pypdf 6.10.0, Node.js with `@oai/artifact-tool` 2.8.6+, LibreOffice `soffice`, Poppler `pdftoppm`.

## Global Constraints

- Output root is exactly `files/R01-R69全节点业务验收测试包/`.
- Existing source drawings, certificates, scans, and OCR files remain unchanged.
- Original 2021 source dates and identifiers remain unchanged; newly generated test records use a coherent 2026 timeline.
- Reuse existing project, organization, person, certificate, and file identifiers only when the source explicitly supports the role and scope.
- Missing identities and identifiers use a `TEST-` prefix.
- Every generated DOCX, XLSX, PDF, and image must display `测试专用／合成资料／不得用于真实工程`.
- Never generate an authentic-looking official license, qualification certificate, seal, signature, QR code, or anti-counterfeit device.
- Plans, changes, calculations, reviews, and reports use DOCX plus same-version PDF.
- Ledgers, lists, inspection records, and construction records use XLSX plus same-version PDF.
- Construction photos use marked JPG/PNG placeholders; validation checks only file presence and readability and performs no OCR.
- Aggregate data contains exactly 11 lines, 30 representative welds, and 5 primary pressure-bearing material batches.
- The final pack contains exactly 58 logical documents and 114 physical files.
- B00 and S01–S06 together provide at least one executable sample for every R01–R68 node; R69 is recorded as a workflow-only node with no file binding.
- All 166 node-material requirements are marked `已提供` or `本场景不适用`, with a file locator or applicability rationale.
- S02, S03, and S06 contain process exceptions and finish in qualified/closed status.
- The generator and tests use the bundled runtime:

```bash
PACK_PY=/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
PACK_NODE=/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node
PACK_NODE_MODULES=/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules
PACK_SOFFICE=/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice
PACK_PDFTOPPM=/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm
```

- XLSX authoring uses only `@oai/artifact-tool`; Python may prepare JSON payloads but must not author workbooks with openpyxl, xlsxwriter, or pandas.
- `scripts/r01_r69_pack/node_modules` is a symlink to `$PACK_NODE_MODULES` and is never committed.
- Git commands stage only the paths named in each task; existing unrelated worktree changes remain untouched.

## File Structure

Create the generator as a standalone, non-production package:

```text
scripts/r01_r69_pack/
├── __init__.py                 # package exports
├── model.py                    # dataclasses, IDs, dates, reference validation
├── source_extract.py           # read-only extraction from existing OCR and repository files
├── node_snapshot.py            # nodes.yaml -> normalized JSON snapshot
├── catalog.py                  # 58 logical-document catalog and 166 requirement bindings
├── render_common.py            # fonts, page metadata, headers, test markings
├── render_docx.py              # DOCX renderer
├── render_xlsx.mjs             # artifact-tool XLSX renderer and sheet preview
├── render_graphics.py          # S04 diagram and photo placeholder
├── convert_pdf.py              # isolated LibreOffice conversion and PDF health checks
├── build_pack.py               # deterministic orchestration entry point
├── validate_pack.py            # structural and business-completeness validator
├── data/
│   ├── project_master.json     # base project plus S01–S06 objects and timeline
│   ├── document_catalog.json   # 58 logical documents and their output formats
│   ├── requirement_map.json    # 166 REQ rows and file locators/applicability
│   └── content/
│       ├── M00.json            # instructions and project-control content
│       ├── B00.json            # base-project document content
│       ├── S01.json            # foreign/new-material content
│       ├── S02.json            # material-substitution content
│       ├── S03.json            # repair/PWHT content
│       ├── S04.json            # crossing/cathodic-protection content
│       ├── S05.json            # safety-accessory content
│       └── S06.json            # pressure-test-alternative content
└── tests/
    ├── __init__.py
    ├── test_model.py
    ├── test_node_snapshot.py
    ├── test_catalog.py
    ├── test_renderers.py
    ├── test_scenarios.py
    └── test_validate_pack.py
```

Generated output:

```text
files/R01-R69全节点业务验收测试包/
├── 00_使用说明与总目录/
├── M00_项目主数据与总目录/        # 4 logical / 8 physical
├── B00_基础项目资料/              # 12 logical / 24 physical
├── S01_境外材料与新材料/          # 7 logical / 14 physical
├── S02_材料代用/                  # 5 logical / 10 physical
├── S03_焊缝返修与热处理/          # 9 logical / 18 physical
├── S04_阴极保护与穿跨越/          # 6 logical / 10 physical
├── S05_安全附件/                  # 5 logical / 10 physical
├── S06_耐压免除或替代/            # 5 logical / 10 physical
└── V00_R01-R69覆盖验证/           # 5 logical / 10 physical
```

The conceptual M00 group contains four logical documents: `使用说明` and
`资料总目录` are written to `00_使用说明与总目录/`, while `项目主数据` and
`标准版本台账` are written to `M00_项目主数据与总目录/`. Together they remain
4 logical/8 physical files; no duplicate pointer copies are created.

---

### Task 1: Normalized Project Model and Source Reuse

**Files:**
- Create: `scripts/r01_r69_pack/__init__.py`
- Create: `scripts/r01_r69_pack/model.py`
- Create: `scripts/r01_r69_pack/source_extract.py`
- Create: `scripts/r01_r69_pack/data/project_master.json`
- Create: `scripts/r01_r69_pack/tests/__init__.py`
- Create: `scripts/r01_r69_pack/tests/test_model.py`

**Interfaces:**
- Consumes: `Scan/大模型OCR结果.md`, the confirmed design spec, and existing repository paths.
- Produces: `load_project_master(path: Path) -> ProjectMaster`, `extract_source_facts(workspace: Path) -> SourceFacts`, and `ProjectMaster.validate() -> list[str]`.

- [ ] **Step 1: Write failing model tests**

```python
from pathlib import Path
import unittest

from scripts.r01_r69_pack.model import load_project_master
from scripts.r01_r69_pack.source_extract import extract_source_facts


ROOT = Path(__file__).resolve().parents[3]


class ProjectModelTest(unittest.TestCase):
    def test_source_identity_is_reused(self):
        facts = extract_source_facts(ROOT)
        self.assertEqual(
            facts.project_name,
            "珠海恒基达鑫国际化工仓储股份有限公司一、二期装车站新增两套卸车系统项目",
        )
        self.assertEqual(facts.design_organization, "广东星燃石化设计院有限公司")
        self.assertIn("QX201903S-13-Y-07", facts.drawing_numbers)
        self.assertIn("QX201903S-13-Y-10", facts.drawing_numbers)

    def test_master_has_exact_object_counts(self):
        master = load_project_master(
            ROOT / "scripts/r01_r69_pack/data/project_master.json"
        )
        self.assertEqual(len(master.lines), 11)
        self.assertEqual(len(master.welds), 30)
        self.assertEqual(len(master.material_batches), 5)
        self.assertEqual(master.validate(), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_model -v
```

Expected: import failure because `model.py` and `source_extract.py` do not exist.

- [ ] **Step 3: Implement dataclasses and source extraction**

Define immutable dataclasses for `SourceFacts`, `Line`, `MaterialBatch`, `Weld`, `PersonRef`, `CertificateRef`, and `ProjectMaster`. Use explicit regex patterns for the known project name, design organization, drawing numbers, PL/VT line numbers, 0.55 MPa design pressure, 0.825 MPa test pressure, 20# material, and Φ108×4 specification.

`ProjectMaster.validate()` must report:

- duplicate IDs;
- references to missing line/material/weld IDs;
- counts different from 11/30/5;
- synthetic identities without a `TEST-` prefix;
- dates outside the 2026 scenario timeline;
- base facts that conflict with extracted source facts.

- [ ] **Step 4: Author the exact master object set**

Use these 11 lines:

```text
PL8301 PL8302 PL8303 PL8304 PL8305 PL8306 VT8301 VT8302
PL8307-TEST ST8301-TEST PL8308-TEST
```

Use these 5 pressure-bearing material batches:

```text
MAT-B00-20-001          20# / GB/T 8163 / base lines
MAT-S01-TP316L-001      ASTM A312 TP316L / PL8307-TEST
MAT-S01-NM01-001        TEST-NM01 / PL8307-TEST
MAT-S02-S30408-001      S30408 / PL8303 test segment
MAT-S03-15CRMO-001      15CrMoG / ST8301-TEST
```

Allocate exactly 30 welds:

```text
B00 12; S01 3; S02 3; S03 4; S04 3; S05 2; S06 3
```

Use the exact scenario technical facts:

```text
B00: 20#, Φ108×4, DP 0.55 MPa, hydro 0.825 MPa, leak 0.55 MPa
S02: PL8303 test segment, S30408, Φ108×4.5, WPS-TEST-S02-01
S03: ST8301-TEST, 15CrMoG, Φ76×16, DP 2.5 MPa, DT 300 ℃,
     PWHT 680±20 ℃ / 60 min, hardness <=225 HB
S04: PL8308-TEST, 20#, Φ108×4, crossing 18 m, casing Φ273×7,
     two 11 kg magnesium anodes, target -0.85 to -1.20 V CSE
S05: PSV-8301-TEST DN50 PN16 set 0.50 MPa;
     RD-8301-TEST DN50 burst 0.52 MPa at 20 ℃;
     ESDV-8301-TEST DN100 PN16 close time <=2 s
S06: PL8306 final closure segment, 100% RT + 100% MT,
     leak test 0.55 MPa / 30 min
```

- [ ] **Step 5: Re-run the tests**

Run:

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_model -v
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit the model**

```bash
git add scripts/r01_r69_pack/__init__.py \
  scripts/r01_r69_pack/model.py \
  scripts/r01_r69_pack/source_extract.py \
  scripts/r01_r69_pack/data/project_master.json \
  scripts/r01_r69_pack/tests/__init__.py \
  scripts/r01_r69_pack/tests/test_model.py
git commit -m "feat: add R01-R69 project master model"
```

### Task 2: Node Snapshot and Requirement Coverage Contract

**Files:**
- Create: `scripts/r01_r69_pack/node_snapshot.py`
- Create: `scripts/r01_r69_pack/data/requirement_map.json`
- Create: `scripts/r01_r69_pack/tests/test_node_snapshot.py`

**Interfaces:**
- Consumes: `backend/business_packs/engineering_inspection_v1/nodes.yaml`.
- Produces: `snapshot_nodes(source: Path, output: Path) -> dict`, `load_node_snapshot(path: Path) -> NodeSnapshot`, and exactly 69 nodes/166 requirements.

- [ ] **Step 1: Write failing snapshot tests**

```python
class NodeSnapshotTest(unittest.TestCase):
    def test_snapshot_has_contiguous_nodes_and_requirements(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        self.assertEqual([node.code for node in snapshot.nodes], list(range(1, 70)))
        self.assertEqual(len(snapshot.requirements), 166)
        self.assertEqual(snapshot.requirements_for_node(69), [])

    def test_every_requirement_has_resolution(self):
        snapshot = load_node_snapshot(
            ROOT / "scripts/r01_r69_pack/data/requirement_map.json"
        )
        self.assertTrue(all(row.status in {"已提供", "本场景不适用"}
                            for row in snapshot.requirements))
        self.assertTrue(all(row.locator or row.rationale
                            for row in snapshot.requirements))
```

- [ ] **Step 2: Run the tests and confirm failure**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_node_snapshot -v
```

Expected: import or missing-file failure.

- [ ] **Step 3: Implement YAML snapshotting with the backend interpreter**

`node_snapshot.py` must invoke `backend/.venv/bin/python` in a subprocess to import `yaml`, normalize `nodes.yaml`, and write UTF-8 JSON. The normalized record fields are:

```python
{
    "node": 1,
    "nodeName": "...",
    "inspectionType": "A|B|C|需确认",
    "requirementId": "REQ-01-01",
    "materialTypeCode": "...",
    "requiredType": "必传|条件必传",
    "responsibleParty": "...",
    "status": "已提供|本场景不适用",
    "logicalDocumentId": "...",
    "locator": "文件名#页码或工作表",
    "rationale": ""
}
```

R69 is emitted as a node with zero requirements and `workflowOnly: true`.

- [ ] **Step 4: Populate deterministic coverage resolutions**

Map every requirement to one of the 58 logical document IDs. Use B00 for normal qualification/design/material/welding/NDT/installation/test nodes and S01–S06 for their conditional groups. Every conditional row not triggered inside a specific sub-scenario still receives an aggregate-pack locator where that condition is deliberately triggered.

- [ ] **Step 5: Run tests**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_node_snapshot -v
```

Expected: both tests pass with 69 nodes and 166 requirements.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/node_snapshot.py \
  scripts/r01_r69_pack/data/requirement_map.json \
  scripts/r01_r69_pack/tests/test_node_snapshot.py
git commit -m "feat: snapshot R01-R69 material requirements"
```

### Task 3: Logical Document Catalog

**Files:**
- Create: `scripts/r01_r69_pack/catalog.py`
- Create: `scripts/r01_r69_pack/data/document_catalog.json`
- Create: `scripts/r01_r69_pack/tests/test_catalog.py`

**Interfaces:**
- Consumes: `ProjectMaster` and `NodeSnapshot`.
- Produces: `load_catalog(path: Path) -> DocumentCatalog`, `DocumentCatalog.validate(master, nodes) -> list[str]`, and `DocumentSpec` records used by all renderers.

- [ ] **Step 1: Write failing catalog tests**

```python
class CatalogTest(unittest.TestCase):
    def test_exact_logical_and_physical_counts(self):
        catalog = load_catalog(ROOT / "scripts/r01_r69_pack/data/document_catalog.json")
        self.assertEqual(len(catalog.documents), 58)
        self.assertEqual(catalog.expected_physical_file_count(), 114)
        self.assertEqual(
            catalog.logical_counts_by_folder(),
            {
                "M00": 4, "B00": 12, "S01": 7, "S02": 5,
                "S03": 9, "S04": 6, "S05": 5, "S06": 5, "V00": 5,
            },
        )

    def test_catalog_covers_r01_to_r68(self):
        catalog = load_catalog(ROOT / "scripts/r01_r69_pack/data/document_catalog.json")
        covered = sorted({node for doc in catalog.documents for node in doc.r_nodes})
        self.assertEqual(covered, list(range(1, 69)))
        self.assertEqual(catalog.validate(master, snapshot), [])
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_catalog -v
```

Expected: missing module or catalog.

- [ ] **Step 3: Implement catalog types and checks**

`DocumentSpec` fields:

```python
logical_id: str
folder: str
title: str
source_format: Literal["docx", "xlsx", "pdf", "jpg"]
submit_format: Literal["pdf", "jpg"]
document_number: str
revision: str
date: str
r_nodes: tuple[int, ...]
related_lines: tuple[str, ...]
related_welds: tuple[str, ...]
related_materials: tuple[str, ...]
template_kind: str
content_ref: str
```

`validate()` rejects duplicate document/file numbers, missing object references, R69 bindings, absent R01–R68 coverage, and incorrect folder counts.

- [ ] **Step 4: Author all 58 logical documents**

Use these exact logical groups:

```text
M00 (4): 使用说明; 项目主数据; 标准版本台账; 资料总目录
B00 (12): 设计输入摘要; 施工组织设计; 质量计划; 单位人员资质台账;
          基础管线台账; 材料验收台账; 阀门试验记录; WPS/PQR基础包;
          焊口与检验台账; 基础NDT报告; 压力泄漏试验方案;
          安装试验吹扫综合记录
S01 (7): 设计变更; 境外/新材料清单; 境外制造与型式资料;
         企业标准与材料证明; 验证性复验; 新材料评审批准;
         到货验收与标志移植
S02 (5): 材料代用设计变更; 技术比较与强度校核; 书面批准;
         替代材料与WPS适用性; 验收安装记录
S03 (9): 设计变更与计算; PQR/WPS; 焊工焊材台账; 焊口施焊台账;
         首次NDT不合格报告; 返修方案记录; 复检合格报告;
         热处理工艺与仪表; 热处理曲线硬度记录
S04 (6): 穿越设计变更; 穿越结构图; 设备材料台账; 穿越施工记录;
         防腐阴保调试记录; 施工照片
S05 (5): 安全附件设计变更与选型; 产品型式资料; 到货安装记录;
         安全阀校验; 紧急切断阀与爆破片记录
S06 (5): 设计论证与应力分析; 替代申请审批; 替代检验试验方案;
         100% RT/MT报告与底片; 替代试验泄漏最终确认
V00 (5): R01-R69覆盖矩阵; 166要求覆盖明细; 来源差异台账;
         文件校验清单; 完整性检查报告
```

- [ ] **Step 5: Run tests**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_catalog -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/catalog.py \
  scripts/r01_r69_pack/data/document_catalog.json \
  scripts/r01_r69_pack/tests/test_catalog.py
git commit -m "feat: define R01-R69 document catalog"
```

### Task 4: Mixed-Format Rendering Foundation

**Files:**
- Create: `scripts/r01_r69_pack/render_common.py`
- Create: `scripts/r01_r69_pack/render_docx.py`
- Create: `scripts/r01_r69_pack/render_xlsx.mjs`
- Create: `scripts/r01_r69_pack/render_graphics.py`
- Create: `scripts/r01_r69_pack/convert_pdf.py`
- Create: `scripts/r01_r69_pack/tests/test_renderers.py`

**Interfaces:**
- Consumes: `DocumentSpec`, `ProjectMaster`, and an output directory.
- Produces:
  - `render_docx(spec, master, output: Path) -> Path`
  - `render_xlsx(spec, master, output: Path) -> Path`
  - `render_pdf_graphic(spec, master, output: Path) -> Path`
  - `render_test_photo(spec, output: Path) -> Path`
  - `convert_office_to_pdf(source: Path, output_dir: Path) -> Path`
  - `validate_pdf(path: Path) -> list[str]`

- [ ] **Step 1: Write failing renderer tests**

```python
class RendererTest(unittest.TestCase):
    def test_docx_xlsx_and_pdf_are_renderable(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            docx_path = render_docx(docx_spec, master, out)
            xlsx_path = render_xlsx(xlsx_spec, master, out)
            self.assertTrue(docx_path.exists())
            self.assertTrue(xlsx_path.exists())
            self.assertEqual(validate_pdf(convert_office_to_pdf(docx_path, out)), [])
            self.assertEqual(validate_pdf(convert_office_to_pdf(xlsx_path, out)), [])

    def test_every_artifact_has_test_marking(self):
        with TemporaryDirectory() as tmp:
            outputs = render_fixture_set(Path(tmp))
            self.assertTrue(all(has_test_marking(path) for path in outputs))
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers -v
```

Expected: missing renderer imports.

- [ ] **Step 3: Implement shared Chinese document styling**

Use the named `engineering_a4` override of the `standard_business_brief` preset: A4 portrait, 25 mm margins, Chinese fonts selected from installed CJK fonts, 14 pt centered titles, 10.5 pt body text, 9 pt tables, repeating table headers, gray header watermark text, red footer warning, file number/revision/date metadata, and a non-signature approval table containing names/roles plus `电子记录（测试）`.

Do not draw seal circles, handwritten marks, QR codes, or certificate borders.

- [ ] **Step 4: Implement DOCX and artifact-tool XLSX renderers**

DOCX renderer supports narrative sections, key/value tables, normal tables, approval history, references, and page fields. The Node XLSX renderer imports `Workbook` and `SpreadsheetFile` from `@oai/artifact-tool`, consumes a JSON workbook payload produced by Python, and supports multiple named sheets, frozen panes, filters, typed dates/numbers, formulas, page headers/footers, cell validation, and conditional highlighting for process exceptions. It renders every populated sheet to PNG before exporting the final XLSX.

Every XLSX sheet must show the warning in rows 1–2 and start the business table at row 4.

- [ ] **Step 5: Implement diagrams, photos, conversion, and PDF checks**

Use ReportLab for the S04 crossing schematic and Pillow for the marked test photo. Use an isolated temporary LibreOffice profile for each conversion:

```text
soffice -env:UserInstallation=file://<temp-profile> \
  --headless --convert-to pdf --outdir <output-dir> <source>
```

`validate_pdf()` uses pypdf to reject encrypted, zero-page, or page-size-zero PDFs. Render the first and last pages with `pdftoppm -png -r 120` and reject blank images.

- [ ] **Step 6: Run tests**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_renderers -v
```

Expected: all renderer tests pass and temporary artifacts are readable.

- [ ] **Step 7: Commit**

```bash
git add scripts/r01_r69_pack/render_common.py \
  scripts/r01_r69_pack/render_docx.py \
  scripts/r01_r69_pack/render_xlsx.mjs \
  scripts/r01_r69_pack/render_graphics.py \
  scripts/r01_r69_pack/convert_pdf.py \
  scripts/r01_r69_pack/tests/test_renderers.py
git commit -m "feat: add mixed-format engineering document renderers"
```

### Task 5: M00 and B00 Base Project Documents

**Files:**
- Create: `scripts/r01_r69_pack/data/content/M00.json`
- Create: `scripts/r01_r69_pack/data/content/B00.json`
- Create: `scripts/r01_r69_pack/build_pack.py`
- Create: `scripts/r01_r69_pack/tests/test_scenarios.py`
- Generate: `files/R01-R69全节点业务验收测试包/M00_项目主数据与总目录/*`
- Generate: `files/R01-R69全节点业务验收测试包/B00_基础项目资料/*`

**Interfaces:**
- Consumes: source facts, master data, catalog, and renderers.
- Produces: `build_selected(workspace: Path, logical_ids: set[str]) -> BuildResult`.

- [ ] **Step 1: Write failing M00/B00 tests**

```python
def test_m00_b00_counts_and_base_facts(self):
    result = build_fixture({"M00", "B00"})
    self.assertEqual(result.logical_count, 16)
    self.assertEqual(result.physical_count, 32)
    self.assertEqual(result.errors, [])
    self.assert_all_text_present(
        result.files,
        ["QX201903S-13-Y-07", "0.55 MPa", "0.825 MPa", "PL8301"],
    )
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_scenarios.BaseScenarioTest -v
```

Expected: `build_selected` missing.

- [ ] **Step 3: Implement selective build orchestration**

The builder creates a fresh explicit output subtree, renders sources first, converts matching PDFs, computes SHA-256, and returns a manifest without touching any unrelated files.

- [ ] **Step 4: Complete M00 and B00 content**

M00 must include the source provenance, standard status, 11 lines, 30 welds, 5 batches, 58-document catalog, and warning text. B00 must retain the original GC2/20#/Φ108×4/0.55/0.825 data and include normal qualification, organization, material, valve, welding, NDT, installation, pressure/leak, purge, and cleaning records.

- [ ] **Step 5: Run tests and visually inspect representative PDFs**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_scenarios.BaseScenarioTest -v
$PACK_PDFTOPPM -png -r 120 \
  "files/R01-R69全节点业务验收测试包/B00_基础项目资料/B00_设计输入摘要_QX201903S-13-Y-TEST-B00-001_基础设计输入摘要.pdf" \
  "tmp/r01-r69-b00-preview"
```

Expected: tests pass; rendered preview is readable and marked as test-only.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/build_pack.py \
  scripts/r01_r69_pack/data/content/M00.json \
  scripts/r01_r69_pack/data/content/B00.json \
  scripts/r01_r69_pack/tests/test_scenarios.py \
  "files/R01-R69全节点业务验收测试包/M00_项目主数据与总目录" \
  "files/R01-R69全节点业务验收测试包/B00_基础项目资料"
git commit -m "feat: generate R01-R69 base project documents"
```

### Task 6: S01 and S02 Material Scenarios

**Files:**
- Create: `scripts/r01_r69_pack/data/content/S01.json`
- Create: `scripts/r01_r69_pack/data/content/S02.json`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`
- Generate: `files/R01-R69全节点业务验收测试包/S01_境外材料与新材料/*`
- Generate: `files/R01-R69全节点业务验收测试包/S02_材料代用/*`

**Interfaces:**
- Consumes: `build_selected`.
- Produces: 12 logical/24 physical S01+S02 artifacts and closed material chains.

- [ ] **Step 1: Write failing material scenario tests**

```python
def test_s01_has_foreign_and_new_material_chain(self):
    docs = build_fixture({"S01"})
    self.assertEqual((docs.logical_count, docs.physical_count), (7, 14))
    self.assert_chain(
        docs,
        ["境外制造清单", "企业标准", "验证性复验", "技术评审", "型式试验", "标志移植"],
    )

def test_s02_material_substitution_is_approved_and_closed(self):
    docs = build_fixture({"S02"})
    self.assertEqual((docs.logical_count, docs.physical_count), (5, 10))
    self.assert_chain(
        docs,
        ["代用申请", "技术比较", "强度校核", "设计批准", "安装合格"],
    )
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.MaterialScenarioTest -v
```

Expected: missing scenario content or chain assertions fail.

- [ ] **Step 3: Author S01 content**

Use `PL8307-TEST`, `MAT-S01-TP316L-001`, and `MAT-S01-NM01-001`. Every foreign manufacturer, technical-review body, and missing certificate value is visibly prefixed `TEST-`. The type-test and qualification pages are titled `测试资质数据页`, not official certificates.

- [ ] **Step 4: Author S02 content**

Use the isolated PL8303 test segment, substitute 20# with S30408 Φ108×4.5, reference `WPS-TEST-S02-01`, and make approval precede procurement and installation. The final material and installation conclusions are qualified.

- [ ] **Step 5: Build and run tests**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack --folders S01 S02
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.MaterialScenarioTest -v
```

Expected: 12 logical and 24 physical files; tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/data/content/S01.json \
  scripts/r01_r69_pack/data/content/S02.json \
  scripts/r01_r69_pack/tests/test_scenarios.py \
  "files/R01-R69全节点业务验收测试包/S01_境外材料与新材料" \
  "files/R01-R69全节点业务验收测试包/S02_材料代用"
git commit -m "feat: generate conditional material test scenarios"
```

### Task 7: S03 Repair and Post-Weld Heat Treatment Scenario

**Files:**
- Create: `scripts/r01_r69_pack/data/content/S03.json`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`
- Generate: `files/R01-R69全节点业务验收测试包/S03_焊缝返修与热处理/*`

**Interfaces:**
- Consumes: S03 master objects and renderers.
- Produces: 9 logical/18 physical artifacts with one closed NDT repair chain and one qualified PWHT chain.

- [ ] **Step 1: Write failing S03 tests**

```python
def test_s03_exception_and_pwht_chain(self):
    docs = build_fixture({"S03"})
    self.assertEqual((docs.logical_count, docs.physical_count), (9, 18))
    timeline = docs.events_for("W-S03-003")
    self.assertEqual(
        [event.status for event in timeline],
        ["施焊完成", "首次RT不合格", "返修批准", "返修完成",
         "RT复检合格", "焊后热处理完成", "硬度合格"],
    )
    self.assertTrue(docs.pwht_curve_is_continuous("W-S03-003"))
    self.assertLessEqual(docs.max_hardness("W-S03-003"), 225)
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.WeldingScenarioTest -v
```

Expected: missing S03 data.

- [ ] **Step 3: Author welding and NDT content**

Use four S03 welds; `W-S03-003` contains a single lack-of-fusion indication in the first RT record. The repair is the first repair at that location, uses a separately approved repair card, and passes repeat RT before PWHT.

Embed a visibly simulated radiographic evidence panel in the report PDF and label it `测试模拟底片图，不得作为真实检测底片`.

- [ ] **Step 4: Author PWHT and hardness records**

Use 680±20 ℃, 60 minutes holding time, two thermocouples, calibrated recorder `TEST-HTR-001`, continuous readings at five-minute intervals, and three hardness points per weld. All final readings are at or below 225 HB.

- [ ] **Step 5: Build and test**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack --folders S03
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.WeldingScenarioTest -v
```

Expected: 9 logical/18 physical files and all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/data/content/S03.json \
  scripts/r01_r69_pack/tests/test_scenarios.py \
  "files/R01-R69全节点业务验收测试包/S03_焊缝返修与热处理"
git commit -m "feat: generate repair and heat treatment scenario"
```

### Task 8: S04 and S05 Installation and Safety-Accessory Scenarios

**Files:**
- Create: `scripts/r01_r69_pack/data/content/S04.json`
- Create: `scripts/r01_r69_pack/data/content/S05.json`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`
- Generate: `files/R01-R69全节点业务验收测试包/S04_阴极保护与穿跨越/*`
- Generate: `files/R01-R69全节点业务验收测试包/S05_安全附件/*`

**Interfaces:**
- Consumes: S04/S05 master objects, ReportLab diagram renderer, and Pillow photo renderer.
- Produces: 11 logical/20 physical artifacts.

- [ ] **Step 1: Write failing S04/S05 tests**

```python
def test_s04_crossing_and_cp_records(self):
    docs = build_fixture({"S04"})
    self.assertEqual((docs.logical_count, docs.physical_count), (6, 10))
    self.assertTrue(docs.has_readable_image("S04-PHOTO-001"))
    self.assertFalse(docs.photo_requires_ocr("S04-PHOTO-001"))
    self.assertTrue(all(-1.20 <= value <= -0.85
                        for value in docs.cp_potentials()))

def test_s05_accessories_are_individually_traceable(self):
    docs = build_fixture({"S05"})
    self.assertEqual((docs.logical_count, docs.physical_count), (5, 10))
    self.assertEqual(
        docs.accessory_ids(),
        {"PSV-8301-TEST", "RD-8301-TEST", "ESDV-8301-TEST"},
    )
    self.assertTrue(docs.all_accessory_results_qualified())
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.InstallationScenarioTest -v
```

Expected: scenario content missing.

- [ ] **Step 3: Author S04 documents and graphics**

The crossing diagram shows the 18 m road crossing, Φ273×7 casing, Φ108×4 carrier pipe, weld positions, insulating supports, two 11 kg magnesium anodes, test post, and drainage connection. The photo is a neutral diagram-like placeholder with no field claim, no OCR contract, and a prominent test warning.

- [ ] **Step 4: Author S05 documents**

Use PSV set pressure 0.50 MPa, rupture pressure 0.52 MPa at 20 ℃, and ESDV closing time <=2 s. Include individual product-data, arrival, installation, calibration/performance, instrument, and final acceptance references.

- [ ] **Step 5: Build and test**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack --folders S04 S05
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.InstallationScenarioTest -v
```

Expected: 11 logical/20 physical files and all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/data/content/S04.json \
  scripts/r01_r69_pack/data/content/S05.json \
  scripts/r01_r69_pack/tests/test_scenarios.py \
  "files/R01-R69全节点业务验收测试包/S04_阴极保护与穿跨越" \
  "files/R01-R69全节点业务验收测试包/S05_安全附件"
git commit -m "feat: generate crossing and safety accessory scenarios"
```

### Task 9: S06 Pressure-Test Alternative Scenario

**Files:**
- Create: `scripts/r01_r69_pack/data/content/S06.json`
- Modify: `scripts/r01_r69_pack/tests/test_scenarios.py`
- Generate: `files/R01-R69全节点业务验收测试包/S06_耐压免除或替代/*`

**Interfaces:**
- Consumes: PL8306 final-closure segment and S06 approval sequence.
- Produces: 5 logical/10 physical artifacts with an isolated, fully closed alternative-test chain.

- [ ] **Step 1: Write failing S06 tests**

```python
def test_s06_is_isolated_and_closed(self):
    docs = build_fixture({"S06"})
    self.assertEqual((docs.logical_count, docs.physical_count), (5, 10))
    self.assertNotIn("B00-PRESSURE-REPORT", docs.acceptance_evidence_ids())
    self.assertEqual(docs.rt_coverage("W-S06-001"), 100)
    self.assertEqual(docs.mt_coverage("W-S06-001"), 100)
    self.assertEqual(docs.leak_test(), {"pressure_mpa": 0.55, "minutes": 30})
    self.assertEqual(docs.final_status(), "合格闭环")
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.PressureAlternativeScenarioTest -v
```

Expected: S06 content missing.

- [ ] **Step 3: Author S06 analysis, approvals, and plan**

State why the final closure segment cannot receive the normal base hydrotest, identify the applicable code basis, provide flexibility/stress conclusions, and include separate test approval records for construction, design, owner, and supervision-inspection roles. Approval dates precede welding and testing.

- [ ] **Step 4: Author detection and final records**

Provide 100% RT reports and simulated film panels plus 100% MT for all three S06 welds. Record instrument validity, 0.55 MPa leak pressure, 30-minute hold, no pressure drop, no leakage, and final qualified closure.

- [ ] **Step 5: Build and test**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack --folders S06
$PACK_PY -m unittest \
  scripts.r01_r69_pack.tests.test_scenarios.PressureAlternativeScenarioTest -v
```

Expected: 5 logical/10 physical files and all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/r01_r69_pack/data/content/S06.json \
  scripts/r01_r69_pack/tests/test_scenarios.py \
  "files/R01-R69全节点业务验收测试包/S06_耐压免除或替代"
git commit -m "feat: generate pressure-test alternative scenario"
```

### Task 10: V00 Matrices, Final Validator, and Full-Pack QA

**Files:**
- Create: `scripts/r01_r69_pack/validate_pack.py`
- Create: `scripts/r01_r69_pack/tests/test_validate_pack.py`
- Modify: `scripts/r01_r69_pack/build_pack.py`
- Generate: `files/R01-R69全节点业务验收测试包/V00_R01-R69覆盖验证/*`
- Generate: `files/R01-R69全节点业务验收测试包/00_使用说明与总目录/*`

**Interfaces:**
- Consumes: all generated artifacts, master data, catalog, and requirement map.
- Produces:
  - `validate_pack(root: Path) -> ValidationReport`
  - `ValidationReport.errors: list[str]`
  - `ValidationReport.metrics: dict[str, int]`
  - final V00 XLSX/DOCX plus matching PDFs.

- [ ] **Step 1: Write failing validator tests**

```python
class PackValidatorTest(unittest.TestCase):
    def test_complete_pack_passes(self):
        report = validate_pack(FULL_FIXTURE)
        self.assertEqual(report.errors, [])
        self.assertEqual(
            report.metrics,
            {
                "nodes": 69,
                "requirements": 166,
                "logical_documents": 58,
                "physical_files": 114,
                "lines": 11,
                "welds": 30,
                "material_batches": 5,
            },
        )

    def test_missing_pdf_is_reported(self):
        with copied_fixture(FULL_FIXTURE) as fixture:
            fixture.joinpath("S03_焊缝返修与热处理", "S03_返修方案记录.pdf").unlink()
            report = validate_pack(fixture)
            self.assertIn("缺少配对PDF", "\n".join(report.errors))

    def test_photo_is_presence_only(self):
        report = validate_pack(FULL_FIXTURE)
        self.assertEqual(report.photo_ocr_attempts, 0)
```

- [ ] **Step 2: Run and verify failure**

```bash
$PACK_PY -m unittest scripts.r01_r69_pack.tests.test_validate_pack -v
```

Expected: validator import failure.

- [ ] **Step 3: Implement structural and business validation**

Validate:

- exact directory names;
- 58 catalog rows and 114 physical files;
- source/PDF pairs and matching metadata;
- SHA-256 inventory;
- 69 contiguous nodes and 166 requirement rows;
- every R01–R68 node covered and R69 workflow-only;
- 11 lines, 30 welds, and 5 batches;
- no unresolved object references;
- chronological ordering and calibration validity;
- S02/S03/S06 closure chains;
- S01/S04/S05 conditional chains;
- readable DOCX/XLSX/PDF/JPG;
- test warning in every generated file;
- zero photo OCR attempts;
- no unmarked synthetic certificate/seal/signature artifacts.

- [ ] **Step 4: Render the five V00 documents**

Create:

```text
V00-R01-R69资料覆盖矩阵.xlsx/.pdf
V00-166项资料要求覆盖明细.xlsx/.pdf
V00-资料来源与差异台账.xlsx/.pdf
V00-文件校验清单.xlsx/.pdf
V00-资料包完整性检查报告.docx/.pdf
```

The completeness report conclusion is exactly:

```text
业务资料齐全，R01–R69测试场景全部覆盖；
过程异常均已闭环，最终状态合格；
施工照片按存在性附件提交，未执行OCR。
```

- [ ] **Step 5: Build the complete pack**

```bash
$PACK_PY -m scripts.r01_r69_pack.build_pack \
  --workspace /Volumes/7up/github/knowledgetools \
  --output "/Volumes/7up/github/knowledgetools/files/R01-R69全节点业务验收测试包"
```

Expected:

```text
logical_documents=58
physical_files=114
nodes=69
requirements=166
validation_errors=0
```

- [ ] **Step 6: Run all automated tests**

```bash
$PACK_PY -m unittest discover \
  -s scripts/r01_r69_pack/tests \
  -p "test_*.py" \
  -v
```

Expected: all tests pass.

- [ ] **Step 7: Run the final validator**

```bash
$PACK_PY -m scripts.r01_r69_pack.validate_pack \
  "/Volumes/7up/github/knowledgetools/files/R01-R69全节点业务验收测试包"
```

Expected: `validation_errors=0`.

- [ ] **Step 8: Render every PDF for visual QA**

Create a temporary QA directory and render every PDF at 120 DPI. Inspect at least the first and last page of every multi-page PDF, plus every page of the M00 master table, S03 NDT/PWHT documents, S04 crossing diagram, S05 calibration report, S06 alternative-test documents, and all V00 outputs.

Run:

```bash
$PACK_PY -m scripts.r01_r69_pack.validate_pack \
  "/Volumes/7up/github/knowledgetools/files/R01-R69全节点业务验收测试包" \
  --render-qa-dir "/Volumes/7up/github/knowledgetools/tmp/r01-r69-pack-qa"
```

Expected: no blank pages, clipped tables, unreadable fonts, or unmarked test artifacts.

- [ ] **Step 9: Verify git scope and commit**

```bash
git status --short
git add scripts/r01_r69_pack \
  "files/R01-R69全节点业务验收测试包"
git diff --cached --check
git commit -m "feat: add complete R01-R69 business acceptance test pack"
```

Expected: only the generator, its tests/data, and the generated pack are committed; unrelated pre-existing changes remain unstaged.
