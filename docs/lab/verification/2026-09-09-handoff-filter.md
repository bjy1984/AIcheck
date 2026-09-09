# 原工位的交接需重驗與未知篩選

WorkstationProjectTree沿用原節點樹，透過useHandoffNodeStatuses取得工程狀態；新增相容handoffRevalidation展示欄位，不改node.status。WorkstationNodeFilter新增兩個獨立篩選、數量與重新核對按鈕，既有44px控制高度和語義提示保持。

API回傳新增projectId供客戶端核對。來源未知／無權、缺漏項、重複nodeId、布林與status矛盾、錯工程均不當作current或零需重驗。查詢失敗明示原因，需重驗選項改顯尚未核對且停用；原節點及已存審查結果保留。每次重新查詢與工程切換使舊generation失效，卸載後不寫入回應。

驗證：

- [98個前端測試檔通過](2026-09-09-handoff-filter-tests.txt)，新增投影／原判定保留／工位篩選／錯工程／缺漏／重複與矛盾結果測試。
- vue-tsc --noEmit --skipLibCheck通過。
- [58項交接接口測試通過](2026-09-09-handoff-filter-api-tests.txt)。diff通過。
- 已登入原4395工作台讀取DOM：出現「暂时无法核对交接状态，请重新核对；这不代表没有需重验节点。」及重新核對按鈕，原列表維持69/69。當前4180服務程序尚未載入新接口，這是錯誤顯示驗收，尚非正常回傳流程驗收。

待用更新後隔離測試服務驗收需重驗／未知的實機篩選、工程切換與多程序資料新鮮度。沒有付費模型或歷史結論修改，整體交付與69條驗收仍未完成。
