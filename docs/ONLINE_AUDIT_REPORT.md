# AIcheck 线上审计阶段报告

更新时间：2026-06-27 22:24:00 PDT

## 结论

本次审计结论为：**本机 live 审计环境已大幅推进，API/Mongo/MinIO/OCR/前端 e2e 均通过；LiteLLM DB-backed virtual key、预算和限流管理面已通过 live 探针；但 LiteLLM provider 仍不健康，Docker Compose 生产集群未验证，因此不能出具“生产无误”最终报告。**

已通过：

- 前端 live e2e：51/51 通过。
- 后端全量测试：118 passed。
- API 鉴权模式：`AICHECK_REQUIRE_AUTH=true`，`AICHECK_ENABLE_DEMO_USERS=false`。
- MongoDB replica set：事务探针通过。
- MinIO：signed PUT、preview signed GET、download signed GET 通过。
- OCR 服务：真实 agentdesign/PaddleOCR 管线可用，placeholder 关闭，上传对象 OCR 解析通过。
- LiteLLM：4001 已以 DB-backed 模式运行，模型别名 `default-chat`、`review-chat`、`embedding-default`、`compare-fast` 存在。
- LiteLLM 管理面：`--litellm-management-probes` 创建并删除临时 virtual key 成功，预算、RPM、TPM 设置通过。

未通过：

- LiteLLM `/health` 报 4 个 unhealthy endpoint。
- LiteLLM `default-chat` 实调返回 HTTP 401。
- LiteLLM `embedding-default` 实调返回 HTTP 401。
- 当前本机无 Docker CLI，无法验证 Compose 生产集群。
- `backend/.env` 仍缺失，生产密钥和 provider key 未落入标准部署配置。
- 当前 4001 LiteLLM 已连接本机 PostgreSQL；provider 不健康仍由无效/占位 provider key 导致。

## 本机服务状态

当前审计使用的本机服务：

| 服务 | 地址 | 状态 |
| --- | --- | --- |
| 前端 | `http://127.0.0.1:4000` | 已监听 |
| API | `http://127.0.0.1:8000` | 已监听 |
| OCR | `http://127.0.0.1:8010` | 已监听 |
| LiteLLM | `http://127.0.0.1:4001` | DB-backed 已监听，管理面通过，provider 不健康 |
| MinIO API | `http://127.0.0.1:9000` | 已监听 |
| MinIO Console | `http://127.0.0.1:9001` | 已监听 |
| MongoDB RS | `127.0.0.1:27018` | 已监听 |
| Redis | `127.0.0.1:6379` | 已监听 |

## 角色与面板

五个角色强密码登录、默认面板跳转和路由隔离已通过 live e2e。

| 角色 | 默认路径 | 面板 |
| --- | --- | --- |
| admin | `/admin/overview` | 管理后台 |
| inspection | `/workbench/inspection` | 监检工作台 |
| contractor | `/workbench/contractor` | 施工方工作台 |
| ndt | `/workbench/ndt` | 无损检测工作台 |
| owner | `/workbench/owner` | 建设方只读工作台 |

管理员还可进入 `/knowledge/overview` 知识库后台。业务角色访问后台路径会回落到自身工作台或被后端拒绝。

## Live 探针结果

完整严格探针命令：

```bash
cd backend
.venv/bin/python scripts/verify_deployment.py \
  --api-base http://127.0.0.1:8000 \
  --ocr-base http://127.0.0.1:8010 \
  --litellm-base http://127.0.0.1:4001 \
  --litellm-api-key '***' \
  --strict-production \
  --write-probes \
  --ocr-object-probe \
  --litellm-management-probes \
  --litellm-provider-probes \
  --json
```

2026-06-27 18:38 PDT 完整严格探针结果：`ok=false`。
2026-06-27 22:24 PDT 复跑 LiteLLM 管理面子集：

```bash
cd backend
.venv/bin/python scripts/verify_deployment.py \
  --api-base http://127.0.0.1:8000 \
  --ocr-base http://127.0.0.1:8010 \
  --litellm-base http://127.0.0.1:4001 \
  --litellm-api-key '***' \
  --strict-production \
  --litellm-management-probes \
  --json
```

结果仍为 `ok=false`，原因是 `litellm.health` 继续报告 provider unhealthy；但管理面探针已通过。

