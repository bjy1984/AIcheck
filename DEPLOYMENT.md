# AIcheck 部署文档

本文档面向单机 Docker Compose 部署和小规模生产部署。当前仓库包含：

- `api-service`：FastAPI 主业务 API，对前端暴露 `/api/*`，并兼容 `/mock/*` 登录联调路径。
- `worker-service`：Celery worker，处理 OCR、知识切片、向量化、AI 复核、模型对比和导出任务。
- `ocr-service`：内部 OCR 服务，提供 `/healthz` 和 `/internal/ocr/parse`。
- `litellm-service`：LiteLLM Proxy，提供 OpenAI-compatible 模型网关。
- `mongodb`、`redis`、`minio`、`litellm-postgres`：业务数据、任务队列、对象存储和 LiteLLM 元数据。

## 1. 项目架构

AIcheck 采用前后端分离、主业务 API 与异步能力服务拆分的架构。浏览器只访问前端站点、`api-service` 和 MinIO signed URL；OCR、LiteLLM、MongoDB、Redis、PostgreSQL 均应部署在内网。

### 1.1 仓库结构

```text
AIcheck/
├── frontend/                  # Vue 3 + Vite 前端应用
│   └── src/
│       ├── api/aicheck/       # 前端业务 API client，后端合同以此为准
│       ├── api/login/         # 登录与动态路由 API client
│       ├── utils/roleAccess.ts
│       └── views/AICheck/     # 监检、施工方、NDT、建设方、管理后台页面
├── backend/
│   ├── apps/api/              # FastAPI 主业务 API
│   ├── apps/worker/           # Celery worker 与异步任务入口
│   ├── apps/ocr_service/      # 内部 OCR HTTP 服务
│   ├── libs/contracts/        # 统一响应、错误码、分页合同
│   ├── libs/db/               # MongoDB 适配、索引、seed、仓储层
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
  │                                      ├── MongoDB：业务数据、审计、任务状态
  │                                      ├── Redis：Celery broker/result backend
  │                                      ├── MinIO：signed PUT/GET、预览、导出包
  │                                      └── LiteLLM：少量同步模型能力探测
  │
  └── signed PUT/GET ─────────────────▶ MinIO

worker-service (Celery)
  ├── Redis 队列：ocr.parse_document、knowledge.slice、knowledge.embed、
  │              inspection.ai_recheck、llm.compare、export.package
  ├── 调用 ocr-service 完成 PDF/图片 OCR、印章识别和结构化字段抽取
  ├── 调用 litellm-service 完成 chat、embedding、模型对比
  └── 回写 MongoDB 与 MinIO 导出产物

ocr-service
  └── 导入 agentdesign 的 seal_ocr/parsing pipeline，失败时按配置生成可重试失败任务

litellm-service
  ├── 对 api/worker 暴露 OpenAI-compatible API
  └── 使用 litellm-postgres 保存模型配置、virtual key、预算和调用日志
```

### 1.3 业务模块边界

| 模块 | 前端入口 | 后端职责 | 主要数据 |
| --- | --- | --- | --- |
| 登录与角色 | `/login`、动态路由 | `/api/auth/login`、JWT、默认面板、路由与动作权限 | `users`、`roles`、`project_members` |
| 工作台 | `/workbench/{role}` | 项目列表、项目上下文、摘要、项目树、节点包 | `projects`、`project_nodes`、`todos`、`messages` |
| 文件与节点资料 | 工作台文件区 | 上传会话、MinIO signed URL、版本、挂载、撤回、作废 | `documents`、`document_versions`、`node_bindings` |
| 提交与补正 | 施工方/监检工作台 | 批次提交、撤回、补正反馈、状态机校验 | `submissions`、`rectifications`、`audit_logs` |
| 监检审查 | 监检工作台 | AI 复核、人工意见、证据链、报告草稿 | `ai_runs`、`evidence_links`、`reports` |
| NDT | `/workbench/ndt` | 底片、检测记录、检测报告、NDT 补正 | `ndt_films`、`ndt_records`、`ndt_reports`、`ndt_feedback` |
| 报告与归档 | 监检/建设方工作台 | 报告复核、导出、归档、证据包 | `reports`、`archive_items`、`export_tasks` |
| 知识库 | `/knowledge/*` | 文件列表、任务中心、知识源、规则、检索测试 | `knowledge_files`、`knowledge_tasks`、`knowledge_chunks` |
| 管理后台 | `/admin/*` | 项目、单位、用户、权限、配置发布、审计 | `admin_configs`、`audit_logs` |

