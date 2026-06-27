# AIcheck 部署文档

本文档面向单机 Docker Compose 部署和小规模生产部署。当前仓库包含：

- `api-service`：FastAPI 主业务 API，对前端暴露 `/api/*`，并兼容 `/mock/*` 登录联调路径。
- `worker-service`：Celery worker，处理 OCR、知识切片、向量化、AI 复核、模型对比和导出任务。
- `ocr-service`：内部 OCR 服务，提供 `/healthz` 和 `/internal/ocr/parse`。
- `litellm-service`：LiteLLM Proxy，提供 OpenAI-compatible 模型网关。
- `mongodb`、`redis`、`minio`、`litellm-postgres`：业务数据、任务队列、对象存储和 LiteLLM 元数据。

## 1. 部署前准备

服务器建议：

- Docker 24+ 与 Docker Compose v2。
- 4 核 CPU、16 GB 内存起步；真实 PaddleOCR/印章识别建议 8 核、32 GB 内存或独立 OCR 节点。
- 磁盘至少 100 GB，并为 MongoDB、MinIO、PostgreSQL 数据卷预留独立持久化空间。
- 前端构建机需要 Node.js 18+ 与 pnpm 8+。

外部依赖：

- 模型供应商密钥，例如 `OPENAI_API_KEY`。
- 可访问的域名和 HTTPS 证书。
- 如果要启用真实 OCR，需要把 `agentdesign` 的 OCR 依赖纳入镜像或部署到可导入路径。当前基础镜像未内置 PaddleOCR 重依赖，无法导入 OCR 管线时会生成规范化 placeholder OCR 结果。

## 2. 端口与路径

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

前端生产环境只需要暴露 Web 站点、`/api/*`、`/mock/*` 和 MinIO 签名上传访问地址。LiteLLM、MongoDB、Redis、PostgreSQL 不应暴露到公网。

## 3. 后端环境变量

在 `backend/.env` 创建部署环境变量。Compose 在 `backend/` 目录运行时会自动读取该文件。

```bash
OPENAI_API_KEY=sk-...

AICHECK_MONGO_URL=mongodb://mongodb:27017
AICHECK_MONGO_DB=aicheck

AICHECK_REDIS_URL=redis://redis:6379/0
AICHECK_TASK_DISPATCH=celery

AICHECK_MINIO_ENDPOINT=minio:9000
AICHECK_MINIO_PUBLIC_ENDPOINT=files.example.com
AICHECK_MINIO_ACCESS_KEY=aicheck
AICHECK_MINIO_SECRET_KEY=replace-with-strong-password
AICHECK_MINIO_SECURE=true

LITELLM_BASE_URL=http://litellm-service:4000
LITELLM_API_KEY=replace-with-litellm-master-key
LITELLM_POSTGRES_DB=litellm
LITELLM_POSTGRES_USER=litellm
LITELLM_POSTGRES_PASSWORD=replace-with-strong-password

# 第一阶段前端 smoke 兼容可保持 false；正式启用鉴权时改为 true。
AICHECK_REQUIRE_AUTH=false
```

变量说明：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | LiteLLM 转发到模型供应商的密钥。没有该值时 AI 复核、向量化和模型对比会失败。 |
| `AICHECK_MONGO_URL` | 是 | 主业务 MongoDB 连接串。 |
| `AICHECK_MONGO_DB` | 是 | 主业务数据库名。 |
| `AICHECK_REDIS_URL` | 是 | Celery broker 和 result backend。 |
| `AICHECK_TASK_DISPATCH` | 是 | 生产使用 `celery`；本地测试可用 `disabled` 或 `inline`。 |
| `AICHECK_MINIO_ENDPOINT` | 是 | 后端访问 MinIO 的内部地址。 |
| `AICHECK_MINIO_PUBLIC_ENDPOINT` | 是 | 浏览器访问签名 URL 的外部地址。域名、端口和协议必须与反代一致。 |
| `AICHECK_MINIO_SECURE` | 否 | HTTPS 访问 MinIO 时设为 `true`。 |
| `LITELLM_BASE_URL` | 是 | API/worker 访问 LiteLLM 的内部地址。 |
| `LITELLM_API_KEY` | 是 | LiteLLM master key，需与 LiteLLM 配置保持一致。 |
| `LITELLM_POSTGRES_DB` | 是 | LiteLLM PostgreSQL 数据库名。 |
| `LITELLM_POSTGRES_USER` | 是 | LiteLLM PostgreSQL 用户名。 |
| `LITELLM_POSTGRES_PASSWORD` | 是 | LiteLLM PostgreSQL 密码。 |
| `AICHECK_REQUIRE_AUTH` | 否 | 设为 `true` 后非公开接口强制校验 JWT。 |

上线前必须替换以下开发默认值：

- `AICHECK_MINIO_ACCESS_KEY`
- `AICHECK_MINIO_SECRET_KEY`
- `LITELLM_API_KEY`
- `LITELLM_POSTGRES_PASSWORD`

## 4. 启动后端服务

```bash
cd backend
docker compose pull
docker compose up -d --build
docker compose ps
```

首次启动时：

- `api-service` 会连接 MongoDB，创建索引，并在空库时写入 demo seed 数据。
- `api-service` 会确保 MinIO bucket：`documents`、`previews`、`exports`、`ocr-artifacts`。
- `worker-service` 会监听队列：`ocr.parse_document`、`ocr.recognize_seals`、`knowledge.slice`、`knowledge.embed`、`inspection.ai_recheck`、`llm.compare`、`export.package`。
- `litellm-service` 使用 `backend/config/litellm.yaml` 中的模型别名：`default-chat`、`review-chat`、`compare-fast`、`embedding-default`。

