# R39 明確品質體系簽批鏈核對（Lab）

工具 evaluate_r39_approval_chain，版本 r39-explicit-qms-approval-chain-v1。按來源明確的單份工藝文件、单一版本與批准週期核對簽批，不預設所有文件具有相同編審批准角色。

## 依據與邊界

本庫TSG D7006-2020轉錄D2.8.3要求工藝文件的批准程序符合品質保證體系文件。NB/T47013.1-2015轉錄7.2.2／7.2.3分別列出工藝規程與操作指導書的編審批准／編審內容；7.2.4要求符合相關法規或標準。本工具不從上述文字推定统一III級資格、固定人員分離或統一批准順序。

實際要求由上游凍結的、帶引用的品質體系資料提供，須另核對標準最低要求、適用性與完整性。complete及authorizationComplete為來源宣告，不是工具自行認證。此工具不查資格證真偽、效期、委託授權或工藝技術正確性；未完成上述鏈路時不能用子工具passed替代整條R39判定。

## 輸入

- projectId須與scope.projectId一致，以配合既有runtime頂層工程核對。
- scope固定projectId、organizationId、documentId、documentVersionId、documentKind（procedure或instruction）、method、approvalCycleId、procedureId、procedureVersion；皆非空無首尾空白字串。
- requirements重複完整scope，applicable=true、complete=true，非空steps及evidenceRefs。未知欄位（例如尚未支援的發行日期限制）拒絕，不靜默忽略。
- step包含stepId、role、required布林、evidenceRefs、after與distinctFrom字串清單。必需步驟另含非空不重複authorizedSignerIds與authorizationComplete=true。人員名單為此版本／範圍／週期所適用的明確完整授權集合；無法確定完整集合時不能填true。
- after指定前置必需步驟，前置成功且簽批時間不晚於當前步驟。distinctFrom指定必須不同簽署人的步驟，未要求時不擅自禁止同人。
- step未知欄位拒絕，包括尚未支援的資格等級條件。所有依賴先驗證，拒絕未知、自我、指向選配步驟及順序循環；即使步驟不必需亦不掩蓋無效設定。
- signatureInventory重複scope，complete=true、evidenceRefs、signatures列表；每筆簽批重複scope，包含stepId、role、signerId、approved布林、帶時區ISO signedAt及evidenceRefs。同一週期每步驟只允許一筆明確記錄。原始文件包含撤回／重簽歷史時須先建立明確週期與有效記錄，不能自行取最新一筆。
- 引用均要求documentVersionId、正整數pageNo及quotedText。工具不核驗引用原文或範圍權限，正式資料接線仍須通過凍結文件及證據門禁。

## 結果

完整明確要求及記錄的必需步驟全部核對通過時返回passed。明確未批准、錯角色、非授權人員、順序或明確人員分離違反返回failed；其中「未批准」代表該週期文件未達已批准狀態，不意味拒絕批准的行為違法。缺記錄／無效資料／孤兒或重複簽批返回evidence_insufficient，缺記錄不自動判定漏簽。完整明確清單僅含非必需步驟且清單有效時，該子檢查返回not_applicable。

輸出包含逐項approvalChecks及來源，wholeRuleAcceptance=not_evaluated、evidenceVerified=false。原始輸入不修改，歷史記錄不重寫。R39正式原子綁定仍未改，尚需工藝內容、標準要求完整性、凍結事實組裝及整條規則验收。

## 驗證

2026-09-09：批准鏈／首次應用／業務工具／執行器／工位隔離／巨石基線269 passed。包括四態、跨範圍九欄、批准週期與版本、引用／清單缺失、重複和孤兒、順序循環、時區等價、人員分離、未知條件及不預設批准角色。Ruff289／289，未提高基線。本批未重跑完整後端；上一批3794 passed／66 skipped為本批修改前紀錄。
