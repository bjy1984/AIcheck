# 标准规范信息最全集合设计

## 1. 目标

为每一份标准规范生成唯一、可追溯、可展示、可检索、可供 AI 审查使用的 canonical 信息全集。

全集必须同时吸收新 MinerU OCR、旧 OCR、人工视觉抽取、知识切片、条款、PageIndex、标准版本、条款定位和业务规则引用等现有信息源，并遵守以下优先级：

1. 同一语义字段新旧结果都有时，使用新结果。
2. 只有新结果有的信息直接纳入。
3. 只有旧结果有的信息继续纳入，但标记为 `legacy_only`，不得覆盖新值。
4. 正文、条款、表格、公式、图片和印章按稳定身份与内容哈希去重，不因来源不同而重复展示。
5. 每项 canonical 信息必须能够追溯到文件、文档版本、解析结果、页码、坐标和原始来源。

## 2. 范围

### 2.1 包含

- 59 条标准库基线记录，其中 58 份有可执行的标准原文，`业务规则.md` 作为规则上下文单独处理。
- 当前 58 份 MinerU sidecar 结构化 OCR。
- 旧 `ocr_parse_results`、`extracted_fields` 和 `evidence_links`。
- `backend/data/visual_extractions` 中的人工视觉抽取。
- `backend/data/rules_ocr_sidecars` 中的旧规则 OCR sidecar。
- `knowledge_chunks`、`knowledge_clauses` 和 `knowledge_page_index_nodes`。
- `standard_document_versions`、`standard_clause_references` 和 `standard_clause_locators`。
- 业务包 `standardCatalog`、规则 `referencedStandards`、监检节点与材料类型关系。
- 标准详情接口、检索候选、AI 审查输入和 `FileDetailDialog` 展示。

### 2.2 不包含

- 修改标准原文。
- 删除任何旧 OCR、旧字段、旧证据或旧条款记录。
- 将 `legacy_only` 值冒充为新 OCR 已确认值。
- 在本阶段引入 PDF.js 或在线编辑能力。

## 3. 当前证据基线

截至 2026-08-29：

| 数据源 | 覆盖 |
|---|---:|
| 标准基线 | 59/59 |
| 新 MinerU OCR | 58/59 |
| 旧 OCR | 29/59 |
| 人工视觉抽取 | 25/59 |
| 旧规则 OCR sidecar | 7/59 |
| 字段/证据投影 | 29/59，且均为 `OCR文本1～5` 占位字段 |
| 知识切片 | 59/59 |
| 知识条款 | 59/59 |
| PageIndex | 59/59，共 5,464 个标准节点 |
| 标准版本记录 | 33/59 |
| 条款引用与定位 | 32/59 |

新 MinerU OCR 已入库 58 份，包含 49,436 个版面块、56 张表格、1,624 行归一化表格数据、96 个印章候选和 3,247 页。

## 4. 架构原则

### 4.1 原始数据不可变

现有集合继续作为来源事实保存：

- `ocr_parse_results`
- `extracted_fields`
- `evidence_links`
- `knowledge_chunks`
- `knowledge_clauses`
- `knowledge_page_index_nodes`
- 标准版本、引用和定位集合
- 文件系统 sidecar 与视觉抽取 JSON

canonical 生成器只读取这些来源并生成派生记录。不得覆盖或删除来源记录。

### 4.2 一个标准一份 canonical 记录

新增逻辑集合：

```text
standard_knowledge_records
```

主键使用 `knowledgeFileId`。记录绑定 `documentId` 和当前 `documentVersionId`，并通过 `canonicalVersion`、`sourceFingerprint` 和 `generatedAt` 支持幂等重建。

### 4.3 新值优先，旧值补缺

合并在语义字段级进行，不按整个来源覆盖：

```text
new_mineru > visual_extraction > standard_catalog > legacy_ocr > filename_inference
```

该顺序仅用于同一字段冲突。旧来源独有的字段、正文或关系仍进入全集，并带上来源等级。

### 4.4 当前值与来源分离

canonical 条目包含当前值和来源列表：

```json
{
  "key": "publicationDate",
  "value": "2015-04-02",
  "authority": "current",
  "selectedSourceId": "PARSE-STANDARD-...",
  "sources": [
    {
      "sourceType": "new_mineru",
      "sourceId": "PARSE-STANDARD-...",
      "value": "2015-04-02",
      "pageNo": 1,
      "bbox": [10, 20, 300, 80]
    }
  ]
}
```

旧独有信息使用 `authority="legacy_only"`。同一字段旧值仍保存在 `sources` 中，但不作为 `value`。

## 5. Canonical 数据契约

