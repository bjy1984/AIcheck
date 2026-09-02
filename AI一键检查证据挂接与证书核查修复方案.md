# AI 一键检查：OCR 全文错挂节点 与 证书节点未调用核验工具 —— 修复方案

日期：2026-09-02
范围：`backend/libs/review_orchestrator/*`、`backend/libs/material_targeting.py`、`backend/libs/review_grounding.py`、`backend/business_packs/engineering_inspection_v1/*`、`backend/apps/api/routes.py`（`ai_recheck` / `ai_recheck_batch`）

---

## 0. 结论先行

两个问题背后是同一个结构性缺口：**LLM 拿到的输入没有携带"这份资料为什么在这个节点"的来源信息，而节点必须做的核验动作又没有被固化为不可跳过的步骤。**

| 问题 | 根因（已在代码中核实） | 处置原则 |
|---|---|---|
| OCR 全文挂错节点，结论跟着错 | ① 节点无挂接时回退把项目里**所有未分类资料**整篇喂给该节点；② 自动挂接"待确认"与"已确认"资料同权进入正式复核；③ 提示词里的 OCR 片段只带 `documentVersionId`，没有资料类型、审查要点、挂接来源，模型无法识别串档；④ 整份 OCR 全文而非审查要点命中页进入提示词 | **挂接可信度分级 + 节点级证据契约**：正式复核只吃"已确认或确定性挂接且类型与审查要点一致"的资料；提示词带资料清单；串档疑似由确定性预检先报出来 |
| 需要验证证书的节点没有调用证书核验 tool | ① 主复核调用不传 `tools=`，工具只作为文本列出，模型根本无法调用；② `verify_license_or_certificate` / `check_license_registry_match` / CNSE 登记查询在原子检查绑定表里**零绑定**，`execute_node_tool_plan` 永远不会执行；③ `verify_license_or_certificate` 只处理焊工证；④ `check_date_covers` 绑定了 7 处但参数构造只覆盖 R01/R02，其余节点恒为 `evidence_insufficient`；⑤ 节点 1/2/3/38 没有 fact builder，R01/R02 已绑定的有效期/范围检查拿到空事实，同样恒为 `evidence_insufficient` | **证书核验做成确定性必经步骤，而不是模型可选**：泛化证书核验工具、绑定到每个证书节点、服务端硬门禁"核验未通过不得判满足"；登记核验失败走人工核验任务；第二阶段再给证书节点开受控 function calling 并校验"必调工具是否真的被调了" |

---

## 1. 问题一：OCR 全文错挂节点

### 1.1 现状链路（核实）

```
上传 → OCR → LLM 分类器(材料类型) ─fallback→ 关键词分类
     → run_material_targeting 打分 → node_evidence_links (+ 自动 binding)
     → ai_recheck 取输入版本 → build_grounded_review_input 把这些版本的
       fields/tables/seals/fragments(整篇 OCR) 打包成 groundedOcrEvidence → 提示词
```

关键代码：

- 输入版本选择 [routes.py:9292-9298](backend/apps/api/routes.py:9292)：只排除 `manualStatus == rejected`，**pending 自动挂接与 confirmed 同权**；无链接时回退 `targeting_input_versions_for_node`。
- 回退链 [material_targeting.py:1506-1516](backend/libs/material_targeting.py:1506)：readiness → 人工 bindings → **`unclassified_input_versions_for_project`**，即项目里所有 `unclassified_material` 且 OCR 成功的资料整批进入该节点。这是"整篇无关全文污染节点"的最直接来源。
- 自动挂接判据 [material_targeting.py:940](backend/libs/material_targeting.py:940)：`material_type_is_binding_compatible` 只认最终 `materialTypeCode`。分类器判错类型（LLM 分类 / 关键词回退），挂接就整体错，且 `needHumanConfirm` 不阻断复核。
- 提示词 OCR 载荷 [review_grounding.py:197](backend/libs/review_grounding.py:197) / [review_grounding.py:691](backend/libs/review_grounding.py:691)：`fragments[]` 每条只有 `documentVersionId / pageNo / text / bbox / confidence`，**没有 fileName、materialTypeCode、命中的 reviewPointId、挂接来源、人工确认状态**。模型无法区分"焊工证"和"设计许可证"的片段，也不知道哪份资料是回退兜底进来的。
- `ai_recheck` 未按 `formalEvidenceEligible` 过滤，readiness 里区分出的 advisory 链接（无页码/坐标/原文定位）也进入正式复核输入 [material_targeting.py:1306-1311](backend/libs/material_targeting.py:1306)。
- 预算裁剪 [evidence_budget.py:85](backend/libs/review_orchestrator/evidence_budget.py:85) 以整份资料为单位丢弃：错挂资料占了预算，正确资料反而可能被裁掉。

