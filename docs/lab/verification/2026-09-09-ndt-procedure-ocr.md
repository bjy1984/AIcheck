# 無損檢測工藝文件OCR入口驗證

## 發現的實際缺口

materials.yaml中ndt_procedure原沒有ocrProfileId或ocrFieldMappings，OCR profile registry無專用profile。R39所需ndt_*結構化表由測試資料直接構造，尚無完整真實來源提取／身份適配鏈。不可將前述合成來源→工具測試稱作真實OCR端到端已完成。

## 本次交付

新增libs/ocr/ndt_procedure.py，配置ndt_procedure_v1及來源限定提取器；profiles registry、別名和materials.yaml對應，OCR service的既有enrich_parse_result／apply_profile_postprocessing調用提取器。僅原文標籤後同一行明確值可提取；未知、無標籤或只有下一頁值不猜。

本文件procedure_no/procedure_revision和referenced_procedure_no/referenced_procedure_revision分離。欄位繼承來源頁碼、bbox、坐標系、engine和confidence。同欄異值不擇首；已有OCR值不覆寫，遇矛盾加field_value_conflict，由原品質門檻辨識。結構化配置保留shadow模式和候選引用契約，不直接發布模型抽取值為業務判斷。

不創建organizationId/projectId等系統身份，不以原文缺少內容推定業務不符合，不憑沒有應用記錄生成尚未使用／complete／人工核驗，不自造ndt_*業務表。不同文件／組織版本匹配需下一階段來源適配。

## 驗證

新增6項測試覆蓋材料配置／profile registry驗證、真正service postprocessing、本文件和引用版次分離、頁碼／坐標／可信度繼承、跨頁不猜、多值衝突及完整enrichment保留文件版本。合成OCR碎片，不是實際掃描件。

backend執行 `.venv/bin/python -m pytest -q tests/test_ndt_procedure_ocr_profile.py tests/test_ocr_accuracy_pipeline.py tests/test_ocr_fast_first.py tests/test_ocr_page_scope.py tests/test_review_workstations.py tests/test_r39*.py`：712 passed。Ruff289/289、monolith與diff通過。沒有付費模型執行、部署生產或修改歷史任務。

尚待身份／版本／標準適用性來源適配、真實文件抽取與R39判定閉環、其餘方法技術要求及69條全面驗收。