通过项包括：

- `api.health`
- `api.strict-production`
- `auth.gate`
- 5 个角色登录与 `/auth/me`
- `mongo.transaction-probe`
- `auth.admin-reads`
- `api.projects`
- `api.knowledge-tasks`
- `api.write-probes.signed-put`
- `api.write-probes.document-preview-get`
- `api.write-probes.document-download-get`
- `ocr.uploaded-object-parse`
- `auth.identity-spoof`
- `auth.action-bypass`
- `auth.read-scope`
- `auth.aggregate-scope`
- `ocr.health`
- `ocr.parse-contract`
- `ocr.bad-request`
- `litellm.models`
- `litellm.aliases`
- `litellm.management-probes`

失败项：

- `litellm.health`：HTTP 200，但 LiteLLM 报 `unhealthyCount=4`。
- `litellm.chat-probe`：HTTP 401。
- `litellm.embedding-probe`：HTTP 401。

说明：22:24 的最新复跑没有再次消耗 provider quota；provider 失败结论沿用 18:38 的 `--litellm-provider-probes` 结果，并且当前 `/health` 仍显示 4 个 unhealthy endpoint。

## 前端 E2E

命令：

```bash
cd frontend
AICHECK_BASE_URL=http://127.0.0.1:4000 \
AICHECK_VITE_MODE=live \
AICHECK_BOOTSTRAP_PASSWORD_ADMIN='***' \
AICHECK_BOOTSTRAP_PASSWORD_INSPECTION='***' \
AICHECK_BOOTSTRAP_PASSWORD_CONTRACTOR='***' \
AICHECK_BOOTSTRAP_PASSWORD_NDT='***' \
AICHECK_BOOTSTRAP_PASSWORD_OWNER='***' \
pnpm exec playwright test
```

结果：`51 passed (4.8m)`。

覆盖包括：

- 角色默认面板跳转。
- 管理后台和知识库后台子路由。
- owner 只读边界。
- 390px 移动宽度无横向溢出。
- live 业务错误映射。
- 施工方提交、绑定、上传、撤回、草稿恢复。
- NDT 底片、记录、报告、补正和提交。
- 管理员配置、授权、建项、权限矩阵、状态机、集成差异。
- 知识任务重试/取消、知识配置、多模型对比。
- 监检报告导出、详情重试、归档和只读切换。

## 质量门禁

已执行并通过：

- `cd backend && .venv/bin/python scripts/validate_deployment_config.py --strict-production --json`：通过。
- `cd backend && .venv/bin/python -m pytest tests/test_validate_deployment_config.py tests/test_check_96_preflight.py tests/test_verify_deployment.py tests/test_deployment_report.py -q`：40 passed。
- `cd backend && .venv/bin/python -m pytest -q`：118 passed，1 个第三方 deprecation warning。
- `python -m ruff check backend`：通过。
- `git diff --check`：通过。
- `cd frontend && pnpm ts:check`：通过。
- `cd frontend && pnpm build:pro`：通过，输出 `dist-pro`。

构建警告：

- Browserslist/caniuse-lite 数据偏旧。
- `mockjs` 依赖内部使用 `eval`。

## 本轮修复