### 1.2 设计：挂接可信度分级 + 节点级证据契约

#### A. 给每条 node_evidence_link 补齐"来源画像"

新增字段（写入 `node_evidence_links`，并进 `inputHash`）：

| 字段 | 取值 | 来源 |
|---|---|---|
| `mountSource` | `manual` / `auto_deterministic` / `fallback_unclassified` | 已有 `boundNodeIds`、`bindingEligible` 分支 |
| `classificationSource` | `llm` / `keyword` / `declared` | `_execute_document_material_classification` 已有分支 |
| `classificationConfidence` | 0..1 | LLM 分类器输出；关键词回退给固定低值 |
| `typeConsistency` | `consistent` / `declared_conflict` / `point_conflict` | 上传者 `materialCategory` vs `materialTypeCode` vs 审查要点 `materialTypeCode` |
| `manualStatus` | 已有 `pending/confirmed/rejected` | 已有 |
| `evidenceTier` | `formal` / `advisory` | 已有 `formalEvidenceEligible` |

#### B. 正式复核（formal）的输入契约

`ai_recheck` 中 `input_document_version_ids` 改为分两桶：

```
formalVersions   = links where manualStatus == confirmed
                   or (mountSource == auto_deterministic
                       and evidenceTier == formal
                       and typeConsistency == consistent
                       and classificationConfidence >= T_formal)
advisoryVersions = 其余非 rejected 链接（仅列清单，不喂 OCR 全文）
```

- **删除 formal 模式的 `unclassified_input_versions_for_project` 回退**。该回退只保留给 `gap_precheck`，且清单里明确标注 `mountSource: fallback_unclassified`。
- formal 模式下 `formalVersions` 为空 → 与现有 `readyForAiFormal` 逻辑一致，降级为 `gap_precheck` 并返回明确原因 `MOUNT_UNCONFIRMED`；批量接口 [batch_review_routes.py:70](backend/apps/api/batch_review_routes.py:70) 新增该 skip reason。
- `inputHash` 加入 links 的 `manualStatus + mountSource`：资料被人工改判后旧 run 自动失效，避免"引用了后来被驳回资料"的结论继续存活。

#### C. 提示词加"资料清单"，OCR 片段带类型标签

`grounding_prompt_block` 增加 `documentManifest`：

```json
{
  "documentVersionId": "V-...",
  "fileName": "设计单位许可证.pdf",
  "materialTypeCode": "design_license",
  "materialTypeName": "设计单位许可证",
  "servesReviewPoints": ["RP-01-003"],
  "mountSource": "auto_deterministic",
  "manualStatus": "confirmed",
  "classificationConfidence": 0.91,
  "evidenceTier": "formal",
  "pageCount": 3
}
```

`fragments[]` / `fields[]` / `seals[]` 每条增加 `materialTypeCode` 与 `reviewPointIds`。`STRICT_GROUNDING_REQUIREMENTS` 增加两条硬要求：

1. 只能引用 `evidenceTier == formal` 且 `servesReviewPoints` 命中本节点审查要点的资料作为 `passed/failed` 的证据；
2. 对清单里 `advisory` 或类型与本节点审查要点不符的资料，只允许输出 `findingType: suspected_mis_mount`、`suggestedAction: human_confirm`，不得据此下业务结论。

#### D. 按审查要点裁剪 OCR 全文，而不是整篇

`build_grounded_review_input` 增加 `reviewPointFocus` 模式：

- 第一层：审查要点已定位的 `evidenceFacts`（页码 + bbox + 原文，`evidence_facts_for_point` 已算好）；
- 第二层：命中页及相邻 1 页的 `fragments`；
- 第三层：整篇全文**不进提示词**，只在 tool-loop 模式下通过 `get_document_ocr_result` 按需拉取。

预算裁剪从"整份丢"改为"先丢第二层再丢整份"，并在 `truncationRequirements` 里说明。

#### E. 确定性"挂接一致性预检"

在 `load_ocr_result` 之前新增步骤 `validate_mount_consistency`（进 `REVIEW_GRAPH_STEPS`，纯服务端，无 LLM）：