### 1.4 核心调用链

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
2. `api-service` 只创建 `ai_runs` 或 `llm_compare_runs`，并投递 Celery 任务。
3. `worker-service` 通过 LiteLLM 的 OpenAI-compatible API 调用 chat/embedding/compare 模型。
4. 业务结果回写 MongoDB；LiteLLM 自己保存模型调用层日志。
5. 前端通过现有查询接口轮询 run/task 状态。

报告导出：

1. 前端创建报告导出或归档包导出任务。
2. `api-service` 写入 `export_tasks` 并投递 `export.package`。
3. `worker-service` 生成 zip/pdf 产物并写入 MinIO；zip 包必须包含 `manifest.json`、`task.json`、`project.json`、`reports.json`、`documents.json`、`archive_items.json`、`evidence_links.json` 和 `README.txt`。
4. 前端查询任务状态；任务可下载时获取短期 signed GET。

### 1.5 权限与数据边界

- 生产必须启用 `AICHECK_REQUIRE_AUTH=true`，后端以 JWT 身份为准；非管理员不能伪造 `X-Role` 或 `X-User-Id`。
- 后端不会只依赖前端按钮显隐。mutation 会根据路径推断 `ActionCode`，即使前端未传 `X-Action-Code` 也会拦截越权动作。
- `tests/test_contract.py::test_all_non_public_mutating_routes_have_inferred_action_codes` 会遍历 FastAPI 所有非登录 POST/PUT/PATCH/DELETE 路由，确保新增写接口必须配置后端可推断的 `ActionCode`。
- 成功 mutation 如果路由没有显式返回 `auditLogId`，后端中间件会写入一条通用 `ApiMutation` 审计日志；已有显式审计的路由不会重复写。
- 项目成员与节点范围校验覆盖 URL、query、body，以及 `documentId`、`bindingId`、`reportId`、NDT report/film、export task 等资源 ID 反查出的节点。
- 项目树、文件、挂载、报告、归档、NDT、知识任务、搜索、待办、消息、推理日志和模型对比列表在登录态下按 `nodeScope` 过滤。
- `/api/admin/*`、全局知识源/配置/审计、规则版本等管理接口仅管理员可读写。
- 已归档项目的 mutation 统一返回 `ARCHIVED_READONLY`；过期 `If-Match` 返回 `ETAG_CONFLICT`；重复 `Idempotency-Key` 使用请求 hash 防止同 key 不同 body。
- 后端中间件会对所有非公开 POST/PUT/PATCH/DELETE 写请求统一处理 `Idempotency-Key`：相同 key 和相同 body/query 重放首次成功响应，同 key 不同 body/query 返回 `IDEMPOTENCY_KEY_CONFLICT`；路由层仍可对提交、导出、任务重试等关键流程显式传入业务 fingerprint。

### 1.6 数据存储边界

| 存储 | 用途 | 生产要求 |
| --- | --- | --- |
| MongoDB | AIcheck 主业务数据、审计日志、任务状态 | 必须开启 replica set 或分片集群以支持 transaction。 |
| MinIO | 原始文件、预览、导出包、OCR artifacts | 浏览器 signed URL 使用外部域名，服务端使用内网 endpoint。 |
| Redis | Celery broker/result backend、任务状态缓存 | 建议开启持久化或使用托管 Redis。 |
| PostgreSQL | 仅 LiteLLM 元数据 | 不承载 AIcheck 业务表。 |

MongoDB 启动时会执行 `backend/libs/db/indexes.py` 中的索引声明。当前索引覆盖所有持久化 collection，包括项目/节点状态、文件版本、提交草稿、补正、项目成员授权、OCR 抽取字段、知识源/任务、审计日志、导出任务、NDT、用户/角色和幂等键；`tests/test_contract.py::test_mongo_indexes_cover_all_persisted_collections` 会阻止新增持久化集合但漏配索引。

