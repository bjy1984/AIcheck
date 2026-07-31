# Test Package Upload Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and verify `files/测试说明.md` as an executable, role-specific source-file upload guide for the complete R01–R69 business acceptance test package.

**Architecture:** The guide is a static Markdown operating manual derived from the existing document catalog, 166-row requirement map, and current frontend role workbenches. Contractor and NDT operators use their own category-based file-library entrances; only inspection operators use the R01–R69 node tree. A final crosswalk shows where each submitted source file is expected to appear for inspection without instructing non-inspection roles to navigate by R number.

**Tech Stack:** Markdown, JSON, Python 3 standard library, ripgrep, Git.

## Global Constraints

- Final path is exactly `files/测试说明.md`.
- The operating subject is an existing UI role: 系统管理员、施工方、无损检测机构、监检人员、建设单位、FDE工程师.
- R01–R69 is the inspection-role business-node system; contractor and NDT instructions use their own file-library categories and actions.
- Contractor upload categories are exactly: 资质证照、设计资料、施工方案、材料证明与复验、安全附件与阀门、焊接资料、热处理资料、防腐保温资料、安装交工资料、试验与吹扫资料.
- NDT upload categories are exactly: 机构与人员资质、检测方案与工艺、检测设备与校准、底片与影像资料、检测记录、检测报告、问题处理闭环.
- Upload the catalog `sourceFormat` file only. DOCX/XLSX-derived PDF copies are preview and verification artifacts, not default upload files.
- Native source PDF files remain valid upload files.
- Construction photographs without OCR text are submitted normally and checked manually.
- Preserve the base project and S01–S06 scenario separation.
- The guide must describe a process exception followed by correction and final qualified closure.
- Existing generated files are read-only inputs; this task does not regenerate or modify them.
- Git commands stage only the new guide and implementation plan.

## File Structure

```text
docs/superpowers/plans/
└── 2026-07-31-test-package-upload-guide.md  # implementation plan

files/
└── 测试说明.md                              # final executable upload guide
```

Authoritative read-only inputs:

```text
scripts/r01_r69_pack/data/document_catalog.json
scripts/r01_r69_pack/data/requirement_map.json
frontend/src/views/AICheck/components/WorkbenchRoleStaticSections.vue
frontend/src/views/AICheck/components/NdtWorkflowPanel.vue
frontend/src/views/AICheck/components/UploadSessionDrawer.vue
frontend/src/views/AICheck/components/NdtReportUploadDrawer.vue
frontend/src/utils/roleAccess.ts
files/R01-R69全节点业务验收测试包/
```

---

### Task 1: Write the role-specific upload manual

**Files:**
- Create: `files/测试说明.md`

**Interfaces:**
- Consumes: the 76-document catalog, 166 requirement rows, current UI role/category definitions, and generated source files.
- Produces: one self-contained Markdown guide with role instructions, source-file upload manifests, scenario order, correction workflow, and an inspection R01–R69 receiving crosswalk.

- [ ] **Step 1: Extract the authoritative document and node inventories**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

