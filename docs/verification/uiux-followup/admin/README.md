# 管理後台後續優化驗證

本輪保留前一輪 `docs/verification/uiux-optimization/admin` 的 13 路由、24 張原圖；新證據獨立存放於此。

## 已確認與修復

- 審查點浮層殘留：在 `dist-uiux-release` 點擊第一列被截斷的 OCR 證據文字，再搜尋不存在的詞，清單為 0 筆時原提示仍停留在左上角。`before-material-no-results.jpg` 為 Chrome CUA 原始畫面。程式檢查顯示表格溢出提示依賴已移除的列元素；本輪改為長文本直接換行，移除該表對溢出提示的依賴，不使用 DOM 刪除或 Element Plus 私有 API。
- 規則與流程：兩組表格改為上下全寬排列，名稱、版本、Prompt、節點直接換行，保留詳情／差異／編輯與所有原欄位。
- 業務類型：狀態移到名稱旁；分級範圍與項目屬性換行顯示，縮減過寬的欄位分配，保留所有欄位與排序。
- Prompt／報告模板：名稱、識別碼及更新時間同格分層；Prompt 版本與模板版本同格。導出類型、Agent 與業務類型完整換行。操作改為兩欄排列並縮小固定操作區，沿用原權限與事件。合併的次要資訊不再有獨立排序表頭。
- 接口契約：狀態前移；模組與負責人、狀態與級別、前後端欄位分組顯示，接口與說明直接換行；資料與篩選保留，合併的次要資訊不再有獨立排序表頭。

## 業務類型名稱核對

以下映射均由 `backend/business_packs/*/manifest.yaml` 明確配置；前端顯示並非自行猜測。本輪沒有修改 manifest、seed、domainType 或業務邏輯。

| 業務包 ID | domainType | name／pipelineTypeName |
| --- | --- | --- |
| compliance_audit_v1 | compliance_audit | 長輸管道 |
| device_inspection_v1 | device_inspection | 公用管道 |
| engineering_inspection_v1 | engineering_inspection | 工業管道 |

模板名稱仍含「合規審計／設備年檢」等舊業務語意，而業務包配置已採管道類型名稱。若需統一命名，應先確認產品資料遷移與模板用途；不能僅由識別碼字面推斷重新歸類。

## 本地檢查

`adminListPresentation.test.ts`、`adminOverviewSections.test.ts` 均通過，涵蓋 168 筆搜尋／分頁、正式模板草稿衍生與發布候選、管理區定位等既有行為。`AdminOverview.vue` 的 ESLint、Prettier 與 Vue 模板編譯通過。本輪為呈現調整，未新增僅重述 CSS 的測試。全站整合檢查與 production build 由主代理統一執行。

## 最終逐頁目視確認

`dist-uiux-followup-final` 強制重載後完成 **13/13 個管理主路由、28 張原始 JPEG**，每張均目視並於 [manifest.json](manifest.json) 記錄版本、路由、實際尺寸及限制。另保留 1 張最初修前問題證據。最終 manifest 僅包含修前與 final 版；中間 QA 原圖和 `qa-intermediate-manifest.json` 留存但不計入覆蓋。

| 主路由 | 最終原圖 |
| --- | --- |
| /admin/overview | [管理總覽](final-01-overview.jpg) |
| /admin/projects | [項目管理](final-02-projects.jpg) |
| /admin/org | [組織清單](final-03-org-organizations.jpg)、[組織搜尋](final-03b-org-search.jpg)、[使用者搜尋](final-03c-user-search.jpg) |
| /admin/business-packs | [業務類型](final-04-business-packs.jpg) |
| /admin/permission | [權限矩陣](final-05-permission.jpg) |
| /admin/rules | [規則清單](final-06-rules.jpg)、[詳情](final-06b-rule-detail.jpg)、[流程](final-06c-workflow-state-machine.jpg) |
| /admin/material-review-points | [審查點](final-07-material-review-points.jpg)、[零結果](final-07b-material-no-results.jpg)、[末頁搜尋](final-07c-material-tail-search.jpg) |
| /admin/prompt-templates | [Prompt清單](final-08-prompt-templates.jpg)、[草稿](final-08b-prompt-draft.jpg) |
| /admin/report-templates | [報告清單](final-09-report-templates.jpg)、[草稿](final-09b-report-draft.jpg) |
| /admin/fine-config | [待辦／消息](final-10-fine-config.jpg)、[工具／映射](final-10b-fine-config-mappings.jpg) |
| /admin/integration | [聯調摘要](final-11-integration.jpg)、[契約欄位](final-11b-integration-fields.jpg) |
| /admin/skill-requests | [請求空狀態](final-12-skill-requests.jpg) |
| /admin/audit | [審計日誌](final-13-audit.jpg) |

核心互動已確認：

- 審查點點擊同一段 OCR 證據文字，再搜尋不存在字詞，0 筆結果沒有左上角殘留提示；重置恢復 168 筆，搜尋 `pmi_report` 命中節點 16／21 兩筆。
- 組織搜尋 `粤检` 命中 1／5，使用者搜尋 `ndt` 命中 1／7，兩組條件獨立。
- 規則詳情正常載入；中間 QA 也確認差異抽屜返回實際 7 項新增／3 項需複核，未操作發布。
- Prompt／報告正式版仍限制發布及刪除；衍生草稿為 `2026.06-draft` 並保留內容。報告保留 4 章節與 3 導出選項，取消後原清單仍為 3 筆；Prompt仍為 1 筆。沒有提交任何保存或發布。
- 聯調清單實際返回 6 項已對齊；Skill請求為 0 筆，審計日誌為 1 筆並如實提示歷史記錄未封存。

常規截圖為 1470×692。等待其他 Chrome 驗證全部結束後補拍 1280×720 的 [Prompt](final-08c-prompt-1280.jpg)、[報告](final-09c-report-1280.jpg)、[契約](final-11c-integration-1280.jpg)，及 900×720 的 [規則](final-06d-rules-900.jpg)、[流程](final-06e-workflow-900.jpg)。已恢復預設 viewport 並關閉本代理分頁。

主代理最終整合檢查：126 個單元測試通過、型別檢查通過、production build 通過、靜態檢查 626 檔 0 發現。

## 範圍與限制

- 使用隔離記憶體示例資料與真實 API，不代表正式資料庫、外部 OCR 或完整發布流程驗收。
- 審查點全部欄位仍需要橫向捲動；1280 以下的部分模板／契約、900 的規則表亦需捲動查看全部欄位。長文本在欄位內直接換行，沒有以縮小字級壓入全部資訊。
- 項目表長施工單位名稱、規則差異抽屜的長值仍沿用既有省略提示；本輪未擴大到這些次要視圖。
- 模板名稱與業務包名稱語意差異有明確配置來源，需產品資料治理確認後再處理；未直接改動 seed。

