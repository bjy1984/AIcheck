# 完整後端回歸與合約補齊

## 實際結果

在 55dd1f9d 執行 backend/.venv/bin/python -m pytest -q：4564 passed、1 failed、75 skipped、6 warnings，150.09 秒。完整輸出：2026-09-09-full-backend-followup.txt。

唯一失敗是 test_generated_contract_artifact_is_current，OpenAPI 工件漏了 /api/projects/{project_id}/review-handoff-node-statuses 及相容無 /api 前綴路由。按官方倉庫生成命令 python -m scripts.openapi_route_coverage --export ../openapi/generated/openapi.json 更新工件，diff 僅新增兩路由共 74 行；不是 503 錯誤碼造成的失敗。

更新後重跑 tests/test_openapi_contract.py：7 passed、5 warnings。輸出：2026-09-09-openapi-followup.txt。這是全量後定位唯一失敗並通過其全部合約回歸，未聲稱更新工件後再次執行全量。

## 範圍與仍待完成

75 skip 屬本次未設定外部服務的測試結果，不當成通過。其中交接新 PostgreSQL 測試已在先前隔離資料庫專項實跑，詳見 handoff-postgres-refresh / handoff-refresh-failure 紀錄，不能把不同回歸的數字簡單相加。

69 規則空輸入審計仍是 draft、194 原子項、36 原試點，releaseReady=false。現有靜態 handler 分類尚未辨識 R40 的 profile 專用分流；下階段需修正其分類，不代表 R40 完成業務驗收。

生成完整路由工件與手工契約片段覆蓋是兩回事；目前生成器另報手工片段覆蓋 25／426，未宣稱全 API 已有完整手工 schema。原規則／標準資料、真實案件、發布與遷移等剩餘要求保持，整體未證明達 90%。
