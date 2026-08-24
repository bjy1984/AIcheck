# MinerU Markdown 驱动的 Qwen3.8-Max 资料类型分类与自动金标设计

## 1. 目标

文件完成 MinerU OCR 后，只把 Markdown 正文和项目预设的具体资料类型定义发送给 Qwen3.8-Max。模型从 `material_review_points.json` 去重得到的60种 `materialTypeCode` 中选择零个或多个类型，通过本地 Schema、枚举和 Markdown 原文证据门禁后直接生成自动金标。

自动金标中的全部具体类型写回文档，并通过 164 条“资料类型—业务节点—证据项”映射重新执行节点打靶。16 个资料大类不再由模型直接判断，而是由具体类型在映射中的 `materialCategory` 自动派生。

## 2. 已确认决策

1. 模型固定为 `qwen3.8-max`，使用独立 `documentClassifier` 角色。
2. Qwen 输入只包含 MinerU Markdown 与60种具体资料类型定义。
3. 不传文件名、目录名、扩展名、上传人或旧分类结果。
4. 一份文件可以对应多个 `materialTypeCode`。
5. 单次 Qwen 调用；不做人审、二次模型复核或多模型投票。
6. 每个类型必须提供可在 Markdown 中逐字定位的 `contentEvidence`。
7. 模型结果直接成为不可变、可版本替代的自动金标。
8. Prompt 通过现有管理员“Prompt 模板管理”编辑、发布和审计。
9. 自动金标后按全部具体类型查询 164 条映射，创建节点证据链接与绑定。
10. `test/` 23份文件作为人工回归基准；资料包允许多类型，未被60类型覆盖的文件允许零类型。

## 3. 分类本体

权威配置 `backend/config/material_review_points.json` 包含 16 个 `materialCategory`、60 个去重 `materialTypeCode` 和 164 条映射。164 条记录去重后是 163 个“类型—节点”组合，因为 `design_document` 在节点 1 有两条不同证据要求；这两条都必须保留。

运行时生成 `document-material-types@1` 快照：

```json
{
  "materialTypeCode": "design_license",
  "materialTypeNames": ["设计单位许可证"],
  "materialCategories": ["资质证照"],
  "evidenceItems": ["设计许可证机构名称", "许可范围", "有效期", "印章"],
  "nodeIds": [1]
}
```

模型只能输出快照中的 `materialTypeCode`。大类和节点由系统派生，不能由模型自由生成。

## 4. 数据流

```text
上传完成
  -> MinerU OCR
  -> full.md + normalized result 持久化
  -> 创建 document_classification_run
  -> llm.remote / classify_document_auto_gold
  -> production Prompt 模板
  -> materialTypeDefinitionsJson + ocrMarkdown
  -> 单次 qwen3.8-max JSON Schema 调用
  -> 枚举、证据、版本和新鲜度校验
  -> document_gold_labels 新版本
  -> materialTypeLabels[] / 主 materialTypeCode
  -> 派生 materialCategoryLabels[]
  -> run_material_targeting(triggered_by=qwen_auto_gold)
  -> 按 164 条映射创建节点链接和绑定
```

运行 ID 由文档版本、OCR结果、Markdown哈希、Prompt哈希、60类型快照哈希和模型名共同生成，相同输入不重复调用。

## 5. Prompt 模板

```text
promptKey: document-material-classifier
agentId: document_material_classifier
variables:
  - materialTypeDefinitionsJson
  - ocrMarkdown
```

模板不得声明或引用 `fileName`、`relativeDirectory`、`filePath`、`extension`。默认 Prompt 把 Markdown 当作不可信内容，只允许选择给定类型，允许零类型，禁止根据常识猜测，并要求每个类型提供 Markdown 原文证据。

管理员复用 `/admin/prompt-templates` 的创建、编辑、发布、ETag和审计机制。

## 6. 模型输出与门禁

```json
{
  "labels": [
    {
      "materialTypeCode": "design_license",
      "confidence": 0.97,
      "decisionSummary": "正文是压力管道设计许可证。",
      "contentEvidence": [
        {"quote": "许可项目：压力管道设计", "purpose": "设计许可依据"}
      ]
    }
  ],
  "documentSummary": "压力管道设计许可证",
  "classificationComplete": true,
  "unclassifiedReason": null
}
```

本地门禁要求：Schema严格通过；类型属于60类型快照且无重复；置信度在0到1；每个类型至少一条证据；证据可在原Markdown或仅去除空白后的Markdown中定位；文档与OCR版本未过期；无类型时给出原因。

失败时保存运行和原始响应，但不生成金标，也不回退文件名分类。

## 7. 持久化与投影

`document_classification_runs` 保存文档/版本/OCR ID、Markdown、60类型快照、完整Prompt、模型、Token、耗时、原始与结构化响应、校验和打靶结果。

`document_gold_labels` 保存全部具体类型及证据、`primaryMaterialTypeCode`、派生 `materialCategoryLabels`、模型和版本链。新金标使旧active版本变为superseded，不删除历史。

文档和知识文件投影：

```text
materialTypeLabels[]
materialTypeCode
materialCategoryLabels[]
materialCategory
activeGoldLabelId
classificationSource=qwen_auto_gold
classificationConfidence
classifiedAt
```

## 8. 节点挂接

`material_targeting` 的来源闸门、计分和自动绑定读取：

```text
{document.materialTypeCode} ∪ document.materialTypeLabels[]
```

因此同一文档被识别为 `design_license` 和 `design_document` 时，两种类型对应的映射都可产生证据链接和绑定。原规则分类保留作OCR阶段兼容结果；Qwen金标完成后成为类型权威结果并再次打靶。

## 9. `test/` 23文件基准

清单固定23个路径和SHA-256。每份文件包含人工语义名、零个或多个 `expectedMaterialTypeCodes`，以及大类对照。材料报审资料包可对应多个类型；告知书、监检合同、社保证明当前不在60类型中，明确使用空数组。

目录和文件名只用于人工基准，`model_input_for_case()`只返回 `materialTypeDefinitionsJson` 和 `ocrMarkdown`。

## 10. 验收标准

1. OCR成功后自动派发一次Qwen分类；
2. 实际模型为 `qwen3.8-max`；
3. Qwen输入不含文件名、目录或扩展名；
4. 输出为零个或多个60种具体资料类型；
5. 16大类完全由具体类型映射派生；
6. 每个accepted金标都有Markdown原文证据；
7. 运行保存Prompt、模型、OCR、原始响应和版本链；
8. 金标不可变并支持版本替代；
9. 金标后按全部类型执行 164 条映射打靶；
10. 管理员能修改并发布分类Prompt；
11. 23文件具体类型枚举和哈希审计通过；
12. 现有细类型、节点打靶、Qwen、MinerU和Prompt测试不回归。