- 对每个输入版本重算 `typeConsistency`；
- 同一版本被挂到审查要点类型互斥的多个节点 → `cross_node_conflict`；
- 结果写入 `ruleResults`，并直接生成系统 finding：`资料「xxx.pdf」疑似挂接错误（分类 design_license，本节点要点要求 welder_certificate），请人工确认`；
- 命中的版本从 `formalVersions` 移到 `advisoryVersions`，即使人工尚未处理，也保证错挂资料**不会成为结论证据**。

#### F. 人工确认闭环（前端）

- 节点页"AI 一键检查"按钮旁列出 `pending` 自动挂接资料，可一键确认/驳回（后端 [routes.py:10745](backend/apps/api/routes.py:10745) 已有 `manualStatus` 写接口，需核实前端是否已接）。
- 批量检查前弹出"有 N 份资料挂接待确认，继续将按缺口预检执行"的提示。
- 复核结果页：引用了 advisory 资料的 finding 标黄。

### 1.3 验收标准

- 构造"故意错挂"回归集（用现有真实项目，把焊工证挂到设计单位许可证节点、把未分类资料留在项目里）：正式复核**不得引用**错挂资料；必须产出 `suspected_mis_mount` finding；`promptAudit` 里 `documentManifest` 与输入版本一致。
- 单元测试：`targeting_input_versions_for_node` 在 formal 模式不再返回未分类资料；`inputHash` 随 `manualStatus` 变化。

---

## 2. 问题二：证书节点未调用证书有效性核查工具

### 2.1 现状链路（核实）

- 主复核 LLM 调用 [execution.py:2311](backend/libs/review_orchestrator/execution.py:2311) 只传 `response_format=json_object`，**不传 `tools=`**；工具目录以文本 `availableRuntimeTools` 出现在 payload（[execution.py:1990](backend/libs/review_orchestrator/execution.py:1990)），提示词要求"用它规划"，但模型没有调用通道。真实 tool loop 只存在于 R12、R13–R18 受控模式、R19 语义审查、AI 复核对话。
- 证书相关工具存在但未接入运行：
  - `verify_license_or_certificate` [runtime_tools.py:465](backend/libs/review_orchestrator/runtime_tools.py:465)：`certificateType` 硬编码 `welder_certificate`，只遍历 `welderCertificates`；许可证类证书返回空 `verifications` 且 `status: succeeded`。
  - `check_license_registry_match`、`search_cnse_persons`、`search_cnse_organizations`：在 `atomic_check_tool_bindings.yaml` 中**零绑定**，只有复核对话 agent 能调用。
- `check_date_covers`（有效期覆盖）绑定了 R01/R02/R03/R08/R35/R45/R66 共 7 处，但参数构造 [executor.py:365](backend/libs/review_tools/executor.py:365) 只处理 `r01_design_license_period` / `r02_installation_license_period` 两个 profile，其余节点缺 `validFrom/validUntil` → 恒 `evidence_insufficient`。
- `load_ocr_result` 对所有节点固定跑 `extract_structured_fields(materialTypeCode="welder_certificate")` [execution.py:1621-1626](backend/libs/review_orchestrator/execution.py:1621)，设计/安装/制造许可证的结构化字段抽取不在这条路径。
- 节点 1/2/3/38 **没有 fact builder**：`run_step("load_context")` 只为节点 12–23 与 24–34 构造 `businessFacts`（[execution.py:1500-1520](backend/libs/review_orchestrator/execution.py:1500)），`designLicense.*` / `installationLicense.*` / `ndtPersonnel.*` 这些 `requiredFacts` 在整个 `libs/` 里没有任何生产者。结果是 R01/R02 已绑定的 `check_date_covers` / `check_*_license_scope` 拿到空 facts，恒为 `evidence_insufficient`——证书有效期"名义上绑定了，实际上从未核过"。
- 绑定集 `lifecycleStatus: draft`，`pilotRules` 含 R01/R02/R03/R24/R29，但**不含 R38**（以及 R08/R35/R45/R66）：这些节点在 formal 模式下 `compile_node_tool_plan` 直接抛错，工具计划不执行（[executor.py:19-32](backend/libs/review_tools/executor.py:19)）。

### 2.2 设计：证书核验做成确定性必经步骤

#### A. 证书核验能力矩阵（配置化，放进 business pack `materials.yaml` / 新建 `certificate_profiles.yaml`）

