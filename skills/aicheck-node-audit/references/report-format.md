# audit.json 格式

写在资料包目录（与 `bundle.json` 同级），然后跑 `node_audit report --bundle <目录>`。`report` 会：

- 校验 `schemaVersion`、每个原子检查恰好一条、`verdict` 合法；
- `passed`/`failed` 至少一条有名称、非空值及有效来源的事实，并有 `reasoning` 或 `reason`；数值 0 和 false 不算空。其余结论必须有 `reason`，未知内容写在原因或局限，不造空事实；
- 服务器节点：从 `bundle.json` 补 `serverResult` 和 `agreesWithServer` 写回 `audit.json`（输出 `auditJsonUpdated: true`，之后再改先重新读一遍），与服务器不同又没写 `differenceNote` 的给警告；本地资料不改写 `audit.json`；
- 来源必须实际存在：原件 `files/…` 须在包清单内；工具 `tool:<命令名>` 的 `locator` 写本包对应 JSON 存档路径；标准 `standard:<仓库相对路径>` 须有原文件；服务器数据 `server:<本包JSON路径>`。PDF 页须为正整数且不超过原件页数。转文字仍引用原件，Office 的文字行号写进 `locator`。这些检查验证结构与来源，不证明原文读值正确；
- 生成 `audit.md`：开头是节点整体结论（通过／不通过／暂不能判定通过）和逐项总览表（结论、一句话理由、主要依据），然后按“不通过的原因”“需要人工确认”“证据不足”“需要补充的资料”“通过项及证据”分组，最后是逐项明细。一句话理由取 `reasoning`（符合、不符合）或 `reason`（其他结论）到第一个句号为止（分号不断句，太长会截断加省略号），所以第一句要能单独看懂。

节点整体结果由各项结论算出：有一项不符合就是不通过；全部符合（或不适用，且至少一项符合）是通过；其余是暂不能判定通过。证据不足和需人工确认不算不通过。

## 结构

```json
{
  "schemaVersion": "aicheck-node-audit-report@1",
  "projectId": "P-2026-XXXX",
  "nodeId": 24,
  "ruleId": "R24",
  "auditedAt": "2026-10-22T15:30:00+08:00",
  "auditor": "助手名（模型名）",
  "summary": "一两段总体意见：主要问题、最关键的缺口。",
  "checks": [
    {
      "atomicCheckId": "AC-R24-01",
      "name": "证书有效性和核验来源",
      "verdict": "human_review_required",
      "requirement": "焊工证在施焊日期有效，人员身份一致",
      "facts": [
        {"name": "证书编号", "value": "…", "source": {"file": "files/01-焊工证.pdf", "page": 2, "excerpt": "证书编号：…"}},
        {"name": "有效期至", "value": "2027-03", "source": {"file": "files/01-焊工证.pdf", "page": 2, "excerpt": "有效期至2027年3月"}},
                {"name": "平台记录", "value": "licList 3 条，含同号证书", "source": {"file": "tool:cert-registry", "locator": "tool-results/20261022-152000-cert-registry.json；对应本证查询"}}
      ],
      "reasoning": "按什么要求、怎样比、得出什么。",
      "reason": "非 passed/failed 时必填：缺什么、为什么判不了。",
      "toolCalls": [{"tool": "cert-registry", "at": "2026-10-22T15:20:00+08:00", "summary": "查到 3 张现行证，含本证"}],
      "differenceNote": "与服务器不同时必填：服务器缺施焊日期，本次从 files/03 第 4 页读到。",
      "nextSteps": ["请施工方补实际施焊记录（REQ-24-04）"]
    }
  ],
  "missingMaterials": ["REQ-24-04 实际施焊记录：未挂载"],
  "relatedNodeSuggestions": ["R29：施焊记录与焊工钢印号对应关系需在节点 29 复核"],
  "limitations": ["原件第 7–9 页为扫描件且模糊，未能确认证书照片与本人一致"],
  "reviewedFiles": [
    {"file": "files/01-焊工证.pdf", "method": "read", "pages": "1–2"},
    {"file": "files/05-质量计划.pdf", "method": "search", "pages": "4、9 细读", "note": "只细读检索命中本节点关键词的页"},
    {"file": "files/09-无损检测资质.pdf", "method": "skipped", "note": "属节点 03/38 资料，检索无本节点关键词"}
  ]
}
```

逐件核对项判符合时加 `"coverage": {"items": 12, "checked": 12, "source": "到货清单第 3 页共 12 批"}`（其他结论不校验 coverage：知道件数照实填，不知道保留骨架的 `null`；件怎么数、`checked` 算什么，见 audit-method 的“逐件核对项”）；发现两处资料互相矛盾时在该检查加 `"conflicts": ["质量证明书炉批号 A123，到货验收记录写 A132"]`。

判不了但风险高的事项（设计材质超出全部已交证书、计划人数多于交证人数等）加报告级 `"riskFlags": [{"level": "high", "check": "AC-R24-02", "flag": "一句话说明", "basis": "依据或出处"}]`，`level` 为 high 或 medium，会显示在 `audit.md` 开头。

`report` 另外强制：报告里不得出现完整 18 位身份证号；`reviewedFiles` 覆盖包里每一份文件（`method` 为 read/pages/thumbs/search/text/skipped，skipped 要写 `note`，没有文字层的文件不能只标 search）；证据追溯项与逐件核对项按 [audit-method.md](audit-method.md) 的严格口径。

转成文字的 Office 文件：`file` 写原件 `files/…`，`locator` 写 `"text/<文件名>.txt 第 N 行"`。`reviewedFiles.method` 还接受旧写法 `textutil`（同 `text`）。

`serverResult`、`agreesWithServer` 只在服务器节点由 `report` 写入，不用自己填；`auditor` 写你自己的助手名和所用模型名；先跑 `skeleton` 生成骨架再填空最省事。`verdict` 取值：`passed`、`failed`、`evidence_insufficient`、`human_review_required`、`not_applicable`、`not_executed`。

符合／不符合项引用的扫描件或扫描页，阅读方式须为 `read` 或 `pages`，并如实注明读过的页；`thumbs`、`skipped`、纯检索或转文字不能代替该页取证。没有检索存档时仍检查所引 PDF 页的文字层，不运行 OCR。缺证结论仍可交付，须说明未读或未获证据的原因。校验器不自动补造旧报告的事实；重新校验发现缺项时报告原因。