catalog = json.loads(Path('scripts/r01_r69_pack/data/document_catalog.json').read_text())
requirements = json.loads(Path('scripts/r01_r69_pack/data/requirement_map.json').read_text())
assert catalog['logicalDocumentCount'] == 76
assert catalog['physicalFileCount'] == 136
assert requirements['nodeCount'] == 69
assert requirements['requirementCount'] == 166
print('catalog=76, physical=136, nodes=69, requirements=166')
PY
```

Expected: `catalog=76, physical=136, nodes=69, requirements=166`.

- [ ] **Step 2: Write the operating rules and role boundaries**

Create `files/测试说明.md` with these top-level sections:

```markdown
# 完整资料包测试说明
## 1. 使用范围与上传口径
## 2. 测试角色与界面入口
## 3. 测试前准备
## 4. 系统管理员初始化
## 5. 施工方上传清单
## 6. 无损检测机构上传清单
## 7. 监检人员上传与审查清单
## 8. 建设单位和FDE操作
## 9. 监检R01–R69接收对照表
## 10. 基础项目与条件场景执行顺序
## 11. 异常、补正与最终合格闭环
## 12. 完成判定与测试留痕
```

State explicitly that contractor and NDT users do not use R01–R69 as their upload navigation. R numbers appear in their manifests only as “监检预期接收范围”.

- [ ] **Step 3: Add the contractor source-file manifest**

Use one table per contractor category. Every row contains:

```text
场景 | 源文件 | 源文件路径 | 资料项/用途 | 界面操作 | 监检预期接收范围 | 备注
```

Classify contractor files by their primary purpose:

```text
资质证照          B00-QUAL and qualification-related source documents
设计资料          B00-DESIGN, M00-STD, S01/S02/S03/S04/S05/S06 design/change/calculation sources
施工方案          B00-CONSTRUCTION, B00-TEST, alternative-test plans
材料证明与复验    B00-MATERIAL, S01 foreign/new-material records, S02 material-substitution records
安全附件与阀门    B00-VALVE and S05 accessory/PSV/ESDV records
焊接资料          B00-WELD, B00-WELD-LEDGER, S02-WPS, S03 welder/weld/repair sources
热处理资料        S03 PWHT process and record sources
防腐保温资料      S04 CP/equipment/coating-related sources
安装交工资料      B00-INSTALL, S02/S04/S05 installation records
试验与吹扫资料    B00-TEST, B00-INSTALL test sheets, S06 approval/alternative/final records
```

For each category, instruct: click “上传资料” → choose source file → confirm category → upload → select the file row → “选择环节” → complete 资料项、文件用途、关联审核环节 → submit.

- [ ] **Step 4: Add the NDT source-file manifest**

Use one table per NDT category with the same fields, replacing “界面操作” with the exact category action. Classify the sources as follows:

```text
机构与人员资质    B00-QUAL, B00-NDT qualification content
检测方案与工艺    B00-NDT and S03/S06 NDT procedure sources
检测设备与校准    equipment/calibration content contained in the NDT source packages
底片与影像资料    B00-FILM-001/002, B00-PHOTO-003, S06-FILM-001
检测记录          B00-INSTALL NDT sheets, S01-RETEST, S03-NDT-INITIAL/REPEAT, S06-NDT
检测报告          B00-NDT, S03-NDT-INITIAL/REPEAT, S06-NDT
问题处理闭环      S03-REPAIR plus initial-failure and repeat-qualified evidence
```

Describe the dedicated flows:

```text
ordinary material: category “上传资料” → upload source → wait for processing
structured record: “批量导入记录” → verify weld/film/report relations
film/image: “新增底片编号” first, then upload image source and bind identifiers
formal report: “上传检测报告” → fill report metadata → associate film/image → upload
submission: “提交检测资料”
correction: “问题处理闭环/上传补正” → “提交反馈”
```

- [ ] **Step 5: Add inspection-only uploads and the R01–R69 receiving crosswalk**

List monitor-generated sources under “监检人员 → Rxx → 上传监检资料”, including all photo/query evidence and `V00-R69-001`.

Build exactly 69 R rows with fields:

```text
监检节点 | 节点名称 | 接收自哪个角色入口 | 预期源文件 | 监检操作 | 预期结果
```

For R01–R68, derive node names from `requirement_map.json` and source documents from the union of requirement `logicalDocumentId` and catalog `rNodes`. For R69, use the inspection-uploaded workflow record and require an artificial/manual final evaluation; do not claim an automated decision.

- [ ] **Step 6: Add scenario and correction execution order**

Document the ordered run:

```text
B00 → S01 → S02 → S03 → S04 → S05 → S06 → R01–R68 review → R69 evaluation → owner read-only check
```

Keep B00 unchanged between scenario books. Explicitly record that S02, S03, and S06 expose the planned exception first, then use a replacement version or correction attachment, resubmit, recheck, and close as qualified. Submitted files are never physically deleted.

- [ ] **Step 7: Review the guide for operational language**

Confirm every action is written from the active UI role’s viewpoint. Replace phrases such as “施工方进入Rxx上传” with “施工方从资料类别上传并选择审核环节；监检人员在Rxx接收”.

### Task 2: Verify completeness and commit the guide

**Files:**
- Verify: `files/测试说明.md`
- Verify: `docs/superpowers/plans/2026-07-31-test-package-upload-guide.md`

**Interfaces:**
- Consumes: final Markdown guide and authoritative JSON catalogs.
- Produces: reproducible evidence that the guide covers all roles, source files, scenarios, and R01–R69 receiving nodes without listing converted PDFs as default uploads.

- [ ] **Step 1: Run Markdown structure and role/category checks**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

text = Path('files/测试说明.md').read_text()
required = [
    '系统管理员', '施工方', '无损检测机构', '监检人员', '建设单位', 'FDE工程师',
    '资质证照', '设计资料', '施工方案', '材料证明与复验', '安全附件与阀门',
    '焊接资料', '热处理资料', '防腐保温资料', '安装交工资料', '试验与吹扫资料',
    '机构与人员资质', '检测方案与工艺', '检测设备与校准', '底片与影像资料',
    '检测记录', '检测报告', '问题处理闭环',
    'S01', 'S02', 'S03', 'S04', 'S05', 'S06', '上传监检资料'
]
missing = [item for item in required if item not in text]
assert not missing, missing
print('role/category/scenario structure: PASS')
PY
```

