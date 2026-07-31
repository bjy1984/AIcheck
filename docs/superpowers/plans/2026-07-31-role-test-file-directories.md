# Role Test File Directories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `files/角色测试文件` with six role-oriented work areas, 76 byte-identical source-file copies, and instructions that tell every role exactly where to select each upload file.

**Architecture:** Treat `document_catalog.json` and the existing complete package as the authoritative source. A fixed logical-ID mapping assigns every catalog document exactly once to test-control, contractor, NDT, or inspection folders; static role guidance plus mechanically generated per-file manifests provide the local-selection and UI-entry navigation. Validation independently rebuilds the expected source/destination pairs and compares counts, formats, hashes, documentation coverage, the original package, and the full existing test suite.

**Tech Stack:** Python 3 standard library (`json`, `pathlib`, `shutil`, `hashlib`), Markdown, existing `unittest` package tests, Git.

## Global Constraints

- Create the new root exactly at `files/角色测试文件`.
- Copy exactly 76 catalog source files: DOCX, XLSX, JPG, and the one native PDF; do not copy DOCX/XLSX-derived paired PDFs.
- Distribute the 76 files exactly as test-control 12, contractor 44, NDT 8, and inspection 12.
- Do not place engineering DOCX, XLSX, JPG, or PDF files under system-administrator, owner, or FDE directories.
- Do not change any file under `files/R01-R69全节点业务验收测试包`; it must remain a 136-file valid package.
- Each copied file must have the same SHA-256 digest as its authoritative source.
- R01–R69 is inspection navigation only; contractor and NDT directories follow their own UI categories.
- Every upload manifest row must state login role, UI entry/action, local selection directory, actual filename, expected inspection nodes, purpose, and notes.
- Photos without OCR information remain selectable and are submitted for manual inspection review.
- Preserve the existing “exception during process, all-qualified final closure” test order.
- Because `files/` is ignored, stage intended artifacts with `git add -f`.

---

### Task 1: Establish the Role Directory Skeleton and Static Guidance

**Files:**
- Create: `files/角色测试文件/目录说明.md`
- Create: `files/角色测试文件/01_系统管理员_不上传业务资料/操作说明.md`
- Create: `files/角色测试文件/03_无损检测机构/02_检测方案与工艺/操作说明.md`
- Create: `files/角色测试文件/03_无损检测机构/03_检测设备与校准/操作说明.md`
- Create: `files/角色测试文件/03_无损检测机构/05_检测记录/操作说明.md`
- Create: `files/角色测试文件/03_无损检测机构/07_问题处理闭环/操作说明.md`
- Create: `files/角色测试文件/05_建设单位_只读/操作说明.md`
- Create: `files/角色测试文件/06_FDE工程师_技术审计/操作说明.md`
- Create directories: all contractor, NDT, and 12 inspection subdirectories named in the approved design.

**Interfaces:**
- Consumes: approved design `docs/superpowers/specs/2026-07-31-role-test-file-directories-design.md`.
- Produces: stable local selection roots and role-boundary instructions consumed by manifests and testers.

- [ ] **Step 1: Run the pre-generation assertion**

Run:

```bash
test ! -e 'files/角色测试文件'
```

Expected: exit 0, proving the new artifact has not already been partially generated.

- [ ] **Step 2: Create the complete directory skeleton**

Run one `mkdir -p` command with these exact relative paths:

