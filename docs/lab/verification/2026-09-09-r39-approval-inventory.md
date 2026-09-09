# R39 簽核週期清單驗收

## 接口與身份

既有evaluate_r39_approval_chain增加inventory／approvalCycles，可省略以沿用單週期scope/requirements/signatureInventory。任一清單欄位存在即走清單模式，不回退。inventory須projectId一致、complete=true、非空有來源members；每一成員完整包含projectId、organizationId、documentId、documentVersionId、documentKind、method、approvalCycleId、procedureId、procedureVersion及引用。approvalCycles每一項沿用單週期輸入。

按全部九個身份欄位精確匹配，重複不取首筆、未列週期不默默忽略。結果cycleResults/cycleScope保留每一輪，coverage列requiredCount、comparedCount、missingCycles與complete；完成覆蓋不代表全部通過。缺簽名是證據不足，不自動判失敗；明確未批准等既有業務判斷照常保留。

## 來源接線與本次修復

新增ndt_approval_cycle_inventory／ndt_approval_cycle_members，成員使用reviewedDocumentVersionId區分被審版本與引用來源版本。既有approvalContexts／requirements／steps／signatureInventories／signatures按完整身份分組，仍驗證工程／租戶／選定文件版本。共用清單來源可信後才逐週期隔離，節點整體grounding門檻保持。

首次新案例發現原單週期適配沒有阻止同一被審文件舊版上的簽名被解析為新版簽名。現以state的版本→文件關係核對：來源屬同一被審文件但版本不同，禁止送入工具；獨立審批登記表仍可提供對應新版的來源。這不是簽名真偽認證，來源語義仍待真實文件驗收。

## 測試證據與未完成項

backend執行 `.venv/bin/python -m pytest -q tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`：648 passed。新增31項覆蓋四態、舊版本／錯週期、重複、漏查、順序不變、共用清單失效、逐輪來源隔離及實際編譯節點結果，另證明獨立登記表不被誤阻擋。Ruff289/289、monolith與diff通過。

本次使用合成解析來源。各聲明清單彼此一致性、真實工程完整性、技術判定及69條全面驗收仍未完成，原pendingCapabilities、試點與發布狀態保持，沒有付費執行、生产部署或歷史任務改寫。
