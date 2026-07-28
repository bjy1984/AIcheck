# Agent 实现概览

> 撰写日期：2026-07-26
> 分析范围：`backend/apps/api/routes.py`（Version B 对话 Agent）、`backend/libs/review_orchestrator/*`（正式 ReviewRun Agent）、`backend/libs/db/repository.py`、`frontend/src/views/AIReviewB/*`、`backend/tests/test_review_b_workspace.py`
> 所有结论均以实际代码与测试用例为依据；标注“无法确认”的内容，是本次分析环境中无法执行验证的项目。

---

## 一、项目目标与垂直 Agent 定位

本项目是一个**压力管道工程监督检验（监检）材料审查系统**。Agent 面向的业务场景是：监检人员按项目节点（如焊工资格 R12、境外牌号材料 R19，以及耐压试验参数等 R13–R34 节点）审查施工方提交的证书、报告和图纸，并依据固化的标准条款（TSG D7006-2020、NB/T 47013 等）给出“符合／不符合／证据不足”的判定。

与通用对话 Agent 的核心差异（在代码中的具体体现）：

| 垂直 Agent 要求 | 实现位置 |
| --- | --- |
| 基于专业规则与证据判断，不允许模型临时改选条款 | 条款包固化：`get_fixed_basis` 工具描述明示“模型不能临时改选条款”；`llmMaySelectClause=false`（`AI复核交互实现.md` §19） |
| 确定性工具结果优先于自然语言推断 | 系统提示：“固定条款、确定性工具结果优先于自然语言推断”；`check_*` 系列确定性工具（`llm_tool_schemas.py`） |
| 不替代人工作出最终结论 | 对话 Agent 全部工具只读；最终结论走 `POST /review-runs/{id}/human-decision`；系统提示“不得代替用户提交最终人工结论，也不得执行写操作” |
| 证据可追溯 | 引用强制写成 `[显示文本](basis:basisRefId)` / `[显示文本](evidence:evidenceLinkId)`；`review_message_source_references()` 附带引用解析表；前端 `ReviewMarkdownText.vue` 渲染为可点击证据卡 |
| 人工补充与复核 | R12/R19 使用 `request_r12/r19_human_input` 工具和 `HumanInputTask`；对话 Agent 不对 R12/R19 节点执行同步判定（`CONVERSATION_FORMAL_JUDGMENT_EXCLUDED_NODES = {12, 19}`） |
| 全程可审计 | `review_session_events` 事件流（promptHash/responseHash/durationMs）、`agent_executions` 执行记录、raw capture（`capture_agent_turn` / `capture_tool_request` / `capture_tool_result` → raw vault） |

---

## 二、目前 Agent 架构总览

项目内有**四代**Agent 实现并存：

1. **旧版一次性 LLM 复核**（已被取代，`项目agent实现.md` 记载）：`前端 → ai-recheck API → Celery worker → 拼接 Prompt → 单次 chat completion → 回写 ai_runs.suggestion`。无工具调用、无循环。
2. **正式 ReviewRun 编排**（`backend/libs/review_orchestrator/execution.py`，约 189KB）：基于规则图执行——fact builder（`r13_facts.py` … `r24_r34_facts.py`）组装业务事实 → `compile_node_tool_plan` 编译原子核查项工具计划 → `execute_node_tool_plan` 逐项执行确定性工具 → 固定聚合器生成节点结论。LLM 仅在既定边界内补充解释。
3. **R12 / R19 正式 Agent**（`r12_agent.py`、`r19_agent.py`）：真正的 tool-calling loop（R19 上限 `AICHECK_R19_AGENT_MAX_TURNS`=12 轮，temperature 0），支持通过 `request_*_human_input` 暂停并等待人工输入、通过 `submit_*_semantic_review` 提交带 EvidenceRef 校验的结构化结果，并产生 `agent.reasoning.delta` 推理流事件。
4. **Version B 对话式 Agent**（本文重点，`routes.py` 中 `review_conversation_llm_answer` 及周边）：服务 `/ai-review-b` 工作台（`ConversationalReviewWorkbenchB.vue`），自由文本问答 + 只读工具循环 + 确定性斜杠命令。

