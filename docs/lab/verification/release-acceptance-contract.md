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
