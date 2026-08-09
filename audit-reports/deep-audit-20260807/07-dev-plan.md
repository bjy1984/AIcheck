# AIcheck 审计修复 · 详细开发计划

- 基线：`8ec3f56`（main）· 审计报告：`deep-audit-20260807`
- 原则：**先止血误报/漏报 → 五态打通 → 人工闭环 → 部署安全 → 结构债增量治理**
- 不做：一次性重写 routes/Workbench；缺基准文件前深挖 device/compliance；把向量 RAG 硬塞进主审查正确性链路

---

## 0. 目标与成功标准

### 业务目标
1. 审查结论与已确认五态口径一致，不再把「字段缺失」误报为不符合。
2. 监检人员能在主卡片看到真实 AI 建议结论，并能保存「证据不足 / 需专业判断」。
3. 人工推翻 AI、人工修正 OCR 事实均有审计留痕；重跑由人工显式触发、不跨节点。
4. 认证默认安全；能力清单与实现一致。

### 工程目标
- 每个修复项有：单元/契约测试断言**业务口径**（不是固化旧行为）。
- 涉及结论词汇的改动前后端同一 PR 合入（或成对 PR 同日合并）。
- 存量绿测若断言旧行为，随修复同步改断言，禁止 `--no-verify` 绕过。

### 不做成功标准
- 不要求本计划内完成内存态全面迁库、OpenAPI 全量补齐、Workbench 整文件拆分。

---

## 1. 统一约定（所有阶段共用）

### 1.1 五态唯一映射表（落码，禁止散落硬编码）

| 业务口径 | 后端内部 | 人工结论（中文） | 节点状态建议 |
|---|---|---|---|
| COMPLIANT | `passed` | 满足要求 | 已通过 |
| NON_COMPLIANT | `failed` | 需补正 | 需补正 |
| INSUFFICIENT_EVIDENCE | `evidence_insufficient` | 证据不足/待补充 | 待补充（新建或复用「部分提交」语义需确认） |
| NOT_APPLICABLE | `not_applicable` | 不适用 | 不适用（**禁止**映射「需补正」） |
| REQUIRES_HUMAN_REVIEW | `human_review_required` | 需专业判断 | 待审查 / 需人工确认（与产品确认文案） |

另设系统态（不对业务展示为「结论」）：
- `execution_error`：工具崩溃/超时等，**不是**业务结论。

### 1.2 聚合优先级（R-2/R-3/R-4）

```
execution_error
  > failed（且 grounding 通过）
  > human_review_required
  > evidence_insufficient
  > not_applicable
  > passed
```

规则补充：
- 同一原子项内若 grounding → `evidence_insufficient`，则该原子项不得输出 `failed`（一票否决降级）。
- 字段级检查：全部失败原因为 `missing` → `evidence_insufficient`；存在 `mismatch` → `failed`。
- 文件本体缺失 → `failed`（保持现有正确行为）。

### 1.3 分支与发布策略
- 分支：`fix/audit-20260807-<phase>-<short-name>`
- 每个 Phase 可拆多个 PR，但 **Phase B（五态）必须前后端同批**
- 建议打 tag：`audit-fix-phase-a` … 便于回滚

### 1.4 估时说明
- 人天按「熟悉本仓的 1 名全栈/后端」计；含测试与自测，不含跨团队业务确认等待时间。
- 带「确认」标记的项：开发前需业务/产品书面确认 0.5 天内闭环，否则排到确认后。

---

## 2. Phase A · 止血（P0）— 预计 3–4 人天

> 目标：立刻消除最大误报与错误整改指令；补上推翻留痕。

### A1. 绑定表 implementationStatus 纠偏（R-5）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 0.5 人天 |
| 改动 | `business_packs/engineering_inspection_v1/atomic_check_tool_bindings.yaml`：R12–R34 → 与实现一致的已实现标注；R35–R69 → 未实现/草稿标注（与 `lifecycleStatus`/`pilotRules` 语义对齐） |
| 测试 | 加断言：已接线规则段标注 ≠ 未接线规则段；可选脚本核对 bindings vs 实际模块存在性 |
| 验收 | 业务方目视能力清单不再颠倒；`require_published` 行为不变 |

