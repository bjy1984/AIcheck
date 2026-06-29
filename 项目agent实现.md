# 项目 Agent 实现分析

## 1. 结论

当前工程中还没有真正的 Agent 或 LangGraph 实现。

现有“AI 复核 / AI 审查”能力本质上是：

```text
前端触发 AI 复核
-> FastAPI 创建 ai_run
-> task_dispatcher 投递 Celery 任务
-> worker 收集 OCR 字段
-> 拼接 Prompt
-> 调用 LiteLLM 的 OpenAI-compatible chat/completions 接口
-> 回写 ai_runs.suggestion
-> 前端展示 AI 建议、证据链、人工采纳/驳回
```

也就是说，当前实现是“异步 LLM 复核任务 + 业务状态回写”，不是具备工具调用、状态图、条件路由、人工中断恢复的 autonomous agent。

项目中也没有引入以下依赖或代码形态：

- `langgraph`
- `langchain`
- `StateGraph`
- `AgentExecutor`
- `create_react_agent`
- `@tool`
- 工具选择循环
- LangGraph checkpointer / interrupt / graph state

## 2. 后端 AI 复核链路

### 2.1 API 创建 AI Run

入口：

```text
backend/apps/api/routes.py
POST /projects/{project_id}/inspection/nodes/{node_id}/ai-recheck
```

该接口会创建一条 `ai_runs` 记录，核心字段包括：

- `id`
- `projectId`
- `nodeId`
- `subject`
- `model`
- `promptVersion`
- `ruleVersion`
- `inputDocumentVersionIds`
- `status`
- `steps`
- `suggestion`
- `evidenceLinks`

当前创建时的默认值：

```text
model: review-chat
promptVersion: node-{node_id}-v1
ruleVersion: Welder-Qualification-B-v2.1
status: 推理中
suggestion.result: 需人工确认
suggestion.opinionDraft: AI 复核任务已进入队列，完成后将更新审查建议。
confidence: 0.0
```

创建完成后，接口会：

1. 将 run 插入 `repo.state["ai_runs"]`。
2. 将节点状态设置为 `业务核验中`。
3. 调用 `task_dispatcher.dispatch_ai_recheck(project_id, node_id, run_id)`。

### 2.2 任务分发

任务分发在：

```text
backend/libs/integrations/task_dispatcher.py
```

当前支持三种模式：

| 模式 | 含义 |
|---|---|
| `disabled` | 不真正执行任务，只返回空 taskId |
| `inline` | 在当前 API 进程里同步执行 worker task |
| `celery` | 投递到 Celery 队列异步执行 |

AI 复核对应函数：

```python
dispatch_ai_recheck(project_id, node_id, run_id)
```

Celery 队列配置在：

```text
backend/apps/worker/celery_app.py
```

对应队列：

```text
inspection.ai_recheck
```

### 2.3 Worker 执行 AI 复核

核心实现位于：

```text
backend/apps/worker/tasks.py
ai_recheck(...)
```

当前执行流程：

1. 调用 `repo.load_from_sync_postgres()` 加载业务状态。
2. 根据 `run_id` 查找 `ai_runs`。
3. 根据 run 的 `inputDocumentVersionIds` 查找 `extracted_fields`。
4. 拼接一个简单中文 Prompt。
5. 调用 LiteLLM chat completion。
6. 将模型返回文本写入 `run["suggestion"]["opinionDraft"]`。
7. 写入简化步骤 `LiteLLM 复核`。
8. 写入若干 evidence links。
9. 失败时写入 `AI_RUN_FAILED`。

当前 prompt 形式大致为：

```python
prompt = (
    f"请基于压力管道监检规则复核节点 {node_id} {node.get('name') if node else ''}。"
    f"OCR字段: {fields[:12]}"
)
```

调用模型：

```python
LiteLLMClient().chat_sync(
    [
        {"role": "system", "content": "你是压力管道监督检验 AI 复核助手。"},
        {"role": "user", "content": prompt},
    ],
    model=run.get("model") or "review-chat",
    temperature=0.1,
)
```

成功后当前固定回写：

```text
run.status = 完成
run.steps = [LiteLLM 复核]
suggestion.result = 需人工确认
suggestion.confidence = 0.82
suggestion.manualConfirmItems = ["证据链和原件一致性"]
run.evidenceLinks = repo.state["evidence_links"][:5]
```

这说明当前还不是规则节点化推理，而是一次性 LLM 复核。

