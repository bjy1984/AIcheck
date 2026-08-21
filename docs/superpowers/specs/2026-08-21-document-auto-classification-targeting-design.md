# 普通资料自动分类、节点打靶与未分类兜底设计

日期：2026-08-21

## 1. 目标

施工方通过普通项目资料上传入口提交文件后，系统在 OCR 结果落库后自动完成标准资料分类，并依据 OCR 中可定位的事实把资料自动打靶到一个或多个业务节点。无法产生任何分类信号的资料统一进入“未分类资料”库；业务节点没有找到输入文件时，AI 审查回退读取当前项目的未分类资料。

本设计不实现“高置信度自动挂载、低置信度人工确认”，也不把人工修正结果作为自动分类决策输入。

## 2. 状态口径

以下两个事实必须分开：

- 上传动作完成：文件字节完整落库，当前版本有实际内容哈希。
- 上传成功：文件本体存在、OCR 已识别、已切片、已向量化。

自动分类和节点打靶不是上传成功的第五、第六个条件。分类结果为“未分类资料”或没有命中节点，不改变上传成功判定。

## 3. 处理依赖图

```text
文件本体落库
      │
      ▼
OCR 结果落库
      │
      ▼
自动分类（必须先完成并同步到知识文件）
      │
      ├─────────────────┐
      ▼                 ▼
自动节点打靶          切片
                        │
                        ▼
                     向量化
```

分类先于切片，确保知识分块和向量元数据携带最终 `materialTypeCode` 与 `classificationStatus`。节点打靶和切片互不依赖，分类完成后可以并行执行。当前同步/内联执行模式允许先完成节点打靶再派发切片；Celery 模式下两条支线分别持久化，互不阻塞。

## 4. 自动分类

### 4.1 输入

- 文件名；
- OCR `profileId`；
- OCR `documentType`；
- OCR fragments、fields、tables、seals 中的可检索文本；
- `material_review_points.json` 中的标准类型名称、编码和类别；
- 现有文件名别名表。

### 4.2 候选与选择

分类器为每个候选标准类型生成 `confidence`。数值只用于候选排序和解释，不作为人工确认门槛。

优先信号如下：

1. OCR `documentType` 与标准类型编码一致；
2. OCR `profileId` 明确对应标准类型；
3. 文件名命中标准类型名称或别名；
4. OCR 正文命中标准类型名称或别名。

选择规则：

- 取 `confidence` 最大的候选；
- 最大值大于 0 即分类；
- 同分时按信号优先级、命中关键词长度、配置顺序决定唯一结果；
- 最大值为 0 时统一生成未分类结果。

### 4.3 未分类统一值

```json
{
  "materialCategory": "未分类资料",
  "materialTypeCode": "unclassified_material",
  "materialTypeName": "未分类资料",
  "classificationStatus": "unclassified",
  "classificationConfidence": 0.0,
  "classificationSource": "ocr_classifier"
}
```

分类成功时 `classificationStatus=classified`。所有结果记录 `classificationReasons`、`classifierVersion` 和 `classifiedAt`。

### 4.4 持久化

分类结果同步写入：

- `Document`；
- 对应的 `KnowledgeFile`；
- 后续生成的 `KnowledgeChunk`；
- 后续生成的 `KnowledgeVector.payload`。

自动重跑按文档版本幂等更新系统分类，不读取人工分类结果作为输入。

### 4.5 异常

没有候选是正常的未分类结果。分类器发生异常时同样落入未分类统一值，并额外记录 `classificationError`，不得阻止切片和向量化。

## 5. 自动节点打靶

### 5.1 运行条件

- 文档分类结果不是 `unclassified_material`；
- OCR 结果可用；
- 项目业务包与资料审查点可加载。

### 5.2 确定性资格

节点打靶不按高低置信度分流。审查点满足以下条件即具有挂载资格：

- 最终 `materialTypeCode` 与审查点类型一致，或命中已配置的明确兼容关系；
- 上传责任方符合；
- 境外、新材料、穿跨越等条件上下文门通过；
- 至少存在一个与审查点事实目标匹配的 OCR 事实；
- 正式证据包含文档版本、页码、有效 bbox 和引用原文。

满足条件时：

- 生成或更新 `NodeEvidenceLink`；
- 系统证据状态直接标记为已确认，不生成低置信度待确认流程；
- 生成幂等的 `BIND-AUTO-*` 草稿挂载；
- 一个文件可以挂载多个节点；
- 重跑不重复创建挂载；
- 不删除或覆盖人工创建的挂载。

未分类资料不执行自动节点挂载。

## 6. 未分类资料 AI 兜底

AI 节点审查先读取节点已有正式证据和节点挂载。当目标节点没有任何输入文档版本时，回退加载当前项目中满足以下条件的资料：

- `materialTypeCode=unclassified_material`；
- 当前版本；
- OCR 可用；
- 已切片、已向量化；
- 与当前项目和租户一致。

回退资料进入现有 grounded review 输入，仍需经过页码、bbox、原文和事实形态校验。兜底只扩大候选文件范围，不自动创建节点挂载，也不降低正式证据门槛。

## 7. 统一 OCR 后处理入口

新增单一服务函数：

```python
def process_document_classification_and_targeting(
    repo: Any,
    project_id: str,
    document_id: str,
    document_version_id: str,
    *,
    triggered_by: str,
) -> dict[str, Any]: ...
```

所有成功 OCR 路径必须通过该函数：

- 本地 OCR；
- 普通 accuracy pipeline；
- active accuracy finalize；
- MinerU 远程 OCR。

函数执行顺序固定为：加载最新 OCR 结果、分类、持久化分类、条件执行节点打靶、返回结构化摘要。调用方在它返回后派发切片。

## 8. 端到端验收

必须覆盖真实普通上传入口，不得只用 `repo.create_document()` 构造文档：

```text
POST upload-session
→ PUT 文件字节
→ POST complete
→ OCR 结果应用
→ 自动分类
→ 自动节点打靶
→ 切片
→ 向量化
→ 上传成功
→ 提交
```

必测场景：

- 设计许可证分类为 `design_license` 并打靶 R01；
- 产品质量证明书分类为 `quality_certificate` 并打靶 R16；
- 焊工资格证分类为 `welder_certificate` 并打靶 R24；
- 无损检测报告分类为 `ndt_report` 并打靶 R40；
- 一个文件打靶多个符合条件的节点；
- 无任何分类信号时进入 `unclassified_material` 且不创建自动挂载；
- 节点没有输入资料时，AI 输入版本回退到未分类资料；
- MinerU 和本地 OCR 走同一后处理入口；
- 重跑不重复生成绑定；
- OCR、切片或向量化任一未完成时不满足上传成功；
- 四项完成后可以提交项目资料池或已有节点挂载。

## 9. 非目标

- 不实现分类人工确认队列；
- 不实现高低置信度分流；
- 不把分类或打靶加入上传成功判据；
- 不改变现有上传成功四项定义；
- 不重构无关的标准条款知识库检索；
- 不自动删除人工节点挂载。