```text
files/角色测试文件/00_测试控制资料_不上传
files/角色测试文件/01_系统管理员_不上传业务资料
files/角色测试文件/02_施工方/01_资质证照
files/角色测试文件/02_施工方/02_设计资料
files/角色测试文件/02_施工方/03_施工方案
files/角色测试文件/02_施工方/04_材料证明与复验
files/角色测试文件/02_施工方/05_安全附件与阀门
files/角色测试文件/02_施工方/06_焊接资料
files/角色测试文件/02_施工方/07_热处理资料
files/角色测试文件/02_施工方/08_防腐保温资料
files/角色测试文件/02_施工方/09_安装交工资料
files/角色测试文件/02_施工方/10_试验与吹扫资料
files/角色测试文件/03_无损检测机构/01_机构与人员资质
files/角色测试文件/03_无损检测机构/02_检测方案与工艺
files/角色测试文件/03_无损检测机构/03_检测设备与校准
files/角色测试文件/03_无损检测机构/04_底片与影像资料
files/角色测试文件/03_无损检测机构/05_检测记录
files/角色测试文件/03_无损检测机构/06_检测报告
files/角色测试文件/03_无损检测机构/07_问题处理闭环
files/角色测试文件/04_监检人员/R21_材料标志移植
files/角色测试文件/04_监检人员/R24_焊工资格证及持证合格项目
files/角色测试文件/04_监检人员/R28_管道组对
files/角色测试文件/04_监检人员/R30_焊接接头外观质量
files/角色测试文件/04_监检人员/R44_防腐、补口、补伤及保温
files/角色测试文件/04_监检人员/R48_穿跨越工程的管道结构、焊缝布置
files/角色测试文件/04_监检人员/R49_穿跨越工程施工
files/角色测试文件/04_监检人员/R50_套管防腐绝缘
files/角色测试文件/04_监检人员/R51_绝缘支撑
files/角色测试文件/04_监检人员/R52_管道现场制作（预制）
files/角色测试文件/04_监检人员/R53_管道布管与连接方式、穿跨越
files/角色测试文件/04_监检人员/R69_施工单位质量保证体系实施状况的评价
files/角色测试文件/05_建设单位_只读
files/角色测试文件/06_FDE工程师_技术审计
```

- [ ] **Step 3: Write static guidance with `apply_patch`**

`目录说明.md` must contain the six-role table from design section 5, the exact local roots, a four-step selection example for contractor/NDT/inspection, source-versus-PDF rules, and links to all three `上传清单.md` files plus the control `文件清单.md`.

The three non-upload role documents must explicitly say “不选择、不上传工程业务文件” and state their UI responsibilities. The four empty NDT-category documents must point to the reused source files or UI-created structured record identified in `files/测试说明.md` sections 6.3, 6.4, 6.6, and 6.8.

- [ ] **Step 4: Verify skeleton and static role boundaries**

Run:

```bash
find 'files/角色测试文件' -type d | sort
find 'files/角色测试文件/01_系统管理员_不上传业务资料' \
     'files/角色测试文件/05_建设单位_只读' \
     'files/角色测试文件/06_FDE工程师_技术审计' \
     -type f ! -name '*.md' -print
```

Expected: all 37 directories are listed; the second command prints nothing.

### Task 2: Copy All 76 Source Files Using the Fixed Assignment

**Files:**
- Create: 12 source copies under `files/角色测试文件/00_测试控制资料_不上传`
- Create: 44 source copies under `files/角色测试文件/02_施工方`
- Create: 8 source copies under `files/角色测试文件/03_无损检测机构`
- Create: 12 source copies under `files/角色测试文件/04_监检人员`

**Interfaces:**
- Consumes: `scripts/r01_r69_pack/data/document_catalog.json` fields `logicalId`, `outputSubfolder`, `fileStem`, `sourceFormat`, `title`, and `rNodes`; authoritative files under `files/R01-R69全节点业务验收测试包`.
- Produces: one destination path per logical ID and 76 byte-identical copies.

- [ ] **Step 1: Run the failing copy-count assertion**

Run:

```bash
test "$(find 'files/角色测试文件' -type f \( -name '*.docx' -o -name '*.xlsx' -o -name '*.jpg' -o -name '*.pdf' \) | wc -l | tr -d ' ')" = 76
```

Expected: non-zero because no source copies exist yet.

- [ ] **Step 2: Execute one fixed-mapping copy pass**

