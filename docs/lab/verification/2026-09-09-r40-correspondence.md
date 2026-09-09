# R40 記錄與報告對應檢查

## 已實作

原 R40 的 evaluate_ndt_process / ndt_record_report 由通用規則解釋改接專用對應檢查，其餘 profile 保留既有路徑。選定版本的 ndt_event_inventory、ndt_event_members、ndt_event_records、ndt_event_reports 標準化表經原文、頁碼、置信度及衝突門檻，組裝 r40.recordReportCorrespondence，再由現有 executor 傳入工具。

以 projectId + objectId + method + eventId 精確對應每個有來源的聲明事件；記錄和報告各須唯一，核對 report.recordId 是否引用該記錄。缺件、重複、跨事件或無法確定適用性返回證據不足；明確引用不一致返回不符合。只有明示不適用且沒有矛盾记录的事件才返回不適用。未聲明事件中的資料不被忽略，多事件全部核對，保留已查明的不符合。

## 驗收

37 項通過：R40 來源到實際工具參數、四態、錯誤工程、低置信度、重複、事件不符、多事件缺口／已知錯誤；完整 R40 工具計畫會執行專用檢查，但整體仍為 evidence_insufficient。R39 節點及資產生成回歸通過。

Ruff 289／289、monolith 通過。輸出見 r40-correspondence.txt。

## 未完成與發布

這是標準化表的合成驗收，不是實際 PDF 自動抽取驗收。仍需原文 OCR 適配、檢測參數、設計要求和報告結果核對。工具回傳 wholeRuleAcceptance=not_evaluated；正式 binding 及生成 override 都列出 technical_parameters、design_requirements、report_results 三項 pendingCapabilities。binding_only、原 36 試點及 draft 發布狀態保留，不宣稱整條 R40 通過或已發布。
