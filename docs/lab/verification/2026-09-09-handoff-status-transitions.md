# 工位交接來源變動回歸

本輪沿用真實 API 建立交接、人工核驗和下游任務的整合測試，指定目前會話任務後查詢工位狀態。

- 有效來源：current，需重驗 0。
- 上游 inputHash 改動：requires_revalidation，需重驗 1。
- 測試中恢復原 inputHash：current，需重驗 0；這不是生產回滾操作。
- 經核驗 API 追加 rejected 決定：requires_revalidation，需重驗 1。
- 每次查詢均核對任務 ID、AI 任務數不變及下游執行快照不變。

驗證：backend/.venv/bin/python -m pytest tests/test_review_evidence_run_integration.py tests/test_review_handoff_node_statuses.py -q（在 backend 執行）；12 passed，6 warnings。Ruff 289／289，未調高基線。

證據：backend/tests/test_review_evidence_run_integration.py 的 test_real_route_uses_verified_handoff_and_rejects_changed_verification；本輪輸出見同目錄 handoff-status-transitions.txt。

範圍：本機種子資料、單程序 API 回歸；不是瀏覽器動態刷新或 PostgreSQL 多程序驗收。未使用付費模型、未發布工具、未執行 ID 遷移。上述驗收及剩餘規則／標準資料仍未完成，不能據此宣稱整體達 90%。
