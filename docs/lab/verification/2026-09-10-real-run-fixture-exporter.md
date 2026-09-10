# 真實審查運行 → 驗收 fixture 導出器（2026-09-10）

## 做了什麼

新增 `backend/scripts/export_review_acceptance_fixture.py`。它把一次**真實**的
ReviewRun 凍結成可重放的驗收 fixture：

- `expectedResult` **抄自該次運行自己在 `rule_check_results` 留下的結果**，腳本不
  自行下任何判定。
- 寫出前先用 `replay_review_acceptance.export_replay` 完整重放一次；重放結果與
  記錄結果不一致時，`provenance.json` 明確記下 `replayReproducedRecordedResult:
  false`、退出碼非 0。這種目錄不得當作驗收證據。
- `businessAcceptance` 固定 `not_reviewed`，不寫 `reviewer`。運行與重放一致只是
  確定性檢查，不是人工簽字。
- 拒絕沒有 `documentScopeSnapshot` 的運行——事後重新凍結範圍描述的是「今天的
  文件」，不是那次運行真正讀到的文件。
- 拒絕 `execution_error` / `human_review_required`：那不是驗收情境。

同時修好 `replay_review_acceptance.py` 的 `OFFLINE_TOOLS`：26 個 frozen-domain
工具接入時沒同步這份名單，導致 R43 以後全部卡在
`replay_nonlocal_or_unsupported_tools`，只有 R35~R37 能重放。

## 但是：這批真實運行現在導不出來

我原本說「那兩個工程的 49 次真實運行就能導出成驗收情境」。**這句話是錯的。**
直接查生產庫得到的事實：

| 查的東西 | 結果 |
|---|---|
| `review_runs` 帶 `documentScopeSnapshot` 的 | **0 筆**（逐 nodeId 分組全為 False） |
| `rule_check_results` 的結果分布 | `evidence_insufficient` 38、`failed` 1、`warning` 9 |
| `ocr_parse_results` | 308 筆，其中 173 張表有 businessSchema |
| 這些表的 schema | weld_detection_result 13、material_chemical_composition 6、engineering_drawing_title_block 5、welding_procedure_qualification 3、mechanical_property 1、engineering_drawing_list_rows 2、welder_qualified_item 1 |
| **沒有 businessSchema 的表** | **135 張，1004 列** |

兩個獨立的攔路點：

1. **工位模式在生產從沒開過**，`AICHECK_WORKSTATIONS_ENABLED` 不為真時
   `initialize_run_workstation` 不執行，所以沒有任何一次運行凍結過文件範圍。
   開關本身也不會給既有運行補種快照。
2. **素材沒有被歸類到這些規則要讀的表**。R43~R58、R63~R68 的 fact builder 靠
   `businessSchema` 認表；生產裡出現的 8 種 schema 一種都不是它們要的。1004 列
   真實表格資料躺在 `businessSchema: null` 裡。

所以現在就算把工位開關打開重跑，結果也只會是 `evidence_insufficient`——這正是現
有 38 筆的樣子。第 8 項卡的不是登入、不是導出器，是**表格分類覆蓋**。

另外 9 筆 `warning` 已查清：它們的 id 全是 `RCHK-RR-AUDIT-*`、ruleCode 是
`SEAL_REQUIRED_AND_READABLE` / `PIPE_LIST_FIELD_CONFIDENCE`、ruleSetVersion 是
`engineering_rules@1.0.0`，是舊的種子/審計資料，不是現行執行路徑產生的。現行
`execution.py` 只會寫 `passed/failed/not_applicable/evidence_insufficient/
execution_error/human_review_required`。導出器拒絕它們是對的，不需要改引擎。

## 下一步（按依賴順序）

1. 把 135 張未分類表的實際表頭撈出來，看缺的是哪幾類 `businessSchema`，補分類器。
2. 生產開 `AICHECK_WORKSTATIONS_ENABLED` 並重跑，才會有帶凍結範圍的運行。
3. 有了 1~2，導出器才能產出 `compliant` / `noncompliant` / `not_applicable` 三種
   情境的真實證據；`insufficient` 現在就已經有真實素材。

## 更嚴重的發現：73 個表結構名，OCR 一個都不會產生

沿著「表格分類覆蓋」往下查，結果比預想的糟。

27 個 fact builder 靠 `businessSchema` 認表，一共要讀 **73 種**表結構名
（`ndt_plan_items`、`ndt_plan_context`、`coating_holiday_test_domains`、
`ndt_nonconformance_notices`……）。全庫搜索這些名字，只出現在兩個地方：

- `libs/review_orchestrator/*_facts.py`——讀它們的地方
- `tests/test_r*_facts.py`——單元測試自己造的假表

**OCR 管線一個都不會寫出來。** `apps/ocr_service` 的分類器只認得
`piping_characteristic_table`、`weld_detection_result_table`、
`material_chemical_composition_table`、`mechanical_property_table`、
`construction_record_table`、`welding_record_table` 等六到八種，和那 73 種**沒有
任何交集**。

這解釋了生產庫裡 38 筆全是 `evidence_insufficient`：不是素材不夠，是**素材永遠
到不了規則手上**。1004 列真實表格資料躺在 `businessSchema: null` 裡，而規則只按
名字取表。

從那 135 張未分類表的欄位看，素材本身是對得上的：

| 出現次數 | 欄位 | 對應規則 |
|---|---|---|
| 13 | 介质 \| 公称直径 \| 检测比例 \| 管道号 | R36 `ndt_plan_items` |
| 3 | 产品质量证明书编号 \| 元件名称 \| 制造许可证编号 \| 材质/标准 \| 规格/炉批号 | R43 材料證明 |
| 2 | 压力管道级别 \| 操作压力 \| 管路等级 \| 设计压力 | R63 應力分析 |
| 2 | 核查项目 \| 具体要求 \| 见证资料 \| 完成状态 | 通用核查表 |
| 10+ | 许可项目 \| 许可子项目 \| 许可参数 | 資質類 |

也就是說：**規則寫好了、判據凍結了、工具測試綠了，但這條鏈在 OCR 到規則之間是斷
的。** 之前所有「規則完成度」的百分比都只反映了斷點之後那一半。

## 這對剩餘工作意味著什麼

第 8 項（276 情境驗收）不是「還沒做」，是**在補上表結構分類之前做不了**。用單元
測試那種手造 state 可以跑出四種情境，但那是合成輸入，不是真實素材，對「這套系統
能不能審真圖紙」一個字都證明不了。

優先級應該調成：先把 73 個表結構名接進 OCR 分類（或反過來，讓 fact builder 認
現有的 schema 名），再談驗收。
