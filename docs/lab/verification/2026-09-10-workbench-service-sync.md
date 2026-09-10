# 工作台服務同步：資料保留與服務更新

## 現況（本輪查清）

- 前端 4397（vite `--mode live`）代理到 **4180**，該 API 進程啟動於 2026-09-09 09:47，對應提交 `302f47ec`。
- 4180 與 4181 兩個進程都是 `AICHECK_SQLITE_DISABLE=true` 且無資料庫連線，狀態**純在記憶體**。
- 代碼庫裡**沒有任何整體狀態匯出接口**（只有報表／證據包／標註導出）。認證在路由之前，未登入時所有路徑一律 401，無法從外部探測其路由面。

結論：這兩個進程的當日操作資料**只能留在進程內**，一重啟就沒有。所以本輪**沒有重啟它們**。

## 舊 API 缺哪些接口

不靠登入，用啟動時間對應的提交與當前代碼做 git 比對得出。`backend/apps/api/review_handoff_routes.py` 在 `302f47ec` 之後新增三條：

- `/projects/{project_id}/review-handoffs/targets`
- `/projects/{project_id}/review-runs/{run_id}/handoff-dependencies`
- `/projects/{project_id}/review-handoff-node-statuses`

當前代碼中三條均已註冊（用 `app.openapi()` 確認；注意本專案用 `_IncludedRouter` 惰性掛載，`app.routes` 看不到葉子路由，只能從 OpenAPI 讀）。功能面由 324 條交接相關回歸覆蓋。

## 本輪做法：不動舊進程，另起帶持久化的服務

`backend/scripts/run_lab_api.sh`：當前代碼 + 本機 PostgreSQL（`aicheck_lab_workbench`），預設 4186 埠，認證設定沿用原工作台（要求登入、不開發用權杖）。

```
createdb aicheck_lab_workbench
cd backend && .venv/bin/python -m scripts.migrate_backend \
  --database-url postgresql://$USER@127.0.0.1:5432/aicheck_lab_workbench
bash backend/scripts/run_lab_api.sh
```

實測：

- 起動後 `aicheck_state` 落庫 2156 行；按 collection 分佈正常（node_requirements 516、standard_clause_locators 243、project_nodes 221…）。
- **重啟驗證**：kill 進程後重新拉起，`aicheck_state` 仍為 2156 行，healthz 200。這正是舊服務做不到的——服務更新與資料保留不再互斥。

## 切換由你決定

前端指到新服務是一行環境變數：

```
VITE_API_PROXY_TARGET=http://127.0.0.1:4186 pnpm exec vite --mode live --port 4397
```

**未執行切換**。原因：4186 的資料是全新種子庫，不是 4180 記憶體裡你這一天的工程資料；切過去等於換掉當前工作資料。舊進程仍在跑，資料完好。

## 未完成

- 「在你目前使用的工作台驗證新接口」需要監檢帳號登入，本輪未代輸憑證，未執行。
- 舊進程 4180／4181 的記憶體資料無法匯出；若要保住，只能不重啟。若判定可捨棄，直接切到 4186 即可。

整體工程估算仍約 60%，本項不提高整體估值。
