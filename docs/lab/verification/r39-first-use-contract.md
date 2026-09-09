# R39 首次應用工藝驗證核心（Lab）

工具：evaluate_r39_first_use_validation；版本：r39-first-use-validation-occurrence-v1。

## 原文依據與能力邊界

本庫 rules/results/NB_T 47013.1-2015 承压设备无损检测 第1部分 通用要求.pdf.md 的4.3.2.3要求操作指導書首次應用時進行工藝驗證，列出對比試塊、模擬試塊或直接在檢測對象上的驗證方式。本批以既有本地轉錄為依據，未重新核定標準現行有效性或完成PDF影像人工覆核；實際適用性須由上游提供有來源的依據。

此工具只核對該次首次應用的驗證是否實施及是否在首次應用時實施。不是整條R39判定，不核定驗證效果、工藝參數技術符合性、編審批准或完整文件內容。輸出wholeRuleAcceptance=not_evaluated、evidenceVerified=false。工具已註冊，但未接入R39正式原子綁定，也未改發布狀態。

## 輸入

- scope：projectId、organizationId、instructionId、instructionVersion、method、objectId、eventId，皆為非空且無首尾空白字串。事件指本次操作指導書應用，不由焊口或文件編號猜填。
- basis：重複以上完整身份，standard精確為NB/T 47013.1-2015、clause為4.3.2.3、applicable為布林true，及evidenceRefs。不同標準或適用性未知返回不足，由上游選擇其他適用判定。
- application：完整身份、firstUse布林、completed布林及evidenceRefs。firstUse=false只代表當前事件不適用「首次應用」子檢查，不證明歷史首次應用合規。
- validation：完整身份、performed與atFirstUse布林及evidenceRefs。performed=false須為明確有來源的未實施事實，不得由缺文件推導。
- 每份evidenceRefs要求非空列表，各項含documentVersionId、正整數pageNo（不接受bool）及非空quotedText。本工具檢查引用結構，不認證摘錄真實性或語義支持；正式接線仍需凍結範圍與證據核驗。

## 四態與保守處理

- 符合：來源和身份完整、適用、首次應用已完成，明確已執行且在首次應用時驗證。只適用於上述狹義子檢查。
- 不符合：首次應用已完成，明確未驗證；或已驗證但明確不在首次應用時進行。
- 證據不足：資料、引用、身份、首次應用性或時機未知；首次應用尚未完成或完成狀態未知亦返回不足，避免過早認定未履行。
- 不適用：適用標準依據存在，且有同事件來源明確不是首次應用。

沒有新增「必須在應用開始前完成」要求；不以列舉方式以外的方法直接判不符合。方法有效性須另行專業審查，通過本工具不代表該方法被採信。所有來源按版本、檢測单位、方法、對象、事件及指導書版本精確匹配。

## 後續整合

補齊R39工藝規程／指導書內容、引用版本與批准程序、方法專項技術要求；建立凍結文件事實組裝及原子項專屬輸入，再接入完整R39執行／四態重放。不得以本工具的註冊或passed替代整條R39業務驗收。真實文檔引用支持、全部69條驗收與發布仍未完成。

## 本批驗證

首次應用核心與業務工具163 passed；完整收集3860項，3794 passed／66 skipped／6 warnings，250.53秒，退出0。原始輸出見r39-first-use-backend.txt。Ruff289／289，沒有提高基線；環境跳過不代表服務實機驗收。
