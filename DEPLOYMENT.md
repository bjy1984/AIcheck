# AIcheck 部署文档

本文档面向单机 Docker Compose 部署和小规模生产部署。当前仓库包含：

- `api-service`：FastAPI 主业务 API，对前端暴露 `/api/*`，并兼容 `/mock/*` 登录联调路径。
- `worker-service`：Celery worker，处理 OCR、知识切片、向量化、AI 复核、模型对比和导出任务。
- `review-worker-service`：Temporal worker，执行 ReviewRun 外层 Workflow，并调用 LangGraph 兼容审查图。
- `ocr-service`：内部 OCR 服务，提供 `/healthz` 和 `/internal/ocr/parse`。
- `litellm-service`：LiteLLM Proxy，提供 OpenAI-compatible 模型网关。
- `temporal-service`、`temporal-ui`：审查编排与任务可视化。
- `postgres`、`redis`、`minio`：统一 PostgreSQL 数据库、任务队列/缓存、对象存储。

## 0. 稳定上线门禁

除 **OCR 100+ 人工标注样本准确率评估报告** 可作为延期项外，其它生产门禁必须全部通过。上线前不要使用当前本地开发进程作为验收依据，必须以 Docker Compose 生产拓扑和 live probe 报告为准。

必须满足：

- API `/healthz`：`authRequired=true`、`demoUsersEnabled=false`、`postgresEnabled=true`、`postgresTransactions=true`、`objectStorageEnabled=true`。
- 生产模式禁止 `mock://` 上传、预览、下载、导出 URL。MinIO 未配置或 signed URL 生成失败时返回 `OBJECT_STORAGE_REQUIRED`，不得静默回退到 mock。
- OCR 服务必须运行最新 `document-intelligence-service` 入口，并暴露 `/healthz`、`/readyz`、`/internal/ocr/doctor`、`/internal/ocr/parse`、`/internal/document-parse/jobs`。允许延期的是 100+ 样本准确率报告，不允许使用 placeholder OCR。
- LiteLLM 必须通过健康检查、模型别名检查、virtual key 管理探针和最小 provider 调用。
- ReviewRun 必须通过真实 worker/Temporal/LangGraph 编排探针，FDE replay 必须生成 child run，不覆盖原始 run。
- FDE、admin、inspection、contractor、ndt、owner 六类角色必须登录到自己的默认面板，FDE 不能调用正式业务审批命令。

上线验收命令：

```bash
cd backend

python scripts/check_96_preflight.py --strict-production --require-ports-free
python scripts/ocr_runtime_doctor.py --strict-production
python scripts/validate_business_packs.py --json

python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --write-probes \
  --ocr-object-probe \
  --review-run-probe \
  --review-run-wait-seconds 30 \
  --litellm-management-probes \
  --litellm-provider-probes \
  --roles admin,inspection,contractor,ndt,owner,fde \
  --output-dir ./deployment-reports/latest

python -m pytest -q

cd ../frontend
npm run ts:check
npm run lint:style:check
npm run test:e2e -- --grep "aicheck|fde"
```

当前允许延期项只包括：

```text
OCR 100+ 人工标注样本准确率评估报告
```

延期项不豁免 OCR 运行态。`ocr_runtime_doctor.py --strict-production` 仍必须无 fail，`--ocr-object-probe` 仍必须证明 OCR 服务能读取 MinIO 对象并返回结构化失败或成功结果。

## 1. 项目架构

AIcheck 采用前后端分离、主业务 API 与异步能力服务拆分的架构。浏览器只访问前端站点、`api-service` 和 MinIO signed URL；OCR、LiteLLM、PostgreSQL、Redis 均应部署在内网。

### 1.1 仓库结构

```text
AIcheck/
├── frontend/                  # Vue 3 + Vite 前端应用
│   └── src/
│       ├── api/aicheck/       # 前端业务 API client，后端合同以此为准
│       ├── api/login/         # 登录与动态路由 API client
│       ├── utils/roleAccess.ts
│       └── views/AICheck/     # 工程角色工作台、通用审查工作台、管理后台页面
├── backend/
│   ├── apps/api/              # FastAPI 主业务 API
│   │   └── adapters/          # 行业兼容 adapter，例如工程监检旧接口默认值
│   ├── apps/worker/           # Celery worker 与异步任务入口
│   ├── apps/ocr_service/      # 内部 OCR HTTP 服务
│   ├── business_packs/        # 可插拔业务包：角色、节点、资料、规则、报告、AI SOP
│   ├── libs/contracts/        # 统一响应、错误码、分页合同
│   ├── libs/db/               # PostgreSQL 适配、索引、seed、仓储层
│   ├── libs/integrations/     # MinIO、OCR、LiteLLM、任务投递客户端
│   ├── libs/security/         # JWT、角色、ActionCode、权限推断
│   ├── scripts/               # 角色创建、部署验收、前后端合同审计
│   ├── config/litellm.yaml    # LiteLLM 模型别名配置
│   ├── Dockerfile             # API/worker 通用后端镜像
│   ├── Dockerfile.ocr         # OCR 专用镜像，安装 PaddleOCR 基线依赖
│   ├── requirements-ocr.txt   # agentdesign OCR 依赖基线
│   └── docker-compose.yml     # 后端服务与依赖编排
└── DEPLOYMENT.md              # 本部署与架构文档
```

### 1.2 服务拓扑

```text
Browser
  │
  ├── 静态资源：frontend/dist-pro
  ├── /api/*、/mock/* ───────────────▶ api-service (FastAPI)
  │                                      │
  │                                      ├── PostgreSQL：业务数据、审计、任务状态
  │                                      ├── Redis：Celery broker/result backend
  │                                      ├── MinIO：signed PUT/GET、预览、导出包
  │                                      └── LiteLLM：少量同步模型能力探测
  │
  └── signed PUT/GET ─────────────────▶ MinIO

worker-service (Celery)
  ├── Redis 队列：ocr.parse_document、knowledge.slice、knowledge.embed、
  │              inspection.ai_recheck（legacy）、llm.compare、export.package
  ├── 调用 ocr-service 完成 PDF/图片 OCR、印章识别和结构化字段抽取
  ├── 调用 litellm-service 完成 chat、embedding、模型对比
  └── 回写 PostgreSQL 与 MinIO 导出产物

review-worker-service (Temporal + LangGraph)
  ├── Temporal Workflow：ReviewRunWorkflow，负责长流程、重试、等待人工确认和取消信号
  ├── LangGraph 兼容 Graph：load_context → OCR → 规则 → 知识检索 → LiteLLM → 校验 → 草稿持久化
  ├── PostgreSQL：保存业务 ReviewRun 元数据、Temporal 状态库与 LangGraph checkpoint
  └── temporal-ui：工作流调试和任务可视化入口

ocr-service
  └── 导入 agentdesign 的 seal_ocr/parsing pipeline，失败时按配置生成可重试失败任务

litellm-service
  ├── 对 api/worker 暴露 OpenAI-compatible API
  └── 使用统一 PostgreSQL 中的 `litellm` 数据库保存模型配置、virtual key、预算和调用日志
```

### 1.3 业务模块边界

| 模块 | 前端入口 | 后端职责 | 主要数据 |
| --- | --- | --- | --- |
| 登录与角色 | `/login`、动态路由 | `/api/auth/login`、JWT、默认面板、路由与动作权限 | `users`、`roles`、`project_members` |
| 工作台 | `/workbench/{role}` | 项目列表、项目上下文、摘要、项目树、节点包 | `projects`、`project_nodes`、`todos`、`messages` |
| 通用资料审查 | `/workbench/generic` | 非工程业务包的节点、资料要求、AI 发现和人工确认入口 | `project_nodes`、`review_findings`、`ai_runs` |
| 文件与节点资料 | 工作台文件区 | 上传会话、MinIO signed URL、版本、挂载、撤回、作废 | `documents`、`document_versions`、`node_bindings` |
| 提交与补正 | 施工方/监检工作台 | 批次提交、撤回、补正反馈、状态机校验 | `submissions`、`rectifications`、`audit_logs` |
| 监检审查 | 监检工作台 | AI 复核、人工意见、证据链、报告草稿 | `ai_runs`、`evidence_links`、`reports` |
| NDT | `/workbench/ndt` | 底片、检测记录、检测报告、NDT 补正 | `ndt_films`、`ndt_records`、`ndt_reports`、`ndt_feedback` |
| 报告与归档 | 监检/建设方工作台 | 报告复核、导出、归档、证据包 | `reports`、`archive_items`、`export_tasks` |
| 知识库 | `/knowledge/*` | 文件列表、任务中心、知识源、条款库、PageIndex 树节点、规则、Query Router、精确条款/Hybrid RAG/PageIndex 条件检索测试 | `knowledge_sources`、`knowledge_files`、`knowledge_tasks`、`knowledge_chunks`、`knowledge_clauses`、`knowledge_page_index_nodes`、`retrieval_traces` |
| FDE 后台 | `/fde/*` | AI 绩效、AI Run/ReviewRun 追踪、Temporal/LangGraph 编排可视化、原文授权、脱敏策略、审计事件、反馈归因、评估样本池、评估报告、Capability Bundle diff、发布门禁和影响面、业务包安装/升级/回滚、业务包 diff、OCR 质量、事故 RCA、成本预算变更、交付验收 | `ai_runs`、`review_runs`、`review_graph_nodes`、`review_events`、`ai_trace_steps`、`access_grants`、`data_exports`、`masking_policies`、`ai_feedback`、`feedback_triage`、`evaluation_cases`、`evaluation_reports`、`capability_bundles`、`release_plans`、`business_pack_installations`、`cost_budgets`、`cost_budget_change_requests`、`incidents`、`incident_rca` |
| 管理后台 | `/admin/*` | 项目、单位、用户、权限、配置发布、审计 | `admin_configs`、`audit_logs` |

知识检索测试页会展示 Query Router 选路、`RetrievalTrace.pageIndexTree`、PageIndex 命中节点、关联条款和树搜索路径；部署验收时应使用跨章节/附录类问题确认页面走 `pageindex_tree_search` 且不会把 PageIndex 结果写入正式审查结论。

### 1.4 业务包开发与部署

AIcheck 现在按“通用资料审查内核 + 业务包”组织可复用业务。业务包放在 `backend/business_packs/{pack_id}/`，每个包至少包含：

- `manifest.yaml`：`id`、`name`、`version`、`domainType`、发布状态。
- `roles.yaml`：业务角色、平台角色映射、默认入口、动作权限。
- `nodes.yaml`：节点模板、资料要求、默认状态。
- `materials.yaml`：资料类型、必填字段、OCR 字段映射、证据要求。
- `workflow.yaml`：状态、动作、允许角色和目标状态。
- `rules.yaml`：规则版本、适用节点、严重级别、输出 schema。
- `reports.yaml`：报告模板、章节和导出类型。
- `agents.yaml`：AI 员工 SOP、工具权限和人工确认边界。
- `fixtures.yaml`：可选但推荐，声明跨行业 smoke 用的示例项目、文档、绑定、证据、项目成员授权和 AI 发现。

内置业务包：

- `engineering_inspection_v1`：工程监检业务包，当前默认包，生成 69 个工程监检节点。
- `compliance_audit_v1`：合规审计样例包，用于验证跨业务复用，生成 8 个审计节点。
- `device_inspection_v1`：设备年检样例包，用于验证设备资料核验迁移，生成 6 个年检节点。

管理后台入口：

- `/admin/business-packs`：查看业务包版本、快照 hash、角色/节点/资料/规则/Agent/fixtures 数量，并触发全量业务包校验。
- `/admin/projects`：项目立项向导支持选择 `businessPackId`；工程包进入原工程监检工作台，非工程包可进入 `/workbench/generic` 通用资料审查工作台。

部署或新增业务包后，应运行：

```bash
cd backend
python scripts/validate_business_packs.py --json
python -m pytest tests/test_business_pack.py -q
python -m pytest -q
```

复制一个新业务包骨架：

```bash
cd backend
python scripts/create_business_pack.py \
  --id device_audit_v1 \
  --template compliance_audit_v1 \
  --dry-run
```

运行后可用 API 验证：

```bash
curl http://127.0.0.1:8000/api/business-packs
curl -X POST http://127.0.0.1:8000/api/business-packs/validate-all
curl -X POST http://127.0.0.1:8000/api/business-packs/engineering_inspection_v1/validate
curl http://127.0.0.1:8000/api/business-packs/engineering_inspection_v1/snapshot
```

`POST /api/business-packs/validate-all` 和 `POST /api/fde/business-packs/validate-all` 会返回同一份 `scorecard`。它按 100 分制拆成四段：`catalog` 覆盖多业务域和快照，`core-boundary` 扫描平台核心层行业硬编码，`fixtures` 检查项目/资料/绑定/证据/AI 发现/项目成员授权覆盖，`delivery` 检查领域元数据、工作流动作、Agent SOP、角色映射和干净验证结果。FDE 后台“业务包门禁”会展示总分、四段评分、每个可交付包得分和阻断项。

创建非默认业务项目时传入 `businessPackId`：

```json
{
  "businessPackId": "compliance_audit_v1",
  "code": "P-CA-001",
  "name": "合规审计试点项目"
}
```

核心层新增行业业务时不应修改平台逻辑；新增业务优先通过业务包配置表达。`libs/business_pack` 默认边界扫描会检查核心加载器中是否出现工程监检行业词。

项目创建后可查询绑定快照，审计时以项目上的 `businessPackSnapshotHash` 和 `businessPackSnapshot` 为准，而不是直接读取最新业务包：

```bash
curl http://127.0.0.1:8000/api/projects/P-CA-001/business-pack/snapshot
```

AI 反馈进入结构化记录，不直接修改业务状态：

```bash
curl -X POST http://127.0.0.1:8000/api/ai/runs/{runId}/feedback \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: feedback-001' \
  -d '{"feedbackType":"edited","accepted":true,"shouldEnterEvaluationSet":true}'
```

监检员在 ReviewRun 上提交 `accept/edit/reject` 人工决策时，后端也会生成不可变来源的 `ai_feedback`：`accept` 记录采纳样本，`edit` 记录人工修正样本，`reject` 记录 `rejected_false_positive` 样本。FDE 调用 `/api/fde/feedback/{id}/triage` 并设置 `status=approved_for_eval` 或 `canUseForEval=true` 后，同一 `sourceFeedbackId` 会幂等生成或更新一条 `evaluation_cases`，用于后续 Prompt/模型/规则/知识库回归评估；原始 ReviewRun 与 AI Run 输出不会被覆盖。`GET /api/fde/feedback` 会把每条反馈的 `governanceState`、`evaluationCaseId`、`canUseForEval`、`canUseForTraining`、`adjudicationRequired`、`dataSensitivity` 和 `sampleUsage` 一并返回，FDE 后台可直接看到反馈是否已提升为评估样本、是否可进入训练集、是否需要仲裁。FDE 发起 `/api/fde/evaluation-runs` 时会为每个样本写入 `evaluation_case_results`，报告包含 `caseSummary`、`caseResults`、缺失 finding、证据覆盖、检索召回、错误依据率和 `casePassRate/findingRecall/evidenceCoverage/retrievalRecall/wrongReferenceRate` 门禁；带 `expectedClauseIds` 的样本会实际调用 Query Router，写入 `fde_evaluation_retrieval` 类型的 `RetrievalTrace`，样本失败会让评估报告进入 `failed`。

FDE 后台是平台级 AI Delivery & Governance Console，不属于业务包角色。它管理 AI 能力，不管理正式业务结论：

- 默认入口：`/fde/dashboard`，登录账号：`fde`。
- 允许：查看 AI 绩效、脱敏 AI Run、Trace、反馈池、评估集/评估报告、Capability Bundle、业务包校验、发布计划、发布门禁、OCR 质量、成本预算和事故/验收记录。
- 受控：诊断重跑、原文访问申请、数据导出申请、反馈归因、发起离线评测、创建/提交发布计划、启动 shadow、申请 canary、请求回滚、业务包安装/升级/回滚演练、事故 RCA 更新；重跑会生成 child run，不覆盖原始 AI Run。
- 禁止：审批资料、保存正式审查意见、发正式补正单、关闭补正项、归档项目、删除业务文件、修改项目最终状态。
- 生产数据默认脱敏；原文访问应通过 `access_grants` 授权并留审计。

FDE 前端一级模块和路由：

```text
/fde/dashboard            AI 驾驶舱：绩效、风险、成本、治理摘要。
/fde/ai-runs              AI Run 追踪：脱敏输出、Trace、诊断重跑。
/fde/review-runs          Agent 编排：Temporal/LangGraph 图、节点、事件、人工确认边界。
/fde/feedback             反馈与标注池：人工纠错、归因、样本入库。
/fde/evaluation           评估实验室：评估集、评估运行、报告和版本对比。
/fde/capability-bundles   Capability Bundle：Agent/Prompt/模型/规则/知识/OCR/Profile 组合与 diff。
/fde/releases             发布中心：shadow、canary、影响面、回滚和审批门禁。
/fde/ocr-quality          OCR 质量中心：runtime doctor、字段/表格/印章/证据质量、100 分评分卡。
/fde/business-packs       业务包工厂：校验、安装、升级、回滚和 diff。
/fde/security             数据安全与脱敏：原文授权、导出审批、脱敏策略、访问审计。
/fde/costs                成本与预算：租户/项目/Agent/模型预算和变更申请。
/fde/incidents            事故与 RCA：影响范围、根因、整改和关闭。
/fde/acceptance           交付验收：验收样本、指标、报告和客户确认记录。
```

98+ 治理闭环已经落到以下接口：

```text
GET  /api/fde/dashboard
GET  /api/fde/ai-runs/{id}
POST /api/fde/ai-runs/{id}/replay
GET  /api/fde/review-runs
GET  /api/fde/review-runs/{id}
GET  /api/fde/review-runs/{id}/graph
GET  /api/fde/review-runs/{id}/temporal-history
POST /api/fde/review-runs/{id}/replay
POST /api/fde/review-runs/{id}/shadow-run
GET  /api/fde/feedback
POST /api/fde/feedback/{id}/triage
GET  /api/fde/evaluation-sets
POST /api/fde/access-grants/request
POST /api/fde/access-grants/{id}/approve     # 仅 admin 批准
POST /api/fde/data-exports
POST /api/fde/data-exports/{id}/approve
POST /api/fde/data-exports/{id}/expire
GET  /api/fde/audit-events
GET  /api/fde/security/masking-policies
POST /api/fde/security/masking-policies
POST /api/fde/evaluation-runs
GET  /api/fde/evaluation-runs/{id}/report
GET  /api/fde/capability-bundles/{id}/diff
POST /api/fde/releases/{id}/submit
POST /api/fde/releases/{id}/start-shadow
POST /api/fde/releases/{id}/mark-shadow-passed
GET  /api/fde/releases/{id}/impact
POST /api/fde/releases/{id}/request-canary
POST /api/fde/releases/{id}/approve-production
POST /api/fde/releases/{id}/rollback
POST /api/fde/business-packs/validate-all
GET  /api/fde/business-packs/{id}/diff
POST /api/fde/business-packs/{id}/install
POST /api/fde/business-packs/{id}/upgrade
POST /api/fde/business-packs/{id}/rollback
POST /api/fde/incidents/{id}/rca
POST /api/fde/incidents/{id}/close
GET  /api/fde/cost-budgets
POST /api/fde/cost-budgets/{id}/propose-change
```

