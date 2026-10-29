# 知識庫 UI/UX 修復驗證（2026-10-28）

依據 `.impeccable/critique/2026-10-29T00-22-28Z__frontend-src.md`。本次保留原有視覺與操作架構，修復最優先五組在知識庫範圍的問題。未部署、未修改真實資料、未更改後端。

## 修復與證據

| 編號 | 修前確認 | 修復 |
| --- | --- | --- |
| A04 | 實際執行原 SFC `handleImportRulesStandards`，模擬取消確認仍發出 1 次 reset（原函式沒有確認）。後端 `knowledge_admin_routes.py` 確認 reset 範圍為預設標準源所有文件及其關聯記錄。 | 危險按鈕改為「重置預設標準庫」，顯示具名來源、既有上傳亦受影響、重建內容與不可由頁面撤銷；取消不呼叫 API。 |
| A02/A05 | 執行原 tab loader，overview 只呼叫 overview API，沒有載入畫面使用的 sources；摘要直接讀尚未載入或單頁陣列。 | overview 自行載入 sources；全域計數僅使用全域 API total/metric，未知顯示「未取得」；當頁統計明確標示本頁／目前篩選。 |
| A06 | 原 files tab loader 只有 loadFiles，專案載入僅在第一次直達 files 或全域刷新。 | 每次進 files 均自行載入完整專案選項；開啟專案上傳亦刷新選項，載入／錯誤／重試獨立呈現，失敗保留舊選項。 |
| A07 | 原 computed 在 pageIssue=error 時回傳 false，隱藏整個 tabs。 | overview 請求納入獨立 section，錯誤 banner 保留各頁功能；一般錯誤／空資料不隱藏 tabs。 |
| A21 | **已動態重現反序回應**：執行實際 loadFiles + loadSection，舊篩選請求先送、新篩選先回，舊回應最後覆寫 new 為 old。 | 每個 section 的 request generation 與 current 判斷隔離更新／錯誤／loading；各表格與 sources 列表顯示獨立載入狀態。修後相同反序測試保留 new。 |
| A12 | 原 tasks tab 不消費 taskId；實際 tab 函式測試 detail 載入次數為 0。已確認後端既有 GET `/knowledge/tasks/{id}`。 | 新增該 API wrapper；taskId 打開具名詳情抽屜，無須在目前列表頁內；支援失敗重試與任務操作。兼容 dashboard 的 running/failed 狀態別名。 |
| A22 | 實際執行原業務規則導入函式，API 成功一筆＋skipped 一筆時關閉 dialog 並清空失敗檔案，回歸測試修前失敗。 | 知識文件／業務規則均顯示逐檔成功或未導入與原因，保留 dialog，僅留下未導入檔案及其名稱／路徑／上下文供重試。API 只按檔名識別 skipped，因此同批重名先要求區分，避免重送成功檔。 |
| A11 | 原 getRollbackTargetVersion 從當頁第一筆同 key 版本取得目標，沒有版本選擇。 | 新增獨立分頁歷史候選與原生 radio；排除草稿、其他規則及發布晚於來源的版本；未選不能繼續。沿用操作原因＋差異預覽＋確認，再提交明確 target id。 |
| A23/A24 | 歷史列為 click div，API 固定取 pageSize 20。 | 改為原生 button、焦點輪廓，新增 server total 與分頁；定向測試確認 page 2 請求及 total 41。 |
| A34 | 配置返頁呼叫 loadKnowledgeConfig 直接覆寫 reactive 表單。 | 記錄已保存快照，返頁／背景刷新保留未保存草稿，明示未保存；手動重新載入須確認捨棄。載入成功前停用表單，策略說明依現有執行證據撰寫，不宣稱保存會立即啟動重建。 |
| A35 | 替換版本表單可修改 projectId，但 replacement API 不提交 projectId。 | 替換模式專案唯讀並說明可經「編輯」修改，避免顯示可改卻不保存。 |

另修正資料夾導入清單的 row id：顯示與刪除都使用 relativePath/size/lastModified，避免資料夾文件移除失敗。

## 定向檢查

- `knowledgeUxRecovery.test.ts`：13 項通過，透過 TypeScript AST 抽取**生產 SFC 的函式**執行，API 使用可控 Promise；不是用正規式宣稱競態已修。包含反序請求、缺失計數、獨立載入、取消 reset、單筆 task 深連結、兩種部分匯入、候選篩選、歷史分頁與配置草稿。
- 同樣 runner 執行 `knowledgeFileDetailReuse.test.ts`、`standardCanonicalDetail.test.ts`、`noFullPageLoading.test.ts`：通過。
- 變更的 Vue 與 TS helper/test：Prettier、定向 ESLint 通過。
- `git diff --check`（本次知識庫檔與 API wrapper）：通過。
- 全量單元、型別、建置與實際元件瀏覽器驗證由主代理整合執行；此文件不把函式測試冒充完整視覺或端到端驗收。

## 未完成與限制

- A25/A26/A27 知識圖譜鍵盤替代、超限關係／metadata、選點與視野：本輪未改 KnowledgeNetwork.vue，保留原待驗證狀態。
- 對外 reset、retry、cancel、rollback、檔案導入沒有在真實環境執行；只以 API mock 驗證 UI 分支與取消不寫入。
- A34 的草稿保留覆蓋同一知識庫元件內切頁／刷新，瀏覽器重新載入或離開到另一元件仍未做持久化草稿；未宣稱解決所有 A14 離頁保護。
- 回滾歷史使用既有 keyword 分頁，再精確篩選同一 ruleKey 與曾發布狀態，頁內可能沒有候選；介面明示可看其他分頁，未自行取第一筆或修改後端查詢契約。
- 知識策略開關目前後端用途不一：autoReindex 沒找到執行消費點，故文案只承諾保存策略，未宣稱會自動觸發索引。