### A2. 字段缺失 ≠ 不符合（R-1）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 1 人天 |
| 改动 | `business_tools.py`：`checked_result` / `check_required` 等区分 `missing` / `mismatch`；聚合逻辑按 1.2 |
| 回归注意 | 改写 `test_review_*` 中断言 `failed` 的用例：空 facts / 缺字段应期望 `evidence_insufficient` |
| 验收 | 给定实测：`check_required(fields, {})` → insufficient；有值但不合规 → failed；文件本体缺失仍 failed |

### A3. 「不适用」节点状态映射修复（N-1）
| 项 | 内容 |
|---|---|
| 负责人 | 后端（前端若展示节点状态文案需同步） |
| 估时 | 0.5 人天 |
| 改动 | `save_review_opinion`：`不适用` → 节点状态「不适用」（或产品确认的终态名）；**禁止** `需补正` |
| 数据 | 评估是否需迁移历史「不适用却标需补正」的脏数据（脚本可选） |
| 验收 | 保存「不适用」后施工单位工作台不出现补正待办 |

### A4. save_review_opinion 推翻留痕（R-7）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 1–1.5 人天 |
| 改动 | opinion 增加：`aiRunId` / `aiSuggestedResult` / `overriddenFromAi`；保存时 `add_audit(before, after)`；尽量关联当前节点最新 ai_run |
| 对齐 | 参考 ReviewRun `human_decision` 通道的事件模型，字段命名统一 |
| 验收 | 采纳与推翻均可在审计日志还原「AI 原判 → 人工结论」；无 AI 时 `overriddenFromAi=false` 且 ai 字段可空 |

### Phase A 交付物
- [ ] PR(s) 合入 + 回归测试全绿
- [ ] 更新审计跟踪：在 README 发现清单标注「已修」
- [ ] 简短发布说明（给监检试用）

### Phase A 风险
- 存量测试大量断言旧 `failed` 行为 → 预留 0.5 天专门改测。

---

## 3. Phase B · 五态打通（P0/P1）— 预计 5–7 人天

> 目标：聚合层、人工结论、suggestion 主卡片、前端展示一套词表打通。

### B1. 结论词汇模块（共享契约）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 + 前端 |
| 估时 | 1 人天 |
| 改动 | 后端新增单一映射模块（如 `libs/review_conclusion.py`）；前端 `constants/reviewConclusion.ts`；OpenAPI/文档同步枚举 |
| 验收 | 全仓禁止再散落三套硬编码中文/英文；grep 抽查通过 |

### B2. 聚合器重排（R-2 + R-3 + R-4）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 1.5–2 人天 |
| 改动 | `executor.py`：`aggregate_tool_results` / `aggregate_atomic_results` 按 1.2；执行故障走 `execution_error`，不伪装 insufficient；grounding 一票否决 |
| 范本 | 对齐 `aggregate_r19_atomic_judgments` |
| 测试 | 用审计报告附带实测用例固化为单元测试 |
| 验收 | R-2/R-3/R-4 四组实测全部符合新口径 |

### B3. suggestion.result 携带真实聚合结论（N-2）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 1 人天 |
| 改动 | `execution.py`：去掉硬编码「需人工确认」；按映射写入建议结论；文案层保留「最终由监检确认」提示字段（如 `needsHumanConfirmation: true`） |
| 验收 | Workbench 主卡片展示与 `rule_check_results` 聚合一致；不再恒为「需人工确认」 |

### B4. 人工结论选项扩展（R-6）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 0.5 人天 |
| 改动 | `save_review_opinion` 允许值扩展至五态对应中文；节点状态映射表完整（含证据不足、需专业判断）**【确认】** 证据不足时节点状态文案 |
| 验收 | API 可保存五态；非法值仍 400 |

### B5. 前端五态展示与选项（F-1）
| 项 | 内容 |
|---|---|
| 负责人 | 前端 |
| 估时 | 1.5–2 人天 |
| 改动 | Workbench（及对话式工作台若展示结论）：状态→标签→颜色→可执行动作；人工结论下拉与后端对齐；兼容旧数据字符串 |
| 验收 | 五态均可区分展示；「需专业判断」与「证据不足」动作不同（催补件 vs 打开明细） |

