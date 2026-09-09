# R40 人工核驗提示

沿用原 ReviewAutomationLimitations，將 technical_parameters、design_requirements、report_results 分別改為參數／單位／適用條件、設計或規程要求來源、報告結論／缺陷評定／簽章的具體提示。保留「系統能力未完成，補文件不一定解決」及既有結果仍需處理的說明，不改原判定或過濾問題。

主畫面 AC-R40-01 改為「節點 40 · 第 1 項」。只轉換合法的既有節點與項次格式；無法辨認的 ID 不猜顯示名稱。原 API 資料保持原樣。

98 個前端測試檔通過，vue-tsc 通過。Chrome 桌面 1280×800 直接掛載原元件，確認三項提示都在、無內部 ID 文字、警示邊界保留且無頁面錯誤。已檢視 browser/r40-limitations-light.png 與 r40-limitations-dark.png。入口 automation-limitations.html 僅供元件驗收，沒有另建產品工作台。

此為合成結果元件驗收，不是實際登入案件或完整可用性測試；不代表後端 R40 能力、真實資料驗收或全量發布完成。整體未證明達 90%。
