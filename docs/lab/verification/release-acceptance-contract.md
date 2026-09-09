# 綁定發布驗收記錄契約（Lab）

本契約是發布前的留存記錄一致性檢查，不是模型品質評估、案例執行器、審核人身份認證或人工業務背書。全部 69 條仍須完成真實業務驗收；不得用人工拼造的通過 JSON 代替執行結果。測試中的 synthetic-test-only 僅存在暫存目錄。

## 入口

backend/scripts/publish_atomic_check_bindings.py 增加必填 --acceptance-manifest 與 --release-version。既有 --expected-sha256、--approver、--approval-ticket 保留；--dry-run 同樣檢查全部前置条件但不寫入。從 backend 目錄以 PYTHONPATH=. 執行腳本。

發布前仍先檢查業務包完整性、實作狀態與工具註冊；binding_only 不可發布。驗收版本必須是與目前版本不同的非空字串。真實發布更新版本並保存 rollbackPilotRules、驗收清單及來源雜湊；保留 pilotRules。替換前再次檢查來源內容與程式雜湊，偵測到變動即拒絕，不覆寫其他更新。這不是跨程序交易鎖，正式操作仍需部署流程停止相關配置寫入。

## 留存格式

清單 JSON：
- schemaVersion: review-business-acceptance-v1。
- bindingSha256: 發布前綁定 YAML 原始位元組 SHA-256。
- sourceSha256: source_digest(backend)；包含 libs/apps/scripts/business_packs 的 py/yaml/yml/json/md/txt，以及 backend 根目錄 requirements*.txt、pyproject.toml、*.lock。相對路徑排序後，逐項納入路徑、NUL、內容雜湊。
- scenarios: 每條實際綁定規則各有且僅有 compliant、noncompliant、insufficient、not_applicable 四種記錄。
- 每條記錄包含 ruleId、scenario、status=passed、非空 reviewer，以及 fixture/output 引用。引用包含 path 與 sha256，目標必須在清單目錄內，解析符號連結後也不可越界。

fixture JSON：
- ruleId、expectedResult。
- frozenInput: 保存本次實際輸入的 JSON 物件，含 inputDocumentVersionIds；缺證據案例允許空文件清單。
- fixtureInputSha256: 對 frozenInput 使用 sort_keys=True、separators=(",", ":")、ensure_ascii=False、allow_nan=False 序列化後，以 UTF-8 計算 SHA-256。這是驗收輸入雜湊，與應用程式既有 inputHash 分開。

output JSON：
- ruleId、result、fixtureInputSha256、bindingSha256、sourceSha256。
- atomicResults: 每個已綁定 atomicCheckId 必須有且僅有一項，包含 result。
- evidenceRefs: documentVersionId 必須在凍結文件清單內，pageNo 為正整數，並有非空 quotedText 或有效四座標 bbox。缺證據情境允許空引用；提供了引用仍須檢查。
- 四種預期結果依序為 passed、failed、evidence_insufficient、not_applicable。

驗證器重新計算輸入雜湊；從當前綁定推導 evidence_gate 身份，不信任結果自報角色，使用正式 aggregate_atomic_results 重新彙總並與結果比較。不接受空綁定、重複綁定、遺漏／重複案例、原子缺項、來源過期、檔案雜湊錯誤或越界引用。清單雜湊對實際讀取的同一份位元組計算。

## 已驗證與待辦

2026-09-09：本批發布檢查、發布寫入／dry-run、來源變動、工具執行器、發布盤點、業務包及巨石基線測試 63 passed／1 dependency deprecation warning；Ruff 289／289。較早一次擴展測試使用錯誤檔名，未執行任何測試；已改用 test_review_tool_executor.py 並完成上述批次。未執行本批完整後端回歸。

仍待：真實案例收集與執行結果匯出／重放、逐原子證據語義支持性、必要事實覆蓋、模型與環境完整重現、可信審核留痕、原 36 條結果差異及服務／完整瀏覽器驗收。四種結果與雜湊一致不證明原文支持結論。此批不得作為全量發布完成或品質提升量測的證據；未修改生產綁定狀態。

## 離線來源重放入口（2026-09-09）

新增 backend/scripts/replay_review_acceptance.py。從 backend 目錄執行：

```sh
PYTHONPATH=. .venv/bin/python scripts/replay_review_acceptance.py --fixture /absolute/path/case.json --output-dir /absolute/path/new-run
```

output-dir 必須是新目錄，建議放在 backend 來源雜湊範圍以外；重跑使用另一個新目錄。輸出 fixture.json 原始輸入、output.json 完整原子／工具結果與來源引用、report.json 檔案雜湊及預期比對。matchesExpected=false 時仍保存觀測結果，CLI 退出碼為 1；一致為 0。報告始終 businessAcceptance=not_reviewed，不自動填 reviewer 或產生發布批准清單。

fixture 沿用上述契約；frozenInput 另需 state（凍結的文件、版本、OCR／修正資料）及 reviewRun（含 documentScopeSnapshot）。外層 inputDocumentVersionIds 必須與 reviewRun 一致；不接受執行時重建快照來掩蓋來源變動。fixtureInputSha256 包含整份來源 state 與 reviewRun。

目前從正式 NDT_FACT_BUILDERS 接入 R35–R37，重新從固定來源組裝事實並執行實際原子綁定與 runtime 工具，不接受用預計結果替換觀測結果。整個計畫執行前檢查明確的本地工具允許清單；其他節點、未註冊工具或外部查詢工具明確報錯，沒有模型或平台網路調用。此模式可以在 Lab 執行尚未發布的綁定，但不改綁定狀態，也不證明正式發布權限。

semantic_result 僅移除 runtime 的 toolCallId，供同版本重跑比較；原始输出保留 ID、全部判定及證據欄位。不忽略其他差異。來源雜湊不同的版本對照與三組品質評估仍待接入。

目前案例為合成結構化 OCR 測試，驗證路由及契約；不代表真實掃描品質、69 節點覆蓋、模型輸出重放或業務人員驗收。其餘節點的事實組裝器與外部平台留存回放仍需逐條接入。
