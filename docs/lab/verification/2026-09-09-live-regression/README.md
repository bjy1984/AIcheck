# 本機三服務回歸

- 後端：4128 passed、1 skipped、6 warnings；332.30秒。前端91個測試文件通過，vue-tsc退出0。
- PostgreSQL16.10、pgvector0.8.5：AICHECK_TEST_POSTGRES_URL指向專用aicheck_codex_verify_fd4057e8ed，每測試再建立獨立資料庫並清理。
- MinIO使用127.0.0.1:19000與獨立/tmp/aicheck-minio-verify.CUqQSD；首輪與重啟後原版本驗收均通過。完整回歸設定AICHECK_TEST_MINIO_BUCKET_PREFIX=aicheck-verify-cuqqsd。
- AICHECK_TEST_TEMPORAL_LIVE=true，測試建立真實本機Temporal開發服務；活動使用確定性替身，不呼叫模型。
- 唯一跳過：AICHECK_CNSE_LIVE未開啟，未對真人證書資料發出外部查詢。
- 此紀錄證明本機程式／服務回歸，不代表生產部署驗收或69條規則業務驗收。
