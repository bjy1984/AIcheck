# 結果提交與來源同時變動的交易邊界

## 缺口

執行前有一道來源校驗閘（`libs/review_live_sources.ensure_live_document_sources`，在 `execution.py` 圖執行結束、寫結果之前調用）。它讀的是**另一條連線的只讀事務**，而結果落庫是後面**另一次事務**。兩者之間存在窗口：閘放行之後、結果寫下去之前，上游交接可能被別的程序改掉。

寫入側本來就有樂觀鎖 `assert_persistence_baseline`，但它只比對**被寫的那一行**的基線。上游交接是另一行，改它不會讓審查運行這一行的基線失配，於是依據已經過時的結論仍會作為最新結果保存。

實測重現：閘放行 → 另一條 psycopg 連線往交接記錄追加一次核驗並提交 → 本程序寫入 `waiting_human_review` 結果 → **提交成功**，過時結論成為最新結果。

## 修復

`libs/db/review_handoff_commit_guard.py`：在 `flush_to_sync_postgres` 的**同一個事務內**，用該事務的連線把交接來源再讀一遍（沿用既有的 `load_handoff_rows` 與 `ensure_document_sources`），不一致就拋 `HandoffSourceChangedDuringCommit`，整筆回滾。

範圍刻意收窄到「把結論擺到人面前」的狀態（`waiting_human_review`、`waiting_human_input`）。失敗、取消，以及記錄「來源已變、需重新核對」本身都要能寫下去——把它們一起攔掉，系統就沒法記錄自己已經過時了。

原因碼與發起前的 `REVIEW_INPUT_CHANGED_RECREATE_RUN` 分開：提交階段是結論已經算完、落庫時才發現依據過時，處置不同（應重新發起，而不是重試寫入）。

## 驗收

測試檔 `backend/tests/test_review_handoff_commit_race.py`，三條：

1. 閘通過後來源變動 → 提交被擋，庫裡那條保持原狀態，不被過時結論覆蓋，原因碼為來源變動。
2. 來源未變 → 照常提交，守衛不誤傷正常路徑。
3. 沒有交接依賴的運行 → 不進守衛。

命令（backend 目錄，需設定專用測試 PostgreSQL）：

```
AICHECK_TEST_POSTGRES_URL=<專用測試庫> .venv/bin/python -m pytest tests/test_review_handoff_commit_race.py -q
```

- 交接／審查運行／來源相關子集 324 條通過、0 失敗。
- 完整後端回歸 **4919 通過、0 失敗、4 跳過**（351.54 秒）。本機已配置 PostgreSQL，整合用例不再跳過，故總數高於先前記錄的 4835。
- Ruff 289／289，monolith 基線通過。

## 限制

合成工程資料、隔離測試庫。守衛只覆蓋 PostgreSQL 持久化路徑；記憶體／SQLite 模式沿用原有契約（那裡沒有跨程序併發）。人工確認結論（`accepted_by_human` 等）走另一條 API 路徑，其來源校驗未在本輪改動範圍內，仍待逐條核查。

整體工程估算仍約 60%，本項不提高整體估值。
