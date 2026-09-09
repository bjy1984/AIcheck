# R39實際節點綁定與未完成能力門檻（Lab）

## 實際執行

AC-R39-01由通用evaluate_ndt_process改為evaluate_r39_document_content、evaluate_r39_approval_chain及evaluate_r39_first_use_validation，使用現有凍結來源builder與各自工具輸入；保留OCR、欄位／表格讀取及validate_evidence_grounding。AC-R39-02明確標為evidence_gate，證據門禁成功不作業務通過票。

原子項數保持194，R39仍兩項；來源atomic_binding_overrides.py、生成YAML與tools规划.md同步。逐項重建後194條綁定與維護來源語義一致，保留YAML原有註解及試點名單。R39未加入試點，require_published=true仍拒絕執行；本批是Lab實際綁定接入，不是生產開放。

## 未完成能力

AC-R39-01固定parameters.pendingCapabilities列出：

- procedure_reference_consistency：規程與指導書引用一致性。
- method_specific_technical_requirements：檢測方法專項技術要求。
- complete_document_and_application_inventory：完整文件及應用清單覆蓋。

執行器保留所有子工具結果與引用，並在atomicResults.warnings列出pending_capability原因。存在未完成能力時，該原子項不能返回passed或not_applicable，改為evidence_insufficient；可靠的failed、既有execution_error與human_review_required仍沿用原聚合語義。來源門禁失敗仍優先降級不足，不能利用其他子項失敗掩蓋不可靠證據。

這裡的evidence_insufficient表示當前自動審查覆蓋尚不足，不應提示使用者只需補一份文件即可解決；warnings列出實際待開發原因。完整工位介面如何呈現此類原因仍需驗收。

沒有pendingCapabilities的既有原子項維持原行為。欄位存在但為空、非清單或含無效值時視為無效能力宣告，拒絕通過。工具參數不能覆寫固定pendingCapabilities；解除門檻須完成相應實作與驗收後更新維護來源，不能由任務輸入或模型宣告完成。

## 發布檢查

validate_release會拒絕任何仍帶pendingCapabilities欄位的綁定，即使implementationStatus被改成implemented，或該欄位被清成空值，仍不得發布。此項與原有實作狀態、工具註冊及69條驗收清單共同生效，不替代業務驗收。

未修改歷史任務快照，未發布69條、未部署生產、未執行ID遷移。R39技術符合與完整清單仍未完成，不能把本批三項子工具接線視為整條驗收。

## 驗證

實際R39計畫從凍結資料經三個專用工具執行，測試全部子工具通過但整體不足、明確缺項／未批准／未驗證、低可信度失敗降級、非首次應用、證據角色、門檻格式、固定參數覆寫拒絕與發布攔截。首輪一項測試用result=execution_error但沒有既有協議的status=error，修正測試資料後重跑；未改既有故障聚合語義。

相關164 passed；完整收集4069項，4003 passed／66 skipped／6 warnings，1075.12秒，退出0。完整紀錄及跳過原因見r39-node-plan-backend.txt，環境跳過不算PostgreSQL／MinIO／Temporal實機驗收。本轮較慢但原因未核定，不作性能效果宣稱。Ruff289／289、diff check通過；配置比對只有R39兩項變更，其餘192項與發布中繼資料不變。


## 2026-09-09：R39指定文件對的規程引用比對

- 新增evaluate_r39_procedure_reference及來源適配，接入實際AC-R39-01工具鏈；同工程、機構、方法及明確指定的指導書／規程固定版本，逐項比對引用編號和版本。缺值返回證據不足，明確不一致返回failed；不猜測版本等價，不把所選規程當成全工程適用規程清單。
- 四類獨立來源表ndt_reference_context／ndt_reference_basis／ndt_instruction_reference／ndt_procedure_identity由既有凍結讀取器提供原文位置。兩個文件均須在工程、租戶與所選版本範圍內；同名多筆、不可靠來源及引用錯文件均不放行。
- 同步atomic_binding_overrides.py、綁定YAML、tools规划.md。132條來源／R39回歸通過，最後43條綁定重建與節點回歸通過。新增子項成功仍不代表R39成功；完整文件對清單、方法專項要求及全量應用清單尚未完成，原pendingCapabilities保留。
- 本批是合成來源的確定性比對驗收，沒有人工標準採信背書、沒有模型實跑或生產發布。真實資料解析成這四類來源表及全量文件對覆蓋仍待驗收。
