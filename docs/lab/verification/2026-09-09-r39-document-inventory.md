# R39 多文件內容清單驗收

## 資料契約

`evaluate_r39_document_content` 增加 `inventory` 及 `documents`；不提供時沿用單文件scope/basis/contentInventory。提供任一清單欄位即走清單模式，不回退單文件。

inventory包含projectId、complete=true、evidenceRefs與members。member包含projectId、organizationId、documentId、documentVersionId、documentKind（procedure/instruction）、method及引用。documents每一項是既有單文件工具輸入；完整身份必須與清單唯一匹配。清單不能根據當前documents反向生成，以免把漏查誤當齊全。

結果保留documentResults和每項documentScope；coverage列requiredCount、comparedCount、missingDocuments與complete。只有清單有效、無多餘／重複項且所有項目已得到四態中可定論結果時complete才為true。complete表示覆蓋完成，不代表符合，已確認缺項仍為failed；任何已確認缺項優先保留，其他漏查仍可見。

## 來源與執行

- 新增解析表 `ndt_content_document_inventory`、`ndt_content_document_members`。成員被審版本用reviewedDocumentVersionId，來源版本由reader產生。
- 原contentContexts／Bases／Inventories／Fields按完整身份分組，逐份套用現有同工程／租戶／選定版本校驗，不取首筆。
- 共用清單與成員通過來源門檻後才允許逐份隔離；不可靠文件不送入內容判定，保留diagnostics和未完成標記。
- 來源驗證的共用整理亦覆蓋原referencePairs，因此同批重跑原引用清單與來源隔離全部案例。
- 既有AC-R39-01工具名稱及綁定不變，只擴充相容輸入Schema；沒有改寫歷史任務或開放發布。

## 驗證與限制

backend命令：`.venv/bin/python -m pytest -q tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`，587 passed。新增30項覆蓋四態、混合文件類型、順序、漏查、重複、嵌套清單、跨工程、低可信、原文錯版、已知缺項保留及編譯節點中的真實工具結果。Ruff289/289、monolith及diff通過。

本批是有來源的聲明清單覆蓋，不是人工對真實工程文件清單完整性的背書。內容存在也不代表技術值正確。簽核週期、應用清單、方法技術要求、真實文件抽取仍待驗收，pendingCapabilities未解除。