### B6. 置信度治理（N-3）— 可与 B5 同 PR
| 项 | 内容 |
|---|---|
| 负责人 | 前端为主，后端可选 |
| 估时 | 0.5 人天 |
| 改动 | 短期：UI 隐藏或标注「非模型置信度」；后端可改返回 `confidenceSource: "static"` |
| 验收 | 监检界面不再以「82%」误导信任分配 |

### Phase B 交付物
- [ ] 前后端同批上线说明 + 存量结论展示兼容说明
- [ ] 契约测试补充五态枚举
- [ ] （可选）数据迁移：历史 opinion 三值保留，新枚举向前兼容

### Phase B 依赖
- 依赖 Phase A 的 N-1（状态映射）先合入，避免五态映射再改一轮节点状态。

---

## 4. Phase C · 人工干预闭环（P1）— 预计 4–5 人天

> 目标：OCR 错字可改事实重跑；与推翻留痕同一审计模型。

### C1. 节点级事实修正 API（D-1）
| 项 | 内容 |
|---|---|
| 负责人 | 后端 |
| 估时 | 2–2.5 人天 |
| 接口草案 | `POST /projects/{pid}/nodes/{nid}/fact-corrections` |
| 载荷 | `fieldPath`, `previousValue`, `correctedValue`, `reason?`, `actor`, `timestamp` |
| 行为 | 持久化修正记录 + `add_audit`；**仅改本节点事实视图**；不自动重跑；不传播到其他节点 |
| 权限 | 仅 inspection（及 admin 策略按现有矩阵）；写动作进动作矩阵 |
| 验收 | 改证书编号后事实读接口返回新值；审计可还原；其他节点不受影响 |

### C2. 「基于修正事实重跑本节点」入口
| 项 | 内容 |
|---|---|
| 负责人 | 后端 + 前端 |
| 估时 | 1–1.5 人天 |
| 改动 | 显式按钮/API 触发本节点 review_run；请求体可带 `factCorrectionIds`；事件记入 review_event |
| 验收 | 未点重跑不改变 AI 结论；重跑后结论基于修正事实 |

### C3. 前端事实修正 UI
| 项 | 内容 |
|---|---|
| 负责人 | 前端 |
| 估时 | 1 人天 |
| 改动 | 在证据/字段明细处可编辑；提交修正；展示修正历史；「重跑本节点」按钮 |
| 验收 | 主路径可完成：发现错字 → 修正 → 重跑 → 看新建议 |

### Phase C 交付物
- [ ] API + UI + 审计联调通过
- [ ] 与「打回补正/重传」路径文案区分，避免用户走错

---

## 5. Phase D · 部署安全与假接口（P1/P2）— 预计 2–3 人天

### D1. 认证默认与告警（S-1 + S-4）
| 项 | 内容 |
|---|---|
| 估时 | 0.5–1 人天 |
| 改动 | `AICHECK_REQUIRE_AUTH` 默认 `true`；若允许 false：启动 stderr/日志显著警告；`/readyz` 暴露 `authRequired`；删除或收紧 `X-User-Id` 无 snapshot 回退 |
| 验收 | 裸起 API 不会静默全开；CI/compose 显式配置 |

### D2. 高敏读端点 handler 防御（S-2）
| 项 | 内容 |
|---|---|
| 估时 | 0.5 人天 |
| 改动 | 5 个 GET 补 `member_node_scope_error`（与写端点惯例对齐） |
| 验收 | 无节点权限返回 403；中间件误配时仍有兜底 |

### D3. batch-classify stub 显式化（R-9）
| 项 | 内容 |
|---|---|
| 估时 | 0.25 人天 |
| 改动 | 返回 501 或 `stub: true` + `confidence: null`；去掉写死 0.82 误导 |
| 验收 | 调用方能识别未实现 |

### D4. 角色读裁剪（S-3）**【确认】**
| 项 | 内容 |
|---|---|
| 估时 | 确认 0.5 天；若要做 2–3 人天 |
| 选项 A | 业务确认「进节点即全可见」→ 文档固化，关闭本项 |
| 选项 B | contractor 隐去意见全文/AI 理由；owner 只看汇总 → 实现响应裁剪 |
| 验收 | 与书面口径一致 |