Use a Python standard-library command that reads the catalog, resolves each source as `outputSubfolder/fileStem.sourceFormat`, calls `shutil.copy2`, and fails unless all 76 catalog IDs are assigned exactly once. Use these exact assignments:

```python
support = {
    "M00-README-001", "M00-MASTER-001", "M00-DIR-001",
    "M00-SOURCE-001", "M00-DATA-001", "M00-SEAL-001",
    "B00-QUALITY-001", "V00-NODE-MATRIX-001", "V00-REQ-MATRIX-001",
    "V00-SOURCE-DIFF-001", "V00-CHECKSUM-001", "V00-REPORT-001",
}

contractor = {
    "M00-STD-001": "02_设计资料",
    "B00-DESIGN-001": "02_设计资料", "B00-CONSTRUCTION-001": "03_施工方案",
    "B00-QUAL-001": "01_资质证照", "B00-LINES-001": "02_设计资料",
    "B00-MATERIAL-001": "04_材料证明与复验", "B00-VALVE-001": "05_安全附件与阀门",
    "B00-WELD-001": "06_焊接资料", "B00-WELD-LEDGER-001": "06_焊接资料",
    "B00-TEST-001": "10_试验与吹扫资料", "B00-INSTALL-001": "09_安装交工资料",
    "S01-DESIGN-001": "02_设计资料", "S01-FOREIGN-001": "04_材料证明与复验",
    "S01-MATERIAL-001": "04_材料证明与复验", "S01-RETEST-001": "04_材料证明与复验",
    "S01-REVIEW-001": "04_材料证明与复验", "S01-ACCEPT-001": "04_材料证明与复验",
    "S01-MARK-001": "04_材料证明与复验", "S02-DESIGN-001": "02_设计资料",
    "S02-CALC-001": "02_设计资料", "S02-APPROVAL-001": "04_材料证明与复验",
    "S02-WPS-001": "06_焊接资料", "S02-INSTALL-001": "09_安装交工资料",
    "S03-DESIGN-001": "02_设计资料", "S03-WPS-001": "06_焊接资料",
    "S03-WELDER-001": "06_焊接资料", "S03-WELDLOG-001": "06_焊接资料",
    "S03-REPAIR-001": "06_焊接资料", "S03-PWHT-001": "07_热处理资料",
    "S03-PWHT-RECORD-001": "07_热处理资料", "S04-DESIGN-001": "02_设计资料",
    "S04-DIAGRAM-001": "02_设计资料", "S04-EQUIP-001": "08_防腐保温资料",
    "S04-INSTALL-001": "09_安装交工资料", "S04-CP-001": "08_防腐保温资料",
    "S05-DESIGN-001": "02_设计资料", "S05-ACCESSORY-001": "05_安全附件与阀门",
    "S05-INSTALL-001": "05_安全附件与阀门", "S05-PSV-001": "05_安全附件与阀门",
    "S05-ESDV-001": "05_安全附件与阀门", "S06-ANALYSIS-001": "02_设计资料",
    "S06-APPROVAL-001": "10_试验与吹扫资料", "S06-ALTERNATIVE-001": "10_试验与吹扫资料",
    "S06-FINAL-001": "10_试验与吹扫资料",
}

ndt = {
    "B00-NDT-001": "01_机构与人员资质",
    "B00-FILM-001": "04_底片与影像资料", "B00-FILM-002": "04_底片与影像资料",
    "B00-PHOTO-003": "04_底片与影像资料",
    "S03-NDT-INITIAL-001": "06_检测报告", "S03-NDT-REPEAT-001": "06_检测报告",
    "S06-NDT-001": "06_检测报告", "S06-FILM-001": "04_底片与影像资料",
}

inspection = {
    "S01-PHOTO-001": "R21_材料标志移植",
    "B00-QUERY-001": "R24_焊工资格证及持证合格项目",
    "B00-PHOTO-001": "R28_管道组对",
    "B00-PHOTO-002": "R30_焊接接头外观质量",
    "B00-PHOTO-004": "R44_防腐、补口、补伤及保温",
    "S04-PHOTO-001": "R48_穿跨越工程的管道结构、焊缝布置",
    "S04-PHOTO-002": "R49_穿跨越工程施工",
    "S04-PHOTO-003": "R50_套管防腐绝缘",
    "S04-PHOTO-004": "R51_绝缘支撑",
    "S04-PHOTO-005": "R52_管道现场制作（预制）",
    "S04-PHOTO-006": "R53_管道布管与连接方式、穿跨越",
    "V00-R69-001": "R69_施工单位质量保证体系实施状况的评价",
}
```

