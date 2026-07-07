# AI 审查资料映射关系实现

## 1. 目标

本方案用于实现从“施工方/无损检测机构上传资料”到“监检业务节点审查证据”的自动映射链路。

核心目标：

```text
上传文件 -> 保留上传标签 -> OCR/解析 -> 识别资料类型 -> 识别内容项 -> 抽取证据点 -> 关联业务节点 -> 计算资料齐全度 -> 支撑 AI/人工审查
```

系统不能只判断“有没有上传文件”，而应判断上传文件中的具体章节、页段、表格和字段能否支撑某个监检业务节点的审查要求。

## 2. 核心对象

| 对象 | 说明 | 示例 |
| --- | --- | --- |
| 上传资料标签 `materialCategory` | 上传时由施工方或无损检测机构选择的资料标签，表示上传方对文件用途的业务声明 | 设计资料、资质证照、无损检测资料 |
| 标准化资料类型 `materialTypeCode` | 平台标准化后的资料类型，用于规则匹配和资料齐全度计算 | `design_document`、`design_license`、`ndt_report` |
| 内容项 `evidenceItem` | 文件内部可支撑审查的章节、页段、表格或局部区域 | 施工图纸标题栏、设计印章页、管道特性表 |
| 抽取字段 `extractedField` | 从内容项中抽取出的结构化字段 | 设计单位名称、许可范围、有效期、管道级别 |
| 证据链接 `EvidenceLink` | 将文件、内容项、字段与业务节点审查要求绑定的证据关系 | R01 由某文件第 2 页标题栏支撑 |

关键原则：

- `materialCategory` 是上传方声明，必须原样保存，不能被 OCR 或 AI 覆盖。
- `materialTypeCode` 可以由上传标签、文件名、OCR、规则分类和人工校正共同确定。
- `evidenceItem` 和 `extractedField` 必须能回溯到文件、页码、区域坐标和原文。
- 节点资料齐全度应基于 EvidenceLink 判断，而不是单纯基于文件数量判断。

## 3. 上传阶段

施工方或无损检测机构上传文件时，应保存以下原始信息：

| 字段 | 含义 |
| --- | --- |
| `fileName` | 文件名 |
| `sourceOrgName` | 上传单位 |
| `uploaderName` | 上传人 |
| `materialCategory` | 上传时选择的资料标签 |
| `declaredNodeIds` | 上传人主动挂载的节点，可为空 |
| `uploadTime` | 上传时间 |
| `fileStatus` | 草稿、已上传、已提交等 |

示例：

```json
{
  "documentId": "DOC-001",
  "fileName": "设计资料.pdf",
  "sourceOrgName": "中石化安装有限公司",
  "uploaderName": "李工",
  "materialCategory": "设计资料",
  "declaredNodeIds": [],
  "uploadTime": "2026-07-07 10:30:00",
  "fileStatus": "已上传"
}
```

上传标签用于保留上传方的业务判断。即使后续 OCR 判断该文件更像“施工组织设计”，也不能覆盖原始 `materialCategory`，只能新增系统推断结果并提示人工确认。

## 4. 文件解析阶段

上传后进入后台解析任务：

1. OCR 文字识别。
2. PDF/图片版面分析。
3. 表格识别。
4. 页码、区域坐标、段落、表格行列保存。
5. 文本切片与向量化。

输出不应只是纯文本，而应保存结构化片段：

```json
{
  "documentId": "DOC-001",
  "pageNo": 3,
  "blockType": "table",
  "text": "管道特性表...",
  "bbox": [120, 220, 900, 640],
  "confidence": 0.91
}
```

## 5. 资料类型标准化

系统根据上传标签、文件名、OCR 内容、版面特征和人工校正结果，判断标准化资料类型：

```json
{
  "documentId": "DOC-001",
  "declaredMaterialCategory": "设计资料",
  "materialTypeCode": "design_document",
  "confidence": 0.88,
  "source": "ocr_classifier",
  "needHumanConfirm": false
}
```

如果上传标签和 OCR 判断冲突，应保留两者：

| 数据 | 示例 |
| --- | --- |
| 上传标签 | 设计资料 |
| OCR 判断 | 施工组织设计 |
| 处理状态 | 需人工确认 |

## 6. 内容项识别

系统应从文件中识别出可支撑审查的内容块。

| 内容项编码 | 名称 | 常见资料类型 |
| --- | --- | --- |
| `drawing_title_block` | 施工图纸标题栏 | `design_document` |
| `design_seal_page` | 设计印章页 | `design_document` |
| `design_specification` | 设计说明 | `design_document` |
| `pipeline_characteristic_table` | 管道特性表 | `design_document` |
| `license_scope` | 许可证范围 | `design_license`、`construction_license` |
| `valid_until` | 有效期 | 各类许可证 |
| `ndt_report_conclusion` | 无损检测报告结论 | `ndt_report` |

输出示例：

```json
{
  "evidenceItemCode": "pipeline_characteristic_table",
  "documentId": "DOC-001",
  "pageNo": 8,
  "bbox": [120, 220, 900, 640],
  "text": "管道类别 GC2...",
  "confidence": 0.86
}
```

