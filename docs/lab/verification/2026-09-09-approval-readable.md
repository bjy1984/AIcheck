# 原節點首頁的簽批結果展示（2026-09-09）

已在原 ReviewNodeOverview 接入 ReviewApprovalChecks，沿用 Vue／Element Plus 及既有 evidence 事件、原文定位解析。沒有新增另一套工作台。

API 從當前任務已保存的 AC-R11-01 工具結果投影 approvalChecks，按任務／工程／租戶／節點隔離，白名單輸出檢查碼、原判定、事件、時間和引用；不改歷史結果、發現或判定碼。沒有記錄時不增加空欄位，保留舊回傳相容。

預設看待核對，保留完整總數與查看全部。明確區分未簽名、拒絕批復、先採用後批復、清單不完整及其他不足，未知碼保守提示。引用沿用既有固定版本映射；不能定位時清楚顯示不可用，沒有捏造新證據連結。

驗證：142 項後端相關測試、100 個前端單測檔、vue-tsc、改動範圍 ESLint／Stylelint 通過，Ruff 289／289、monolith 通過。完整後端最近一次仍為前階段 ec101add 的 4779 通過／75 跳過，本階段未重跑全庫。

Chrome 實際原元件合成資料驗證：待核對／全部切換、完整件數、鍵盤 Enter 原文事件及精確版本／頁碼、不可用引用、44px 按鈕、深淺色截圖（已目視檢查）。測試頁 /e2e/lab-rules/approval-checks.html；截圖 browser/approval-checks-light.png 與 approval-checks-dark.png。這是元件瀏覽器驗收，不是已登入真實案件完整流程或實際 PDF 返回位置驗收。

仍待：真實任務完整 HTTP／原文／人工確認流程、其他專用工具的同等可讀展示及大批量事項可用性。整體未證明達 90%。
