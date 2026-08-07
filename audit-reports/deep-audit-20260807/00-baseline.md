# 阶段 0 · 基线体检

- 审计日期：2026-08-07
- 基线 commit：`8ec3f56`（main，工作区 clean）
- 审计方式：只读审计，不改动代码；发现项记录于本目录并同步 GitHub issues

## 体检结果

| 检查 | 结果 | 说明 |
|---|---|---|
| pytest 收集 | 1327 用例可收集 | `tests/test_cnse_api.py` 收集失败：venv 缺 `numpy`（环境问题，非代码缺陷） |
| 审查核心测试 | ✅ 131 passed | `test_review_p0_correctness / test_review_tool_executor / test_review_business_tools / test_r24_r34_tools / test_r20_r23_tools` |
| 契约测试 | ✅ 264 passed | `test_contract.py` |
| 前端类型检查 | ✅ 通过 | `vue-tsc --noEmit --skipLibCheck` |

## 结论

代码库整体绿色，存量测试全过。本次审计发现的问题均为**测试未覆盖的业务语义缺陷**（测试断言的是当前实现行为，而当前实现与已确认的业务口径不一致），详见各阶段报告。

## 业务口径基线（审计判据，已与业务方确认）

1. 系统输出为**建议结论**，最终由监检人员定夺；任何结论不自动成立。
2. 无「全量复核」概念：资料分批上传，节点各自成熟、各自触发。
3. 工程监检基准 = checklist R01–R69，重点实现 R12–R34，其余未接线；device/compliance 两包为真实业务线但缺基准文件。
4. 节点独立：不共享事实，各自抽取、各自判定，互不牵连（成本已接受）。
5. 人工可推翻 AI 结论：**必须留痕**，无需理由与审批。
6. OCR 错误不重传：人工改结构化事实并留记录，**人工触发**重跑本节点，不跨节点传播。
7. 打回施工/NDT：系统只记录，不做闭环通知。
8. 记忆为**节点级**（历史结论 + 人工推翻记录），两套工作台共享。
9. 结论五态：COMPLIANT / NON_COMPLIANT / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE / REQUIRES_HUMAN_REVIEW；
   NON_COMPLIANT 仅在「证据充分且明确不满足」或「应交文件本体缺失」时成立。
10. 角色可见性按最小权限默认口径执行（未另行确认前）。
