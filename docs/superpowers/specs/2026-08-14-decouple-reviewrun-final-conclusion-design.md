# ReviewRun 与最终人工结论解耦设计

## 背景与目标

AI 复核 B 版工作台当前把“最终人工结论”作为 ReviewRun 的人工确认处理：只有 ReviewRun 进入 `waiting_human_review` 后才允许填写和提交，提交后还会改变 ReviewRun 的终态。这使业务结论被 AI 执行流程阻塞。

本次调整将最终人工结论恢复为项目节点级业务数据。监检人员可在没有 ReviewRun，或 ReviewRun 尚未完成、执行失败、存在过程人工待办时独立提交结论。ReviewRun 仅提供 AI 分析和过程记录，不再控制或承载最终人工结论。

## 业务口径

- 最终人工结论归属 `projectId + nodeId`，不归属 `reviewRunId`。
- 结论选项使用现有业务口径：`满足要求`、`需补正`、`不适用`、`证据不足`。
- 是否可提交只取决于用户角色、项目和节点范围权限，不取决于 ReviewRun 是否存在或处于何种状态。
- ReviewRun 的创建、运行、暂停、失败和终止均不阻止人工结论提交。
- 提交人工结论不结束、不恢复、不取消 ReviewRun，也不修改其状态或人工反馈。
- 现有节点结论质量校验继续生效。例如“满足要求”仍要求资料就绪，并引用当前节点已确认的证据。这些是业务证据约束，不是 ReviewRun 约束。

## 方案

### 后端投影

`review-workspace` 继续聚合当前节点数据，并把结论提交权限表达为节点审查权限。新增语义明确的 `canSubmitReviewOpinion` 权限字段，值由角色和节点访问范围决定，不读取 ReviewRun 状态。

为降低一次性契约变更风险，现有 `canSubmitHumanDecision` 可暂时保留供旧客户端使用，但 B 版工作台不再读取它。该兼容字段不参与新结论流程。

`latestHumanDecision` 改为优先返回当前节点最新的 `review_opinions` 记录。ReviewRun 上的 `humanDecision` 仅属于 ReviewRun 审计信息，不再作为节点最终结论的来源。

### 前端提交链路

AI 复核 B 版工作台的“最终人工结论”区域改用节点级结论模型：

- 单选项替换为四个业务结论选项。
- 提交权限读取 `canSubmitReviewOpinion`。
- 提交调用现有 `POST /api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions`。
- 请求包含 `result`、人工意见和已选中的 confirmed 证据 ID。
- 不再要求 `activeRunId`，不再调用 `/api/review-runs/{reviewRunId}/human-decision`，也不再使用 ReviewRun etag 或 ReviewRun 决策幂等键；并发保护改用节点结论接口既有的项目 etag。
- 确认提示改为节点人工结论语义，不再提示“结束本次 ReviewRun”。
- ReviewRun 未创建、运行中、失败或存在过程人工待办时，结论表单和提交按钮保持可用；只有无审查权限或正在提交时禁用。

ReviewRun 的“采纳、修改、驳回”仍可作为 FDE/AI 反馈能力保留在其专属审计或诊断界面，但不再出现在节点最终人工结论表单中。

### 数据流

1. 工作台按项目和节点加载 `review-workspace`。
2. 用户选择节点级业务结论、填写意见并按需选择 confirmed 证据。
3. 前端调用节点 `review-opinions` 接口。
4. 后端执行角色、节点范围、文本和证据就绪校验。
5. 后端新增 `review_opinions` 记录并更新节点业务状态。
6. 前端刷新工作台，展示最新节点结论；并行或既存的 ReviewRun 保持原状态。

## 错误处理

- 无审查权限：前端禁用提交，后端继续返回权限错误作为最终防线。
- 结论或意见为空：前端提示，后端返回参数校验错误。
- “满足要求”但资料未就绪或 confirmed 证据不足：展示现有后端业务错误，不改变 ReviewRun。
- 并发或重复提交：沿用节点结论接口现有幂等请求头机制。
- ReviewRun 刷新、轮询或 SSE 失败：不影响已经加载的节点结论表单提交能力；提交仍以节点接口结果为准。

## 测试与验收

### 后端

- `review-workspace` 在无 ReviewRun 时允许有权限的监检人员提交节点结论。
- ReviewRun 为 queued、running、waiting_human_input、failed 等状态时，节点结论权限不变。
- 节点最新人工结论来源于 `review_opinions`，不被 ReviewRun `humanDecision` 覆盖。
- 节点结论提交后，关联或并行 ReviewRun 的状态和 `humanDecision` 不变。
- 现有证据就绪、角色和节点范围校验继续生效。

### 前端

- B 版工作台不再引用 ReviewRun 人工确认提交 API。
- 表单展示四个节点业务结论选项。
- 无 ReviewRun、ReviewRun 运行中、失败、存在过程待办时均可填写并提交。
- 请求使用当前 `projectId + nodeId`，并携带意见和 confirmed 证据 ID。
- 确认文案和禁用提示不再表达 ReviewRun 前置条件。

## 非目标

- 不删除 ReviewRun 的 `human-decision` API；它仍服务 ReviewRun 审计、AI 反馈和 FDE 流程。
- 不改变 ReviewRun 编排状态机或 Temporal 工作流。
- 不放宽“满足要求”的证据质量门槛。
- 不调整其他工作台的节点人工结论流程。
