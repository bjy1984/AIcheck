# 「審哪一個對象」接上工位既有的條件對象映射（2026-09-11）

## 缺口

真實的元件核查記錄一張表列六個元件；frozen-domain 規則一次只審一個對象，構建器遇到
多列不替人挑（判「來源含糊」）。第一筆帶凍結範圍的真實運行 `RRUN-02721A7D01` 就是
因此落在 `evidence_insufficient`（另一個原因是證據連結指向施工圖）。

我先加了顯式的 `run["selectedObjectIds"]`（讀表認、fixture 凍結整個 run 所以重放帶著），
但沒有任何入口會寫它——等於還是沒有。

## 產品裡本來就有這個概念

- 前端 `ReviewWorkstationTools.vue` 顯示「下次审查对象：{objectId}」，`documentPageSelection.ts`
  把 `conditionObjectMapping`（`selection.subject: {objectType, objectId}`）隨發起審查送出
- 後端 `prepare_condition_selection` → `freeze_condition_mapping` 凍成
  `conditionObjectMappingSnapshot`，`effective_condition_mapping()` 驗雜湊、規則修訂、來源指紋

所以**不另造欄位**：`read_ndt_tables` 在沒有顯式 `selectedObjectIds` 時，沿用
`effective_condition_mapping(run, state)` 驗證通過的 `subject.objectId`。任何一項對不上
（`ValueError`）就視為沒有選取——被篡改或過期的映射不能悄悄把多元件的表收窄到某一行。

## 測試（`tests/test_real_table_reaches_the_rules.py`）

- 驗證通過的映射 → R43 收窄到那一列，`scope.objectId` 正確
- 雜湊對不上的快照 → 不收窄，回到 `r43_source_object_conflict`
- 顯式 `selectedObjectIds` 優先於映射
- 映射沒有 subject → 沒有選取

## 意義

從工作台選對象 → 凍結進運行 → 讀表收窄 → 凍結判據逐對象判定，這條鏈**不需要新 UI**
就通了。下一筆在工作台選了對象再發起的真實運行，R43 會對那一張證明書出結論，而不是
整張表判含糊。
