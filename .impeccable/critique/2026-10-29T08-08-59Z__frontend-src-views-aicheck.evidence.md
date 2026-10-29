# Assessment B（獨立技術證據）

建議「前端技術成熟度」78/100，中等信心；這是評閱判斷，不是測試通過百分比，也不包含後端安全、模型判斷準確性或正式營運可用性認證。基礎工程驗證紮實；仍缺全角色無障礙、當前最終建置的手機核心流程與大型資料效能證據，所以不支持90+。

## 本次完成與證據可靠性
- 真實執行一次 bundled `/Users/big67/.codex/skills/impeccable/scripts/impeccable detect --json frontend/src/views/AICheck`，退出2（有提示）；結果完整保留 `/tmp/aicheck-score-detector.json`。target有72個markup檔，低於500限制。
- `docs/verification/role-content-focus/verification.json` 與 `manifest.json` 一致：44主路由、68張capture，分組管理13/13、知識庫10/13、FDE16/24、工作台5/18。68檔皆存在；67張1280×720、1張900×900。這是路由/畫面覆蓋，不是44條成功端到端流程，不是使用者完成率。
- 核對既有 unit-tests.txt：133測試檔通過、0失敗。runner以esbuild打包node:assert腳本，包含函式回歸及source契約斷言，不能換算為133條瀏覽器任務成功。verification記錄typecheck、production build、修改檔ESLint通過；本次不重跑。
- source-snapshot記錄654檔；本次按project-relative path + NUL + bytes + NUL重算，SHA256確實吻合 `b6d32b800687a6642a745f4f7dbf532f10753724fecefffdbd5ac36cdc3d8a45`。現存`frontend/dist-role-content-focus/index.html`雜湊吻合 `577bb1f6ea99ee9b78a6fd5a994c5767ce42c940ef845851079c9ef4b92bb79e`。這比只讀一份成功宣告更可靠。
- 既有staticOperability的641檔0發現，實為source regex規則（demo標識、固定69上限、800/900字重、假模型alias、偽action等）；不能代表WCAG、全頁操作性或使用者研究全部通過。
- 證據環境明示production build + 真實API + 隔離記憶體示例資料；未正式部署/寫入。部分原文、歷史AI對話、人工意見缺失；FDE任務中心0項；盲審未判fixture，未提交結論；保留這些限制很可信。

## Detector摘要及解讀
11項，6個檔；9 warning `side-tab`、2 advisory `codex-grid-background`。全部是視覺樣式啟發式，不是11個已確認UX defect。

代表位置（完整清單見JSON）：
- FdeConsole.vue:26663、26667：OCR標注任務橘/綠側線；23757：graph node card側線。
- FdeConsole.vue:22701：`.knowledge-chart-shell`圖譜畫布網格。
- components/OcrAnnotationCanvas.vue:721：OCR標注畫布網格。
- components/OperationTaskDrawer.vue:398、481、495：等待/失敗/阻斷提示側線。
- components/FileDetailDialog.vue:1534、WorkbenchAiReviewPanel.vue:1625、contractor/ContractorFeedbackPanel.vue:211：內容區或反饋展開側線。

已核對source context：兩個網格正用於圖譜/OCR canvas，是規則描述明示可接受的用途；不能據此扣「裝飾網格」分。任務drawer側線伴隨文字/提示，用作狀態輔助亦不構成只靠顏色的已確認問題。其餘側線只能作一致性/裝飾克制的候選項，需視覺情境；本次不把數量當故障率。

## Browser（3代表畫面）
新建隱藏IAB tab讀既有4195靜態圖集，從頁面可見link打開/讀取原尺寸證據。檢視：
1. `admin/02-projects.jpg`：有搜尋、狀態篩選、查詢、重置、刷新、分頁與文字操作。資料只有5條，不能證明長列表使用品質；操作文字在資料表中偏密，可列為後續觸控尺寸量測目標，不能僅靠JPEG宣稱低於44px。
2. `workflows/05c-generic-owner-tasks.jpg`：4任務，進度、時間、排隊/可下載/執行等文字狀態分明。長耗時來自固定歷史fixture，不能當效能問題或實際等待時間。
3. `workflows/05g-generic-navigation-900.jpg`：900px drawer導航有清晰名稱與當前狀態；證明此中窄版視圖，不證明390px手機任務閉環。
CUA evaluate明確唯讀，未測mutation、未嘗試注入、未開detector live-server；live overlay unavailable，無browser detector console結果。fallback是CLI+來源上下文+原始畫面核對。未重啟產品server。兩個本次建立的頁籤均已close，未動原有頁面。

