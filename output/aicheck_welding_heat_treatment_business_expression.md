# AIcheck 焊接与热处理审查业务表达规范

## 1. 结论

`files/焊接热处理要求.docx` 应表达为 AIcheck 的“节点规则卡”，而不是只作为一段自然语言 Prompt。每个业务节点都要拆成：

- 节点身份：`nodeId`、节点名称、检查类别。
- 审查对象：应上传或应引用哪些资料。
- 字段映射：从 OCR/结构化表单中提取哪些字段。
- 证据要求：每个判断必须绑定 `EvidenceLink`、页码、字段或截图。
- 标准依据：引用规范名称、条款号、适用条件。
- 核验逻辑：缺失检查、有效期检查、覆盖性检查、一致性检查、跨节点联动检查。
- 系统动作：创建 AI run、写入推理步骤、生成建议、更新证据链、触发人工确认或补正。
- 验证方式：和专家预期、历史人工结论、多模型结果、前后规则版本结果做对比。

当前项目已有 `ai_runs`、`steps`、`suggestion`、`evidenceLinks`、规则版本、Prompt 版本和多模型对比的基础结构；缺口在于 worker 当前只是一次性 LLM 调用，尚未按节点规则逐步执行。

## 2. 推荐表达格式

建议规则库使用如下结构保存专家审查经验：

```json
{
  "ruleKey": "welding-heat-treatment",
  "ruleVersion": "Welding-HeatTreatment-v1.0",
  "promptVersion": "prompt-welding-heat-treatment-v1.0",
  "applicableNodeIds": [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34],
  "nodes": [
    {
      "nodeId": 24,
      "nodeName": "焊工资格证及持证合格项目",
      "inspectionType": "B",
      "reviewGoal": "核验焊工资格证真实有效，持证合格项目覆盖实际施焊活动。",
      "requiredEvidence": [
        {
          "name": "焊工资格证",
          "required": true,
          "acceptedFileTypes": ["pdf", "image", "docx"],
          "fields": ["姓名", "证书编号", "有效期", "焊接方法", "母材类别", "焊接位置", "厚度范围", "管径范围"]
        },
        {
          "name": "焊接施工记录",
          "required": true,
          "fields": ["焊工姓名", "焊工证号", "管线材质", "规格", "焊接方法", "焊缝编号"]
        }
      ],
      "standards": [
        {
          "standardName": "TSG Z6002-2010 特种设备焊接操作人员考核细则",
          "clauses": ["焊接方法覆盖", "金属材料类别覆盖", "焊接位置覆盖", "厚度和管径覆盖"]
        }
      ],
      "checks": [
        {
          "checkId": "24-C1",
          "name": "资料完整性",
          "logic": "焊工资格证和焊接施工记录必须存在，且 OCR 置信度低的关键字段进入人工确认。",
          "onFail": "需补正"
        },
        {
          "checkId": "24-C2",
          "name": "证书有效期覆盖施工日期",
          "logic": "证书有效期起止日期必须覆盖施焊日期或项目施工日期。",
          "onFail": "需补正"
        },
        {
          "checkId": "24-C3",
          "name": "持证项目覆盖实际作业",
          "logic": "证书中的焊接方法、母材类别、位置、厚度范围、管径范围必须覆盖施工记录中的实际作业条件。",
          "onFail": "需补正"
        },
        {
          "checkId": "24-C4",
          "name": "跨节点联动",
          "logic": "节点 29 的施焊记录必须与本节点焊工证号、焊接方法、焊缝编号一致；节点 25 的 WPS/PQR 应覆盖同一作业条件。",
          "onFail": "需人工确认"
        }
      ],
      "systemActions": [
        "写入 ai_runs.steps，每个 check 形成一条步骤记录",
        "为每个结论绑定 evidenceLinkIds",
        "生成 suggestion.result、opinionDraft、risks、manualConfirmItems",
        "若缺少必备证据，建议触发 return-correction；若全部通过，生成可采纳审查意见草稿"
      ],
      "outputRequirements": {
        "mustReturnJson": true,
        "allowedResults": ["满足要求", "需补正", "不适用", "需人工确认"],
        "mustCiteEvidence": true,
        "noEvidenceNoPass": true
      }
    }
  ]
}
```

