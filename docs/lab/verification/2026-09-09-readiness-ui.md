# 文件詳情的辨識未完成提示

## 已修复

原FileDetailDialog將incomplete標為「已完成」，並在blockingReasons沒有fieldName／requirementName時隱藏提示。現在沿用現有ElAlert、狀態標籤與詳情內容，顯示「部分完成」；缺頁優先提示「還有頁面沒辨識完」，一般未完整狀態也不再靜默。

OCR readiness保留既有品質阻擋，另外將OCR_PAGE_COVERAGE_INCOMPLETE作為首項具體原因，帶pageNos、可讀範圍和review_ocr行動。連續頁碼壓縮為2–28等範圍；大量分散範圍最多在摘要顯示8段並標「等」，完整pageNos仍保留。提示請先查看原文，沒有推定需要重傳。

展示函數移入同目錄ocrReadinessPresentation.ts，原元件直接使用；沒有另外建立UI。本機重試仍有單次頁數限制，因此本批沒有提供尚不具補全能力的按鈕。

## 驗證

- [前端日誌](2026-09-09-readiness-ui-tests.txt)：97個測試檔通過。新增展示測試覆盖未完成標籤、缺頁優先、無具體欄位仍有提示、缺欄位文案、失敗和正常狀態。
- vue-tsc --noEmit --skipLibCheck通過。
- 後端test_ocr_render_coverage.py及test_ocr_readiness.py：14 passed；新增實際readiness生成測試確認首項缺頁原因、完整pageNos、範圍文案與review_ocr。
- Ruff289/289、diff通過。未執行付費OCR，未發布。

本批没有真實登入瀏覽器流程驗收；後續仍須核對完整任務中展示、原文返回及長文件補全。本次只修正既有前端對後端partial狀態的誤呈現，不代表辨識能力或69條驗收完成。
