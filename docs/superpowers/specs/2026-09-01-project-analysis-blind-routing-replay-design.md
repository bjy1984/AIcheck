# “测试项目三”全工程分析证据路由盲测回放设计

## 1. 目标

针对本地项目 `P-2026-FDBB4B`（“测试项目三”）实现并真实运行三组隔离回放：

- A：沿用当前 `node.fileRefs` 硬绑定证据边界；
- B：完整 OCR 分段 Map/Reduce 项目级 LLM 路由；
- C：规则、关键词与真实向量 Top 8 召回，再由项目级 LLM 路由。

三组使用同一冻结项目快照、同一正式审查模型、同一输出 Schema 和相同生成参数。实验不建立人工金标准，不限制 LLM token 消耗，以匿名盲评、确定性引用校验、组内稳定性和运行成本比较相对效果。

## 2. 非目标

- 不把盲评结果表述为绝对“准确率”；
- 不修改正式项目资料、节点挂接、节点状态、审查意见或既有一键分析运行；
- 不在本轮加入 CNSE 单位/人员查询、证书核验或标准查新 Tool；
- 不用离线哈希向量冒充语义向量；
- 不优化生产 UI，本轮交付是可复现的实验运行器、证据和报告。

资质查询 Tool 作为胜出路由确定后的第二阶段实验单独实施。

## 3. 已确认的样本事实

实验启动时重新读取并冻结，当前基线为：

- 项目文件：23 份；
- 合格候选池：23 份，均为“上传成功且当前版本有效”；
- 完整 OCR：23/23；
- 当前已向量化：0/23；
- 当前有效挂接：36 条，覆盖 30 个业务节点；
- 最近一次真实一键分析：`PARUN-610C714411540742`；
- 原运行只携带 9 份唯一文件语料；
- 原运行供应商实报输入：68,961 tokens；
- 不可变请求快照：`PASNAP-EE082552EFF13E99`。

候选池只包含同时满足以下条件的文件：

1. 属于 `P-2026-FDBB4B`；
2. `fileStatus` 为上传成功态；
3. `currentVersionId` 指向存在且 `isCurrent=true` 的版本；
4. 当前版本存在对象存储键；
5. 文件和版本未删除、未作废。

是否提交、当前挂在哪个节点，不作为候选池限制。

## 4. 实验隔离与冻结

运行器先生成 `ExperimentSnapshot`，至少包含：

- 项目、业务包和节点规则快照；
- 30 个节点的 `criteria`、`checkMethod` 和 `configuredRequirements`；
- 23 份候选文件的当前版本、OCR 原文和内容哈希；
- 原 `node.fileRefs`；
- 模型路由版本、Prompt 版本和生成参数；
- Embedding 模型、索引版本和向量维度；
- 实验代码 Git SHA。

快照写入 `output/project-analysis-routing-replay/<experiment-id>/`。运行器不得调用正式一键分析创建接口，不得调用项目 mutation，不得写正式数据库状态。

每组独立运行 3 次。每次使用相同快照和参数，但使用独立实验运行 ID，以观察模型随机性和路由稳定性。

## 5. A组：当前硬绑定基线

A 组复用当前 `build_project_analysis_request` 和正式审查执行语义：

- 每个节点只可使用原 `node.fileRefs`；
- `project.fileCorpus` 只包含这些挂接关系引用的文件；
- System Prompt 保留 `Use only fileCorpus entries referenced by the current node.fileRefs.`；
- 审查模型、温度、输出 Schema 和输出 token 上限与 B/C 一致。

历史运行只作为事实参考。为了公平，A 组仍需按本轮统一模型配置重新回放 3 次。

## 6. B组：完整 OCR 分段 Map/Reduce 路由

### 6.1 分段原则

B 组必须让路由模型读取 23 份文件的全部清洗后 OCR，不得用检索提前丢弃文本。

- 普通文件尽量整份进入同一 Map 批次；
- 超大文件按连续页码或稳定字符边界分段；
- 每段保留 `fileId`、版本 ID、页码范围、段序号和内容哈希；
- 每个 OCR 字符必须恰好属于至少一个 Map 段；
- 允许少量边界重叠，但报告重复 token 数。

按文件分批，不按节点分批。每个 Map 批次都携带全部 30 个节点的精简规则画像，确保任一文件都可以路由到任一节点。

### 6.2 Map

Map Prompt 只判断“当前文件/分段可能支持哪些节点”，禁止输出合规结论。输出：

```json
{
  "fileRoutes": [
    {
      "fileId": "DOC-...",
      "segmentId": "SEG-...",
      "matchedNodes": [
        {
          "nodeId": 24,
          "score": 0.0,
          "reasonCodes": ["ocr_evidence_match"],
          "quotedText": "逐字原文"
        }
      ]
    }
  ]
}
```

`quotedText` 必须逐字存在于当前 Map 段。确定性校验失败的匹配直接丢弃并记录。

### 6.3 Reduce

Reduce 不读取 OCR，只读取全部 Map 结果、节点画像和原 `priorityFileIds`。它统一输出每个节点最多 5 份新增候选。模型生成的文件 ID、节点 ID或引用不存在时判为无效；Reduce 失败时使用 Map 分数的确定性排序。

正式审查输入证据集为：

```text
原 node.fileRefs ∪ B 路由新增文件
```

跨节点文件静默采用，不要求重新挂接，但实验产物记录来源为 `full_ocr_map_reduce`。

## 7. C组：混合召回 + 项目级 LLM 路由

### 7.1 OCR 切片

将 23 份完整 OCR 按页、标题和表格边界切成约 300–600 字的稳定片段，保留 60–100 字边界重叠。片段包含：

