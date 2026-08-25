# 单工程 AI 全审查编排 Prompt

本 Prompt 用于编排一个工程的节点级无损证据审查。每次模型调用只处理一个业务节点的一个 EvidenceShard；不得把整个工程压入单次上下文，不得跳过 manifest 中列出的 shard。

## 强制规则

1. 项目 manifest 是本次审查范围的权威清单。
2. 每个节点必须读取其 node manifest 和全部 shard。
3. 节点输入必须包含该节点截至 EvidenceSnapshot 的全部当前有效历史挂接资料，不能只审最后上传的文件。
4. shard 大小只控制模型调用次数，不能删除 OCR 原文、表格、字段、印章或证据链接。
5. 只有节点 coveragePassed=true 且全部 shard 执行成功后，才能聚合节点结果。
6. FindingDraft 必须保留 projectId、nodeId、reviewRunId 和 evidenceRefs，并始终 requiresHumanConfirmation=true。
7. 所有结果仅为监检审查草稿，不得自动改变正式业务状态。