## 7. 字段抽取

从内容项中抽取结构化字段：

```json
{
  "fieldCode": "pipeline_class",
  "fieldName": "管道类别/级别",
  "fieldValue": "GC2",
  "evidenceItemCode": "pipeline_characteristic_table",
  "documentId": "DOC-001",
  "pageNo": 8,
  "bbox": [300, 410, 120, 32],
  "confidence": 0.82
}
```

字段抽取结果必须能回溯到原始文件、页码、区域和原文。

## 8. 规则节点匹配

需要建立核心配置：

```text
业务节点 -> 审查内容项 -> 所需资料类型 -> 所需字段
```

以 R01 为例：

| 节点 | 审查内容项 | 所需资料类型 | 所需字段 |
| --- | --- | --- | --- |
| R01 | 设计许可证 | `design_license` | 机构名称、许可范围、有效期 |
| R01 | 图纸标题栏 | `design_document` | 设计单位名称 |
| R01 | 设计印章页 | `design_document` | 设计单位名称 |
| R01 | 设计说明 | `design_document` | 管道类别/级别 |
| R01 | 管道特性表 | `design_document` | 管道类别/级别 |

匹配后生成 EvidenceLink：

```json
{
  "nodeId": 1,
  "ruleId": "R01",
  "requirementId": "REQ-01-02",
  "evidenceItemCode": "drawing_title_block",
  "documentId": "DOC-001",
  "pageNo": 2,
  "fieldCodes": ["design_org"],
  "supportStatus": "已支撑",
  "confidence": 0.87
}
```

## 9. 资料齐全度计算

节点资料齐全度不应只看文件数量，而应看以下条件：

1. 所需资料类型是否存在。
2. 所需内容项是否识别到。
3. 所需字段是否抽取到。
4. 字段置信度是否达标。
5. 是否需要人工确认。

示例：

```text
R01 资料齐全度：
设计单位许可证：已支撑
施工图标题栏：已支撑
设计印章页：缺失
设计说明：已支撑
管道特性表：已支撑

结果：4/5，需补充设计印章页
```

## 10. AI 审查执行

AI 审查不应直接基于全文做结论，而应基于规则和 EvidenceLink 执行：

1. 读取业务节点依据。
2. 读取已匹配 EvidenceLink。
3. 比对抽取字段。
4. 判断资料缺项、字段冲突、范围覆盖和有效期。
5. 输出总分结构的审查结论。

R01 示例结论：

```text
总体意见：暂不能通过，需补充设计印章页并确认设计单位名称一致性。

一、设计许可证显示机构名称为 A 公司，来源 DOC-001 第 1 页。
二、施工图标题栏显示设计单位为 A 公司，来源 DOC-002 第 2 页。
三、未识别到设计印章页，无法完成三方名称一致性核验。
```

## 11. 人工确认闭环

人工可进行三类修正：

| 操作 | 说明 |
| --- | --- |
| 修正资料类型 | 将 OCR 判断的资料类型改为正确的 `materialTypeCode` |
| 标注内容项 | 手动框选“这里是管道特性表”或“这里是设计印章页” |
| 确认证据点 | 确认字段抽取正确，或修改字段值 |

人工确认结果应回写 EvidenceLink，并可作为后续 OCR 分类、字段抽取和规则匹配优化的数据。

## 12. 推荐实施顺序

### 第一期：数据模型

补齐以下实体和关系：

| 实体 | 作用 |
| --- | --- |
| `Document` | 文件级信息，保存上传标签 `materialCategory` |
| `DocumentMaterialClassification` | 系统推断或人工确认的标准化资料类型 |
| `DocumentBlock` | OCR/版面分析后的页段、表格和区域 |
| `EvidenceItem` | 可支撑审查的内容项 |
| `ExtractedField` | 从内容项抽取的字段 |
| `EvidenceLink` | 内容项/字段与业务节点要求的支撑关系 |

### 第二期：规则配置

将 `docs/工程监检资料映射表.md` 中的映射关系固化为 YAML/JSON：

```text
nodeId -> requiredEvidenceItems -> materialTypeCode -> fieldCodes
```

### 第三期：解析与匹配

OCR 后完成：

1. 资料类型推断。
2. 内容项识别。
3. 字段抽取。
4. EvidenceLink 自动生成。
5. 冲突或低置信度项进入人工确认。

### 第四期：审查工作台

节点页展示：

- 节点需要哪些内容项。
- 哪些内容项已由文件支撑。
- 哪些内容项缺失。
- 每个证据点来自哪份文件、哪一页、哪个区域。
- 可点击查看原文。
- AI 结论引用了哪些证据。

## 13. 实施原则

- 上传标签是输入信号。
- OCR 是识别信号。
- 向量化是召回手段。
- EvidenceLink 是审查依据。
- 人工确认是闭环校正机制。

最终判断一个节点能否开展审查，应基于 EvidenceLink 是否覆盖该节点所需的资料类型、内容项和字段。
