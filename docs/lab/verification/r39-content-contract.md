# R39 通用工藝文件內容核對（Lab）

工具evaluate_r39_document_content，版本r39-nbt47013-common-document-content-v2。

## 來源與適用範圍

依本庫rules/results/NB_T 47013.1-2015 承压设备无损检测 第1部分 通用要求.pdf.md第7.2.2及7.2.3的轉錄，分別核對工藝規程13組、操作指導書11組通用必備內容；每組內的要求拆成獨立子項。沒有對PDF影像重新作人工覆核或重新判定標準現行有效性；實際適用條款及版本須由上游提供來源並採信。

規程內容包括版本、範圍、引用文件、人員资格要求、設備器材／校驗及運行檢查、相關因素及範圍、按對象選擇工藝與指導書要求、實施要求、結果評定及分級、記錄、報告、編審批准及編制日期。指導書包括編號、引用規程及版本、技術要求、檢測對象、設備器材及性能檢查、參數、程序、示意圖、記錄規定、編審及日期。

此為內容覆蓋檢查，不驗證技術值是否正確、資格級別是否符合、簽名真偽、引用版本是否適用或方法專項標準要求是否完整。操作指導書不憑空增加7.2.2列出的批准者欄位；其他法規／品質體系仍可能另有批准要求，須由批准鏈及標準適用性檢查處理。

## 輸入契約

- projectId與scope.projectId一致。scope包含projectId、organizationId、documentId、documentVersionId、documentKind（procedure/instruction）及method，皆非空無首尾空白字串。
- basis重複scope，standard為NB/T 47013.1-2015，clause按文件類型為7.2.2或7.2.3，applicable為嚴格布林及evidenceRefs。明確有來源的false僅使此通用條款子檢查不適用，不代表R39或其他標準不適用。
- contentInventory重複scope，含evidenceRefs、completeDocumentReview及fields。完整核閱為上游有來源的宣告，工具不自行認證全頁已讀。
- fields每筆重複scope，包含fieldId、presence（present/absent/unknown）、value及evidenceRefs。必備fieldId與條款對照定義在r39_content.py；未知或重複fieldId、錯誤身份先拒絕。
- present須有非空字串value及同一被審版本的實際摘錄引用；absent須有明確引用、空value及completeDocumentReview精確true。其他情況返回不足，不由OCR欄位缺失推定文件漏項。具體值及語義正確性仍待專項核對。
- 各引用要求documentVersionId、正整數pageNo及非空quotedText。只有圖像／bbox而無可用原文摘錄時返回不足，並不代表文件沒有該圖；圖片語義核驗另行處理。

## 凍結資料接線

來源增加ndt_content_context、ndt_content_basis、ndt_content_inventory及ndt_content_fields四種businessSchema。來源資料用reviewedDocumentVersionId表示被審版本，實際evidenceRefs.documentVersionId由解析記錄確定。被審文件須已選入任務且屬本租戶工程。

上下文／依據／清單表頭須唯一，所有內容資料列身份須一致；欄位來自獨立表格資料列，覆蓋表頭內嵌fields。從品質體系或其他版本抄入的內容引用不能充當被審文件原文。來源仍沿用版本快照、工程租戶、來源變動檢查；build_tool_arguments已接入documentContent。

## 判定邊界與後續

輸出contentChecks保留各子項條款與引用。所有必需子項內容明確才passed；完整核閱後有來源明確缺項才failed；漏讀、未知或衝突返回不足。輸出technicalCompliance=not_evaluated、wholeRuleAcceptance=not_evaluated、evidenceVerified=false，不能據此宣稱R39已通過。

仍待工藝規程与指導書引用一致性、方法專項技術比較、完整文件／週期覆蓋、原子綁定與真實來源語義驗收。未修改R39發布狀態或部署生產。

## 本批驗證

340項相關回歸通過，包括兩類文件四態、逐子項缺失、六欄身份、同版本引用、明確缺項與漏讀、真假布林、重複／未知欄位、不預設批准者或級別，以及來源builder到runtime的接線與既有R39、工位、執行器、業務工具、巨石回歸。Ruff初次一項測試匯入I001，修正排序後289／289，未提高基線。本批未重跑完整後端；上一批3874 passed／66 skipped是本批修改前全量紀錄。

2026-09-09後續：v2於不適用分支前核對已提供內容清單與欄位身份、重複及未知fieldId；builder另加入按工具來源分組的初步門檻，詳見r39-source-gate-contract.md。
