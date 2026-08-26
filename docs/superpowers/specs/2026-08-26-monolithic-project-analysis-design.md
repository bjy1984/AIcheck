# 工程一键全量分析设计

日期：2026-08-26  
状态：待用户复核

## 1. 目标

在监检平台新增独立的“一键分析”入口，将当前工程所有有有效挂接资料的业务节点、节点规则、资料要求和完整 OCR 语料拼成一个工程级 Prompt，通过一次大上下文 LLM 调用完成全工程分析。

该功能与现有项目自动审查并存：

- 项目自动审查继续按节点、EvidenceShard 多次调用；
- 一键分析固定为一个工程、一个 Prompt、一次模型调用；
- 一键分析结果仍拆回节点，等待监检人员人工确认；
- 不自动改变节点正式状态、整改状态、报告状态或归档状态。

## 2. 页面入口

监检工作台顶部入口调整为：

```text
[ AI审查 | 完整工作台 ] [ 自动审查：实时 + 每天 02:00 ] [ 一键分析 ]
```

“一键分析”仅对监检和管理员角色显示。点击后打开工程分析抽屉，展示：

- 纳入分析的业务节点数；
- 唯一 OCR 文件数；
- 节点—文件引用数；
- 预计输入 token；
- 目标模型及最大上下文；
- 最近一次工程分析状态；
- “开始全量分析”按钮；
- 当前运行进度和失败原因。

现有自动审查抽屉中的“立即执行全工程审查”保留，其含义仍是批量发起节点级审查，不改为单体 Prompt。

## 3. 单体 Prompt 数据结构

工程 Prompt 使用项目级唯一语料库：

```json
{
  "project": {
    "projectId": "P-...",
    "includedNodeCount": 42,
    "nodes": [
      {
        "nodeId": 1,
        "nodeName": "设计单位许可资质",
        "criteria": "...",
        "checkMethod": "...",
        "configuredRequirements": [],
        "fileRefs": [
          {
            "fileId": "FILE-1",
            "documentVersionId": "DV-1",
            "fileName": "设计许可证.pdf"
          }
        ]
      }
    ],
    "fileCorpus": {
      "FILE-1": {
        "fileId": "FILE-1",
        "documentVersionId": "DV-1",
        "fileName": "设计许可证.pdf",
        "sourceContentHash": "sha256:...",
        "cleanedContentHash": "sha256:...",
        "fullOcrText": "完整 OCR 文字"
      }
    }
  }
}
```

约束：

- 同一文档版本的 OCR 正文只在 `fileCorpus` 出现一次；
- 节点通过 `fileRefs[].fileId` 解析正文；
- 当前节点只能使用自己 `fileRefs` 引用的文件；
- 后上传资料触发的新分析必须包含节点全部当前有效历史资料；
- 无挂接资料节点不进入 Prompt；
- 删除遗留规则 `Use only files in the current node linkedFiles`，统一改为 `fileRefs/fileCorpus`；
- OCR 清洗只移除 HTML 标签、图片路径、控制符、零宽字符和空白结构，保留表格行顺序、单元格顺序及文字值；
- 保存源内容哈希和清洗后内容哈希，支持审计回放。

## 4. 不可变工程快照

开始分析前创建 `ProjectAnalysisSnapshot`：

```json
{
  "projectAnalysisSnapshotId": "PASNAP-...",
  "projectId": "P-...",
  "nodeIds": [1, 2, 3],
  "nodeSnapshotHashes": {},
  "documentVersionIds": [],
  "nodeFileRefs": {},
  "ruleVersions": {},
  "promptVersion": "project-monolithic-analysis@1.0.0",
  "modelRouteVersion": "...",
  "snapshotHash": "sha256:..."
}
```

运行期间新增、替换、驳回或解除挂载的资料不修改当前快照；它们形成新的快照，供下一次一键分析使用。

幂等键覆盖：

```text
tenantId + projectId + snapshotHash + promptVersion + modelRouteVersion
```

## 5. 上下文限制

