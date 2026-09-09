# R39 多文件OCR引用比對

## 配對與結果

沿用來源限定欄位讀取，依機構原文名稱、方法及引用規程編號精確找唯一對應規程；版次只用於比較，不用於候選挑選。同編號多版本、重複解析及不完整同編號候選不取首筆。各文件輸入受工程／租戶／固定版本、來源頁碼／位置／文字及可信度門檻保護。

若存在明確reference業務表仍走原路徑，不借OCR欄位旁路其衝突。恰好單對且無問題保留原返回；多對使用fieldPairs、selectedDocumentVersionIds、selectionIssues。工具逐對驗證來源模式、工程、所選版本、重複指導書與巢狀輸入後聚合，保留獨立已知失敗及其他未完成項。

scope為selected_ocr_document_pairs_only，coverage含selectedDocumentCount、comparedPairCount、unresolvedDocumentVersionIds、complete。集合只覆蓋具有ndt_procedure_v1解析或文件材料類型明確為ndt_procedure的本次選定版本；不能據此宣稱工程全部工藝文件已識別。未解析版本、未找到關係或候選不唯一均保留issues；不是工程不符合的直接依據。

## 驗證

新增18項：兩組文件四態相關組合、低可信／缺欄／重複解析／同編號多版本／未解析、重排不變、獨立失敗保留、重複pair與越界／巢狀／格式錯誤，以及缺版次同編號候選仍阻止唯一配對。

backend命令 `.venv/bin/python -m pytest -q tests/test_ndt_procedure_ocr_profile.py tests/test_ocr_accuracy_pipeline.py tests/test_ocr_fast_first.py tests/test_ocr_page_scope.py tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`：869 passed；Ruff289/289、monolith與diff通過。

測試仍使用合成OCR來源經實際後處理／凍結事實／編譯工具。真實PDF／掃描、機構身份核實、其他R39事實、全面技術要求及69條驗收仍未完成。沒有生產發布、付費模型或歷史改寫。
