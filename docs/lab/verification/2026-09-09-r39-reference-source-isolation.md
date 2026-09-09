# R39 文件對來源隔離驗證


## 2026-09-09：R39 文件對來源隔離

- 修正聲明清單比對的來源門檻：一組文件對低可信、來源衝突或可信度格式錯誤時，只排除該組輸入，保留其他獨立可信文件對的引用差異。保留來源診斷及未完成清單，不讓剩餘項目被誤判為全部通過。
- 共用清單或成員來源不可信仍阻止整組輸入；單文件對路徑保持原門檻。節點整體 grounding 門檻不變，可能仍為證據不足，但具體子工具的不一致結果保留供核對。
- 驗證：全部 R39 測試 366 passed；新增 15 項覆盖來源可信度／衝突、獨立差異保留、順序變動、共用清單失效及不可信差異不得判失敗。Ruff 289/289、monolith 與 diff 檢查通過。合成來源測試，不代表真實案件驗收。
- 方法專項技術要求仍待補齊。本次確認庫內部分方法標準 PDF 沒有可提取文字，尚未完成逐頁原文核對；未新增技術閾值、未解除 R39 pendingCapabilities，未發布生產。

實作：`backend/libs/review_orchestrator/r39_source_validation.py`。測試：`backend/tests/test_r39_reference_source_isolation.py`；執行命令：在 backend 執行 `.venv/bin/python -m pytest -q tests/test_r39*.py`。