## 3. Prompt 应这样写

系统 Prompt 不应要求模型“自由复核”，而应要求它按规则卡执行：

```text
你是压力管道监督检验 AI 复核助手。
你必须依据输入的节点规则卡、OCR 字段、项目文件证据、标准条文片段进行判断。

执行约束：
1. 逐条执行 checks，不允许跳过。
2. 每个判断必须引用 evidenceLinkIds 或明确说明“证据缺失”。
3. 没有证据不得判定“满足要求”。
4. OCR 低置信度、字段冲突、标准条款不明确时，结论为“需人工确认”。
5. 必须输出 JSON，字段为 steps、suggestion、evidenceLinks。
6. 不得编造标准条文、证书编号、日期、检测数据。

输出 JSON：
{
  "steps": [
    {
      "id": "24-C1",
      "title": "资料完整性",
      "inputSummary": "核验焊工资格证、施工记录",
      "action": "rule.check",
      "conclusion": "通过 | 需补正 | 待人工确认 | 不适用",
      "evidenceLinkIds": []
    }
  ],
  "suggestion": {
    "result": "满足要求 | 需补正 | 不适用 | 需人工确认",
    "opinionDraft": "审查意见草稿",
    "risks": [],
    "rectificationSuggestion": "补正要求",
    "confidence": 0.0,
    "manualConfirmItems": []
  }
}
```

## 4. 节点 24-34 应拆分的业务规则

| 节点 | 规则重点 | 必须提取字段 | 关键比对 |
|---|---|---|---|
| 24 焊工资格证及持证合格项目 | 证书有效、持证项目覆盖实际作业 | 姓名、证号、有效期、方法、母材、位置、厚度、管径 | 与节点 29 施焊记录、节点 25 WPS/PQR 联动 |
| 25 焊接工艺文件 | PQR/WPS 审批有效，参数和适用范围覆盖生产条件 | PQR 编号、WPS 编号、审批状态、电流、电压、速度、层间温度、厚度范围 | 与管线汇总表、施焊记录、焊评覆盖范围比对 |
| 26 焊接材料质量证明文件 | 焊材牌号、规格、批号、性能符合设计 | 材料牌号、规格、批号、化学成分、力学性能、标准号 | 与设计说明、实物批号、材料标准比对 |
| 27 焊材验收保管发放回收 | 烘干、保温、发放、回收记录闭环 | 温湿度、烘干温度时间、领用人、批号、回收数量 | 检查混用、过期、记录缺失 |
| 28 管道组对 | 错边量、间隙、坡口符合工艺 | 错边量、间隙、坡口角度、组对日期、焊口号 | 与 WPS、现场照片、记录表比对 |
| 29 施焊参数、记录、焊缝标识 | 施工记录真实可追溯 | 电流、电压、速度、层间温度、焊工证号、焊缝编号 | 与节点 24、25、30、40 联动 |
| 30 焊接接头外观质量 | 外观尺寸和缺陷满足标准 | 余高、宽度、咬边、气孔、裂纹、检查日期 | 与照片、检验尺数据、标准限值比对 |
| 31 焊缝返修 | 返修审批、次数、工艺和复检闭环 | 返修次数、返修原因、审批人、返修工艺、复检报告 | 超过次数触发专项方案/人工确认 |
| 32 焊后热处理工艺文件 | 热处理工艺卡经审批且基于评定 | 升温速率、保温温度、保温时间、降温速率、审批状态 | 与设计说明、热处理评定报告比对 |
| 33 热处理测温仪表 | 热电偶、温控仪有效校准 | 仪表编号、校准日期、有效期、测温点布置 | 与热处理日期、曲线记录对应 |
| 34 热处理记录、曲线、硬度报告 | 温度曲线完整，硬度结果符合要求 | 曲线起止时间、温度、保温段、硬度值、检测位置 | 与工艺卡参数、设计硬度要求比对 |