### D5. 嵌入降级与维度（D-2 / D-4）
| 项 | 内容 |
|---|---|
| 估时 | 1 人天 |
| 改动 | Embedding 未启用禁止静默哈希写入（除非显式 env）；维度 ≠1024 显式报错；管理页可展示 index_version 占比（可后置） |
| 验收 | 配错 embedding 时失败可见，而非随机检索 |

---

## 6. Phase E · 状态机与一致性加固（P2）— 预计 3–4 人天

### E1. 节点状态转移表（N-4）
| 项 | 内容 |
|---|---|
| 估时 | 1.5–2 人天 |
| 改动 | 定义合法 `from→to`；`set_node_status` 校验；非法 → 409/422 + 审计；梳理 15 处调用点 |
| 验收 | 已通过节点不能被任意端点静默打回非法态；并发冲突可解释 |

### E2. 高风险写强制 If-Match（N-6）
| 项 | 内容 |
|---|---|
| 估时 | 0.5 人天 |
| 改动 | 结论保存、打回、归档等缺 If-Match → 428/400 |
| 验收 | 无头脚本无法绕过乐观锁；前端已发头路径不受影响 |

### E3. 多租户加载（N-5）**【确认部署模式】**
| 项 | 内容 |
|---|---|
| 估时 | 1–1.5 人天（若坚持多租户） |
| 选项 A | 单租户：文档声明 + 移除/禁用误导性多租户白名单 |
| 选项 B | `load_from_sync_postgres` 按请求 tenant_id 加载，修正 `mark_tenant_loaded` |
| 验收 | 重启后非 configured 租户数据可见（多租户模式）或明确不支持 |

---

## 7. Phase F · 结构债与体验（P2/P3，常规迭代）— 持续 2–3 周并行

> 规则：**触碰即迁移**，不做大爆炸重构。

| ID | 项 | 估时 | 做法 |
|---|---|---|---|
| F1 | A-1 OCR 出内存 | 先 2 人天评估 + 3–5 人天改造 | MinIO/DB 存全文；内存留元数据；启动断言单副本 |
| F2 | A-2 routes 按域拆分 | 每次触碰 +0.5–1 天 | inspection/documents/knowledge/review/admin |
| F3 | A-3 libs→apps 下沉 | 1–2 人天 | profiles、证书工具、cnse/samr 下沉 libs |
| F4 | A-4 OpenAPI 自动导出 | 2 人天 | FastAPI schema 为源；CI diff；淘汰手工 24 条 |
| F5 | A-5 compose 权威化 | 1 人天 | base + overlay；其余进 examples |
| F6 | F-2 Workbench 拆分 | 触碰即拆 | 按 tab/面板抽子组件 |
| F7 | F-3 主链路 e2e | 2–3 人天 | 提交→AI→采纳/推翻；OCR 失败；打回补正 |
| F8 | F-4 轮询降频/SSE | 0.5 / 2 人天 | 先 1–2s；后 SSE |
| F9 | R-8 步骤级断点 | 2 人天 | LLM 步骤缓存或 skip succeeded |
| F10 | D-3 主链路 dense 检索 | 可选 | 仅提升草稿质量，文档先标注现状 |

### A-1 容量评估门禁（开始改造前必做）
1. 用真实/近似项目估算：页数 × OCR payload × 项目数 ×（API+worker）内存。
2. 产出一页纸：峰值内存、单副本约束、淘汰策略。
3. 评审通过后再开发 F1。

---

## 8. 测试与质量门禁

### 每 Phase 必做
| 层级 | 要求 |
|---|---|
| 单元 | 新增/改写聚合、check_required、opinion 映射、状态转移用例 |
| 契约 | `test_contract.py` 覆盖新枚举与新 API |
| 审查核心 | `test_review_p0_correctness` 等与口径冲突的断言全部更新 |
| 前端 | `vue-tsc`；五态映射单测（若抽 constants） |
| 手工 | 监检工作台：缺字段 / 真不符合 / 不适用 / 推翻 AI /（Phase C）改事实重跑 |