**重用关系**：Version B 通过 `run_node_formal_judgment` 工具**只读复用**第 2 代的 fact builder + tool plan + 原子项执行链（`review_conversation_formal_judgment()`，`advisoryOnly=True`，不建 ReviewRun、不写 findingDrafts）；工具目录（`runtime_tool_catalog()`）、模型网关（`qwen_runtime.py` → LiteLLM OpenAI 兼容接口）、证据就绪模型（`build_node_evidence_readiness`）四代共用。

**Version B 完整调用链**：

```
前端 ConversationalReviewWorkbenchB.vue
  → POST /api/review-sessions/{id}/messages（Idempotency-Key + If-Match）
    → create_review_session_message.produce()
      → recover_interrupted_agent_executions()        # 重启后将遗留的 running 记录收敛为终态
      → review_assistant_request_context()            # 请求线程内收集上下文快照（含可见性过滤）
      → review_conversation_slash_command()           # 斜杠精确匹配 → 确定性回答（同步返回）
      → acquire_review_session_execution()            # 会话级执行锁，占用失败回 409
      → 写入 user 消息、running 状态的 assistant 占位消息和 agent_executions 记录（实时入库）
      → threading.Thread → run_review_conversation_execution()
        → review_conversation_llm_answer()            # Agent Loop（见第三节）
          → qwen_runtime_client().chat_sync(tools=...) ⇄ review_conversation_agent_tool_output()
          → append_review_session_event()（每事件实时 persist）
        → review_agent_answer_blocks() → 回填 assistant 消息（重新编 sequence）
        → finalize_agent_execution_record() + 定向持久化
  ← 响应 status="accepted" + running 占位消息
前端 SSE /events/stream（或 400ms 轮询降级）→ 事件时间线 + applyStreamingDeltas() 渐进渲染
前端 waitForAssistantCompletion() 轮询全量消息快照 → 占位消息终态后刷新
```

---

## 三、Version B Agent Loop 实现分析

核心函数：`review_conversation_llm_answer(session, user_text, *, project, node, basis_items, evidence_links, review_run, readiness, basis, cancel_event, execution_id)`（`routes.py`）。

| 环节 | 实现 |
| --- | --- |
| 开始条件 | 非斜杠命令的自由文本，且 `AICHECK_REVIEW_CONVERSATION_LLM_EXECUTION` 不为 `deterministic/disabled/mock`（否则返回 `deterministic_fallback`，`failureReason=LLM_EXECUTION_DISABLED`） |
| 上下文构建 | 单一 user 消息内嵌 JSON：节点/项目、`fixedBasis`（≤12 条）、`nodeEvidence`（≤24）、`selectedEvidence`（≤12）、ReviewRun 摘要（findingDrafts ≤8）、`recentConversation`（近 6 条、各 1200 字）、`previousToolFindings`（会话工具记忆摘要 ≤12 条）、`question` |
| 最大轮数 | `AICHECK_REVIEW_CONVERSATION_AGENT_MAX_TURNS`，夹在 2–12，默认 8 |
| 每轮模型调用 | `chat_sync(model="review-chat", tools=REVIEW_CONVERSATION_AGENT_TOOLS(29 个), tool_choice="auto", temperature=0.1, max_tokens=1200, timeout=AICHECK_REVIEW_CONVERSATION_TIMEOUT_SECONDS(默认 60s))` |
| 取消检查 | 每轮模型调用前 + 每个工具执行前检查 `cancel_event.is_set()` → 抛 `ReviewConversationCancelled` |
| Token 预算 | `AICHECK_REVIEW_CONVERSATION_INPUT_TOKEN_BUDGET`（默认 24000，下限 4000）；估算器使用 `len(content)//2` 进行近似计算，**并非真实 tokenizer** |
| 上下文压缩 | 超预算时从最旧工具消息开始，内容替换为 `[工具结果已压缩] {tool}：{summary}`（`compactable_tool_messages` 队列）；发 `agent.context.compacted` 事件 |
| 强制最终轮 | 两个触发：轮数达上限（消息含“轮次上限”）或压缩后仍超预算（`agent.budget.exhausted` 事件）；此时 `tool_choice="none"` 并注入“立即输出最终结论”指令 |
| 重复调用防护 | `executed_tool_cache`（signature = `hash({tool, arguments})`）；命中直接回缓存 + 提示“请勿再重复调用”；会话记忆种子命中另附 `fromSessionMemory` 提示 |
| 工具输出压缩 | `compact_llm_payload`（字符串 ≤600、列表 ≤40 项）+ 每条 tool 消息 ≤6000 字（`review_conversation_tool_message_content`） |
| 增量流式输出 | 每轮模型返回后发送 `agent.reasoning.delta`（供应商实际返回的 `reasoning_content`/`reasoning`）与 `agent.message.delta`（正文，各截取 2000 字）事件，payload 携带 executionId |
| 正常终止 | 模型不再请求工具且内容非空 → 返回 `mode=llm_agent`、text ≤4000 字、累计 usage |
| 取消终止 | `ReviewConversationCancelled` → `mode=cancelled`、`failureReason=USER_CANCELLED`、附已完成工具轨迹（`tool_trace` 末 12 条）、事件 `agent.execution.cancelled` |
| 失败降级 | 任何其他异常（包括模型超时、空输出 `LLM_OUTPUT_EMPTY`、**任一工具异常**）→ `mode=deterministic_fallback` + 已获得的部分工具结果，事件 `agent.model_call.failed` |
| 消息写回 | `run_review_conversation_execution()`：回填占位消息（`status` completed/cancelled/failed）、**重新分配 sequence**（保证 `sequence > after` 增量拉取可见）、bump session revision、`agent.message.completed/failed` 事件、`finalize_agent_execution_record()`、定向持久化 |