- `passageId`、`fileId`、版本 ID；
- 页码或页码范围；
- 原文；
- 内容哈希；
- 标题/表格上下文。

### 7.2 节点查询

节点查询由以下字段确定性拼接：

```text
nodeName + criteria + checkMethod
+ configuredRequirements.name
+ configuredRequirements.materialTypeCode
```

### 7.3 召回

每个节点分别执行：

1. BM25/关键词 Top 12 片段；
2. 真实语义向量 Top 12 片段；
3. 原挂接文件优先加分；
4. 按文件聚合，每份文件最多保留 3 条片段；
5. 合并为 Top 8 候选文件。

必须使用配置明确、可记录模型 ID和维度的真实 Embedding 服务。服务不可用则 C 组阻断并报告，不能自动切换到 `offline-hash-v1`。

### 7.4 项目级路由

一次路由调用读取：

- 30 个节点画像；
- 每节点 Top 8 文件候选；
- 每个候选最多 3 条 OCR 原文片段；
- 原 `priorityFileIds`；
- 去重后的全局 `passageId` 字典。

输出：

```json
{
  "routes": [
    {
      "nodeId": 24,
      "selectedFileIds": ["DOC-..."],
      "supportingPassageIds": ["PASS-..."],
      "confidence": 0.0,
      "reasonCodes": ["priority_binding", "dense_match"]
    }
  ]
}
```

输出强校验：文件必须属于合格池和当前节点 Top 8，片段必须属于所选文件，每节点最多 5 份新增文件。失败时回退到原挂接文件加确定性召回前三名。

正式审查输入证据集为：

```text
原 node.fileRefs ∪ C 路由新增文件
```

## 8. 正式审查的统一约束

A/B/C 的正式审查必须共用：

- 相同模型别名和模型路由版本；
- 相同温度、response format 和最大输出 token 计算；
- 相同节点规则和输出 Schema；
- 相同引用约束：`quotedText` 必须逐字存在于对应文件完整 OCR；
- 相同批次规划算法；
- 相同失败重试策略。

B/C Prompt 将硬白名单规则替换为：原挂接文件是优先证据，路由新增文件是允许证据；只能使用当前节点最终证据集中出现的文件。

## 9. 无金标准的盲测比较

### 9.1 匿名化

比较器只看到匿名候选 `X/Y/Z`，不知道对应 A/B/C。每次运行的候选顺序使用固定随机种子打乱，映射仅写入单独 manifest。

### 9.2 确定性指标

- 证据集扩展数量、跨节点文件数量；
- `insufficient_evidence` 节点数及变化；
- Finding 数量、严重级别和结论分布；
- `quotedText` 原文存在率，要求 100%；
- fileId、nodeId、passageId 有效率；
- 组内 3 次运行的路由 Jaccard、一致结论率和 Finding 语义一致率；
- 输入/输出/reasoning/cache tokens；
- Map、Reduce、召回、路由、审查各阶段耗时；
- 费用及失败/重试次数。

这些指标只描述行为和一致性，不冒充正确率。

### 9.3 独立 LLM 盲评

对每个节点，把匿名候选结果交给独立评审模型做两两比较。评审输入包含：

- 节点规则和资料要求；
- 23 份完整 OCR，必要时同样分段；
- 候选使用的证据、Finding 和原文引用；
- 不包含组名、路由方法、成本或历史结果。

评审维度：证据充分性、规则覆盖、引用真实性、结论谨慎性、遗漏风险。每个节点至少进行 3 次不同候选顺序的盲评，并报告胜/负/平、位置偏差和评审一致性。

评审模型分数是相对偏好，不是人工真值。报告必须显式标注该限制。

## 10. 产物

每次实验至少输出：

```text
output/project-analysis-routing-replay/<experiment-id>/
  snapshot.json
  manifest.json
  arm-a/run-1..3/
  arm-b/run-1..3/
  arm-c/run-1..3/
  blind-judge/
  deterministic-metrics.json
  token-cost-latency.json
  node-comparison.json
  comparison-report.md
```

报告逐节点列出：原挂接文件、路由新增文件、证据变化、结论变化、引用校验、三次稳定性、匿名盲评结果和成本。

## 11. 错误处理

- Embedding 服务不可用：只阻断 C，不伪造结果；
- 单个 B Map 失败：重试后仍失败则 B 组该次运行失败，不能跳过该 OCR 段；
- 路由 JSON 无效：记录原始响应和校验错误，按已定义确定性回退；
- 正式审查截断或空输出：按现有失败语义重试，仍失败则保留失败记录；
- 盲评失败：不影响A/B/C原始结果，报告盲评缺口；
- 任一阶段不得将实验结果写回正式业务集合。

## 12. 测试策略

- 单元测试：候选池过滤、OCR全覆盖分段、Map/Reduce校验、Top 8聚合、路由输出校验、引用原文校验、匿名映射和成本汇总；
- 集成测试：使用小型固定夹具跑通A/B/C，验证正式数据库零变更；
- 回归测试：当前一键分析生产路径保持不变；
- 实际回放：对 `P-2026-FDBB4B` 各运行3次并生成最终报告。

## 13. 完成条件

目标完成必须同时满足：

1. A/B/C 都完成3次真实模型回放；外部服务阻断只能保持目标未完成，不能算作交付；
2. B 的全部 OCR 段覆盖率为100%；
3. C 使用真实语义 Embedding；
4. 所有成功审查输出通过引用原文校验；
5. 匿名盲评不泄露组别；
6. tokens、耗时、费用和错误完整记录；
7. 正式项目状态和既有运行未被修改；
8. 输出完整对比报告，且不把无金标准盲评分数称为绝对准确率。
