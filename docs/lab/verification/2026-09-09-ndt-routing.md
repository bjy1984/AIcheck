# NDT PDF深度辨識路徑

## 修復

專用profile先前已存在，但service.py的BUSINESS_PDF_DEEP_SCAN_PROFILE_IDS、DOCUMENT_TYPES漏列ndt_procedure。因此含文字正文的混合PDF可能直接走文字層返回，掃描封面沒有進入視覺處理。現在加入該類型及profile，沿用既有業務PDF深度處理，預設maxPages=12。顯式文字層或深度選項不覆寫。

PyMuPDF原生引擎另提供nativeTextCoverage，包括pageCount、pagesWithText、pagesWithoutText；部分頁面无文字時附PDF_TEXT_LAYER_PARTIAL及pageNos。文字層本身無法區分空白、掃描內容或漏讀；診斷請求核對，不推定業務不符合。metadata保留到normalize結果中。這項資訊只描述原生引擎，不代表合併其他引擎後的最終覆蓋；不能以它直接否定已由其他OCR讀到的內容。

## 驗證

- 新增test_ndt_pdf_routing.py的8項測試：以profile／material type進入真正parse_document，捕獲本機引擎路徑，確認不走文字層捷徑；4種顯式選項保留；實體PDF有／無空白頁的覆蓋與診斷保持。視覺引擎以捕獲替身隔離，這不是實際掃描識別品質驗收。
- [相關回歸日誌](2026-09-09-ndt-routing-tests.txt)：879 passed，含OCR、R39、工具、綁定、工位與發布門檻。
- [接口日誌](2026-09-09-ndt-routing-contract.txt)：8 passed、312 deselected。
- [兩份實際PDF重跑](2026-09-09-ndt-native-coverage.json)：均列第1頁PDF_TEXT_LAYER_PARTIAL；之前的源檔、SHA256、頁數及缺欄結論保持。
- Ruff289/289、monolith與diff通過。未發布、未執行付費模型、未變更歷史任務。

## 尚未完成

12頁是單次深度嘗試上限，不能視為22／28頁實例全頁完成；長文件分段、最終覆蓋、機構身份及其他R39事實適配仍需後續驗證。三類pendingCapabilities與69條全量發布門檻不變。
