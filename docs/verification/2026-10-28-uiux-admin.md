# 管理後台 UI/UX 修復驗證（2026-10-28）

範圍：`AdminOverview.vue`，以及 Prompt 模板 API／執行端的生產版本保護。對照 `.impeccable/critique/2026-10-29T00-22-28Z__frontend-src.md`。沿用既有 Element Plus 介面與樣式，未部署或操作正式資料。

## 已確認及修復

| 編號 | 確認方式 | 修正後行為 |
| --- | --- | --- |
| A01 | 修前直接執行原始 `needsHeavySections` 判斷，`rule` 返回 false，回歸斷言失敗；實際頁籤 key 為 `rule` | 規則頁請求 `ruleVersions`，審查點頁請求 `materialReviewPoints`；其他頁明確請求 `core`。省略必要節時補拉，仍缺資料則顯示失敗。請求序號阻止較舊頁面覆蓋目前頁面。 |
| A02 | 原 core 回應以空陣列代表省略，但摘要照樣使用 length/0 | 未載入、載入中、失敗或被省略的規則不顯示 0 或全部發布。全域項目數使用 overview metrics；審計數清楚標為最近一次查詢的篩選範圍，未查詢顯示未取得。 |
| A03 | 核對後端 `/admin/config-overview/publish`：只寫版本登記、關聯範圍和審計，並不切換各領域生產版本 | 頁首改為「登记配置版本」；僅權限／規則頁提供真正支援的範圍選單（權限矩陣、節點模板、業務規則、流程狀態機）。原因、預覽、成功結果及詳情都說明真實效果。移除 Prompt、審查點及細項配置的錯配入口。預覽後使用同一個已捕捉的 scope 與 etag，取消不提交。 |
| A08 | 修前 FastAPI TestClient 回歸：production／已發布都可直接改寫或降級，POST 也能直接建立正式版（4 fail / 1 pass） | 生產 Prompt 在 UI 唯讀，可由列表複製為新草稿；草稿不攜帶原 ID/etag。後端拒絕修改或降級現有生產版，也拒絕以 create/update 繞過 publish。兩種正式狀態別名都保護。交叉 review 另外確認執行端在無正式候選時會取第一筆草稿或別的業務包；已改為不套用未發布模板、保留業務包內建 Prompt。 |
| A09 | 確認列表刪除 catch 僅寫入抽屜的錯誤欄位 | 抽屜關閉時，配置操作錯誤顯示在列表上方。模擬 409 刪除失敗，確認錯誤可見且未打開抽屜。 |
| A10 | 原載入／提交使用 `value || default`，0 被替換 | 兩種閾值的載入與提交保留 0；不存在或非有限數值才使用預設。瀏覽器驗證欄位顯示 0，實際 PUT payload 仍為 0。 |
| A12（admin 部分） | 搜尋目標以 `/admin/org?userId=...`／`orgId=...` 傳遞；原頁面未消費這兩個參數 | 找到目標後切到所屬頁並打開具名對話框。測試第 13 位使用者，驗證不是只處理第一頁。不存在時顯示具名錯誤；切換目標先關閉前一個對話框。 |
| A19 | 原 Prompt／報告行內發布直接呼叫 mutation | 發布前取得同業務包版本，顯示待發佈名稱、版本、ID、業務包、Prompt Key，以及被替代的正式版本；說明後續選用與既有快照界線。取消不發 mutation，確認時 reason 帶具名版本。完整讀取分頁歷史再確認，超過 100 筆不再永久被擋；分頁重複或清單總數中途改變時要求重新確認，避免漏列替代版本。 |
| A20 | 原業務包尚未校驗即顯示可用；聯調失敗仍以初始 blockers=0 顯示可推進 | 統一未檢查、檢查中、失敗、通過／有錯誤狀態。聯調失敗時摘要數值也不顯示為真實 0。流程狀態機標題原本固定顯示綠色啟用，改為可驗證的配置數量。業務包校驗失敗使用錯誤提示。 |

