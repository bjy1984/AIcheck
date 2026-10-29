# 知識庫逐頁截圖確認

完成 10/10 路由、19 張 JPEG；每張已開圖檢視。使用 CUA IAB、production build 與隔離記憶體 demo API：`http://127.0.0.1:4178/`。正常視窗 1280×720，圖譜全屏補圖 1470×923（已退出全屏）。詳細逐圖狀態見 [manifest.json](manifest.json)。

| 路由 | 主畫面 | 補充 | 結果 |
| --- | --- | --- | --- |
| /knowledge/overview | [總覽](overview.jpg) | [索引與知識源](overview-lower.jpg) | 可讀，主要操作須向下捲動 |
| /knowledge/sources | [首屏](sources.jpg) | [列表](sources-content.jpg)、[詳情](sources-detail.jpg) | 列表正常；canonical未生成，PDF預覽白區 |
| /knowledge/files | [文件庫](files.jpg) | [詳情](files-detail.jpg) | 列表正常；原文NOT_FOUND、OCR追溯資料缺失 |
| /knowledge/tasks | [任務中心](tasks.jpg) | [失敗任務](tasks-detail.jpg) | 清楚顯示65條任務與失敗原因 |
| /knowledge/rules | [規則](rules.jpg) | — | 69條規則；主要操作可見 |
| /knowledge/retrieval | [檢索](retrieval.jpg) | — | 表單與結果空狀態正常 |
| /knowledge/network | [圖譜](network.jpg) | [全屏](network-fullscreen.jpg) | 259節點、294關係；標籤密集重疊 |
| /knowledge/reasoning | [日誌](reasoning.jpg) | [詳情](reasoning-detail.jpg) | 1條日誌；抽屜正常 |
| /knowledge/compare | [輸入](compare.jpg) | [歷史結果](compare-history.jpg) | 可讀取既有歷史比較 |
| /knowledge/config | [設定](config.jpg) | [儲存區](config-lower.jpg) | 表單、策略與保存操作正常可見 |

沒有整頁白屏、崩潰或持續錯誤遮罩。標準規範和項目文件的原文／OCR限制已保留截圖，不能以此次畫面驗證宣稱原文預覽、OCR或向量流程成功。各列表在窄於全部欄寬的視窗中採橫向捲動及固定操作欄，截圖未同時顯示全部中間欄位。

共用治理摘要佔據多數知識頁首屏，內容列表需捲動才出現；圖譜大量標籤在預設及全屏視圖仍較密集。這些列為可讀性觀察，未修改產品程式。

只執行登入與讀取型操作（詳情、歷史結果、全屏）。未提交檢索或模型對比，未上傳、儲存設定、重建、重試、取消或刪除；未存取外部服務或真實資料庫，未跑測試或commit。