```json
{
  "id": "SKR-KF-KB-...",
  "knowledgeFileId": "KF-KB-...",
  "documentId": "KDOC-...",
  "documentVersionId": "KDV-...-V1",
  "canonicalVersion": "standard-knowledge-canonical@1",
  "identity": {},
  "version": {},
  "metadata": {},
  "sections": [],
  "clauses": [],
  "blocks": [],
  "tables": [],
  "equations": [],
  "images": [],
  "seals": [],
  "normativeReferences": [],
  "replacementRelations": [],
  "businessRelations": [],
  "evidence": [],
  "provenance": [],
  "completeness": {},
  "history": [],
  "sourceFingerprint": "sha256:...",
  "generatedAt": "..."
}
```

### 5.1 `identity`

- `standardCode`
- `standardNameZh`
- `standardNameEn`
- `standardType`
- `partNumber`
- `icsCode`
- `ccsCode`
- `filingNumber`
- `sourceFileName`
- `sourceRelativePath`

### 5.2 `version`

- `edition`
- `publicationDate`
- `effectiveDate`
- `issuingAuthority`
- `proposingOrganization`
- `administeringOrganization`
- `draftingOrganizations`
- `draftingPeople`
- `status`
- `replaces`
- `replacedBy`
- `amendments`
- `releaseId`
- `businessPackVersion`

### 5.3 `metadata`

- `scope`
- `purpose`
- `applicability`
- `keywords`
- `abstract`
- `foreword`
- `introduction`
- `termsAndDefinitionsSummary`
- `requiredCapabilities`
- `language`
- `pageCount`

### 5.4 结构内容

- `sections`：层级、标题、编号、页码范围、父子关系。
- `clauses`：条款号、标题、全文、所属章节、页码、bbox、标签。
- `blocks`：正文、标题、列表、页眉、页脚、旁注、代码等阅读顺序块。
- `tables`：标题、列、归一化行、单元格、页码、bbox、必备性标签。
- `equations`：原文、LaTeX、编号、上下文、页码、bbox。
- `images`：图题、图片类型、图片路径、页码、bbox。
- `seals`：名称、类型、识别状态、证据等级、页码、bbox、是否需人工确认。

### 5.5 关系

- `normativeReferences`：引用标准编号、名称、条款、来源页。
- `replacementRelations`：替代、被替代、修改单关系。
- `businessRelations`：业务规则、监检节点、材料类型、原子检查项和适用目的。

### 5.6 证据与来源

每一条字段、条款、表格、公式和关系都包含：

- `sourceType`
- `sourceId`
- `parseResultId`
- `documentVersionId`
- `pageNo`
- `bbox`
- `quotedText`
- `confidence`
- `needsHumanVerification`
- `authority`
- `contentHash`

## 6. 稳定身份与去重

### 6.1 字段

使用标准字段代码作为身份，例如 `publicationDate`。同一代码按来源优先级选当前值。

### 6.2 章节与条款

优先身份：

```text
standardCode + edition + clauseNo
```

缺少条款号时使用：

```text
sectionPath + normalizedTextHash + pageNo
```

### 6.3 表格、公式和图片

使用：

```text
blockType + pageNo + normalizedContentHash + normalizedBbox
```

结构相同但来源不同的记录合并到同一 canonical 条目，来源全部保留。

### 6.4 引用关系

使用规范化标准编号和条款号：

```text
sourceStandardCode + sourceClauseNo + targetStandardCode + targetClauseNo
```

## 7. Canonical 生成流程

1. 读取标准文件、文档和当前版本。
2. 读取当前新 MinerU parse result。
3. 读取该版本全部旧 parse result、字段和证据。
4. 读取视觉抽取和旧规则 sidecar。
5. 读取切片、条款和 PageIndex。
6. 读取标准版本、条款引用和定位。
7. 读取业务包标准目录和规则引用。
8. 规范化来源数据为统一候选结构。
9. 按字段优先级选择当前值。
10. 将旧独有内容标记为 `legacy_only` 后补入。
11. 按稳定身份去重结构内容和关系。
12. 计算完整度、来源指纹和差异统计。
13. 幂等写入 `standard_knowledge_records`。

任一来源读取失败时，不得删除已有 canonical 记录。生成结果标记为 `partial`，并记录具体失败来源。

## 8. 完整度模型

每份标准必须输出以下类别状态：

```text
identity
version
metadata
fullText
sections
clauses
tables
equations
images
seals
normativeReferences
replacementRelations
businessRelations
evidenceLocation
history
```

状态取值：

- `complete`
- `partial`
- `missing`
- `not_applicable`

总体状态只有在所有必需类别均为 `complete` 或 `not_applicable` 时才为 `complete`。不能以数组非空代替语义完整性。

## 9. API

### 9.1 当前全集

```text
GET /api/knowledge/files/{fileId}/canonical
```

返回完整 canonical 记录，支持可选参数：

- `includeBlocks`
- `includeHistory`
- `section`
- `pageNo`

### 9.2 主详情接口

现有文件详情增加：

```json
{
  "canonical": {},
  "canonicalSummary": {},
  "activeParseResultId": "...",
  "completeness": {}
}
```