**注意（如实说明）**：工具异常目前仍会终止整个 Loop（进入 fallback），尚未实现单工具错误隔离；`AGENT_MAX_TURNS_EXCEEDED` 的 raise 是不可达的死代码（最终轮必然 return 或抛出 `LLM_OUTPUT_EMPTY`）。

---

## 四、核心模块与关键代码

| 模块 | 文件 | 关键函数／类 | 输入 → 输出 | 目前限制 |
| --- | --- | --- | --- | --- |
| 对话入口 | `backend/apps/api/routes.py` | `create_review_session_message`（POST `/review-sessions/{id}/messages`） | content（≤4000 字）→ accepted/completed + user/assistant 消息 | 同步分支与 Agent 分支同函数，函数偏长 |
| Session / Message | 同上 | `create_node_review_session`、`review_session_view`、`next_review_session_sequence`、`review_message_view`；数据模型 `review_sessions` / `review_messages`（`STATE_COLLECTIONS`） | — | sequence 的生成并非原子操作（依靠会话锁串行执行 Agent 分支） |
| Agent 执行 | 同上 | `review_conversation_llm_answer`、`run_review_conversation_execution`、`review_agent_answer_blocks` | 上下文快照 → contentBlocks + execution | 执行于 daemon thread（见第五节任务 10） |
| Tool Registry | `backend/libs/review_orchestrator/llm_tool_schemas.py` | `CONVERSATION_AGENT_RUNTIME_TOOL_NAMES`（20）、`EXTERNAL_REGISTRY_LLM_TOOLS`（4）、`build_review_conversation_agent_tools` | 名称 → OpenAI function schema | schema 部分为宽松对象（`additionalProperties` 混用） |
| Tool Dispatcher | `routes.py` + `runtime_tools.py` | `review_conversation_agent_tool_output`（5 个 context 工具内联 + `dispatch_runtime_tool` 转发）、`review_conversation_formal_judgment` | (tool, args, context) → dict | 例外不隔离；文档范围守卫 `DOCUMENT_SCOPED_CONVERSATION_TOOLS` + `REVIEW_AGENT_DOCUMENT_SCOPE_VIOLATION` |
| Context Builder | `routes.py` | `review_assistant_request_context`（在请求线程内完成可见性过滤，供后台线程使用） | request+session → 纯数据快照 | 截断时没有标记（证据 >24 条时模型无法获知） |
| Memory | `routes.py` | `load/store_review_session_tool_memory`、`review_session_tool_memory_revision`；`REVIEW_SESSION_TOOL_MEMORY_LIMIT`=40 | signature → 压缩输出 | 进程内、不持久化（重启即失；多 worker 各自为政） |
| SSE Event | `routes.py` | `append_review_session_event`（实时 `persist_review_session_records`）、`review_session_event_snapshot`（合并 session 事件与 ReviewRun 事件重排）、`stream_review_session_events`（SSE + to_thread live-read） | — | 快照每 tick 全量重排 O(n)；共享依赖 Postgres 轮询（0.5s），非 pub/sub |
| Background Execution | `routes.py` | `threading.Thread(daemon=True)` + `review_conversation_execution_mode()`（`background`/`inline`） | — | 非工作流；重启即中断（由 recovery 收敛） |
| Cancellation | `routes.py` | action `cancel_execution` → `cancelEvent.set()`；Loop 内两处检查点 | — | 无法中断进行中的模型 HTTP 请求（最长等一个 timeout=60s） |
| Lock | `routes.py` | `acquire/release_review_session_execution`、`REVIEW_SESSION_ACTIVE_EXECUTIONS` + `threading.Lock`；陈旧回收 `AICHECK_REVIEW_CONVERSATION_EXECUTION_STALE_SECONDS`=900 | — | **进程内锁**，跨 worker 无效（见任务 4） |
| Retry | — | 无 | — | 模型调用零重试；一次超时即降级 |
| 执行记录 | `routes.py` + `repository.py` | `record_agent_execution_started`、`finalize_agent_execution_record`、`recover_interrupted_agent_executions`；GET `/review-sessions/{id}/agent-executions`；collection `agent_executions`（schema `ReviewAgentExecution@1`） | — | recovery 假设单 worker（见任务 4 风险） |
| Testing | `backend/tests/test_review_b_workspace.py` | 24 个测试（含 9 个本轮新增：async 受理、409 忙锁、取消、精确匹配、记忆复用、预算收束、执行记录、增量事件等）；autouse fixture 将既有用例固定在 `inline` 模式 | — | **尚未在完整环境实际执行**（沙箱缺依赖） |
| 前端 | `ConversationalReviewWorkbenchB.vue`、`api/aiReviewB/index.ts`、`types/ai-review-b.ts` | `sendMessage`、`waitForAssistantCompletion`（全量快照轮询 800ms）、`applyStreamingDeltas`、`stopCurrentAnswer`（停止回答按钮）、SSE `streamReviewBEventsApi`（fetch+ReadableStream，失败降级 400ms 轮询） | — | 增量渲染靠事件轮询/SSE，粒度为“每轮”而非token 级 |

