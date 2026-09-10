# 原文件詳情：逐頁資料辨識

沿用 `FileDetailDialog.vue` 的結構化內容區、原文預覽與定位池。Lab 開關啟用時顯示「這份文件裡有哪些資料」，每頁以一般名稱表示類型，未知／矛盾保持待確認；全量頁數及待確認數始終可見，先顯示 6 頁並可展開全部。看原文按鈕沿用既有 `#page` 定位機制，沒有另建產品預覽器。

後端 `build_ocr_structured_view` 從目前版本原 fragments 重算頁面分類，只下發 pageNo／status／documentKind，保留 documentVersionId；不下發全部原文片段。前端版本不匹配時不使用分類，重複頁／未知種類也不當已辨識。main 未開 Lab 功能保持原介面。

這是只讀辨識展示，不是人工分類保存；沒有新增虛假的確認狀態、變更文件類型、選頁範圍或規則結論。當前版本無分類時沿用原空資料行為。

驗證：後端 38 項相關測試通過；前端 99 個測試檔通過；vue-tsc、增量 ESLint、新元件 Stylelint 通過。Ruff 289／289、monolith、diff check 通過。

Chrome 1280×900 使用原新增元件、合成 9 頁資料：初始 6 頁／待確認 8 頁提示、展開全部、鍵盤 Enter 定位第 9 頁、aria-pressed、至少 44px 點擊區域、無頁面錯誤。深淺色截圖實際檢視，深色等待 Element Plus 色彩過渡結束後拍攝。證據為 `browser/document-pages-light.png`、`browser/document-pages-dark.png` 及本目錄三份 page-view 日誌。

`frontend/e2e/lab-rules/document-pages.html` 僅是元件驗收入口，不是新產品工作台。此次未以已登入真實工程完成 FileDetailDialog 的 API→頁面→原文全流程，不能用元件事件代替完整預覽定位驗收。人工分類確認、續頁歸屬、分段執行、事件映射仍待完成，整體未證明達 90%。
