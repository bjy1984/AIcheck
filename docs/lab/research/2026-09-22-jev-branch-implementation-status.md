# Jev v3 分支实施状态（2026-09-22）

分支：`codex/jev-integration-v3`。此文件记录代码已做和仍需验收的范围；研究数字仍以
[`2026-09-22-jev-plan-v3-final.md`](2026-09-22-jev-plan-v3-final.md) 为准。

## 已接入代码、未开放资料出境

- 第 2 期的新守卫：Jev state 只接收归属本工程的冻结文件版本；对同一事实有相反
  `passed` 的规则检查，会同时排除两边并留下冲突清单。GC2 样例有回归测试。
  单份文件超过 40,000 字会显式返回版本 ID，不截断原文。
- 第 3 期的表格分类：在 Temporal `review.llm` worker 上、事实构建前执行；仅对
  R24–R34 调用。表格类型、每行角色共用整份文件原文。`r24_r34_facts.py` 只接受
  固定 `jev-1.13.0`、与当前表格哈希匹配、把握值 ≥ 0.90 的分类；其余逐行回退
  原启发式。力学试验表不再作为 R25/R29/R32 的 WPS/PQR/热处理记录行；R26
  焊材证明的力学数据保留。
- 第 4 期的影子路径：Qwen 输出增加逐字摘自发现文本的 `claims`；Jev 用整节点原文
  核对。未取得监检校准时只保存 `jevClaimChecks`，不撤下发现。校准后如另行开启
  拒绝开关并配置阈值，被明确否定或原文没有的主张会从可见描述撤下，整条降级人工。
- 第 5 期的影子路径：每原子项保存 `jevSecondOpinions`，含结构化选择、
  把握值、与确定性层是否一致，以及仅供提示的支持页。原规则判定完全不变。
  原工作台已能显示第二意见并按分歧、低把握排序，但未校准时不会把该字段写入
  工作台的 `atomicCheckOutcomes`。
  进队列／出队列阈值必须在校准后显式配置，灰区沿用上次队列状态。
- 所有 Jev 请求固定 `jev-1.13.0`，只通过
  `AICHECK_JEV_ENABLED=true`、`AICHECK_JEV_DATA_EGRESS_APPROVED=true` 和全新
  `AICHECK_JEV_API_KEY` 三项同时具备，并单独启用对应阶段，才可发起。
  第 3/4/5 期分别用 `AICHECK_JEV_TABLE_CLASSIFICATION_ENABLED`、
  `AICHECK_JEV_CLAIM_SHADOW_ENABLED`、`AICHECK_JEV_SECOND_OPINION_ENABLED`。
  旧 `JEV_KEY` 不读取。
  inline 请求模式一律跳过新增步骤。测试用录制/伪造响应，不向外网发送工程资料。

## 发布前还缺什么

1. **正式资料出境合规决定与密钥轮换**。2026-09-23 用户允许 `test2/` 和七项目 OCR
   作为测试资料出境，已用测试资料评估；这不等于正式审查资料获批。提供给测试的密钥也
   出现在聊天中，不能作为生产密钥复用；全新密钥由运维放入
   `/home/dev-bjy/aicheck-secrets.env`。正式 Jev 开关仍保持关闭。
2. **33 题监检标注与阈值校准**。16 道分歧和 17 道 Jev 判通过的原始候选表未在本
   工作树中找到；`scratchpad/shadow/` 也不存在。只有研究报告，不能重造题目或宣称
   0.68／0.72 已经校准。标注后才能设置校准、拒绝和 UI 开关。
3. **上游两个生产缺陷**。GC2 覆盖结论冲突和节点 3 单位名称 `verified_mismatch`
   误报由原计划中的独立任务负责；本分支只阻止冲突结果进入 Jev state，不把两项
   业务缺陷记为修复完成。
4. **实机验收**。需要原始七项目影子产物或获准后的受控回放，核对 R25/29/32 的
   71 条假事实、219 格方向对照、逐句抓错率、R19 八项语义题及大文件分拆。
   单份超过 40,000 字的文件目前会跳过 Jev；不能宣称两格超长已补跑。
5. **费用优化与正式队列**。当前 Qwen 仍对所有进入原流程的节点生成发现；“只给人工
   队列生成解释”的省费改造尚未实施。R19 仍按现有语义路径裁决，Jev 暂不替换它。
6. **清单模式**。`AICHECK_REVIEW_PROMPT_MODE=checklist` 的清单结论受独立的条件一致性
   契约保护；本分支的逐句核对只针对自由发现模式。清单模式会明确记录
   `unsupported_checklist_mode`，不会擅自改写固定条件判定。

## 开关与验收顺序

先验收不出境的规则/表格回退测试；获得出境结论并轮换密钥后，先只开三项基础开关
跑影子数据。33 题经监检标注后，确定并记录拒绝阈值、人工队列进出阈值，再考虑设置：

```text
AICHECK_JEV_CALIBRATION_APPROVED=true
AICHECK_JEV_CLAIM_GATE_ENABLED=true
AICHECK_JEV_CLAIM_REJECT_CONFIDENCE=<经标注确认的值>
AICHECK_JEV_SECOND_OPINION_UI_ENABLED=true
AICHECK_JEV_QUEUE_ENTER_CONFIDENCE=<经标注确认的值>
AICHECK_JEV_QUEUE_EXIT_CONFIDENCE=<经标注确认且高于进入阈值的值>
```

研究计划中的 0.68/0.72 只是待校准候选。支持页只有 Jev 的定位建议，不能替代
现有 `evidenceRefs`。所有代码变更目前只在该分支，未部署。

## 本地验证记录

- Jev 单元测试、条件清单一致性和 P8/H5 清单回归：57 项通过（2026-09-23）。
- 新增 Jev 代码及测试的 Ruff 检查通过；前端单元测试 106 个文件及 Vue 类型检查通过。
- 此前的重点后端回归共 80 项通过。排除既有 `test_openapi_contract.py` 后可收集
  5,428 项；完整后端测试仍未跑通：该文件在收集阶段导入当前实现没有的
  `OpenApiContractError` / `validate_operation`。排除它的一次广泛运行在约 20% 处
  因本分支新增的图顺序断言失败而中断（当时为 1,112 通过、6 跳过、1 失败）；断言
  已修正且单独复测通过，但**不能据此声称全套后端测试通过**。
- 2026-09-22 的单元测试全部使用伪造/录制响应。2026-09-23 在用户允许后，另用
  合成资料及 `test2/` 两份完整 OCR 做了真实 Jev API 评估，详见
  [`2026-09-23-jev-test-evaluation.md`](../verification/2026-09-23-jev-test-evaluation.md)。
  只在评估进程内启用出境和影子开关；没有部署或开启正式裁决／UI 门禁。