---

## 五、待办任务完成度检查表

> 判断依据：实际代码和测试用例。“已完成”并不表示没有限制，具体限制在“缺失内容”栏中说明。

| # | 任务 | 状态 | 完成依据 | 缺失内容 | 风险 | 建议下一步 | 优先级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 执行完整 pytest 并修复问题 | **尚未完成／无法确认** | 24 个测试已就绪且通过语法/AST 检查；但云端沙箱缺少完整的后端依赖，未实际执行 | 实际执行结果未知；两轮改动（async、记忆、预算）未经测试验证 | 可能存在未发现的回归 | 本机执行 `pytest backend/tests/test_review_b_workspace.py -x`，若失败则修复，再运行全部测试 | **P0** |
| 2 | 斜杠命令精确前缀匹配 | **已完成** | `REVIEW_CONVERSATION_SLASH_COMMANDS` + `review_conversation_slash_command()`（`stripped.startswith("/")` + 首词查表）；测试 `test_review_b_natural_language_with_command_words_goes_to_agent` | 无模糊提示（打错命令会直接进 Agent，成本较高） | 低 | 可选：未知 `/xx` 前缀时回“未知命令”提示 | 已闭环 |
| 3 | 单工具错误隔离 + 模型有限重试 | **尚未完成** | `review_conversation_agent_tool_output` 的异常仍会向上抛出，并由 Loop 顶层 `except Exception` 触发整体降级（`routes.py` 工具执行区块）；`chat_sync` 没有重试包装 | 工具级 try/except 返回结构化错误；区分可重试错误（timeout/5xx）与不可重试错误（4xx）；执行 1–2 次退避重试 | 一个工具的小故障会导致整轮回答失败；瞬时网络抖动会直接触发降级 | 在工具执行层用 try/except 返回 `{"status":"failed","errorCode":...}`，作为 tool 消息反馈给模型；模型调用增加 1 次退避重试 | **P0** |
| 4 | 执行锁升级为 Redis／数据库锁 | **尚未完成**（现为过渡方案） | 现状：`REVIEW_SESSION_ACTIVE_EXECUTIONS`（进程内 dict + `threading.Lock`）+ 陈旧回收 | 跨进程互斥；**已知风险**：多 worker 下 `recover_interrupted_agent_executions` 会把另一 worker 正在执行的 running 记录误判为中断（本地无执行槽即收敛），造成双重执行与消息覆盖 | **多 worker 部署下锁形同虚设**；单 worker 下无问题 | 以 `agent_executions` 表做 DB 乐观锁（status=running 唯一约束 / `SELECT ... FOR UPDATE`）+ 心跳字段；recovery 改为“心跳超时”判定 | **P1**（多 worker 前必做） |
| 5 | 持久化 `agent_executions` | **已完成** | collection 注册（`repository.py` `STATE_COLLECTIONS` + 3 处 setdefault）；`record_agent_execution_started` / `finalize_agent_execution_record` / `recover_interrupted_agent_executions`；路由 `GET /review-sessions/{id}/agent-executions`；事件 `agent.execution.interrupted`；测试 `test_review_b_agent_executions_recorded_and_queryable` | 无心跳字段；recovery 单 worker 假设（同任务 4） | 中（与任务 4 耦合） | 加 `heartbeatAt`；供任务 4 做 DB 锁载体 | 已闭环（基础版） |
| 6 | 会话级工具结果记忆 | **已完成**（进程内缓存） | `review_session_tool_memory`（signature + `toolMemoryRevision` 失效键，上下文动作递增）；种子入 `executed_tool_cache`、`fromSessionMemory` 提示、`previousToolFindings` 注入上下文与系统提示；`AICHECK_REVIEW_CONVERSATION_TOOL_MEMORY_LIMIT`=40；排除 `run_node_formal_judgment`；测试 `test_review_b_session_tool_memory_reuses_results_across_messages` | 不持久化（设计取舍：缓存而非状态）；多 worker 各进程独立；无 TTL | 低（记忆失效只损效率不损正确性） | 若迁 Celery，改存 Redis 并带 TTL | 已闭环（基础版） |
| 7 | Token 预算、上下文淘汰与压缩 | **部分完成** | 预算 `AICHECK_REVIEW_CONVERSATION_INPUT_TOKEN_BUDGET`；压缩 `compactable_tool_messages` → `[工具结果已压缩]` 摘要；耗尽强制收束；事件 `agent.context.compacted` / `agent.budget.exhausted`；测试 `test_review_b_token_budget_forces_early_final_answer` | 估算器为 `chars//2` 而非真实 tokenizer；**已收集的 usage（`normalize_model_usage` 累计）未反馈到预算判断**；对话历史（recentConversation）无 LLM 摘要压缩；初始上下文截断（24/12/8 条）无截断标记 | 估算偏差可能过早/过晚收束 | 用上一轮 usage.inputTokens 校准估算；截断处加计数提示 | P2 |
| 8 | SSE 事件迁移至共享持久化存储 | **部分完成** | 写入侧：`append_review_session_event` 每事件实时 `persist_review_session_records()`（`flush_mutation_records` 定向落 Postgres `aicheck_state`）；消息/会话/执行记录同样定向落库；读取侧：`/messages`、`/events`、`/events/stream`、`/agent-executions` 均先 `refresh_state_from_postgres_for_live_read()`（SSE 内 `asyncio.to_thread`、0.5s）；背景线程已移除整体 `flush_state()`（避免快照覆盖） | 本质是“DB 轮询桥接”而非 LISTEN/NOTIFY 或消息队列；无 Postgres（sqlite/纯内存）模式下仍是单进程内存；事件快照每 tick 全量重排 | 每 SSE 客户端 0.5s 一次 DB 读，客户端多时 DB 压力上升 | Postgres LISTEN/NOTIFY 或 Redis pub/sub 推送；快照改增量游标 | P2 |
| 9 | 回答内容增量流式输出 | **部分完成** | 事件 `agent.message.delta` / `agent.reasoning.delta`（每轮模型返回后发出，payload 含 executionId/turn/content；executionId 已与执行记录统一）；前端 `applyStreamingDeltas()` 将增量内容渲染到 running 占位消息中；测试 `test_review_b_content_delta_events_are_emitted` | 粒度为“每轮”，而非 token 级：`qwen_runtime.py` 通过 httpx 发起单次 JSON POST（`post_json_with_raw_capture`），**不支持 stream=True** | 长回答仍需等待整轮生成完成后才能显示 | 为 `QwenRuntimeClient` 增加 SSE 流式模式，Loop 接收数据的同时持续发送 delta | P2 |
| 10 | 迁移至 Celery／Temporal | **尚未完成**（现为过渡方案） | 现状：`threading.Thread(daemon=True)`（`run_review_conversation_execution`）+ `inline` 兼容模式；Celery 基建存在（`task_dispatcher.py`、`celery_app.py`，正式 ReviewRun 已走 Celery）但对话 Agent 未接入 | 对话 Agent 的 ~15 个辅助函数全在 `routes.py`（API 层），worker 程序无法 import 使用；无检查点、无跨重启续跑 | 部署重启丢执行（仅能事后收敛为 interrupted）；API 程序承担模型长调用的线程占用 | 先抽 `libs/review_conversation/`（context builder / loop / persistence），再接 `task_dispatcher.dispatch_review_conversation()`；Temporal 留给含人工节点的长工作流 | **P1** |

