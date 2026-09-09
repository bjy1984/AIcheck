# 工位交接人工核驗（Lab）

新增 POST /api/projects/{projectId}/review-handoffs/{handoffId}/verifications（亦可使用無/api前綴路由）。僅啟用工位Lab時提供，限具備review:save動作且同時有兩端節點、當前及凍結文件存取權的監檢人員。歸檔工程不可寫入。

## 請求

必須且只能提供：
- snapshotHash：正在核驗的交接草稿雜湊。
- expectedPreviousId：首次為null，其後為上次核驗ID，防止覆蓋其他核驗人的較新決定。
- subject：與v2／v3草稿完全相同的objectType／objectId／repairRound／eventId。
- outcome：verified或rejected。
- objectMatchConfirmed、evidenceSupportConfirmed：嚴格布林值。verified時均須true。
- note：非空核驗說明。

確認代表人工已核對該交接的對象／事件配對與內容證據支持，不代表整節點或工程合格。collaboration沒有引用時可人工確認協作內容；facts／judgment確認前必須可定位引用頁面。拒絕不需先取得完整頁面，但雙方來源仍須具備有效凍結指紋。v1交接與未凍結來源不能新增核驗，須先建立有明確事件及當前來源的新草稿。

reviewedByUserId、createdAt由伺服器提供，不接受客戶端偽造。Idempotency-Key沿用通用中介層；重送仍核對當前權限、草稿／来源新鮮度及最新核驗記錄，較新決定出現後拒絕返回舊確認快取。

## 保存及讀取

核驗逐筆追加於交接記錄verifications，包含草稿雜湊、subject、previousId、決定、兩項確認、說明與伺服器核驗人／時間。核驗ID為內容雜湊衍生值，讀取與追加核对連結及內容一致性；沒有改寫draft或原始任務結論。雜湊是完整性檢查，不是數位簽章或防資料庫管理者重算的背書。

單筆與列表新增verification摘要：
- unreviewed：沒有核驗。
- verified／rejected：最新核驗決定，且草稿和雙方來源仍有效。
- stale：有核驗，但任務／來源已變動或無法驗證；歷史核驗原文仍保留。
- invalid_history：核驗內容或連結校驗失敗。

authoritative保持false；此批尚未把核驗後交接供下游判定使用。核驗人明示確認與系統自動核實內容不同，不由頁碼存在推定語義支持。

## 併發與驗證範圍

單一API程序內以鎖保護expectedPreviousId核對及追加，同一版本的兩次並行提交只允許一次成功。多API程序的資料庫級CAS／鎖與PostgreSQL實機驗收尚未完成，是正式多寫入程序部署前置條件；不能把本地鎖描述為分散式併發保證。

2026-09-09：交接API／契約／巨石基線78 passed，1條相依套件棄用警告；Ruff289／289。驗證確認、追加退回、舊修訂拒絕、快取失效、來源變動、權限／字段偽造拒絕、內容竄改、單程序並行及SQLite重載留存。本批未執行完整後端。

尚待工位人工核驗介面、真實帳號瀏覽器驗收、正式下游使用、依賴圖與失效傳遞、選擇性重跑及多程序持久化併發驗收。未替任何真實交接自動添加人工背書。

## 固定版本原文與空工作區（2026-09-09）

交接讀取新增evidenceDocuments，由伺服器依已通過權限檢查的凍結版本，從版本／文件記錄解析documentId、文件名及類型，不採用引用自報的documentId。前端只接受唯一版本對應，構造帶versionId的原文URL交由既有證據對話框顯示；缺失或歧義時不回退最新版本。來源變更後仍可查看有權存取的固定原文，但人工核驗保持失效。

實際FastAPI瀏覽器聯調發現空白seed沒有review_handoffs集合，第一次保存的find_one會拋KeyError；現在相關首次讀寫入口在延遲載入後初始化空集合，未清理或覆蓋已有記錄。回歸测试以移除初始集合覆蓋首次保存。

## 集中式契約補齊

完整後端回歸發現核驗路由尚缺集中式動作映射與端點冪等包裝，並且生成OpenAPI落後於新增路由。已把verifications POST接入libs/security/actions.py的review:save及既有api.idempotent，保留來源／修訂／權限重送檢查，沒有增加豁免。依FastAPI重新匯出openapi/generated/openapi.json，包含eventId查詢參數、核驗路由與Idempotency-Key。


## v3接收任務進度相容（2026-09-09）

新建交接使用review-handoff-draft-v3。來源身份仍包含狀態、outputHash與findingDrafts；接收身份保留runId、工程／租戶／業務包／節點、inputHash、工位快照、文件版本／来源快照及有效規則，排除接收任務自己的status／outputHash／findingDrafts。因此接收任務正常執行及產生自身結果不會令交接自動失效，輸入／規則／文件／身份變動仍會。

既有v1／v2保持原本雙方完整身份校驗，不重算原ID或升級歷史記錄；v2／v3均可在來源有效時人工核驗，v1仍需重新建立有事件的新交接。本批不改inputHash本身，也不代表已建立依賴圖或完成交接輸入併入執行快照。

90項相關後端測試、87個前端測試檔案及真實API瀏覽器流程通過；瀏覽器在核驗後更新接收任務自己的進度／結果，確認交接仍有效，再驗證原有退回、來源變動及權限撤回行為。本批未重跑完整後端。
