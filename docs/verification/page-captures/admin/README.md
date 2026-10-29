# 管理後台逐頁截圖

以 production build 與隔離記憶體 demo API 完成 13 個路由、17 張 JPEG 的逐張目視檢查。視窗為 1470 × 748，未改動 viewport；無產品資料寫入。

未遇到空白或阻斷頁。正式 Prompt 唯讀抽屜、規則列表載入及未取得狀態已在畫面確認。剩餘可見問題以表格欄寬、技術代碼、定位工具不足為主；詳見 manifest.json，每張附有問題及驗證限制。

| 路由 | 畫面 | 截圖 | 狀態 |
| --- | --- | --- | --- |
| `/admin/overview` | 项目管理（overview 別名） | [01-overview.jpg](01-overview.jpg) | reviewed |
| `/admin/projects` | 项目管理 | [02-projects.jpg](02-projects.jpg) | reviewed |
| `/admin/org` | 组织单位 | [03-org-organizations.jpg](03-org-organizations.jpg) | reviewed_with_issues |
| `/admin/org` | 用户与角色（下方區塊） | [03b-org-users.jpg](03b-org-users.jpg) | reviewed_with_issues |
| `/admin/business-packs` | 业务类型管理 | [04-business-packs.jpg](04-business-packs.jpg) | reviewed_with_issues |
| `/admin/permission` | 角色权限矩阵 | [05-permission-matrix.jpg](05-permission-matrix.jpg) | reviewed_with_issues |
| `/admin/permission` | 节点模板（下方區塊） | [05b-permission-nodes.jpg](05b-permission-nodes.jpg) | reviewed |
| `/admin/rules` | AI业务规则与流程 | [06-rules.jpg](06-rules.jpg) | reviewed_with_issues |
| `/admin/material-review-points` | 业务资料审查点 | [07-material-review-points.jpg](07-material-review-points.jpg) | reviewed_with_issues |
| `/admin/prompt-templates` | Prompt 模板管理 | [08-prompt-templates.jpg](08-prompt-templates.jpg) | reviewed_with_issues |
| `/admin/prompt-templates` | 查看生产 Prompt（唯讀抽屜） | [08b-prompt-production-readonly.jpg](08b-prompt-production-readonly.jpg) | reviewed |
| `/admin/report-templates` | 报告模板管理 | [09-report-templates.jpg](09-report-templates.jpg) | reviewed_with_issues |
| `/admin/fine-config` | 细项配置（待辦與消息） | [10-fine-config-top.jpg](10-fine-config-top.jpg) | reviewed_with_issues |
| `/admin/fine-config` | 工具源與欄位映射（下方區塊） | [10b-fine-config-tools-fields.jpg](10b-fine-config-tools-fields.jpg) | reviewed_with_issues |
| `/admin/integration` | 联调清单 | [11-integration.jpg](11-integration.jpg) | reviewed |
| `/admin/skill-requests` | Skill 请求记录 | [12-skill-requests.jpg](12-skill-requests.jpg) | reviewed |
| `/admin/audit` | 审计日志 | [13-audit.jpg](13-audit.jpg) | reviewed_with_issues |

限制：僅目前桌面尺寸、repository demo 資料；未驗證外部服務、真實資料庫或有寫入副作用的操作。Skill 請求是空資料狀態。Overview 與 projects 指向相同內容。
