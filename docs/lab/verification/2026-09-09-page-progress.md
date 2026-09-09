# 正式OCR頁進度與分塊恢復

## 修復內容

此前worker收尾以result.pages長度（渲染頁數）填completed，status固定completed；成本停止時也可能顯示全數完成。本批新增libs/ocr/page_progress.py，正式提取產生recognitionPageCoverage，worker由final_page_progress收尾。

完整頁呼叫未截斷，或該頁全部預期恢復區塊已返回且未截斷，才計入completedPageNos。缺頁另列unprocessedPageNos及OCR_PAGE_COVERAGE_INCOMPLETE品質阻擋，readiness將實際頁碼帶入原工作台缺頁提示。印章ROI、重複區塊和仍截斷區塊不冒充完整頁。頁面完成但字段品質仍partial時，頁進度狀態仍partial；既有已完成的原生文字結果支持原頁數，未知完成數的partial舊結果不猜測。

同時修復scan_advanced_page以「已有任意tile」跳過整頁的漏洞。恢復時計算預期區塊數，跳過已成功的區塊，只重讀缺少／截斷區塊。新成功結果替換同位置的失敗恢復候選；服務既有逐次模型調用留痕沿用，沒有重寫歷史任務。

## 驗證

- 新增12項頁計數／品質狀態測試，包括正常、缺頁、印章ROI、截斷、部分恢復、重複tile、完整恢復、failed保持和舊結果相容。
- 正式提取離線測試：3頁PDF成本停止後coverage缺2、3頁，worker helper為1/3 partial。
- 單頁輸出截斷，成本僅允許第一塊恢復：0/1 partial；保留checkpoint並恢復額度後，只呼叫tile-2，1/1 completed。
- [52項回歸通過](2026-09-09-page-progress-tests.txt)，含長文件分批／續跑、正式runtime及成本控制、readiness。Ruff289/289、monolith與diff通過。

實體PDF與離線客戶端用於流程測試，未發起付費模型，也非真實識別品質或本輪Temporal服務重啟驗收。69條全面驗收、真實業務資料鏈路與本機長文件補全仍待完成。