### 禁止
- 用「测实现」的旧断言挡住口径修复。
- Phase B 只合后端不合前端（或反之）导致线上半套五态。

### 建议新增的「口径回归」专项文件
- `tests/test_review_conclusion_semantics.py`：固化审计报告中的实测矩阵（R-1～R-4、N-1、N-2）。

---

## 9. 里程碑与排期（建议）

```
W1     Phase A（止血）           可发布 hotfix
W2     Phase B（五态打通）       前后端同发
W3     Phase C（事实修正闭环）
W3–W4  Phase D（安全/假接口/嵌入）
W4–W5  Phase E（状态机/乐观锁/租户）
W5+    Phase F 并行进常规迭代；A-1 评估先行
```

| 里程碑 | 日期锚点（相对启动日 T0） | 可演示结果 |
|---|---|---|
| M1 | T0+5 工作日 | 缺字段不再误打回；不适用不再催补正；推翻有审计 |
| M2 | T0+10 | 主卡片五态可读；人工可选证据不足/需专业判断 |
| M3 | T0+15 | OCR 错字可改事实并重跑本节点 |
| M4 | T0+20 | 认证默认安全；stub/嵌入失败可见 |
| M5 | T0+25 | 节点状态机 + 强制 If-Match |

---

## 10. 人员与分工建议

| 角色 | 主要 Phase |
|---|---|
| 后端 A（审查编排） | A2, B2, B3, C1–C2, E1 |
| 后端 B（API/安全/数据） | A3, A4, B4, D1–D5, E2–E3, C 审计模型 |
| 前端 | B5, B6, C3, F6–F8 |
| 业务/产品 | S-3、证据不足节点状态文案、不适用终态名、多租户模式 —— **W1 内书面确认** |
| 测试 | 口径矩阵用例 + M1–M3 手工场景 |

最小编制：后端 1 + 前端 1，则按 Phase 串行，总日历约 **6–8 周**（含确认等待缓冲）。

---

## 11. 待业务确认清单（阻塞项，W1 并行收集）

1. 「证据不足」对应的节点状态文案与施工单位可见性（是否生成待办）。
2. 「需专业判断」是保持「待审查」还是独立状态。
3. 「不适用」终态名称（「不适用」vs「已通过(不适用)」）。
4. S-3：同节点四方是否维持全可见。
5. 部署是否承诺多租户（决定 N-5 选项 A/B）。
6. 置信度：隐藏 vs 标注静态估计（产品偏好）。

---

## 12. 明确不在本计划范围

- device_inspection_v1 / compliance_audit_v1（缺检查项基准，阻塞：待业务输入）。
- LLM 判定质量/幻觉率评测。
- Temporal/Postgres/MinIO 生产故障切换实操演练。
- 标准换版与条款解冻策略。

---

## 13. 进度跟踪模板

| ID | Phase | 状态 | PR | 负责人 | 目标日 | 备注 |
|---|---|---|---|---|---|---|
| A1 | A | todo | | | | R-5 |
| A2 | A | todo | | | | R-1 |
| A3 | A | todo | | | | N-1 |
| A4 | A | todo | | | | R-7 |
| B1 | B | todo | | | | 映射表 |
| B2 | B | todo | | | | R-2/3/4 |
| B3 | B | todo | | | | N-2 |
| B4 | B | todo | | | | R-6 |
| B5 | B | todo | | | | F-1 |
| B6 | B | todo | | | | N-3 |
| C1 | C | todo | | | | D-1 API |
| C2 | C | todo | | | | 重跑 |
| C3 | C | todo | | | | UI |
| D1 | D | todo | | | | S-1 |
| D2 | D | todo | | | | S-2 |
| D3 | D | todo | | | | R-9 |
| D4 | D | blocked | | | | 待确认 S-3 |
| D5 | D | todo | | | | D-2/D-4 |
| E1 | E | todo | | | | N-4 |
| E2 | E | todo | | | | N-6 |
| E3 | E | blocked | | | | 待确认 N-5 |
| F* | F | backlog | | | | 见 §7 |

状态：`todo` / `in_progress` / `review` / `done` / `blocked`
