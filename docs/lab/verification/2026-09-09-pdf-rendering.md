# 固定版本PDF：恢復、顯示與翻頁驗收

正常監檢登入隔離服務4401／4184，使用三頁實體PDF合成案例。舊版DV-EDE08A95-V1寫FIXED OLD VERSION；同文件currentVersionId指向-NEW新版，內容寫NEW VERSION。交接引用仍是舊版第1頁。

## 發現與修正

原生iframe在內嵌瀏覽器中無法顯示已成功讀取的PDF，實際截圖空白。因此在既有EvidenceLocatorDialog內加入延遲載入的PDF.js頁面渲染，固定依賴pdfjs-dist 6.3.289，worker由Vite打包，無第三方文件上傳。頁面元件提供上一頁、下一頁及回引用頁；文件切換／關閉取消載入及渲染，錯誤不回退其他頁。

API仍走原來指定versionId的原文入口、權限與Blob錯誤檢查，不改業務結論及任務快照。此批先接證據定位器，文件選取器其他既有iframe尚需統一驗收。

實作參考Mozilla官方範例：https://mozilla.github.io/pdf.js/examples/index.html 。

## 實機操作

1. 暫移舊版實體文件，新版存在且為currentVersionId。交接查看原文顯示舊版不可用，沒有讀新版。
2. 恢復舊版實體文件，原視窗點重新讀取。截圖可讀FIXED OLD VERSION - ORIGINAL EVIDENCE和PAGE 1 / 3，versionId仍舊版。
3. 下一頁顯示第2/3頁，點回到引用頁返回第1/3頁。
4. PDF.js接入後再次實際執行缺失→恢復→重試，不需關窗或重建審查即可成功看到舊版。

截圖在CUA對話工具記錄中；測試PDF位於忽略目錄tmp/original-recovery-acceptance/。沒有模型執行或真實人工核驗。

## 邊界

這是實體PDF的合成內容，並非真實工程文件驗收。中文特殊字型／CMap、掃描PDF、大文件／高解析度頁面、文字可選與完整無障礙仍需驗收。原生文件選取預覽仍需接入同一渲染器。不能因三頁案例通過宣稱所有PDF皆通過。

- 收尾：前端95個測試檔通過、vue-tsc通過；修改元件ESLint／Stylelint及diff檢查通過；vite build --mode base正式打包成功。worker隨應用打包。
