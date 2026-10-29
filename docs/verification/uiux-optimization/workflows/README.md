# 工作台截圖問題優化

本輪沿用既有視覺樣式，針對上一輪逐頁截圖確認的可讀性與狀態誤導修復。沒有修改 seed、正式資料、權限政策，也沒有提交或部署。

## 修復與資料來源

| 問題 | 已核對來源 | 修改 |
|---|---|---|
| 通用頁雙欄表格右側裁切、發現長標題省略 | 前端兩表固定欄寬總和超過各自半欄寬度；before 28–29 | 改為完整寬度上下排列；節點、分組、發現文字換行，狀態、置信度及操作同列可讀 |
| 通用頁直接顯示 EvidenceRef、業務包代碼 | GenericReviewWorkbench.vue 靜態文案 | 改為關聯證據、原文追溯、專案摘要；業務類型回傳與專案不一致時顯示待核對，不替後端猜名稱 |
| 人工確認顯示0，但發現仍待確認 | 後端預設 `humanStatus=pending_human_review`；舊前端用 `!humanStatus` | 明確認定待確認狀態；accepted/rejected優先，與後端採納／拒絕更新契約一致 |
| 證據／人工確認只停在數量 | `GET /projects/{id}/review-workbench` 提供逐筆finding；node package提供人工意見，evidence-chain提供已授權節點證據 | 卡片及側欄篩選具體發現；每筆可開啟內容、規則引用、精確證據引用與同節點人工意見。僅監檢且具review:save可到對應node的human_review視圖 |
| owner報告V0.8／復核中、4筆時間線、2項異常為固定值 | WorkbenchRoleStaticSections.vue及WorkbenchRightStaticDetails.vue硬編碼，並非API回傳 | 改為真實reports/archive/project/node；空授權清單顯示無可查看記錄，載入中／失敗顯示未知與重試；不再造預計進度、爐批號或照片問題 |
| owner節點總覽只顯示當前一個節點 | 既有ownerNodeRows只讀props.node | 顯示全部授權可見projectNodes，缺資料數顯示—，不將node補正狀態猜成異常數 |
| contractor需補正文件1、意見0口徑不清 | 文件數依binding狀態；補正API依可見binding/submission過濾，無可見關聯的補正單不暴露給施工方 | 明示按文件與按意見分別統計；提供實際「需補正」文件篩選入口；尚未載入不顯示0，不放寬權限或改seed |

## 定向驗證

- `workbenchTruth.test.ts`：pending_human_review／accepted／rejected；真實時間線與空資料；未知／失敗不補零；補正文件與意見分別計數；切換發現後舊證據回應不覆蓋新發現。
- `workflowConcurrency.test.ts`：W05、W10、W16通過；Office預覽競態fixture已改為有效PDF Blob並使用新previewContentError驗證。
- `workflowContext.test.ts`：W01–W04、W08、W11、W12通過。
- `workbenchRoleAccess.test.ts`、`ownerExportButtons.test.ts`通過。
- 全量型別檢查與build由主代理集中執行；本輪沒有重跑全套測試搶資源。

## 限制

- 舊generic demo的EV-CA-001屬legacy evidence_links，引用其他節點的documentVersion；目前節點evidence-chain只回傳node_evidence_links及其匹配證據。本輪不偽造證據位置，找不到精確引用時顯示「引用證據暫不可查看」，保留查核原因。
- 不新增另一套正式審查表單；已有權限的監檢人員進入既有節點人工審查。管理員／施工方／建設方只能查看可見記錄。
- 已以最終 production 建置 `dist-uiux-final` 與隔離記憶體 API 完成 5/5 個主路由、16 張原始 JPEG 逐張目視。視窗為 Chrome 1470×748（DPR 2 原圖）；沒有改動共享 viewport。詳見 [manifest.json](manifest.json)。

補充只讀查核：合規demo專案顯示「長輸管道」來自 `backend/business_packs/compliance_audit_v1/manifest.yaml` 的 `name`，該檔同時保留 `domainType: compliance_audit`。這是業務類型配置語意衝突，不是前端ID映射錯誤；本輪沒有改配置或seed來掩蓋。正常回傳同一ID時仍顯示配置名稱，不能把此項列為已修。

待後續情境驗證：若先開啟某筆發現，再改成不包含該發現的篩選，詳情可能仍保留。現有demo只有一筆待確認發現；本輪凍結後未直接追加修正，已回報主代理。

## 本輪瀏覽器驗證結果

- **監檢：**登入與完整工作台總覽、節點資料缺漏、AI未運行及人工結論前置阻斷均正常顯示（01、01b）。
- **施工：**在華東成品油專案顯示待處理意見0／待提交1／審核中1；補正提示明確區分1份需補正文件與0條可見意見。點擊「查看需補正文件（1）」實際篩選為1/3檔案，僅列出鋼管質量證明書（02、02b、02c）。
- **檢測：**歷史底片/記錄/報告5項、待處理回饋1項與目前已上傳文件0分開呈現；報告上傳表單可開啟及取消，未選檔/送出（03、03b）。
- **建設方：**顯示6個授權可見節點；報告列表0與歸檔2分開呈現。最近更新是2筆實際歸檔及1筆項目更新，無硬寫預計進度。節點風險摘要與報告空態均誠實呈現（04–04e）。
- **通用：**待人工確認正確為1條；卡片按鈕實際定位並篩出待確認發現。節點/發現全寬表格可同時閱讀長標題、置信度82%、人工狀態與操作；逐筆詳情顯示規則、legacy引用不可查看原因和節點人工意見空態。管理員只有查看，未提供越權確認按鈕（05–05d）。

尚存次要觀察：建設方歸檔表的`report/evidence`類型仍為原始代碼，其中`evidence`在窄欄換行（04d）；已回報主代理，未將此列為本輪已修。通用發現篩選只有全部／待人工確認／有關聯證據，現有唯一示例同時滿足三者，因此「詳情可能保留於不匹配篩選」情境仍未能用現有示例重現，不宣稱已驗收或已修復。
