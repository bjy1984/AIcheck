# 原工位元件瀏覽器競態驗收

以原 WorkstationProjectTree、WorkstationNodeFilter 和 useHandoffNodeStatuses 執行。新增的 e2e 入口僅供測試，不新增產品工作台。

桌面 Chrome headless，1440×1000；兩個合成工程，由 Playwright 攔截交接 GET 並控制回應順序。測試在網路请求完成且兩次動畫幀後才斷言，避免舊回應尚未抵達就誤判通過。

已通過：

- 工程 A 尚未回應時切至 B，先回 B 的 0 需重驗，再回 A 的 2 需重驗：保留 B、B 節點及 0 數量。
- 刷新回應 503：出現未核對提示，沒有 0 個需重驗的假正常統計。
- 再次刷新成功：顯示 2 個需重驗，錯誤消失。
- 最新請求回傳錯誤工程 ID：報錯，不套用外工程資料。
- 請求未完成時卸載元件，回應後重新掛載：新請求正常，沒有殘留舊統計或頁面例外。

命令：frontend 下執行 node e2e/lab-rules/check-handoff-races.mjs，使用既有 4394 隔離 Vite 服務。輸出见 handoff-browser-races.txt。

範圍：原元件 + 受控 HTTP 的瀏覽器驗收，非真實登入雙工程端到端；未覆蓋真实資料庫延遲性能。沒有新的產品 UI 或判定變更。剩餘規則、標準資料、真實業務及發布驗收仍未完成，整體未證明達 90%。
