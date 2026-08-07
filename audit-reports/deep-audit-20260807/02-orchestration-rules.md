# 阶段 2 · 审查编排与规则正确性审计

审计对象：`libs/review_orchestrator/`、`libs/review_tools/`、`apps/review_worker/`、绑定表、人工结论通道。
所有发现均已用实际代码执行验证（非静态推测），验证脚本见文末。

---

## R-1 · 字段缺失被判为「不符合」，会误报施工单位 【P0】

**位置**：[business_tools.py:1851 `checked_result`](../../backend/libs/review_tools/business_tools.py) + `check_required` 等通用工具。

**实测**：
```
check_required(requiredFields=["a.b","a.c"], facts={"a":{"b":"X"}})  → failed
check_required(requiredFields=["a.b"],       facts={})               → failed
```

**业务口径**（已确认）：`NON_COMPLIANT` 仅在「证据充分且明确不满足」或「应交**文件本体**缺失」时成立；「资料不完整无法判断」应为 `INSUFFICIENT_EVIDENCE`。

**缺陷**：`checked_result` 不区分「字段缺失（OCR 没抽到）」与「字段有值但不合规」，一律 `failed`。OCR 漏抽一个字段（业务方确认这是常态）即误判不符合 → 误打回施工单位。文件本体缺失走 `failed` 是**正确**的，问题仅在字段级。

**建议**：`check()` 项区分 `missing` 与 `mismatch` 两种失败原因；聚合时「全部失败均为 missing」→ `evidence_insufficient`，存在 mismatch → `failed`。

---

## R-2 · `REQUIRES_HUMAN_REVIEW` 状态在聚合层被吞掉，五态退化为四态 【P0】

**位置**：[executor.py:475-503](../../backend/libs/review_tools/executor.py)。

**实测**：
```
aggregate_tool_results([{result: human_review_required}])   → evidence_insufficient
aggregate_atomic_results([{result: human_review_required}]) → evidence_insufficient
```
`aggregate_atomic_results` 根本不认识 `human_review_required`。全仓该值仅 6 处，5 处在
[r19_agent.py](../../backend/libs/review_orchestrator/r19_agent.py) 的私有聚合器里（R19 内部正确保留）。
**只有 R19 保住了这个状态，其余节点全部被折叠成「证据不足」。**

**业务影响**：监检人员无法区分「资料没交齐 → 催补件」和「资料齐但需专业判断 → 自己去看」，
这两个动作完全不同。业务方明确要求区分这两态。

**建议**：两个聚合器加入 `human_review_required` 分支，优先级放在 `evidence_insufficient` 之上、`failed` 之下；参考 `aggregate_r19_atomic_judgments`（该实现是正确范本）。

---

## R-3 · 工具执行故障伪装成业务结论，并掩盖已确认的不符合项 【P1】

**位置**：[executor.py:477-480](../../backend/libs/review_tools/executor.py)。

**实测**：
```
[{result: failed}, {status: failed}]  → evidence_insufficient
```
`execution_failed` 分支在检查业务结果**之前**返回：
1. 系统故障（工具崩溃/超时）被表述为业务判断「资料不足」→ 监检人员会去催施工单位补件，实际是服务问题；
2. 同一原子项内已产出的 `failed`（真实不符合）被抹掉 → **漏报**。

**建议**：执行故障走独立 `error` 通道（原子项标执行失败、不产出业务结论）；已产出的 `failed` 不被覆盖。

---

## R-4 · 证据锚定失效时仍输出「不符合」 【P1】

**位置**：同上聚合函数，`failed` 优先级高于 `evidence_insufficient`。

**实测**：
```
[validate_evidence_grounding → evidence_insufficient, check_required → failed]  → failed
```
`validate_evidence_grounding` 判定「结论无证据支撑」时，原子项仍输出 `failed`。违反通用执行原则
「证据、条款和结果关联」——无法回溯到页码/条款的不符合项，监检人员无法据此打回。

**建议**：grounding 工具的 `evidence_insufficient` 应作为一票否决（降级该原子项为 `evidence_insufficient` 并警告），或至少在输出上标记 `groundingFailed: true`。

---

## R-5 · 绑定表 `implementationStatus` 与实现完全颠倒 【P1·数据修正】

**位置**：[atomic_check_tool_bindings.yaml](../../backend/business_packs/engineering_inspection_v1/atomic_check_tool_bindings.yaml)。

**实测核对**（绑定表 194 条 vs `review_orchestrator`/`review_tools` 实际模块）：

| 规则段 | 实际实现 | 表中标注 |
|---|---|---|
| R12–R34（有专用 facts/tools/agent 模块） | ✅ 已实现 | `pilot_implemented`（109 条） |
| R35–R69（无任何代码模块） | ❌ 未实现 | `implemented`（85 条） |

标注方向 180° 相反。当前无运行时风险（`lifecycleStatus: draft` + `require_published` 闸门实测拦住 R35-R69），但作为能力清单完全误导。业务方已确认要改。

**附带核实（正面）**：pilotRules 中未接线的 R01/R02/R03/R06/R07/R09/R60/R61/R62 实测在空事实下全部输出 `evidence_insufficient`——失败关闭，不会误报。

---

## R-6 · 三套结论词汇不对齐；人工无法表达「证据不足」 【P1】

