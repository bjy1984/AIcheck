# 正式OCR長文件分批與續跑驗收

本批驗證既有official_ocr_extract，不新增另一套分批實作。

新增test_official_ocr_long_document.py：

- 實體35頁PDF，分別每批3頁及30頁，實際render_pages產生所有頁影像，客戶端逐頁執行，最後片段頁碼為1–35、進度35/35。
- 每個案例保留前34頁call checkpoint後續跑，客戶端只執行第35頁；合併片段仍覆蓋35頁。
- 實體7頁PDF在第二批第4頁注入失敗；第一批checkpoint保留，續跑只呼叫未保存頁，最後覆蓋1–7。

客戶端為離線替身，輸出可追蹤的PAGE-n識別標记，用於檢查分批、續跑與頁碼。沒有網路／付費識別，不是OCR準確率、真實工程審查或Temporal服務重啟測試。

[專項日誌](2026-09-09-official-long-document-tests.txt)：上述3項加既有正式OCR runtime／成本控制共24 passed。Ruff289/289、diff通過。

[完整後端日誌](2026-09-09-full-backend-readiness.txt)：4487 passed、72 skipped，134.65秒；啟動時尚未新增上述3項，所以兩組數字保持分列，跳過不計通過。

下一問題已在apps/worker/tasks.py確認：最終pageProgress使用len(result.pages)填completed並固定status=completed，尚未根據partial／成本停止處理。這項進度語義修復未包含在本批完成範圍。

長文件辨識品質、本機全頁補全、R39真實資料及69條全面驗收仍未完成，發布門檻不變。
