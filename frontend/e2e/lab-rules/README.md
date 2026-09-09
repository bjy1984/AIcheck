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
