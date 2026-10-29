# 後台逐頁截圖確認

已完成 **44/44 個後台主路由**（43種內容，overview是projects別名），另補4個帳號頁，整理 **113 張原始JPEG**，包含子視圖、詳情、對話框和調整前證據。每張已目視；[開啟可搜尋截圖圖庫](index.html)。

使用目前工作區完整production建置＋真實API，後端為隔離記憶體示例資料。管理視窗1470×748/DPR2，知識與FDE通常1280×720，工作台1470×692/DPR2；圖譜另有全屏補圖。沒有宣稱完成手機版、正式資料庫或外部服務的端到端驗收。

## 本輪確認並修復

登入會呼叫resetRouter，常駐FDE獨立路由未列入保留名單，導致「打開反饋歸因隊列／打開獨立盲審」落到404。已保留父子路由，並同時保留加入項目和規範舊連結。實際登入、點入口重驗通過；回歸測試修前117通過/1失敗，修後118通過/0失敗。修復後建置成功。主圖片為修復後；before-404僅作歷史證據。

監檢初次截圖的403與未啟用提示來自截圖環境。核對後啟用工位功能，僅放行會自動初始化的空會話端點（記憶體、不調模型），在4183重新登入重拍；舊圖以superseded標示。其餘業務寫入仍由隔離服務拒絕。

## 已確認但仍待處理的畫面問題

- **資料語意：**FDE示例評估報告沒有caseSummary.cases，畫面補成「樣本0」卻同時顯示通過率100%。已對照seed與模板，不能把未知補零。建設方歸檔摘要與列表的示例資料也有口徑差異。
- **表格可讀性：**通用工作台雙欄表格、管理細項配置與部分FDE表格在目前寬度截斷欄位或需橫向捲動；發布狀態production_approved拆行。
- **定位與導覽：**知識庫共用摘要佔據大部分首屏；管理168筆審查點缺少就地搜尋／篩選，部分使用者清單也不易定位。
- **用詞與資訊：**組織類型、FDE狀態、能力差異鍵名直接呈現內部代碼。通用工作台證據／人工確認主要是數量，逐筆辦理入口不足。
- **圖譜：**預設與全屏仍有密集標籤重疊。
- **待進一步查證：**規範整體治理缺口與部分零切片行的「正常」口徑、報告模板是否需提供派生草稿的完整流程，未僅憑截圖修改。

## 環境與資料限制

部分規範PDF預覽白區、原文NOT_FOUND、OCR parse result未提供，均留有詳情證據；目前不能宣稱原文預覽成功。沒有執行真實AI、OCR、評測、上傳、發布、改密或授權提交。空列表已確認有提示與下一步，但不能代表有資料時完整流程通過。

分組紀錄：[管理](admin/README.md) · [知識庫](knowledge/README.md) · [FDE](fde/README.md) · [工作台](workflows/README.md) · [完整逐圖JSON](manifest.json)。原始圖片未加工，圖庫可以顯示調整前的錯誤證據。

## 44個後台路由對照