- [ ] **Step 3: Verify count, extensions, and distribution**

Run an independent Python check that counts only `.docx`, `.xlsx`, `.jpg`, and `.pdf` files and asserts:

```python
assert total == 76
assert counts == {"00": 12, "02": 44, "03": 8, "04": 12}
assert native_pdfs == ["S04_S04-DIAGRAM-001_TEST-S04-002_穿越结构与焊缝布置图.pdf"]
```

Expected: all assertions pass.

### Task 3: Generate Per-File Selection Manifests and Navigation

**Files:**
- Create: `files/角色测试文件/00_测试控制资料_不上传/文件清单.md`
- Create: `files/角色测试文件/02_施工方/上传清单.md`
- Create: `files/角色测试文件/03_无损检测机构/上传清单.md`
- Create: `files/角色测试文件/04_监检人员/上传清单.md`
- Modify: `files/测试说明.md`

**Interfaces:**
- Consumes: Task 2 destination mapping and catalog metadata.
- Produces: a one-row-per-file local selection index and a backlink from the main UI-operation guide.

- [ ] **Step 1: Run manifest coverage assertions before generation**

Run:

```bash
test -f 'files/角色测试文件/02_施工方/上传清单.md'
test -f 'files/角色测试文件/03_无损检测机构/上传清单.md'
test -f 'files/角色测试文件/04_监检人员/上传清单.md'
```

Expected: non-zero before the manifests exist.

- [ ] **Step 2: Mechanically generate four Markdown manifests**

For each assigned catalog row, write exactly one table row with these columns:

```text
序号 | 逻辑文件编号 | 场景 | 登录角色 | 界面入口或操作 | 本地选择目录 | 选择的源文件名 | 监检预期接收节点 | 用途 | 备注
```

Use `基础项目` for `B00`, `全包控制` for `M00`/`V00` except R69, and the scenario folder name for S01–S06. Format catalog `rNodes` as comma-separated `Rnn`; use `不上传` for control files. Use these exact UI rules:

```python
contractor_ui = lambda category: f"施工方工作台 → 项目文件库 / 施工资料台账 → {category[3:]} → 上传资料 → 选择环节 → 提交"
ndt_ui = {
    "01_机构与人员资质": "无损检测工作台 → 无损检测资料库 / 检测资料台账 → 机构与人员资质 → 上传资料",
    "04_底片与影像资料": "无损检测工作台 → 新增底片编号 → 登记焊口关系 → 上传底片/影像 → 提交检测资料",
    "06_检测报告": "无损检测工作台 → 上传检测报告 → 填写元数据 → 关联底片 → 提交检测资料",
}
inspection_ui = lambda node: f"监检工作台 → {node.split('_', 1)[0]} → 上传监检资料 → 提交"
```

Every manifest introduction must include one complete “登录角色 → 界面入口 → 本地目录 → 选择文件 → 提交” example. Control `文件清单.md` must state that none of its 12 rows are uploaded.

- [ ] **Step 3: Add the role-selection navigation to the main guide with `apply_patch`**

Insert after `files/测试说明.md` section 1 a new subsection named `1.1 按角色选择本地源文件`. It must link these exact relative locations:

```text
files/角色测试文件/目录说明.md
files/角色测试文件/02_施工方/上传清单.md
files/角色测试文件/03_无损检测机构/上传清单.md
files/角色测试文件/04_监检人员/上传清单.md
files/角色测试文件/00_测试控制资料_不上传/文件清单.md
```

