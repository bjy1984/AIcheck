# 簽批結果 API 與引用一致性（2026-09-09）

實際 TestClient 路由驗證：由 evaluate_construction_plan 產生結果，保存到 rule_check_results，再透過 review-workspace 與 audit-view 取得相同檢查結果、晚批復判定、時間及引用。排除其他租戶／舊任務記錄，保存的 run／rule records 不被改寫。這是隔離記憶體測試庫及測試身份標頭，不是正式登入帳號或真實工程案件。

修復共用原文定位器：證據 ID 必須唯一，且仍須滿足引用提供的文件、版本、頁碼、原文條件；不能用相同 ID 蓋過矛盾條件。無文件／版本／證據 ID 的空引用、只有頁碼或原文，不再偶然匹配唯一證據。頁碼只接受正整數或純數字整數字串，拒絕布林、NaN、小數、零及負數。符合的舊 ID-only 引用維持可用，不創建新證據。

6 項 API／投影測試、100 個前端測試檔、vue-tsc、改動 ESLint、Ruff 289／289、monolith 及 diff 檢查通過。Chrome 原簽批元件增補相同 ID／不同版本及空引用案例，只有正確版本頁碼可開原文；不可用提示、鍵盤事件、篩選件數及深淺色截圖保留。

日誌：approval-link-integrity-http／frontend／browser，日期前綴同本檔。截圖更新於 browser/approval-checks-light.png 及 dark.png。未重新執行完整後端；最近全量仍 ec101add 的 4779 通過／75 跳過。實際登入、PDF 閱讀後返回事項、人工保存及真實案件品質仍待驗，整體未證明 90%。
