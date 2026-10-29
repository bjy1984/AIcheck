# 工作台後續 UI/UX 修復與逐頁驗證

本輪先證實上一輪留下的待驗證問題，再修正產品碼。未修改產品 seed、業務包配置、權限或正式資料。已使用最終 production build `dist-uiux-followup-final` 與隔離記憶體 API，完成 **5/5 個主路由、14 張修後原始 JPEG** 逐張目視；另有 2 張修前問題證據。完整結果見 [manifest.json](manifest.json)。Chrome 視窗 1470×692，沒有改動共享 viewport。

## 已確認並修復

| 問題 | 修前證據 | 修改 |
|---|---|---|
| 切換發現篩選後，已被排除的發現詳情仍留在畫面 | 新增 workbenchSelection.test.ts，以實際 Vue ref/computed 執行元件原本的 computed 與 showFindings handler；待確認側欄切換與關聯證據下拉兩個情境均失敗 | selectedFinding 只從 visibleFindings 解析；不匹配時隱藏詳情，仍匹配的選取保留；資料移除亦不留舊詳情 |
| 下拉改成關聯證據篩選後，側欄仍標示人工確認 | 中間版實際 CUA 操作確認列表已換篩選，但側欄高亮仍停在上一入口 | 下拉 change 共用 showFindings handler；全部／待確認／有證據分別同步至發現／人工確認／證據鏈路 |
| 業主歸檔表直接顯示 report/evidence，其中 evidence 被窄欄拆行 | 上輪目視截圖 04d-owner-detail-summary.jpg，對照 ReportArchivePanel.vue 的原始 type 欄 | 類型顯示「資料文件／報告／證據資料」，類型欄加寬至 100px；未知型別顯示待核對 |
| 右側「最新報告／歸檔」與主區摘要、時間線不一致 | 實際元件 computed 回歸：輸入較舊記錄在先、較新記錄在後；右側兩個值及歸檔面板的最新報告共三項失敗 | 三個元件共用 latestReportVersion/latestArchiveItem；依更新日期（報告可回退生成日期）選最新資料，不改動傳入陣列次序，空資料回傳 undefined |

## 定向驗證

- `workbenchSelection.test.ts`：修前明確得到 5 項失敗，修後全部通過。涵蓋 pending/evidence 篩選排除、仍可見的選取、資料移除、未排序輸入、更新日期優先、空清單及不改動原陣列；補充實際 handler 的 pending→human、evidence→evidence、all→findings 映射。
- 已用上一版 `dist-uiux-release` + 隔離 fixture 在 Chrome 1470×692 實際重現兩種殘留並目視截圖：`before-generic-stale-selection.jpg` 顯示待確認清單仍留已採納詳情；`before-generic-stale-evidence.jpg` 顯示有證據清單仍留無證據詳情。
- `workbenchTruth.test.ts`：既有待人工確認狀態、真實活動、未知與空態、補正計數、證據載入競態全部通過。
- 本輪修改的 6 個檔案通過 ESLint 與 Prettier；全站型別檢查、完整測試與 production build 由主代理集中執行。
- 主代理最終整合驗證：126 個測試通過、0 失敗，型別檢查與 production build 通過；靜態檢查 626 檔、0 發現。
- `intermediate/` 保留第一次集中建置的目視 QA 圖，供排查歷史使用，沒有列入最終 manifest 或路由覆蓋數。
- 現有 generic demo 只有一筆發現，同時符合三個篩選，無法用它證實「排除已選發現」。除了實際元件邏輯回歸，`serve.py` 新增可選 `workflow-filter-extras` 旗標：在隔離記憶體環境複製同 tenant/project/node 的兩筆明確標示為「隔離截圖示例」的發現（一筆已採納，一筆未關聯證據），未修改產品 seed、成員或授權規則，未偽造證據引用。實際瀏覽器結果另記 manifest。

## 仍屬資料問題的限制

- `compliance_audit_v1/fixtures.yaml` 的 EV-CA-001 是 legacy evidenceLinks，指向 DV-CA-001-V1；finding 位於節點 3，而該文件 binding 位於節點 1。可見節點證據 API 依 node_evidence_links 授權與定位回傳，不能憑引用代碼拼接成錯誤原文入口。現有詳情繼續清楚顯示引用暫不可查看；沒有放寬權限或猜證據位置。
- 合規業務包的「長輸管道」名稱來自 backend manifest 配置。本輪沒有把這個配置語意問題當作前端修復。
- 報告與歸檔時間的目前契約為後端 `server_time()` 的 `YYYY-MM-DD HH:mm:ss`；seed、生成、更新與歸檔皆採相同格式。沒有把不含時區的服務時間擅自當成瀏覽器本地時區。若未來 API 改為混合 ISO offset，應連同時間契約更新比較方式。

## 最終瀏覽器結果

- **監檢／施工／無損檢測：**三個主頁皆於資料載入完成後重拍；施工補正入口實際篩出 1／3 份文件，檢測歷史資料與目前上傳文件數分開顯示。
- **建設方：**歸檔類型已顯示「報告／證據資料」，沒有代碼拆行；09:45 的證據包在時間線、主區與最新歸檔摘要一致。可見報告為空，因此非空報告排序由實際 computed 回歸覆蓋，沒有宣稱以畫面覆蓋不存在的資料。
- **通用：**已採納詳情切到待確認後移除，無證據詳情切到有證據後移除，兩次都確認對應 heading count=0；三種篩選的側欄高亮同步。返回全部發現後，可見的原選取可恢復詳情。
- 14 張最終圖全部 `reviewed: true`、`status: verified`、`build: dist-uiux-followup-final`；2 張修前圖為 `before-confirmed`。中間 QA 圖不計入最終覆蓋。瀏覽器最後的 error log 為空，臨時分頁已關閉；4190 修前服務已停止，4188 最終服務由主代理管理。
