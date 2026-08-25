# test2 工程 AI 全审查入口

工程：TEST项目二｜珠海新建化工区管道气站

工程 ID：P-TEST-OCR-002

本工程必须按照 `ai_full_review_prompt.md` 执行。项目清单位于：

`evidence_shards/test2/manifest.json`

一次只处理一个业务节点的一个 EvidenceShard。每个节点的输入范围是 EvidenceSnapshot 中的全部当前有效历史挂接资料；后上传资料不得脱离此前资料单独判断。

执行完成条件：项目 manifest 中每个节点的全部 shard 都已处理，节点 coveragePassed=true，节点 FindingDraft 已通过 projectId/nodeId/reviewRunId 回挂，且所有结果等待人工确认。
