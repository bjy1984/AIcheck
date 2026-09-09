# R39 跨清單一致性契約與驗收

## 核對內容

工具evaluate_r39_inventory_consistency接收referenceInventory、documentInventory、approvalInventory、applicationInventory及applicationDocumentLinks。四份清單均需同工程、complete=true、非空唯一且完整身份members與引用。比較範圍是本次聲明的同一組文件與應用，不能把無關工程清單混合。

引用成員展開指導書與規程的文件ID／固定版本／種類／方法；與內容清單及簽核清單投影集合對照，缺失和多餘均明列。應用成員仍按工程、機構、指導書業務ID／版本、方法、對象、事件識別。映射記錄增加instructionDocumentId和instructionDocumentVersionId及來源；每個應用需唯一對應且目標必須在指導書內容清單中。同一業務指導書版本不得跨事件映射到不同文件。

錯版、漏對照、重複、額外事件或未有應用對應的指導書返回evidence_insufficient，issues列具體身份及原因。只在對照一致時返回passed；wholeRuleAcceptance和realWorldCompleteness均為not_evaluated，evidenceVerified=false。這是資料鏈路核對，不生成技術不符合判斷。

## 正式資料路徑

新增ndt_application_document_links。來源reader按任務固定版本取表並產生引用，經inventoryConsistency來源門檻後，僅從已通過既有來源門檻的四類事實取得清單；缺任一清單不組裝輸入。接入executor、註冊與AC-R39-01綁定；工具數100，pendingCapabilities、lifecycle及試點保持。

## 驗證及邊界

backend命令：`.venv/bin/python -m pytest -q tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`，685 passed。新增37項清單失效、版本錯配、映射缺失／重複、跨事件業務版本衝突、來源低可信及實際編譯工具案例。Ruff289/289、monolith與diff通過。

測試明確證明：合成清單能彼此一致，但內容／簽名／應用驗證未完成時整個R39仍為證據不足。未宣稱真實清單完整。零應用、尚未使用文件的有據排除尚未支持，目前保留不足而不是推定不符合；其他方法技術要求、真實抽取與69條全面驗收仍未完成。沒有生產發布、付費任務或歷史改寫。