## 3. LiteLLM 集成

LiteLLM client 位于：

```text
backend/libs/integrations/litellm_client.py
```

它只是一个 OpenAI-compatible HTTP client，提供：

- `chat(...)`
- `chat_sync(...)`
- `embed(...)`
- `embed_sync(...)`
- `first_message_text(...)`

模型配置位于：

```text
backend/config/litellm.yaml
```

当前模型别名：

| 模型别名 | 实际模型 |
|---|---|
| `default-chat` | `openai/gpt-4o-mini` |
| `review-chat` | `openai/gpt-4o` |
| `compare-fast` | `openai/gpt-4o-mini` |
| `embedding-default` | `openai/text-embedding-3-large` |

LiteLLM 只负责模型网关，不负责 Agent 编排。

## 4. OCR 与知识处理

OCR service 位于：

```text
backend/apps/ocr_service/service.py
```

它会尝试从 `AICHECK_AGENTDESIGN_BACKEND` 指定路径导入外部 OCR 管线：

```python
from seal_ocr.pipeline import recognize_document
```

或：

```python
from seal_ocr.pipeline import SealOcrPipeline
```

如果外部 OCR 管线不可用：

- 当 `AICHECK_OCR_ALLOW_PLACEHOLDER=true` 时，返回 placeholder OCR。
- 当 `AICHECK_OCR_ALLOW_PLACEHOLDER=false` 时，返回失败结果。

OCR 成功后会标准化为：

- `fragments`
- `fields`
- `seals`
- `diagnostics`

这些字段后续会进入 `extracted_fields`，供 AI 复核 worker 拼 Prompt 使用。

## 5. 前端 AI 展示链路

### 5.1 节点包加载

前端工作台通过节点包接口获取 AI 运行记录：

```text
GET /projects/{project_id}/nodes/{node_id}/package
```

该接口返回：

- `node`
- `requirements`
- `bindings`
- `projectFiles`
- `availableVersions`
- `extractedFields`
- `reviewOpinions`
- `aiRuns`
- `actions`

其中 `aiRuns` 来自：

```python
repo.state["ai_runs"]
```

### 5.2 前端类型定义

AI run 类型定义在：

```text
frontend/src/types/aicheck.ts
```

核心结构：

```ts
export type AiReviewRun = {
  id: string
  projectId: string
  nodeId: number
  subject: string
  model: string
  promptVersion: string
  ruleVersion: string
  status: '推理中' | '完成' | '失败' | '已人工确认'
  suggestion: {
    id: string
    result: '满足要求' | '需补正' | '不适用' | '需人工确认'
    opinionDraft: string
    confidence: number
    manualConfirmItems: string[]
  }
  evidenceLinks: EvidenceLink[]
  finishedAt?: string
}
```

### 5.3 工作台展示

工作台位于：

```text
frontend/src/views/AICheck/Workbench.vue
```

当前取最新 AI run：

```ts
const latestAiRun = computed(() => nodePackage.value?.aiRuns[0])
const evidenceLinks = computed(() => latestAiRun.value?.evidenceLinks || [])
```

“业务核验链路”不是后端真实逐节点推理结果，而是前端基于以下数据拼出来的展示：

- `latestAiRun.suggestion.opinionDraft`
- `latestAiRun.ruleVersion`
- `latestAiRun.promptVersion`
- `extractedFields`
- `evidenceLinks`

当前展示步骤包括：

- 证书真实性核验
- 关键字段一致性
- 业务规则适配

这更像 UI 层对 AI run 的解释性展示，不是 LangGraph 真实执行步骤。

### 5.4 重新核验

前端 API：

```text
frontend/src/api/aicheck/index.ts
requestAiRecheckApi(...)
```

实际请求：

```text
POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck
```

页面按钮位于工作台顶部，“重新核验”会触发该接口。

### 5.5 AI 建议采纳与驳回

采纳接口：

```text
POST /projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/adopt
```

当前逻辑只是生成一个审查意见草稿：

```text
draftOpinion.result = 前端传入 result
draftOpinion.opinion = 前端传入 opinion 或 “采纳 AI 建议。”
auditLog = 采纳 AI 建议
```

它不会真正改变 AI run 的推理状态，也不会执行新的模型推理。

驳回接口：

```text
POST /projects/{project_id}/inspection/nodes/{node_id}/ai-suggestions/{suggestion_id}/reject
```

当前逻辑是写入 mutation result 和审计记录。

