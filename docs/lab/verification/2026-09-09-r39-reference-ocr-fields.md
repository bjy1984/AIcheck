# R39 原文欄位引用比對驗證

## 入口及範圍

在沒有顯式referenceContexts／Bases／instructionReferences／procedureIdentities／referenceInventories／Members來源資料時，嘗試讀取本次固定版本中的兩份ndt_procedure_v1解析。須明確各一份工藝規程、操作指導書；多份、重複解析、缺類型或其他類型不取首筆。

使用本文件編號與版次、原文明示機構名稱、方法、指導書引用編號／版次。資料庫驗證文件與版本屬同工程及租戶；selected_parse_results沿用快照、頁碼範圍與來源更新檢查。欄位須唯一，值／頁碼／confidence格式正確，可信度至少0.75，無field_value_conflict；找到同頁同bbox且含該值的唯一原文碎片後建立有ID的引用。

機構名稱和方法完全一致、引用規程編號與所選規程本身編號完全一致才建立配對，之後比較引用版次；不以版次作匹配條件以免隱藏不一致。名稱只作文件內身份線索，不推定機構證照／實體身份核實。新模式scope用organizationName，identityMode=exact_source_organization_name，organizationIdentityVerified=false；不生成organizationId。原显式ID模式與清單模式維持原路徑。

新增來源record納入既有judgment與source gate；任一條件不足不輸出可判定輸入。沒有生成complete清單、整體規則通過或人工核驗標记。兩份選定文件並不代表工程全部文件已覆蓋。

## 驗證

新增12項從合成OCR碎片經真實enrich_parse_result至R39編譯工具的案例：一致、版次不一致、欄位缺失／重複、低可信、來源衝突、不同機構、多餘文件、跨工程、顯式表衝突不可旁路、原文缺失及無關规程不得猜配。正常時子工具passed但節點仍不足；版次不一致可保留failed。

backend執行 `.venv/bin/python -m pytest -q tests/test_ndt_procedure_ocr_profile.py tests/test_ocr_accuracy_pipeline.py tests/test_ocr_fast_first.py tests/test_ocr_page_scope.py tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`：851 passed。Ruff289/289、monolith與diff通過。

## 未完成

真實PDF／掃描OCR及模型抽取效果、機構身份核實、其餘內容／簽批／應用事實、多文件自動配對與整條規則驗收仍待完成。當前證据是合成碎片经过實際後處理及工具鏈，不能冒充真實工程文件驗收。沒有發布或付費調用。
