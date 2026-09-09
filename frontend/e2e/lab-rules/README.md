# Lab rule editor browser integration

This local-only harness mounts the real Vue editor and calls real FastAPI routes through TestClient with isolated in-memory seed data. Only authentication transport is substituted with a seeded inspection member. It is not production-login acceptance or external-service verification.

Run from the repository root in separate terminals:

```sh
PYTHONPATH=backend backend/.venv/bin/python frontend/e2e/lab-rules/backend.py
```

```sh
cd frontend
./node_modules/.bin/vite --config e2e/lab-rules/vite.config.ts
```

```sh
cd frontend
node e2e/lab-rules/check.mjs
```

Requires installed Google Chrome. Uses a fresh temporary browser profile; does not access existing browser sessions. Servers bind loopback ports 4174 and 4393. Stop both servers after testing. Do not expose the test bridge to a network or deploy it.

The script checks platform read-only behavior, creating and saving a numeric condition, failing/passing/missing-evidence trials, clearing stale results, disabling trials for unsaved edits, and retaining unsaved text after canceling close. It fails on browser runtime errors. The screenshot is written to `docs/lab/verification/browser/rule-trial-pass.png`.

Workbench CSS comparison (from `frontend`):

```sh
node e2e/lab-rules/check-workbench-css.mjs
```

Uses installed Chrome to compare the workbench CSS against commit `4cac73d1` at
1200px / 1600px and both reduced-motion settings. An optional first argument
selects another baseline commit. Transitions are disabled during measurement so
intermediate layout animation values do not cause false differences. This is a
CSS regression probe, not a logged-in workbench acceptance test.


文件選取元件驗收：啟動同一組本地 API／Vite 後，在 frontend 執行 `node e2e/lab-rules/check-documents.mjs`。入口 `/e2e/lab-rules/documents.html` 使用真實文件列表／詳情 API；驗證搜尋、跨頁保留、空殼禁止選取、取消、載入失敗保留、批選、模式、節點重設及恢復預設。測試版本的 hash／isCurrent 為記憶體夾具，不代表檔案內容驗收；預覽僅驗證不支援格式提示。

保存掛載驗收：同一組本地服務執行 `node e2e/lab-rules/check-document-bindings.mjs`。檢查固定版本、補充掛載、保存後遺失回應的冪等重試，以及寫入回應途中切換節點。測試橋接關閉嚴格 If-Match，不能取代生產並行編輯驗收。

掛載腳本亦驗證整頁重新載入後重新選取相同版本，使用新操作編號仍沿用原掛載 ID；不代表多服務程序並行寫入驗收。

歷史版本驗收：`node e2e/lab-rules/check-document-versions.mjs`。使用真實版本列表／original API 與臨時 PNG 夾具，驗證固定舊版、圖片解碼、空本體停用、原文缺失提示及保存保留。橋接按真實 Content-Type 傳回 Blob；不代表 PDF、完整登入或大型檔案驗收。

PDF／窄螢幕：`node e2e/lab-rules/check-version-pdf-mobile.mjs`。以 1280px／390px Chrome 視窗驗證真實兩頁 PDF 的 Blob、內建閱讀器頁數及選取保存。依賴測試環境 PyMuPDF 產生臨時 PDF；Chrome 內建閱讀器 DOM 改版可能需調整檢查。此為視窗模擬，不是實體手機 Safari 驗收。

交接核驗元件：使用同一個 Vite 設定、指定獨立測試埠：
```sh
./node_modules/.bin/vite --config e2e/lab-rules/vite.config.ts --port 4394
node e2e/lab-rules/check-handoffs.mjs
```
此腳本以 Playwright 模擬交接 API 回應，不需啟動後端橋接。驗證確認必填、追加退回的前版ID、核驗人欄位不由客戶端傳入、歷史內容、過期停用、提交錯誤保留意見及停用再次提交、切換任務後忽略延遲回應、390px／1280px無水平溢出與瀏覽器無runtime error。畫面保存於 docs/lab/verification/browser/handoff-review-*.png。這是隔離元件驗收；真實登入工作台、兩端權限、PDF原文預覽與完整API聯合驗收仍需另跑。

交接真實API聯合驗收（每輪需重新啟動後端橋接以恢復合成資料／權限）：

```sh
# 倉庫根目錄
PYTHONPATH=backend backend/.venv/bin/python frontend/e2e/lab-rules/backend.py
# frontend，另一個終端
./node_modules/.bin/vite --config e2e/lab-rules/vite.config.ts --port 4394
# frontend
node e2e/lab-rules/check-handoffs-live.mjs
```

此腳本不攔截或偽造API回應，透過loopback橋接呼叫實際FastAPI／權限／快照／核驗路由；只有認證傳輸替換為記憶體seed監檢身份。使用臨時合成PDF和OCR，建立帶事件的facts交接，驗證固定版本原文API的PDF內容、既有證據對話框Blob／頁碼、人工確認與追加退回、歷史保留、OCR來源變更後失效及移除來源節點權限後列表／詳情拒絕。來源變更後原文仍可按權限查看，核驗操作停用。

handoff_seed.py與 /__lab/handoff/* 控制路徑僅存在於此測試橋接，不註冊於正式應用路由；Vite測試設定代理到loopback4174。不得部署或對外暴露測試橋接。腳本會修改此合成案例的OCR及seed成員節點權限，因此再次執行前必須重啟橋接。截圖：docs/lab/verification/browser/handoff-live-stale.png。這不是生產登入、真實監檢資料、資料庫跨程序或完整工作台驗收。

交接真實API腳本亦驗證v3：人工確認後更新接收任務status／outputHash／findingDrafts不使交接失效；來源變動仍失效。此控制僅修改測試橋接的合成任務，未實際排程AI執行。

### main UI復用：共用節點工具區

在frontend目錄啟動既有Vite harness（4394），另開終端執行：

```sh
node node_modules/vite/bin/vite.js --config e2e/lab-rules/vite.config.ts --port 4394
node e2e/lab-rules/check-workstation-tools.mjs
node e2e/lab-rules/check-workbench-css.mjs origin/main
```

workstation-tools.html掛載真實共用工具區及三個子元件，API由測試腳本模擬，無需啟動4174橋接。涵蓋鍵盤操作、工程／任務參數、切換上下文、權限與無任務狀態、390／900橫向／1280與深淺色截圖；不是完整登入工作台的業務驗收。僅攔截/api/projects/業務請求，不攔截Vite的src/api模組。


結果卡閱讀驗收：以同一 Vite 配置啟動於4394後，執行 `node e2e/lab-rules/check-readable-results.mjs`。readable-results.html 使用真實結果／Markdown元件和合成資料，不連業務API；覆蓋完整發現、長文、引用事件、收合、狀態與深淺色，截圖存 docs/lab/verification/browser/readable-results-*.png。


結果優先工作台原型：同一 Vite 配置以4394啟動後開啟 `/e2e/lab-rules/workstation-overview.html`；`node e2e/lab-rules/check-workstation-overview.mjs` 驗證六態、待核對／全部、原有工具入口、inline與彈窗、指定版本請求及版本切換、原文不可用、鍵盤和390／900／1440深淺色。原型入口攔截列表為合成資料並拒絕寫入；原文GET由測試攔截。這不是完整登入工作台或服務實機驗收。