| 层 | 词汇 |
|---|---|
| 业务文档口径 | COMPLIANT / NON_COMPLIANT / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE / REQUIRES_HUMAN_REVIEW |
| 后端实现 | passed / failed / evidence_insufficient / not_applicable / human_review_required |
| 人工结论（[routes.py:11997](../../backend/apps/api/routes.py)硬校验） | 满足要求 / 需补正 / 不适用 —— **只有 3 个** |

- 文档五态大写词汇在全仓（前端+后端）零出现，纯纸面。
- 监检人员无法保存「证据不足」结论：AI 判 `evidence_insufficient` 后，人只能选「需补正」（语义更重，等于认定不符合）或「满足要求」。人工结论统计口径失真；按业务口径「历史结论作为节点级记忆」，喂给模型的历史标签也被扭曲。

**建议**：人工结论增加「证据不足/待补充」选项；建立五态 ↔ 实现词汇 ↔ 人工结论的唯一映射表并落码。

---

## R-7 · `save_review_opinion` 通道无审计留痕、不关联 AI 结论 【P0】

**位置**：[routes.py:11991 `save_review_opinion`](../../backend/apps/api/routes.py)。

**对比两条人工结论通道**：

| 通道 | 留痕 | 关联 AI 结论 |
|---|---|---|
| ReviewRun `human_decision`（[execution.py:3958](../../backend/libs/review_orchestrator/execution.py)） | ✅ humanDecision + review_event + feedback 记录 | ✅ |
| 检验工作台 `save_review_opinion` | ❌ 无 `add_audit` 调用 | ❌ opinion 无 aiRunId/aiSuggestedResult 字段 |

业务口径「人工推翻 AI 必须留痕」在第二条通道不成立。`adopt/reject_ai_suggestion` 虽有 `add_audit`，但只生成**草稿**；最终落库的 `save_review_opinion` 反而无痕。事后无法回答「这条结论 AI 原判什么、是否被推翻」。

**建议**：opinion 增加 `aiRunId` / `aiSuggestedResult` / `overriddenFromAi` 字段；保存时 `add_audit(before=AI结论, after=人工结论)`。

---

## R-8 · 活动重试从头重跑整个图，无步骤级断点 【P2】

**位置**：[activities.py:24 `run_review_graph_activity`](../../backend/apps/review_worker/activities.py) + [execution.py:1693](../../backend/libs/review_orchestrator/execution.py)。

活动超时（20 分钟 start_to_close）或瞬态失败后重试时，`execute_review_run_inline` 仅跳过终态/等待态，否则从 `load_context` 重跑全部 12 步（含 2 个 LLM 步骤）→ LLM 成本翻倍、结果可能不同。步骤有 `attempt` 计数（[execution.py:511](../../backend/libs/review_orchestrator/execution.py)），FDE 可见重试，无重复记录问题——影响限于成本与时延。

**建议**：低优先级。可按 `review_graph_nodes` 已 succeeded 的步骤跳过（上下文可从 details 重建的前提下），或仅对 LLM 步骤做结果缓存。

---

## R-9 · 硬编码假实现挂在正式路由上 【P2】

**位置**：[routes.py:7372 `batch-classify`](../../backend/apps/api/routes.py)。

```python
"suggestedNodeIds": [24 if "焊工" in doc["fileName"] else 16], "confidence": 0.82
```
文件名含「焊工」→节点 24，否则一律 16，置信度写死。返回结构完整、写审计日志，调用方无法分辨是 stub。几千页项目下会把绝大多数文件误挂到节点 16。

**建议**：接真实分类逻辑前，返回 `501` 或在响应中显式标注 `stub: true`，并把置信度置 null。

---

## 做对的部分（审计确认，不需要动）

- **Temporal 层工程质量高**：outbox/inbox 双表幂等、commandId 去重、payload SHA-256 完整性校验、租户/聚合 scope 校验、瞬态错误分类重试（[activities.py:73-283](../../backend/apps/review_worker/activities.py)）。
- **节点独立性符合业务口径**：一个 review_run = 一个节点，businessFacts 按 nodeId 独立构建，节点间零共享。
- **LLM 边界符合口径**：R12 agent 的 LLM 仅决定「是否请求人工核验」，不下结论；R19 的 LLM 语义判断结果经固定聚合器 `aggregate_r19_atomic_judgments` 产出（且该聚合器是唯一正确保留五态的实现）。
- **失败关闭**：未注册工具 → `compilable=false` → `evidence_insufficient`；未接线 pilot 规则空事实下不误报。
- **取消/恢复语义**：取消后恢复节点先前状态、同步 ai_run 状态、记录事件。

---

## 附：验证脚本

```python
# backend 目录，./.venv/bin/python
import libs.review_orchestrator  # 必须先导入（循环依赖，见阶段1 A-3）
from libs.review_tools.executor import aggregate_tool_results, aggregate_atomic_results
from libs.review_tools import dispatch_business_tool, compile_node_tool_plan, execute_node_tool_plan
from libs.review_orchestrator.runtime_tools import runtime_tool_catalog

# R-1
dispatch_business_tool("check_required", {"requiredFields":["a.b"], "facts":{}})   # → failed
# R-2
aggregate_tool_results([{"toolName":"a","result":"human_review_required"}])         # → evidence_insufficient
# R-3
aggregate_tool_results([{"toolName":"a","result":"failed"},{"toolName":"b","status":"failed"}])  # → evidence_insufficient
# R-4
aggregate_tool_results([{"toolName":"validate_evidence_grounding","result":"evidence_insufficient"},
                        {"toolName":"check_required","result":"failed"}])           # → failed
```
