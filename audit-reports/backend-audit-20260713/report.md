# AIcheck 后端 AI 审查与操作审计模块深度审计

## 结论

**NO-GO，聚焦审计得分 30/100。** 当前提交的自动证据门、规则工具和 LLM 输出校验有较好基础，完整后端测试也全部通过；但本次在现有测试之外复现了 6 项 P0 和 11 项 P1。跨项目/节点越权、Temporal 与数据库状态分裂、多进程丢更新及审计日志泄露均可直接破坏正式审查与审计真实性，不能通过测试总数抵消。

- 基线：`main@0b6da1b25fce9f639de81c616ce537b93ff0db3a`
- 范围：AI 审查主链、legacy recheck、ReviewRun/Temporal/LangGraph、FDE 审计投影、操作审计日志及共享鉴权/幂等/持久化
- 租户假设：同一实例服务多个组织
- 问题：P0 6、P1 11、P2 2、P3 0
- 产品代码或公共 API 修改：无
- 生产运行结论：未评估；按约定未访问预发布/生产，也未调用外部模型或真实 Temporal

## 评分

| 维度 | 得分 | 满分 | 结论 |
| --- | ---: | ---: | --- |
| AI 证据与规则正确性 | 14 | 25 | 自动门禁较强，但人工修正可绕过引用校验，draft 绑定集进入正式执行 |
| 鉴权与多租户隔离 | 2 | 20 | ReviewRun、AI Run、审计日志和幂等重放存在跨范围访问 |
| 工作流与状态一致性 | 3 | 20 | 启动失败假成功、signal split-brain、终态可重复翻转 |
| 审计日志完整性 | 2 | 15 | 非 append-only，缺安全失败事件和资源范围 |
| 可靠性与性能 | 4 | 10 | 全量快照会丢更新，live read 存在明显内存和延迟放大 |
| 测试治理与可观测性 | 5 | 10 | 套件规模大，但三项全路由安全门禁已空跑 |
| **合计** | **30** | **100** | **NO-GO** |

## P0 阻断项

| ID | 问题 | 已复现的结果 |
| --- | --- | --- |
| TENANT-001 | ReviewRun、AI Run、review-workbench 跨项目/节点 IDOR | nodeScope 仅含 24 的用户读取节点 40 Prompt、对 queued run 决策，并跨项目取消 ReviewRun |
| AUDIT-SCOPE-001 | 审计日志无租户/项目/节点隔离 | 非管理员可读取全局日志；项目接口返回相同全量结果 |
| IDEM-001 | 幂等缓存跨用户重放 | 无项目成员关系的第二用户使用相同 key 得到第一用户相同数据和 operationId |
| REVIEW-DISPATCH-001 | Temporal 启动失败被当成功 | dispatch=`failed_to_start`，API 仍 code=0，节点从“待人工确认”变成“业务核验中” |
| REVIEW-SIGNAL-001 | 人工决定与 signal 非原子，终态可反复覆盖 | signal=`failed` 时仍落 `accepted_by_human`；同一 run 可 edit→accept→reject |
| STATE-PERSIST-001 | 全量旧快照覆盖导致丢数据 | 临时 PostgreSQL 中 writer 2 刷新后，writer 1 已提交的 audit 和 ReviewRun 均消失 |

## P1 高风险项

| ID | 问题 | 核心影响 |
| --- | --- | --- |
| REVIEW-EVIDENCE-001 | 人工 edit 不重新验证证据/规则/知识引用 | 不存在的引用被持久化为 accepted finding |
| AUTH-JWT-001 | JWT 宽松解码不要求 exp/iss/aud/jti | 合法签名但不可过期、不可注销的 token 被接受 |
| REVIEW-PRIVACY-001 | 普通 ReviewRun 返回完整 promptAudit/OCR 上下文 | 系统 Prompt、证号、单位和文档内容可能泄露 |
| AUDIT-INTEGRITY-001 | 审计日志无 append-only/哈希链/签名 | 无法证明日志未被改写或删除 |
| AUDIT-COVERAGE-001 | 登录、拒绝、失败和限流不记审计 | 本地 330 条日志全部为“成功” |
| TEMPORAL-RETRY-001 | activity 吞异常导致 RetryPolicy 不生效 | 短暂故障直接变成最终失败 |
| PERF-STATE-001 | live read 全量加载全部状态 | 当前等价数据一次加载 8.91 秒、峰值 Python 分配约 618 MB，分页顺序不稳定 |
| ROUTE-GATE-001 | 三项全路由安全测试空跑 | 只看到 9 个 app 顶层条目，没有检查 335 个业务路由 |
| KNOWLEDGE-AUTH-001 | owner 可创建知识重建 preview | 无 `knowledge:manage` 仍可读取 5 个样本文件名 |
| ARCHIVE-001 | 已归档项目仍可重算资料打靶 | 新增运行记录，归档快照不再只读 |
| RULE-LIFECYCLE-001 | draft 工具绑定集进入正式执行 | 171 个 draft-set binding 全部编译，生命周期未进入执行计划 |