## 2. 部署前准备

服务器建议：

- Docker 24+ 与 Docker Compose v2。
- 4 核 CPU、16 GB 内存起步；真实 PaddleOCR/印章识别建议 8 核、32 GB 内存或独立 OCR 节点。
- 磁盘至少 100 GB，并为 MongoDB、MinIO、PostgreSQL 数据卷预留独立持久化空间。
- 前端构建机需要 Node.js 18+ 与 pnpm 8+。

外部依赖：

- 模型供应商密钥，例如 `OPENAI_API_KEY`。
- 可访问的域名和 HTTPS 证书。
- 如果要启用真实 OCR，需要提供 `agentdesign` OCR 代码。当前 Compose 使用 `Dockerfile.ocr` 安装 `requirements-ocr.txt` 中的 PaddleOCR/PaddleX/PyMuPDF/OpenCV 依赖，并通过 `AICHECK_AGENTDESIGN_HOST_PATH` 把宿主机 `agentdesign` 目录只读挂载到 `/opt/agentdesign`；生产建议保持 `AICHECK_OCR_ALLOW_PLACEHOLDER=false`，无法导入 OCR 管线时任务会失败并进入可重试状态。

## 3. 端口与路径

默认 Compose 端口：

| 服务 | 容器端口 | 主机端口 | 说明 |
| --- | ---: | ---: | --- |
| `api-service` | 8000 | 8000 | FastAPI 主业务 API |
| `ocr-service` | 8010 | 8010 | 内部 OCR API |
| `litellm-service` | 4000 | 4001 | LiteLLM Proxy，对内使用 |
| `mongodb` | 27017 | 27017 | 业务数据库 |
| `redis` | 6379 | 6379 | Celery broker/result backend |
| `minio` | 9000 | 9000 | 对象存储 API，浏览器签名上传需要访问 |
| `minio` | 9001 | 9001 | MinIO 控制台 |
| `litellm-postgres` | 5432 | 5433 | LiteLLM 元数据数据库 |

