# Jev Lab 分支：节点模板 → Qwen 出题 → Jev 选择（2026-09-23）

## 本轮实现

新 ReviewRun 的主路径现在是：完整的当前 OCR 与冻结节点模板进入
`qwen_compose_jev_questions`；Qwen 为每个适用原子项生成一条中立题目和
`passed / failed / evidence_insufficient / human_review_required / not_applicable`
五个选项；校验覆盖、结构及输入哈希后，`jev_decision` 把同一份完整 OCR 和
这些题目交给统一的 `jev-1.13.0` 客户端作答。Qwen 不提供答案，Jev 不自己出题。
规则层结果在本地保留供人工对照，Jev 结果成为 Lab 的节点建议，最终仍待监检员确认。
纯系统证据链接校验留给本地确定性工具，因为 OCR 不包含完整的系统证据引用图。

出题模型预设固定为 `qwen3.5-flash-2026-02-23`，可通过
`AICHECK_JEV_QUESTION_MODEL` 切换。选择 Flash 是因为该阶段只需输出结构化题目；
质量必须以同一批 OCR 的漏题、错误选项和暗示答案率验收，不能只凭价格决定。
阿里云[模型资料](https://help.aliyun.com/en/model-studio/qwen3-5-flash)和
[结构化输出文档](https://help.aliyun.com/en/model-studio/qwen-structured-output)
列出此模型及 JSON 能力；实际费用取决于调用区域和账单。

缺模板、最新 OCR 失败、超长、Qwen 缺题／截断／不可达、题目过期或 Jev
不可达时，不会绕过 Qwen 改用固定题直问 Jev；本次建议降为人工确认或证据不足。
节点 24／29 的多人对象尚未实现按人拆题，明确阻挡自动建议。当前没有独立监检真值，
Jev 置信度仍不作为通过门槛。
静态业务包含 **69 个节点模板、194 个原子项**，每个模板都有原子项；这只是
出题输入覆盖，不代表 69 节点均已完成真实模型验收。当前最多 67 个节点可进入
单对象出题路径，节点 24／29 明确待补按人拆题。

出境测试只对明示列入 `AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS` 的工程开放，
并同时要求 Jev 全局、资料出境及主判定开关。文件归属 Jev 的建议在原有选择器
按当前版本显示，人仍需手动保存挂载；既有绑定不会被模型直接改写。

## 实测的准确范围

此前在本轮用七项目快照 `P-TEST-OCR-002` 的真实 OCR 发出了 **4 次 Jev
请求**：节点 25 一次（20,005 字、1.305 秒），节点 13 三次（26,543 字、
1.311／1.335／1.634 秒）。它们证明 Jev API 连通，并揭示节点 13 的系统证据
链接题不能只靠 OCR 判；但当时的题目是固定原子题，**没有真实 Qwen 出题**。
因此这 4 次不得作为本计划的端到端实测，也不能推断准确率。旧私有报告保留在
`/Users/big67/.codex/aicheck-jev-eval/2026-09-23/`，未提交仓库。

当前本机的 QwenRuntime 公共配置为 `server`，但没有可用的服务器地址或
Qwen 测试凭据，本机 `127.0.0.1:4000` 也不可达。因此新的
**Qwen 真实出题 → Jev 真实作答尚未运行**。这一项必须在可用的测试模型连接
到位后，用同一份已获准出境的 OCR 重跑，记录 Qwen 实际模型、输出题目、
Jev 答案、两段耗时和供应商费用；当前不能宣称实战验收完成。

## 验证与复现

测试专用脚本 `backend/scripts/run_jev_primary_lab_case.py` 会唯读加载七项目快照，
在本机内存运行真实 `load_context → load_ocr_result → run_rule_engine`，再按
`qwen_compose_jev_questions → jev_decision` 顺序执行。发送 Jev 请求前会用生成的
题目核对预计请求数；只有 `--send --prompt-key` 才外呼。无 `--send` 的模式
只校验本地 OCR／规则输入，不声称已估算动态题目的 Jev 请求数。输出报告以
0600 权限写入私有位置，不更新正式数据库或历史 ReviewRun。

录制响应测试覆盖出题顺序、八道 R19 题、每项覆盖、额外答案字段拒绝、旧题、
OCR 最新失败、工程许可边界、Jev 不可达及系统证据闸。本轮后端完整测试
**5,495 passed、81 skipped、0 failed**；最后的异常回覆处理调整后，相关
后端测试 **91 passed**。前端单测 **107／107 个文件通过**，TypeScript 检查
通过；Ruff 棘轮 **286／286**。七项目节点 13 新路径的唯读输入预检成功，
3 份资料、26,543 OCR 字；无 `--send`，所以这次 Qwen、Jev 外呼均为零。
实机两模型连续调用与独立人工标注仍是单独验收项。
