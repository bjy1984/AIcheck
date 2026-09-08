# 審查點 ID 維護窗口操作單

本分支只完成程式、資產及只讀 dry-run；尚未停止生產寫入或執行正式遷移。

## 已核實的影響

2026-09-08 生產快照：168 個 ID、304 條證據連結、262 筆資料掛載、0 筆整改要求需要改寫，孤兒引用為 0。兩個停用且沒有引用的節點 9 項目已逐項列出於 `material-id-production-reviewed-dry-run.json`，排除後 `safeToApply=true`。這份摘要不是維護窗口的寫入許可；資料變動後須重新 dry-run。

ID 哈希輸入為節點號、資料類型碼、審查內容。插入、刪除其他行及重排行序不改既有 ID；修改該條審查內容仍可能改 ID，必須再走映射流程。R01 原本兩行具有相同业务键，本次以「標題欄及設計印章單位一致性」「設計許可範圍與管道特性覆蓋」區分，舊資料以 fileContent 唯一匹配。

## 窗口前

1. 固定待部署提交及鏡像摘要，保留舊 API／worker 鏡像與伺服器程式版本。
2. 在伺服器暫存目錄放入新遷移腳本及新資產，使用舊鏡像、只讀掛載及伺服器 runtime env 執行 dry-run；不要先啟動新 API，避免補種新 ID。
3. 在已約定的窗口暫停入口寫入與排程。處理在途審查，溫停 API 及所有寫入 worker，確認沒有活躍任務及殘留寫入程序。若溫停逾時或仍有在途任務，停止操作並處理原因。
4. 在伺服器建立受限權限的 PostgreSQL custom-format 全量備份及程式版本清單，計算 SHA-256。用 `pg_restore --list` 檢查備份；先在獨立資料庫恢復並核對關鍵集合筆數。備份及憑證均不拷至本機。
5. 在停止寫入的狀態重新產生 dry-run，審閱 unmatched、excluded、orphanReferences、wouldRewrite 及 planSha256。任何歧義或目標衝突均停止，不能刪掉報告中的阻擋项硬做。

## 執行

以下命令在裝有本分支程式的專用遷移容器內執行；環境僅由伺服器的 runtime env 注入。`<digest>` 和 `<old-id-list>` 必須取自窗口內新報告，不能沿用本次線上快照。

```bash
python scripts/migrate_material_review_point_ids.py \
  --exclude-inactive-id MRP-9-leakage_test_report-5983A4 \
  --exclude-inactive-id MRP-9-instrument_calibration_certificate-F445C6

python scripts/migrate_material_review_point_ids.py --apply --maintenance-confirmed \
  --expect-plan-sha256 '<digest>' --ids <old-id-list> \
  --exclude-inactive-id MRP-9-leakage_test_report-5983A4 \
  --exclude-inactive-id MRP-9-instrument_calibration_certificate-F445C6

python scripts/migrate_material_review_point_ids.py --check-current
```

寫入使用單一 PostgreSQL 交易，锁住涉及的兩張状态表；任何例外回滾。只改 admin_config、node_evidence_links、bindings 和 rectifications。保留 previousIds，不改歷史 AI 快照。

## 恢復及回滾

- 再次 dry-run 必須零映射、零孤兒。部署新版本並執行原有 reconcile 後，核對 168 條活動配置的派生欄位及所有引用，再恢復入口和排程。
- API／四個 worker 必須同鏡像、同提交，readyz 和業務探針通過。普通部署腳本有只讀 ID 前置檢查；未遷移即非零退出。
- 回滾必須在仍停止寫入時同步恢復資料庫備份、舊程式及舊鏡像。單獨回滾程式會再次引入新舊 ID 混用。
- 本次沒有執行生產備份恢復演練；不可把單元測試或 dry-run 當成備份可恢復的證明。
