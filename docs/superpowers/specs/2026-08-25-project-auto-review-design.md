# 项目自动审查与无损证据拼接设计

日期：2026-08-25
状态：已实现并验收

## 1. 背景

监检工作台目前支持按业务节点手动发起 AI ReviewRun，并把 FindingDraft 通过 `projectId`、`nodeId` 和 `reviewRunId` 挂回节点。现有“一键审查”也是批量创建多个节点 ReviewRun，不是一个真正的工程级运行。

现有审查输入存在两类问题：

1. OCR 原文、表格、字段、印章和证据链接经过固定数量或固定字符裁剪，造成关键许可范围、制造资质、签章、表格行等信息没有进入模型。
2. 离线工程 Prompt 使用已经裁剪过的 `evidenceExcerpts`，与生产 `EvidenceGroundedReviewInput` 不是同一数据契约。

本设计建立统一的项目自动审查机制和无损证据输入机制，同时保留现有节点级人工确认边界。

## 2. 目标

### 2.1 功能目标

- 在监检页面“AI审查 / 完整工作台”分段控件旁增加“开启/关闭自动审查”按钮。
- 自动审查按项目配置。
- 支持 OCR 成功并完成节点挂载后的即时审查。
- 支持每天指定时间扫描需要重新审查的节点。
- 支持“即时 + 定时补偿”的混合模式。
- 支持手动立即执行一次全工程审查。
- 全工程审查作为自动审查协调器的一种触发范围，不改变节点级结果归属。
- 不同业务节点可以使用不同 Prompt、事实模型、工具、模型路由和证据分片方案。
- 当单次模型上下文不足时，增加模型调用次数，不静默删除 OCR 信息。

### 2.2 数据完整性目标

- 每个进入审查范围的 OCR 页、字段、表格、印章、片段和证据链接都有明确处理状态。
- 禁止通过数组切片或字符截断静默丢弃证据。
- 每个节点完成前必须验证 EvidenceShard 覆盖率为 100%。
- 所有 FindingDraft 必须能够回放到文档版本、页码和 bbox，或明确标记为无可定位证据。
- 模型供应商的物理上下文上限通过分片和多次调用处理，不通过删除证据处理。

### 2.3 业务边界

- 自动审查只生成待人工确认草稿。
- 自动审查不得自动批准、退回、下发整改、关闭整改、归档或改变正式业务结论。
- 监检人员仍然是最终业务结论的责任主体。
- 自动审查建议使用 `gap_precheck` 和 `advisoryOnly=true`。

## 3. 核心不变量

### 3.1 节点累计资料必须整体重审

业务节点的资料可能分多次上传。后续资料进入节点时，新 ReviewRun 的输入必须包含该节点截至本次快照的全部有效挂接资料，而不能只包含本次新增资料。

例如：

```text
第一次上传：设计许可证
第二次上传：施工图
第三次上传：设计印章页
```

第三次触发审查时，输入必须是：

```text
设计许可证 + 施工图 + 设计印章页
```

不得只审“设计印章页”。

### 3.2 增量触发不等于增量证据输入

新增资料只用于标记节点变脏和触发新审查。实际模型输入使用完整的累计证据快照。

可以利用模型缓存、文档摘要缓存和已处理 EvidenceShard 复用降低成本，但这些优化不得改变本次 ReviewRun 的逻辑输入集合。

### 3.3 ReviewRun 输入快照不可变

ReviewRun 启动后，其证据集合不可修改。

如果运行期间又有资料进入节点：

1. 当前 ReviewRun 继续使用启动时的快照；
2. 节点被重新标记为 dirty；
3. 新资料形成新的 evidenceSnapshotHash；
4. 当前运行完成后自动创建下一次累计快照 ReviewRun。

不得把新资料追加到正在执行的模型调用中。

### 3.4 文档新版本与历史版本

- 同一逻辑文档上传新版本后，新的活动快照默认使用最新有效版本。
- 被替代版本不进入新的业务判断，但必须保留在历史 ReviewRun 中供审计回放。
- 不同逻辑文档即使属于相同资料类型，也必须全部保留在活动快照中。
- 文件被人工驳回、解除挂载或作废后，新快照必须移除该文件并触发重新审查。

### 3.5 最新结果不能覆盖历史审计

