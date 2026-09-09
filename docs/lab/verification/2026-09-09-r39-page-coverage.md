# R39原文引用路徑的缺頁狀態

R39 reference_from_fields先前只查看現有OCR欄位與原文定位。即使OCR已明示部分頁尚未辨識，欄位齊全時仍可能返回引用子工具passed。本批將本機／正式OCR的缺頁coverage帶入selectionIssues，使整組不因局部欄位齊全而通過；已有明確不一致保留failed，不丟棄已取得證據。

review_page_scope原本丟棄全部metadata／quality以避免範圍外內容滲入。現在另產生僅含原因碼、範圍內頁碼、定位是否已知的reviewCoverageGap；不保留原metadata或摘要。範圍外已知缺頁不影響本次核對；位置未知／混雜非法頁碼仍阻擋。再次縮窄範圍時重新投影。

新增11項測試：整份與兩種範圍、符合／已知不符合、空／非法缺頁位置、範圍外資訊清除及縮窄範圍。從凍結reader到R39事實與實際判定子工具驗證，使用合成OCR欄位，未宣稱真實案件已完成。

[734項相關回歸通過](2026-09-09-r39-page-coverage-tests.txt)。Ruff289/289、monolith與diff通過。保留既有API／判定碼；reviewCoverageGap是內部相容欄位，沒有修改歷史任務。

本批限原文欄位引用路徑；結構化清單完整性、其餘業務事實和69條實際驗收仍待補，三類pendingCapabilities保持。
