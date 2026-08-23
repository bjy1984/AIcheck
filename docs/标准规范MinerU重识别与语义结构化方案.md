# 标准规范 MinerU 重识别与语义结构化方案

## 目标与非目标

**目标**：用 MinerU 重新识别标准库（`KS-STANDARD-RULES`）中的标准规范，替换当前质量偏低的 OCR 正文，并让公式、表格以结构化形式进入知识库，同时不破坏 AI 工作台中已建立的固定条款引用。

**非目标**：不改变 YAML 作为条款包维护源的地位，不调整 `standard_clause_packages` 的发布流程，不重建项目资料（非标准）侧的任何索引。

## 一、现状基线（2026-08-23 实测；P0 完成后已刷新）

以下数字来自 PostgreSQL，并由 `backend/scripts/standards_mineru_baseline.py freeze` 落盘到
`backend/data/standards_mineru_baseline/`。**Track 1 起以该快照为对照。**

| 项 | 数量 | 说明 |
|---|---|---|
| `knowledge_files`（`sourceType=standard`） | **59** | 已下线 `NB／T 47013-2015 修订版` 合集 |
| 其中有 `ocr_parse_results` 的 | ~30 | 约一半分块是离线直接写入的 |
| `knowledge_chunks`（`KS-STANDARD-RULES`） | **2119** | 下线合集后自 2134 下调 |
| `knowledge_clauses` | **2119** | 与分块一一对齐 |
| `knowledge_vectors` | **2119** | 与分块一一对齐；亦为 `backfill_knowledge_pgvector` 默认期望值 |
| `standard_clause_locators` | 243 | |
| locator 覆盖的文件数 | 32 | |
| locator 中 `chunkId` 非空的 | **0** | 引用不依赖分块 ID |
| locator 的 `precision` 取值 | `page` / `page_range` | 引用精度到页 |
| 断引用 | **0** | 原 2 条已改挂现存 KF（见下） |

磁盘与 MinerU 产物的覆盖情况：

| 位置 | 文件数 | 已有 MinerU 产物 |
|---|---|---|
| `rules/standards/`（顶层） | 37 | 37（全覆盖） |
| `rules/standards/NB_T_47013_split/` | 21 | **0（完全未跑）** |
| 合计 | 58 | 37 |

未跑 MinerU 的 21 份全部是 NB/T 47013 无损检测系列，其中 **3 份带有固定引用**：47013.1 通用要求（9 条 locator）、47013.2 射线检测（5 条）、47013.11-2023 射线数字成像（4 条）。这批文件必须纳入重跑范围。

库内曾比磁盘多出两个、现已处置：

- `NB／T 47013-2015 承压设备无损检测-修订版.pdf`：**已从标准库下线**（`KF-KB-B4C51A523B` 及其 15 条派生索引已删）
- `业务规则.md`：仍保留（非标准 PDF，位于仓库根/`rules`）

标准库条款的 OCR 引擎分布（下线前抽样，数量级仍成立）：

| 引擎 | 条款数 | 文件数 |
|---|---|---|
| `pymupdf_text_layer` | 1515 | 31 |
| `paddle_ocr_subprocess` | 483 | 22 |
| `python_text_reader` | 109 | 2 |
| （无） | 18 | 3 |
| `python_docx_xml` | 9 | 2 |

标准库中**没有任何一条**是 MinerU 产出的。磁盘侧 `rules/standards` 共 414MB，单文件最大 63.6MB。

## 二、关键约束：引用到底挂在什么上

这是决定"能否重建"的唯一前提。`standard_clause_locators` 的实际形状：

```json
{
  "locatorId": "LOC-18CB6BBB5C60",
  "knowledgeFileId": "KF-KB-CE49677F5B",
  "documentVersionId": "KDV-CE49677F5B-V1",
  "startPage": 27, "endPage": 27, "sourcePage": 27,
  "precision": "page",
  "chunkId": null,
  "bbox": null
}
```

**结论：固定引用只依赖 `knowledgeFileId` + `documentVersionId` + 页码，不依赖 `chunkId`、不依赖 `bbox`。**