| 节点 / 规则 | 证书类型 `certificateType` | 必核字段 | 必做检查 |
|---|---|---|---|
| 1 / R01 | `design_license` 设计单位许可证 | 编号、持证单位、发证机关、有效期起止、许可范围 | 期覆盖、范围覆盖、主体一致、印章、登记核验 |
| 2 / R02 | `installation_license` 安装许可证 | 同上 | 同上（失败 → 联系单） |
| 3 / R03 | `ndt_agency_approval` 无损检测机构核准 | 编号、机构、核准项目代码、有效期 | 期覆盖、项目覆盖、登记核验 |
| 12 / R12 | `manufacturing_license` 制造许可证 | 编号、单位、范围、有效期 | 期覆盖、范围覆盖、登记核验（已有人工核验流程） |
| 13 / R13 | `supervision_certificate` 监检证书 | 编号、产品、日期 | 完整性（已有 evaluate_r13_*） |
| 15 / R15 | 境外制造许可 | 同 R12 | 已有 `requireRegistryVerification` |
| 24、29 / R24、R29 | `welder_certificate` 焊工证 | 编号、姓名、身份证、合格项目、有效期 | 期覆盖施焊日、项目覆盖、身份一致、印章、**人员登记核验** |
| 38 / R38 | `ndt_personnel_certificate` 无损检测人员证 | 编号、姓名、方法/级别、有效期 | 期覆盖、方法级别覆盖、人员登记核验 |

每类证书一个 profile：`extractionMaterialTypeCode`、字段映射（`validFrom/validUntil/holder/issuer/certificateNo/scope`）、`periodSource`（施工期 / 施焊日 / 检测日）、`registryKind`（`cnse_org` / `cnse_person` / `manual_record` / `none`）。

#### B. 泛化 `verify_license_or_certificate` → `check_certificate_validity`

输入：`documentVersionIds`、`certificateType`、`period {start,end}`、`expectedHolder`、`requiredScopes`。
内部按 profile 顺序执行并汇总为统一 schema：

```json
{
  "toolName": "check_certificate_validity",
  "result": "passed | failed | evidence_insufficient",
  "certificateType": "design_license",
  "certificates": [{
    "documentVersionId": "V-...",
    "certificateNo": "TS1210xxx",
    "holder": "...", "issuer": "...",
    "validFrom": "2024-01-01", "validUntil": "2028-01-01",
    "checks": [
      {"code": "period_covers", "passed": true, "expected": "...", "actual": "..."},
      {"code": "scope_covers", "passed": true},
      {"code": "holder_matches", "passed": true},
      {"code": "issuer_seal_matched", "passed": false},
      {"code": "registry_verified", "passed": null, "status": "registry_unavailable"}
    ],
    "riskFlags": ["issuer_seal_not_matched", "registry_unavailable"],
    "evidenceRefs": [{"documentVersionId": "...", "pageNo": 1, "bbox": [...], "quotedText": "有效期至2028年1月1日"}]
  }]
}
```

复用已有确定性件：`check_date_covers`、`check_design_license_scope` / `check_installation_license_scope` / `decode_ndt_approval_item_codes` / `decode_welder_qualification`、`recognize_document_seals`、`certificate_risks`。任一必核字段缺失 → `evidence_insufficient`，**永不 passed**（沿用 `check_date_covers` 现有原则）。

#### C. 绑定进原子检查绑定表 + 补参数 profile

- 在 `atomic_check_tool_bindings.yaml` 为上表每个节点增加一条 `AC-Rxx-CERT` 绑定：`tools: [extract_document_fields, check_certificate_validity, validate_evidence_grounding]`，`argumentProfile: rxx_certificate_validity`，`failurePolicy: business_rule_result`。
- `build_tool_arguments` 增加通用分支：`profile` 以 `_certificate_validity` 结尾时从 profile 表读字段路径，一次性修掉 R03/R08/R35/R45/R66 的 `check_date_covers` 无参问题。
- `load_ocr_result` 的 `extract_structured_fields` 预调用改为按节点 profile 的 `extractionMaterialTypeCode` 执行，不再固定焊工证。
- 为节点 1/2/3/38 新增 fact builder（`build_r01_business_facts` 等，产出 `designLicense.* / installationLicense.* / ndtAgency.* / ndtPersonnel.*`），并纳入 `load_context` 的分派表；这是 R01/R02 有效期核验从"恒证据不足"变为真正可判的前提。
- 把 R38（及 R08/R35/R45/R66）加入 `pilotRules`，或发布绑定集，确保 formal 模式真正执行。

#### D. 服务端硬门禁

