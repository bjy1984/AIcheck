# R39 尚未應用的資料契約

## 零應用不等於沒有找到記錄

applicationInventory的members可為空，但必須complete=true、有引用、declaredApplicationCount為整數0。布林false、小數0.0、字串零、缺省、負數或不符成員數均拒絕。非空舊清單可繼續省略count；提供時必須精確等於members數量。零清單若仍傳application資料或存在未列入的來源事件，不得返回不適用。

首用子工具僅在上述聲明清單有效且沒有應用輸入時返回not_applicable；不以找不到驗證記錄推定尚未使用。cross-inventory亦使用同一count契約。

## 按文件排除未使用項目

unappliedInstructions是有來源的文件聲明，每筆含projectId、organizationId、documentId、documentVersionId、documentKind=instruction、method、reason=not_yet_applied、applied=false、evidenceRefs。必須唯一存在於內容清單，且不能同時被applicationDocumentLinks引用；錯版、未知原因、重複、不實際屬此工程／清單或無引用都保留不足。所排除的僅是應用映射要求，不跳過文件內容、引用和簽核核對。

新增ndt_unapplied_instructions源表，以reviewedDocumentVersionId區分被審版本與來源版本，來源門檻覆蓋引用與可信度；既有已用／未用文件可混合。清單工具ruleVersion分別更新r39-application-inventory-v2與r39-cross-inventory-v2。

## 驗證與剩餘範圍

新增22項單元及凍結來源／編譯節點測試，涵蓋空清單、嚴格零值、聲明缺失、錯版、無引用、重複、應用衝突、低可信及已用／未用混合。backend命令 `.venv/bin/python -m pytest -q tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`：707 passed；Ruff289/289、monolith與diff通過。

以上為合成來源驗證，沒有人工對真實尚未使用狀態的背書。內容、技術與簽核未完成時整個節點仍為證據不足，pendingCapabilities、試點及發布狀態未變。真實案件和完整技術判定仍待驗收。