因此重建的红线是三个键：`KF-KB-*`、`KDV-*`、页码。`CHK-*` / `KC-*` / `KV-*` 可以全量替换。

### 已修复：2 条断引用（P0）

原先 YAML/locator 指向已不存在的 `KF-KB-35C2CDA839` / `KF-KB-47A96E73DA`。
同名标准在库内另有存活记录，已改挂并保留原 `locatorId`：

| locatorId | standardRef | 新 knowledgeFileId |
|---|---|---|
| `LOC-7F57BDE44233` | `STD-GBT-5117-2012` | `KF-KB-7969D087E8` |
| `LOC-A3614CAF5FCD` | `STD-GBT-8110-2020` | `KF-KB-8F8C9E132E` |

涉及：`standard_clause_catalog.yaml`、`standard_clause_packages.yaml`、
`generate_standard_clause_artifacts.py`，并已 `sync_standard_clause_artifacts.py --apply`。
有效引用基数 **243**。

> **上一版方案中"尽量复用旧 `CHK-{file}-{n}` 只改 text"的做法已废弃。** MinerU 的语义分块与旧的按长度分块粒度根本不同，1:1 对齐做不到，且因为引用不挂 CHK，对齐也没有任何收益。

## 三、核心难点：结构在切片层被丢弃

这是本方案的主要工作量所在，不是 MinerU 识别本身。

MinerU 适配层**确实**保留了块类型：

```487:498:backend/libs/mineru_ocr.py
        fragments.append(
            {
                "fragmentId": f"MINERU-FRAG-{identity}",
                "candidateId": candidate_id,
                "sourceCandidateIds": [candidate_id],
                "text": text,
                "blockType": block_type,
```

`equation` 与 `interline_equation` 都会被映射为 `equation` 类型。但这个类型在下游三层里逐层丢失：

| 层 | 位置 | 丢失情况 |
|---|---|---|
| fragments → units | `knowledge_slice_fragments_from_ocr`（`backend/apps/worker/tasks.py:482`） | 只取 `bbox` / `sourceMethod` / `ocrEngine` / `ocrConfidence`，**不取 `blockType`** |
| units → chunks | `build_chunks_for_file`（`backend/libs/knowledge_indexing.py:431`） | 对每个 unit 只做 `chunk_text(unit["text"])`，纯文本切分 |
| chunks → clauses | `clause_from_chunk`（`backend/libs/knowledge_indexing.py:596`） | 无 `blockType` / `latex` 字段 |
| 库表 | `knowledge_clauses` | 实测无任何公式相关字段 |

**即使 MinerU 把公式识别为 LaTeX，落库后仍然只是一串文本。** 要做真正的语义结构化，必须扩展这四层的数据模型——这构成 Track 2 的全部内容。

另一处需要注意：MinerU 归一化时 `_content_text` 按 `("text", "latex", "content", ...)` 顺序取值，只保留一个字符串，不会同时保留渲染文本与 LaTeX 源码。若 Track 2 需要两者并存，此处也要改。

## 四、现有 MinerU 产物不可直接复用

`rules/results/` 下有 37 份 MinerU 输出的 md，只覆盖 `rules/standards/` 顶层文件，split 目录 21 份从未跑过。

即便是这 37 份也不可复用：`scripts/rules_standards_mineru_ocr.py` 只从返回的 zip 中抽取 `full.md` 写盘，**丢弃了 `content_list.json`、`layout.json` 以及 zip 本身**。因此这批 md **不含块类型、bbox 与页结构**，只能用作文本质量的人工对照，不能作为结构化摄取的输入源。

**结论：必须全量重跑 MinerU**，规模约 58–60 份 / 414MB / 单文件最大 63.6MB。配额、耗时与失败重试需要单独预算。

### 重跑的输入源应取 `output/knowledge_uploads/`

不要用 `rules/standards/` 作为重跑输入。`output/knowledge_uploads/KS-STANDARD-RULES/` 才是摄取时的真实存储，按 `knowledgeFileId` 分目录存放，具备两个 `rules/standards/` 不具备的性质：