Expected: `role/category/scenario structure: PASS`.

- [ ] **Step 2: Verify exact R01–R69 table coverage**

Run:

```bash
python3 - <<'PY'
import re
from pathlib import Path

text = Path('files/测试说明.md').read_text()
section = text.split('## 9. 监检R01–R69接收对照表', 1)[1].split('## 10.', 1)[0]
rows = [int(value) for value in re.findall(r'^\| R(\d{2}) \|', section, re.M)]
assert rows == list(range(1, 70)), rows
assert 'R69' in text and '人工' in text
print('R01-R69 receiving rows: PASS')
PY
```

Expected: `R01-R69 receiving rows: PASS`.

- [ ] **Step 3: Verify all catalog source documents are accounted for**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path('files/R01-R69全节点业务验收测试包')
guide = Path('files/测试说明.md').read_text()
catalog = json.loads(Path('scripts/r01_r69_pack/data/document_catalog.json').read_text())['documents']

missing_paths = []
missing_mentions = []
for doc in catalog:
    source = root / doc['outputSubfolder'] / f"{doc['fileStem']}.{doc['sourceFormat']}"
    if not source.exists():
        missing_paths.append(str(source))
    if source.name not in guide:
        missing_mentions.append(source.name)

assert not missing_paths, missing_paths
assert not missing_mentions, missing_mentions
print(f'catalog source documents accounted: PASS ({len(catalog)})')
PY
```

Expected: `catalog source documents accounted: PASS (76)`.

- [ ] **Step 4: Verify converted PDFs are not default upload objects**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

guide = Path('files/测试说明.md').read_text()
catalog = json.loads(Path('scripts/r01_r69_pack/data/document_catalog.json').read_text())['documents']
violations = []
for doc in catalog:
    if doc['sourceFormat'] not in {'docx', 'xlsx'}:
        continue
    paired_pdf = f"{doc['fileStem']}.pdf"
    if f'`{paired_pdf}`' in guide or f'/{paired_pdf}`' in guide:
        violations.append(paired_pdf)
assert not violations, violations
assert '转换PDF仅用于预览、签章和结果核验' in guide
print('source-only upload rule: PASS')
PY
```

Expected: `source-only upload rule: PASS`.

- [ ] **Step 5: Verify Markdown and Git diff**

Run:

```bash
git diff --check
git diff -- files/测试说明.md docs/superpowers/plans/2026-07-31-test-package-upload-guide.md
```

Expected: no whitespace errors; diff contains only the plan and final guide.

- [ ] **Step 6: Commit the implementation**

```bash
git add -- docs/superpowers/plans/2026-07-31-test-package-upload-guide.md
git add -f -- files/测试说明.md
git commit -m "docs: add complete test package upload guide"
```