- 最新成功快照的节点 FindingDraft 是当前活动建议。
- 旧 ReviewRun 和旧 FindingDraft 保留，不物理覆盖。
- 新结果可以标记旧结果为 superseded，但不得删除旧结果。
- 节点页面默认展示最新活动建议，并提供历史运行入口。

## 4. 总体架构

```text
文件上传
  → OCR 成功
  → 资料分类
  → 节点打靶与挂载持久化
  → node.evidence.mounted Outbox 事件
  → AutoReviewCoordinator
      ├── 即时触发
      ├── 每日定时扫描
      └── 手动全工程触发
  → ProjectReviewRun
      ├── NodeReviewRun 1
      │    ├── EvidenceManifest
      │    ├── EvidenceShard 1..N
      │    ├── ModelAttempt 1..N
      │    └── NodeFindingAggregate
      ├── NodeReviewRun 2
      └── NodeReviewRun N
  → ProjectReviewSummary
  → FindingDraft 继续挂回各业务节点
```

## 5. 页面设计

### 5.1 顶部入口

监检工作台顶部调整为：

```text
[ AI审查 | 完整工作台 ]  [ 自动审查：已开启 ▼ ]
```

按钮状态：

- 自动审查：已关闭
- 自动审查：实时
- 自动审查：每天 02:00
- 自动审查：实时 + 每天 02:00

### 5.2 配置抽屉

点击自动审查按钮打开项目级配置抽屉：

- 开启/关闭自动审查；
- 上传后即时审查；
- 每日定时审查；
- 每日执行时间；
- 项目时区；
- 当前待审节点数；
- 最近一次自动审查时间和结果；
- 立即执行一次全工程审查。

关闭开关只禁止产生新自动任务，不取消正在运行的 ReviewRun。

### 5.3 状态展示

项目级状态：

```text
自动审查已开启
模式：上传后即时 + 每天 02:00
待审节点：3
执行中：2
最近完成：今天 14:32
失败：1
```

节点级状态：

- 等待自动审查
- 自动审查排队中
- 自动审查中 3/8 分片
- 等待人工确认
- 自动审查失败
- 证据已更新，等待重新审查

## 6. 自动审查策略

### 6.1 AutoReviewPolicy

```json
{
  "id": "ARP-...",
  "tenantId": "TENANT-DEFAULT",
  "projectId": "P-...",
  "enabled": true,
  "triggerModes": ["ocr_mounted", "daily_schedule"],
  "dailyTime": "02:00",
  "timezone": "Asia/Shanghai",
  "reviewMode": "gap_precheck",
  "debounceSeconds": 300,
  "revision": 1,
  "updatedBy": "...",
  "updatedAt": "..."
}
```

策略按项目保存。只有拥有项目自动审查管理权限的监检人员可以修改。

### 6.2 即时触发

即时触发必须发生在以下操作全部成功并持久化之后：

1. OCR 完成；
2. 资料分类完成；
3. 节点打靶完成；
4. Binding 和 NodeEvidenceLink 已保存；
5. 当前文档版本可被 ReviewRun 读取。

OCR Worker 不直接调用模型，只写事务性 Outbox 事件。模型服务故障不能把 OCR 成功状态回滚为失败。

### 6.3 每日扫描

定时协调器每分钟检查到期策略，在项目当地时区达到配置时间时：

1. 计算所有有有效挂接资料节点的当前证据快照；
2. 找出当前快照与最近一次成功 ReviewRun 输入哈希不同的节点；
3. 为这些节点创建一个 ProjectReviewRun；
4. 创建节点子 ReviewRun。

定时扫描同时负责补偿丢失的即时事件和失败重试。

### 6.4 手动全工程审查

手动全工程审查创建 ProjectReviewRun，并把当前所有有有效挂接资料的节点加入范围。它不创建一个包含所有 OCR 的单体模型请求。

## 7. 证据新鲜度与幂等

### 7.1 EvidenceSnapshot

每次节点审查前构造不可变证据快照：

```json
{
  "evidenceSnapshotId": "ESNAP-...",
  "projectId": "P-...",
  "nodeId": 12,
  "documentVersions": [
    {
      "documentId": "DOC-1",
      "documentVersionId": "DV-1-V2",
      "ocrParseResultId": "OCR-...",
      "contentHash": "sha256:...",
      "mountRevision": 4
    }
  ],
  "ruleVersion": "...",
  "clausePackageVersion": "...",
  "promptVersion": "...",
  "snapshotHash": "sha256:...",
  "createdAt": "..."
}
```

