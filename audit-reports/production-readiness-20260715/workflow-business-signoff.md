# `failed_to_start` 工作流业务签字单

生成日期：2026-07-15

本单只用于业务确认。未经签字，不修改、不删除、不重新发起任何 ReviewRun。

## 待确认记录

| ReviewRun | 项目/节点 | 技术分类 | 已知来源 | 业务决定 |
| --- | --- | --- | --- | --- |
| `RRUN-1` | 未绑定 | `RECOVERY_DB_ONLY_NEVER_STARTED` | 生产事故 `INC-PROD-20260714-001` 的数据库恢复遗留记录 | 待签字 |
| `RRUN-REPLAY-2D7C8DAA` | `P-2026-HDCP-001` / `24` | `RECOVERY_DB_ONLY_NEVER_STARTED` | deployment verifier immutable replay probe | 待签字 |
| `RRUN-REPLAY-2F03A634` | `P-2026-HDCP-001` / `24` | `RECOVERY_DB_ONLY_NEVER_STARTED` | deployment verifier immutable replay probe | 待签字 |

三条记录均没有可核对的 Temporal Run ID。后两条明确标记为部署验证产生的不可变重放探针，不应自动当作真实业务审查重新执行。

## 每条记录的可选决定

- `接受并保留`：确认该记录仅用于事故/部署追溯，维持 `failed_to_start`，不重新发起。
- `重新发起`：由业务责任人确认项目、节点、输入文档版本和执行窗口后，另建新的 ReviewRun；不得覆盖原记录。
- `继续调查`：指定责任人和截止时间，在结论形成前保持原状。

## 签字要求

| 字段 | 填写内容 |
| --- | --- |
| ReviewRun |  |
| 业务决定 | 接受并保留 / 重新发起 / 继续调查 |
| 决定理由 |  |
| 业务责任人 |  |
| 技术复核人 |  |
| 签字时间 |  |
| 如需重新发起：输入版本和维护窗口 |  |

签字后仍需由变更执行人单独提交执行记录；本单本身不授权修改历史记录。