## 5. 系统执行路径

按照当前项目架构，推荐的执行路径是：

```text
前端点击 AI 复核
-> POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck
-> 创建 ai_runs，记录 ruleVersion / promptVersion / inputDocumentVersionIds
-> worker 加载节点规则卡
-> worker 收集节点文件、OCR 字段、标准条文、历史人工意见
-> 按 checks 逐条执行规则核验
-> 必要时调用 LLM 生成解释性审查意见
-> 回写 ai_runs.steps、suggestion、evidenceLinks
-> 前端展示业务核验链路
-> 监检人员采纳、修改后采纳、驳回或退回补正
```

当前 `backend/apps/worker/tasks.py` 的 `ai_recheck` 应从“一次 chat completion”升级为：

```text
load_context
-> load_rule_card
-> map_fields
-> retrieve_standards
-> execute_deterministic_checks
-> llm_explain_uncertain_items
-> build_suggestion
-> persist_ai_run
```

其中日期覆盖、字段是否存在、枚举值匹配、数值范围判断应优先用确定性代码执行；LLM 主要负责解释、归纳风险、生成审查意见草稿。

## 6. 效果对比验证

要验证 AIcheck 是否“准确”，建议建立样本集和版本对比表：

```json
{
  "caseId": "CASE-24-001",
  "nodeId": 24,
  "inputDocumentVersionIds": ["DV-xxx"],
  "expertExpected": {
    "result": "满足要求",
    "requiredFindings": [
      "证书有效期覆盖施工日期",
      "GTAW 覆盖氩弧焊",
      "FeII 覆盖 20 钢",
      "6G 覆盖全位置",
      "3/57 覆盖 89x4.5mm 管线"
    ]
  },
  "compareRuns": [
    {
      "ruleVersion": "Welder-Qualification-B-v2.1",
      "promptVersion": "prompt-welder-v2.1",
      "result": "满足要求",
      "hitRequiredFindings": 5,
      "falsePositiveCount": 0,
      "missingEvidenceCount": 0
    }
  ]
}
```

核心指标：

- 结论一致率：AI 建议结果是否与专家预期一致。
- 证据命中率：关键证据是否全部引用到 `evidenceLinks`。
- 风险召回率：缺证、过期、范围不覆盖、字段冲突是否被发现。
- 误报率：不应补正却被判为补正的比例。
- 人工修改率：监检人员采纳 AI 建议时需要改动多少内容。
- 可追溯率：每条结论是否能追溯到文件版本、页码、OCR 字段、规则版本。

验证流程：

```text
1. 选取每个节点 5-10 个专家标注样本。
2. 固定输入文件版本和 OCR 版本。
3. 分别运行旧 prompt、规则卡 v1、新规则卡 v2、多模型对比。
4. 比对 AI 输出与 expertExpected。
5. 将差异归因到 OCR、字段映射、规则表达、标准召回或模型解释。
6. 调整规则版本或字段映射，重新发布。
```

## 7. 最小落地建议

第一阶段不要一次改成完整 Agent。建议先做三件事：

1. 把 `焊接热处理要求.docx` 的 24-34 节点录入规则版本管理，形成 JSON 规则卡。
2. 修改 `ai_recheck` worker，让它读取规则卡并按 `checks` 生成真实 `steps`。
3. 建立 10 个节点 24 的专家样本，用现有多模型对比和人工结论做效果验证。

这样可以在不推翻现有 API 和前端的情况下，把 AIcheck 从“LLM 给建议”升级成“按业务规则可追溯复核”。
