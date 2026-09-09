# 最新後端完整回歸收尾

在 Lab 分支 f18ce4b4 基礎上實跑後端 `.venv/bin/python -m pytest -q`。

- 首次：4631 passed、3 failed、75 skipped、6 warnings，138.39 秒。
- 三項失敗均在 `test_review_business_tools.py`：註冊工具數量仍是 100（現為 102）；R40 參數／結論工具被歸入通用 profile 的成功案例。
- 修正：同步明確工具總數；兩個工具依既有專用業務測試驗收，另新增 runtime dispatch 回歸，確認傳入通用 ruleChecks 仍是 evidence_insufficient、保留自身 ruleVersion 且 wholeRuleAcceptance=not_evaluated。沒有放寬工具判定。
- 針對性測試：109 passed（註冊、R40 參數與結論）。
- 修正後再次完整執行：**4634 passed、0 failed、75 skipped、6 warnings，136.02 秒；退出碼 0**。
- Ruff：289／289；monolith 檢查通過；git diff --check 通過，未提高任何基線。

日誌分別保存在本目錄 `2026-09-09-full-backend-before-registry-fix.txt`、`2026-09-09-r40-registry-tests.txt`、`2026-09-09-full-backend-verified.txt`。

本輪為一般本機後端回歸，不把 75 skipped 計成通過，也沒有重新執行先前另行驗過的 PG／MinIO／Temporal 全套服務驗收。警告涉及既有 Starlette/httpx 與 SWIG 棄用提示。全量程式測試通過不等於 69 條規則四態及真實工程驗收完成；R40 pendingCapabilities、36 試點與未發布狀態均不變。
