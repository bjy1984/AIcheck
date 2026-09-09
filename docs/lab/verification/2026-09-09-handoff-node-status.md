# 跨節點交接需重驗查詢

新增GET /api/projects/{project_id}/review-handoff-node-statuses。僅開啟工位功能且有工程／節點權限的監檢人員可讀；每個授權節點依原工作台的active_review_session與latest_review_run_for_node選取目前任務。

返回items中的nodeId、可讀reviewRunId、status及requiresRevalidation，另有requiresRevalidationCount、unavailableCount、automaticRerun=false與historicalResultsPreserved=true。無任務／無使用交接為not_used。失效來源為requires_revalidation；來源無權查看或結構無法核對為unavailable／null，該項不返回run ID、文件或來源細節，不能視為「沒有需重驗」。

既有單任務handoff-dependencies與新查詢共用權限和依賴檢查，補載OCR parse與人工修正集合，仍沿用現有文件／版本／來源校驗。不寫入資料或自動觸發模型。

新增7項API測試，覆蓋目前會話取代舊任務、授權節點過濾、無權文件資訊不洩漏、失效快照一次計數、無交接、角色及功能開關。[63項交接API和既有執行整合回歸通過](2026-09-09-handoff-node-status-tests.txt)。Ruff289/289、monolith與diff通過。

本批為接口階段；原工位UI尚未接入，尚無本批實際瀏覽器與PostgreSQL多程序驗收。原單任務能力保持，交接統計完整交付與69條驗收仍未完成。