---

## 六、与 Claude Code、Codex 的类比分析

从 Agent 工程（而非模型能力）角度对比：

| 能力维度 | Claude Code / Codex 的做法 | 本项目现状 | 差距 |
| --- | --- | --- | --- |
| 任务规划与动态重规划 | 显式 plan/todo 工具，执行中改写计划 | 系统提示内嵌固定“轮次纪律”（整体核查→`run_node_formal_judgment`；单项→`assemble_node_judgment_facts`+`check_*`），无计划对象 | 中：垂直场景由规则图代偿了大部分规划，但自由问答无计划可展示（设计稿的 `agent.plan.created` 未实现） |
| 工具调用循环 | 多轮、并行工具、错误后改道 | 多轮串行；重复去重完善；**错误即全损**（任务 3） | 大：无并行、无错误后替代策略 |
| 任务状态持久化 | 会话/检查点可恢复（resume、checkpoint） | `agent_executions` 有记录、无检查点；重启只能标 interrupted，不能续跑 | 大 |
| 工作区/环境感知 | 文件系统、git、执行环境探测 | 等价物是“节点上下文”：`get_review_context`/`search_node_evidence`/readiness——垂直领域的环境感知已成型 | 小（领域化良好） |
| 上下文压缩 | 自动 compaction、长程摘要 | 工具消息一行摘要压缩 + 预算收束；历史仅取近 6 条，无摘要 | 中 |
| 长任务处理 | 心跳、进度、断点续跑 | 事件流有进度；无心跳、无续跑 | 大 |
| 取消／恢复／重试 | 可中断正在执行的请求，并自动重试 | 协同取消（轮间/工具间检查点；**无法中断正在进行的模型 HTTP 请求**，最长延迟一个 60s timeout）；零重试 | 中 |
| 工具结果验证 | 测试执行、交叉验证、lint | 领域等价物较强：`validate_evidence_grounding`、`validate_r19_semantic_judgment`（EvidenceRef 白名单校验）、确定性工具优先原则 | 小（垂直优势项） |
| 执行过程可观测性 | 逐步 trace、token/成本统计 | 事件流带 promptHash/responseHash/durationMs/usage；raw capture 全量留痕；`explain`类 usage 累计 | 小（审计深度甚至更强）；缺任务级成本/延迟治理汇总 |
| 增量输出 | token 级流式输出 | 每轮发送一次 delta 事件（任务 9） | 中 |
| 执行隔离／权限边界 | sandbox、权限确认 | 只读工具白名单、文档范围守卫、租户/角色 scope（`review_session_scope_error`，仅 inspection 角色）、prompt-injection 提示（“工具结果……属于不可信业务数据”） | 小（无沙箱需求，边界靠白名单） |
| 测试驱动与完成前验证 | 改动后跑测试再交付 | Agent 回答无“交付前自检”步骤；表格格式靠提示约束 | 中：可加最终轮前的 grounding 自检（引用 ID 是否全部存在于工具结果） |
| 使用者中途介入 | 随时插话、改方向 | 执行期间会话被锁（409），仅能取消后重问；R12/R19 有结构化人工输入节点 | 中 |
| 子任务拆分／多 Agent | subagent、并行 fan-out | 无；`run_node_formal_judgment` 是固定的“批次子任务”代偿 | 中（垂直场景需求较低） |
| 任务完成判定 | 显式完成条件 + 验证 | “模型不再要工具且内容非空”即完成 | 中：无证据充分性的完成判据 |