`snapshotHash` 必须覆盖：

- 当前全部有效挂接文档版本；
- OCR 结果哈希；
- 挂载关系及修订号；
- 业务规则版本；
- 条款包版本；
- Prompt 和节点策略版本。

### 7.2 幂等键

```text
tenantId
+ projectId
+ nodeId
+ evidenceSnapshotHash
+ autoReviewPolicyRevision
```

相同幂等键不得创建重复节点 ReviewRun。

### 7.3 Dirty 状态

以下事件使节点变脏：

- 新文档首次挂载；
- 同一文档的新版本生效；
- 挂载文件被驳回、作废或解除；
- OCR 结果发生变化；
- 人工证据确认状态变化；
- 规则、条款包、Prompt 或节点策略版本变化；
- 上次运行失败或分片不完整。

## 8. 工程父任务与节点子任务

### 8.1 ProjectReviewRun

```json
{
  "projectReviewRunId": "PRRUN-...",
  "projectId": "P-...",
  "triggerType": "ocr_mounted",
  "policySnapshot": {},
  "expectedNodeIds": [1, 2, 12],
  "childReviewRunIds": [],
  "completedNodeIds": [],
  "failedNodeIds": [],
  "status": "running",
  "createdAt": "..."
}
```

### 8.2 NodeReviewRun

复用现有 ReviewRun，并增加：

```json
{
  "projectReviewRunId": "PRRUN-...",
  "evidenceSnapshotId": "ESNAP-...",
  "evidenceSnapshotHash": "sha256:...",
  "triggerType": "ocr_mounted",
  "autoReviewPolicyRevision": 1
}
```

现有 `projectId`、`nodeId`、`reviewRunId` 和 `findingDrafts` 继续作为节点结果归属。

### 8.3 ProjectReviewSummary

工程汇总只读取已经完成的节点结果：

```json
{
  "projectReviewRunId": "PRRUN-...",
  "nodeSummaries": [
    {
      "nodeId": 12,
      "reviewRunId": "RRUN-...",
      "findingCount": 3,
      "highestSeverity": "high"
    }
  ],
  "commonRisks": [],
  "priorityReviewNodeIds": [],
  "completion": {
    "expectedNodeCount": 3,
    "completedNodeCount": 3,
    "failedNodeCount": 0
  }
}
```

工程汇总不得覆盖节点 FindingDraft，也不得形成自动业务结论。

## 9. 无损 OCR 证据结构

### 9.1 权威分层

```text
NodeEvidenceLink
  → 文件为什么属于节点

EvidenceManifest
  → 节点累计证据快照中的全部 OCR 内容目录

EvidenceShard
  → 为适应模型物理上下文进行的无损分片

FindingDraft.evidenceRefs
  → 结论实际引用的证据位置
```

### 9.2 移除静默裁剪

以下固定裁剪不能继续用于决定证据是否进入整个 ReviewRun：

```python
fields[:80]
tables[:20]
seals[:20]
fragments[:80]
evidenceLinks[:80]
evidenceTextCorpus[:240]
```

以下表格限制也不能造成整份证据永久丢失：

```text
6000 字符
60 行
160 单元格
```

允许把大表拆成多个 shard，但必须保存全部行、单元格和来源坐标。

### 9.3 EvidenceManifest

EvidenceManifest 对当前累计快照中的所有文档建立目录：

```json
{
  "evidenceManifestId": "EMAN-...",
  "evidenceSnapshotId": "ESNAP-...",
  "documents": [
    {
      "documentVersionId": "DV-...",
      "ocrParseResultId": "OCR-...",
      "pageCount": 120,
      "fieldIds": [],
      "tableIds": [],
      "sealIds": [],
      "fragmentIds": [],
      "contentHash": "sha256:..."
    }
  ],
  "expectedArtifactCount": 0,
  "manifestHash": "sha256:..."
}
```

### 9.4 EvidenceShard

```json
{
  "evidenceShardId": "ESHARD-...",
  "reviewRunId": "RRUN-...",
  "nodeId": 12,
  "documentVersionId": "DV-...",
  "pageStart": 1,
  "pageEnd": 20,
  "artifactIds": [],
  "contentHash": "sha256:...",
  "status": "pending",
  "modelAttemptIds": []
}
```

