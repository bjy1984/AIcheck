# 用一條規則跑真實資料，抓出三個真缺口（2026-09-10）

## 起因

密鑰之外，「R43 能不能對真實文件出結論」一直只有單元測試在證明。單元測試餵的是
手造 state，從沒真的把生產庫那張材料質量證明表**送進工具計畫**跑一遍。
於是寫了 `scripts/evaluate_rule_over_state.py`（只讀，不建審查運行）對
`P-2026-ECD202 / DV-D66DB781-V1` 乾跑 R43，三次失敗、三個缺口，逐個修掉：

| 乾跑結果 | 根因 | 修法 |
|---|---|---|
| `domainRowsBuilt: 0`，`r43_source_object_conflict` | 真實核查記錄一張表列全部元件（6 張證明書），構建器不替人挑 → 「來源含糊」。全倉**沒有任何對象選取欄位**，單元測試都只餵單列表 | `read_ndt_tables` 認顯式的 `run["selectedObjectIds"]`；不給就維持「含糊即拒判」；它掛在 run 上，fixture 凍結整個 run，重放自然帶著 |
| `r43_certificate_scope_missing` | `build_tool_arguments` 給 R11／R35～R40／R45／R64～R67 各有「把 facts 攤進 arguments」的特例，**R43 這批 18 個 installation 工具與 R63／R68 沒有**——收到的只有 `binding.parameters`。接 frozen-domain 那批時漏了這根線；端到端測試只斷言到 facts，沒執行計畫，所以沒抓到 | `FROZEN_DOMAIN_INPUTS` 20 條映射 + 守衛測試：每個走 `evaluate_frozen_domains` 的工具都必須在表裡、且名稱與其事實構建器一致 |
| `evidence_not_from_selected_document` | 判據側 `_refs()` 要求每條引用都有非空 `quotedText`，只有 bbox 不算；表格列的引用只有 bbox，因為 `_table_location` 只認 `contentMarkdown`，而 MinerU 表只有 `html` | **不是**從 normalizedRows 拼引文——`test_r35` 那條「不得偽造原文引用」擋掉了我第一版就是這麼做的。改成引記錄下來的 `html` 去標籤後的原文 |

第三條值得多說一句：第一版我從欄位值拼了一段當引文，測試立刻紅——
`"P1 | NDT1 | conforming | [{...}]"` 根本不是頁面上印的字。那條測試的名字就是它守的東西。

## 修完的乾跑（真實資料，只讀）

```
AC-R43-01 evidence_insufficient
    passed                 materialcertificate_certificate_documentno      | actual= 20260213951
    passed                 materialcertificate_certificate_materialgrade   | actual= S30408
    evidence_insufficient  materialcertificate_certificates_and_marks_reviewed          | actual= None
    evidence_insufficient  materialcertificate_material_grade_matches_specification     | actual= None
    evidence_insufficient  materialcertificate_required_heat_treatment_inspection_and_tests_done | actual= None
    evidence_insufficient  materialcertificate_compliance_statement_submitted_to_inspector | actual= None
quotedText: 序号 | 元件名称 | 材质/标准 | … | 产品质量证明书编号
            1 | 不锈钢无缝钢管 | 材质:S30408标准:GB/T14976-2025 | …
```

這正是設計上的預期狀態：表格能給的兩項過了，**四個**判斷布林（不是先前說的三個，
還有 `compliance_statement_submitted_to_inspector`）等 agent 讀正文填。
鏈路 OCR → 簽名分類 → 欄位對映 → 對象選取 → 執行器 → 凍結判據，**在生產資料上第一次走通到判據本身**。

## 密鑰那邊的更正

使用者重新生成的 `sk-sp-` key 是好的，是 **Token Plan** 的 key，端點
`https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。我連錯三個端點
（按量計費 → Coding Plan → Token Plan）。實測：三個文字模型與視覺可用、模型名不用改；
`qwen-vl-max` 與 `text-embedding-v4` 不存在——視覺改 `qwen3.7-plus`，embeddings 仍需
按量計費 key。詳見 `2026-09-10-llm-key-invalid-in-production.md` 的更正段。

## runtime.env 是生成的，不能手改（我先前給錯了指引）

`deploy_to_server.sh --backend` 每次都用 `backend/deploy/build_runtime_env.py` 從
`/home/dev-bjy/aicheck-secrets.env` 重新拼出 `runtime.env`——`AICHECK_LLM_API_KEY` 與
`AICHECK_EMBEDDING_API_KEY` 都是從 `AICHECK_LLM_VISION_API_KEY` 複製的，base 寫死 dashscope。
手改的五行下次部署就被蓋掉（倉庫記著 2026-08-14 就這樣丟過一次）。

生成器已改：憑證檔有 `AICHECK_TOKEN_PLAN_API_KEY` 就整體切到 Token Plan（文本與視覺端點、
視覺模型 `qwen3.7-plus`），文本模型名不動，embeddings 留在按量端點（Token Plan 沒有），
密鑰取憑證裡顯式的 `AICHECK_EMBEDDING_API_KEY`、沒有就沿用視覺那把。四條測試釘住。

## 還差什麼

1. 使用者往 `aicheck-secrets.env` 加一行 `AICHECK_TOKEN_PLAN_API_KEY=…`，我跑 `deploy_to_server.sh --backend`
2. `run_domain_judgment.py --persist`：agent 讀正文，填那四個布林（含反編造閘門）
3. `evaluate_rule_over_state.py --object-id …`：R43 出真實結論
4. 開工位模式重跑 → `export_review_acceptance_fixture.py` 導出驗收證據
