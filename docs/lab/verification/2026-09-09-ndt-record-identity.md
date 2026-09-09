# 無損檢測原文身份欄位

檢查現有 RT／UT 報告 profile：已有 report_no、weld_no、detection_date 等，缺少可直接區分本記錄、引用記錄、事件的明示欄位。test／test2 文件清單未找到可直接驗收 R40 的成套記錄與報告，不能把施工方案或材料檢測報告當作替代。

本輪在兩個既有 profile 的正式 postprocessing 接入 record_no、referenced_record_no、detection_event_no、ndt_document_kind 明示標籤抽取。沿用既有逐行匹配、原文位置與衝突處理；不從日期／焊口／報告編號推測事件，不跨頁拼接空標籤，不覆蓋已有矛盾字段。不生成標準化業務表、工程身份、完整清單或人工背書。

22 項測試通過：兩個報告 profile 實際後處理、原文位置與置信度、編號分離、無標籤不推測、衝突保留，既有工藝規程 OCR 与 R40 對應檢查回歸。Ruff 289／289、monolith 通過。完整輸出：ndt-record-identity.txt。

尚未完成：新欄位到 R40 的對象／事件映射與判定接線、成套真實 PDF 驗收、檢測參數／設計要求／結論核對。此階段僅改善原文抽取可用性；發布門檻未變，整體未證明達 90%。