### 4.1 角色账号与权限初始化

第一版真实登录已支持五类角色账号。登录成功后前端会根据后端返回的 `defaultPath` 进入对应面板，并通过 `X-Role`、`X-User-Id` 请求头参与后端项目成员和节点范围校验。

| 角色 | 用户名 / 初始密码 | 默认入口 | 说明 |
| --- | --- | --- | --- |
| 系统管理员 | `admin` / `admin` | `/admin/overview` | 管理后台、配置、授权、审计；不能代替业务角色保存审查意见。 |
| 监检人员 | `inspection` / `inspection` | `/workbench/inspection` | 监检审查、AI 复核、报告生成、导出和归档。 |
| 施工方 | `contractor` / `contractor` | `/workbench/contractor` | 资料上传、节点挂载、提交批次、补正反馈。 |
| 无损检测 | `ndt` / `ndt` | `/workbench/ndt` | 底片、检测记录、检测报告和补正反馈。 |
| 建设方 | `owner` / `owner` | `/workbench/owner` | 项目、报告和归档只读查看。 |

部署后运行角色创建脚本，确保 MongoDB 中的后台角色矩阵、用户/单位目录和项目成员授权与登录账号一致：

```bash
cd backend

# 只预览，不写库
python scripts/create_roles.py --dry-run --json

# 本机 MongoDB 写入
AICHECK_MONGO_URL=mongodb://127.0.0.1:27017 \
AICHECK_MONGO_DB=aicheck \
python scripts/create_roles.py --project-id P-2026-HDCP-001

# Docker Compose 环境写入
docker compose exec api-service python scripts/create_roles.py --project-id P-2026-HDCP-001
```

脚本行为：

- 写入或更新 `admin_configs` singleton 中的 `orgUnits`、`users`、`permissionMatrix`。
- 写入或更新 `project_members`，同一项目、同一用户、同一角色重复执行时会合并 `nodeScope` 和 `actions`，不会插入覆盖性重复成员。
- 写入一条 `audit_logs` 记录，便于追溯部署初始化动作。
- 支持 `--roles admin,inspection` 只初始化部分角色；支持 `--project-id` 指定项目；支持 `--mongo-url` 和 `--db` 覆盖环境变量。

注意：当前登录账号仍由后端内置演示账号提供，脚本负责同步后台目录和项目授权。正式生产接入企业用户中心前，应替换默认密码策略和静态演示账号。

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

## 5. 前端构建与发布

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

## 6. OCR 部署说明

当前 OCR 服务启动命令：

```bash
uvicorn apps.ocr_service.main:app --host 0.0.0.0 --port 8010
```

OCR 调用链：

1. 前端创建 upload session。
2. 浏览器使用 MinIO signed PUT 上传文件。
3. 前端调用 upload complete。
4. `api-service` 写入 `documents`、`document_versions`、`knowledge_tasks`。
5. `worker-service` 消费 `ocr.parse_document`，从 MinIO 拉取文件，并调用 OCR 服务模块。
6. OCR 结果回写 `extracted_fields`、`knowledge_files`、`knowledge_chunks`、`evidence_links` 和任务状态。

真实 OCR 注意事项：

- `backend/apps/ocr_service/service.py` 会尝试导入 `/Volumes/Volume/project/agentdesign/mvp-system/backend/seal_ocr/pipeline.py`。
- 在 Docker 生产环境中，应把 `agentdesign` 的 OCR 代码和 `requirements/mvp-ocr.txt` 依赖合入 OCR 镜像，或通过 volume 挂载到相同路径。
- 如果导入失败，服务不会崩溃，但会返回 placeholder 结果，任务中心仍显示流程完成；这只适合联调，不适合生产验收。

## 7. LiteLLM 部署说明

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

如果 `OPENAI_API_KEY` 或供应商密钥无效：

- AI 复核任务会映射为 `AI_RUN_FAILED`。
- 向量化、模型对比等外部工具错误会映射为 `EXTERNAL_TOOL_FAILED`。
- 业务库保留 `ai_runs`、`llm_compare_runs` 等运行记录，LiteLLM 保存模型调用层日志。

## 8. 上线验证

后端 smoke：

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/workbench/projects

curl -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

for account in inspection contractor ndt owner admin; do
  curl -s -X POST http://127.0.0.1:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${account}\",\"password\":\"${account}\"}" | jq '.data.user.role, .data.user.defaultPath'
done
```

前端 smoke：

```bash
cd frontend
AICHECK_BASE_URL=https://aicheck.example.com pnpm playwright test e2e/aicheck-smoke.spec.ts --reporter=list
```

关键手工验证：

- 五类角色登录后能进入各自默认面板；业务角色访问 `/admin/overview` 会回退到自己的工作台。
- 项目列表、项目树、节点包、报告、归档页面能正常加载。
- 管理后台项目成员授权后，业务角色节点范围外 mutation 返回 `FORBIDDEN`。
- 创建 upload session 返回 MinIO signed PUT URL。
- 上传完成后 `GET /api/knowledge/tasks` 能看到 OCR/切片/向量任务。
- 触发 AI 复核后 `GET /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-runs` 能看到运行记录。
- 报告导出任务从处理中变为可下载。

## 9. 备份与恢复

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

## 10. 升级与回滚

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

## 11. 常见问题

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

检查 `ocr-service` 日志。如果看到 `agentdesign OCR pipeline not importable`，说明当前镜像没有真实 OCR 依赖，需要把 `agentdesign` OCR 代码和 PaddleOCR 相关依赖打进镜像。

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