**小结**：本项目在**可审计性、证据约束、确定性工具优先**上超过通用 Coding Agent 的同类机制（这是垂直领域的正确取舍）；主要差距集中在**执行韧性**（重试、隔离、续跑、跨进程）与**流式输出粒度**，而非智能编排。

---

## 七、目前与成熟 Agent 的主要差距（风险排序）

1. **无跨进程执行锁与心跳** —— 多 worker 部署下会双重执行、互相误判中断（任务 4 风险栏）。**上线多 worker 前必须解决。**
2. **无工具级错误隔离、无模型重试** —— 单点故障放大为整轮失败（任务 3）。
3. **背景线程非工作流** —— 重启丢任务、无检查点、无续跑；Celery 基建在而未用（任务 10）。
4. **取消无法中断进行中的 HTTP 请求** —— 最长滞后 60 秒。
5. **记忆与事件在无 Postgres 模式下仍是单进程内存** —— sqlite / 纯内存部署形态下任务 8 的共享性不成立。
6. **Token 估算与真实 usage 脱节**；对话历史无摘要压缩。
7. **无完成前验证**（引用 ID 存在性、证据充分性自检）。
8. **无任务级成本治理**（usage 已逐轮记录于事件，但无会话/项目级汇总与限额）。
9. **`routes.py` 巨石化**（>1.3MB，对话 Agent ~15 个函数内嵌 API 层），阻碍任务 10 与单元测试。
10. **测试未实际执行**（任务 1）——以上所有“已完成”在拿到绿色测试前都应视为待验证。

