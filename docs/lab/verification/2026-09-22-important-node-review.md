# 重要节点审查：实现与验证

入口：监检工作台顶部，与「AI审查」「完整工作台」并列的「重要节点审查」。工程选择沿用工作台，视图参数为 `view=important`。

## 已实现

- 工程资料使用现有项目文件列表及访问权限，包含可访问的未绑定资料；显示名称、解析状态、原文入口，不显示上传来源或类型。支持搜索、跨页选择、仅看已选、监检人员上传。
- 12 个节点按设计文件、元件与材料、焊接分组。名称/所选版本 OCR 内容关键词和已有绑定用于推荐，推荐不等同于适用性或资料完整性判断。允许手动勾选节点、调整每个节点本次采用的文件。
- 启动时逐节点建立异步任务，冻结文件版本与服务端规则快照。不建立永久节点绑定，不自动改变正式业务结论。重复提交沿用既有幂等机制；创建失败按节点展示。
- 当前提交只显示本批成功建立的任务；重新进入时可读取各节点最近任务。结果区区分执行状态和业务结论，显示真实核查留痕、辅助意见、证据入口和文件更新提示。
- 审查规则抽屉读取 v3 原文。历史任务查看冻结的规则。原文入口复用 EvidenceLocatorDialog，携带固定 documentVersionId 和证据页码。

## 服务端接入

新路由在 `backend/apps/api/important_review_routes.py`，同时注册根路径和 `/api` 前缀：

| 方法 / 路径后缀 | 用途 |
| --- | --- |
| GET `/projects/{id}/inspection/important-review` | 授权节点规则及环境开关 |
| POST `…/analyze` | 所选文件的只读节点推荐 |
| POST `…/nodes/{nodeId}/runs` | 复用 ai_recheck，强制异步专项辅助审查 |
| GET `…/runs` | 当前可访问的各节点最近专项任务及实际结果 |

上传复用既有 upload-session → signed PUT → complete。执行复用现有 OCR + LLM、任务派发、ReviewRun、证据包和结果链路。前端不持有模型凭证。

`backend/skills/important-node-review/` 保存服务端 skill 和 v3 参考文档。运行时仅加载对应节点章节，按内容哈希冻结版本，传递至 ReviewRun 和模型任务提示；浏览器不能指定规则正文。参考文档与 `docs/业务节点描述v3.md` 的一致性由测试约束。

沿用既有 `AICHECK_WORKSTATIONS_ENABLED=true` 开关；API 与 worker 应保持配置和代码版本一致。未启用时页面会说明原因并禁用审查。实际执行还依赖现有上传存储、OCR、异步 worker 和模型服务正常配置。

## 验证与边界

- 后端指定回归 65 项通过：包含无绑定资料发起、幂等、真实登录后的节点授权/成员撤权、版本冻结/变更、快照重放、页码范围兼容及单体规模约束。12 个节点均通过真实上传 API → OCR 结果入库 → 异步执行图 → 结果查询的参数化测试；此层使用确定性模型替身验证流程和规则注入。
- 前端全量单元测试 107 个文件通过，vue-tsc、改动组件 ESLint/Stylelint 和静态可操作性检查通过。
- 生产构建通过，产物 `frontend/dist-pro/`。本机默认 Node 堆内存不足，重试使用 `NODE_OPTIONS=--max-old-space-size=4096 ./node_modules/.bin/vite build --mode pro`；未修改项目构建配置。
- Playwright 组件检查使用隔离 API fixtures，验证上传三步、跨页选择、节点推荐、规则抽屉、提交参数、结果、原文入口、视图切换保留选择及工程切换清理。
- 完整工作台另通过真实 FastAPI 登录、上传、下载、节点分析、任务创建、结果读取接口验证。合成的两页中文 PDF 经真实 MinerU 解析得到 14 个片段，真实千问调用返回 3 条辅助意见，R04 执行完成并进入待人工复核；规则快照确实进入执行链路。浏览器确认 PDF 渲染结束，并从第 1 页切换至第 2 页。无浏览器异常或失败 API 请求。
- 后端变更幂等和权限动作覆盖检查通过（missing=0）。新 Python 文件 Ruff 通过；已修改旧文件相对 HEAD 没有新增 Ruff 告警。全仓 Ruff 基线检查仍有本分支既存超基线告警，未放宽基线。
- 业务 v3 全部要求已作为节点审查指令接入，但这不意味着每条要求都新增了确定性判定程序。已有核查项通过不能自动推导整个节点符合；未覆盖项保留人工复核。
- 联调使用本地种子账号、内存仓库和临时文件存储，以线程队列替代消息代理，但执行实际审查编排和模型调用。未访问生产业务数据库、未上传真实工程资料、未执行生产部署；生产 PostgreSQL / Celery 等运行环境验收不在本次本地联调范围内。

## 本地凭证与复现

SSH 跳板及目标机配置已安装到 `~/.ssh/aicheck/`，密钥权限为 600。服务器完整运行配置已同步到 `backend/.env`，核对内容哈希且权限为 600，文件被 Git 忽略。真实服务联调仅取模型和 MinerU 配置，不加载生产数据库配置。

复现浏览器检查（frontend 目录，先启动 Vite）：

```sh
./node_modules/.bin/vite --mode live --host 127.0.0.1 --port 4407
node e2e/important-review/check.mjs
```

测试入口 `/e2e/important-review/index.html` 仅用于组件验证，不是正式业务入口。截图和日志在 `output/important-review/`。

完整工作台联调另开终端，从仓库根目录启动隔离后端：

```sh
PYTHONPATH=backend backend/.venv/bin/python frontend/e2e/important-review/backend.py
```

需要真实 MinerU 和千问时增加 `--live-providers`，会使用 `backend/.env` 中对应服务的凭证并产生实际调用。默认模式不调用外部模型。再从 frontend 目录运行：

```sh
VITE_API_PROXY_TARGET=http://127.0.0.1:4410 ./node_modules/.bin/vite --mode live --host 127.0.0.1 --port 4407 --strictPort
node e2e/important-review/check-live.mjs
```

同一后端进程已有已完成的 R04 联调任务时，可加 `--existing` 仅复查结果、原文渲染/翻页和视图切换，避免重复模型调用。`full-workbench-report.json` 记录真实调用标识及结果数量，不记录凭证。
