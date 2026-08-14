# AI 审查运行告警组件抽取设计

## 背景

2026-08-13 的检验工作台改动合并后，`frontend/src/views/AICheck/Workbench.vue` 从基线 9875 行增长到 9989 行，触发 `test_monolith_ratchet.py` 的巨石文件门禁。新增行主要来自 AI 审查证据截断提示、运行失败提示及对应样式。

本次只做满足门禁所需的最小组件抽取，不改变检验工作台的业务流程、路由、请求或展示文案。

## 目标

- 将证据截断提示和 AI 运行失败提示从 `Workbench.vue` 移入独立组件。
- 保持现有视觉、文案、重跑行为和失败详情展开行为不变。
- 使 `Workbench.vue` 行数回到 `monolith-baseline.json` 限制以内。
- 保留 2026-08-13 两个分支以及当前 `main` 的既有功能。

## 非目标

- 不抽取完整的 AI 审查执行时间线。
- 不调整 `monolith-baseline.json`。
- 不重构 AI 审查数据模型、接口或状态管理。
- 不改变失败重试条件或证据预算判定规则。

## 组件边界

新增 `frontend/src/views/AICheck/components/AiReviewRunAlerts.vue`。

组件接收三个只读输入：

- `evidenceBudget`：证据预算信息；仅在 `truncated` 为真时显示截断提示。
- `failure`：AI 运行失败信息；存在时显示失败原因、建议动作和原始报错。
- `failureKindLabel`：由父组件根据失败类型计算的中文标签。

组件只向父组件发出一个 `retry` 事件。父组件继续持有并调用现有的 `handleAiRecheck`，因此网络请求、加载状态和业务错误处理均不迁移。

失败详情的展开状态属于纯展示状态，迁入组件内部并默认折叠。这样可以删除父组件中的 `aiFailureDetailExpanded`，减少无关耦合。

## 数据流

1. `Workbench.vue` 继续从当前 AI 运行记录计算 `aiEvidenceBudget`、`aiRunFailure` 和 `aiFailureKindLabel`。
2. 父组件把三个值传给 `AiReviewRunAlerts`。
3. 子组件根据输入决定是否渲染两个告警区域。
4. 用户点击“重跑本节点审查”时，子组件发出 `retry`。
5. 父组件接收事件并执行现有 `handleAiRecheck`。

## 样式

把 `.ai-truncation*` 和 `.ai-failure*` 规则原样迁入新组件的 scoped style。组件根元素不额外引入布局间距，确保在现有执行卡片中的位置和间距保持不变。

## 测试与验证

- 新增轻量组件契约测试，验证组件声明的输入和 `retry` 输出边界。
- 继续运行现有检验工作台、内嵌 AI Review、角色默认路由单测。
- 运行前端 TypeScript 检查和生产构建。
- 运行完整后端测试，重点确认 `test_monolith_ratchet.py` 恢复通过。
- 最终运行 `git diff --check` 并确认工作区只包含预期提交。

## 风险控制

- 类型采用组件所需的最小结构，不引入新的跨层依赖。
- 不把请求逻辑移入展示组件，避免改变错误处理和重试时序。
- 不使用共享状态；组件卸载后详情展开状态自然释放。