---

## 八、改进路线图

### 第一阶段：稳定性与正确性（P0，天级）
- 本机执行 `pytest backend/tests/test_review_b_workspace.py -x`，再运行全部测试；修复失败用例。验收标准：CI 通过。
- 工具执行包 try/except，结构化错误作为 tool 消息反馈模型（不再整轮降级）。验证：新增“单工具抛例外仍产出最终回答”测试。
- `chat_sync` 包一层有限重试（timeout/5xx 重试 1 次、退避；4xx 不重试），`failureReason` 区分 `MODEL_TIMEOUT`/`MODEL_HTTP_4XX`/`MODEL_HTTP_5XX`。验证：mock 首次超时、二次成功的测试。
- 移除 `AGENT_MAX_TURNS_EXCEEDED` 死代码。

### 第二阶段：执行状态持久化（P1）
- `agent_executions` 加 `heartbeatAt`（Loop 每轮更新）；以 DB 唯一 running 约束或 `FOR UPDATE` 实现跨进程会话锁，取代进程内 dict；recovery 改“心跳超时”判定（修复多 worker 误收敛风险）。
- 取消改为“DB 标记 + 内存 Event”双通道，跨 worker 可取消。
- 页面重新整理后：前端以 `GET /agent-executions` + running 占位消息恢复等待状态（后端已支持，前端补 on-mount 逻辑）。
- 验证：双进程集成测试（参考 `test_repository_postgres_concurrency.py` 的风格）。

