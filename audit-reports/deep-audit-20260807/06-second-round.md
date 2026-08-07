# 第二轮深度审计 · 横切面探查（2026-08-07）

第一轮按模块扫描；本轮按「容易藏 bug 的横切面」探查：状态机、结论映射链、硬编码指标、
多租户持久化、并发模型、YAML 数据一致性、日期解析、LLM 错误处理。

---

## N-1 · 人工结论「不适用」会把节点状态置为「需补正」 【P0】

**位置**：[routes.py:12039 `save_review_opinion`](../../backend/apps/api/routes.py)

```python
# result 允许值：{"满足要求", "需补正", "不适用"}（11997 行校验）
next_status = "已通过" if opinion["result"] == "满足要求" else "需补正"
repo.set_node_status(project_id, node_id, next_status)
```

三值结论被二值映射：**监检人员判「不适用」→ 节点状态变「需补正」**→ 施工单位被要求
补正一个根本不适用的节点。业务口径中 `NOT_APPLICABLE` 是独立终态（如境外材料节点对
纯国产项目），映射进「需补正」直接制造错误的整改指令。

**修复**：`不适用` → 独立状态（如「不适用」或「已通过(不适用)」），至少不能落入「需补正」。

---

## N-2 · 正式链路 AI 建议主结论恒为「需人工确认」，确定性判定结果不上卡片 【P1】

**位置**：[execution.py:1876](../../backend/libs/review_orchestrator/execution.py)

```python
ai_run.setdefault("suggestion", {}).update({
    "result": "需人工确认",          # ← 硬编码，与判定结果无关
    ...
    "confidence": ...0.82,
})
```

确定性工具的 `passed / failed / evidence_insufficient` 只写入 `rule_check_results`
（execution.py:2232），而前端主卡片渲染的 `suggestion.result`（Workbench.vue:1043/1569）
**永远是「需人工确认」**。监检人员要在证据链/规则明细里翻才能看到真实判定——
「AI 建议结论」这个核心 UI 元素不携带任何判定信息。

这也解释了阶段 5 F-1 的现象（前端零处理五态：后端 suggestion 根本不输出五态）。

**修复**：`suggestion.result` 按固定映射携带聚合结果（passed→建议满足要求 / failed→建议不符合 /
insufficient→证据不足 / human_review→需专业判断），保留「最终由人确认」的定位不变。

---

## N-3 · 置信度全部硬编码，伪指标呈现给监检人员 【P2】

**证据**（全为常量，无任何计算）：

| 位置 | 值 |
|---|---|
| `build_finding_draft`（execution.py:3226-3236） | 0.82 / 0.55 / 0.5 |
| ai_run suggestion（execution.py:1878） | 0.82 |
| 本地降级路径（routes.py:8123） | 0.55 / 0.68 |
| batch-classify stub（routes.py:7373，第一轮 R-9） | 0.82 |

前端以「置信度 82%」展示（Workbench.vue:1569）并影响监检人员的信任度分配。
一个从未被计算过的数字以两位小数精度呈现，属于误导性指标。

**修复**：短期在 UI 隐藏置信度或标注「静态估计」；长期由 grounding 覆盖率 + 校验通过率派生。

---

## N-4 · 节点状态机无转移校验，15 处 set_node_status 各自为政 【P2】

`repo.set_node_status`（repository.py:791）无任何前置状态校验，15 个调用点
（部分提交/待审查/复审中/业务核验中/需补正/已通过…）互不知晓。已通过的节点可被
任意端点直接改回任何状态；并发场景（AI 复核完成 vs 人工打回同时到达）最终状态取决于
到达顺序。近期提交修的「submitted document lifecycle」只覆盖了 binding 状态，节点状态本身仍无状态机。

**修复**：定义节点状态转移表（合法 from→to 集合），`set_node_status` 校验并拒绝非法跃迁，记录 before/after 审计。

---

## N-5 · 多租户重启恢复缺陷：非 configured 租户的数据落库后不可见 【P2】

**位置**：[repository.py:3088-3118](../../backend/libs/db/repository.py) + [main.py:180](../../backend/apps/api/main.py)

- 写入路径：请求租户（JWT `tid`，`tenant_is_allowed` 白名单内）的记录以其 tenant_id 落库 ✅；
- 加载路径：`load_from_sync_postgres` **只按 `configured_tenant_id()`（环境变量）过滤加载**；
- main.py:180 对新租户触发 `load_state()` 后 `mark_tenant_loaded(claims.tid)` ——
  实际加载的是 configured 租户的数据，却把 claims 租户标记为已加载。

**后果**：多租户部署（`AICHECK_TENANT_MODE=shared` + 白名单多租户）下，进程重启后
非 configured 租户的数据在 DB 里存在但永远不会被加载——表现为「数据丢失」。
单租户部署（当前 compose 默认）不受影响。

**修复**：`load_from_sync_postgres` 按请求租户加载（参数化 tenant_id），或明确声明只支持单租户并移除多租户白名单机制。

---

## N-6 · If-Match 缺省即放行，乐观锁形同虚设（取决于客户端自觉） 【P3】

[routes.py:2243 `project_if_match_valid`](../../backend/apps/api/routes.py)：`if not if_match: return True`。
客户端不发 If-Match 头 → 并发写无冲突检测。前端目前发头，但任何脚本/第三方调用不发头即绕过。
配合 N-4（无状态机）放大丢失更新风险。

**修复**：对高风险写端点（结论保存、打回、归档）强制要求 If-Match。

---

## 本轮排除项（探查过、确认没问题）

| 探查面 | 结论 |
|---|---|
| 业务包三表一致性 | ✅ atomic_checks 194 = bindings 194，双向无孤儿；69 条款绑定 standardRef 全部命中 catalog.id |
| 条款包数据质量 | ✅ professionalClauses 带页码 locators + `visual_verified` 标记，冻结快照可回溯 |
| R19 LLM 输出校验 | ✅ 结果白名单、evidenceRef 必须已登记、bbox/quote 必填、confidence range 校验、conflict 拒绝 |
| LLM 调用错误处理 | ✅ 截断/空输出/非法信封分类抛错，token/成本/次数三重预算闸门（execution.py:2646-2658） |
| 日期解析 | ✅ 中文「年月日」/`.`/`/` 格式归一化后 fromisoformat，失败→insufficient 不误判 |
| 并发模型 | ✅ 每租户 asyncio 互斥锁串行化全部 mutation（main.py:148），写写不竞态；代价是单租户写吞吐上限（记入 A-1 语境） |
| Temporal 命令通道 | ✅（第一轮已确认）outbox/inbox + payload 哈希 + scope 校验 |
