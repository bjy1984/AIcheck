# 工作台逐頁截圖驗證

2026-10-29 截圖；五個主路由、主要頁籤／流程區塊，共 **35 張 JPEG，全部逐張檢視**。本輪只讀驗證，沒有修改產品碼、提交、部署、上傳檔案或呼叫模型。

使用 CUA 操作 Chrome，沿用既有 **1470 × 692** 視窗，未改 viewport。真實 production build 與真實 API 在隔離記憶體 demo 資料上執行，沒有連外部服務或正式資料庫。原環境 `http://127.0.0.1:4179/`；監檢主要視圖在 `http://127.0.0.1:4183/` 重驗。新環境啟用工位功能並只放行記憶體空會話初始化，其他業務寫入仍拒絕。

## 主路由覆蓋

| 路由 | 帳號角色 | 首頁截圖 | 主要內部視圖 |
|---|---|---|---|
| `/#/workbench/generic` | admin | [01](01-generic-overview.jpg) | 資料要求、AI發現、證據／人工確認統計：28–29 |
| `/#/workbench/inspection` | inspection | [30](30-inspection-overview-enabled.jpg) | AI待辦結果／助手：31–32；重要節點資料／範圍／結果：33–35；節點AI／人工結論：19–21 |
| `/#/workbench/contractor` | contractor | [03](03-contractor-overview.jpg) | 切換有資料專案後檔案清單／分類指引：22–23 |
| `/#/workbench/ndt` | ndt | [04](04-ndt-overview.jpg) | 檔案列表、報告抽屜、反饋表單、資料上傳抽屜：24–27 |
| `/#/workbench/owner` | owner | [05](05-owner-overview.jpg) | 節點／審查鏈路、時間線、報告歸檔／詳情：06–09；共用搜尋、文件頁籤、待辦訊息：10–15 |

## 視覺判定與限制

- 五個主路由皆能顯示主要內容，未發現整頁空白、阻擋閱讀的覆蓋或重疊。此結果只涵蓋上述桌面尺寸與 demo 狀態。
- 通用審查兩張並排表格的右側欄位被裁切、需橫向捲動，發現標題省略；證據／人工確認導覽只定位統計卡，沒有逐筆辦理入口。`EvidenceRef`、`compliance_audit` 等技術詞直接呈現（28–29）。
- 檔案歷史與施工方長表格需橫向捲動；施工方分類指引單行省略，完整內容依賴逐列 hover（13、22–23）。歸檔類型 `evidence` 在窄欄拆為兩行（08）。
- demo 有語意／資料口徑不一致：通用合規專案顯示業務類型「長輸管道」；owner 摘要 V0.8 但報告版本列表為空；contractor 檔案需補正1但意見清單0；NDT結構化底片／報告數量與原子檔案列表不同。保留證據，**不能僅由此斷言正式資料有相同問題**。
- 初次監檢環境沒有啟用工位功能，交接提示「暂时无法核对交接状态，请重新核对；这不代表没有需重验节点。」；AI空會話初始化被只讀防護回應403；重要節點提示功能未啟用。環境補齊後30–35已重拍，問題消失。02、16–18僅保留為前置條件證據，主驗證採用替代圖。
- 搜尋鋼管文件後實際開啟相應文件詳情（10→11），不是只跳到節點。mock原文URL及缺少OCR parse result均有明確警告，沒有把不可預覽偽裝成可用（11–13）。
- 未窮盡所有彈窗、每一筆資料及手機尺寸。報告清單沒有可編輯版本、contractor沒有可開啟補正單，故報告保存失敗保稿、補正新增附件等功能仍依賴既有可執行單元測試，不能聲稱由本輪截圖完成端對端驗證。

## 每張截圖

`manifest.json` 保存每張完整路由、標題、專案、載入狀態、視覺判定、限制與替代關係。以下載入狀態為觀察結果，不等同所有操作已通過。

