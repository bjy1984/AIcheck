# 交接狀態錯誤分類與恢復驗收

- 交接狀態查詢沿用原工作台與 API，將登入失效、工程權限不足、接口不可用及暫時故障分開提示。查詢失敗仍保持未知，不顯示零個需重驗。
- 同時辨識 HTTP 錯誤和 HTTP 200 內的業務錯誤碼；不向使用者回顯伺服器內部錯誤文字。此查詢使用既有 silent headers，錯誤仍向呼叫端拋出並顯示行內提示，登入處理沿用攔截器。
- 原 WorkstationProjectTree 元件瀏覽器回歸：跨工程遲到回應、503、404、403、HTTP 200 業務 403／401、501、錯工程回應、卸載／重掛及成功重試全部通過，無 pageerror。使用受控 HTTP 回應和合成工程；不是原 4397 API 已恢復的證明。
- 前端單測 102 檔通過、0 失敗；修改 TypeScript 檔 ESLint 通過。vue-tsc --noEmit --skipLibCheck 通過；git diff --check 通過。
- 原 4397 所用的 4180 本機 API 是停用 SQLite 的記憶體模式，本批未重啟或清空。接口更新及保留目前資料的完整流程仍未完成。
- 整體仍約 60% 工程估算，未達 90%；無生產發布、付費模型或 ID 遷移。

命令（frontend 目錄）：`node scripts/run-unit-tests.mjs`、`node e2e/lab-rules/check-handoff-races.mjs`。
