# AIcheck 深度审计报告（2026-08-07）

- 基线 commit：`8ec3f56`（main）
- 审计范围：代码逻辑 + 业务逻辑（按已确认的业务口径基线，见 [00-baseline.md](00-baseline.md)）
- 方式：只读审计；关键结论均以实际运行代码验证，验证脚本随报告附上
- 分报告：[00 基线](00-baseline.md) · [01 架构](01-architecture.md) · [02 编排与规则](02-orchestration-rules.md) · [03 数据与检索](03-data-retrieval.md) · [04 安全与角色](04-security-roles.md) · [05 前端](05-frontend.md) · [06 第二轮横切面](06-second-round.md)

## 执行摘要

存量测试全绿（1327 收集 / 抽样 395 通过 / vue-tsc 通过），工程基础扎实：Temporal 编排、
raw_vault 哈希链、条款冻结快照、幂等与乐观锁、上传清洗都达到生产水准。

**但审查结论的聚合语义与已确认的业务口径存在系统性偏差**——这是本次审计最重要的发现群
（R-1/R-2/R-3/R-4）：字段缺失被判「不符合」会**误报**施工单位；`REQUIRES_HUMAN_REVIEW`
被聚合层吞掉使五态退化为四态；工具故障伪装成业务结论并能**掩盖真实不符合项**。
这些缺陷全部有存量测试覆盖却未被发现，因为测试断言的是实现行为而非业务口径。

另有两个业务要求的能力缺失：人工推翻 AI 的留痕（`save_review_opinion` 通道无审计）、
人工修正 OCR 事实的接口（完全不存在）。

## 发现清单（按优先级）

| # | 级别 | 发现 | 位置 | 报告 |
|---|---|---|---|---|
| R-1 | **P0** | 字段缺失被判 failed，误报不符合项 | business_tools.py:1851 | [02](02-orchestration-rules.md) |
| R-2 | **P0** | REQUIRES_HUMAN_REVIEW 被聚合层折叠，五态退化四态（仅 R19 幸免） | executor.py:475-503 | [02](02-orchestration-rules.md) |
| R-7 | **P0** | save_review_opinion 无审计留痕、不关联 AI 结论，违反「推翻必留痕」口径 | routes.py:11991 | [02](02-orchestration-rules.md) |
| R-3 | P1 | 工具执行故障伪装业务结论，掩盖已确认的 failed | executor.py:477 | [02](02-orchestration-rules.md) |
| R-4 | P1 | 证据锚定失效时仍输出「不符合」 | executor.py:475 | [02](02-orchestration-rules.md) |
| R-5 | P1 | 绑定表 implementationStatus 与实现 180° 颠倒（85 条误标 implemented） | atomic_check_tool_bindings.yaml | [02](02-orchestration-rules.md) |
| R-6 | P1 | 三套结论词汇不对齐；人工无法保存「证据不足」 | routes.py:11997 | [02](02-orchestration-rules.md) |
| D-1 | P1 | 人工修正 OCR 事实能力完全缺失（业务明确要求） | 无对应路由 | [03](03-data-retrieval.md) |
| D-2 | P1 | 哈希伪向量可静默混入知识索引，无告警 | tasks.py:505-533 | [03](03-data-retrieval.md) |
| A-1 | P1 | 全量业务状态（含 OCR 全文）驻留内存，容量/一致性/扩展三重约束 | repository.py | [01](01-architecture.md) |
| A-4 | P1 | OpenAPI 契约覆盖率 7.6%（24/313 路径） | openapi/ | [01](01-architecture.md) |
| S-1 | P1 | 认证默认关闭且关闭时授权四层同时归零 | main.py:372 | [04](04-security-roles.md) |
| F-1 | P1 | 前端零处理五态词汇，与 R-2/R-6 联动 | Workbench.vue | [05](05-frontend.md) |
| A-2 | P2 | routes.py 巨石 + repo.state 双口径访问（315 处直访/82 处直写） | routes.py | [01](01-architecture.md) |
| A-3 | P2 | 分层倒置 libs→apps（7 处）+ 循环导入 | libs/ | [01](01-architecture.md) |
| A-5 | P2 | 14 个 compose 文件生产口径不唯一 | backend/ | [01](01-architecture.md) |
| R-8 | P2 | 活动重试整图重跑，LLM 成本翻倍 | activities.py | [02](02-orchestration-rules.md) |
| R-9 | P2 | batch-classify 硬编码假实现挂正式路由 | routes.py:7372 | [02](02-orchestration-rules.md) |
| D-3 | P2 | 审查主链路知识检索为固定词词法检索，向量索引未参与 | execution.py:2281 | [03](03-data-retrieval.md) |
| D-4 | P2 | 非 1024 维 embedding 配置被静默丢弃 | repository.py:4096 | [03](03-data-retrieval.md) |
| S-2 | P2 | 5 个高敏读端点无 handler 层防御，单靠中间件正则 | routes.py | [04](04-security-roles.md) |
| S-3 | P2 | 角色级读裁剪未实现，节点范围内四方全可见（需业务确认） | routes.py | [04](04-security-roles.md) |
| F-2 | P2 | Workbench.vue 9231 行单文件 | frontend | [05](05-frontend.md) |
| F-3 | P2 | e2e 仅 1 条 smoke，主审查链路无覆盖 | frontend/e2e | [05](05-frontend.md) |
| S-4 | P3 | auth 关闭时审计日志身份可伪造等 | routes.py | [04](04-security-roles.md) |
| F-4 | P3 | 400ms 轮询与后端 0.4s 节流共振 | AIReviewB | [05](05-frontend.md) |

