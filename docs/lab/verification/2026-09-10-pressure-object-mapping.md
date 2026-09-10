# 耐壓試驗的對象映射：多管線不再合併成一個工程級數值

## 缺口

`design_special_requirements` 對整段設計說明做 `re.search`，取**第一處匹配**當成整個工程的耐壓試驗資料。

實測：一份說明寫了兩條管線——

```
管道 PL-1：液压试验，试验压力为 1.5 MPa，保压 10 min 无泄漏。
管道 PL-2：气压试验，试验压力为 0.8 MPa，保压 10 min 无泄漏。
```

事實裡報出的是 `method: 液压试验`、`testPressureMPa: 1.5`。PL-1 的資料成了整個工程的結論，而 **PL-2 那條 0.8 倍設計壓力的氣壓試驗（低於 1.1 倍下限，是真的不符合）完全不可見**。

## 修復

新增 `pressure_test_statements(text)`：按句切開逐條抽取，能歸到具體管線就帶上管線號（`objectRef`），不做跨句合併，也不猜歸屬。

域事實據此分兩種情形：

- **單條陳述** → 照原樣給 `method` / `testPressureMPa` / 倍率，並置 `objectMappingResolved: True`。
- **多條互不相同的陳述** → `testPressureMPa`、倍率、以及各上限判定全部置 `None`；`method` 改為列出全部方法（「液压试验、气压试验」）；`pressureTestStatements` 保留每一條（對象、方法、壓力、原文句）；`objectMappingResolved` 置 `None`。

`objectMappingResolved` 為 `None` 時，凍結判據把它當未決 → **證據不足**。這是對的：多條陳述歸屬不清是「我們判不了」，不是設計本身不符合，不該報成 failed。

R09 的 `designSpecialRequirementRules` 與 R11 的 `constructionPlanProcessRules` 同步新增 `pressure_object_mapping` 判據（帶 `verifiedBy: null`）。

## 驗收

`tests/test_pressure_ratio_availability.py` 新增三條：多管線不合併、單條保留取值、凍結判據存在且未簽字。

- 相關子集 243 條通過；完整後端回歸 **4948 通過、0 失敗、4 跳過**（339.62 秒）。
- Ruff 289／289、monolith 通過。

## 限制

歸屬只認「管道／管線／管段 + 編號」這種寫法；表格式、附錄式的試驗清單尚未覆蓋。多次試驗（同一對象先後幾次）按句各算一條，未做事件級去重與時序判定。

溫度應力修正（公式 54）、8.6.1.1.3 a) 降壓例外、8.6.1.5 免除情形仍未接入。整體工程估算仍約 60%。
