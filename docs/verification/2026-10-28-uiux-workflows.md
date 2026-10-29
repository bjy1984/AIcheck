# 工作台 UI/UX 優先修復驗證

日期：2026-10-28（America/Los_Angeles）。依據 `.impeccable/critique/2026-10-29T00-22-28Z__frontend-src.md` 的 W 編號。此紀錄只涵蓋業務工作台分工；沒有部署或提交 Git。

## 已處理

| 問題 | 修復與驗證 |
| --- | --- |
| W01 節點草稿混用 | 人工結論、意見、補正原因、證據選擇依 projectId/nodeId 隔離；A→B→A 恢復 A 草稿，切另一項目同號節點不繼承。正式保存、退回確認前固定 payload，確認後若已換節點即停止。草稿保留在本次頁面會話記憶體，未新增服務端草稿或跨重載持久化。 |
| W02 新補正附件被排除 | 候選包含本節點退回資料及新掛載的補正附件；表格可逐筆勾選。本次上傳成功的 binding IDs 預選，提交不再用空選擇退回全節點 bindings。後端既有提交端點已允許「需補正／草稿掛載」，本次沒有更改規則。 |
| W03 補正清單只看當前節點 | 施工方使用既有受權限篩選的 project rectifications API，讀取全部分頁；列出各補正單所屬真實節點名稱，進詳情／提交先載該節點。載入、失敗、上次清單均明示，數量不可用時不顯示 0。 |
| W04 操作後刷新跳回預設節點 | 同項目刷新預設保留節點和區段；初始載入／明確換項目仍可指定預設選擇。補正上傳後載入補正單真正所屬節點，再開反饋。 |
| W05 AI 對話回應跨上下文 | 發送固定 session etag 與 context generation。每次 await 後先驗證再寫 message/session，舊請求不再復原到新輸入框、停掉新追蹤或修改新 sending。等待回答輪詢同樣驗證。 |
| W08 搜尋假定位 | 文件開真實詳情、報告開真實詳情、節點走可見工作區／施工方節點篩選。失敗保留搜尋結果。入口明示「目前項目」範圍，不再宣稱全局。其他結果按服務端提供的可解析路由開啟，不再無條件彈「已定位」。正式 workbench search API 目前返回 project/node/document/report；舊 mock 的 standard/rule 只帶知識庫總覽路由，不能宣稱已精確開到該規則。 |
| W10 上傳關閉遺失補正目標 | 上傳開始固定 project/node/mode/etag/rectification，後段完成確認與掛載使用原身份；上傳期間關閉／取消禁用並顯示等待文字。舊項目完成不改目前畫面。監檢完成也驗證節點，並去除對舊節點額外載入工作區的重複請求。 |
| W11 報告保存失敗丟稿 | 保存錯誤與初始載入錯誤分開；失敗保持編輯器和章節。成功直接採用返回 report revision 與提交章節，不透過清空詳情再載入。取消編輯／關閉有未存稿確認，保存中不允許關閉。 |
| W12 檢測報告無法換檔 | 選第二檔會取代第一檔，顯示檔名／更換文字及移除按鈕；不清表單 metadata。 |
| W16 Office／文件詳情舊回應覆寫 | Office 轉換及 blob 每步驗代次和文件身份，關閉／換文件／卸載作廢請求。文件詳情本身增加代次，避免 A detail 覆寫 B。普通原文請求關閉也使 token 失效。 |

## 待驗證問題的先紅後綠證據

`workflowConcurrency.test.ts` 透過 TypeScript AST 找到實際元件／helper handler，轉譯後注入可控制完成順序的 Promise。測試執行的是實際函式，不是檢查 guard 字串。

- W05：A 發送 pending，切 B，再完成 A。修前 `workspace.session.id` 得 A、預期 B，確實失敗；修後 B 的 session/message 保持不變。
- W16 Office：先請求 A、後請求 B；B 先完成再 A。修前得到 `blob:A`、預期 `blob:B`；修後保持 B。
- W10：上傳建立會話 pending 時模擬抽屜關閉 watcher 清掉 target。修前補正 bind 呼叫為 0、預期 1；修後仍以原 project A／rectification R-A／node 2 綁定。
- W16 detail：A/B 詳情請求顛倒回應。修前 document.id 得 A、預期 B；修後保持 B。

以上是可執行 handler 層重現，沒有宣稱已在正式環境用大檔／網路限速重現。

## 執行結果

使用專案既有 esbuild + Node assert 方式，僅 bundle 並執行以下測試檔；暫存 `.mjs` 已清除：

- `workflowConcurrency.test.ts`：通過（W05、W10、W16）。
- `workflowContext.test.ts`：通過（W01–W04、W08、W11、W12）。
- `contractorCorrectionUpload.test.ts`、`uploadCompletionPresentation.test.ts`、`todoJumpHonesty.test.ts`：通過。
- `AIReviewB/startReviewLiveTrace.test.ts`、`AIReviewB/savedDecisionFeedback.test.ts`：通過。
- `aiConclusionAvailability.test.ts`：改用真實草稿 helper 驗證初始空意見，通過。
- `uploadedMaterialActions.test.ts`：保留版本替換約束，指向抽離的上傳 handler，通過。
- `git diff --check`：通過。
- W12 建置相容性修正：移除會被 Element Plus style plugin 當成元件的 `genFileId` 匯入，改用元件內遞增 uid；定向測試通過，Vite production mode 的該 SFC 轉換成功且不再生成不存在的 helper style 路徑。整體 build 結果由主代理記錄。

上傳 handler 抽出為 `useWorkbenchUploadSession.ts`，避免增加 Workbench 巨石檔案；此輪量測低於 9636 code lines 基線。全量 typecheck／整體測試由主代理統一記錄。

## 本分工未完成／驗證界限

- 未處理 W06、W07、W09、W13、W14、W15、W17、W18；其他分工是否另行完成請看整體紀錄。
- 未以真實帳號驗證跨角色資料授權、正式物件儲存上傳、Office 轉換服務及報告簽發；既有權限邊界與後端流程維持。
- 沒有刪除業務入口來迴避缺陷，沒有修改原稽核報告的問題數，沒有宣稱全後台問題已清零。
