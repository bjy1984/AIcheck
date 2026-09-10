# 整合測試首次真跑，並抓出交接來源核驗的生產 bug

## 背景：77 個測試一直在跳過

`run_tests_in_container.sh` 不設 `AICHECK_TEST_POSTGRES_URL` 時，77 個整合測試全部按「環境跳過」處理，其中包括 `tests/test_review_handoff_commit_race.py` 那三條——也就是**交接提交競態防護自己的測試**。

我在 2026-09-10 之前的兩輪回歸報過「4980 passed」「5065 passed」，那兩輪這些測試都在跳過名單裡。**沒跑過的測試不能當成通過。**

## 抓到的 bug

`libs/review_live_sources.py` 在工作流閘口用一條新的唯讀連線複查上游資料：

```python
with psycopg.connect(connection.info.dsn) as fresh:
```

psycopg 的 `connection.info.dsn` **按 libpq 的規矩把口令剝掉**。生產庫要口令認證，所以這條新連線必然 `fe_sendauth: no password supplied`，整個檢查一路拋 `IntegrationServiceError 503 HANDOFF_SOURCE_CHECK_UNAVAILABLE`。

後果：**這道防護在線上從未真正生效過**。它是 fail-closed（拋錯而不是放行），所以沒有造成錯誤放過，但等於一直沒工作。先前寫的 `libs/db/review_handoff_commit_guard.py` 依賴同一條路徑。

這個 bug 從程式碼上看不出來——`connection.info.dsn` 讀起來完全合理。它只有在測試真的對著**要口令的** PostgreSQL 跑時才會暴露。

### 修法

改用倉庫自己保存的完整 DSN，解析順序與 `repository.configure_sync_postgres` 一致：

```python
dsn = (getattr(repository, "postgres_dsn", None)
       or os.getenv("AICHECK_DATABASE_URL")
       or os.getenv("DATABASE_URL"))
if not dsn:
    raise IntegrationServiceError(..., reason="HANDOFF_SOURCE_CHECK_UNAVAILABLE")
```

psycopg 這個行為寫進註解，避免再有人照原樣寫。

## 一次性測試庫

新增 `backend/scripts/start_test_postgres.sh`，把當時手動摸出來的做法固化：

- 獨立 docker 網路 `aicheck-tests-net`、**不發布端口**、資料放 tmpfs、容器 `--rm`
- 容器名與網路名都必須是 `aicheck-tests-*`，腳本自己校驗
- `run_tests_in_container.sh` 另有一道擋板：DSN 只要出現 `aicheck-postgres` 或 `aicheck-net` 就直接拒絕執行，**不可能指到生產庫**
- 預設行為不變：不設 `AICHECK_TEST_POSTGRES_URL` 時仍然按環境跳過，生產網路依舊從不掛載到測試容器

## 驗收

- 交接三檔（commit_race、postgres_loading、live_handoff_sources）**12 通過、0 跳過**
- 其餘整合測試檔 **224 通過、0 跳過、0 失敗**（87.99 秒）
- 完整回歸見本次提交記錄

## 順帶修的另一件事

`run_tests_in_container.sh` 用固定的遠端工作區且沒有互斥，並發調用會互相覆蓋源碼鏡像，造成一批與改動無關的失敗。已加 mkdir 原子鎖（macOS 沒有 flock），陳舊鎖按持有者 PID 判斷。另外給 SSH 加了連線複用——腳本每次跑開 6 條連線，密集運行時被服務端限流斷開。

我先前把這些失敗歸因到「SSH 限流」和「目錄權限」，那只是症狀。
