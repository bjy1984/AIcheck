# 交接資料刷新失敗處理

交接狀態的兩個 GET 入口共用嚴格刷新。已授權後刷新，再檢查工程權限；資料庫讀取例外回覆 HTTP 503 / REVIEW_STATE_UNAVAILABLE（50334），不回傳舊統計或資料庫錯誤細節。前端沿用既有錯誤與重試顯示。

repository.refresh_collections_incrementally 新增可選 strict=True：增量查詢失敗直接交由接口處理；尚無水位線的集合使用 load_collections_into_state 補入，避免 load_from_sync_postgres 重建其他集合。其他呼叫方保留既有預設行為。

驗證：81 passed、6 warnings、0 skip，包含真實 PostgreSQL 跨程序更新／刪除、首次載入保留其他狀態、兩個 API 的資料庫例外，以及交接／增量／探針回歸。Ruff 289／289、monolith 通過。完整輸出見 handoff-refresh-failure.txt。

界限：接口例外以故障注入驗證，未進行 PostgreSQL 斷網與恢復實機演練；瀏覽器跨工程競態、刷新性能、真實規則資料與完整發布驗收仍未完成。沒有改寫歷史任務或觸發付費審查，整體尚未證明達 90%。
