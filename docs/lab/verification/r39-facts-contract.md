# R39 凍結文件事實接線（Lab）

build_r39_business_facts加入NDT_FACT_BUILDERS[39]，沿用selected_parse_results及read_ndt_tables。正式執行器建立businessFacts時會選取此builder；兩個R39專用工具的參數組裝亦已接入，但現有R39原子綁定尚未切換到這兩個工具。因此本批不是整條R39端到端業務驗收或發布。

## 來源格式

只接受有businessSchema的結構化OCR表及normalizedRows；沒有以檔名、自由文字或JSON字串猜造事實。實際來源限任務選定版本、租戶與工程；已有documentScopeSnapshot時核對來源指紋。OCR／人工修正變更後阻擋舊任務，不改寫快照。

首次應用工具：ndt_instruction_application、ndt_first_use_basis、ndt_first_use_validation，分別提供應用、依據與驗證。一次目前只組裝一個明確應用事件；多事件／重複依據或驗證保留sourceRecords並列sourceIssues，不自行挑第一筆或忽略其餘資料。

批准鏈工具：ndt_approval_context、ndt_approval_requirements、ndt_approval_steps、ndt_signature_inventory、ndt_approval_signatures。上下文、要求表頭及簽批清單表頭須唯一。步驟與簽批必須來自獨立結構化資料列，覆蓋表頭內嵌steps／signatures，不信任內嵌資料的自報引用。

## 被審版本與來源版本

批准鏈的所有資料列用reviewedDocumentVersionId表示被審文件版本；documentId表示被審文件ID。實際證據來源的documentVersionId由OCR解析記錄確定，無法由資料列中的evidenceRefs重新指定。

組裝後，工具的scope／requirements／signatures.documentVersionId是被審版本；evidenceRefs.documentVersionId仍為各自原始來源版本。例如QMSV1文件中的要求可用於DV1工藝文件，不把QMSV1誤當被審版本。被審版本必須已選入任務，且版本／文件註冊資料在本租戶工程內唯一匹配。

每筆要求、步驟、清單和簽批須與同一scope的九欄一致。額外跨範圍資料不靜默過濾，而使本次批准鏈輸入不可用；來源記錄仍保留供檢查。未知業務要求欄位保留傳入，交由專用工具拒絕，避免組裝時丟失限制條件。

## 證據與結果邊界

引用由來源表提供版本、頁碼、tableId、rowIndex與實際contentMarkdown／bbox，覆寫自報引用；不以str(row)製造摘錄。R39工具目前要求quotedText，因此只有bbox但沒有原文摘錄的表返回證據不足。

judgment沿用現有來源可信度／衝突資料，供後續證據門禁使用。直接執行專用工具不等於已完成語義支持核驗；本批驗證的passed只表示結構化事實符合該子工具條件，wholeRuleAcceptance仍not_evaluated。原子綁定、完整工藝內容、方法專項要求、全部文件／週期覆蓋及真實掃描文件驗收仍待完成。

## 本批驗證

來源builder→build_tool_arguments→runtime的兩工具檢查、缺表／未選來源／工程租戶／被審版本／九欄身份／重複表頭／未知要求／缺原文／內嵌資料與偽造引用／來源變動，以及既有R39核心、執行器、工位及巨石基線：222 passed。初次Ruff有一項I001匯入排序告警，僅修正排序後289／289，未提高基線。

完整收集3940項，3874 passed／66 skipped／6 warnings，233.99秒，退出0。原始結果及跳過原因見r39-facts-backend.txt，環境跳過不代表實機驗收。
