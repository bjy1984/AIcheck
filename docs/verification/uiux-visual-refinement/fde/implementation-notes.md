# FDE 本輪修復與驗證

本輪實作：共用狀態標籤／圖標、OCR 中性卡片與選中邊框、任務狀態堆疊圖、OCR 問題排序橫條與場景實測表、向量實測維度橫條、未知耗時與評分保留缺值。

初輪瀏覽器 QA 已檢查 16 條主路由及向量品質圖；圖條實際點擊可進入 AI 任務列表。發現並修正：圖表推低阻斷中心、聚合狀態英文漏譯、OCR 圖原位置被舊樣式隱藏、當前導航徽章用領域色、後端把「完成」誤歸未開始。

`backend/libs/fde_console_views.py` 新增未知分類並修正明確狀態映射。既有呼叫只依完成／失敗集合判斷，並以開放字典返回分類，新增未知項保持相容。`test_fde_status_semantics.py` 與原 `test_fde_console.py` 合計 65 通過。前端定向 `fdeVisualData.test.ts`、`fdeFollowup.test.ts`、`fdeReportedData.test.ts` 通過。

此目錄 intermediate-* 圖只屬修前／中間 QA，不代表最終建置；最終覆蓋以 manifest.json 為準。

OCR 正值排序與切換口徑另由 `fdeChartRendering.test.ts` 驗證：從正式 Vue 元件擷取實際 computed option，以明確合成 props 提供品質標記 2／7 件、缺失必填欄位 1／4 件，再用 ECharts SVG renderer 檢查降序與數字標籤。耗時測試同樣使用正式 FdeConsole option，確認真實 0ms 保留為 0、缺值為 null／未取得耗時，無補造 80ms。結果記於 `../chart-rendering-tests.txt`。這是元件渲染測試，並非實際業務資料或瀏覽器中的正值 OCR 圖截圖。

瀏覽器驗證環境使用 production 建置、真實 API 與隔離記憶體資料，未接正式資料庫、模型或外部 OCR。此資料的 OCR 品質標記／缺失欄位統計皆為空、審查任務亦為空，因此最終截圖會明確保留空態，缺值分支由上述元件測試與 `fdeVisualData.test.ts` 覆蓋。