## 6. 推理日志与多模型对比

### 6.1 推理链路历史日志

接口：

```text
GET /reasoning/logs
GET /reasoning/logs/{log_id}
GET /reasoning/logs/{log_id}/evidence
```

这些接口本质上读取 `repo.state["ai_runs"]`。

也就是说，“推理链路历史日志”当前不是从 LangGraph trace 生成的，而是从 AI run 业务记录生成的。

### 6.2 多模型对比

接口：

```text
POST /llm/compare
GET /llm/compare-runs
GET /llm/compare-runs/{run_id}
```

Worker 实现：

```text
backend/apps/worker/tasks.py
llm_compare(...)
```

当前逻辑：

1. 读取 `llm_compare_runs`。
2. 遍历 `modelCodes`。
3. 每个模型调用一次 `LiteLLMClient().chat_sync(...)`。
4. 将回答写入 `run["results"]`。

这也是多次普通 LLM 调用，不是多 Agent 协作。

## 7. 当前实现的边界

当前 AI/agent 相关实现已经具备：

- 前端触发 AI 复核。
- 后端创建 AI run。
- 异步任务执行。
- LiteLLM 模型网关。
- OCR 字段进入 Prompt。
- AI 建议回写。
- EvidenceLink 展示。
- 人工采纳 / 驳回 / 保存审查意见。
- 推理日志列表。
- 多模型对比任务。

但还不具备：

- LangGraph 图编排。
- Agent 工具调用。
- 规则节点化执行。
- 条件路由。
- 人工中断与恢复。
- 可重放的 Graph State。
- 结构化输出校验。
- 真实 RAG 检索。
- 按规则版本动态加载核验子图。
- 每一步独立 EvidenceLink 绑定。
- 节点级耗时、Token、模型调用 trace。

## 8. 与 LangGraph 的改造关系

现有工程已经具备接入 LangGraph 的外围基础：

- `ai_runs` 可作为业务运行记录。
- `evidence_links` 可作为证据追溯对象。
- `extracted_fields` 可作为图输入。
- `rule_versions` 可作为规则版本来源。
- `Celery` 可作为异步执行入口。
- `LiteLLM` 可继续作为模型网关。
- 前端工作台和知识库页面可以继续复用。

最自然的改造点是：

```text
backend/apps/worker/tasks.py
ai_recheck(...)
```

建议将当前“一次 chat completion”替换为 LangGraph 图：

```text
load_context
-> collect_ocr_fields
-> retrieve_evidence
-> load_rule_template
-> check_authenticity
-> check_validity
-> check_scope
-> check_consistency
-> risk_router
-> human_interrupt / draft_suggestion / correction_required
-> persist_ai_run
```

这样可以保留现有 API 和前端数据结构，只增强 worker 内部执行方式。

## 9. 推荐的目标架构

推荐后续把 Agent 分为三层：

```text
前端工作台
  展示 AI 建议、核验步骤、证据链、人工采纳/驳回

业务 API
  创建 ai_run、校验权限、保存人工审查结果、提供推理日志

LangGraph worker
  执行规则图、调用 OCR/检索/LLM/外部核验工具、处理人工中断、回写 run state
```

LangGraph 图状态建议包含：

```json
{
  "projectId": "P-2026-HDCP-001",
  "nodeId": 24,
  "runId": "AIRUN-...",
  "inputDocumentVersionIds": [],
  "ocrFields": [],
  "retrievedEvidence": [],
  "ruleVersion": "Welder-Qualification-B-v2.1",
  "promptVersion": "24-焊工资格-v1.5",
  "fieldMappingVersion": "map-v1.3",
  "toolSourceVersion": "tool-v2.0",
  "stepResults": [],
  "riskItems": [],
  "manualConfirmItems": [],
  "suggestion": {},
  "auditEvents": []
}
```

## 10. 总体判断

当前工程已经完成了 AI 审查功能的产品外壳和后端任务骨架：

- 有页面。
- 有 API。
- 有 run 数据结构。
- 有异步任务。
- 有 LiteLLM 调用。
- 有审计和人工处理动作。

但是“agent”目前只是命名和产品语义，并没有形成真正的 Agent 架构。

如果项目目标是“AI 通过业务规则进行可追溯推理”，下一步应优先把 `ai_recheck` 从单次 LLM 调用改造为 LangGraph 业务规则图。这样现有页面中的“业务核验链路”才能从静态解释升级为真实执行链路。