- 固定聚合器：证书节点若 `check_certificate_validity.result ∈ {failed, evidence_insufficient}`，节点结论不得为"满足要求"（与 [routes.py:13146](backend/apps/api/routes.py:13146) 现有 `readyForAiFormal` 门禁同位置）。
- `review_quality_gate`：证书节点的 draft 若未引用 `check_certificate_validity` 的 evidenceRefs，降级为 `insufficient_evidence`，置信度上限 0.55（复用 [execution.py:1877](backend/libs/review_orchestrator/execution.py:1877) 已有降级机制）。
- 提示词 `ruleResults` 中带上完整 `checks[]`，并沿用"`tool_result_primary` 模式下 LLM 不得把 failed 改写为 passed"的既有原则（见 `llm交互.md` §2.3）。

#### E. 登记核验（在线 + 人工兜底）

- `registryKind = cnse_org / cnse_person` 时，在 `run_rule_engine` 内调用 `search_cnse_organizations` / `search_cnse_persons`（[runtime_tools.py:664/709](backend/libs/review_orchestrator/runtime_tools.py:664)），按 `certificateNo + holder` 缓存 7 天。
- 三态：`registry_verified` / `registry_mismatch`（→ failed）/ `registry_unavailable`（限流、反爬、超时）。
- `registry_unavailable` → 创建人工核验任务（复用 R12 的 `plan_r12_human_verification` 与 `check_license_registry_match` 的"人工官网核验记录"契约），run 进入 `waiting_human_input`，节点结论保持 `evidence_insufficient`，**绝不因查不到而放行**。

#### F. 第二阶段：证书节点开受控 function calling，并校验"必调工具是否真的被调了"

- 证书节点切到 R13–R18 已有的 `llm_tool_call_with_workflow_guard` 模式（[execution.py:833](backend/libs/review_orchestrator/execution.py:833)）：`tools = [inspect_tool, *build_llm_tools_for_runtime(required_tools)]`，`required_tools` 包含 `check_certificate_validity`（及需要时的登记查询）。
- 守卫新增 `requiredToolCallsSatisfied` 校验：模型结束循环时若 `required_tools` 中任一工具未被调用或未成功，run 不接受模型结论，改用 C 步的确定性结果并记录 `REQUIRED_TOOL_NOT_INVOKED` 事件。这条直接对应"该调没调"的问题，并可审计。
- 主复核路径（非证书节点）暂不开放 function calling，避免预算与时延失控。

### 2.3 验收标准

- fixtures：过期证、范围不覆盖、持证人与施焊记录不一致、发证机关印章缺失、登记查无、字段缺失六类样本；每类断言 `check_certificate_validity.result` 与节点结论，且 `promptAudit.toolCalls` 里存在该工具调用。
- 现有 R24 pilot 用例回归不变。
- 受控 tool-call 模式：故意让模型不调工具的 mock，断言 run 记录 `REQUIRED_TOOL_NOT_INVOKED` 且节点不判满足。

---

## 3. 实施排期

| 阶段 | 内容 | 预估 |
|---|---|---|
| P0 立即止血 | formal 模式删除未分类回退；`inputHash` 纳入 `manualStatus`；提示词加 `documentManifest` 与片段类型标签；`check_date_covers` 通用参数 profile；`load_ocr_result` 抽取类型按节点走 | 2 天 |
| P1 挂接可信度 + 证书核验落地 | 来源画像字段与迁移；formal/advisory 双桶；挂接一致性预检步骤；`check_certificate_validity` 与 8 个节点绑定；硬门禁；前端待确认列表 | 1 周 |
| P2 登记核验 + 受控调用 | CNSE 在线核验三态与人工兜底；证书节点受控 function calling 与必调校验；错挂/证书回归集进 CI | 1–2 周 |

## 4. 需要业务侧确认的点

1. `T_formal`（自动挂接直接进正式复核的分类置信度阈值）初值建议 0.85，低于则必须人工确认。
2. 焊工证、无损检测人员证的在线登记核验是否允许走全国特种设备公示平台，还是一律人工核验记录。
3. R38 及 R08/R35/R45/R66 是否本轮一并纳入 `pilotRules`。

## 5. 已核实 / 未核实

已核实（代码阅读）：
- 前端 `AICheck/Workbench.vue` 已有证据链接确认/驳回按钮（第 6461/6469 行），F 步只需补"待确认清单前置到一键检查入口"与批量提示。
- `pilotRules` 当前含 R01/R02/R03/R06/R07/R09/R12–R34/R60–R62，绑定集 `lifecycleStatus: draft`。
- 节点 1/2/3/38 无 fact builder（见 2.1）。

未在生产验证：本方案全部基于代码阅读，未对生产 run 的 `promptAudit` 抽样核对；P0 落地前建议先抽 3 个证书节点的真实 run 看 `ruleResults` 是否如分析所述恒为 `evidence_insufficient`。
