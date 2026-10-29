# 知識區優化驗證

已目視 **21 張原始 JPEG，覆蓋 10/10 個知識主路由**。畫面為 Chrome 1470×692；完整逐張說明、限制與檔案對應見 [manifest.json](manifest.json)。本輪沒有覆寫前次 [baseline 圖集](../../page-captures/knowledge/README.md)。

## 已確認的改善

- 非總覽頁將共用治理內容收進可展開摘要；標準、文件、任務、規則等頁的清單與操作回到首屏。失敗任務與未知狀態仍在折疊列可見。展開後治理資料仍可讀取。
- 圖譜保留 259 個節點和 294 條關係。預設呈現結構標籤，實際滾輪放大後依序切換到「结构与监检节点标签」與「详细标签」，不是只靠程式碼推斷。
- 搜尋「焊工」實際命中 3 個節點，保留一跳關係後顯示 4 節點／4 關係。點擊命中節點會更新右側完整規則說明；懸停可讀完整名稱。
- 標準原文在 Chrome 顯示 GB 50235–2010 PDF 封面及第 1/129 頁，原文另開與下載入口清楚。示例項目原文的 NOT_FOUND 則明確顯示錯誤與重新加載入口。

## 主路由與證據

| 主頁 | 截圖 |
|---|---|
| 知識庫總覽 | [overview.jpg](overview.jpg) |
| 標準規範庫 | [sources.jpg](sources.jpg)、[展開摘要](sources-summary-expanded.jpg)、[PDF 原文](sources-detail.jpg) |
| 項目文件庫 | [files.jpg](files.jpg)、[原文缺失](files-preview-error.jpg) |
| 任務中心 | [tasks.jpg](tasks.jpg) |
| 規則管理 | [rules.jpg](rules.jpg) |
| 檢索測試 | [retrieval.jpg](retrieval.jpg) |
| 推理鏈路歷史 | [reasoning.jpg](reasoning.jpg) |
| 多模型對比 | [compare.jpg](compare.jpg) |
| 知識庫配置 | [config.jpg](config.jpg) |
| 知識網絡 | [network.jpg](network.jpg)、[搜尋](network-search.jpg)、[命中詳情](network-search-detail.jpg)、[監檢層級](network-zoom-sections.jpg)、[詳細層級](network-zoom-detail-level.jpg) |

`network-zoom.jpg` 保留原檔名，但該圖只證明懸停 tooltip，不能當作縮放門檻的證據；真正縮放層級由後兩張補圖確認。新增圖譜互動後 console error 記錄為空。

## 測試與限制

集中前端檢查由主代理執行：123 個測試檔通過、型別檢查與 production 建置通過。相關回歸包含逐層圖譜標籤、一跳搜尋不遞迴擴散，以及對空 blob、偽 PDF HTML、JSON 錯誤、非 PDF 內容與過期請求的預覽防護。

預覽防護測試使用 HTTP Response→Blob fixtures 並執行真實載入 handler；它們不是每種錯誤的現場 API 回應。現場已驗證的是標準 PDF 成功與項目 NOT_FOUND。先前 IAB 白區和 Chrome 成功渲染有差異，不能據此把問題歸因為缺檔，也不能宣稱所有瀏覽器 PDF 渲染已修復。

環境為隔離記憶體 demo API，沒有連正式資料庫或外部 OCR、向量、LLM。除登入外未提交業務寫入；canonical、缺失原文及示例資料狀態未改造。寬表仍需橫向捲動；密集圖譜需搜尋、縮放或詳情閱讀，沒有宣稱所有節點能在一屏完整顯示。配置審計尚有技術標籤，圖譜搜尋也不會自動切換已選節點，這些保留為後續改善項。