- `verify_deployment.py`：LiteLLM `/health` 和 `/v1/models` 统一携带 Bearer key；严格识别 `unhealthy_count`，避免 HTTP 200 误判。
- `verify_deployment.py`：新增 `--litellm-management-probes`，通过创建/删除临时 virtual key 验证 LiteLLM DB-backed key、预算、限流管理面，且不输出 key 明文。
- `verify_deployment.py`：角色登录密码支持 `AICHECK_VERIFY_PASSWORD_*` / `AICHECK_BOOTSTRAP_PASSWORD_*`。
- `verify_deployment.py`：导出写探针使用 admin token，符合 `admin:export` 后端权限。
- `deployment_report.py`：递归展开 FastAPI `_IncludedRouter`，真实覆盖 142 条 mutation，修复 action/idempotency 静态审计漏扫。
- `routes.py`：知识任务列表将失败、排队、运行任务优先展示，避免失败任务被新任务挤出首页。
- `main.py`：Mongo transaction probe 不再对 Motor/PyMongo Database 做布尔判断。
- `frontend/e2e/aicheck-smoke.spec.ts`：live e2e 登录密码从环境变量读取；任务中心用例降低对固定持久状态的耦合；导出类型断言匹配中文 UI。
- 新增 `backend/scripts/reset_audit_mongo.py`：显式 `--yes` 才能重置本地/审计 Mongo 种子，并创建强密码角色账号。
- `backend/.gitignore`：忽略本地 LiteLLM Python 3.11 虚拟环境。
- `docker-compose.yml`：LiteLLM healthcheck 现在携带 `LITELLM_MASTER_KEY` 调 `/health`，并在 `unhealthy_count > 0` 时失败，避免 provider 不健康时 Compose 误报 healthy。
- `docker-compose.yml`：`litellm-service` 新增 `NO_PROXY/no_proxy`，默认 `127.0.0.1,localhost,::1,litellm-postgres`，避免 Prisma query-engine 本机 HTTP 健康探针被代理转发导致 DB-backed 管理面失败。
- `validate_deployment_config.py`：静态审计 LiteLLM healthcheck 必须带 Bearer key、检查 unhealthy provider，并要求 `NO_PROXY/no_proxy` 包含 `127.0.0.1` 和 `localhost`。
- 本机 4001 LiteLLM：已用 PostgreSQL `litellm` 数据库和 `NO_PROXY/no_proxy` 重启为 DB-backed 实例；管理探针通过。

## 生产预检

`python scripts/check_96_preflight.py --json` 当前仍为 `ok=false`：

- `runtime.docker`：docker CLI 不存在。
- `runtime.compose`：无法检查 Docker Compose。
- `env.file`：`backend/.env` 缺失。
- `env.required`：缺少 `AICHECK_AGENTDESIGN_HOST_PATH`、`AICHECK_JWT_SECRET`、`AICHECK_MINIO_SECRET_KEY`、`LITELLM_API_KEY`、`LITELLM_POSTGRES_PASSWORD`、`OPENAI_API_KEY`。
- `agentdesign.path`：未通过 `.env` 配置。
- `probe.command-ready`：上述阻塞未解决前不能宣称 96+ 生产验收。

预检同时提示当前默认端口已有本地 live 服务监听，包括 `4001`、`6379`、`8000`、`8010`、`9000`、`9001`、`27017`；这是本机审计环境正在运行导致，真正启动 Compose 前需要停止或调整端口。

## 风险判断

当前可以确认：

- 本机 live API、Mongo 事务、MinIO signed URL、OCR 对象解析、RBAC、状态写回、前端业务流程均可跑通。
- OCR 服务不是 placeholder，已接入 agentdesign 管线。
- 前端 51 条 live smoke 已覆盖主要角色面板和业务写回流程。

当前不能确认：

- LiteLLM 能调用真实 chat/embedding provider。
- LiteLLM DB-backed proxy 的 virtual key、预算、限流管理面可用；调用日志仍需在真实 provider 调用成功后再验。
- Docker Compose 生产集群可启动并健康。
- `.env` 标准部署配置已经具备真实生产密钥。

## 下一步

要生成“生产无误/96+ 线上验收通过”的最终报告，需要先完成：

1. 安装 Docker/Compose，并确认 `docker --version`、`docker compose version` 可用。
2. 创建 `backend/.env`，填入真实 `OPENAI_API_KEY`、`LITELLM_API_KEY`、`LITELLM_POSTGRES_PASSWORD`、`AICHECK_JWT_SECRET`、`AICHECK_MINIO_SECRET_KEY`。
3. 配置 `AICHECK_AGENTDESIGN_HOST_PATH` 指向包含 `mvp-system/backend/seal_ocr/pipeline.py` 的 agentdesign checkout。
4. 换入真实 provider key，确认 LiteLLM `/health` healthy，并通过 chat、embedding 和调用日志探针。
5. 重跑：
   - `cd backend && python scripts/check_96_preflight.py --strict-production`
   - `cd backend && python scripts/verify_deployment.py --strict-production --write-probes --ocr-object-probe --litellm-management-probes --litellm-provider-probes --json`
   - `cd frontend && AICHECK_VITE_MODE=live pnpm test:e2e:live`

上述全部通过后，才应生成最终“确定无误”报告。
