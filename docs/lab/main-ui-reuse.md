# Lab復用main UI與業務擴充

2026-09-09已fetch origin/main，遠端main為6d4c843c。git merge-base HEAD origin/main等於該提交，HEAD..origin/main無新增提交，證明Lab已包含該main；本地main指標4dfd962d較舊，不以舊指標覆蓋Lab。

## 復用邊界

繼續使用main的Vue／Element Plus、頁面布局、節點樹、對話區、證據預覽與執行軌跡。Lab已有的文件版本、規則草稿與工位交接功能在此基礎上擴充，沒有整批還原frontend或合入另一套前端。

本批將分散在ConversationalReviewWorkbenchB標題區的Lab入口抽為ReviewWorkstationTools，標題區回到main既有的節點標題＋執行軌跡結構。新增工具區集中「選擇本次文件、工程規則、工位交接」，並沿用既有元件、API、未保存提醒及來源／版本驗證。

獨立與embedded節點工作台共用工具區，修正先前embedded模式隱藏規則與交接入口的限制。文件按原canManageEvidence及動作中狀態停用；工位交接在沒有任務時停用並說明，規則與交接的伺服器授權仍沿用既有API。使用activeRunId統一傳遞當前任務ID。

VITE_AICHECK_WORKSTATIONS_ENABLED不是true時整個工具區不渲染。此開關只控制介面，不能取代後端工位開關或權限。沒有修改main、生產部署、後端審查規則、歷史結論或發布狀態。

## 視覺與驗證

使用Element Plus既有語義色彩及字體，按鈕最小高度44px、8px間隔，可換行；沒有新增主題或改main頁面CSS。

- 前端87個單元測試檔通過，vue-tsc全量通過。
- 修改Vue檔ESLint通過，新工具區Stylelint通過。首次新增CSS缺少規則間空行，修正後通過；未宣稱全庫Stylelint通過。
- Chrome工具區測試使用真實三個Vue子元件與模擬業務API，核對鍵盤開啟／關閉、各API工程與任務參數、切換工程關閉舊視窗、文件權限、無任務提示。
- 390×900、900×390及1280×900，深／淺色及減少動畫模式無水平溢出，按鈕達44px；已檢视390淺色及1280深色截圖。
- check-workbench-css.mjs origin/main通過，核對原布局及減少動畫行為。本批没有真實登入帳號的完整工作台業務驗收或生產部署。
- 首次命令因工作目錄重複frontend前綴未寫入，改用絕對路徑後完成。瀏覽器首輪攔截**/api/**誤攔前端模組，縮至業務API；另一輪過早按Escape遇到載入時的關閉保護，改待載入完畢並以實際關閉按鈕驗證鍵盤操作，未放寬產品保護。

截圖：verification/browser/workstation-tools-390-light.png、workstation-tools-1280-dark.png；完整重跑命令見frontend/e2e/lab-rules/README.md。後續main UI更新以已核對提交為基準逐項整合，保留Lab業務擴充及其權限／快照契約。