分片规则优先使用自然边界：

- 文档；
- 页；
- 表格；
- 证书或报告区块；
- OCR fragment 边界。

不得在无记录的情况下截断字符串。

### 9.5 覆盖门禁

节点聚合前必须满足：

```json
{
  "expectedShardCount": 8,
  "completedShardCount": 8,
  "failedShardCount": 0,
  "processedArtifactCount": 320,
  "expectedArtifactCount": 320,
  "coveragePassed": true
}
```

覆盖未通过时，节点只能标记为 `review_incomplete`，不能伪装为已完成。

## 10. 节点策略与多模型调用

每个节点通过 NodeReviewStrategy 定义审查方式：

```json
{
  "nodeId": 12,
  "strategyType": "manufacturing_license_review",
  "modelAlias": "review-chat",
  "shardMode": "document_and_page",
  "tools": [
    "verify_manufacturing_license",
    "compare_component_scope"
  ],
  "requiredFactTypes": [
    "manufacturer",
    "licenseNumber",
    "licenseScope",
    "componentType",
    "validity"
  ],
  "version": "1.0.0"
}
```

不同节点可采用不同：

- Prompt；
- 模型路由；
- 工具集合；
- 事实结构；
- shard 分组；
- 聚合规则。

共同输出仍使用 FindingDraft，并由后端补入 `projectId`、`nodeId` 和 `reviewRunId`。

## 11. 节点结果聚合

同一节点的所有 shard 和模型调用完成后，NodeFindingAggregate：

- 按 finding 类型、事实对象和证据引用去重；
- 合并证据，不丢弃少数模型发现的问题；
- 保留不同模型之间的冲突；
- 拒绝无证据引用的正面业务断言；
- 验证引用属于当前累计 EvidenceSnapshot；
- 形成该节点最终 FindingDraft；
- 设置 `requiresHumanConfirmation=true`。

节点聚合只使用当前快照结果，不把旧快照的 Finding 无条件混入。旧结果用于变化对比和审计。

## 12. 事件与任务

### 12.1 Outbox 事件

新增事件：

- `document.ocr.completed`
- `node.evidence.mounted`
- `node.evidence.unmounted`
- `node.evidence.snapshot_changed`
- `auto_review.candidate.created`
- `project_review_run.started`
- `node_review_run.started`
- `node_review_run.completed`
- `project_review_run.completed`

事件与挂载数据在同一事务中写入，确保不会出现挂载成功但事件永久丢失。

### 12.2 Celery 任务

新增任务：

- `auto_review_scan_due_projects`
- `auto_review_consume_evidence_event`
- `auto_review_start_project_run`
- `auto_review_start_node_run`
- `auto_review_process_evidence_shard`
- `auto_review_aggregate_node`
- `auto_review_finalize_project`

使用数据库保存策略、候选、运行和幂等状态；Celery Beat 每分钟触发到期策略扫描；Celery Worker 执行具体任务。

## 13. API

```text
GET  /projects/{projectId}/inspection/auto-review-policy
PUT  /projects/{projectId}/inspection/auto-review-policy

GET  /projects/{projectId}/inspection/auto-review-status

POST /projects/{projectId}/inspection/auto-review/run

GET  /projects/{projectId}/inspection/project-review-runs
GET  /projects/{projectId}/inspection/project-review-runs/{id}
```

策略更新和手动运行必须支持：

- 权限检查；
- `Idempotency-Key`；
- ETag/Revision；
- 审计日志；
- 租户和项目隔离。

## 14. 失败与恢复

- OCR 成功但没有节点挂载：不创建审查候选，记录原因。
- 即时事件丢失：每日扫描根据快照差异补偿。
- 相同证据快照重复触发：幂等命中，不重复创建 ReviewRun。
- 节点运行中又有新资料：当前运行不变，完成后按新快照再运行。
- 某个 shard 失败：只重试该 shard；达到上限后节点标记为 incomplete。
- 某个节点失败：不阻止其他节点完成，但 ProjectReviewRun 显示部分失败。
- 模型物理上下文超限：缩小 shard 并重试，不删除证据。
- 关闭自动审查：停止新任务，不取消已运行任务。

## 15. 可观测性与审计

每次运行记录：