1. **与 `knowledgeFileId` 一一对应**，不需要靠文件名做模糊匹配（标准文件名中存在全角斜杠、多余空格等不稳定因素）
2. **覆盖那 2 份不在 `rules/standards/` 下的库内文件**

`rules/standards/` 仅作为人工维护入口保留。

## 五、标准库缺少可用的重建入口

通用重建管线对标准库是被明确禁止的：

```746:769:backend/libs/knowledge_indexing.py
def reject_if_dedicated_ingestion(file: dict[str, Any]) -> None:
    """标准条款库不许走通用重建管线（dispatch_knowledge_file_index_pipeline）。
```

该护栏的文档字符串指引"要重建分块请走 `scripts/backfill_knowledge_pgvector.py`"。但经核实，**该脚本只回填向量**：

```10:14:backend/scripts/backfill_knowledge_pgvector.py
DEFAULT_SOURCE_ID = "KS-STANDARD-RULES"
DEFAULT_DIMENSIONS = 1024
DEFAULT_EXPECTED_COUNT = 2134
```

它不从源文档重建分块。**也就是说，标准库目前不存在任何被认可的分块重建路径**，本方案的摄取脚本属于新建而非复用。护栏中的指引文字应一并修正。

同时，`DEFAULT_EXPECTED_COUNT = 2134` 是硬编码期望值，重建后分块数必然变化，该常量需同步处理，否则后续向量回填会失败。

## 六、方案：拆成两条独立轨道

上一版把"换 OCR 源 + 改数据模型 + 动引用体系"捆在一起，风险面过大。现拆分为：

- **Track 1 · 文本质量重建**——用 MinerU 重出正文，**不改数据模型**，解决断行碎裂问题。风险低，收益立刻可见。
- **Track 2 · 公式与表格结构化**——扩展四层数据模型承载 `blockType` / `latex`，单独立项。

两轨共享同一份 P0 基线与护栏。Track 1 完成并稳定后再启动 Track 2。

### P0 · 基线与护栏（两轨共同前置）

1. **冻结基线快照**：✅ `backend/scripts/standards_mineru_baseline.py freeze` → `backend/data/standards_mineru_baseline/`
2. **登记已知失败项**：✅ 原 2 条断引用已修复，白名单现为空
3. **编写只读断言脚本**：✅ `standards_mineru_baseline.py assert`（当前 PASS）
4. **处置 `DEFAULT_EXPECTED_COUNT`**：✅ 优先读基线 `expectedVectorCount`（现为 2119）
5. **修正护栏指引文字**：✅ 指向 `reocr_standards_with_mineru.py`
6. **确认 MinerU 预算**：全量重跑；中断记 `_checkpoint.json` 后续跑
7. **47013 合集下线**：✅ `offline_standard_nbt47013_bundle.py --apply`

### Track 1 · 文本质量重建（已完成 2026-08-23）

1. ✅ MinerU 采集：`scripts/rules_standards_mineru_ocr.py`（uploads 输入 + sidecar + 断点）；58/59 有源文件
2. ✅ `enable_formula=true`（客户端默认）；产物含 **324** 个 equation 块、**1220** 个 table 块
3. ✅ split 目录随基线 KF 一并跑完
4. ✅ 专用摄取：`backend/scripts/reocr_standards_with_mineru.py`（按页合并 content_list → 分块）
5. ✅ 派生数据重建：分块/条款/向量均为 **3208**，模型统一 `text-embedding-v4`
6. ✅ 红线键未改：`knowledgeFileId` / `documentVersionId` / locator 页码校验 0 溢出

补充处理：
- `KF-KB-4273F0F9CE`（`.md`）：MinerU 拒识 → 直接落 sidecar
- `KF-KB-7ED59299DE`（GBT 20801.1）：整本 311 页超 MinerU 200 页上限；已拆成 1–180 / 181–311 两段跑通并合并 sidecar（含 equation 189、table 176），已重灌分块/向量
- `KF-KB-98FD02B66B`（业务规则.md）：**明确不做 MinerU**（非标准 PDF；仅保持向量与全库同模）