| 圖片 | 路由／頁籤 | 載入狀態 | 視覺判定與限制 |
|---|---|---|---|
| [01-generic-overview.jpg](01-generic-overview.jpg) | `/workbench/generic`<br>通用資料審查總覽 | loaded | 原有文字混用 EvidenceRef；人工確認區僅數量，未見辦理入口 |
| [02-inspection-overview.jpg](02-inspection-overview.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=list`<br>完整工作台／項目總覽 | loaded-with-warning（已由 30 替代） | 左側交接狀態無法核對；總覽資料表可用，已提交審查資料為0 |
| [03-contractor-overview.jpg](03-contractor-overview.jpg) | `/workbench/contractor`<br>施工資料摘要、上傳與監檢意見 | loaded-empty | 預設廣東LNG示範項目沒有文件／監檢意見，後續切有資料項目確認 |
| [04-ndt-overview.jpg](04-ndt-overview.jpg) | `/workbench/ndt`<br>無損檢測資料庫首頁 | loaded | 畫面最終為底片2、檢測紀錄1、報告2、待補正1；已上傳原子資料文件為0，兩組統計口徑需區分 |
| [05-owner-overview.jpg](05-owner-overview.jpg) | `/workbench/owner`<br>建設方唯讀總覽 | loaded | 唯讀提示與節點上下文清楚；總覽統計0與另有歸檔資料，屬示範資料口徑待確認。 |
| [06-owner-node-chain.jpg](06-owner-node-chain.jpg) | `/workbench/owner`<br>節點狀態與審查鏈路 | loaded | 未見重疊；表格文字密集，原有審查鏈路含泛用說明 |
| [07-owner-report-archive.jpg](07-owner-report-archive.jpg) | `/workbench/owner`<br>報告與歸檔列表 | loaded-partial | 報告版本列表為空，但上方靜態摘要顯示V0.8；歸檔列有資料，需留意示範摘要與列表口徑 |
| [08-owner-archive-files.jpg](08-owner-archive-files.jpg) | `/workbench/owner`<br>歸檔檔案與唯讀摘要 | loaded | 歸檔檔案可見；類型用 report/evidence 英文，evidence 在窄欄被拆成兩行 |
| [09-owner-archive-detail.jpg](09-owner-archive-detail.jpg) | `/workbench/owner`<br>歸檔資料詳情抽屜 | loaded | 詳情、預覽/下載入口與導出任務清楚；示範檔案不驗證實際下載內容 |
| [10-shared-project-search.jpg](10-shared-project-search.jpg) | `/workbench/owner`<br>目前項目搜尋／文件結果 | loaded | 搜尋範圍明示正確；結果類型仍顯示document技術值 |
| [11-shared-file-evidence.jpg](11-shared-file-evidence.jpg) | `/workbench/owner`<br>文件詳情／OCR欄位 | loaded-with-demo-limit | 搜尋確實開到鋼管文件；原文是mock URL，預覽禁用並顯示原因，OCR缺parse result警告可見 |
| [12-shared-file-metadata.jpg](12-shared-file-metadata.jpg) | `/workbench/owner`<br>文件詳情／文件資訊 | loaded | 文件資訊表可讀；較下方列需捲動；原文預覽仍受示範mock限制。 |
| [13-shared-file-history.jpg](13-shared-file-history.jpg) | `/workbench/owner`<br>文件詳情／歷史版本 | loaded | 歷史版本V2可見；右側日期／操作欄需橫向捲動，原文仍為mock地址。 |
| [14-shared-todos-empty.jpg](14-shared-todos-empty.jpg) | `/workbench/owner`<br>待辦頁籤／唯讀角色空狀態 | loaded-empty | 唯讀建設方沒有待辦，空狀態與數量一致 |
| [15-shared-messages.jpg](15-shared-messages.jpg) | `/workbench/owner`<br>訊息頁籤 | loaded | 兩條示範訊息顯示，未點標記已讀或其他寫入操作 |
| [16-inspection-ai-overview.jpg](16-inspection-ai-overview.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=ai&nodeId=24&auditItem=ai_review`<br>AI審查／待辦與結果 | loaded-readonly-api-limit（已由 31 替代） | 自動初始化接口遭隔離服務403；已保存結論仍顯示，未發起審查 |
| [17-inspection-ai-assistant.jpg](17-inspection-ai-assistant.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=ai&nodeId=24&auditItem=ai_review`<br>AI審查／追問助手與紀錄 | loaded-readonly-api-limit（已由 32 替代） | 會話初始化被只讀服務阻擋，未發送訊息 |
| [18-inspection-important-nodes.jpg](18-inspection-important-nodes.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=important&nodeId=24&auditItem=ai_review`<br>重要節點審查 | loaded-feature-disabled（已由 33 替代） | 實際載入5份資料；提示「当前环境尚未开启指定资料审查，请管理员启用工位审查配置。」分析按鈕停用。 |
| [19-inspection-node-ai.jpg](19-inspection-node-ai.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=list&nodeId=24&auditItem=ai_review`<br>完整工作台／節點 AI 複核 | loaded | 節點上下文、審查狀態與必傳資料缺項清楚；AI詳細結果見20，未發起複核。 |
| [20-inspection-manual-review.jpg](20-inspection-manual-review.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=list&nodeId=24&auditItem=human_review`<br>完整工作台／人工結論 | loaded | 切至人工結論時保留AI結果區；證據不足與AI非正式結論標籤可見；表單另見21。 |
| [21-inspection-manual-form.jpg](21-inspection-manual-form.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=list&nodeId=24&auditItem=human_review`<br>人工審查表單 | loaded | 正式結論阻斷與證據不足說明明確，未輸入或提交 |
| [22-contractor-files.jpg](22-contractor-files.jpg) | `/workbench/contractor`<br>施工方／審查意見與上傳資料 | loaded | 3份資料載入，需補正1但意見清單0，示範資料關聯不足；表格需橫向捲動 |
| [23-contractor-guide.jpg](23-contractor-guide.jpg) | `/workbench/contractor`<br>施工方／資料分類指引 | loaded | 10類資料均顯示，但建議資料與提示單行省略；hover提示有長文，仍需逐列查看。 |
| [24-ndt-files-feedback.jpg](24-ndt-files-feedback.jpg) | `/workbench/ndt`<br>無損檢測／已上傳資料與監檢反饋 | loaded-demo-gap | 已上傳資料列表空狀態可見；摘要底片與報告屬另一組結構化記錄，反饋表單見26。 |
| [25-ndt-report-upload.jpg](25-ndt-report-upload.jpg) | `/workbench/ndt`<br>無損檢測／報告上傳抽屜 | loaded | 報告主要必填欄位與底片選項可讀；文件選擇與提交按鈕位於抽屜下方，未選文件或上傳。 |
| [26-ndt-feedback-form.jpg](26-ndt-feedback-form.jpg) | `/workbench/ndt`<br>無損檢測／補正反饋 | loaded | 待處理項、下拉選擇與說明可見；未提交反饋 |
| [27-ndt-material-upload.jpg](27-ndt-material-upload.jpg) | `/workbench/ndt`<br>無損檢測／資料上傳抽屜 | loaded | 資料類型與適用業務規則可調整，未選擇文件或上傳 |
| [28-generic-requirements-findings.jpg](28-generic-requirements-findings.jpg) | `/workbench/generic`<br>通用審查／資料要求與AI發現 | loaded | 8節點與1發現可見；兩個並排表格最右欄部分被裁切，發現長標題省略，無逐筆證據／人工確認操作。 |
| [29-generic-evidence-human.jpg](29-generic-evidence-human.jpg) | `/workbench/generic`<br>通用審查／證據鏈路與人工確認 | loaded | 導覽定位統計卡；EvidenceRef技術詞直接呈現，人工確認0與發現區待確認標題混用；兩側表格需橫向捲動。 |
| [30-inspection-overview-enabled.jpg](30-inspection-overview-enabled.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=list`<br>監檢總覽／工位功能啟用 | loaded | 隔離環境已啟用工位功能，交接計數取代先前warning；未執行業務操作 |
| [31-inspection-ai-enabled.jpg](31-inspection-ai-enabled.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=ai&nodeId=24&auditItem=ai_review`<br>AI審查／正常初始化 | loaded | 無403；就緒檢查與未發起狀態顯示，沒有呼叫模型 |
| [32-inspection-assistant-enabled.jpg](32-inspection-assistant-enabled.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=ai&nodeId=24&auditItem=ai_review`<br>AI審查／追問助手與紀錄正常初始化 | loaded | 空會話初始化成功，快捷提問及輸入區可見；未發送 |
| [33-inspection-important-enabled.jpg](33-inspection-important-enabled.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=important&nodeId=24&auditItem=ai_review`<br>重要節點審查／工位功能啟用 | loaded | 5份工程資料載入，feature-disabled提示已消失；未勾選或發起分析 |
| [34-inspection-important-scope.jpg](34-inspection-important-scope.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=important&nodeId=24&auditItem=ai_review`<br>重要節點審查／選擇範圍與結果 | loaded | 三組節點範圍可讀，但設計文件較長造成右側大面積留白；開始審查因未選資料／節點停用。 |
| [35-inspection-important-results.jpg](35-inspection-important-results.jpg) | `/workbench/inspection?projectId=P-2026-HDCP-001&view=important&nodeId=24&auditItem=ai_review`<br>重要節點審查／結果空狀態 | loaded-empty | 尚未開始審查，先選資料並確認範圍提示清楚；未發起審查 |