保留现有 `ocrStructured`，在迁移期由 canonical 结构投影生成，避免现有前端立即失效。

### 9.3 历史来源详情

```text
GET /api/knowledge/files/{fileId}/canonical/sources/{sourceId}
```

仅用于只读追溯，不参与当前 AI 判断。

## 10. 前端

`FileDetailDialog` 增加以下区域：

1. 标准概览：身份、版本、状态、发布机构、范围和替代关系。
2. 结构化内容：字段、章节、条款、表格、公式、图片、印章。
3. 引用与业务关系：规范性引用、关联规则和监检节点。
4. 完整度：逐类别展示 complete/partial/missing。
5. 来源与历史：新值、旧来源、`legacy_only` 补充和原始 parse result。

当前展示永远使用 canonical `value`。旧值只能在来源/历史中查看。

标准详情不再使用“证书编号、设计压力”类项目资料提示。提示按标准完整度生成，例如：

- `标准正文已识别，标准版本信息不完整`
- `表格可阅读，但部分单元格无法定位原文`
- `缺少规范性引用关系`

## 11. 检索与 AI 审查

- 检索候选从 canonical 条款、表格、公式和关系生成。
- 当前值和新 OCR 内容使用正常权重。
- `legacy_only` 内容可检索，但必须带来源标签并降低正式证据权重。
- 旧冲突值不进入当前检索文本。
- AI 审查输入记录 `canonicalVersion`、`sourceFingerprint` 和使用的 canonical 条目 ID。
- 需要正式证据的结论必须引用具有页码/bbox 或精确条款定位的 canonical 条目。

## 12. 迁移方案

### 阶段 A：只读生成与报告

- 建立 canonical builder。
- 对 59 份标准生成 dry-run JSON。
- 输出字段选择、旧独有内容、去重数量和完整度报告。
- 不写数据库。

### 阶段 B：写入派生集合

- 备份相关集合。
- 幂等写入 `standard_knowledge_records`。
- 不修改来源集合。
- 逐条校验文件、文档和版本关系。

### 阶段 C：接口与前端

- 接入 canonical API。
- 详情页展示全集和完整度。
- 保持旧 `ocrStructured` 兼容。

### 阶段 D：检索和 AI 消费

- canonical 投影到检索候选。
- AI 审查记录 canonical 版本。
- 对比旧检索结果，确认没有信息丢失。

### 阶段 E：专项补齐

- 对缺少标准版本的 26 份补抽取。
- 对缺少引用与定位的 27 份补抽取。
- 对缺少视觉元数据的 34 份按优先级补抽取。
- `业务规则.md` 明确标记为 `context_only`。

## 13. 验收标准

### 13.1 覆盖

- 59/59 有 canonical 记录。
- 58/58 原文标准包含新 MinerU 内容。
- 旧 OCR、视觉抽取、旧 sidecar、条款和关系均有来源覆盖报告。
- 无孤立来源：所有有效来源记录都能映射到 canonical 或明确列为拒绝项。

### 13.2 内容

- 新旧同字段只使用新值。
- 旧独有信息全部保留且标记 `legacy_only`。
- 正文、章节、条款、表格、公式、图片和印章均能展示。
- 所有表格保留归一化行或原始单元格。
- 所有公式保留完整 LaTeX。

### 13.3 追溯

- 每项 canonical 信息都有来源。
- 有坐标的内容可定位原文。
- 缺坐标时明确标记，不伪造定位。
- AI 结果可回溯 canonical 版本和来源。

### 13.4 安全与幂等

- 重复生成不增加重复记录。
- 来源内容不变时 `sourceFingerprint` 不变。
- 任一标准失败不影响其他标准。
- 生成失败不覆盖上一份有效 canonical。
- 迁移前后来源集合的记录数和内容摘要一致。

### 13.5 UI

- 标准详情显示 canonical 全集。
- 新值和旧来源区分清楚。
- 不再显示项目资料专用误导提示。
- 每份标准显示完整度和具体缺项。

## 14. 测试策略

- 单元测试：来源规范化、优先级、旧值补缺、去重、完整度。
- 契约测试：canonical API、历史来源 API、详情兼容字段。
- 数据迁移测试：59 份 dry-run、幂等双跑、失败隔离、来源摘要不变。
- 检索测试：表格、公式、条款、引用关系和 `legacy_only` 权重。
- 前端测试：当前值、来源历史、完整度、定位、空态与错误态。
- 浏览器验收：至少覆盖普通标准、超长标准、无 layout 标准、含表格标准、旧信息补缺标准和 `context_only` 规则文档。

## 15. 回滚

- canonical 是派生集合，回滚只需停用新读路径并删除指定 `canonicalVersion` 的派生记录。
- 原始 OCR、字段、证据、切片、条款和 PageIndex 不受影响。
- API 保留旧 `ocrStructured` 兼容路径，直到 canonical 验收通过。