## 自動驗證

- `backend/.venv/bin/python -m pytest tests/test_admin_prompt_safety.py -q`（cwd `backend`）：原 API 5 項通過，新增 runtime 10 項後共 15 項通過。原 API 修前為 4 failed、1 passed；runtime 的 4 種未發布狀態與跨業務包回退，修前 5 項全部失敗，確實重現原本風險。
- 加入執行端保護後，`test_admin_prompt_safety.py`、`test_review_fix_jev_prompt_hint.py`、`test_review_page_grounding.py` 合併執行：25 passed。覆蓋無正式候選時預設 Prompt、安全模板選擇、既有 Prompt builder／證據行為。
- 既有 contract 測試：`test_prompt_template_management_api_and_audit_metadata`、`test_admin_config_diff_export_publish_and_project_members`、`test_report_template_management_publish_and_report_generation_snapshot`，共 3 passed。涵蓋草稿編輯、發布、冪等性／etag 既有契約、配置登記、報告快照。
- `frontend/node_modules/.bin/tsx frontend/src/views/AICheck/adminOverviewSections.test.ts`：通過。測試實際被畫面採用的策略函式，涵蓋載入分節／補拉、未知狀態、0 閾值、複製草稿、正式狀態別名、發布替代範圍、登記範圍與跨頁定位。
- 對 `AdminOverview.vue`、`adminOperationPolicy.ts`、`adminOverviewSections.test.ts` 執行 ESLint：通過。
- 一次全量 vue-tsc 未報 AdminOverview 或 helper 錯誤；當時其他 agent 編輯中的 FDE／Workbench 仍有 4 個錯誤。最終全量型別驗證由主代理統一進行。
- `git diff --check`（本次所有既有變更檔案）：通過。

## 真實元件瀏覽器回歸

`frontend/e2e/admin-usability/` 直接掛載正式 `AdminOverview.vue`、Vue Router 及 Element Plus；僅登入狀態與 HTTP transport 為測試替身。所有 API 都由 Playwright 攔截並回傳合成資料，不會連正式後端。獨立 Vite port 4491 與 cache，避免與其他驗證互相影響。

執行：

```sh
# cwd: frontend，持續執行的測試服務
node_modules/.bin/vite --config e2e/admin-usability/vite.config.ts
# 另一終端，cwd: repository root
node frontend/e2e/admin-usability/check.mjs
```

驗收包含：規則真實請求參數／表格、未知摘要、未驗證業務包、聯調錯誤後重試、正式 Prompt 禁止輸入與無保存入口、複製草稿的 POST body、具名 Prompt／報告替代確認、取消不發佈、確認發布目標、使用者第二頁／組織深連結、刪除失敗列表錯誤、0 閾值 PUT body，以及配置登記預覽／取消。Prompt／報告各使用 205 筆歷史資料，正式版位於第三頁；確認訊息必須列出該正式版，並斷言真實 handler 請求過第三頁。

瀏覽器全部互動回歸通過，沒有未捕捉的瀏覽器錯誤；桌面截圖為 `/tmp/aicheck-admin-ui/rules.png`。合成失敗路徑刻意回傳 HTTP 500／409，不代表未捕捉的應用程式例外。

## 邊界與後續

- 本文只記錄 admin 責任範圍。A12 的 knowledge／workbench 目標定位由各模組負責，不據此宣稱整項全部完成。
- 未聲稱設定版本登記會啟用執行時配置；後端原有 metadata 登記行為保持，僅修正警告文案。
- 本輪不包含 A13–A18 的完整排序、搜尋、表單草稿保護、選擇器或報告視覺預覽，以及 A28–A33 的其他流程；它們屬後續批次。
- 瀏覽器驗證是桌面 1440 × 1080 合成資料；正式環境權限、超過 205 筆的大量版本、手機／200% 縮放及完整讀屏路徑未由這組測試涵蓋。