### 第三阶段：上下文与记忆（P2）
- 用上轮 `usage.inputTokens` 校准估算器；截断处加“共 N 条，已截断”标记。
- 记忆迁 Redis（带 TTL），与 Celery 化配套；`toolMemoryRevision` 失效机制保留。
- 对话历史超过 N 条时做一次 LLM 摘要（存 session，增量维护）。

### 第四阶段：事件流与实时互动（P2）
- Postgres LISTEN/NOTIFY（或 Redis pub/sub）替代 0.5s 轮询；SSE 断线重连带 `after` 游标补发（后端 `sent_event_ids` 机制已可支撑）。
- 为 qwen client 增加 `stream=True` SSE 解析，Loop 边接收边发送 token 级 `agent.message.delta`；前端渲染逻辑（`applyStreamingDeltas`）无需大幅修改。

### 第五阶段：正式工作流化（P1 后段）
- 抽 `backend/libs/review_conversation/`（context builder、loop、tool output、persistence），`routes.py` 只留路由与权限。
- 接 `task_dispatcher.dispatch_review_conversation(session_id, message_id)` 走 Celery（`inline` 模式保留给测试）；含人工输入节点的长流程评估 Temporal（设计稿 §21.8 既定方向）。
- 检查点：每轮结束把 messages 状态摘要写入 `agent_executions`，重启后可从最近检查点续跑。

### 第六阶段：对标 Claude Code／Codex（P3）
- `agent.plan.created`：执行前产出可展示计划（设计稿已定义事件名）。
- 完成前验证轮：输出前检查引用 ID 均存在于工具结果、必答项齐全，不合格自动补一轮。
- 工具失败后替代路径表（如 OCR 失败 → 改走 `locate_evidence_fragment`）。
- 建立 Agent 评测集：以 raw capture 的真实轨迹回放为回归基准（`test_raw_vault_agent_capture.py` 已有雏形）。
- 会话级成本/延迟汇总与限额（usage 事件已齐，补聚合端点）。

---

## 附：十个问题的直接回答

1. **垂直 Agent 如何实现？** “固化条款包 + 只读工具白名单 + 确定性判定工具 + tool-calling loop + 事件审计”五件套；判定权留给人工（第一、三、四节）。
2. **各版本演进关系？** 一次性 LLM 复核 → 规则图编排 → R12/R19 带人工节点的正式 Agent → Version B 对话 Agent（只读复用前代判定链）（第二节）。
3. **Version B Loop 如何运行？** 见第三节表格：最多 8 轮、预算收束、去重缓存、取消检查点、每轮 delta、部分结果降级，以及重新编排 sequence 后写回。
4. **已完成？** 任务 2、5、6（及任务 4/10 的过渡形态：进程内锁、背景线程、取消、409 忙锁）。
5. **过渡实现？** 进程内锁（不支持多 worker）、背景线程（未 Celery 化）、取消（无法中断进行中 HTTP）、DB 轮询式事件共享（非 pub/sub）、字符估算的预算（usage 未反馈）、每轮粒度的 delta（非token 级）。
6. **尚未完成？** 任务 1、3、4、10；以及计划对象、完成前验证、检查点续跑。
7. **影响正式部署／多 worker 的问题？** 第七节 1–3、5：跨进程锁缺失（含 recovery 误判双执行风险）、无续跑、无 Postgres 模式的共享性缺口。
8. **相比 Claude Code/Codex 缺什么？** 执行韧性（隔离/重试/续跑/心跳）、token 级流式输出、计划与完成前验证、子任务拆分；审计与证据约束反而领先（第六节）。
9. **下一步先做什么？** 第一阶段 P0：跑 pytest → 工具隔离 → 模型重试（一天内可完成的三件事）。
10. **如何验证改进有效？** 每项改进都应配套测试，具体见第八节各阶段的验证说明；统一以 `pytest backend/tests/test_review_b_workspace.py` 为回归门槛，多 worker 相关改进还需补充双进程集成测试。
