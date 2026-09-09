# 本機長文件渲染覆蓋與完成狀態

## 發現與修復

正式libs/official_ocr_pipeline.py已有以maxPagesPerBatch分窗處理selected_source_pages的流程，另有200頁上限和成本阻擋；本次沒有重寫或付費實跑。

本機pages.py已輸出truncated、totalPages、renderedPages，但先前沒有將渲染截斷傳至業務readiness。本批新增libs/ocr/page_coverage.py，在OcrService.record_parse_result返回前處理（包括停用服務健康更新、快取返回情境），以OCR_PAGE_COVERAGE_INCOMPLETE列阻擋及未渲染頁碼，保留內容和執行status，outcomeStatus為partial。ocr_readiness正式阻擋名單同步增加该碼。既有failed不改為partial；重複處理不累加診斷。

localRenderCoverage只表示本機視覺渲染範圍。原生文字抽取可能覆蓋更多頁，但不能抹除尚未視覺處理的頁。沒有明示truncated的原生／正式頁結果不更改。此處不是最終OCR全頁覆蓋證明，也不聲稱已完成剩餘頁面辨識。

## 實測

[實際文件報告](2026-09-09-render-coverage.json)：兩份既有PDF使用NDT預設12頁上限，為驗證節省資源明確設定72dpi／最長邊800，經render_document_pages→public_document_pages→record_parse_result→readiness。

- 盈德22頁方案：已渲染1–12，未渲染13–22，partial。
- 射線28頁方案：已渲染1–12，未渲染13–28，partial。

沒有呼叫OCR模型，報告以verificationScope和visualOcrExecuted明確區分渲染驗證。

新增4項test_ocr_render_coverage測試，包含實體4頁PDF完整／截斷範圍、重複處理、原生文字不能遮蔽視覺缺頁、既有失敗保持及正式頁結果保持。共[770項相關回歸通過](2026-09-09-render-coverage-tests.txt)，Ruff289/289、monolith及diff通過。

尚待本機長文件分段補全、全頁實際辨識、工艺身份／引用與剩餘事實適配；69條發布門檻保持。不能把本次防止誤報完成的修復當作完整資料鏈路交付。