State that the role directories contain actual source-file copies, while the original complete package remains authoritative and unchanged.

- [ ] **Step 4: Verify manifest rows resolve to actual local files**

Run an independent parser that reads each table, combines `本地选择目录` with `选择的源文件名`, and asserts the path exists. Assert manifest data-row counts are exactly 12, 44, 8, and 12 and every row contains its login role and UI entry.

Expected: 76 rows resolve, with no missing local path and no duplicate logical ID.

### Task 4: Prove Hash, Format, Package, and Documentation Integrity

**Files:**
- Verify only: all generated files, original complete package, current Git diff.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: evidence that every explicit acceptance criterion is satisfied.

- [ ] **Step 1: Compare every source/destination SHA-256**

Independently rebuild the 76 source/destination pairs from the fixed mapping, stream each file through `hashlib.sha256`, and assert source digest equals destination digest. Print a summary exactly containing:

```text
SHA-256一致: 76/76
角色分布: 控制=12, 施工方=44, 无损检测=8, 监检=12
```

- [ ] **Step 2: Prove no derived PDF was copied**

For every catalog row whose `sourceFormat` is `docx` or `xlsx`, assert no same-stem `.pdf` appears anywhere under `files/角色测试文件`. Assert the only copied PDF is catalog-native `S04-DIAGRAM-001`.

- [ ] **Step 3: Validate documentation and role boundaries**

Use `rg` plus a Markdown-table parser to prove:

- all six interface roles appear in `目录说明.md`;
- three upload manifests contain the “本地选择目录” and “选择的源文件名” columns;
- all 76 logical IDs appear exactly once across the four manifests;
- the main `测试说明.md` points to the role directory and all manifests;
- administrator, owner, and FDE directories contain Markdown only;
- photo notes explicitly allow submission without OCR.

- [ ] **Step 4: Revalidate the original package and full test suite**

Run:

```bash
test "$(find 'files/R01-R69全节点业务验收测试包' -type f | wc -l | tr -d ' ')" = 136
/Users/hankieyooly/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s scripts/r01_r69_pack/tests -v
```

Expected: original count remains 136 and all existing tests pass (currently 34 tests).

- [ ] **Step 5: Inspect and commit the generated package**

Run:

```bash
git diff --check
git status --short
git add -f 'files/角色测试文件' 'files/测试说明.md'
git add docs/superpowers/plans/2026-07-31-role-test-file-directories.md
git diff --cached --stat
git commit -m 'feat: add role-based test upload directories'
```

Expected: the commit contains the role directory, the main-guide navigation update, and this plan; no original complete-package file is modified.

### Task 5: Push and Verify the Existing Pull Request

**Files:**
- External state only: branch `codex/r01-r69-acceptance-pack-pr`, existing PR #2.

**Interfaces:**
- Consumes: verified local commits from Tasks 1–4.
- Produces: remote branch and PR head synchronized with local HEAD.

- [ ] **Step 1: Confirm branch/worktree state**

Run the read-only worktree detection commands required by `superpowers:using-git-worktrees`; assert the branch is `codex/r01-r69-acceptance-pack-pr` and is not detached.

- [ ] **Step 2: Push the current branch**

Run:

```bash
git push origin codex/r01-r69-acceptance-pack-pr
```

Expected: push succeeds and remote branch advances to local HEAD.

- [ ] **Step 3: Verify PR #2 through the GitHub connector**

Read the existing PR and verify it remains open, targets `main`, uses head `codex/r01-r69-acceptance-pack-pr`, is mergeable, and its head SHA equals local `git rev-parse HEAD`. Update the PR description only if it does not mention the new role directories and per-role selection manifests.

- [ ] **Step 4: Run the final completion audit**

Check every acceptance criterion in the approved design section 8 against current files, command outputs, Git state, and PR state. Only after every item is supported by direct evidence, mark the active goal complete.