## 已有有限證據與缺證據須分開
- 無障礙：e2e/aicheck-smoke.spec.ts含Escape、鍵盤選擇、虛擬樹、reduced-motion相關情境；workbenchResponsiveCascade.test.ts只斷言樣式順序及media query存在。它們顯示有設計/測試意識，未見當前最終建置的完整鍵盤/讀屏實測結果、焦點回復/困陷記錄、量測對比或WCAG稽核。結論是缺完整證據，不是已確認無法使用。
- 小螢幕：本輪67桌面+1張900px；上一輪uiux-optimization記錄1470/1280/900；更早uiux-priority-summary明示盲審資料抽屜390px可開原始版本，且smoke source含多個390px案例。所以不能說「完全沒做手機」，但無法宣稱所有角色/表單/長列表在本輪390px均驗收。
- 大型資料/效能：前一輪priority summary有真實元件+合成API的205筆歷史第三頁正式版驗證，這是有限的分頁正例。現有目標證據有5項project/4項task與FDE空態，未見本輪1000+列表/高密度圖譜的瀏覽器效能報告、低階裝置CPU/網路節流、INP/LCP、長任務、記憶體或API p95延遲。不可稱「沒有分頁證據」，亦不能稱「大資料效能通過」。

## 最值得補的5項驗證（均為驗證缺口，不是新增已確認bug）
1. P1：用當前最終建置做鍵盤/VoiceOver主流程，記錄table行操作、drawer/modal開關、focus trap/restore、錯誤宣告、200%縮放與實測對比。對應 `$impeccable audit`。
2. P1：390/360px覆蓋至少施工上傳/補正、監檢證據與結論、管理搜尋/編輯；檢查橫向overflow、觸控尺寸、抽屜底部操作與長中文。現有900導航和局部390資料抽屜不能替代。對應 `$impeccable adapt`。
3. P1：1k/10k記錄與長名稱/多狀態，量測搜尋、篩選、分頁、任務進度更新的p95互動延遲和memory；另測圖譜/原文頁數的高負載。對應 `$impeccable optimize`。
4. P1：有真實可讀原文/歷史回覆/人工意見/非空FDE執行資料的隔離整合環境，走完整上傳→處理→核驗→補正→報告並核對角色邊界；現有缺失提示驗證不等於正向業務閉環。對應 `$impeccable harden`。
5. P2：慢網路、API部分失敗、輪詢中斷/恢復、刷新/返回後保存與重試的瀏覽器案例，並對核心任務做真實角色可用性測試，量測完成率/耗時/錯誤數。單元/契約/截圖不能推出這些指標。對應 `$impeccable harden`。

## 建議評分用語
「前端技術成熟度78/100：工程回歸、版本可追溯與桌面角色覆蓋有紮實證據；無障礙、全流程手機和大型資料效能尚未形成足以高分背書的驗收資料。未發現足以從這11個樣式提示判定阻斷問題的依據。」
若主線需分項，建議以『驗證充分度』單獨列為72/100，勿對未知實際效能強打低分；也勿把模型準確率或使用者完成率臆造為數值。

## Run notes
- 本次獨立B，未讀A內容；A完成前只告知ready。
- 目標frontend/src/views/AICheck；target slug/ignore/持久化交主線處理。本次檢查`.impeccable/critique/ignore.md`不存在。
- CLI成功（findings exit 2）；browser背景；overlay不可用；未啟動live server所以無需stop；既有gallery保留。
- 沒有產品碼變更，沒有重跑大型測試。暫存JSON/本報告留給主線合成與歸檔後清理。
