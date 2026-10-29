# 知識區後續 UI/UX 驗證

最終建置：`dist-uiux-followup-final`。Chrome 1470×748，全部 **10 / 10 路由**已截圖目視，包含 16 張最終畫面及 4 張修前證據。機器可讀逐張紀錄見 [manifest.json](manifest.json)。

## 已確認並修復

| 問題 | 修前證據 | 最終證據與結果 |
| --- | --- | --- |
| 搜尋後仍顯示已不在圖中的舊節點詳情 | [修前](before-network-filter-selection.jpg) | [篩除後](final-network-filter-cleared.jpg)：詳情清除並顯示重新點選指引；不自動選其他結果。 |
| 清空搜尋後圖表舊選取外框復活 | [中間 QA](network-filter-reset-no-auto-selection.jpg) | [最終恢復全圖](final-network-reset-no-selection.jpg)：259 節點恢復，舊外框與詳情均未復活。 |
| 可見選取不應因搜尋改變被清除 | — | [可見選取保留](final-network-visible-selection-retained.jpg)：搜尋「焊工」後選「焊接（粘接）」，改搜「焊」仍保留相同詳情。 |
| 規則表依據與見證被固定操作欄擠出 | [修前](before-rules-wide-table.jpg) | [最終列表](final-rules.jpg)：項目、分類、狀態與操作同屏；[展開見證](final-rules-expanded-witness.jpg)、[版本時間](final-rules-expanded.jpg)保留完整內容。 |
| 設定頁審計結果欄不可見 | [修前](before-config-audit.jpg) | [最終配置](final-config.jpg)：時間、人員、中文操作對象與結果同屏。 |
| 審查歷史建議、狀態與時間難以同時查看 | [修前](before-reasoning-wide-table.jpg) | [最終列表](final-reasoning.jpg)同屏可讀；[詳情](final-reasoning-detail.jpg)保留模型、規則與 Prompt 版本。 |

## 寬表量測

實際 DOM 容器 / 內容寬度，單位 px：

| 頁面 | 修前 | 最終 |
| --- | --- | --- |
| 業務規則 | 1088 / 1570 | 1088 / 1088 |
| 配置審計 | 611 / 860 | 706 / 706 |
| 推理歷史 | 1088 / 1586 | 1088 / 1088 |

## 逐頁覆蓋

| 路由 | 最終截圖 |
| --- | --- |
| `/knowledge/overview` | [總覽](final-overview.jpg) |
| `/knowledge/sources` | [標準規範庫](final-sources.jpg) |
| `/knowledge/files` | [項目文件](final-files.jpg) |
| `/knowledge/tasks` | [任務中心](final-tasks.jpg) |
| `/knowledge/rules` | [業務規則](final-rules.jpg) |
| `/knowledge/retrieval` | [檢索測試](final-retrieval.jpg) |
| `/knowledge/network` | [知識網路](final-network.jpg) |
| `/knowledge/reasoning` | [推理歷史](final-reasoning.jpg) |
| `/knowledge/compare` | [模型對比](final-compare.jpg) |
| `/knowledge/config` | [配置審計](final-config.jpg) |

## 回歸檢查

- 中央整合：126 個單元測試檔通過、0 失敗；型別檢查、production build 通過；靜態操作檢查掃描 626 檔、0 發現。
- `knowledgeGraphLabels.test.ts`：漸進標籤、搜尋一跳關係、隱藏選取消除、可見選取保留、清空篩選不復活舊詳情。
- `knowledgeGraphSelection.test.ts`：使用真實 ECharts SVG SSR 執行 production 選取同步函數，驗證篩除再恢復不殘留 selectedMap、有效選取保留、zoom / center 不被重設。
- `knowledgeGraphDisplay.test.ts`、`knowledgeGraphLayout.test.ts` 及 `knowledgeUxRecovery.test.ts` 的 13 項恢復/競態行為通過；修改檔 ESLint 通過。

## 中間 QA 與限制

中間建置 `dist-uiux-followup` 的圖片保留作為發現外框殘留的證據，但不列入最終 manifest / coverage。根因是 ECharts 單選模式的 `unselect` 省略 `dataIndex` 不會清掉已選節點；最終版明確傳入當前圖表節點索引，再同步有效選取。

本輪使用隔離 demo API，未呼叫外部模型、未寫入正式資料，未執行規則發布/回滾、重建或重試任務。規則長內容需要在表格內垂直捲讀；標準規範庫與項目文件的既有多欄表仍需水平捲動查看低頻欄位，列為後續候選，未擴大本輪修改範圍。

PDF 真實渲染與缺原文回退沿用前輪 `uiux-optimization/knowledge` 的獨立證據：Chrome 可顯示 GB50235 封面；IAB 白區屬瀏覽器差異，項目原文缺檔有明確回退。本輪未宣稱補齊缺失檔案，也未將瀏覽器差異視為渲染已全面修復。
