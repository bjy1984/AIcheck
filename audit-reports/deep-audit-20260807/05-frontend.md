# 阶段 5 · 前端业务逻辑审计

审计对象：两套工作台、结论词汇链路、长任务交互、e2e 覆盖。
基线：`vue-tsc` 通过、lint 体系完整、`build:pro` 前置强制可操作性静态审计（工程化成熟度高）。

---

## F-1 · 五态词汇在前端零处理，结论展示完全信任后端字符串 【P1·随 R-6 联动】

**证据**：全前端源码中 `evidence_insufficient` / `human_review_required` / `not_applicable` /
`passed` / `failed` **零出现**；AI 结论直接渲染 `suggestion.result` 原始字符串
（[Workbench.vue:1043,1569,1588](../../frontend/src/views/AICheck/Workbench.vue)）。
人工结论选项与后端硬校验一致，只有「满足要求 / 需补正 / 不适用」。

**影响**：
- 后端聚合层把 `human_review_required` 折叠成 `evidence_insufficient`（见阶段2 R-2）后，前端无任何机会区分展示——两层缺陷叠加，监检人员在 UI 上永远见不到「需人工专业判断」这个状态；
- 修复后端五态时，前端没有映射层可承接，需同步开发（状态→中文标签→颜色→可选动作）。

**建议**：与后端 R-2/R-6 作为同一个修复项排期：前端建立结论状态枚举 + 映射表，人工结论增加「证据不足」选项。

---

## F-2 · Workbench.vue 9231 行单文件 【P2】

[Workbench.vue](../../frontend/src/views/AICheck/Workbench.vue) 9231 行（后端 routes.py 的前端镜像问题）。
`GenericReviewWorkbench.vue` 只有 559 行，说明抽象是可行的，但主工作台没有跟进。
两套工作台（表单式 / 对话式 2381 行）并存是业务确认的方向，不算问题；单文件规模是问题。

**建议**：增量拆分（按 tab/面板抽子组件），触碰哪块拆哪块，不做一次性重构。

---

## F-3 · e2e 覆盖仅 1 个 smoke 用例，主审查链路无端到端保护 【P2】

`e2e/` 目录仅 `aicheck-smoke.spec.ts`。「上传 → OCR → AI 复核 → 人工结论 → 打回/通过」
这条核心业务链没有任何 e2e 覆盖；后端契约测试（264 用例）测的是 API 行为，
前端交互回归完全靠人工。以 Workbench.vue 的体量，这是主要回归风险敞口。

**建议**：补 3 条链路级 e2e：施工方提交→监检查看 AI 建议→采纳/推翻→状态流转；OCR 失败态展示；补正打回流转。

---

## F-4 · 400ms 高频轮询 live trace 【P3】

[ConversationalReviewWorkbenchB.vue:461](../../frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue)
以 400ms 间隔轮询 agent trace；后端 `refresh_review_live_state_shared` 节流恰好也是 0.4s
（[routes.py:11330](../../backend/apps/api/routes.py)），意味着每次轮询都可能触发一次 Postgres 全集合重载
（23 个 REVIEW_LIVE_STATE_KEYS）。单用户可接受，多监检人员同时开对话工作台时后端反复重载。

**建议**：轮询间隔提到 1-2s，或后端节流窗口放大；长期换 SSE。

---

## 做对的部分

- 角色路由守卫 + 后端动作矩阵双层（前端 `permission.ts` 仅 UI 遮挡，后端为准——符合正确分层）。
- `X-Role` 头由登录态注入（[axios/index.ts:20](../../frontend/src/axios/index.ts)），与后端身份一致性校验配合。
- 多环境构建（base/live/dev/test/pro）+ mock 隔离清晰；`ensure-backend-ready` 脚本保证 live 联调一致性。
- token 用量统计有独立单测（`tokenUsage.test.ts`）；提交文档生命周期有专项测试（`inspectionSubmittedDocuments.test.ts`）。