P2 为异常/健康可观测性不足和人工评论长度限制未真正落到持久化值。每项完整复现、影响和回归要求见 `findings.json`。

## 已验证的正向控制

- 完整后端测试：`882 passed, 1 skipped, 6 warnings in 29.64s`。
- 审查专项测试：`83 passed, 1 warning in 4.03s`。
- 前后端合同：237 个前端端点、683 个后端路由键、缺口 0。
- formal 模式在证据未就绪时会阻断，`pure_llm` 只能用于 advisory/gap-precheck。
- 非法、空或截断的 LLM 结构化输出会失败关闭。
- 自动草稿的 schema、证据、规则和知识引用门禁，以及缺事实/缺工具时的 fail-closed 聚合已有测试。
- 模型对照流水线保持 compare-only，不直接替换正式审查主结果。

这些正向能力未覆盖资源级 IDOR、分布式失败原子性、跨进程快照覆盖和审计不可抵赖性，因此不能支撑放行。

## 关键实测

1. 在内存 API 探针中，限制到节点 24 的 inspection 用户成功读取节点 40 ReviewRun 的 `promptAudit`、用节点 24 URL 读取节点 40 AI Run，并取消另一个项目的 ReviewRun。
2. 注入 `TEMPORAL_START_FAILED` 后，API 仍返回成功并推进节点；注入 `TEMPORAL_SIGNAL_FAILED` 后，数据库仍提交人工接受终态和 finding。
3. 两个用户共用同一 Idempotency-Key 时，第二用户虽然没有项目成员关系，仍得到第一用户缓存响应。
4. 在独立临时 PostgreSQL 16.10 中，两个 repository 从同一旧快照出发写入；后提交者执行全量刷新后，先提交者的 ReviewRun 和 audit 均被删除。
5. 将当前本地 SQLite 数据复制到临时 PostgreSQL 后，全量 `load_from_sync_postgres()` 读取 14,438 条 state 和 156 条 idempotency，耗时 8.91 秒，`tracemalloc` 峰值约 617.6 MB。
6. FastAPI 当前把业务路由放在 `IncludedRouter`；原有三项门禁遍历 `app.routes`，只看到 9 个顶层条目。直接遍历 API router 才发现 335 个路由和 171 个 mutation。

## 修复顺序与重新放行门槛

1. 先统一 run 资源授权：每个详情、决定、取消、重跑和列表都绑定 tenant/project/node；全局审计日志仅限专门审计角色；幂等缓存加入主体并在重放前重新授权。
2. 重构 ReviewRun 状态机：仅 `waiting_human_review` 可单次决定，使用 revision/CAS；Temporal start/signal 通过事务型 outbox 与数据库状态协调，失败不推进正式节点。
3. 移除全表 DELETE/重建，改为行级事务；业务写、审计事件和幂等记录同事务提交，并增加双进程交错写回归测试。
4. 将审计事件迁移到独立 append-only 存储，补齐失败/认证事件、tenant/project/node、before/after、IP/UA、哈希链和外部不可变锚定。
5. 人工 edit 重新执行证据、规则、知识和定位校验；业务端默认不返回原始 Prompt/OCR，FDE 使用字段级脱敏和短期授权。
6. ReviewRun/FDE/审计列表改为数据库条件查询和 `(createdAt,id)` keyset pagination，补齐复合索引。
7. 修复路由发现门禁并增加被检查路由数量断言；formal 模式拒绝 draft binding set；归档项目所有 mutation 统一走 guard。

重新放行要求：全部 P0/P1 关闭；新增回归用例通过；双进程 PostgreSQL 并发无丢写；真实 Temporal 启动、重试、signal/outbox 和 worker heartbeat 在隔离预发布验证通过；审计日志跨租户隔离及篡改检测通过。

## 范围限制

- 未访问预发布或生产，未创建外部业务数据。
- 本地 PostgreSQL 仅使用创建后立即删除的独立临时数据库；现有 SQLite 只读。
- 本机没有 Temporal 服务，相关失败通过确定性 patch 注入；因此没有给出生产运行 PASS。
- 未重新认证 OCR 识别精度、前端体验或 171 条行业规则内容本身；仅审计它们进入后端审查链后的版本、证据与状态约束。
- 本次只生成审计产物，没有修改产品代码、API、数据库 schema 或配置。