### Track 2 · 公式与表格结构化（开发完成 2026-08-23）

结构字段统一为四个：`blockType`（`equation` / `table`）、`latex`、`tableHtml`、`caption`。
只在确实有结构时写入，纯正文分块不带这些键——否则"这条有没有结构"无从判断。

| # | 落点 | 改动 |
|---|---|---|
| 1 | `libs/mineru_ocr.py` | 新增 `_content_latex`：MinerU 的 equation 块**不给** `latex` 字段，而是把 LaTeX 放进 `text` 并用 `text_format: "latex"` 标注。只认 `latex` 字段的话一条公式都拿不到 |
| 2 | `apps/worker/tasks.py` | `knowledge_slice_fragments_from_ocr` 透传结构字段；公式块跳过 `split_text_fragments`（按字符数硬切会把 LaTeX 断成两半） |
| 3 | `libs/knowledge_indexing.py` | `structure_fields_for_unit` 统一提取；`build_chunks_for_file` 对公式不走 `chunk_text`；`clause_from_chunk` 带出结构并打 `block_type:*` 标签 |
| 4 | `libs/knowledge_indexing.py` | 隔离规则新增 `block_type` 入参：结构块豁免 `symbol_ascii_only` 与 `low_value_short` |
| 5 | `libs/knowledge_retrieval.py` | 检索入口的二次过滤同样传入块类型；`normalize_clause` 是白名单式构造，补上结构字段才能透出到工作台 |
| 6 | `scripts/reocr_standards_with_mineru.py` | content_list 按块拆分：公式/表格独立成块，正文仍按页合并 |
| 7 | `scripts/standards_mineru_baseline.py` | 新增结构完整性断言：标了 `equation` 却无 `latex`、标了 `table` 却无 `tableHtml`、条款层与分块层结构数不一致，均判 FAIL |

**两处会静默失败的坑，已用测试钉住**（`tests/test_knowledge_structured_blocks.py`，14 例）：

1. `symbol_ascii_only` 规则会把长度不足 140 且全是 ASCII 符号的文本整条隔离。
   公式正文正是 `$$ a = \frac{S_1 - S_2}{S_1} \times 100 $$` 这种形状，落库和检索
   两道关卡都会把它滤掉，且**不报错**——只是分块少了。
2. `chunk_text` 按句读切分。`\frac{S_1 - S_2}{S_1}` 从中间断开后再也渲染不回来。

#### 粒度决策：正文只按页合并，标题不作为切分边界

先按 `text_level` 标题层级切段实现过一版，实测正文分块从 3100 涨到 **11209**
（sidecar 里 `text_level=2` 出现 8606 次），正是护栏文档里记着的那种粒度爆炸。
改为标题只用于填 `sectionPath`、不切分后：

| 类别 | 数量 |
|---|---|
| 正文块 | 3548 |
| 表格块 | 1131 |
| 公式块 | 513 |
| 合计 fragments | 5192 |

相比 Track 1 的 3203，增量全部来自被单独切出的 1644 个结构块以及它们造成的
页内分段。Track 2 要解决的是公式和表格的结构，不是把全库正文重新切一遍。

#### 重灌结果（2026-08-23）

`standards_mineru_baseline.py assert` → **PASS**：

| 项 | 数量 |
|---|---|
| `knowledge_files` | 59 |
| `knowledge_chunks` / `knowledge_clauses` / `knowledge_vectors` | **5405**（三者一致） |
| 其中 `blockType=table` | 1253（`missingTableHtml` = 0） |
| 其中 `blockType=equation` | 513（`missingLatex` = 0） |
| 条款层带结构的 | 1766（= 1253 + 513） |
| `standard_clause_locators` | 243，页码溢出 0，断引用 0 |
| 向量模型 | `text-embedding-v4`，5405 条全覆盖 |

基线已重新 freeze，`expectedVectorCount` = 5405。