健康检查：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8010/healthz
curl http://127.0.0.1:4001/health
```

`api-service` 健康检查会返回 `mongoEnabled`、`mongoTransactions`、`authRequired`、`demoUsersEnabled`、`objectStorageEnabled`。`mongoTransactions` 表示后端已开启事务配置；生产验收还应使用 `verify_deployment.py --strict-production` 调用 `/api/system/mongo-transaction-probe`，实际执行一次临时 MongoDB transaction，确认数据库副本集和会话能力可用。`ocr-service` 健康检查会返回 `pipelineAvailable`、`pipelineBackend`、`placeholderAllowed`，用于确认 OCR 依赖和占位策略是否符合生产预期。

Compose 已为 `api-service`、`worker-service`、`ocr-service`、`mongodb`、`redis`、`minio`、`litellm-postgres` 和 `litellm-service` 配置容器级 `healthcheck`；`api-service`、`worker-service`、`ocr-service` 和 `litellm-service` 的依赖使用 `condition: service_healthy`，避免依赖容器刚启动但服务尚不可用时提前接流量或消费任务。`validate_deployment_config.py --strict-production` 会静态检查这些 healthcheck 和依赖条件。

前端生产环境只需要暴露 Web 站点、`/api/*`、`/mock/*` 和 MinIO 签名上传访问地址。LiteLLM、MongoDB、Redis、PostgreSQL 不应暴露到公网。

## 4. 后端环境变量

在 `backend/.env` 创建部署环境变量。Compose 在 `backend/` 目录运行时会自动读取该文件。

```bash
OPENAI_API_KEY=sk-...

AICHECK_MONGO_URL=mongodb://mongodb:27017/?replicaSet=rs0
AICHECK_MONGO_DB=aicheck
AICHECK_MONGO_TRANSACTIONS=true

AICHECK_REDIS_URL=redis://redis:6379/0
AICHECK_TASK_DISPATCH=celery

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

LITELLM_BASE_URL=http://litellm-service:4000
LITELLM_API_KEY=replace-with-litellm-master-key
LITELLM_POSTGRES_DB=litellm
LITELLM_POSTGRES_USER=litellm
LITELLM_POSTGRES_PASSWORD=replace-with-strong-password

```

变量说明：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | LiteLLM 转发到模型供应商的密钥。没有该值时 AI 复核、向量化和模型对比会失败。 |
| `AICHECK_MONGO_URL` | 是 | 主业务 MongoDB 连接串。Compose 默认使用单节点 replica set：`mongodb://mongodb:27017/?replicaSet=rs0`。 |
| `AICHECK_MONGO_DB` | 是 | 主业务数据库名。 |
| `AICHECK_MONGO_TRANSACTIONS` | 是 | 生产设为 `true`，跨 collection flush 和角色初始化会使用 MongoDB transaction；数据库必须是 replica set 或分片集群。 |
| `AICHECK_REDIS_URL` | 是 | Celery broker 和 result backend。 |
| `AICHECK_TASK_DISPATCH` | 是 | 生产使用 `celery`；本地测试可用 `disabled` 或 `inline`。 |
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
| `LITELLM_BASE_URL` | 是 | API/worker 访问 LiteLLM 的内部地址。 |
| `LITELLM_API_KEY` | 是 | LiteLLM master key，需与 LiteLLM 配置保持一致。 |
| `LITELLM_POSTGRES_DB` | 是 | LiteLLM PostgreSQL 数据库名。 |
| `LITELLM_POSTGRES_USER` | 是 | LiteLLM PostgreSQL 用户名。 |
| `LITELLM_POSTGRES_PASSWORD` | 是 | LiteLLM PostgreSQL 密码。 |

Compose 对敏感变量使用必填校验，缺少以下变量时服务不会启动；上线前必须提供强随机值或真实 provider key：

- `OPENAI_API_KEY`
- `AICHECK_AGENTDESIGN_HOST_PATH`
- `AICHECK_JWT_SECRET`
- `AICHECK_MINIO_SECRET_KEY`
- `LITELLM_API_KEY`
- `LITELLM_POSTGRES_PASSWORD`

## 5. 启动后端服务

```bash
cd backend
# 确认 backend/.env 中已设置 AICHECK_AGENTDESIGN_HOST_PATH，并且该目录包含 mvp-system/backend
docker compose pull
docker compose up -d --build
docker compose ps
```

首次启动时：

- `api-service` 会连接 MongoDB，创建索引，并在空库时写入 demo seed 数据。
- Compose 中的 MongoDB 以 `rs0` 单节点 replica set 启动；这是 MongoDB transaction 的最低运行条件。
- `api-service` 会确保 MinIO bucket：`documents`、`previews`、`exports`、`ocr-artifacts`。
- `worker-service` 会监听队列：`ocr.parse_document`、`ocr.recognize_seals`、`knowledge.slice`、`knowledge.embed`、`inspection.ai_recheck`、`llm.compare`、`export.package`。
- `ocr-service` 会把 `${AICHECK_AGENTDESIGN_HOST_PATH}` 只读挂载到 `/opt/agentdesign`，并从 `/opt/agentdesign/mvp-system/backend` 导入 OCR pipeline。
- `litellm-service` 使用 `backend/config/litellm.yaml` 中的模型别名：`default-chat`、`review-chat`、`compare-fast`、`embedding-default`。

### 5.1 角色账号与权限初始化

第一版真实登录已支持五类角色账号。登录成功后前端会根据后端返回的 `defaultPath` 进入对应面板，并通过 `X-Role`、`X-User-Id` 请求头参与后端项目成员和节点范围校验。

生产开启 `AICHECK_REQUIRE_AUTH=true` 后，后端会以 JWT 中的登录身份为准校验 `X-Role` 和 `X-User-Id`：非管理员不能伪造其他角色或用户；未传 `X-User-Id` 时会自动使用 JWT 对应用户做项目成员和节点范围校验。GET 和 mutation 都会校验项目成员资格；节点范围同时覆盖 URL 中的 `/nodes/{nodeId}`、query/body 中的 `nodeId/nodeIds`，以及 `documentId`、`bindingId`、`reportId` 等资源 ID 反查出的关联节点。项目树、文件、挂载、报告和归档列表在登录态下会按 `nodeScope` 过滤，避免业务角色看到授权范围外的数据。写接口会根据后端路径表自动推断 `ActionCode`，即使前端未发送 `X-Action-Code`，也会按角色动作矩阵拦截越权调用。

| 角色 | 用户名 | 默认入口 | 说明 |
| --- | --- | --- | --- |
| 系统管理员 | `admin` | `/admin/overview` | 管理后台、配置、授权、审计；不能代替业务角色保存审查意见。 |
| 监检人员 | `inspection` | `/workbench/inspection` | 监检审查、AI 复核、报告生成、导出和归档。 |
| 施工方 | `contractor` | `/workbench/contractor` | 资料上传、节点挂载、提交批次、补正反馈。 |
| 无损检测 | `ndt` | `/workbench/ndt` | 底片、检测记录、检测报告和补正反馈。 |
| 建设方 | `owner` | `/workbench/owner` | 项目、报告和归档只读查看。 |

部署后运行角色创建脚本，确保 MongoDB 中的真实登录用户、角色、后台角色矩阵、用户/单位目录和项目成员授权一致：

```bash
cd backend

cat > /secure/aicheck-role-passwords.json <<'JSON'
{
  "admin": "replace-with-strong-admin-password",
  "inspection": "replace-with-strong-inspection-password",
  "contractor": "replace-with-strong-contractor-password",
  "ndt": "replace-with-strong-ndt-password",
  "owner": "replace-with-strong-owner-password"
}
JSON
chmod 600 /secure/aicheck-role-passwords.json

# 只预览，不写库
python scripts/create_roles.py \
  --password-file /secure/aicheck-role-passwords.json \
  --require-strong-passwords \
  --dry-run \
  --json

# 本机 MongoDB 写入
AICHECK_MONGO_URL='mongodb://127.0.0.1:27017/?replicaSet=rs0' \
AICHECK_MONGO_DB=aicheck \
AICHECK_MONGO_TRANSACTIONS=true \
python scripts/create_roles.py \
  --project-id P-2026-HDCP-001 \
  --password-file /secure/aicheck-role-passwords.json \
  --require-strong-passwords

# Docker Compose 环境写入
docker compose exec api-service python scripts/create_roles.py \
  --project-id P-2026-HDCP-001 \
  --password-file /run/secrets/aicheck-role-passwords.json \
  --require-strong-passwords
```

脚本行为：

- 写入或更新 `users` 与 `roles`，`users.passwordHash` 使用 PBKDF2-SHA256；重复执行不会重置已有用户密码。
- 生产必须通过 `--password-file` 或 `AICHECK_BOOTSTRAP_PASSWORD_<ROLE>` 环境变量提供初始密码，并使用 `--require-strong-passwords` 拒绝用户名同名、过短或复杂度不足的密码；默认输出会脱敏密码。
- 如需显式重置已有账号密码，增加 `--rotate-passwords`；未传该参数时重复执行会保留已有 `passwordHash`。
- 写入或更新 `admin_configs` singleton 中的 `orgUnits`、`users`、`permissionMatrix`。
- 写入或更新 `project_members`，同一项目、同一用户、同一角色重复执行时会合并 `nodeScope` 和 `actions`，不会插入覆盖性重复成员。
- 写入一条 `audit_logs` 记录，便于追溯部署初始化动作。
- 当 `AICHECK_MONGO_TRANSACTIONS=true` 时，上述 MongoDB 写入在同一个 transaction 中提交。
- 支持 `--roles admin,inspection` 只初始化部分角色；支持 `--project-id` 指定项目；支持 `--mongo-url` 和 `--db` 覆盖环境变量。

注意：生产环境 `AICHECK_ENABLE_DEMO_USERS=false` 时，只有脚本写入 `users` 后才能登录。不要在生产使用用户名同名密码；首次上线后仍建议接入企业用户中心或正式密码重置流程。

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

不要在生产环境使用 `docker compose down -v`，它会删除 MongoDB、MinIO 和 PostgreSQL 数据卷。

## 6. 前端构建与发布

生产构建必须关闭 mock。当前 `frontend/.env.pro` 仍保留模板默认值，发布前至少修改：

```bash
VITE_APP_TITLE=压力管道监检协作系统
VITE_USE_MOCK=false
VITE_BASE_PATH=/
VITE_API_BASE_PATH=
VITE_OUT_DIR=dist-pro
```

构建：

```bash
cd frontend
pnpm install
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

说明：

- `/api/*` 不需要在 Nginx 中去掉 `/api`，后端已经同时支持 `/api/*` 与无前缀路由。
- `/mock/*` 保留给第一阶段登录兼容。真实登录接口是 `/api/auth/login`。
- 如果 MinIO 使用独立域名，例如 `files.example.com`，需要为 MinIO API 单独配置 HTTPS 反代，并把 `AICHECK_MINIO_PUBLIC_ENDPOINT` 设置为该域名。
- 浏览器直传 MinIO 时，如前端站点和 MinIO 域名不同，需要为 MinIO 配置 CORS，允许 `PUT`、`GET`、`HEAD` 和必要请求头。

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
- `Dockerfile.ocr` 会安装 `requirements-ocr.txt`；该文件对齐 `agentdesign/requirements/mvp-ocr.txt` 的基线依赖：`PyMuPDF`、`paddlepaddle`、`paddleocr`、`paddlex[ocr]`、`opencv-python-headless`。
- 如果改为企业自维护 OCR 镜像，应保留 `/internal/ocr/parse` 合同和 `/healthz` 中的 `pipelineAvailable/placeholderAllowed` 字段，并继续安装上述 OCR 依赖基线或等价替代。
- 生产应设置 `AICHECK_OCR_ALLOW_PLACEHOLDER=false`。此时 OCR 管线不可用会写入失败任务，前端任务中心可重试。
- `verify_deployment.py --strict-production` 会要求 OCR 健康检查返回 `pipelineAvailable=true` 且 `placeholderAllowed=false`。
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
- `compare-fast`
- `embedding-default`

上线前检查：

```bash
curl http://127.0.0.1:4001/health
curl http://127.0.0.1:4001/v1/models \
  -H "Authorization: Bearer ${LITELLM_API_KEY}"
```

`/v1/models` 必须能看到 `default-chat`、`review-chat`、`compare-fast`、`embedding-default` 四个别名；`verify_deployment.py` 会自动检查这些别名。

`api-service` 和 `worker-service` 在 `AICHECK_REQUIRE_AUTH=true`、`AICHECK_MONGO_TRANSACTIONS=true` 或 `AICHECK_STRICT_PRODUCTION=true` 任一生产标志开启时，禁止使用内置开发 LiteLLM key；必须显式提供 `LITELLM_API_KEY`。

如果 `OPENAI_API_KEY` 或供应商密钥无效：

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

for account in inspection contractor ndt owner admin; do
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

# 供应商级模型验收：会消耗少量模型额度，确认 default-chat 与 embedding-default 能真实调用 provider
python scripts/verify_deployment.py \
  --strict-production \
  --litellm-provider-probes \
  --litellm-api-key "$LITELLM_API_KEY"

# 机器可读输出，适合 CI 或上线流水线
python scripts/verify_deployment.py --strict-production --json

# 生成上线验收证据包：默认跑离线配置和前后端合同审计，输出 report.json/report.md
python scripts/deployment_report.py \
  --strict-production \
  --output-dir ./deployment-reports/latest

# 生成包含目标环境探针的证据包；可按需加 --write-probes、--ocr-object-probe、--litellm-provider-probes
python scripts/deployment_report.py \
  --strict-production \
  --include-live \
  --write-probes \
  --ocr-object-probe \
  --litellm-provider-probes \
  --litellm-api-key "$LITELLM_API_KEY" \
  --output-dir ./deployment-reports/latest
```

`validate_deployment_config.py` 会静态解析 `Dockerfile`、`Dockerfile.ocr`、`requirements-ocr.txt`、`docker-compose.yml` 和 `config/litellm.yaml`，检查镜像基础契约、非 root 运行用户、API/OCR 端口、OCR PaddleOCR 基线依赖、服务拓扑、依赖、healthcheck、端口映射、Celery 队列、Mongo replica set、OCR artifact 只读挂载、持久化 volume、关键环境变量、LiteLLM 四个模型别名和数据库配置。它不需要 Docker，可在没有 Docker daemon 的 CI 环境中先挡住配置错误。

`verify_deployment.py` 默认只做健康检查、登录、MongoDB transaction 探针、只读查询、OCR parse 合同探测、OCR bad request 合同探测、LiteLLM 模型别名检查，以及应返回 `FORBIDDEN` 的身份伪造/动作越权/读范围检查，不会创建业务数据，也不会消耗模型额度。开启 `--litellm-provider-probes` 后会通过 LiteLLM 的 OpenAI-compatible API 实际调用 `default-chat` 和 `embedding-default`，证明网关、virtual key、provider key、模型别名和供应商连通性可用。开启 `--write-probes` 后会在 `--project-id` 指定项目下创建一条验证用上传会话，使用 returned HTTP/HTTPS signed URL 实际 PUT 一个包含文字的 PDF，再执行 upload complete，校验新文档的 preview/download signed GET 可以实际读取对象，确认 OCR task 创建，并创建/读取导出任务，用于证明 MinIO signed PUT、文档 signed GET、upload complete、OCR task 创建和 export task 查询闭环。开启 `--ocr-object-probe` 时，verifier 会读取新文档当前版本 `storageKey` 并调用 `ocr-service /internal/ocr/parse`，要求 OCR 对刚上传的 MinIO 对象返回 `status=success`。严格生产模式还会要求 MongoDB 已启用并通过实际 transaction 探针，校验 OCR 使用真实 pipeline 而不是 placeholder，并要求 signed PUT/GET URL 是 HTTP/HTTPS。

`deployment_report.py` 会把离线配置验收、前后端合同审计和可选 live deployment probes 汇总成 `aicheck-deployment-report-v1` 结构，同时输出 Markdown 表格，适合随上线单归档。默认不访问目标环境；加 `--include-live` 后复用 `verify_deployment.py` 的所有目标环境探针。

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
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# 终端 2
cd frontend
pnpm vite --mode live --host 127.0.0.1 --port 4100

# 终端 3
cd frontend
AICHECK_BASE_URL=http://127.0.0.1:4100 pnpm playwright test e2e/aicheck-smoke.spec.ts --reporter=list
```

当前本地 live smoke 基线为 51 条通过，覆盖四类工作台、管理后台、知识库、NDT、报告导出/归档、联调清单 0 blocker、错误码恢复和主要写回流程。

关键手工验证：

- 五类角色登录后能进入各自默认面板；业务角色访问 `/admin/overview` 会回退到自己的工作台。
- 项目列表、项目树、节点包、报告、归档页面能正常加载。
- 管理后台项目成员授权后，业务角色节点范围外 mutation 返回 `FORBIDDEN`。
- 生产鉴权开启后，业务角色读取项目成员范围外的节点包、文件详情或报告详情返回 `FORBIDDEN`。
- 生产鉴权开启后，项目树、文件列表、挂载列表、报告列表和归档列表只返回当前用户 `nodeScope` 范围内的数据。
- 生产鉴权开启后，非管理员使用 JWT 登录身份之外的 `X-Role` 或 `X-User-Id` 调用 mutation 返回 `FORBIDDEN`。
- 生产鉴权开启后，业务角色在请求体里提交授权范围外的 `nodeId/nodeIds` 返回 `FORBIDDEN`，例如施工方不能提交 NDT 节点资料，NDT 不能向监检节点导入记录。
- 生产鉴权开启后，业务角色通过 `documentId`、`bindingId`、`reportId` 操作节点范围外资源返回 `FORBIDDEN`；资源与 URL `projectId` 不一致返回 `NOT_FOUND`。
- 生产鉴权开启后，业务角色直接调用未授权写接口会按后端推断的 `ActionCode` 返回 `FORBIDDEN`，例如施工方不能生成报告草稿或发布后台配置。
- mutation 使用相同 `Idempotency-Key` 和相同请求体会重放同一结果；同 key 不同请求体返回 `IDEMPOTENCY_KEY_CONFLICT`。
- `verify_deployment.py --strict-production` 会调用 `/api/system/mongo-transaction-probe`，确认 MongoDB 已连接、`AICHECK_MONGO_TRANSACTIONS=true`，且能实际开启 session 并提交临时 transaction。
- 提交批次撤回资料时，只能撤回该批次内资料；不存在的批次返回 `NOT_FOUND`，跨批次资料返回 `CONFLICT`，已通过、已锁定或已归档资料返回 `WITHDRAW_LOCKED`。
- 施工方提交补正反馈时必须存在当前节点的待反馈补正单，且反馈资料必须属于该节点；成功后原补正单变为 `已反馈`，节点进入 `复审中`。
- 报告草稿只能从已进入审查链路的节点生成；`待提交`、`需补正`、`退回补正中`、`部分提交`、`AI 预审中` 节点返回 `CONFLICT`。
- 创建 upload session 返回 MinIO signed PUT URL。
- `verify_deployment.py --write-probes --strict-production` 能实际 PUT signed URL，上传完成后文档 `preview-url/download-url` 能返回并读取 HTTP(S) signed GET，`GET /api/knowledge/tasks` 能看到 OCR/切片/向量任务。
- `verify_deployment.py --write-probes --ocr-object-probe --strict-production` 能让 OCR 服务从 MinIO 读取刚上传的 PDF 并返回 `status=success`。
- `POST /internal/ocr/parse` 返回统一 OCR 结构：`status/fragments/fields/diagnostics/storageKey`；源文件缺失时也应返回 `status=failed` 的业务结构，而不是 500。
- 触发 AI 复核后 `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs` 能看到运行记录。
- LiteLLM `/v1/models` 包含四个业务别名：`default-chat`、`review-chat`、`compare-fast`、`embedding-default`。
- `verify_deployment.py --strict-production --litellm-provider-probes` 能通过 LiteLLM 实际获得 chat completion 和 embedding vector；失败时 verifier 只返回业务级 HTTP/形状错误，不输出 provider 原始密钥或错误正文。
- 报告导出任务从处理中变为可下载。
- 下载导出 zip 后能解出 `manifest.json`，其中 `schemaVersion=aicheck-export-v1`，`counts` 与当前项目报告、资料、归档和证据数量一致；报告 PDF 至少包含任务、项目和报告摘要。

## 10. 备份与恢复

MongoDB 备份：

```bash
docker compose exec mongodb mongodump --db aicheck --archive=/tmp/aicheck.archive
docker compose cp mongodb:/tmp/aicheck.archive ./backup/aicheck.archive
```

MongoDB 恢复：

```bash
docker compose cp ./backup/aicheck.archive mongodb:/tmp/aicheck.archive
docker compose exec mongodb mongorestore --drop --archive=/tmp/aicheck.archive
```

MinIO 数据：

- Compose 默认数据卷是 `minio-data`。
- 生产建议将 MinIO 数据目录挂载到独立磁盘，并使用对象存储生命周期、版本控制或外部备份策略。

LiteLLM PostgreSQL：

```bash
docker compose exec litellm-postgres pg_dump -U litellm litellm > backup/litellm.sql
```

## 11. 升级与回滚

升级：

```bash
git pull
cd backend
docker compose up -d --build
cd ../frontend
pnpm install
pnpm ts:check
pnpm build:pro
```

回滚：

```bash
git checkout <previous-commit>
cd backend
docker compose up -d --build
```

如果升级包含数据结构变化，先做 MongoDB、MinIO 和 LiteLLM PostgreSQL 备份。当前后端启动时会自动补齐 MongoDB 索引，但没有单独的迁移命令。

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

### AI 复核失败

检查：

- `OPENAI_API_KEY` 是否存在且有效。
- `backend/config/litellm.yaml` 的模型名是否被供应商支持。
- `LITELLM_API_KEY` 是否与 `general_settings.master_key` 一致。
- `worker-service` 能否访问 `http://litellm-service:4000`。

### 写接口返回 `AUTH_REQUIRED`

如果启用了：

```bash
AICHECK_REQUIRE_AUTH=true
```

前端必须携带 `Authorization: Bearer <jwt>`。第一阶段兼容联调可以保持 `false`。
