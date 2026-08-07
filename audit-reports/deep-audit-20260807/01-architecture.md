# 阶段 1 · 架构与契约边界审计

审计对象：backend 服务拆分、状态管理架构、分层依赖、契约一致性。
结论先行：**当前架构是「内存态 + 写穿透持久化」的单副本设计**，功能正确性有测试保障，但存在 4 个结构性问题，其中 A-1（内存驻留全量状态）在「几千页/项目、周期一年」的业务规模下会成为硬瓶颈。

---

## A-1 · 全量业务状态驻留 API 进程内存，容量与一致性双重风险 【P1】

**证据**：
- `repo.state` 是进程内 dict，承载全部业务集合（[repository.py:237-260](../../backend/libs/db/repository.py)）；Postgres/SQLite 仅作写穿透备份（`flush_mutation_records`，[repository.py:4586](../../backend/libs/db/repository.py)）。
- **OCR 解析结果全文**（pages/fragments/layoutBlocks/tables/fields）作为 `ocr_parse_results` 记录常驻内存，`insert(0)` 追加、无淘汰机制（[repository.py:1606-1657](../../backend/libs/db/repository.py)）。
- API 进程按租户一次性加载后标记 `mark_tenant_loaded`，此后仅对审查相关的 `REVIEW_LIVE_STATE_KEYS`（23 个集合）在特定端点做节流 0.4s 的选择性重载（[routes.py:264-293](../../backend/apps/api/routes.py)）。

**业务影响**：
1. **容量**：按业务口径单项目几千页、周期一年、多项目并行，OCR 全文常驻内存的增长没有上界；worker 与 API 各持一份。
2. **一致性**：worker 写库后，API 内存中**非** `REVIEW_LIVE_STATE_KEYS` 的集合（documents/versions/bindings/tree_nodes 等）不会自动刷新——仅个别端点手工 `load_state({"documents",...})`（routes.py:13708）。任何遗漏刷新的读端点都会向监检人员展示过期数据（如 OCR 已完成但界面仍显示处理中）。
3. **扩展性**：API 单副本约束是隐式的（uvicorn 无 workers 参数、compose 单实例）。任何人加副本或加 `--workers` 会静默引入双写不一致，代码中没有防护或注释说明这一约束。

**建议**：
- 短期：把 `ocr_parse_results` 大 payload 移出内存态（MinIO/DB 存全文，内存只留索引元数据）；在启动处显式断言/文档化单副本约束。
- 中期：读路径逐步改为直接查询 Postgres，内存态只保留热点集合。

---

## A-2 · routes.py 巨石 + 双层数据访问口径并存 【P2】

**证据**：
- [routes.py](../../backend/apps/api/routes.py)：30,490 行、368 个路由、912 个函数。
- 路由层**直接**操作 `repo.state[...]` 共 315 处（其中写操作 82 处），与 `repo.add_audit()` 等方法封装并存——同一份数据存在两套访问口径，事务/审计/租户注入等横切逻辑只在方法封装一侧生效。
- 例：`save_review_opinion` 直接 `repo.state["review_opinions"].insert(0, opinion)`（routes.py:12039），绕过任何 repository 方法。

**影响**：新增字段/审计/租户逻辑时极易漏改一侧；30k 行单文件使任何 diff review 都昂贵。

**建议**：不做一次性重写。增量规则：新代码一律走 repository 方法；按业务域（inspection / documents / knowledge / review / admin）拆 routes.py，每次触碰某域时顺带迁移。

---

## A-3 · 分层依赖倒置：libs → apps 【P2】

**证据**（7 处）：
```
libs/mineru_ocr.py                        → apps.ocr_service.{engines,profiles,service}
libs/ocr_accuracy_pipeline.py             → apps.ocr_service.profiles
libs/document_audit_pipeline_comparison.py→ apps.ocr_service.profiles
libs/review_orchestrator/runtime_tools.py → apps.ocr_service.welder_certificate_tool,
                                            apps.api.cnse_routes, apps.api.std_samr_routes
libs/integrations/task_dispatcher.py      → apps.worker.tasks
```
另有实测确认的循环导入：`import libs.review_tools` 单独执行会触发
`review_tools ↔ review_orchestrator` 循环（必须先 `import libs.review_orchestrator` 才能用）。

**影响**：libs 无法独立测试/复用；导入顺序敏感是隐性 bug 源（新入口脚本按直觉 import 就会崩）。

**建议**：把被 libs 依赖的 apps 代码（profiles、welder_certificate_tool、cnse/samr 查询函数）下沉到 libs；`task_dispatcher` 用延迟导入已部分规避，保持并注释。

---

## A-4 · OpenAPI 契约严重漂移：24 条 vs 实际 313 条路径 【P1】

**证据**：`openapi/paths-*.yaml` 合计声明 **24** 个唯一路径；`routes.py` 实际注册 **313** 个唯一路径（368 个路由含方法重复）。覆盖率 ≈ 7.6%。

**影响**：
- 前端 `src/api` 与后端的对齐完全依赖人工与 `API_DOCUMENTATION.md`（20 万字 Markdown，无法机器校验）。
- 契约测试（test_contract.py，264 用例）测的是行为快照而非 openapi 一致性，无法发现「文档说 A、实现是 B」。

**建议**：从 FastAPI 自动导出 openapi 作为唯一契约源，替换手工维护的 24 条；CI 加 diff 检查。

---

## A-5 · 14 个 docker-compose 文件，生产口径不唯一 【P2】

`backend/` 下 14 个 compose 文件（deploy/backup/ocr-validation/qwen-official/remote-ai-services/...），`docker-compose.yml` 与 `docker-compose.deploy.yml` 均含完整服务栈。DEPLOYMENT.md（14 万字）描述了多套流程。哪份是生产权威只能靠口口相传。

**建议**：指定权威 compose + overlay 结构（base + env overrides），其余移入 `deploy/examples/` 并在 README 标注用途。

---

## 做对的部分（不需要动）

- 写路径有统一的 mutation 边界：`ConcurrentPersistenceError` → 409 + 状态回滚（main.py:271-288），配 ETag/If-Match 乐观锁。
- 幂等机制完整：Idempotency-Key + 指纹 + 租户隔离 scope。
- worker 每任务前 `load_state()` 重建视图，worker 侧一致性口径明确。
- 业务包边界：`require_published` + `pilotRules` 闸门实测有效（R35-R69 无法在正式复核中执行）。