一键分析必须保持单次模型调用语义：

- 不静默裁剪；
- 不自动切换为节点分片；
- 不删除末尾 OCR；
- 不用摘要替代完整 OCR；
- 模型路由必须配置 `maxContextTokens` 和预留输出 token；
- 调度前估算完整 messages token；
- 超限时不调用模型，返回 `PROJECT_ANALYSIS_CONTEXT_LIMIT_EXCEEDED`；
- 页面展示预计 token、模型上限和超出数量，提示改用现有节点级自动审查。

## 6. 运行记录

新增 `ProjectAnalysisRun`：

```json
{
  "projectAnalysisRunId": "PARUN-...",
  "projectAnalysisSnapshotId": "PASNAP-...",
  "tenantId": "TENANT-...",
  "projectId": "P-...",
  "status": "preparing_snapshot",
  "phase": "preparing_snapshot",
  "includedNodeCount": 0,
  "uniqueFileCount": 0,
  "fileReferenceCount": 0,
  "estimatedInputTokens": 0,
  "modelAlias": "project-review-large",
  "modelAttemptId": null,
  "validatedFindingCount": 0,
  "persistedNodeCount": 0,
  "createdAt": "..."
}
```

一个运行最多对应一个成功的模型调用。模型调用记录输入哈希、输出哈希、token 使用量、成本、供应商请求 ID 和原始响应审计引用。

## 7. 真实进度展示

进度不伪造模型内部完成百分比。状态采用阶段和可验证计数：

| 阶段 | 页面展示 | 确定进度 |
|---|---|---:|
| `preparing_snapshot` | 正在收集节点和当前有效文档 | 节点 `prepared/total` |
| `building_prompt` | 正在清洗、去重并拼接 OCR | 文件 `loaded/total`、预计 token |
| `queued` | 已进入大模型队列 | 排队时长、队列任务 ID |
| `model_running` | 大模型正在分析 | 不确定进度条、运行时长、最近心跳 |
| `validating_output` | 正在验证 JSON、证据和规则引用 | Finding `validated/total` |
| `persisting_results` | 正在将结果挂回节点 | 节点 `persisted/total` |
| `waiting_human_review` | 分析完成，等待人工确认 | 100% |
| `failed` | 分析失败 | 失败阶段、错误码、可重试说明 |

接口每次阶段变化写入 `ProjectAnalysisEvent`。前端每 2 秒读取轻量状态接口；`model_running` 阶段使用不确定进度条，不根据时间虚构 30%、60% 等百分比。

关闭抽屉不取消任务。第一版不提供取消正在执行的供应商请求。

## 8. API

```text
GET  /projects/{projectId}/inspection/full-project-analysis/preview
POST /projects/{projectId}/inspection/full-project-analysis/runs
GET  /projects/{projectId}/inspection/full-project-analysis/runs
GET  /projects/{projectId}/inspection/full-project-analysis/runs/{runId}
GET  /projects/{projectId}/inspection/full-project-analysis/runs/{runId}/status
```

要求：

- 监检/管理员权限；
- 租户和项目隔离；
- POST 支持 `Idempotency-Key`；
- Preview 和 POST 使用快照哈希防止预览后资料变化；
- 所有写操作记录审计日志。

## 9. Worker 与模型路由

新增 Celery 任务：

```text
project_analysis_prepare
project_analysis_execute_model
project_analysis_validate_output
project_analysis_persist_results
```

准备、验证和持久化进入 `business.light`；唯一模型调用进入 `llm.remote`。

使用独立模型别名 `project-review-large`，不得无声回退到小上下文模型。模型不可用时运行失败，不影响 OCR、挂载和节点正式业务状态。

## 10. 输出校验

模型输出不得直接生效。后端必须执行：