- 触发来源；
- 策略快照；
- 累计证据快照及哈希；
- 新增、移除和替代的文档版本；
- EvidenceManifest；
- 全部 shard 及覆盖率；
- 每次模型调用输入哈希、输出哈希和 token 使用量；
- 聚合版本；
- FindingDraft 变化；
- 人工采纳、修改或驳回结果。

页面必须能够回答：

```text
为什么这个节点又被自动审查？
本次比上次新增了哪些资料？
本次模型实际审了哪些完整资料？
是否有任何 OCR 内容未处理？
哪个 Finding 来自哪次模型调用和哪段原文？
```

## 16. 方案选择记录

### 16.1 采用

采用：

```text
项目级自动审查策略
+ 即时 Outbox 事件
+ 每日定时补偿扫描
+ ProjectReviewRun 父任务
+ 现有 NodeReviewRun 子任务
+ 累计不可变 EvidenceSnapshot
+ 无损 EvidenceManifest/EvidenceShard
+ 节点级多模型策略
+ 节点结果回挂
```

### 16.2 不采用

不采用 OCR Worker 直接调用模型，因为模型故障不能影响 OCR 成功事务。

不采用单体全工程模型请求，因为业务节点差异大、上下文容易串扰、结果容易遗漏。

不采用只审新增文件的增量输入，因为后续资料必须与节点历史资料共同判断。

不采用静默 token 裁剪，因为它会造成模型在不知道资料残缺的情况下形成错误结论。

## 17. 实施阶段

1. 新增 AutoReviewPolicy、ProjectReviewRun、AutoReviewCandidate 和 EvidenceSnapshot。
2. 在监检工作台增加自动审查按钮与配置抽屉。
3. 在 OCR/分类/打靶成功事务后写 Outbox 事件。
4. 增加实时消费和每日定时扫描。
5. 将全工程审查建模为父任务和节点子 ReviewRun。
6. 建立累计证据快照和 dirty/hash 幂等规则。
7. 建立 EvidenceManifest 和 EvidenceShard。
8. 移除所有静默数组、表格和字符裁剪。
9. 增加节点级策略和多模型聚合。
10. 增加覆盖门禁、审计、指标和失败恢复。

## 18. 验收标准

- 监检人员可以按项目开启、关闭和配置自动审查。
- OCR 成功并完成节点挂载后，符合策略的节点自动进入待审。
- 每日定时扫描只审证据快照发生变化或上次失败的节点。
- 后上传资料触发的新 ReviewRun 包含该节点全部当前有效历史挂接资料。
- 运行期间新增资料不会污染当前快照，而会产生下一次累计快照审查。
- 同一证据快照不会产生重复 ReviewRun。
- 手动全工程审查创建父任务和节点子任务，不创建单体工程 Prompt。
- 每个 FindingDraft 继续通过 `projectId/nodeId/reviewRunId` 挂回节点。
- 所有 EvidenceShard 和 OCR artifact 覆盖率达到 100% 后，节点才可完成。
- 模型上下文超限时通过增加调用次数处理，不静默删除证据。
- 自动审查结果不会自动改变正式业务状态。

## 19. 实施与验收记录

实现分支：`codex/auto-review`。

实现结果：

- 项目级策略、实时 Outbox、每日补偿扫描、手动全工程父任务和节点子任务均已落地；
- 后续上传会基于全部当前有效挂接资料生成新的不可变累计快照；
- EvidenceManifest 对字段、表格、印章、片段和证据链接建立完整目录；
- EvidenceShard 逐片进入模型调用，并记录 ModelAttempt 双向引用；
- 节点聚合保留不同发现和冲突，只合并完全相同的发现；
- 结构覆盖与模型处理覆盖分开计量，只有两者都通过时 `coveragePassed=true`；
- 分片失败时节点进入 `review_incomplete`，成功兄弟分片不回滚，正式业务状态不改变；
- ProjectReviewRun 列表、详情、ProjectReviewSummary、定时收口和分片进度已提供；
- test/test2 离线包均包含 42 个有挂接资料的节点，结构覆盖率为 100%，执行前不会误报为处理完成；
- 监检工作台已通过真实浏览器复验：按钮位置、项目隔离、配置抽屉、手动运行确认和分片状态展示正常。

数据持久化沿用现有通用 JSONB 状态集合，因此不需要新增关系型表 DDL；新增集合已加入仓库映射、持久化加载范围和部署契约门禁。生产部署继续使用现有业务 Worker 的内嵌 Celery Beat，不新增未部署服务。
