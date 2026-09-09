# 交接狀態跨程序刷新

## 實測與修正

在本機 PostgreSQL 的臨時隔離資料庫建立有效交接依賴；啟動另一個 Python 程序透過独立連線提交來源 inputHash 更新或刪除交接，讀取端不重啟。

首次測試：修改來源通過，但刪除最後一筆交接仍被視為 current。探針只比較現存集合，並在全域最大 updated_at 不變時跳過。

修正：兩個交接狀態 GET 入口主動增量刷新 review_runs、review_handoffs、review_sessions、documents、versions、ocr_parse_results、fact_corrections；增量讀取包含現存 ID 比對，能移除已刪除快取。通用強制探針也會比對消失的集合，保留一般節流。

第二次實測：另一程序更新來源和刪除交接均轉為 requires_revalidation，NEXT 歷史任務保持逐欄相等。原 worker 依賴圖載入測試亦通過。臨時資料庫由 fixture 在完成後刪除，沒有操作正式資料。

## 驗證與範圍

- test_review_handoff_postgres_loading.py、test_review_handoff_node_statuses.py、test_review_handoff_api.py、test_state_freshness.py：71 passed，6 warnings，0 skipped。
- PostgreSQL 測試使用 AICHECK_TEST_POSTGRES_URL；實際執行獨立程序寫入，並非兩個假的 repository。
- Ruff 289／289，monolith 通過，沒有提高基線。
- 本輪證明 repository 跨程序更新／刪除讀取及接口回歸，不是多個 HTTP server 的端到端測試；資料庫故障時的降級、刷新性能與瀏覽器跨工程競態仍待驗。
- 工具发布、真實規則驗收及 ID 維護操作未完成，整體未證明達 90%。

完整輸出：handoff-postgres-refresh.txt。
