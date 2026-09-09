# R39規程引用：文件對清單覆蓋

## 改動與來源契約

沿用evaluate_r39_procedure_reference、facts.r39.procedureReference及AC-R39-01現有接線。新增ndt_reference_inventory／ndt_reference_members來源表；原四表ndt_reference_context／basis、ndt_instruction_reference、ndt_procedure_identity仍提供逐組事實。

清單必須明確complete=true、工程一致且有來源；成員列完整projectId、organizationId、instructionDocumentId／VersionId、procedureDocumentId／VersionId、method和來源。來源適用既有可信度與引用核對門檻。按完整身份組合組裝，不任取多筆中的第一筆；文件必須屬本工程／租戶、固定版本已選入任務。

工具輸入inventory＋referencePairs。逐組核對規程編號和版本後聚合，coverage提供清單是否有效、應查數、已查數、漏查文件對與是否完整；pairResults保留各組scope、結果和引用。清單表頭與成員引用均保留。缺清單成員、重複、清單外文件、錯誤身份／來源及未完成比對不能宣稱覆蓋完整。

對有效獨立文件對的已知不一致優先保留；其他組輸入無效時不抹掉已知不一致，結果不依資料排列順序而變。重複文件對不任選第一筆。沒有新清單來源時仍保留原工具明確的selected_instruction_procedure_reference_only能力，沒有宣稱它是工程全量驗收。

## 驗證

R39來源、文件內容、原節點計畫及比對相關156條回歸通過；工具註冊與引用回歸112條通過；最後25條清單專項（含實際編譯節點計畫）通過。案例包含兩文件對、四態、漏查、低可信度、重複、清單外、嵌套、錯誤身份、缺版本及資料順序交換。最後節點測試確認清單實際進入工具，整條R39仍被剩餘能力門檻阻擋。

Ruff289/289、monolith及diff檢查通過；未提升基線或移除發布阻擋。首輪唯一失敗是把隨機toolCallId當成業務結果比較，改為比較result／facts／evidenceRefs，不放寬業務斷言。曾誤用不存在的測試檔名稱，該次未執行測試，之後用實際test_review_business_tools.py完成112條回歸。

## 邊界

這是具來源的声明文件對清單完整性，不是對真實工程清單本身完整的人工背書。測試使用合成解析來源；真實文件表格抽取、方法專項技術要求、簽核／內容／首次應用的全量文件清單仍待驗收。保留technicalCompliance、wholeRuleAcceptance為not_evaluated，evidenceVerified=false及原pendingCapabilities。沒有發布69條或重跑歷史任务。


## 2026-09-09：R39來源組裝隔離異常文件對

- 實際來源組裝原先遇到任一重複／清單外／缺身份記錄即丟棄整份引用比對輸入。現在對有效清單保留其他獨立文件對；有問題的文件對不任選第一筆，仍計為未完成。清單本身無效和原有來源可信度門檻仍阻擋。
- 八組來源案例覆蓋重複、缺失、清單外及缺身份資料，分別搭配另一組符合／不符合。已知不一致保留到編譯節點結果；資料重新排列後判定和覆蓋一致，證據行號指向重排後的對應記錄。
- 相關R39回歸132條通過；最後清單33條（含編譯節點結果）通過；Ruff289/289、monolith與diff通過。這是合成來源链路验收，真實文件／方法技術要求和整條R39發布仍未完成，整體目標持續。

來源重排測試沒有要求舊證據ID或行號不變；那會錯指原文。測試比較判定／覆蓋／檢查內容，並逐引用核對documentVersionId、tableId及rowIndex確實回到重排後的UT記錄。原始輸入不回寫。
