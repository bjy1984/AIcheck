# 阶段 3 · 数据与检索链路审计

审计对象：embedding/向量检索、审查主链路的知识检索、OCR 事实修正能力、raw_vault/审计锚定。

---

## D-1 · 业务要求的「人工修正 OCR 事实」能力完全缺失 【P1·能力缺口】

**业务口径**（已确认）：OCR 抽错不重传，监检人员直接修改结构化事实并留记录，人工触发重跑本节点，不跨节点传播。

**现状**：全部 368 个路由中不存在任何「修正抽取字段/事实」的接口。相近的只有：
- `/fde/vector-corrections`（知识库向量修正，FDE 治理用，与业务事实无关）；
- `/actions/return-correction`（打回补正，是重传流程——恰是业务方说**不该**走的路）。

**影响**：OCR 错一个证书编号，唯一出路是让施工单位重新上传整份文件。与业务口径直接冲突，也是「几千页项目」下最高频的人工干预动作。

**建议**：新增节点级事实修正接口：`POST /projects/{pid}/nodes/{nid}/fact-corrections`
（字段路径、原值、修正值、修正人、时间戳），修正记录持久化并进入审计日志；重跑判定由人工显式触发；修正仅对本节点生效（符合节点独立原则）。

---

## D-2 · 哈希伪向量可静默混入知识索引，检索质量塌陷无告警 【P1】

**位置**：[tasks.py:505-533 `embedding_batches_for_chunks`](../../backend/apps/worker/tasks.py)。

三条路径写入向量库：
1. 远程 embedding 正常 → 真语义向量 ✅；
2. 远程失败且 `AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK=true` → **offline_hash_embedding**（字符哈希伪向量，无语义），有 `fallback_reason` 标记；
3. **EmbeddingClient 未启用 → 直接静默用哈希伪向量，无任何标记**（函数最后一个分支）。

哈希向量与真向量同为 1024 维、同表存储，仅 `index_version` 不同。查询侧
（[routes.py:28216 retrieval-test](../../backend/apps/api/routes.py)）会按 index_version 过滤——
配对逻辑本身正确，**但没有任何监控/告警指出「当前索引里有多少哈希伪向量」**。配置错误
（embedding 服务没配好）时系统照常运行，检索结果近似随机，用户无从察觉。

**建议**：路径 3 应视为配置错误直接拒绝（或强制要求显式环境变量确认）；知识管理页显示各 index_version 的向量占比；哈希向量占比 > 0 时在检索结果标注降级。

---

## D-3 · 审查主链路的知识检索是固定查询词的词法检索，向量索引未参与 【P2】

**位置**：[execution.py:2281-2293](../../backend/libs/review_orchestrator/execution.py)。

审查图 `retrieve_knowledge` 步骤的查询是固定模板 `f"{节点名} 审查依据"`、top_k=5、走
`retrieve_knowledge_clauses`（条款库结构化/词法检索）。pgvector 语义检索仅在
`/knowledge/retrieval-test`（交互测试端点）中使用，**不在正式审查链路里**。

**评估**：条款绑定已按业务口径冻结（`frozen_standard_clause_package`），主判定依据不靠检索，
所以这不是正确性缺陷；但 `rag优化方案.md` 描述的能力与实际主链路存在落差，
LLM 草稿生成步骤拿到的知识上下文质量受限于固定查询词。

**建议**：文档标注现状即可；若要提升 LLM 草稿质量，把 dense 检索接入 `retrieve_knowledge` 步骤并沿用 index_version 配对逻辑。

---

## D-4 · 非 1024 维 embedding 模型配置会被静默丢弃 【P2】

**位置**：[repository.py:4096, 4164](../../backend/libs/db/repository.py)。

`embedding_models.py` 注册了 2560 维（Qwen3-4B）与 4096 维（Qwen3-8B）模型档案，但：
- pgvector 表固定 `vector(1024)`；
- `flush_knowledge_vectors_to_pgvector` 对维度 ≠1024 的行 `continue`（静默跳过持久化）；
- `search_knowledge_vectors` 对维度 ≠1024 的查询向量直接返回 `[]`（静默空结果）。

配置切到大模型档案后：索引静默不落库、检索静默空——无报错、无日志。

**建议**：维度不匹配时显式报错；或表结构升级为按 index_version 分表/动态维度。

---

## 做对的部分（审计确认）

- **条款冻结快照**：review_run 创建时冻结 `clausePackageSnapshotHash`（[execution.py:415-425](../../backend/libs/review_orchestrator/execution.py)），判定依据可追溯到确切条款版本，符合「标准换版暂不考虑、冻结在审查时点」的口径。
- **raw_vault 完整性链**：canonical JSON + SHA-256 事件哈希 + payload 哈希（[raw_vault.py](../../backend/libs/raw_vault.py)），OCR 解析结果 `immutable: True` + inputHash/outputHash（[repository.py:1640-1645](../../backend/libs/db/repository.py)）。
- **审计锚定**：`audit_chain_anchors` 序列化哈希信封上链式锚定（[audit_anchor.py](../../backend/libs/audit_anchor.py)）。
- **检索配对逻辑**：查询 embedding 模型与 index_version 严格配对，降级路径有 reason 标记（除 D-2 路径 3 外）。
- **OCR provider 选择**：`AICHECK_OCR_DEFAULT_PROVIDER` + 每文件 `ocrOptions.provider` 覆盖，MinerU 专用队列隔离，与 README 声明一致。