1. JSON 和 `AIAllReviewResult@2.0.0` Schema 校验；
2. `nodeReviews` 与快照节点一一对应；
3. evidenceRef 的 fileId 属于当前节点 fileRefs；
4. fileId 能解析到 fileCorpus；
5. documentVersionId、fileName 与语料一致；
6. quotedText 逐字存在于 fullOcrText；
7. 不连续引用必须拆成多条 evidenceRef；
8. ruleRef 仅允许逐字引用当前节点 criteria 或 checkMethod；
9. 无直接证据的正面结论降级为 `insufficient_evidence`；
10. 无效引用的 grounded Finding 降级并将置信度封顶为 0.55；
11. `projectSummary` 由后端重新统计，不信任模型计数；
12. 所有 Finding 强制 `requiresHumanConfirmation=true`。

## 11. 节点结果归属

模型只调用一次，但验证通过后为每个节点创建一个派生 `ReviewRun`：

```json
{
  "reviewRunId": "RRUN-...",
  "projectAnalysisRunId": "PARUN-...",
  "projectId": "P-...",
  "nodeId": 1,
  "triggerType": "manual_full_project_analysis",
  "sharedModelAttemptId": "MCALL-...",
  "status": "waiting_human_review",
  "findingDrafts": []
}
```

派生 ReviewRun 不再调用模型，只承载节点结果、证据引用和审计链。旧节点 ReviewRun 不覆盖、不删除，可标记 superseded。

一键分析为 advisory-only：不得自动把节点设置为通过、需补正、不适用或已完成。

## 12. 失败与恢复

- 无有效挂接节点：不发模型请求，返回明确空范围结果；
- Prompt 超限：Preview 和运行均阻断；
- 模型超时或网关失败：保留失败运行，可基于相同快照手动重试；
- 输出截断：标记 `LLM_OUTPUT_TRUNCATED`，不持久化部分节点结果；
- JSON 无效：标记 `LLM_OUTPUT_INVALID_JSON`；
- 部分 Finding 引用无效：逐条降级，其他有效 Finding 保留；
- 节点回挂部分失败：运行停在 `persisting_results`/`partial_failure`，重试只处理未持久化节点；
- 运行完成后资料变化：页面显示“资料已更新，可重新分析”，不污染历史快照。

## 13. 审计与可观测性

记录：

- 操作人和触发时间；
- 工程快照、节点快照及哈希；
- 节点—文件引用；
- source/cleaned OCR 哈希；
- Prompt 版本、模型路由版本、预计与实际 token；
- 单次模型调用尝试；
- 原始响应哈希；
- 每条 Finding 的校验结果和降级原因；
- 后端重算的工程汇总；
- 节点派生 ReviewRun IDs；
- 人工采纳、编辑和驳回反馈。

## 14. 与现有功能的关系

```text
自动审查 / 立即执行全工程审查
  → ProjectReviewRun
  → 多个 NodeReviewRun
  → 多次 EvidenceShard 模型调用

一键分析
  → ProjectAnalysisRun
  → 一个工程级 Prompt
  → 一次大上下文模型调用
  → 校验后派生多个 NodeReviewRun
```

两条链路共享 FindingDraft、人工确认和证据校验规则，但不共享任务语义，不互相替代。

## 15. 验收标准

- 监检页面显示独立“一键分析”按钮；
- Preview 显示节点、文件、引用、预计 token 和模型上限；
- 单次运行只产生一个模型调用；
- 同一 OCR 文本只在 fileCorpus 出现一次；
- 每个 fileRef 都能解析，未解析引用为 0；
- 无资料节点不进入 Prompt；
- 超上下文时明确阻断，不裁剪、不分片；
- 页面展示真实阶段、计数、时长和心跳；
- 模型阶段不显示虚构百分比；
- 关闭页面后任务继续，重新进入可恢复进度；
- quotedText、ruleRef、节点文件边界通过后端校验；
- 工程汇总由后端重算；
- 结果回挂到各节点派生 ReviewRun；
- 所有结果等待人工确认，不改变正式业务状态；
- 旧 `linkedFiles` Prompt 规则已删除；
- 后端、前端、OpenAPI、部署契约和浏览器验收全部通过；
- 完成后将 `codex/auto-review` 合并到本地 `main`。