## 第二轮发现（横切面探查，2026-08-07 补充）

| # | 级别 | 发现 | 位置 | 报告 |
|---|---|---|---|---|
| N-1 | **P0** | 人工结论「不适用」把节点置为「需补正」，制造错误整改指令 | routes.py:12039 | [06](06-second-round.md) |
| N-2 | P1 | AI 建议主结论恒为「需人工确认」，确定性判定不上卡片 | execution.py:1876 | [06](06-second-round.md) |
| N-3 | P2 | 置信度全硬编码（0.82/0.55/0.5/0.68），伪指标 | execution.py:3226 等 4 处 | [06](06-second-round.md) |
| N-4 | P2 | 节点状态机无转移校验，15 处 set_node_status 各自为政 | repository.py:791 | [06](06-second-round.md) |
| N-5 | P2 | 多租户重启后非 configured 租户数据不可见 | repository.py:3088 | [06](06-second-round.md) |
| N-6 | P3 | If-Match 缺省即放行，乐观锁依赖客户端自觉 | routes.py:2243 | [06](06-second-round.md) |

## 建议修复顺序

1. **R-5**（数据修正，几分钟）+ **R-1**（单函数，当天）——立即消除最大误报源；
2. **R-2 + R-6 + F-1** 作为一个「五态打通」专项（后端聚合 → 人工结论选项 → 前端映射，含存量数据迁移）；
3. **R-7 + D-1** 作为「人工干预留痕」专项（推翻留痕 + 事实修正接口，同一套审计模型）；
4. **R-3 + R-4** 聚合器优先级重排（`error > failed(有grounding) > human_review > insufficient > not_applicable > passed`）；
5. **S-1**（默认值/启动警告）随下一次部署变更走；
6. P2 项进入常规迭代，A-1 需要先出容量评估再定方案。

## 未覆盖范围（明示）

- device_inspection_v1 / compliance_audit_v1：业务方确认缺检查项基准文件，列为「阻塞：待业务输入」，未审计其 YAML 内容正确性。
- Temporal/Postgres/MinIO 生产部署实操演练（备份恢复、故障切换）未实测，仅审了代码与测试存在性。
- LLM 判定质量（prompt 有效性、幻觉率）不在本次代码审计范围。

## 业务方决策与落地（2026-08-11）

三项待决事项已由业务方拍板：

| # | 决策 | 落地情况 |
|---|---|---|
| #11 认证默认值 | **翻转为默认开启** | 已改（`665b0fb`）。`AICHECK_REQUIRE_AUTH` 默认 true，漏配表现为「登不进去」而非「谁都能进」。开关原先散在 7 处各写一遍 `os.getenv(..., "false")`，已收敛为单一判据 `authentication_enforced()`，并有用例扫描 `apps/`+`libs/` 禁止 false 默认值回流。 |
| #18 报告读取权限 | **建设方只能看已定稿版本** | 已改（`665b0fb`）。owner 仅可读 已签发/已归档；监检/FDE/admin 不变。六个读取入口同口径：列表、owner 看板、工作台汇总计数、节点审计工作区、归档包、全局搜索；详情端点返回 404 而非 403（确认「存在一份未签发报告」本身也是信息）。 |
| #17 条款绑定标签 | **保持现状，先不动** | 未改。当前所有 AI 建议都需人工确认才生效，风险可控；待业务方明确要求再实现。 |

真实服务器实测（不带任何环境变量启动）：无凭证请求业务接口返回 401；伪造 `X-Role: admin` +
`X-User-Id` 请求头同样 401；`readyz` 报 `authRequired: true`；启动日志不再出现 SECURITY WARNING。
报告可见性：监检可见 9 份「复核中」报告，建设方一份都看不到。

## 浏览器验证补漏（2026-08-11）

用施工方账号在本地跑完整流程时，发现前几轮的 U-3/U-4/U-5 漏了施工方最常用的入口
——项目文件库台账行（已修，`0a30d25`）：

- **台账行不带 `bodyUploaded`**：从未上传成功的资料在台账里永远显示「上传中」，
  施工方看不出该重传，只有点了提交才会撞到 `DOCUMENT_BODY_MISSING`；
- **行内「提交」没有确认弹窗**：批量提交/退回补正/采纳建议三处都有，唯独这里直接发请求；
- **上传失败的行仍可点提交、且没有重传入口**。

现在：处理状态显示「上传失败」→ 操作列出现「重新上传」→「提交」禁用并提示
「该资料未上传成功，请先重新上传再提交」。真实上传的资料点提交会弹「提交资料给监检」确认框。

另：轮询期间实测 19 次 `live-status` vs 9 次 `package`（后者仅首屏与提交后主动刷新），
确认 U-6 的轻量轮询在生效。

## 其他已修

- **M-12**：建设方看板「总体进度」原为常量 `"42%"`，改为按监检节点办结比例计算
  （已通过/不适用计入已办结，停用不进分母；无可统计节点显示「—」而非 0%）。`4ede08a`
- **测试基线**：八个失败已按真因消除（状态污染 3 + 部署契约违约 3 + 时间炸弹 1 +
  响应构造竞态 1），另修本地 venv 缺 numpy / opencv-python-headless / psycopg[binary]
  导致的整模块漏跑。`f76f493`

当前基线：**1348 passed, 30 skipped, 0 failed**；`vue-tsc` 通过。