FDE 100 分治理验收应至少验证：

- FDE 只能调用 `/api/fde/*` 治理接口，不能调用正式业务审批、补正、归档、删除文件等命令。
- AI Run、ReviewRun、replay、shadow run 均不可变；重跑必须生成 child run 并保留 parent id。
- 数据默认脱敏；原文访问、数据导出和导出过期均必须写审计事件。
- Capability Bundle、业务包和发布计划必须支持 diff；高风险发布必须有通过状态评估报告、shadow 通过记录、影响面分析、回滚方案和非 FDE 审批。
- 脱敏策略、成本预算变更、事故 RCA 关闭都必须写入持久化集合，并能在 FDE 后台展示。

### 1.5 核心调用链

文件上传与 OCR：

1. 前端调用 `POST /api/projects/{projectId}/documents/upload-session`。
2. `api-service` 创建上传会话并返回 MinIO signed PUT。
3. 浏览器直接上传到 MinIO。
4. 前端调用 upload complete。
5. `api-service` 写入 `documents`、`document_versions`、`knowledge_files`、`knowledge_tasks` 并投递 `ocr.parse_document`。
6. `worker-service` 从 MinIO 读取文件，调用 `ocr-service`。
7. `ocr-service` 返回 fragments、字段、bbox、confidence、diagnostics、seal results。
8. `worker-service` 回写 OCR 字段、证据定位、知识切片和任务状态。

AI 复核与模型对比：

1. 前端触发 AI 复核或 LLM compare。
2. AI 复核：`api-service` 创建 `ai_runs` 和 `review_runs`，默认通过 `AICHECK_REVIEW_ORCHESTRATION=temporal` 启动 Temporal `ReviewRunWorkflow`。
3. `review-worker-service` 执行 LangGraph 兼容审查图：加载上下文、OCR 证据、规则结果、知识依据，经 LiteLLM 生成结构化 finding draft，再做 Schema、证据、依据、Critic 和质量门禁校验。
4. AI finding draft 只进入 `waiting_human_review`，不会直接改变正式业务结论；监检员通过人工确认 API 后才写入正式 `review_findings`，同时沉淀 `ai_feedback`，供 FDE 归因和评估集回流。
5. FDE 通过 `/api/fde/review-runs/*` 查看 Workflow 时间线、Graph 节点、节点产物摘要、工具调用、规则结果、检索 Trace、Finding Draft 明细、校验失败数、Temporal 摘要和 `scorecard`；scorecard 会按 workflow、graph、evidence、governance 四段显示 100 分生产就绪度，明确暴露 inline/fallback、缺少 LangGraph checkpoint、缺少证据链或人工确认边界等阻断项。FDE 可发起诊断重跑或 shadow run；重跑生成 child ReviewRun，不覆盖原始结果。
6. LLM compare 仍由 `worker-service` 通过 LiteLLM 的 OpenAI-compatible API 异步执行。
7. 业务结果回写 PostgreSQL；LiteLLM 保存模型调用层日志，`postgres` 保存 Workflow/checkpoint 状态。

本地开发态如果要达到 Agent 审查编排 `100/100`，不能使用 `AICHECK_REVIEW_ORCHESTRATION=inline`。复制
`backend/.env.review100.example` 为 `.env.review100`，替换本地密钥后启动真实 workflow 栈：

```bash
docker compose --env-file .env.review100 up -d \
  postgres temporal-service redis minio \
  litellm-service api-service review-worker-service

python scripts/review_orchestration_100_probe.py \
  --api-base http://127.0.0.1:8000 \
  --project-id P-2026-HDCP-001 \
  --node-id 24 \
  --wait-seconds 60 \
  --json
```

该探针只验证 Agent 编排本地 100 分：必须看到 `dispatch.mode=temporal`、`workflowEngine=temporal`、
`graphRunner=langgraph`、`graphExecution.checkpointer=postgres`、FDE `scorecard.score=100/ok=true`，并且人工确认
signal 成功发送到 Temporal。inline 模式仍保留为快速单测路径，预期会因为 Temporal/checkpoint 不真实而低于 100。

报告导出：

1. 前端创建报告导出或归档包导出任务。
2. `api-service` 写入 `export_tasks` 并投递 `export.package`。
3. `worker-service` 生成 zip/pdf 产物并写入 MinIO；zip 包必须包含 `manifest.json`、`task.json`、`project.json`、`reports.json`、`documents.json`、`archive_items.json`、`evidence_links.json` 和 `README.txt`。
4. 前端查询任务状态；任务可下载时获取短期 signed GET。

### 1.6 权限与数据边界

- 生产必须启用 `AICHECK_REQUIRE_AUTH=true`，后端以 JWT 身份为准；非管理员不能伪造 `X-Role` 或 `X-User-Id`。
- 后端不会只依赖前端按钮显隐。mutation 会根据路径推断 `ActionCode`，即使前端未传 `X-Action-Code` 也会拦截越权动作。
- `tests/test_contract.py::test_all_non_public_mutating_routes_have_inferred_action_codes` 会遍历 FastAPI 所有非登录 POST/PUT/PATCH/DELETE 路由，确保新增写接口必须配置后端可推断的 `ActionCode`。
- 成功 mutation 如果路由没有显式返回 `auditLogId`，后端中间件会写入一条通用 `ApiMutation` 审计日志；已有显式审计的路由不会重复写。
- 项目成员与节点范围校验覆盖 URL、query、body，以及 `documentId`、`bindingId`、`reportId`、NDT report/film、export task 等资源 ID 反查出的节点。
- 项目树、文件、挂载、报告、归档、NDT、知识任务、搜索、待办、消息、推理日志和模型对比列表在登录态下按 `nodeScope` 过滤。
- `/api/admin/*`、全局知识源/配置/审计、规则版本等管理接口仅管理员可读写。
- 已归档项目的 mutation 统一返回 `ARCHIVED_READONLY`；过期 `If-Match` 返回 `ETAG_CONFLICT`；重复 `Idempotency-Key` 使用请求 hash 防止同 key 不同 body。
- 后端中间件会对所有非公开 POST/PUT/PATCH/DELETE 写请求统一处理 `Idempotency-Key`：相同 key 和相同 body/query 重放首次成功响应，同 key 不同 body/query 返回 `IDEMPOTENCY_KEY_CONFLICT`；路由层仍可对提交、导出、任务重试等关键流程显式传入业务 fingerprint。

### 1.7 数据存储边界

| 存储 | 用途 | 生产要求 |
| --- | --- | --- |
| PostgreSQL | AIcheck 主业务数据、审计日志、任务状态、LiteLLM 元数据、Temporal 状态、LangGraph checkpoint | 使用单实例多数据库或多 schema；生产必须开启持久化卷和备份。 |
| MinIO | 原始文件、预览、导出包、OCR artifacts | 浏览器 signed URL 使用外部域名，服务端使用内网 endpoint。 |
| Redis | Celery broker/result backend、任务状态缓存 | 建议开启持久化或使用托管 Redis。 |

PostgreSQL 第一阶段使用 `aicheck_state`、`aicheck_singletons`、`idempotency_records` 三类 JSONB 状态表承载现有业务 collection，保留 API 行为不变；`backend/libs/db/indexes.py` 声明 PostgreSQL 主键、collection 索引和 JSONB GIN 索引，测试会阻止状态表索引合同退化。后续可按高频查询逐步把项目、资料、审计、FDE 指标等对象关系化。

## 2. 部署前准备

服务器建议：

- Docker 24+ 与 Docker Compose v2。
- 4 核 CPU、16 GB 内存起步；真实 PaddleOCR/印章识别建议 8 核、32 GB 内存或独立 OCR 节点。
- 磁盘至少 100 GB，并为 PostgreSQL、MinIO 数据卷预留独立持久化空间。
- 前端构建机需要 Node.js 18+ 与 pnpm 8+。

外部依赖：

- 模型供应商密钥：AI 审查主链路使用 `DEEPSEEK_API_KEY`，默认模型为 DeepSeek `deepseek-reasoner`；`OPENAI_API_KEY` 仅在继续使用默认 `embedding-default` 时需要。
- 可访问的域名和 HTTPS 证书。
- 如果要启用真实 OCR，需要提供 `agentdesign` OCR 代码。当前 Compose 使用 `Dockerfile.ocr` 安装 `requirements-ocr.txt` 中的 PaddleOCR/PaddleX/PyMuPDF/OpenCV 依赖，并通过 `AICHECK_AGENTDESIGN_HOST_PATH` 把宿主机 `agentdesign` 目录只读挂载到 `/opt/agentdesign`；生产建议保持 `AICHECK_OCR_ALLOW_PLACEHOLDER=false`，无法导入 OCR 管线时任务会失败并进入可重试状态。

## 3. 端口与路径

默认 Compose 端口：