| 路由 | 截圖 | 結果 |
| --- | --- | --- |
| `/admin/overview` | [项目管理（overview 別名）](admin/01-overview.jpg) | 已檢視，詳見分組限制 |
| `/admin/projects` | [项目管理](admin/02-projects.jpg) | 已檢視，詳見分組限制 |
| `/admin/org` | [组织单位](admin/03-org-organizations.jpg) | 已檢視，詳見分組限制 |
| `/admin/business-packs` | [业务类型管理](admin/04-business-packs.jpg) | 已檢視，詳見分組限制 |
| `/admin/permission` | [角色权限矩阵](admin/05-permission-matrix.jpg) | 已檢視，詳見分組限制 |
| `/admin/rules` | [AI业务规则与流程](admin/06-rules.jpg) | 已檢視，詳見分組限制 |
| `/admin/material-review-points` | [业务资料审查点](admin/07-material-review-points.jpg) | 已檢視，詳見分組限制 |
| `/admin/prompt-templates` | [Prompt 模板管理](admin/08-prompt-templates.jpg) | 已檢視，詳見分組限制 |
| `/admin/report-templates` | [报告模板管理](admin/09-report-templates.jpg) | 已檢視，詳見分組限制 |
| `/admin/fine-config` | [细项配置（待辦與消息）](admin/10-fine-config-top.jpg) | 已檢視，詳見分組限制 |
| `/admin/integration` | [联调清单](admin/11-integration.jpg) | 已檢視，詳見分組限制 |
| `/admin/skill-requests` | [Skill 请求记录](admin/12-skill-requests.jpg) | 已檢視，詳見分組限制 |
| `/admin/audit` | [审计日志](admin/13-audit.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/overview` | [知識庫總覽](knowledge/overview.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/sources` | [標準規範庫：首屏](knowledge/sources.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/files` | [項目文件知識庫](knowledge/files.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/tasks` | [OCR／向量任務中心](knowledge/tasks.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/rules` | [業務判斷規則管理](knowledge/rules.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/retrieval` | [知識檢索測試](knowledge/retrieval.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/network` | [知識網路](knowledge/network.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/reasoning` | [推理鏈路歷史](knowledge/reasoning.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/compare` | [多LLM反饋對比](knowledge/compare.jpg) | 已檢視，詳見分組限制 |
| `/knowledge/config` | [知識庫配置與審計](knowledge/config.jpg) | 已檢視，詳見分組限制 |
| `/fde/dashboard` | [治理總覽](fde/01-dashboard.jpg) | 已檢視，詳見分組限制 |
| `/fde/projects` | [項目審計](fde/02-projects.jpg) | 已檢視，詳見分組限制 |
| `/fde/ocr-quality` | [OCR 品質](fde/03-ocr-quality.jpg) | 已檢視，詳見分組限制 |
| `/fde/ai-runs` | [AI Run 追蹤](fde/04-ai-runs.jpg) | 已檢視，詳見分組限制 |
| `/fde/review-runs` | [審查編排](fde/05-review-runs.jpg) | 已檢視，詳見分組限制 |
| `/fde/feedback` | [回饋樣本](fde/06-feedback.jpg) | 已檢視，詳見分組限制 |
| `/fde/evaluation` | [評估實驗室](fde/07-evaluation.jpg) | 已檢視，詳見分組限制 |
| `/fde/business-packs` | [業務包](fde/08-business-packs.jpg) | 已檢視，詳見分組限制 |
| `/fde/capability-bundles` | [能力組合](fde/09-capability-bundles.jpg) | 已檢視，詳見分組限制 |
| `/fde/releases` | [發布治理](fde/10-releases.jpg) | 已檢視，詳見分組限制 |
| `/fde/security` | [資料安全](fde/11-security.jpg) | 已檢視，詳見分組限制 |
| `/fde/incidents` | [事故復盤](fde/12-incidents.jpg) | 已檢視，詳見分組限制 |
| `/fde/costs` | [成本預算](fde/13-costs.jpg) | 已檢視，詳見分組限制 |
| `/fde/acceptance` | [客戶驗收](fde/14-acceptance.jpg) | 已檢視，詳見分組限制 |
| `/workbench/generic` | [AIcheck - 通用资料审查 · 通用資料審查總覽](workflows/01-generic-overview.jpg) | 已檢視，詳見分組限制 |
| `/workbench/inspection` | [AIcheck - 监检工作台 · 監檢總覽／工位功能啟用](workflows/30-inspection-overview-enabled.jpg) | 已檢視，詳見分組限制 |
| `/workbench/contractor` | [AIcheck - 施工方工作台 · 施工資料摘要、上傳與監檢意見](workflows/03-contractor-overview.jpg) | 已檢視，詳見分組限制 |
| `/workbench/ndt` | [AIcheck - 无损检测工作台 · 無損檢測資料庫首頁](workflows/04-ndt-overview.jpg) | 已檢視，詳見分組限制 |
| `/workbench/owner` | [AIcheck - 建设方工作台 · 建設方唯讀總覽](workflows/05-owner-overview.jpg) | 已檢視，詳見分組限制 |
| `/fde-feedback-triage` | [回饋歸因](fde/15-feedback-triage.jpg) | 已檢視，詳見分組限制 |
| `/fde-blind-review` | [盲審](fde/16-blind-review.jpg) | 已檢視，詳見分組限制 |

## 帳號頁補圖

[登入](auth/login.jpg) · [加入項目](auth/join.jpg) · [首次改密](auth/change-password.jpg) · [授權頁](auth/skill-authorize.jpg)。註冊連結、首次改密旗標與授權payload為明示的隔離示例；沒有提交。