批量嵌入固化为 `scripts/embed_standard_library.py`（Track 1 用的是临时 heredoc，
跑完就丢了）。它在开跑前先检查调度模式：环境变量是 `AICHECK_TASK_DISPATCH`，
**不带 `_MODE`**；写错时 `dispatch_mode()` 静默返回 `disabled`，`dispatch_embed`
对每份文件都返回空结果且不抛错——看着跑完了，实际一个向量都没写。

#### 公式的嵌入文本

裸 LaTeX 直接嵌入等于让模型去理解一串反斜杠，检索基本命不中。
`embedding_text_for_chunk` 为结构块补上条款路径与"公式/表格"字样后再送去向量化，
`embedding_batches_for_chunks` 改用该函数取文本。分块自身的 `text` 不变，
渲染与检索用的文本因此解耦。

## 七、验收标准

**引用完整性（一票否决）**

- **243** 条 locator 全部仍能解析到有效的 `knowledgeFileId` 与 `documentVersionId`（不得新增断引用）
- 页码校验**按文件分组**逐份核对，不出整体通过率——243 条只覆盖 32 个文件，其中前 3 个文件就占了 140 条，整体数字会掩盖单份文件的整体漂移
- 重点核查两类源：`NB_T_47013_split/` 下的拆分文件（本次首跑 MinerU，无历史页码可比对），以及无页码概念的 `.md` 类源
- 抽样打开原文预览链接 `#page=N`，人工确认落点正确

**数据一致性**

- `knowledge_chunks` / `knowledge_clauses` / `knowledge_vectors` 三者数量一致
- 新分块数已写回基线 `summary.json` 的 `expectedVectorCount`，`backfill_knowledge_pgvector.py` 可正常运行

**文本质量（Track 1）**

- 抽样对比重建前后的正文，确认断行碎裂（如 `L4=2.\n5Teh=…`）已消除

**结构完整性（Track 2）**

- `standards_mineru_baseline.py assert` 的 `structuredBlocks` 中 `missingLatex`
  与 `missingTableHtml` 均为 0，且条款层结构数与分块层一致
- 检索结果中公式条款能带出 `latex`、表格条款能带出 `tableHtml`
- 抽样确认公式在工作台渲染正确（**待人工**；前端渲染组件尚未接入）

## 八、明确不做的事

- 不调用 `dispatch_knowledge_file_index_pipeline` 处理标准库文件
- 不试图对齐新旧 `CHK-*` ID
- 不修改 `standard_clause_locators` 的 `locatorId`
- 不在 Track 1 中改动任何数据模型
- 页码若确实漂移，只更新 YAML 中的 `locator.page` 后重新同步，不改 locator ID

## 九、已拍板决议

| # | 议题 | 决议 |
|---|---|---|
| 1 | 页码漂移 | **接受并更新**：改 YAML 中的 `locator.page` 后重新同步，不改 `locatorId` |
| 2 | 公式是否参与向量化 | **参与**（Track 2 建模时按此定型） |
| 3 | 无固定引用的 28 份 | **一并全量重建** |
| 4 | MinerU 全量重跑 | **全量跑**；若中断则记录断点后续跑 |
| 5 | 2 条断引用 | **一并修复**（`LOC-7F57BDE44233` / `LOC-A3614CAF5FCD`） |
| 6 | `NB／T 47013-2015 修订版.pdf` | **从标准库下线**（已被 split 目录取代） |
| 7 | Track 2 正文粒度 | **不按标题切分**，仅按页合并；标题只填 `sectionPath` |
| 8 | 结构块的隔离豁免 | 只对 `blockType` 为 `equation` / `table` 的块豁免，普通噪声照旧滤掉 |

## 十、尚未完成

- **前端渲染**：`latex` / `tableHtml` 已经从检索接口透出，但工作台还没有对应的
  渲染组件（KaTeX/MathJax 与表格渲染），目前仍以纯文本显示。属产品侧决策。
- **人工校验**：正文断行修复与 `#page=N` 落点仍需抽样人工确认。