| 服务 | 容器端口 | 主机端口 | 说明 |
| --- | ---: | ---: | --- |
| `api-service` | 8000 | 8000 | FastAPI 主业务 API |
| `ocr-service` | 8010 | 8010 | 内部 OCR API |
| `review-worker-service` | - | - | Temporal/LangGraph 审查编排 worker，不直接暴露 HTTP |
| `litellm-service` | 4000 | 4001 | LiteLLM Proxy，对内使用 |
| `postgres` | 5432 | 5432 | 统一 PostgreSQL 数据库，包含 `aicheck`、`litellm`、`workflow` |
| `redis` | 6379 | 6379 | Celery broker/result backend |
| `minio` | 9000 | 9000 | 对象存储 API，浏览器签名上传需要访问 |
| `minio` | 9001 | 9001 | MinIO 控制台 |
| `temporal-service` | 7233 | 7233 | Temporal 内部 gRPC 服务 |
| `temporal-ui` | 8080 | 8088 | Temporal 工作流调试 UI |

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8010/healthz
curl http://127.0.0.1:4001/health
```

`api-service` 健康检查会返回 `postgresEnabled`、`postgresTransactions`、`authRequired`、`demoUsersEnabled`、`objectStorageEnabled`。`postgresTransactions` 表示后端已启用 PostgreSQL 持久化；生产验收还应使用 `verify_deployment.py --strict-production` 调用 `/api/system/postgres-transaction-probe`，实际执行一次临时 PostgreSQL transaction。`ocr-service` 健康检查会返回 `pipelineAvailable`、`pipelineBackend`、`placeholderAllowed`，`/internal/ocr/doctor` 会返回本地包、模型目录、引擎和预处理候选能力诊断，用于确认 OCR 依赖和占位策略是否符合生产预期。

Compose 已为 `api-service`、`worker-service`、`review-worker-service`、`ocr-service`、`postgres`、`redis`、`minio`、`temporal-service` 和 `litellm-service` 配置容器级 `healthcheck`；`api-service`、`worker-service`、`review-worker-service`、`ocr-service` 和 `litellm-service` 的依赖使用 `condition: service_healthy`，避免依赖容器刚启动但服务尚不可用时提前接流量或消费任务。`validate_deployment_config.py --strict-production` 会静态检查这些 healthcheck 和依赖条件。

前端生产环境只需要暴露 Web 站点、`/api/*`、`/mock/*` 和 MinIO 签名上传访问地址。LiteLLM、PostgreSQL、Redis 不应暴露到公网。

## 4. 后端环境变量

在 `backend/.env` 创建部署环境变量。Compose 在 `backend/` 目录运行时会自动读取该文件。

```bash
DEEPSEEK_API_KEY=sk-...
# Optional: only needed by the default embedding-default alias.
OPENAI_API_KEY=

AICHECK_POSTGRES_DB=aicheck
AICHECK_POSTGRES_USER=aicheck
AICHECK_POSTGRES_PASSWORD=replace-with-strong-postgres-password
AICHECK_DATABASE_URL=postgresql://aicheck:replace-with-strong-postgres-password@postgres:5432/aicheck

AICHECK_REDIS_URL=redis://redis:6379/0
AICHECK_TASK_DISPATCH=celery
AICHECK_REVIEW_ORCHESTRATION=temporal
TEMPORAL_ADDRESS=temporal-service:7233
TEMPORAL_NAMESPACE=default
AICHECK_REVIEW_WORKFLOW_TASK_QUEUE=review.workflow
AICHECK_REVIEW_GRAPH_TASK_QUEUE=review.graph
AICHECK_REVIEW_LLM_TASK_QUEUE=review.llm
AICHECK_REVIEW_RETRIEVAL_TASK_QUEUE=review.retrieval
AICHECK_REVIEW_VALIDATION_TASK_QUEUE=review.validation
AICHECK_REVIEW_LLM_EXECUTION=litellm
AICHECK_LANGGRAPH_DISABLE=false
AICHECK_LANGGRAPH_CHECKPOINT_DISABLE=false
AICHECK_LANGGRAPH_CHECKPOINT_SETUP=false
WORKFLOW_POSTGRES_DB=workflow
LANGGRAPH_CHECKPOINT_DSN=postgresql://aicheck:replace-with-strong-postgres-password@postgres:5432/workflow

AICHECK_MINIO_ENDPOINT=minio:9000
AICHECK_MINIO_PUBLIC_ENDPOINT=files.example.com
AICHECK_MINIO_ACCESS_KEY=aicheck
AICHECK_MINIO_SECRET_KEY=replace-with-strong-password
AICHECK_MINIO_SECURE=true

AICHECK_JWT_SECRET=replace-with-strong-jwt-secret
AICHECK_REQUIRE_AUTH=true
AICHECK_ENABLE_DEMO_USERS=false

AICHECK_OCR_BASE_URL=http://ocr-service:8010
AICHECK_AGENTDESIGN_HOST_PATH=/Volumes/Volume/project/agentdesign
AICHECK_AGENTDESIGN_BACKEND=/opt/agentdesign/mvp-system/backend
AICHECK_OCR_ALLOW_PLACEHOLDER=false
AICHECK_OCR_OFFLINE_ONLY=true
AICHECK_OCR_DISABLE_NETWORK=true
AICHECK_OCR_MODELS_HOST_PATH=/opt/aicheck/ocr-models
AICHECK_PADDLEOCR_DET_MODEL_DIR=/models/paddleocr/PP-OCRv6_medium_det
AICHECK_PADDLEOCR_REC_MODEL_DIR=/models/paddleocr/PP-OCRv6_medium_rec
AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS=true
AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT=180
AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR=/models/paddlex/PP-DocLayout-L
AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR=/models/paddlex/SLANeXt_wired
AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR=/models/paddlex/RT-DETR-L_wired_table_cell_det
AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR=/models/paddlex/SLANeXt_wireless
AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR=/models/paddlex/RT-DETR-L_wireless_table_cell_det
AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE=auto
AICHECK_SEAL_DET_MODEL_DIR=/models/paddlex/PP-OCRv4_server_seal_det
AICHECK_SEAL_REC_MODEL_DIR=/models/paddleocr/PP-OCRv4_server_rec
AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR=/models/paddleocr-vl/PP-DocLayoutV3
AICHECK_PADDLEOCR_VL_REC_MODEL_DIR=/models/paddleocr-vl/PaddleOCR-VL-1.6-0.9B
AICHECK_PADDLEOCR_VL_DOC_ORI_MODEL_DIR=/models/paddlex/PP-LCNet_x1_0_doc_ori
AICHECK_PADDLEOCR_VL_DOC_UNWARP_MODEL_DIR=/models/paddlex/UVDoc
DOCLING_ARTIFACTS_PATH=/models/docling
AICHECK_OCR_PREPROCESS_CACHE_DIR=/tmp/aicheck-ocr-preprocess-cache
AICHECK_OCR_DISABLE_VARIANT_CACHE=false
AICHECK_OCR_RESULT_CACHE_DIR=/tmp/aicheck-ocr-result-cache
AICHECK_OCR_DISABLE_RESULT_CACHE=false

LITELLM_BASE_URL=http://litellm-service:4000
LITELLM_API_KEY=replace-with-litellm-master-key
LITELLM_POSTGRES_DB=litellm
AICHECK_LITELLM_NO_PROXY=127.0.0.1,localhost,::1,postgres
AICHECK_LITELLM_STRICT_PROVIDER_HEALTH=true

```

OCR 离线模型目录支持两种布局：

- 标准 bundle：`AICHECK_OCR_MODELS_HOST_PATH` 下包含 `paddleocr/`、`paddlex/`、`paddleocr-vl/` 和 `docling/`，容器内分别通过 `/models/...` 引用。
- PaddleX 官方缓存：`AICHECK_OCR_MODELS_HOST_PATH` 直接指向 `.paddlex-cache/official_models`，并把 `AICHECK_PADDLEOCR_*_MODEL_DIR`、`AICHECK_PPSTRUCTURE_*_MODEL_DIR`、`AICHECK_SEAL_*_MODEL_DIR`、`AICHECK_PADDLEOCR_VL_*_MODEL_DIR` 配成 `/models/<模型目录名>`。如果 Docling artifacts 放在 `agentdesign/docling`，则设置 `DOCLING_ARTIFACTS_PATH=/opt/agentdesign/docling`；Compose 已把 `AICHECK_AGENTDESIGN_HOST_PATH` 只读挂载到 `/opt/agentdesign`。

变量说明：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | LiteLLM 转发到 DeepSeek 的密钥。`default-chat`、`review-chat`、`compare-fast` 和 `deepseek-reasoner` 默认都路由到 `deepseek/deepseek-reasoner`。 |
| `OPENAI_API_KEY` | 条件必填 | 仅默认 `embedding-default` 使用。若更换 embedding provider，可不填但应关闭严格 provider 健康门禁或同步替换 `embedding-default`。 |
| `AICHECK_DATABASE_URL` | 是 | 主业务 PostgreSQL 连接串。Compose 默认指向 `postgres:5432/aicheck`。 |
| `AICHECK_POSTGRES_DB` | 是 | 主业务数据库名。 |
| `AICHECK_POSTGRES_USER` / `AICHECK_POSTGRES_PASSWORD` | 是 | 统一 PostgreSQL 用户与密码，供 AIcheck、LiteLLM、Temporal 和 LangGraph 使用。 |
| `AICHECK_REDIS_URL` | 是 | Celery broker 和 result backend。 |
| `AICHECK_TASK_DISPATCH` | 是 | 生产使用 `celery`；本地测试可用 `disabled` 或 `inline`。 |
| `AICHECK_REVIEW_ORCHESTRATION` | 是 | 审查工作流编排模式；生产使用 `temporal`，本地兼容模式可用 `legacy`。 |
| `TEMPORAL_ADDRESS` / `TEMPORAL_NAMESPACE` | 是 | `api-service` 和 `review-worker-service` 访问 Temporal 的内部地址和 namespace。 |
| `AICHECK_REVIEW_*_TASK_QUEUE` | 是 | Temporal 审查工作流、Graph、LLM、检索、校验 activity 队列名。 |
| `AICHECK_REVIEW_LLM_EXECUTION` | 是 | 审查图的 LLM 执行模式。生产默认 `litellm`，本地测试可用 `deterministic`。 |
| `AICHECK_LANGGRAPH_DISABLE` | 否 | 生产默认 `false`。为 `true` 时禁用真实 LangGraph runner，仅使用可审计 fallback。 |
| `AICHECK_LANGGRAPH_CHECKPOINT_DISABLE` | 否 | 生产默认 `false`。为 `true` 时即使配置了 DSN 也不启用 LangGraph checkpointer。 |
| `AICHECK_LANGGRAPH_CHECKPOINT_SETUP` | 否 | 是否在 worker 启动执行图时调用 checkpointer `setup()`。生产首次部署可临时设为 `true`，迁移完成后建议关闭。 |
| `WORKFLOW_POSTGRES_DB` | 是 | Temporal 和 LangGraph checkpoint 数据库名，统一 PostgreSQL 初始化脚本会自动创建。 |
| `LANGGRAPH_CHECKPOINT_DSN` | 是 | LangGraph checkpoint 连接串；建议与 `postgres` 保持一致。 |
| `AICHECK_MINIO_ENDPOINT` | 是 | 后端访问 MinIO 的内部地址。 |
| `AICHECK_MINIO_PUBLIC_ENDPOINT` | 是 | 浏览器访问签名 URL 的外部地址。域名、端口和协议必须与反代一致。 |
| `AICHECK_MINIO_SECURE` | 否 | HTTPS 访问 MinIO 时设为 `true`。 |
| `AICHECK_JWT_SECRET` | 是 | JWT 签名密钥。生产必须使用强随机值。 |
| `AICHECK_REQUIRE_AUTH` | 是 | 生产设为 `true`，非公开接口强制校验 JWT。 |
| `AICHECK_ENABLE_DEMO_USERS` | 是 | 生产设为 `false`，禁止使用内置演示账号兜底登录。 |
| `AICHECK_OCR_BASE_URL` | 是 | worker 访问 OCR 服务的内部地址。 |
| `AICHECK_AGENTDESIGN_HOST_PATH` | 是 | 宿主机上的 `agentdesign` 项目路径，Compose 会挂载到 OCR 容器 `/opt/agentdesign:ro`。 |
| `AICHECK_AGENTDESIGN_BACKEND` | 是 | OCR 服务导入 `agentdesign` 后端包的路径，容器内建议挂载到 `/opt/agentdesign/mvp-system/backend`。 |
| `AICHECK_OCR_ALLOW_PLACEHOLDER` | 否 | 生产设为 `false`；OCR 管线不可用时任务失败而不是生成占位成功结果。 |
| `AICHECK_OCR_OFFLINE_ONLY` | 是 | 生产设为 `true`，OCR 只允许使用本地模型。 |
| `AICHECK_OCR_DISABLE_NETWORK` | 是 | 生产设为 `true`，配合 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 禁止运行时下载模型。 |
| `AICHECK_OCR_MODELS_HOST_PATH` | 是 | 宿主机本地 OCR 模型目录，Compose 挂载到 `/models:ro`。 |
| `AICHECK_PADDLEOCR_DET_MODEL_DIR` / `AICHECK_PADDLEOCR_REC_MODEL_DIR` | 是 | PP-OCRv6 文本检测与识别模型目录。 |
| `AICHECK_OCR_ENABLE_PERSISTENT_SUBPROCESS` | 否 | 生产建议 `true`，让 `paddle_ocr_subprocess` 复用常驻 PaddleOCR worker，避免每次解析重复加载模型；异常时自动回退一次性子进程。 |
| `AICHECK_OCR_PERSISTENT_WORKER_TIMEOUT` | 否 | 常驻 PaddleOCR worker 单次请求超时秒数，默认沿用 `AICHECK_OCR_SUBPROCESS_TIMEOUT` 或 `180`。 |
| `AICHECK_PPSTRUCTURE_*_MODEL_DIR` | 建议 | PP-StructureV3 版面、无线/有线表格结构和单元格检测模型目录；缺失时表格引擎不可用，不会联网下载。 |
| `AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE` | 否 | 默认 `auto`；本地 PaddleX 包和印章模型目录齐全时自动启用真实章名识别，显式设为 `false` 才关闭。必需印章 Profile 不应只依赖颜色视觉候选，未跑出可读章名时会进入人工复核。 |
| `AICHECK_SEAL_DET_MODEL_DIR` / `AICHECK_SEAL_REC_MODEL_DIR` | 建议 | PaddleX 印章检测和文字识别模型目录。 |
| `AICHECK_OCR_PREPROCESS_CACHE_DIR` | 否 | 预处理候选图缓存目录，默认 `/tmp/aicheck-ocr-preprocess-cache`；缓存键包含源文件 hash、Profile 和预处理策略。结果会返回 `preprocessStatus.requestedVariants/generatedVariants/missingVariants`。 |
| `AICHECK_OCR_DISABLE_VARIANT_CACHE` | 否 | 设为 `true` 时禁用预处理候选缓存，用于排查图像策略问题。 |
| `AICHECK_OCR_RESULT_CACHE_DIR` | 否 | 本地 OCR 成功解析结果缓存目录，默认 `/tmp/aicheck-ocr-result-cache`；缓存键包含源文件 hash、Profile、模型清单、预处理策略和引擎选项。 |
| `AICHECK_OCR_DISABLE_RESULT_CACHE` | 否 | 设为 `true` 时禁用解析结果缓存，用于重新跑 OCR 引擎或排查模型变化。 |
| `LITELLM_BASE_URL` | 是 | API/worker 访问 LiteLLM 的内部地址。 |
| `LITELLM_API_KEY` | 是 | LiteLLM master key，需与 LiteLLM 配置保持一致。 |
| `LITELLM_POSTGRES_DB` | 是 | LiteLLM PostgreSQL 数据库名。 |
| `AICHECK_LITELLM_NO_PROXY` | 否 | LiteLLM 容器内代理旁路列表，默认必须包含 `127.0.0.1`、`localhost` 和 `postgres`，避免 Prisma query-engine 本机健康探针被 HTTP 代理转发。 |
| `AICHECK_LITELLM_STRICT_PROVIDER_HEALTH` | 否 | 默认 `true`，LiteLLM healthcheck 会在任何 provider 不健康时失败。本地只跑 DeepSeek ReviewRun 且未配置 embedding provider 时可临时设为 `false`。 |

Compose 对关键变量使用必填校验，缺少以下变量时服务不会启动；上线前必须提供强随机值、真实 provider key 或可访问的宿主机路径：

- `DEEPSEEK_API_KEY`
- `AICHECK_AGENTDESIGN_HOST_PATH`
- `AICHECK_OCR_MODELS_HOST_PATH`
- `AICHECK_JWT_SECRET`
- `AICHECK_MINIO_SECRET_KEY`
- `LITELLM_API_KEY`
- `AICHECK_POSTGRES_PASSWORD`

`OPENAI_API_KEY` 是条件必填：如果继续使用默认 `embedding-default` alias 并开启 `AICHECK_LITELLM_STRICT_PROVIDER_HEALTH=true`，则必须提供；如果 embedding provider 已替换为本地或其他供应商，应同步更新 `backend/config/litellm.yaml` 和验收脚本期望。

`check_96_preflight.py --strict-production` 会额外检查内部密钥强度。`AICHECK_JWT_SECRET` 至少 32 个字符且至少 12 个不同字符；`AICHECK_MINIO_SECRET_KEY`、`LITELLM_API_KEY`、`AICHECK_POSTGRES_PASSWORD` 至少 16 个字符且至少 8 个不同字符。`DEEPSEEK_API_KEY` 等 provider key 只做存在和 placeholder 检查，因为格式由供应商决定。

## 5. 启动后端服务

```bash
cd backend
# 确认 backend/.env 中已设置 AICHECK_AGENTDESIGN_HOST_PATH，并且该目录包含 mvp-system/backend
docker compose pull
docker compose up -d --build
docker compose ps
```

首次启动时：

- `api-service` 会连接 PostgreSQL，创建索引，并在空库时写入 demo seed 数据。
- Compose 中的 PostgreSQL 使用一个服务承载 `aicheck`、`litellm`、`workflow` 三个数据库；首次启动时 `docker/postgres/init-databases.sh` 会创建辅助数据库。
- `api-service` 会确保 MinIO bucket：`documents`、`previews`、`exports`、`ocr-artifacts`。
- `worker-service` 会监听队列：`ocr.parse_document`、`ocr.recognize_seals`、`knowledge.slice`、`knowledge.embed`、`inspection.ai_recheck`、`llm.compare`、`export.package`。
- `ocr-service` 会把 `${AICHECK_AGENTDESIGN_HOST_PATH}` 只读挂载到 `/opt/agentdesign`，并从 `/opt/agentdesign/mvp-system/backend` 导入 OCR pipeline。
- `litellm-service` 使用 `backend/config/litellm.yaml` 中的模型别名：`default-chat`、`review-chat`、`deepseek-reasoner`、`compare-fast`、`embedding-default`。

### 5.1 角色账号与权限初始化

第一版真实登录已支持六类角色账号。登录成功后前端会根据后端返回的 `defaultPath` 进入对应面板，并通过 `X-Role`、`X-User-Id` 请求头参与后端项目成员和节点范围校验。FDE 是平台级 AI 治理角色，不写入业务包 `roles.yaml`，也不默认创建项目成员授权。

生产开启 `AICHECK_REQUIRE_AUTH=true` 后，后端会以 JWT 中的登录身份为准校验 `X-Role` 和 `X-User-Id`：非管理员不能伪造其他角色或用户；未传 `X-User-Id` 时会自动使用 JWT 对应用户做项目成员和节点范围校验。GET 和 mutation 都会校验项目成员资格；节点范围同时覆盖 URL 中的 `/nodes/{nodeId}`、query/body 中的 `nodeId/nodeIds`，以及 `documentId`、`bindingId`、`reportId` 等资源 ID 反查出的关联节点。项目树、文件、挂载、报告和归档列表在登录态下会按 `nodeScope` 过滤，避免业务角色看到授权范围外的数据。写接口会根据后端路径表自动推断 `ActionCode`，即使前端未发送 `X-Action-Code`，也会按角色动作矩阵拦截越权调用。

| 角色 | 用户名 | 默认入口 | 说明 |
| --- | --- | --- | --- |
| 系统管理员 | `admin` | `/admin/overview` | 管理后台、配置、授权、审计；不能代替业务角色保存审查意见。 |
| 监检人员 | `inspection` | `/workbench/inspection` | 监检审查、AI 复核、报告生成、导出和归档。 |
| 施工方 | `contractor` | `/workbench/contractor` | 资料上传、节点挂载、提交批次、补正反馈。 |
| 无损检测 | `ndt` | `/workbench/ndt` | 底片、检测记录、检测报告和补正反馈。 |
| 建设方 | `owner` | `/workbench/owner` | 项目、报告和归档只读查看。 |
| FDE | `fde` | `/fde/dashboard` | AI 交付治理、绩效监控、反馈归因、评估和发布申请；不能执行正式业务审批。 |

部署后运行角色创建脚本，确保 PostgreSQL 中的真实登录用户、角色、后台角色矩阵、用户/单位目录和项目成员授权一致：

```bash
cd backend

cat > /secure/aicheck-role-passwords.json <<'JSON'
{
  "admin": "replace-with-strong-admin-password",
  "inspection": "replace-with-strong-inspection-password",
  "contractor": "replace-with-strong-contractor-password",
  "ndt": "replace-with-strong-ndt-password",
  "owner": "replace-with-strong-owner-password",
  "fde": "replace-with-strong-fde-password"
}
JSON
chmod 600 /secure/aicheck-role-passwords.json

# 只预览，不写库
python scripts/create_roles.py \
  --password-file /secure/aicheck-role-passwords.json \
  --require-strong-passwords \
  --dry-run \
  --json

# 本机 PostgreSQL 写入
AICHECK_DATABASE_URL='postgresql://aicheck:replace-with-strong-postgres-password@127.0.0.1:5432/aicheck' \
python scripts/create_roles.py \
  --project-id P-2026-HDCP-001 \
  --password-file /secure/aicheck-role-passwords.json \
  --require-strong-passwords

# Docker Compose 环境写入：先把密码文件复制进 api-service，再执行脚本。
# 当前 compose 文件没有声明 Docker secrets；不要直接引用 /run/secrets 路径，除非你已自行挂载。
docker compose cp /secure/aicheck-role-passwords.json api-service:/tmp/aicheck-role-passwords.json

docker compose exec api-service python scripts/create_roles.py \
  --project-id P-2026-HDCP-001 \
  --password-file /tmp/aicheck-role-passwords.json \
  --require-strong-passwords

docker compose exec api-service rm -f /tmp/aicheck-role-passwords.json
```

脚本行为：

- 写入或更新 `users` 与 `roles`，`users.passwordHash` 使用 PBKDF2-SHA256；重复执行不会重置已有用户密码。
- 生产必须通过 `--password-file` 或 `AICHECK_BOOTSTRAP_PASSWORD_<ROLE>` 环境变量提供初始密码，并使用 `--require-strong-passwords` 拒绝用户名同名、过短或复杂度不足的密码；默认输出会脱敏密码。
- 如需显式重置已有账号密码，增加 `--rotate-passwords`；未传该参数时重复执行会保留已有 `passwordHash`。
- 写入或更新 `admin_configs` singleton 中的 `orgUnits`、`users`、`permissionMatrix`。
- 写入或更新 `project_members`，同一项目、同一用户、同一角色重复执行时会合并 `nodeScope` 和 `actions`，不会插入覆盖性重复成员。`fde` 是平台级角色，脚本会创建登录用户和角色记录，但不会写入 `project_members`。
- 写入一条 `audit_logs` 记录，便于追溯部署初始化动作。
- 上述 PostgreSQL 写入在同一个 transaction 中提交。
- 支持 `--roles admin,inspection` 或 `--roles fde` 只初始化部分角色；支持 `--project-id` 指定项目；支持 `--database-url` 覆盖环境变量。

注意：生产环境 `AICHECK_ENABLE_DEMO_USERS=false` 时，只有脚本写入 `users` 后才能登录。不要在生产使用用户名同名密码；首次上线后仍建议接入企业用户中心或正式密码重置流程。

无 PostgreSQL 的本地联调可以启用内存角色 bootstrap。该模式只用于开发机，后端启动时会把六类角色账号写入当前进程的 in-memory repository：

```bash
cd backend
source .venv/bin/activate
AICHECK_BOOTSTRAP_LOCAL_ROLES=true \
AICHECK_BOOTSTRAP_PASSWORD_ADMIN='Local!2026-SystemZ' \
AICHECK_BOOTSTRAP_PASSWORD_INSPECTION='Local!2026-InspectZ' \
AICHECK_BOOTSTRAP_PASSWORD_CONTRACTOR='Local!2026-BuildZ' \
AICHECK_BOOTSTRAP_PASSWORD_NDT='Local!2026-TestZ' \
AICHECK_BOOTSTRAP_PASSWORD_OWNER='Local!2026-ViewZ' \
AICHECK_BOOTSTRAP_PASSWORD_FDE='Local!2026-FdeZ' \
AICHECK_BOOTSTRAP_LOCAL_ROLE_LIST='admin,inspection,contractor,ndt,owner,fde' \
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

查看日志：

```bash
cd backend
docker compose logs -f api-service
docker compose logs -f worker-service
docker compose logs -f ocr-service
docker compose logs -f litellm-service
```

重启单个服务：

```bash
cd backend
docker compose restart api-service
docker compose restart worker-service
```

停机：

```bash
cd backend
docker compose down
```

不要在生产环境使用 `docker compose down -v`，它会删除 PostgreSQL、MinIO 和 PostgreSQL 数据卷。

## 6. 前端构建与发布

生产构建必须关闭 mock。发布前确认 `frontend/.env.pro` 至少满足：

```bash
VITE_APP_TITLE=AIcheck
VITE_USE_MOCK=false
VITE_BASE_PATH=/
VITE_API_BASE_PATH=
VITE_OUT_DIR=dist-pro
```

构建：

```bash
cd frontend
pnpm install
pnpm lint
pnpm ts:check
pnpm build:pro
```

构建产物在 `frontend/dist-pro`。将该目录发布到 Nginx、OpenResty、Caddy 或对象存储静态站点。

Nginx 示例：

```nginx
server {
    listen 80;
    server_name aicheck.example.com;

    root /var/www/aicheck/dist-pro;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /mock/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

生产 HTTPS 反代示例：

```nginx
server {
    listen 80;
    server_name aicheck.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name aicheck.example.com;

    ssl_certificate /etc/letsencrypt/live/aicheck.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aicheck.example.com/privkey.pem;

    client_max_body_size 200m;
    root /var/www/aicheck/dist-pro;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 300s;
    }

    location /mock/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

MinIO 独立域名 HTTPS 反代示例：

```nginx
server {
    listen 443 ssl http2;
    server_name files.example.com;

    ssl_certificate /etc/letsencrypt/live/files.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/files.example.com/privkey.pem;

    client_max_body_size 2g;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_request_buffering off;
        proxy_read_timeout 600s;
    }
}
```

MinIO CORS 示例。以下命令需要运维机安装 MinIO Client `mc`，并能访问 MinIO API：

```bash
cat > /tmp/aicheck-minio-cors.json <<'JSON'
[
  {
    "AllowedOrigins": ["https://aicheck.example.com"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["Authorization", "Content-Type", "x-amz-*"],
    "ExposeHeaders": ["ETag", "x-amz-request-id", "x-amz-version-id"],
    "MaxAgeSeconds": 3600
  }
]
JSON

mc alias set aicheck-minio https://files.example.com "$AICHECK_MINIO_ACCESS_KEY" "$AICHECK_MINIO_SECRET_KEY"
for bucket in documents previews exports ocr-artifacts; do
  mc cors set "aicheck-minio/${bucket}" /tmp/aicheck-minio-cors.json
  mc cors info "aicheck-minio/${bucket}"
done
```

说明：

- `/api/*` 不需要在 Nginx 中去掉 `/api`，后端已经同时支持 `/api/*` 与无前缀路由。
- `/mock/*` 保留给第一阶段登录兼容。真实登录接口是 `/api/auth/login`。
- 如果 MinIO 使用独立域名，例如 `files.example.com`，需要为 MinIO API 单独配置 HTTPS 反代，并把 `AICHECK_MINIO_PUBLIC_ENDPOINT` 设置为该域名。
- 浏览器直传 MinIO 时，如前端站点和 MinIO 域名不同，需要为 MinIO 配置 CORS，允许 `PUT`、`GET`、`HEAD` 和必要请求头。
- `AICHECK_MINIO_SECURE` 必须和浏览器实际访问 signed URL 的协议一致：`https://files.example.com` 时设为 `true`，本地 `http://127.0.0.1:9000` 时设为 `false`。

## 7. OCR 部署说明

当前 OCR 服务启动命令：

```bash
uvicorn apps.ocr_service.main:app --host 0.0.0.0 --port 8010
```

OCR 调用链：

1. 前端创建 upload session。
2. 浏览器使用 MinIO signed PUT 上传文件。
3. 前端调用 upload complete。
4. `api-service` 写入 `documents`、`document_versions`、`knowledge_tasks`。
5. `worker-service` 消费 `ocr.parse_document`，通过 `AICHECK_OCR_BASE_URL` 调用 `ocr-service`。
6. OCR 结果回写 `extracted_fields`、`knowledge_files`、`knowledge_chunks`、`evidence_links` 和任务状态。

真实 OCR 注意事项：

- `backend/apps/ocr_service/service.py` 会从 `AICHECK_AGENTDESIGN_BACKEND` 指定路径导入 `seal_ocr.pipeline`。
- 当前 Compose 要求设置 `AICHECK_AGENTDESIGN_HOST_PATH`，并把该目录挂载为 `/opt/agentdesign:ro`；默认 `AICHECK_AGENTDESIGN_BACKEND=/opt/agentdesign/mvp-system/backend`。
- `Dockerfile.ocr` 会安装 `requirements-ocr.txt`；该文件对齐本地 OCR 基线依赖：`PyMuPDF`、`paddlepaddle`、`paddleocr`、`paddlex[ocr]`、`opencv-python-headless`、`docling`、`transformers`。
- OCR 服务已按 Document Intelligence 方向组织：优先使用本地 agentdesign 管线；无可解析内容时调用本地引擎链 `PaddleOCR subprocess -> PaddleOCR in-process -> PP-StructureV3 -> PaddleX Seal -> 视觉印章候选 -> PaddleOCR-VL/Docling adapter`。所有引擎都必须使用本地模型目录，缺模型时只标记 engine unavailable 或返回结构化诊断，不允许运行时联网下载。
- 本地模型目录建议结构：

```text
${AICHECK_OCR_MODELS_HOST_PATH}/
├── paddleocr/
│   ├── PP-OCRv6_medium_det/
│   ├── PP-OCRv6_medium_rec/
│   └── PP-OCRv4_server_rec/
├── paddlex/
│   ├── PP-DocLayout-L/
│   ├── SLANeXt_wired/
│   ├── RT-DETR-L_wired_table_cell_det/
│   ├── SLANeXt_wireless/
│   ├── RT-DETR-L_wireless_table_cell_det/
│   ├── PP-OCRv4_server_seal_det/
│   ├── PP-LCNet_x1_0_doc_ori/
│   └── UVDoc/
├── paddleocr-vl/
│   ├── PP-DocLayoutV3/
│   └── PaddleOCR-VL-1.6-0.9B/   # PaddleX may also create PaddleOCR-VL-1.6/
└── docling/
```

- `piping_characteristic_list_v1` 已内置为第一批工程表格 Profile；PP-StructureV3 模型缺失时，会基于 OCR 文本坐标重建基础 `piping_characteristic_table_1`，并抽取公司名称、项目名称、文件标题、图纸编号、设计阶段、管道代号等字段。
- 样本验收可使用：

```bash
cd backend
python scripts/ocr_runtime_doctor.py --json
python scripts/ocr_runtime_doctor.py --strict-production
curl http://127.0.0.1:8010/internal/ocr/doctor
```

`ocr_runtime_doctor.py` 不跑 OCR 推理，只检查本地 Python 包、`AICHECK_OCR_SUBPROCESS_PYTHON`、模型目录、引擎可用性、离线策略和预处理候选生成能力。若 `preprocess.variants`、`engine.paddle_ocr_subprocess` 或 `engine.pp_structure_v3` 失败，应先修 OCR 镜像依赖或模型挂载，再调 Profile 和字段规则。
如果 `AICHECK_AGENTDESIGN_HOST_PATH` 指向本地 agentdesign 工程，doctor 会额外返回 `recommendedEnv`，自动推荐 `.venv-ocr311/bin/python`、`.paddlex-cache/official_models/PP-OCRv6_medium_det`、`PP-OCRv6_medium_rec`、`PP-OCRv4_server_seal_det`、`PP-DocLayoutV3`、`PaddleOCR-VL-1.6-0.9B` 或 PaddleX 实际生成的 `PaddleOCR-VL-1.6` 等可用路径，便于直接写入 `backend/.env`。
OCR 100 的 PaddleOCR-VL 适配器要求 OCR 镜像安装 `transformers`，并同时存在本地 `AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR` 与 `AICHECK_PADDLEOCR_VL_REC_MODEL_DIR`；`AICHECK_PADDLEOCR_VL_REC_MODEL_DIR` 可以指向 `PaddleOCR-VL-1.6-0.9B` 或 `PaddleOCR-VL-1.6`，但目录必须包含完整 `transformers` 权重，例如 `model.safetensors`。Docling 适配器要求安装 `docling` 且挂载非空的本地 `DOCLING_ARTIFACTS_PATH`。
Docker 部署时 `AICHECK_OCR_SUBPROCESS_PYTHON` 应保持 `/usr/local/bin/python`，使用 OCR 镜像内依赖；只有裸机本地 probe 才使用 doctor 推荐的宿主机 `.venv-ocr311`。
裸机本地 probe 可以加 `--auto-discover-runtime`，脚本会在未显式设置对应环境变量时应用 doctor 推荐的 OCR Python 和模型路径；生产 Compose 仍应显式写入 `.env`，不要依赖自动发现。
FDE 的 `GET /api/fde/ocr-quality` 会返回同一诊断的 `runtimeDoctor` 摘要，后台可直接看到 fail/warn 数和首要修复建议。

### 7.1 OCR 100 人工金标验收 Runbook

OCR 100 分不是运行态 smoke test，而是“本地 OCR 能力 + 真实业务样本 + 人工金标 + 回归评分”的验收证据。运行态必须先通过 `ocr_runtime_doctor.py --strict-production` 和 live OCR object probe；100+ 人工标注准确率报告可以延期，但不能用机器预标注或合成样本替代。

当前状态先用统一汇总命令查看：

```bash
cd backend
python scripts/ocr_100_certification_status.py \
  --output ocr_eval/reports/ocr_100_certification_status.json \
  --markdown-output ocr_eval/reports/ocr_100_certification_status.md
```

汇总报告会合并 `ocr_100_scorecard.json`、closure plan、sample intake、pipeline 和 reviewed-label gate，输出 `status`、门禁、阻塞项、场景缺口和下一步动作。典型未完成状态包括：

- `needs_sample_files`：真实样本文件还没有放入 intake 目录，或 `manifest` 仍是占位文件名。
- `needs_human_labels`：样本已进入标注包，但还没有完成独立人工标注和复核。
- `needs_release_eval_export`：人工标注已 ready，但 release eval set 尚未导出。
- `needs_scorecard_rerun`：release eval set 已存在，需要重跑 scorecard。
- `complete`：scorecard `ok=true` 且 100 分门禁完成。

生成 OCR 100 行动板，给 FDE/人工标注团队分派“采样、去重、标注、导出、重跑评分”任务：

```bash
python scripts/ocr_100_action_board.py \
  --closure-plan ocr_eval/reports/ocr_100_closure_plan_after_batch6_dedupe.json \
  --annotation-tasks ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_retry_merged_after_batch6_dedupe.json \
  --candidates ocr_eval/reports/ocr_100_scan_candidates.json \
  --output ocr_eval/reports/ocr_100_action_board.json \
  --markdown-output ocr_eval/reports/ocr_100_action_board.md \
  --csv-output ocr_eval/reports/ocr_100_action_board.csv
```

`ocr_100_action_board.csv` 可直接给采样/标注人员使用；`collect_samples` 行包含 `missingCases`、`dropDirectory`、`checklist` 和 `collectionHint`，用于补真实业务文件；`label_existing` 行包含 `sourcePath`、`taskId`、`blockers`、`previewPaths` 和 `humanActions`，用于处理已有 Scan 样本的人审校对；`triage_candidates` 行先去重再入库。

真实样本采集和导入流程：

```bash
cd backend

# 1. 由 closure plan 生成或刷新缺口采样包。
python scripts/ocr_100_collection_intake.py \
  ocr_eval/reports/ocr_100_closure_plan_after_batch6_dedupe.json \
  --output-dir ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe

# 2. 按 samples/<scenario>/README.md 放入真实客户/现场文件。
#    不要把标准、规范、制度 PDF 当作业务 OCR 认证样本。

# 3. 先扫描候选文件并按 SHA256 去重；发现 duplicate 时不要重复入库。
python scripts/ocr_100_collection_candidates.py \
  ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/samples \
  --existing-queue ocr_eval/reports/scan_sample_queue.json \
  --existing-queue ocr_eval/reports/new_sample_queue.json \
  --intake-dir ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe \
  --output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/collection_candidates.json \
  --markdown-output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/collection_candidates.md

# 4. 自动把各场景目录中的文件填入 manifest_autofilled.json。
python scripts/ocr_100_collection_intake_autofill.py \
  ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe \
  --output-manifest manifest_autofilled.json \
  --output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/autofill.json \
  --markdown-output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/autofill.md

# 5. 严格校验 manifest。该命令不过，不允许进入 ingest。
python scripts/ocr_100_collection_intake_verify.py \
  ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe \
  --manifest manifest_autofilled.json \
  --strict \
  --output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/verify_autofilled.json \
  --markdown-output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/verify_autofilled.md

# 6. 先 dry-run 看 ingest 和 annotation pack 计划。
python scripts/ocr_100_collection_intake_pipeline.py \
  ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe \
  --output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/pipeline.json \
  --markdown-output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/pipeline.md

# 7. strict 校验通过后执行 ingest 和 annotation pack 生成。
python scripts/ocr_100_collection_intake_pipeline.py \
  ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe \
  --execute \
  --render-previews \
  --queue-output ocr_eval/reports/new_sample_queue.json \
  --annotation-output-dir ocr_eval/reports/new_annotation_pack \
  --ocr-result-dir ocr_eval/reports/new_ocr_results \
  --copy-to ocr_eval/real_samples \
  --output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/pipeline_execute.json \
  --markdown-output ocr_eval/reports/ocr_100_sample_intake_after_batch6_dedupe/pipeline_execute.md
```

人工标注要求：

- Label Studio 中必须由人工校对机器建议，替换所有 `replace-with-*` 占位值。
- 每个字段、表格、印章都要有正面积 `bbox` 或 `polygon` 证据；`[0,0,0,0]` 不合格。
- `collectionStatus` 必须进入 `ready_for_eval`。
- `review.labeler` 与 `review.reviewer` 必须存在且不能相同。
- 机器草稿必须改为 `review.source=human_review`，并设置 `requiresHumanConfirmation=false`。

Label Studio 回导和 release eval 门禁：

```bash
cd backend

python scripts/ocr_100_reviewed_label_gate.py \
  ocr_eval/reports/new_annotation_pack/prelabelled_tasks.json \
  --label-studio-export <label-studio-export.json> \
  --output-dir ocr_eval/reports/reviewed_label_gate \
  --sample-summary ocr_eval/reports/img6509_sample_probe_summary.json \
  --strict
```

`reviewed_label_gate` 会导入 Label Studio 标注、运行 readiness、导出 `ocr_100_labeled_release_set.json`，并在可用时写入 gate 报告。它不通过时，不要手工拼 release eval set。

最终 scorecard：

```bash
python scripts/ocr_100_scorecard.py \
  --eval-set ocr_eval/reports/reviewed_label_gate/ocr_100_labeled_release_set.json \
  --sample-summary ocr_eval/reports/img6509_sample_probe_summary.json \
  --auto-discover-runtime \
  --output ocr_eval/reports/ocr_100_scorecard.json

python scripts/ocr_100_certification_status.py \
  --output ocr_eval/reports/ocr_100_certification_status.json \
  --markdown-output ocr_eval/reports/ocr_100_certification_status.md \
  --strict
```

OCR 100 完成标准：

- `ocr_100_certification_status.py --strict` 返回 0。
- `ocr_100_scorecard.json` 中 `ok=true`、`score=100`。
- Release eval set 至少 100 个真实人工金标 case。
- 必需场景覆盖质量证明书、RT/UT NDT 报告、施工记录、焊接记录、资质证书、管道特性表、印章文本、证据定位和质量门禁样本。

部署前预取本地 OCR 模型：

```bash
python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /opt/aicheck/paddlex-cache \
  --ocr-100

# 大模型下载中断后，显式移走 incomplete 缓存并重试。
python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /opt/aicheck/paddlex-cache \
  --model PaddleOCR-VL-1.6-0.9B \
  --vl-download-method hf-snapshot \
  --timeout-seconds 3600 \
  --download-retries 3 \
  --disable-hf-xet \
  --clean-incomplete

python scripts/ocr_prefetch_models.py \
  --python /path/to/ocr-python \
  --cache-home /opt/aicheck/paddlex-cache \
  --ocr-100 \
  --verify-only
```

预取阶段可以在受控准备环境访问官方模型源；生产 `ocr-service` 只挂载预取后的 `official_models` 目录和 Docling artifact 目录，保持 `AICHECK_OCR_OFFLINE_ONLY=true`、`AICHECK_OCR_DISABLE_NETWORK=true`，避免运行时下载模型。`--ocr-100` 覆盖 PP-OCRv6、PP-StructureV3 wired/wireless 表格、PaddleX Seal、文档方向和去畸变模型，并默认下载 Docling 的 `layout/tableformer/code_formula/picture_classifier/rapidocr` 离线资产；如只预取 PaddleX 模型，可显式加 `--no-docling`。

```bash
cd backend
AICHECK_OCR_ALLOWED_LOCAL_DIRS=/tmp \
AICHECK_OCR_SUBPROCESS_PYTHON=/Volumes/Volume/project/agentdesign/.venv-ocr311/bin/python \
AICHECK_PADDLEX_MODEL_CACHE=/Volumes/Volume/project/agentdesign/.paddlex-cache/official_models \
python scripts/ocr_sample_probe.py /tmp/aicheck-ocr-test-IMG_6509.png \
  --profile-id piping_characteristic_list_v1 \
  --min-fragments 300 \
  --min-fields 5 \
  --require-field-code project_name \
  --require-field-code document_title \
  --require-field-code drawing_no \
  --max-missing-required-fields 0 \
  --max-field-conflicts 0 \
  --min-tables 1 \
  --min-formal-tables 1 \
  --min-business-rows 5 \
  --max-missing-required-tables 0 \
  --max-heuristic-tables 0 \
  --min-seals 1 \
  --min-readable-seals 1 \
  --min-fragment-seals 1 \
  --require-seal-type design_license_seal \
  --max-missing-expected-seal-types 0 \
  --require-quality-status auto_usable \
  --min-evidence-completeness 1 \
  --max-low-confidence-fields 0 \
  --max-missing-evidence 0 \
  --output /tmp/aicheck-img6509-probe-full.json \
  --summary-output /tmp/aicheck-img6509-probe-summary.json
```

自动发现版：

```bash
cd backend
AICHECK_OCR_ALLOWED_LOCAL_DIRS=/tmp \
python scripts/ocr_sample_probe.py /tmp/aicheck-ocr-test-IMG_6509.png \
  --auto-discover-runtime \
  --profile-id piping_characteristic_list_v1 \
  --min-fragments 300 \
  --min-fields 5 \
  --require-field-code project_name \
  --require-field-code document_title \
  --max-missing-required-fields 0 \
  --min-tables 1 \
  --min-formal-tables 1 \
  --min-business-rows 5 \
  --max-missing-required-tables 0 \
  --min-seals 1 \
  --min-readable-seals 1 \
  --min-fragment-seals 1 \
  --require-seal-type design_license_seal \
  --max-missing-expected-seal-types 0 \
  --require-quality-status auto_usable \
  --min-evidence-completeness 1
```

- 性能门禁应在至少一次缓存预热后启用，例如追加 `--min-engine-cache-hit-rate 0.75 --max-engine-duration-ms 5000 --max-single-engine-duration-ms 3000`。验证 PaddleX Seal、agentdesign seal OCR 等增强引擎时，再追加 `--fail-on-engine-failure`，避免增强引擎超时但融合结果靠 fallback 成功而被误判为全绿。

- OCR Profile、预处理策略、模型清单或表格/印章引擎变更后，应使用 release evaluation set 做本地回归门禁：

```bash
cd backend
python scripts/ocr_eval_set.py ./ocr_eval/piping_release_set.json \
  --output ./ocr_eval/reports/piping_release_report.json \
  --summary-output ./ocr_eval/reports/piping_release_summary.json \
  --markdown-output ./ocr_eval/reports/piping_release_report.md \
  --min-average-score 0.90
```

100 分 OCR 就绪度是独立严格门禁，不等同于当前小样本 release set 通过。开启后会要求至少 100 个
evaluation cases、覆盖必需 OCR 场景，并把字段、表格、印章、证据和质量门禁提升到 95%+ 级别：

```bash
python scripts/ocr_100_ingest_samples.py ../files ../Scan \
  --output ./ocr_eval/reports/ocr_100_real_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_ingest_samples.py ../Scan \
  --manifest ./ocr_eval/scan_sample_manifest.json \
  --output ./ocr_eval/reports/scan_sample_queue.json \
  --base-dir ..

python scripts/ocr_100_annotation_pack.py ./ocr_eval/reports/scan_sample_queue.json \
  --output-dir ./ocr_eval/reports/scan_annotation_pack \
  --source-base-dir .. \
  --render-previews

python scripts/ocr_100_annotation_prelabel.py ./ocr_eval/reports/scan_annotation_pack \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --source-base-dir .. \
  --run-ocr \
  --auto-discover-runtime \
  --disable-result-cache \
  --save-result-dir ./ocr_eval/reports/scan_ocr_results \
  --limit 5

python scripts/ocr_100_label_studio_export.py ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output-dir ./ocr_eval/reports/scan_label_studio \
  --preview-base-dir ./ocr_eval/reports/scan_annotation_pack \
  --local-files-root ./ocr_eval/reports/scan_annotation_pack

python scripts/ocr_100_label_studio_import.py ./ocr_eval/reports/scan_label_studio/label_studio_export.json \
  --annotation-tasks ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --report-output ./ocr_eval/reports/scan_label_studio_import_report.json

python scripts/ocr_100_annotation_export.py ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --output ./ocr_eval/reports/scan_labeled_release_set.json \
  --report-output ./ocr_eval/reports/scan_annotation_export_report.json

python scripts/ocr_100_corpus.py ./ocr_eval \
  --output ./ocr_eval/reports/ocr_100_release_set.json \
  --report-output ./ocr_eval/reports/ocr_100_corpus_report.json \
  --collection-plan-output ./ocr_eval/reports/ocr_100_collection_plan.json \
  --collection-todo-output ./ocr_eval/reports/ocr_100_collection_todo.csv \
  --require-real-samples

# 仅用于生成采集骨架。所有 fixtureDerived=true 的 case 必须替换为真实标注样本后才能做生产认证。
python scripts/ocr_100_corpus.py ./ocr_eval/piping_release_set.json \
  --bootstrap-to-targets \
  --output ./ocr_eval/reports/ocr_100_collection_skeleton.json \
  --report-output ./ocr_eval/reports/ocr_100_collection_skeleton_report.json

python scripts/ocr_eval_set.py ./ocr_eval/piping_release_set.json \
  --auto-discover-runtime \
  --disable-result-cache \
  --strict-100 \
  --summary-output ./ocr_eval/reports/piping_release_100_summary.json

python scripts/ocr_100_scorecard.py \
  --eval-set ./ocr_eval/piping_release_set.json \
  --auto-discover-runtime \
  --sample-summary /tmp/aicheck-ocr-sample-summary.json \
  --output ./ocr_eval/reports/ocr_100_scorecard.json
```

`ocr_100_scorecard.py` 会把 OCR 服务拆成四块客观打分：本地 runtime/离线策略 25 分、100-case 评估集和核心指标 45 分、真实样张 probe 20 分、评估报告可观测性 10 分。当前 `piping_release_set.json` 是小型合同 fixture，主要证明 evaluator、Profile 和证据门禁存在；它不应被当成 100 分生产验收 corpus。
`ocr_100_corpus.py` 用于从真实 eval set 文件/目录合并 100-case release corpus，并阻止重复 caseId、缺少必需场景、目标场景分布不足、缺少 expected 正面积证据坐标或少于 100 条样本的验收包进入评分卡。`--collection-plan-output` 输出完整 JSON 采集计划，`--collection-todo-output` 输出可分派的 CSV 缺口清单，包含每个缺失 case 的采集提示、必需标注项和源文件要求。
`ocr_100_ingest_samples.py` 用于把本地 PDF/图片登记为 `collectionStatus=needs_labeling` 的真实样本标注队列，默认排除标准/规范类文件；它生成的 `expected` 是人工标注模板，`[0,0,0,0]` 这类占位 bbox 不能通过 100 分认证，必须替换成真实字段、表格、印章标签和正面积 bbox/polygon。
`Scan/` 这类数字文件名扫描件需要配合 `--manifest ./ocr_eval/scan_sample_manifest.json` 导入；当前 manifest 识别出 30 个待标注样本，覆盖质量证明、管道特性表、施工资料、资质证书、焊接工艺评定、RT 报告、印章文字、碎片印章、证据定位和质量门禁场景；本地 Scan 批次仍缺 UT 报告样本。
`ocr_100_annotation_pack.py` 会把待标注队列转成 `annotation_tasks.json`、CSV、Markdown 和可选预览图，便于人工填写字段/表格/印章标签及正面积坐标；预览包是本地工作产物，完成标注后再把 verified expected 写回 release eval set。
`ocr_100_annotation_prelabel.py` 可从已有 OCR JSON 或 `--run-ocr` 生成 `suggestedExpected` 机器预标注；本地真实 OCR 建议加 `--auto-discover-runtime` 自动套用 runtime doctor 推荐的 OCR Python 和模型目录，用 `--disable-result-cache` 避免复用旧失败缓存，用 `--save-result-dir` 保存每个 case 的原始 OCR JSON，并用 `--case-id`/`--limit` 分批处理昂贵任务；这些建议只用于人工复核，审核人必须复制/修正到 `labeledExpected` 后才会被导出为真值。
预标注脚本默认优先使用 annotation pack 中的 `previewPaths`，不只限 HEIC，也包括 PDF 渲染预览；这样机器建议和人工标注共享同一张 PNG 的像素坐标，避免直接重跑原始多页 PDF 后 bbox 坐标系不一致。
`ocr_100_sample_probe_batch.py` 用于把 `scan_sample_queue.json` 中的真实样本按 case/profile 批量跑 OCR，并输出 `ocr_100_scorecard.py --sample-summary` 可直接消费的 `items[]` 摘要。它适合做上线前真实样张 smoke，不会生成或确认金标；`--scorecard-sample-gate` 只验证样张是否达到字段、表格、印章和证据门禁。示例：

```bash
python scripts/ocr_100_sample_probe_batch.py ./ocr_eval/reports/scan_sample_queue.json \
  --case-id real-piping_table_profile-002 \
  --scorecard-sample-gate \
  --auto-discover-runtime \
  --disable-result-cache \
  --output ./ocr_eval/reports/scan_sample_probe_batch.json \
  --summary-dir ./ocr_eval/reports/scan_sample_probe_items \
  --require-all-pass

python scripts/ocr_100_scorecard.py \
  --eval-set ./ocr_eval/reports/ocr_100_release_set.json \
  --sample-summary ./ocr_eval/reports/scan_sample_probe_batch.json \
  --auto-discover-runtime \
  --output ./ocr_eval/reports/ocr_100_scorecard.json
```

`ocr_100_label_studio_export.py` 会把标注/预标注任务转换成 Label Studio 的 `label_config.xml` 和 `label_studio_tasks.json`；配置 Label Studio local files 指向同一个 `--local-files-root` 后，机器建议 bbox 会作为可编辑 prediction region 导入，方便人工修正字段、表格和印章坐标。导出默认不允许静默跳过缺预览或不可读预览的任务，`--allow-skipped` 只适合分批草稿导出，全空导出仍不能作为成功标注包。
`ocr_100_label_studio_import.py` 会把 Label Studio 导出的人工 `annotations` 回写到 `labeledExpected`：如果审核人填写了完整 `label_json`，优先使用该 JSON；否则把人工矩形区域换算回像素 bbox，并尽量合并匹配的 `suggestedExpected` 字段/表格/印章元数据。脚本默认忽略 `predictions`，避免机器预标注未经人工确认就进入金标；导入阶段也会严格检查占位标签、零面积 bbox 和缺少字段/表格/印章证据，默认失败，只有显式 `--allow-incomplete` 才能作为复核草稿继续写出。
`ocr_annotation_readiness.py` 用于在导出 release eval set 前检查人工标注进度，输出任务数、人工已标注数、可入评估集数、场景覆盖、阻断项计数和下一步动作；它会把只有 `suggestedExpected` 的机器预标注标记为 `machine_suggestion_not_confirmed`，防止机器结果未经人工校对直接进入金标。
`ocr_100_annotation_sprint.py` 用于把 annotation/prelabelled pack 转成“人工标注冲刺计划”，按 OCR 100 场景目标、是否已有机器建议、是否已有正面积证据和 readiness blocker 排序，输出 JSON、Markdown 和 CSV 工作清单。它只排班和提示，不会把机器建议升级成金标。示例：

```bash
python scripts/ocr_100_annotation_sprint.py ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --limit 30 \
  --output ./ocr_eval/reports/scan_annotation_sprint.json \
  --markdown-output ./ocr_eval/reports/scan_annotation_sprint.md \
  --csv-output ./ocr_eval/reports/scan_annotation_sprint.csv
```

`ocr_100_annotation_export.py` 是标注包到 release eval set 的严格交接工具：默认拒绝占位标签、零面积 bbox 和缺少字段/表格/印章证据的半成品；`--allow-incomplete` 只用于复核草稿输出，仍会报告未完成项数量，不能用于 OCR 100 认证。

### 7.1 OCR 手动打标教程

AIcheck 支持两条手动打标路径：

- 批量标注：使用 `ocr_100_label_studio_export.py` / `ocr_100_label_studio_import.py` 对接 Label Studio，适合 100-case release corpus。
- 轻量校对：使用 FDE 后台内置 OCR 人工标注工作台，适合从 `Scan/` 抽样、修正机器预标注、补齐 bbox、做二审门禁和小批量回归。

FDE 内置工作台只管理 OCR 金标和 AI 能力评估，不产生正式业务审查结论。FDE 标注或二审不会审批资料、发补正单、归档项目或修改业务状态。

#### 7.1.1 从本地 Scan 生成待标注任务

先把本地扫描件登记成 annotation pack。`Scan/` 中数字文件名较多时建议维护 manifest，用人工语义补齐文件类型、场景和 Profile：

```bash
cd backend

python scripts/ocr_100_ingest_samples.py ../Scan \
  --manifest ./ocr_eval/scan_sample_manifest.json \
  --output ./ocr_eval/reports/scan_annotation_queue.json \
  --copy-to ./ocr_eval/scan_samples \
  --limit 30

python scripts/ocr_100_annotation_pack.py ./ocr_eval/reports/scan_annotation_queue.json \
  --output-dir ./ocr_eval/reports/scan_annotation_pack \
  --render-previews
```

可选：先跑本地 OCR 生成机器预标注，人工只需要校对和修 bbox：

```bash
python scripts/ocr_100_annotation_prelabel.py ./ocr_eval/reports/scan_annotation_pack \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  --source-base-dir .. \
  --run-ocr \
  --auto-discover-runtime \
  --disable-result-cache \
  --save-result-dir ./ocr_eval/reports/scan_ocr_results \
  --limit 5
```

单个样本修复或模型策略更新后，可以只刷新目标 case，避免覆盖整包：

```bash
python scripts/ocr_100_annotation_prelabel.py ./ocr_eval/reports/scan_annotation_pack \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_img6509_refreshed_tasks.json \
  --source-base-dir .. \
  --run-ocr \
  --auto-discover-runtime \
  --disable-result-cache \
  --save-result-dir ./ocr_eval/reports/scan_ocr_results_refreshed \
  --case-id real-piping_table_profile-002 \
  --max-fields 8 \
  --max-tables 3 \
  --max-seals 3
```

刷新局部 case 后，先合并成新的主预标注包，再把该合并包交给人工标注。合并工具默认保留已有 `labeledExpected`，不会覆盖人工金标：

```bash
python scripts/ocr_100_annotation_merge_prelabels.py \
  ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json \
  ./ocr_eval/reports/scan_annotation_pack/prelabelled_img6509_refreshed_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_merged.json

python scripts/ocr_100_annotation_sprint.py ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_merged.json \
  --limit 30 \
  --output ./ocr_eval/reports/scan_annotation_sprint_merged.json \
  --markdown-output ./ocr_eval/reports/scan_annotation_sprint_merged.md \
  --csv-output ./ocr_eval/reports/scan_annotation_sprint_merged.csv
```

刷新一批 OCR 结果后，先做 Scan manifest 审计，防止样本场景错配污染 100-case 评估集。审计工具会读取队列/manifest、已保存 OCR result，按关键词和 OCR 文本给出 `suggestedScenario`、`mismatch` 和目标分布缺口；它只给人工复核建议，不会自动修改 manifest：

```bash
python scripts/ocr_100_manifest_audit.py ./ocr_eval/reports/scan_sample_queue.json \
  --result-dir ./ocr_eval/reports/scan_ocr_results_refreshed \
  --result-dir ./ocr_eval/reports/scan_ocr_results_single \
  --output ./ocr_eval/reports/scan_manifest_audit.json \
  --csv-output ./ocr_eval/reports/scan_manifest_audit.csv \
  --markdown-output ./ocr_eval/reports/scan_manifest_audit.md
```

如果审计报告出现 `mismatch`，先人工确认文件类型，再决定是修正 manifest/队列场景，还是把该样本排除出对应场景的 release eval set。比如 `管道壁厚计算书/设计图纸` 不应继续作为 `quality_certificate_profile` 的质量证明书金标样本。

对旧 `NO_LOCAL_OCR_RESULT` 或 `qualityStatus=failed` 的预标注包，先生成重试计划，不要盲目全量重跑。计划会把 manifest mismatch 样本放入 `reviewBeforeRetry`，其余旧失败样本按优先级拆成小批次，并生成可审阅的 shell 命令：

```bash
python scripts/ocr_100_prelabel_retry_plan.py \
  ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_merged_v2.json \
  --manifest-audit ./ocr_eval/reports/scan_manifest_audit.json \
  --limit 12 \
  --batch-size 3 \
  --output ./ocr_eval/reports/scan_prelabel_retry_plan.json \
  --csv-output ./ocr_eval/reports/scan_prelabel_retry_plan.csv \
  --shell-output ./ocr_eval/reports/scan_prelabel_retry_plan.sh \
  --refresh-output ./ocr_eval/reports/scan_annotation_pack/prelabelled_retry_refreshed_tasks.json \
  --merged-output ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_retry_merged.json \
  --result-dir ./ocr_eval/reports/scan_ocr_results_refreshed \
  --source-base-dir ..
```

执行 `scan_prelabel_retry_plan.sh` 前必须先打开 CSV/JSON 核对 caseId，尤其是 `reviewBeforeRetry`。计划生成的命令默认带 `--retry-fast-timeouts --engine-timeout-seconds <N> --disable-remediation`，用于快速刷新旧失败样本并避免二阶段补救链路拖慢批量预标注；如果要做完整 OCR 优化回归，再用 `--enable-remediation` 重新生成计划。若确认错配样本仍需要重跑，可加 `--include-mismatches` 重新生成计划；否则应先修正 manifest/队列或排除该样本。每批重试完成后，再运行 `ocr_100_manifest_audit.py` 和 `ocr_100_annotation_sprint.py` 生成新的人工标注冲刺清单。

如果某条机器预标注已经足够接近人工结果，可以先把它复制成“人工复核草稿”，减少手工录入量。下面命令只处理 `IMG_6509` 对应 case，并且只接受 `qualityStatus=auto_usable` 的机器建议：

```bash
python scripts/ocr_100_annotation_draft_labels.py \
  ./ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_merged.json \
  --case-id real-piping_table_profile-002 \
  --only-auto-usable \
  --output ./ocr_eval/reports/scan_annotation_pack/draft_labeled_img6509_tasks.json

python scripts/ocr_annotation_readiness.py \
  ./ocr_eval/reports/scan_annotation_pack/draft_labeled_img6509_tasks.json \
  --output ./ocr_eval/reports/scan_annotation_pack/draft_labeled_img6509_readiness.json \
  --markdown-output ./ocr_eval/reports/scan_annotation_pack/draft_labeled_img6509_readiness.md
```

`ocr_100_annotation_draft_labels.py` 会把 `suggestedExpected` 复制到 `labeledExpected`，同时标记 `machineDraftLabel` 和 `review.source=machine_suggestion_draft`，状态保持为 `needs_human_review`。这种草稿不会被计入人工金标，也不能通过 `ready_for_eval`；人工必须校对字段值、表格、印章和 bbox，删除 `machine_prelabel`，填写真实 `labeler/reviewer` 后才可进入评估。

人工完成逐项校对后，用 finalize 工具做最后门禁。该工具默认拒绝机器草稿；只有明确传入 `--confirm-human-reviewed`，并填写不同的 `--labeler` / `--reviewer`，才会移除 `machineDraftLabel`、写入 `review.source=human_review` 并尝试进入 `ready_for_eval`：

```bash
python scripts/ocr_100_annotation_finalize_labels.py \
  ./ocr_eval/reports/scan_annotation_pack/draft_labeled_img6509_tasks.json \
  --case-id real-piping_table_profile-002 \
  --labeler "标注员A" \
  --reviewer "复核员B" \
  --comment "人工已核对字段、表格、印章和证据框" \
  --confirm-human-reviewed \
  --output ./ocr_eval/reports/scan_annotation_pack/labeled_img6509_tasks.json \
  --report-output ./ocr_eval/reports/scan_annotation_pack/finalize_img6509_report.json
```

如果未传 `--confirm-human-reviewed`，工具会生成失败报告并保持 `outputWritten=false`，用于证明该 case 仍停留在人工复核阶段。若校对后仍存在空值、零面积 bbox、重复字段、缺少表格/印章证据或标注员/复核人相同，finalize 同样会失败。

`prelabelled_tasks.json` 里的 `suggestedExpected` 只是机器建议，不能直接作为金标。每条任务必须由人工写入或确认 `labeledExpected`，再由第二个人或 FDE 复核进入 `ready_for_eval`。

#### 7.1.2 导入任务到 FDE 后台

启动后端和前端，使用 `fde` 账号登录：

```bash
cd backend
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

cd ../frontend
pnpm vite --mode live --host 127.0.0.1 --port 4100
```

登录并取得 token：

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"fde","password":"fde"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["data"]["token"])')
```

如果生产环境关闭了 demo users，应把密码替换为 `create_roles.py` 或运维创建 FDE 账号时设置的真实密码。

把 annotation pack 导入 FDE：

```bash
python - <<'PY' > /tmp/aicheck_ocr_annotation_import_payload.json
import json
from pathlib import Path

path = Path("ocr_eval/reports/scan_annotation_pack/prelabelled_tasks.json")
payload = json.loads(path.read_text(encoding="utf-8"))
print(json.dumps({"tasks": payload["tasks"]}, ensure_ascii=False))
PY

curl -X POST http://127.0.0.1:8000/api/fde/ocr-annotation/import-pack \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: import-scan-annotation-pack-001' \
  -d @/tmp/aicheck_ocr_annotation_import_payload.json
```

如果只是本地验证工作台能力，可以在 FDE 页面点击“导入示例”；这只生成演示任务，不能用于 OCR 100 生产认证。

#### 7.1.3 在 FDE 页面手动标注

入口：

```text
http://127.0.0.1:4100/#/fde/ocr-quality
```

在“交付治理 / OCR 质量 / 人工标注门禁”区域：

1. 查看“样本、已人工标注、可评估、完成率”和阻断项。
2. 在任务表点击“编辑”打开 OCR 人工标注工作台。
3. 左侧显示预览图和 SVG 叠框；如果预览文件不存在，会显示坐标网格画布，仍可按像素坐标打标。
4. 右侧选择标注类型：
   - `字段`：填写稳定 `fieldCode` 和字段值，例如 `pipe_no` / `PL8301`。
   - `表格`：填写 `businessSchema`，例如 `piping_characteristic_table_v1`，并确认 `minRows/minColumns`。
   - `印章`：填写 `sealType` 或 `nameContains`，例如 `company_official_seal` / `设计院`。
5. 输入 `pageNo`、`x1`、`y1`、`x2`、`y2`，点击“添加框”。
6. 对误加的字段、表格或印章点击“删除”。
7. 点击“保存草稿”。此时任务状态通常为 `labeled`，仍会被 `review_required` 阻断，不能进入评估集。
8. 标注员和复核人必须不同。复核人检查值、bbox、页码和场景后，点击“二审通过”。
9. 二审后任务进入 `ready_for_eval`；如果仍有阻断项，继续按错误码修正。

bbox 必须使用源图片像素坐标，格式为：

```json
{
  "bbox": [x1, y1, x2, y2],
  "pageNo": 1
}
```

约束：

- `x2 > x1` 且 `y2 > y1`，否则视为零面积框。
- bbox 不能超出 `pageDimensions`。
- 多页样本必须填写 `pageNo`。
- 字段值不能留空，不能保留 `replace-with-*` 占位符。
- 同一页不要重复提交相同字段、表格或印章标签。
- 表格 `minRows/minColumns` 必须是正整数。
- 印章至少需要 `sealType` 或 `nameContains` 之一。

#### 7.1.4 标注门禁和常见阻断项

查看整体门禁：

```bash
curl -X POST http://127.0.0.1:8000/api/fde/ocr-annotation/readiness \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ocr-annotation-readiness-001' \
  -d '{}'
```

常见阻断项：

| 阻断项 | 含义 | 修复方式 |
| --- | --- | --- |
| `missing_human_label` | 没有人工 `labeledExpected` | 进入 FDE 工作台编辑并保存草稿。 |
| `machine_suggestion_not_confirmed` | 只有机器 `suggestedExpected` | 人工校对后保存为 `labeledExpected`。 |
| `machine_draft_not_human_confirmed` | `labeledExpected` 是机器草稿，不是人工金标 | 人工逐项校对并改成真实标注员，再由不同复核人二审。 |
| `review_required` | 已标注但未二审 | 由不同复核人二审通过。 |
| `review_labeler_missing` / `review_reviewer_missing` | 缺少标注员或复核人 | 填写标注员和复核人。 |
| `reviewer_equals_labeler` | 标注员和复核人相同 | 换不同复核人。 |
| `placeholder_labels` | 仍有 `replace-with-*` 占位 | 替换为真实字段/表格/印章标签。 |
| `zero_area_bbox` | bbox 为 `[0,0,0,0]` 或无面积 | 重新画正面积框。 |
| `fields_evidence_missing` / `tables_evidence_missing` / `seals_evidence_missing` | 缺少证据框或 polygon | 为对应对象补 bbox/polygon。 |
| `OCR_ANNOTATION_BBOX_OUT_OF_BOUNDS` | bbox 超出页面尺寸 | 按源图像坐标修正框。 |
| `OCR_ANNOTATION_DUPLICATE_FIELD` / `OCR_ANNOTATION_DUPLICATE_TABLE` / `OCR_ANNOTATION_DUPLICATE_SEAL` | 重复标注 | 删除重复项。 |
| `OCR_ANNOTATION_FIELD_VALUE_EMPTY` | 字段值为空 | 补真实值。 |
| `OCR_ANNOTATION_TABLE_MIN_INVALID` | 表格最小行列无效 | 设置正整数。 |

#### 7.1.5 导出为 release eval set

FDE 页面用于保存和二审任务；批量生成正式 release eval set 仍建议使用 CLI，以便输出完整报告和可追溯文件。完成标注后，先从 FDE API 拉回当前标注任务：

```bash
mkdir -p ./ocr_eval/reports/scan_annotation_pack

curl -s http://127.0.0.1:8000/api/fde/ocr-annotation/tasks?pageSize=100 \
  -H "Authorization: Bearer ${TOKEN}" \
  > ./ocr_eval/reports/fde_ocr_annotation_tasks_response.json

python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path("./ocr_eval/reports/fde_ocr_annotation_tasks_response.json").read_text(encoding="utf-8"))
tasks = payload["data"]["page"]["items"]
Path("./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json").write_text(
    json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
PY
```

然后运行：

```bash
python scripts/ocr_annotation_readiness.py ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --strict \
  --output ./ocr_eval/reports/scan_annotation_readiness.json \
  --markdown-output ./ocr_eval/reports/scan_annotation_readiness.md

python scripts/ocr_100_annotation_finalize_labels.py \
  ./ocr_eval/reports/scan_annotation_pack/labeled_tasks.json \
  --labeler "标注员A" \
  --reviewer "复核员B" \
  --confirm-human-reviewed \
  --output ./ocr_eval/reports/scan_annotation_pack/ready_labeled_tasks.json \
  --report-output ./ocr_eval/reports/scan_annotation_finalize_report.json

python scripts/ocr_100_annotation_export.py ./ocr_eval/reports/scan_annotation_pack/ready_labeled_tasks.json \
  --output ./ocr_eval/reports/scan_labeled_release_set.json \
  --report-output ./ocr_eval/reports/scan_annotation_export_report.json

python scripts/ocr_eval_set.py ./ocr_eval/reports/scan_labeled_release_set.json \
  --strict-100 \
  --summary-output ./ocr_eval/reports/scan_labeled_release_summary.json
```

生产认证继续使用 `ocr_100_corpus.py` 合并 100-case release corpus。任何 `bootstrapGenerated=true`、`fixtureDerived=true`、未二审、占位标签、零面积 bbox 或证据缺失样本都不能进入 OCR 100 生产认证。

默认 100-case 分布为：管道特性表 12、质量证明书 10、NDT RT 10、NDT UT 8、施工记录 10、焊接记录 10、资质/校验证书 8、印章文字 8、OCR 片段融合印章 8、证据坐标 8、质量门禁 8。报告中的 `scenarioTargetGaps` 是下一轮真实样本采集清单。
`--bootstrap-to-targets` 只用于从现有模板生成 100-case 采集骨架，会把生成样本标记为 `bootstrapGenerated=true`，跨场景派生样本还会标记 `fixtureDerived=true` 和 `collectionStatus=needs_real_sample_replacement`；它可以帮助 FDE 分配采集任务，但不能替代真实样本验收。
`ocr_100_scorecard.py` 会把任何 `bootstrapGenerated` 或 `fixtureDerived` case 作为阻断项，即使该骨架的合成指标为满分也不会给出生产 100 分认证。
`ocr_public_benchmark.py` 用于登记公开 foundation benchmark：DocLayNet 测 layout/bbox，PubTabNet 测表格 HTML/结构，ICDAR 2019 cTDaR 测表格检测。公开集报告会标记 `foundationBenchmark=true` 和 `productionCertificationEligible=false`，只能用于验证基础 OCR/版面/表格能力，不会提升 AIcheck OCR 100 生产认证分数。公开数据集应下载到 `backend/ocr_eval/public_datasets/` 这类本地忽略目录，报告写入 `backend/ocr_eval/public_reports/`。

评估集 case 可以内嵌 `result`，也可以用 `resultPath` 指向已保存的 OCR JSON；需要真实跑本地 OCR 时增加 `--run-ocr` 并提供 `source`，建议同时使用 `--auto-discover-runtime` 自动套用本地 OCR Python/模型目录，并在刷新旧缓存时加 `--disable-result-cache`。相对 `resultPath`，以及启用 `--run-ocr` 时的相对 `source`，都按评估集文件所在目录解析，便于把 release set 和 fixtures 一起迁移。报告会输出字段召回、字段值准确、字段/表格/印章证据召回、字段/表格/印章 bbox IoU 命中率、表格命中、印章命中、质量状态、质量原因召回，以及可选的 `quality.evidenceCompleteness` 上下限匹配。评估集顶层 `thresholds` 支持 overall 门槛和 `piping_table_profile`、`seal_text_profile`、`fragment_seal_profile`、`quality_gate_profile`、`field_confidence_profile`、`evidence_profile` 等场景门槛，防止综合均分掩盖某个 OCR 场景低分。`fragment_seal_profile` 专门覆盖视觉印章候选由 OCR 片段融合成正式章名的回归门禁，会校验 `sourceEngine=fragment_seal_text_fusion`、`fragment_seal_text` 质量标记、章内字段和 bbox 证据。`evidence_profile` 专门覆盖核心字段、必需表格、正式印章缺少 bbox/polygon 的证据化门禁。完整 JSON/Markdown 报告还包含 `findingCounts` 和 `details.fields/tables/seals/quality`，用于 FDE 按失败原因定位值错误、漏识别、证据缺失或坐标偏移。`POST /api/fde/ocr-evaluation-runs` 可接收同样的 `cases/thresholds`，并在原有 proxy metrics 外返回同结构 `evaluationSummary`、`evaluationReport.findingCounts`、`scenarioMetrics.findingCounts` 和 `caseDiagnostics`，FDE 后台会优先展示失败原因聚合。`GET /api/fde/ocr-quality` 的 `fieldLevel` 汇总业务落地字段和 parse result 字段候选，包括字段总量、低置信度、冲突字段、缺证据字段、必需字段缺失、字段代码分布、字段来源和质量标记；`evidenceLevel` 汇总平均证据完整度、缺证据总数和 field/table/seal 分布，FDE 后台用它区分“识别值低置信度”和“识别值没有可追溯证据”；`tableLevel` 拆分正式表格、启发表格 fallback、待复核表格、必需表格缺失、业务行和表格来源分布；`sealLevel` 进一步拆分印章总数、可读章、`fragment_seal_text` 片段融合章、视觉候选待复核、期望章类型命中/缺失和章源/章类型分布，避免把成功融合标记误判为故障。
`GET /api/fde/ocr-quality` 还会返回 `ocr100Scorecard`，和 CLI 使用同一个 `build_ocr_100_scorecard` builder，将 runtime、evaluation、sample probes、observability 四段分数和阻断项直接展示在 FDE OCR 质量页。它只用于“本地 OCR 100 分生产就绪”判定，不会因为单个小 fixture 或 bootstrap case 满分而误报通过。
- `--summary-output` 会写出适合 CI/FDE 读取的小摘要，包含 `ok`、`summary`、`metrics`、`findingCounts`、`thresholdFailures`、`scenarioMetrics` 和 `failedCases`；完整证据仍看 `--output` 或 `--markdown-output`。
- `--output`、`--summary-output` 与 `--markdown-output` 会自动创建父目录，首次运行不需要预先创建 `ocr_eval/reports`。
- 如果改为企业自维护 OCR 镜像，应保留 `/internal/ocr/parse` 合同和 `/healthz` 中的 `pipelineAvailable/placeholderAllowed` 字段，并继续安装上述 OCR 依赖基线或等价替代。
- OCR 结果会额外返回 `pageQuality`、`imageVariants`、`preprocessStatus`、`quality.status`、`quality.reasons`、`profilePostprocessVersion`、`resultCacheHit` 和 `engineRuns[].variantId/preprocessChain/purpose/variantCacheHit`。`paddle_ocr_subprocess` 还会返回 `workerMode=persistent|oneshot`，用于 FDE 判断是否复用了常驻 OCR worker。这些字段用于 FDE 质量分析、预处理候选选优和重复解析性能治理；旧的 `fragments/fields/tables/seals/diagnostics` 合同保持不变。
- 结果缓存 key 已包含 `profilePostprocessVersion`，Profile 行映射或字段抽取升级后会自动绕开旧缓存，不会把旧版 `businessRows` 当成新结果。
- `preprocessStatus.missingVariants` 非空时，优先排查 OCR 镜像是否安装 `opencv-python-headless`，或是否设置了指向本地 OCR Python 的 `AICHECK_OCR_SUBPROCESS_PYTHON`。服务会同时写入 `PREPROCESS_VARIANT_GENERATION_UNAVAILABLE`，避免把“预处理依赖缺失”误判成 Profile 规则或模型准确率问题。
- 对同时包含表格和印章的 Profile，候选图上限会优先保留 `table_line_enhanced` 与 `seal_color_mask`，再加入灰度/纠偏类文本候选，防止印章证据被表格优化挤出候选集。
- 对必需印章类 Profile，视觉红/蓝章候选只能证明“疑似有章”，不能单独证明章名已识别；如果章区 OCR fragments 已读到可靠文字，例如许可范围或 `TS...` 证号，融合层会标记 `fragment_seal_text` 并可满足印章门禁。若既没有 fragment seal text，也未命中 PaddleX/agentdesign 正式章名 OCR，质量门禁应返回 `needs_human_review` 和 `SEAL_TEXT_LOW_CONFIDENCE`；若可读正式章类型不匹配 Profile 的 `sealRules.expectedSealTypes`，应返回 `EXPECTED_SEAL_TYPE_MISSING`，样张门禁使用 `--require-seal-type` 和 `--max-missing-expected-seal-types 0` 阻断发布。
- 如需本地高精度章名 OCR，可设置 `AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR=true`。该引擎会在 `AICHECK_OCR_SUBPROCESS_PYTHON` 中调用 agentdesign 的 `seal_ocr.recognize_document`，输出 `organization_name`、`seal_type`、`valid_until`、`license_scope` 等正式字段；它默认关闭，因为 accuracy-first 印章管线在大图上可能增加约 1 分钟耗时。超时或失败会写 `AGENTDESIGN_SEAL_OCR_TIMEOUT/FAILED` 诊断，并继续使用视觉印章候选兜底。
- 对必需表格类 Profile，基于 OCR 坐标的启发式表格重建只能作为 fallback 候选；未命中 PP-StructureV3 等正式表格结构结果时，质量门禁应返回 `TABLE_HEURISTIC_REVIEW_REQUIRED`。
- PP-StructureV3 返回的表格 HTML 会被归一化为 `cells/rows/columns/normalizedRows`，并支持基础 `rowspan/colspan`。正式表格模型启用后的验收应检查 `normalizedRows` 是否覆盖关键业务列。
- `piping_characteristic_list_v1` 会把管道特性表行额外映射成 `businessRows`，稳定字段包括 `pipeNo`、`nominalDiameter`、`mediumName`、`designPressure`、`weldDetectionMethod` 等；规则和 AI 复核应优先使用这些字段，而不是直接依赖原始 OCR 表头。空白管道代号续行会继承上一条 `pipeNo`，并标记 `isContinuation=true`，下游规则应把它当作分支/续行处理。
- 生产应设置 `AICHECK_OCR_ALLOW_PLACEHOLDER=false`。此时 OCR 管线不可用会写入失败任务，前端任务中心可重试。
- `verify_deployment.py --strict-production` 会要求 OCR 健康检查返回 `pipelineAvailable=true`、`placeholderAllowed=false`，并要求 `/internal/ocr/doctor` 没有 failed checks。
- `POST /internal/ocr/parse` 缺少 `storageKey` 时必须返回 `VALIDATION_ERROR` 业务包；源文件缺失时返回 `status=failed` 结构化结果，不应暴露 500。
- 本地联调可临时设置 `AICHECK_OCR_ALLOW_PLACEHOLDER=true`，用于没有 PaddleOCR 依赖时验证上传、任务和状态回写流程。

任务中心行为：

- `POST /api/knowledge/tasks/{taskId}/retry` 会根据 `taskType` 重新投递 OCR、切片、向量化或重建索引子任务，并写入 `attempts`、`lastDispatch` 和 `logs`。
- `POST /api/knowledge/tasks/{taskId}/cancel` 会把任务标记为 `已取消`；worker 开始执行前会检查取消状态，避免继续处理已取消任务。
- retry 支持 `Idempotency-Key`，同一 task 和同一 key 重放同一次 retry 结果。
- OCR 服务不可用、源文件缺失、切片/向量化目标缺失时，worker 会把对应 `knowledge_tasks.status` 写为 `失败`，并写入可前端展示的脱敏 `errorMessage` 和任务日志。

## 8. LiteLLM 部署说明

Compose 中的 LiteLLM 服务：

```yaml
litellm-service:
  image: ghcr.io/berriai/litellm:main-latest
  command: ["--config", "/app/config/litellm.yaml", "--port", "4000", "--host", "0.0.0.0"]
```

模型别名在 `backend/config/litellm.yaml`：

- `default-chat`
- `review-chat`
- `deepseek-reasoner`
- `compare-fast`
- `embedding-default`

上线前检查：

```bash
curl http://127.0.0.1:4001/health
curl http://127.0.0.1:4001/v1/models \
  -H "Authorization: Bearer ${LITELLM_API_KEY}"
```

`/v1/models` 必须能看到 `default-chat`、`review-chat`、`deepseek-reasoner`、`compare-fast`、`embedding-default` 五个别名；`verify_deployment.py` 会自动检查这些别名。

`api-service` 和 `worker-service` 在 `AICHECK_REQUIRE_AUTH=true`、配置了 `AICHECK_DATABASE_URL` 或 `AICHECK_STRICT_PRODUCTION=true` 任一生产标志开启时，禁止使用内置开发 LiteLLM key；必须显式提供 `LITELLM_API_KEY`。

LiteLLM DB-backed virtual key、预算和限流管理依赖 Prisma query-engine。query-engine 会在容器本机启动 HTTP 健康探针；如果宿主或容器注入了 HTTP proxy 且没有设置 `NO_PROXY/no_proxy`，`/key/generate` 可能返回 `DB not connected` 或启动卡住。Compose 会把 `AICHECK_LITELLM_NO_PROXY` 同时写入 `NO_PROXY` 和 `no_proxy`，默认值为 `127.0.0.1,localhost,::1,postgres`；生产环境可以追加内网域名，但不能删除 `127.0.0.1` 和 `localhost`。

如果 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 或供应商密钥无效：

- AI 复核任务会映射为 `AI_RUN_FAILED`。
- 向量化、模型对比等外部工具错误会映射为 `EXTERNAL_TOOL_FAILED`。
- 返回给前端的 `errorMessage` 只保留业务级失败说明，不应包含 provider 原始错误、`sk-...` 密钥或内部连接细节。
- 业务库保留 `ai_runs`、`llm_compare_runs` 等运行记录，LiteLLM 保存模型调用层日志。
- `/api/llm/compare` 只创建异步 run；真实模型调用由 `llm.compare` worker 执行，前端通过 `GET /api/llm/compare-runs` 查询结果。

## 9. 上线验证

后端 smoke：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/workbench/projects

curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"${AICHECK_BOOTSTRAP_PASSWORD_ADMIN}\"}"

for account in inspection contractor ndt owner admin fde; do
  password_var="AICHECK_BOOTSTRAP_PASSWORD_${account^^}"
  curl -s -X POST http://127.0.0.1:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${account}\",\"password\":\"${!password_var}\"}" | jq '.data.user.role, .data.user.defaultPath'
done
```

部署验收脚本：

```bash
cd backend
source .venv/bin/activate

# 离线配置验收，不依赖 Docker daemon
python scripts/validate_deployment_config.py

# CI/上线前严格模式：默认弱密钥、空 provider key 等会失败
python scripts/validate_deployment_config.py --strict-production

python scripts/verify_deployment.py \
  --api-base http://127.0.0.1:8000 \
  --ocr-base http://127.0.0.1:8010 \
  --litellm-base http://127.0.0.1:4001 \
  --litellm-api-key "$LITELLM_API_KEY" \
  --strict-production

# 指定测试项目执行写入探针：创建上传会话、实际 PUT signed URL、完成上传、
# 校验文档 preview/download signed GET、确认 OCR task、创建导出任务
python scripts/verify_deployment.py \
  --strict-production \
  --write-probes \
  --project-id P-2026-HDCP-001

# OCR 真实对象解析验收：会上传一份包含文字的 PDF，再让 OCR 服务从 MinIO 读取并解析
python scripts/verify_deployment.py \
  --strict-production \
  --write-probes \
  --ocr-object-probe \
  --project-id P-2026-HDCP-001

# ReviewRun 编排验收：创建 AI 复核，验证 Temporal/LangGraph 业务视图、图节点、时间线、人工确认和 FDE 不可变重跑
python scripts/verify_deployment.py \
  --strict-production \
  --review-run-probe \
  --review-run-wait-seconds 20 \
  --roles admin,inspection,contractor,ndt,owner,fde \
  --project-id P-2026-HDCP-001

# LiteLLM DB-backed 管理面验收：创建并删除临时 virtual key，确认预算和限流可用
python scripts/verify_deployment.py \
  --strict-production \
  --litellm-management-probes \
  --litellm-api-key "$LITELLM_API_KEY"

# 供应商级模型验收：会消耗少量模型额度，确认 default-chat 与 embedding-default 能真实调用 provider
python scripts/verify_deployment.py \
  --strict-production \
  --litellm-provider-probes \
  --litellm-api-key "$LITELLM_API_KEY"

# 机器可读输出，适合 CI 或上线流水线
python scripts/verify_deployment.py --strict-production --json

# 生成上线验收证据包：默认跑离线配置、API 幂等覆盖、前端合同和 mutation header 审计
python scripts/deployment_report.py \
  --strict-production \
  --output-dir ./deployment-reports/latest

# 生成包含目标环境探针的证据包；可按需加 OCR、LiteLLM 管理面和 provider 实调探针
python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --roles admin,inspection,contractor,ndt,owner,fde \
  --write-probes \
  --ocr-object-probe \
  --review-run-probe \
  --review-run-wait-seconds 20 \
  --litellm-management-probes \
  --litellm-provider-probes \
  --litellm-api-key "$LITELLM_API_KEY" \
  --output-dir ./deployment-reports/latest
```

`validate_deployment_config.py` 会静态解析 `Dockerfile`、`Dockerfile.ocr`、`requirements-ocr.txt`、`docker-compose.yml` 和 `config/litellm.yaml`，检查镜像基础契约、非 root 运行用户、API/OCR 端口、OCR PaddleOCR 基线依赖、服务拓扑、依赖、healthcheck、端口映射、Celery 队列、统一 PostgreSQL 服务、OCR artifact 只读挂载、持久化 volume、关键环境变量、LiteLLM 五个模型别名、数据库配置和 Prisma 本机代理旁路。它不需要 Docker，可在没有 Docker daemon 的 CI 环境中先挡住配置错误。

`check_96_preflight.py` 用于 live probes 之前的宿主机预检，会检查 Docker CLI/Compose、`backend/.env`、必需密钥、生产开关、`AICHECK_AGENTDESIGN_HOST_PATH`、OCR 离线模型目录和默认端口占用。OCR 模型检查同时支持标准 bundle 布局和 PaddleX `official_models` 扁平缓存布局；容器路径 `/models/...` 会映射回 `AICHECK_OCR_MODELS_HOST_PATH`，`/opt/agentdesign/...` 会映射回 `AICHECK_AGENTDESIGN_HOST_PATH`。文本输出和 `--json` 输出都会在失败项上附带 `remediation`，用于明确下一步安装 Docker、复制 `.env.example`、替换占位密钥或修正本地路径。

`backend/tests/test_check_96_preflight.py` 会校验 `backend/.env.example` 覆盖所有预检必需变量和生产开关；如果预检脚本新增必需变量但模板漏配，测试会直接失败。

`verify_deployment.py` 默认只做健康检查、登录、PostgreSQL transaction 探针、只读查询、OCR readyz、OCR runtime doctor、OCR parse 合同探测、OCR bad request 合同探测、LiteLLM 模型别名检查，以及应返回 `FORBIDDEN` 的身份伪造/动作越权/读范围检查，不会创建业务数据，也不会消耗模型额度。开启 `--litellm-management-probes` 后会创建并删除一个临时 LiteLLM virtual key，验证 PostgreSQL-backed key、预算、RPM 和 TPM 管理能力。开启 `--litellm-provider-probes` 后会通过 LiteLLM 的 OpenAI-compatible API 实际调用 `default-chat` 和 `embedding-default`，证明网关、virtual key、provider key、模型别名和供应商连通性可用。开启 `--write-probes` 后会在 `--project-id` 指定项目下创建一条验证用上传会话，使用 returned HTTP/HTTPS signed URL 实际 PUT 一个包含文字的 PDF，再执行 upload complete，校验新文档的 preview/download signed GET 可以实际读取对象，确认 OCR task 创建，并创建/读取导出任务，用于证明 MinIO signed PUT、文档 signed GET、upload complete、OCR task 创建和 export task 查询闭环。开启 `--ocr-object-probe` 时，verifier 会读取新文档当前版本 `storageKey` 并调用 `ocr-service /internal/ocr/parse`，要求 OCR 对刚上传的 MinIO 对象返回 `status=success`。开启 `--review-run-probe` 时，verifier 会使用监检员创建 AI 复核 ReviewRun，验证 `/api/review-runs/{id}`、`/graph`、`/timeline`、`/human-decision`，再用 FDE 角色验证 `/api/fde/review-runs/{id}`、diagnostic replay、Graph artifact summary 和 orchestration `scorecard`；严格生产模式要求 dispatch mode 为 `temporal`、FDE scorecard 为 `100/100` 且 `ok=true`，并会在 `--review-run-wait-seconds` 窗口内等待图节点至少进入 running/succeeded/failed/skipped 或 run 状态离开 queued，用于发现 Temporal worker 未消费任务的故障，因此该探针必须配合 `--roles admin,inspection,contractor,ndt,owner,fde`。严格生产模式还会要求 PostgreSQL 已启用并通过实际 transaction 探针，校验 OCR 使用真实 pipeline 而不是 placeholder，OCR runtime doctor 没有 failed checks，并要求 signed PUT/GET URL 是 HTTP/HTTPS。

`deployment_report.py` 会把离线配置验收、API mutation 幂等覆盖、前端路由合同、前端 mutation header 覆盖和可选 live deployment probes 汇总成 `aicheck-deployment-report-v1` 结构，同时输出 Markdown 表格，适合随上线单归档。默认不访问目标环境；加 `--include-live` 后复用 `verify_deployment.py` 的所有目标环境探针。

98+ 辅助审计包含以下门禁：

- `api.response-envelope`：直接调用后端 `ok()/fail()` helper，确认成功 `{ code: 0, data, operationId, serverTime }`、失败 `{ code, message, data.reason, operationId, serverTime }`，并阻止旧版 `ok: true/false` 响应包回归。
- `auth.role-contract`：检查生产角色 `admin/inspection/contractor/ndt/owner/fde` 的默认面板路径、动作矩阵、`owner` 只读约束、FDE 禁止业务审批约束、`create_roles.py` 覆盖、PBKDF2 密码哈希和项目成员授权规划。
- `api.mutation-idempotency`：扫描 FastAPI mutating routes，业务写接口必须直接调用 `idempotent()` 或代理到已幂等的内部函数；公开登录和只读预览型 POST 会被单独列为豁免。
- `api.action-coverage`：扫描所有非公开 mutating routes，确认后端能根据路径自动推断 `ActionCode`，避免新增写接口绕过角色动作矩阵。
- `postgres.index-contract`：扫描 `backend/libs/db/indexes.py`，确认所有持久化 collection 都有索引声明，并检查项目节点、文件版本、知识任务、证据、审计、幂等键和成员授权的关键复合/唯一索引。
- `storage.bucket-contract`：检查 MinIO bucket 合同必须包含且只包含 `documents`、`previews`、`exports`、`ocr-artifacts`，并确认 `ObjectStorage` 暴露 signed PUT、signed GET、字节写入、临时下载和 `minio://` URL 解析能力；同时扫描 repository 上传、下载、导出调用点，防止业务链路绕过对象存储抽象。
- `ocr.service-contract`：检查 `ocr-service` 的 `/healthz` 必须暴露 `pipelineAvailable`、`pipelineBackend`、`placeholderAllowed`，`/internal/ocr/doctor` 必须返回 runtime doctor，`/internal/ocr/parse` 缺少 `storageKey` 时必须返回 `VALIDATION_ERROR`，并验证 OCR 成功/失败结果都包含 `storageKey`、`fileName`、`status`、`fragments`、`fields`、`seals`、`diagnostics`。
- `ocr.evaluation-contract`：检查共享 evaluator、compact summary、`--strict-100`、`ocr_100_thresholds()`、`ocr_100_scorecard.py` 和 release fixture。普通 fixture 只证明合同可用；100 分验收必须另跑 `ocr_100_scorecard.py`，并满足 100-case、必需场景、本地引擎和真实样张门禁。
- `litellm.client-contract`：用无网络 `MockTransport` 验证业务客户端会以 OpenAI-compatible `/v1/chat/completions`、`/v1/embeddings` 调用 LiteLLM，默认模型别名为 `default-chat`、`embedding-default`，请求必须携带 Bearer master key；同时检查生产模式禁用开发 key、provider 错误脱敏，以及 worker 中 `AI recheck`、向量化、模型对比的模型别名和错误码映射。
- `knowledge-rule.contract`：静态检查知识源、知识文件、知识条款、PageIndex 树节点、知识任务、规则版本、检索测试、知识配置等 API 路由，确认 `knowledge_*`、`rule_versions`、`retrieval_traces`、`rule_check_results` 集合和索引存在，并检查 ReviewRun 中 `RuleCheckResult.linkedClauseIds`、`RetrievalTrace.selectedClauses`、`pageIndexTree`、`queryRouter`、`selectedRoute`、`routerSignals`、精确条款查询、Hybrid RAG、PageIndex 条件路由、Schema/证据/依据/质量门禁校验字段。`GET /api/knowledge/overview` 还会返回 `scorecard`，按 `source-index`、`rule-clause`、`retrieval-router`、`evaluation-governance` 四段给出 100 分知识依据链生产就绪度，并内置 exact/hybrid/pageindex 三路检索探针、retrieval recall、wrong reference rate 和持久化 RetrievalTrace 阻断项，防止知识库、规则库和审查依据链退化成不可审计占位。
- `review-orchestration.contract`：静态检查 ReviewRun 业务端/FDE 端路由、Temporal worker、Workflow signal/query、LangGraph `StateGraph` 与 PostgreSQL checkpointer、ReviewRun 状态集合/索引、工具白名单/黑名单、LiteLLM finding 生成、人工确认、FDE child replay 不可变合同，以及 FDE detail 返回的 workflow/graph/evidence/governance 编排就绪 scorecard。
- `feedback.hr-contract`：静态检查人工确认会创建 `accepted/edited/rejected_false_positive` 结构化反馈，反馈保留 `originalAiOutput/correctedOutput/inputDocumentVersionIds`，FDE triage 会把 `approved_for_eval` 或 `canUseForEval=true` 的反馈幂等提升为 `evaluation_cases`，FDE 评估运行会生成 `evaluation_case_results`，对带 `expectedClauseIds` 的样本执行 Query Router 检索评估并写入 `retrieval_traces`，按 case pass rate、finding recall、evidence coverage、retrieval recall 和 wrong reference rate 计算门禁。
- `export.artifact-contract`：实际构造导出 ZIP/PDF 字节，解析 ZIP 确认 `manifest.json`、`task.json`、`project.json`、`reports.json`、`documents.json`、`archive_items.json`、`evidence_links.json`、`README.txt` 全部存在，manifest 使用 `aicheck-export-v1`，PDF 产物必须带 `%PDF` 文件头和 `AIcheck Export Report` 摘要。
- `worker.task-contract`：扫描 Celery task routes、worker 任务对象和 `task_dispatcher`，确认 `ocr.parse_document`、`ocr.recognize_seals`、`knowledge.slice`、`knowledge.embed`、`inspection.ai_recheck`、`llm.compare`、`export.package` 均有队列路由、重试配置和调度入口。
- `frontend.mutation-headers`：扫描 `frontend/src/api/aicheck/index.ts` 的 `request.post/put/patch/delete` 调用，真实 mutation 必须使用 `mutationHeaders()` 自动携带 `Idempotency-Key`，更新类操作可同时透传 `If-Match`。
- `frontend.mutation-helper`：检查 `mutationHeaders()` 本身必须生成 `Idempotency-Key`，并在传入 `etag` 时写入 `If-Match`，防止前端并发控制 helper 被误删或降级。
- `fde.governance-contract`：静态检查并由 `tests/test_fde_console.py` 覆盖 FDE 单角色登录、脱敏 AI Run、Trace、child run 重跑、原文访问授权、反馈归因、评估报告、发布门禁、高风险发布非 FDE 审批、先 shadow 后 canary、业务包 validate-all 100 分可迁移 scorecard、业务包安装演练、数据导出、事故 RCA 和禁止业务审批。
- `check_96_preflight.py`：在 live probes 前检查 Docker/Compose、`.env`、placeholder、内部密钥强度、生产 flag、agentdesign OCR 基线文件和默认端口冲突；任何失败都会阻止 `probe.command-ready`。

前后端合同审计：

```bash
cd backend
source .venv/bin/activate
python scripts/audit_frontend_contract.py
```

`audit_frontend_contract.py` 会静态解析 `frontend/src/api/aicheck` 与 `frontend/src/api/login` 中的请求路径，并与 FastAPI 路由做动态参数匹配；缺任一路由时返回非 0 退出码。

前端 smoke：

```bash
cd frontend
AICHECK_BASE_URL=https://aicheck.example.com pnpm playwright test e2e/aicheck-smoke.spec.ts --reporter=list
```

本地联调可使用 FastAPI + Vite live 模式：

```bash
# 终端 1
cd backend
source .venv/bin/activate
AICHECK_BOOTSTRAP_LOCAL_ROLES=true \
AICHECK_BOOTSTRAP_PASSWORD_ADMIN='Local!2026-SystemZ' \
AICHECK_BOOTSTRAP_PASSWORD_INSPECTION='Local!2026-InspectZ' \
AICHECK_BOOTSTRAP_PASSWORD_CONTRACTOR='Local!2026-BuildZ' \
AICHECK_BOOTSTRAP_PASSWORD_NDT='Local!2026-TestZ' \
AICHECK_BOOTSTRAP_PASSWORD_OWNER='Local!2026-ViewZ' \
AICHECK_BOOTSTRAP_PASSWORD_FDE='Local!2026-FdeZ' \
AICHECK_BOOTSTRAP_LOCAL_ROLE_LIST='admin,inspection,contractor,ndt,owner,fde' \
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# 终端 2
cd frontend
pnpm vite --mode live --host 127.0.0.1 --port 4100

# 终端 3
cd frontend
AICHECK_BASE_URL=http://127.0.0.1:4100 pnpm playwright test e2e/aicheck-smoke.spec.ts --reporter=list
```

本地开发态关闭方式：

```bash
# 优先在运行 uvicorn / vite 的终端按 Ctrl-C。

# 如果终端已丢失，可按端口查找并结束本地开发进程。
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:4100 -sTCP:LISTEN
kill <pid>

# Docker Compose 栈关闭。
cd backend
docker compose down
```

如果只想暂时关闭前端，停止 `pnpm vite` 对应终端或结束 `4100`/实际 Vite 端口进程即可；后端 `8000` 和数据库不会因此停止。当前本地 live smoke 基线为 51 条通过，覆盖四类工作台、管理后台、知识库、NDT、报告导出/归档、联调清单 0 blocker、错误码恢复和主要写回流程。

关键手工验证：

- 六类角色登录后能进入各自默认面板；业务角色访问 `/admin/overview` 会回退到自己的工作台，FDE 登录后进入 `/fde/dashboard`。
- 项目列表、项目树、节点包、报告、归档页面能正常加载。
- 管理后台项目成员授权后，业务角色节点范围外 mutation 返回 `FORBIDDEN`。
- 生产鉴权开启后，业务角色读取项目成员范围外的节点包、文件详情或报告详情返回 `FORBIDDEN`。
- 生产鉴权开启后，项目树、文件列表、挂载列表、报告列表和归档列表只返回当前用户 `nodeScope` 范围内的数据。
- 生产鉴权开启后，非管理员使用 JWT 登录身份之外的 `X-Role` 或 `X-User-Id` 调用 mutation 返回 `FORBIDDEN`。
- 生产鉴权开启后，业务角色在请求体里提交授权范围外的 `nodeId/nodeIds` 返回 `FORBIDDEN`，例如施工方不能提交 NDT 节点资料，NDT 不能向监检节点导入记录。
- 生产鉴权开启后，业务角色通过 `documentId`、`bindingId`、`reportId` 操作节点范围外资源返回 `FORBIDDEN`；资源与 URL `projectId` 不一致返回 `NOT_FOUND`。
- 生产鉴权开启后，业务角色直接调用未授权写接口会按后端推断的 `ActionCode` 返回 `FORBIDDEN`，例如施工方不能生成报告草稿或发布后台配置。
- 生产鉴权开启后，FDE 直接调用正式业务写接口返回 `FORBIDDEN`；FDE 只能调用 `/api/fde/*` 治理接口，不能保存审查意见、发补正、归档或删除业务文件。
- FDE 查看 AI Run 默认只能看到脱敏内容；`POST /api/fde/access-grants/request` 创建授权申请后，必须由管理员调用 `/api/fde/access-grants/{id}/approve` 才能查看原文。
- FDE 发起评估运行后必须生成 `evaluation_report`；高风险发布缺少通过状态评估报告、Risk Set、回滚方案或非 FDE 审批时必须进入 `blocked_by_gate`，且 canary 申请必须发生在 shadow run 之后。发布单的 `evaluationReportId` 可引用 report `id` 或 `evaluationRunId`，但对应报告 `status` 必须是 `passed`，`failed` 报告不能放行。
- ReviewRun 人工 `accept/edit/reject` 必须生成 `ai_feedback`；FDE 将反馈归因为 `approved_for_eval` 后必须生成或更新一条以 `sourceFeedbackId` 关联的 `evaluation_cases`，且重复归因不能重复创建样本；FDE 离线评估必须生成 `evaluation_case_results`，任一样本缺失 expected finding 或证据门禁失败时报告状态不能是 `passed`。
- FDE 业务包安装/升级/回滚先支持 dry-run，验收通过时写入 `business_pack_installations` 并写审计日志。
- FDE 事故处理必须写 `incident_rca`，数据导出必须写 `data_exports` 并生成水印标识。
- mutation 使用相同 `Idempotency-Key` 和相同请求体会重放同一结果；同 key 不同请求体返回 `IDEMPOTENCY_KEY_CONFLICT`。
- `verify_deployment.py --strict-production` 会调用 `/api/system/postgres-transaction-probe`，确认 PostgreSQL 已连接且能实际开启并提交临时 transaction。
- 提交批次撤回资料时，只能撤回该批次内资料；不存在的批次返回 `NOT_FOUND`，跨批次资料返回 `CONFLICT`，已通过、已锁定或已归档资料返回 `WITHDRAW_LOCKED`。
- 施工方提交补正反馈时必须存在当前节点的待反馈补正单，且反馈资料必须属于该节点；成功后原补正单变为 `已反馈`，节点进入 `复审中`。
- 报告草稿只能从已进入审查链路的节点生成；`待提交`、`需补正`、`退回补正中`、`部分提交`、`AI 预审中` 节点返回 `CONFLICT`。
- 创建 upload session 返回 MinIO signed PUT URL。
- `verify_deployment.py --write-probes --strict-production` 能实际 PUT signed URL，上传完成后文档 `preview-url/download-url` 能返回并读取 HTTP(S) signed GET，`GET /api/knowledge/tasks` 能看到 OCR/切片/向量任务。
- `verify_deployment.py --write-probes --ocr-object-probe --strict-production` 能让 OCR 服务从 MinIO 读取刚上传的 PDF 并返回 `status=success`。
- `POST /internal/ocr/parse` 返回统一 OCR 结构：`status/fragments/fields/diagnostics/storageKey`；源文件缺失时也应返回 `status=failed` 的业务结构，而不是 500。
- 触发 AI 复核后 `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs` 能看到运行记录。
- `verify_deployment.py --strict-production --review-run-probe --review-run-wait-seconds 20 --roles admin,inspection,contractor,ndt,owner,fde` 能创建 ReviewRun，确认 `dispatch.mode=temporal`，等待 Temporal/LangGraph worker 推进图节点，并验证业务端 detail/graph/timeline/human-decision、FDE detail/diagnostic replay 和 FDE orchestration scorecard `100/100` 闭环。
- ReviewRun FDE replay 必须生成 child `reviewRunId` 且保留 `parentReviewRunId`，不能覆盖原始 ReviewRun；图节点必须包含 `nodeKey/status`，时间线必须包含可审计事件。
- LiteLLM `/v1/models` 包含五个业务别名：`default-chat`、`review-chat`、`deepseek-reasoner`、`compare-fast`、`embedding-default`。
- `verify_deployment.py --strict-production --litellm-management-probes` 能创建并删除临时 virtual key，证明 PostgreSQL-backed 预算和限流管理面可用。
- `verify_deployment.py --strict-production --litellm-provider-probes` 能通过 LiteLLM 实际获得 chat completion 和 embedding vector；失败时 verifier 只返回业务级 HTTP/形状错误，不输出 provider 原始密钥或错误正文。
- 报告导出任务从处理中变为可下载。
- 下载导出 zip 后能解出 `manifest.json`，其中 `schemaVersion=aicheck-export-v1`，`counts` 与当前项目报告、资料、归档和证据数量一致；报告 PDF 至少包含任务、项目和报告摘要。

生产 Go/No-Go 判定：

- `python scripts/check_96_preflight.py --strict-production` 必须通过；任何 `fail` 都是 No-Go。
- `python scripts/validate_deployment_config.py --strict-production` 必须通过；Docker/Compose 配置不能依赖人工解释放行。
- 前端必须通过 `pnpm lint`、`pnpm ts:check`、`pnpm build:pro`，且 `VITE_USE_MOCK=false`。
- 后端必须通过 `python -m pytest backend/tests -q`，以及 `python scripts/audit_frontend_contract.py` 缺失 endpoint 为 0。
- `deployment_report.py --strict-production --include-live --write-probes --ocr-object-probe --review-run-probe --litellm-management-probes --litellm-provider-probes` 必须生成全绿证据包。
- `verify_deployment.py --strict-production --roles admin,inspection,contractor,ndt,owner,fde` 必须证明六类角色登录、默认面板、权限边界、PostgreSQL transaction、OCR readyz 和 LiteLLM alias 全部可用。
- `AICHECK_REQUIRE_AUTH=true`、`AICHECK_ENABLE_DEMO_USERS=false`、`AICHECK_OCR_ALLOW_PLACEHOLDER=false`、`AICHECK_OCR_OFFLINE_ONLY=true`、`AICHECK_OCR_DISABLE_NETWORK=true`、`AICHECK_DATABASE_URL`、`AICHECK_REVIEW_ORCHESTRATION=temporal` 必须保持生产值。
- 最近一次完整备份必须覆盖 PostgreSQL、MinIO；若本次上线包含数据结构或 workflow 变更，必须先做一次恢复演练或 staging 恢复验证。
- HTTPS 证书、MinIO signed PUT/GET、CORS、前端静态资源缓存、反代 `client_max_body_size` 和 upload timeout 必须通过真实浏览器上传验证。
- 任一 provider health、ReviewRun Temporal/LangGraph scorecard、FDE governance scorecard、OCR runtime doctor 或 live write probe 失败时，不允许上线。

## 10. 备份与恢复

生产备份必须覆盖四类持久化数据：

- PostgreSQL `aicheck` 数据库：AIcheck 主业务数据、审计日志、任务状态。
- PostgreSQL `litellm` 数据库：模型网关配置、virtual key、预算、调用记录。
- PostgreSQL `workflow` 数据库：Temporal 状态和 LangGraph checkpoint。
- MinIO：原始文件、预览、OCR artifacts、导出包。

建议在低峰期进入短暂停写窗口：暂停前端入口或维护页，停止 `worker-service` 和 `review-worker-service` 消费，再执行备份。备份前先记录当前版本和渲染后的 Compose 配置：

```bash
cd backend
BACKUP_DIR="./backup/$(date +%Y%m%d-%H%M%S)"
mkdir -p "${BACKUP_DIR}/minio"

git rev-parse HEAD > "${BACKUP_DIR}/git-commit.txt"
docker compose config > "${BACKUP_DIR}/docker-compose.rendered.yml"
cp .env "${BACKUP_DIR}/env.secret"      # 该文件包含密钥，只能进入加密备份介质。
chmod 600 "${BACKUP_DIR}/env.secret"
```

进入停写窗口：

```bash
docker compose stop worker-service review-worker-service
```

PostgreSQL 数据库备份：

```bash
docker compose exec -T postgres pg_dump \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${AICHECK_POSTGRES_DB:-aicheck}" \
  -Fc > "${BACKUP_DIR}/aicheck-postgres.dump"

docker compose exec -T postgres pg_dump \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${LITELLM_POSTGRES_DB:-litellm}" \
  -Fc > "${BACKUP_DIR}/litellm-db.dump"

docker compose exec -T postgres pg_dump \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${WORKFLOW_POSTGRES_DB:-workflow}" \
  -Fc > "${BACKUP_DIR}/workflow-db.dump"
```

MinIO 数据备份。建议运维机安装 MinIO Client `mc`，从外部 signed URL 域名或内网 endpoint mirror 全量对象：

```bash
if [ "${AICHECK_MINIO_SECURE:-false}" = "true" ]; then
  MINIO_PUBLIC_URL="https://${AICHECK_MINIO_PUBLIC_ENDPOINT:-127.0.0.1:9000}"
else
  MINIO_PUBLIC_URL="http://${AICHECK_MINIO_PUBLIC_ENDPOINT:-127.0.0.1:9000}"
fi

mc alias set aicheck-minio "$MINIO_PUBLIC_URL" \
  "$AICHECK_MINIO_ACCESS_KEY" "$AICHECK_MINIO_SECRET_KEY"

for bucket in documents previews exports ocr-artifacts; do
  mkdir -p "${BACKUP_DIR}/minio/${bucket}"
  mc mirror --overwrite "aicheck-minio/${bucket}" "${BACKUP_DIR}/minio/${bucket}"
done

tar -C "${BACKUP_DIR}" -czf "${BACKUP_DIR}.tar.gz" .
sha256sum "${BACKUP_DIR}.tar.gz" > "${BACKUP_DIR}.tar.gz.sha256"
```

备份完成后恢复消费：

```bash
docker compose start review-worker-service worker-service
```

恢复顺序：

1. 确认目标环境版本与备份中的 `git-commit.txt`、`docker-compose.rendered.yml`、`.env` 匹配，或先回滚到对应 commit。
2. 停止写入服务：`api-service`、`worker-service`、`review-worker-service`、`ocr-service`、`litellm-service`。
3. 恢复 PostgreSQL 中的 `aicheck`、`litellm`、`workflow` 三个数据库。
4. 恢复 MinIO buckets。
5. 启动全部服务并执行严格验收。

恢复命令：

```bash
cd backend
RESTORE_DIR="./backup/20260101-120000"

docker compose stop api-service worker-service review-worker-service ocr-service litellm-service

cat "${RESTORE_DIR}/aicheck-postgres.dump" | docker compose exec -T postgres pg_restore \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${AICHECK_POSTGRES_DB:-aicheck}" \
  --clean \
  --if-exists

cat "${RESTORE_DIR}/litellm-db.dump" | docker compose exec -T postgres pg_restore \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${LITELLM_POSTGRES_DB:-litellm}" \
  --clean \
  --if-exists

cat "${RESTORE_DIR}/workflow-db.dump" | docker compose exec -T postgres pg_restore \
  -U "${AICHECK_POSTGRES_USER:-aicheck}" \
  -d "${WORKFLOW_POSTGRES_DB:-workflow}" \
  --clean \
  --if-exists

for bucket in documents previews exports ocr-artifacts; do
  mc mirror --overwrite "${RESTORE_DIR}/minio/${bucket}" "aicheck-minio/${bucket}"
done

docker compose up -d
python scripts/verify_deployment.py --strict-production --roles admin,inspection,contractor,ndt,owner,fde
```

恢复验收必须至少确认：

- `GET /healthz` 中 `postgresEnabled=true`、`postgresTransactions=true`、`authRequired=true`。
- 六类角色可登录，默认面板正确。
- 历史项目、资料、ReviewRun、AI feedback、审计日志可查询。
- 已有文件 preview/download signed GET 可读。
- LiteLLM `/v1/models` 返回业务模型别名。
- Temporal UI 可看到恢复后的 workflow 历史，FDE ReviewRun timeline/graph 可打开。

灾备策略建议：

- PostgreSQL、MinIO 每日全量备份，关键上线前额外手动备份。
- MinIO bucket 开启版本控制或外部对象存储生命周期备份。
- 备份包必须加密存储，并和 `.env` secret 分离授权。
- 每月至少做一次恢复演练，恢复后运行 `deployment_report.py --include-live` 生成演练证据。
```

## 11. 升级与回滚

升级前必须先完成第 10 节备份，并确认 `check_96_preflight.py --strict-production` 通过。建议先在 staging 环境跑完整报告，再切生产。

升级：

```bash
git pull
cd backend
python scripts/validate_deployment_config.py --strict-production
python scripts/check_96_preflight.py --strict-production
docker compose up -d --build
cd ../frontend
pnpm install
pnpm lint
pnpm ts:check
pnpm build:pro
```

将 `frontend/dist-pro` 发布到 Web 根目录后，执行：

```bash
cd backend
python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --roles admin,inspection,contractor,ndt,owner,fde \
  --write-probes \
  --ocr-object-probe \
  --review-run-probe \
  --review-run-wait-seconds 20 \
  --litellm-management-probes \
  --litellm-provider-probes \
  --litellm-api-key "$LITELLM_API_KEY" \
  --output-dir ./deployment-reports/latest
```

回滚：

```bash
git checkout <previous-commit>
cd backend
docker compose up -d --build
```

如果回滚涉及前端，也同步恢复上一版 `dist-pro`。回滚后必须重新执行：

```bash
python scripts/verify_deployment.py --strict-production --roles admin,inspection,contractor,ndt,owner,fde
```

如果升级包含数据结构变化，先做 PostgreSQL 三个数据库和 MinIO 备份。当前后端启动时会自动补齐 PostgreSQL 状态表和索引；上线窗口内如发现数据结构不兼容，应按第 10 节恢复整套备份，而不是只回滚代码。

## 12. 常见问题

### 前端仍然显示 mock 数据

检查 `frontend/.env.pro`：

```bash
VITE_USE_MOCK=false
```

然后重新执行 `pnpm build:pro` 并发布新的 `dist-pro`。

### 上传 URL 在浏览器里访问失败

检查：

- `AICHECK_MINIO_PUBLIC_ENDPOINT` 是否是浏览器可访问的域名。
- `AICHECK_MINIO_SECURE` 是否与 HTTPS/HTTP 一致。
- MinIO 反代是否保留 Host、方法和请求体。
- MinIO CORS 是否允许前端域名。

### OCR 任务完成但没有真实字段

检查 `ocr-service` 日志。如果看到 `agentdesign OCR pipeline not importable`，先确认 `AICHECK_AGENTDESIGN_HOST_PATH` 已设置且挂载目录包含 `mvp-system/backend/seal_ocr`；如果路径正确，再确认 OCR 服务确实使用 `Dockerfile.ocr` 构建且 `requirements-ocr.txt` 安装成功。
如果 OCR 有 `fragments` 但没有 `fields/tables/seals`，继续检查：

- `/healthz` 的 `engines` 中 `paddle_ocr_subprocess` 是否 available，`detModelDir/recModelDir` 是否指向真实目录。
- `pp_structure_v3.missingModelDirs` 是否为空；不为空时表格引擎未启用，只能依赖 Profile 的坐标启发表格重建。
- `GET /internal/ocr/doctor` 或 `python scripts/ocr_runtime_doctor.py --json` 中 `preprocess.variants` 是否通过；不通过时先安装 `opencv-python-headless` 或配置 `AICHECK_OCR_SUBPROCESS_PYTHON`。
- 请求是否带 `profileId=piping_characteristic_list_v1` 或正确 `documentType`；没有 Profile 时不会抽取工程表格字段。
- 运行 `scripts/ocr_sample_probe.py` 对同一图片做本地阈值探测，确认 `fragments/fields/tables/seals` 数量是否达标，并加入 `--min-evidence-completeness`、`--max-low-confidence-fields`、`--max-missing-evidence` 检查证据门禁。对必需字段资料，加入 `--min-fields`、重复 `--require-field-code` 指定关键字段，并在严格回归集中使用 `--max-field-conflicts 0`，防止字段冲突静默通过；再加入 `--max-missing-required-fields 0`，让 Profile 自身的 `quality.missingFields` 也能阻断发布。对必需表格资料，加入 `--min-formal-tables`、`--min-business-rows`、`--max-missing-required-tables 0`，必要时再加 `--max-heuristic-tables` 或 `--max-table-review-required`，防止缺失必需表格或启发表格 fallback 在没有正式结构证据时误过门禁。对必需印章资料，再加入 `--min-readable-seals`、`--min-fragment-seals`、`--require-seal-type`、`--max-missing-expected-seal-types 0`，防止视觉章候选、非预期章类型或没有可读章名/片段融合证据的结果误过门禁；`--max-seal-review-required` 只建议用于印章专项回归集，因为真实拍照件可能同时检测到多个非关键视觉候选。验证 PaddleX Seal、agentdesign seal OCR 等增强引擎时，再加入 `--fail-on-engine-failure` 与 `--max-single-engine-duration-ms`，避免增强引擎超时但融合结果靠 fallback 成功而被误判为全绿。用 `--output` 保存完整解析结果，用 `--summary-output` 保存小摘要；失败时先看 `gateFailures/gateFailureCounts`，对目录运行时再看 `qualityReasonCounts`、`diagnosticCodeCounts`、`fieldCodeCounts`、`missingRequiredFieldCounts`、`fieldSourceCounts`、`fieldQualityFlagCounts`、`missingRequiredTableCounts`、`tableSourceCounts`、`tableQualityFlagCounts`、`matchedExpectedSealTypeCounts`、`missingExpectedSealTypeCounts`、`sealTypeCounts`、`readableSealTypeCounts`、`sealSourceCounts`、`sealQualityFlagCounts`、`engineStatusCounts`、`failedEngineRunCount`、`slowestEngineRuns` 和 `slowestFiles`，定位主要失败原因和性能瓶颈。

### AI 复核失败

检查：

- `DEEPSEEK_API_KEY` 是否存在且有效；`deepseek-reasoner` 当前可能由 DeepSeek 侧解析为其兼容 reasoning 模型。
- 如果失败发生在向量化或知识库 embedding，检查 `OPENAI_API_KEY` 或替换后的 embedding provider key。
- `backend/config/litellm.yaml` 的模型名是否被供应商支持。
- `LITELLM_API_KEY` 是否与 `general_settings.master_key` 一致。
- `worker-service` 能否访问 `http://litellm-service:4000`。
- `AICHECK_LITELLM_NO_PROXY` 是否仍包含 `127.0.0.1` 和 `localhost`；缺失时 LiteLLM Prisma query-engine 可能无法连上 DB-backed 管理面。

### 写接口返回 `AUTH_REQUIRED`

如果启用了：

```bash
AICHECK_REQUIRE_AUTH=true
```

前端必须携带 `Authorization: Bearer <jwt>`。第一阶段兼容联调可以保持 `false`。
