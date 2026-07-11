# AIcheck 核心功能深度审计报告

## 结论

- 决策：**NO-GO**
- 真实综合分：**72/100**
- 基线：`bdd834860a28f99b16ce61f1c56b21fb18e01a63` (`audit-baseline-20260710`)
- 问题：P0 0、P1 4、P2 4、P3 0

分数不能覆盖硬门槛。当前存在 OCR 假成功、关键写链路超时、生产部署漂移和凭据轮换四项 P1，因此不能稳定上线。

## 批次得分

| 批次 | 范围 | 得分 | 状态 |
|---:|---|---:|---|
| 1 | 身份、权限与数据隔离 | 15 | PASS |
| 2 | 项目、资料与业务状态机 | 10 | FAIL |
| 3 | OCR、证据与数据真实性 | 5 | FAIL |
| 4 | AI、RAG 与 ReviewRun | 14 | PASS_WITH_RISK |
| 5 | NDT 专项闭环 | 8 | PASS_WITH_RISK |
| 6 | 人工结论、报告与归档 | 7 | PASS_WITH_RISK |
| 7 | 任务、存储与故障恢复 | 5 | FAIL |
| 8 | 前端操作与发布门禁 | 8 | FAIL |

## P1 阻断项

- **OCR-REAL-001**：OCR 主引擎失败后仍返回成功状态。上层可能把无原文定位、缺字段的 OCR 结果当作已完成，造成假就绪和错误审计证据。
- **CORE-PERF-001**：单体 JSONB 状态同步持久化导致写请求和启动超时。上传、OCR 调度和正式审计链路可能形成不可恢复等待、重复点击和持续 502。
- **DEPLOY-DRIFT-001**：生产部署与冻结基线存在漂移。测试结果无法证明线上运行的就是已审计版本，回滚和漏洞追踪不可复现。
- **CRED-ROTATE-001**：模型网关凭据曾进入进程命令行可见范围。凭据可能被同机用户或诊断工具读取。

## 已验证能力

- 641 backend tests passed
- 49 Playwright tests passed
- six-role targeted authorization tests passed
- knowledge and ROI audits scored 100
- Qwen official API, local embedding and ReviewRun probes passed
- Redis strict fail-closed and recovery passed
- pip-audit and pnpm audit reported zero known vulnerabilities
- 28 route/viewport visual checks reported zero violations
