# 工位模式在生產開啟；第一筆帶凍結範圍的真實運行；第一份真實驗收產物（2026-09-11）

## 做了什麼

1. 生成器加 `AICHECK_WORKSTATIONS_ENABLED=true`（`d06333c7`），`deploy_to_server.sh --backend`
   部署——這次部署腳本已修好假成功（`0284f52f`），部署後**逐項核對**容器：開關為 true、
   新檔在、標籤與伺服器 HEAD 一致、探針綠。
2. 用伺服器端引導口令（只從 `aicheck-secrets.env` 讀、經 env-file 傳、不進命令列）登入
   `inspection`，對 `P-2026-ECD202` 節點 43 打 `POST …/ai-recheck`（空 body，模式自動
   判為 `gap_precheck`，因為綁定集仍是 draft、R43 不在 pilotRules）。
3. 得到 `AIRUN-43-0A43111E` → `RRUN-02721A7D01`。

## 結果

| 項目 | 值 |
|---|---|
| `documentScopeSnapshot` | **有**（生產庫 330 筆運行裡第一筆） |
| `workstationSnapshot` / `effectiveRuleSnapshot` | 有 / 有 |
| 範圍內文件 | `DV-3EEB7A48-V1`、`DV-A8E48BB4-V1`——都是《地上甲类储罐区2（含泵区）施工图.pdf》（设计文件） |
| 終態 | `waiting_human_review` |
| `rule_check_results` | `engineering-inspection-r43 → evidence_insufficient` |

導出（`export_review_acceptance_fixture.py`）：先完整重放，重放結果等於記錄結果。

```
ruleId R43 | scenario insufficient | matchesExpected true | businessAcceptance not_reviewed
fixture.json 16.5 MB (sha 265a596a…) | output.json (sha ff7f7656…) | provenance.json
```

位置：`/home/dev-bjy/aicheck-data/files/output/ops/acceptance-RRUN-02721A7D01-20260911124528/`

## 這個「證據不足」是雙重正確的

- 節點 43 的證據連結指向**施工圖**，不是材料質量證明文件——R43 在這份文件上本來就
  不可能成立；判「證據不足」而不是「不符合」，正是四種結果邊界裡「判不了就不放過、
  也不冤枉」那一條。
- 運行沒有 `selectedObjectIds`（工位尚未接對象選取 UI），事實構建對多列表判來源含糊——
  同樣落在「證據不足」。

所以它是**真實的 `insufficient` 情境證據**，不是硬湊出來的。`reviewer` 一欄仍空：
那是人工簽字。

## 這條鏈現在的狀態

OCR → 表結構分類 → 欄位對映 → 對象選取 → 執行器接線 → 凍結判據 → agent 讀正文（反編造
閘門）→ 工位凍結範圍 → 導出重放一致的驗收 fixture。**每一段都在生產真實資料上跑過。**

## 還差什麼（都不在程式裡）

- `passed` / `failed` 情境：要**質量證明書原件與監檢記錄**掛到節點 43，再重跑
- 對象選取：工位 UI 要能把 `selectedObjectIds` 寫進運行（後端已認）
- 人工簽字：fixture 的 `reviewer`
- embeddings：仍需一把按量計費 `sk-` key
