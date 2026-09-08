# 2026-09-08 修復驗證記錄

本輪程式修復於 `codex/aicheck-repair`，審閱入口為 [PR #25](https://github.com/bjy1984/AIcheck/pull/25)。本記錄分開列示已實測結果、尚未通過的發布門檻與需要外部條件的操作；沒有「固定失敗數可放行」規則。

## 已執行的驗證

| 驗證 | 版本／結果 | 實際含義 |
|---|---|---|
| Ruff | 0.16.2；693 → 289，基線 337 → 289 | 沒有新增告警；不是零告警。新增、縮減、移動行號及 Ruff 本身失敗均有測試。 |
| CI 服務整合 | `4a5398d`，[run 34213480974](https://github.com/bjy1984/AIcheck/actions/runs/34213480974) 全部成功 | PostgreSQL 完整後端測試、MinIO 寫入保留版本並重啟驗證、Temporal 重試及持久伺服器重啟均實跑，lint 獨立成功。 |
| 最後程式 CI | `354adfb`，[run 34215533881](https://github.com/bjy1984/AIcheck/actions/runs/34215533881) | 全部成功：lint 53 秒，test 8 分 31 秒；PostgreSQL、MinIO 重啟持久性、Temporal 重試／重啟全部通過。 |
| 本機 PostgreSQL 全量 | `354adfb`：3077 項收集成功，3073 通過／4 跳過／零失敗 | 每項測試獨立 UTF-8 資料庫，未使用生產資料庫；最後修復後全量耗時 157.31 秒。 |
| 獨立測試容器 | `3931776`：3076 項收集成功，3010 通過／66 跳過／零失敗 | 衍生鏡像有 git/zsh/test2/完整回放夾具，未進入生產 API／worker 執行 pytest。全量耗時 478.73 秒；最後 `354adfb` R23 修復的 49 項容器針對性測試亦全部通過（4.88 秒）。 |
| 新標準及審查鏈路 | `3931776`：50 項通過；最後 R23 修復：49 項通過 | 包含別名、不合格限值、缺數據、合同選配、替代試驗、適用性與正式參數組裝。 |
| ID 遷移 | 真 PostgreSQL 測試通過 | 只讀預檢、交易失敗回滾、寫入成功及重跑零變更；不是生產備份恢復演練。 |
| 離線回放 | test／test2 各 42 節點，證據包結構完整 | 0 次模型呼叫、0 付費成本；`coveragePassed=false`，尚未處理分片或完成盲審。 |

本機 4 條環境跳過：MinIO 1 項、Temporal live 2 項（在 CI 另行實跑），以及需要 `AICHECK_CNSE_LIVE=1` 的外部平台即時查詢 1 項。獨立容器未注入 PostgreSQL 等整合服務，所以另有 PostgreSQL 跳過；這些由獨立資料庫全量測試及 CI 補驗，不能用容器跳過替代。

原交接的「8 個環境失敗」已逐類消除：`test_release_manifest.py` 的 3 項測試有 git；兩個本機啟動腳本測試有 zsh，且明確指定測試後端及空環境檔；`test_import_offline_test_projects.py` 與 `test_contract.py` 取得 test2 圖紙、標準及回放夾具。整套測試失敗數為零，沒有按總數放行。早期另發現 `/app/scripts` 誤讀基底鏡像舊程式，已在測試衍生鏡像修正路徑，沒有修改生產鏡像用途。

## 修復鏈路與來源

| 範圍 | 來源 → 組裝 → 判定 | 驗證重點 |
|---|---|---|
| 檢查比例／驗收級別 | `regulatory_tables` → `design_facts` → `evaluate_design_special_requirements` | 未知 GC2 毒性／洩漏條件不得默認低比例；驗收級別比較參與正式凍結規則。 |
| R14 | `productInspectionRules` → `r14_facts` → `build_tool_arguments` → R14 工具 | 正式呼叫讀到全部產品規則；GB/T 13296 依 GB/T 7735 的 E3H 渦流報告可替代標準水壓要求，不能覆蓋設計明確要求。 |
| R16 | `pipe_material_limits` → `material_facts` → 品質證明數值比較 | 品質等級、厚度及合同選配條件缺失留作未決；Ti/Nb 關聯下限和 Ni+Cu 合量計算；來源附於限值與結果矩陣。 |
| R25 | 方法歸一化、母材組別／厚度查詢 → WPS/PQR/施焊記錄比對 | 中文與 SMAW/GTAW 等代碼可匹配，不同方法不能通過；特殊接頭明確提示附錄審查未完成。 |
| R26 | 按標準＋焊材型號的限值檔案 → 正式參數 → 證書比較 | 不再漏讀按型號建立的檔案；保留母材／焊材配套檢查與來源。 |
| R23 | 已抽取試驗記錄 → 正式參數 → 閥門試驗判定 | 沒有可讀報告屬證據不足，有報告的實際不合格仍判不符合。 |

GB/T 14976 成分已存在 32／32，不重複捏造補錄。GB/T 13296-2023 表 3 的 31 個牌號按[官方全文入口](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=B2AB9AB2087F1B28D918295A8E0E0351) PDF 頁 10–11（印刷頁 6–7）補齊；原 PDF SHA-256 為 `d156ea818f31dec56bc73459b69db474599435f6c5e40a8536aaa529e9924564`。NB/T 47014-2023 附錄 C–F 保留來源 PDF 雜湊、原文、條號和頁碼；涉及圖示／公式的特殊接頭自動判定仍未完成。沿用既有 `accept_without_human_signoff` 採信策略，沒有冒填 `verifiedBy`。

## 發布尚未通過

[69 條矩陣](review-release-matrix.md) 包含 194 個原子綁定、必要事實及證據工具。全部可編譯，空輸入均為證據不足；但是原受限 33 條中的 28 條含未配置 `ruleChecks` 的通用工具，尚無完整逐條四情境與文件證據定位驗收。靜態矩陣不能算業務實作完成，`releaseReady=false`、綁定集維持 `draft`。

剩餘實作規則：R10、R11、R35、R36、R37、R39、R40、R43–R58、R63、R64、R66、R67、R68。需按矩陣補充各自的判定條件、適用性、事實及證據鏈，再完成全部 69 條的符合／不符合／證據不足／不適用驗收，才能一次發布。原 36 條 pilotRules 留存，不重跑或改寫歷史 AI 結論。

`python -m scripts.audit_review_release --output <report.json> --check-release` 目前應以 1 退出，這是發布門檻未通過，不是已發布。Ruff 與一般後端測試通過不能繞过這一門檻。

## 生產與外部前置條件

- ID：只讀快照需改寫 168 個 ID、304 條證據連結、262 筆掛載；0 孤兒、2 個停用且無引用項有明確排除理由。見[原始報告](material-id-production-dry-run.json)、[逐項排除後報告](material-id-production-reviewed-dry-run.json)和[維護操作單](material-id-maintenance.md)。正式備份、恢復驗證、遷移、reconcile 及恢復寫入均未執行，需維護窗口。
- 生產未部署本分支；新 ID 資產會觸發部署前置阻擋，必須按窗口流程完成遷移。API／worker 同版本及新功能的生產業務探針尚不能宣稱通過。
- 瀏覽器：再次確認 Chrome 仍停留監檢登入頁，尚無已登入測試帳號。結論卡、工程結果、證據定位及整改流程未驗收，沒有使用 readyz 替代。
- stage2：保持 stage1；最早 2026-09-14 評估，切換另行確認。
- 模型：離線證據包已準備；付費批次頻率與预算上限、足量真實樣本和盲審金標仍缺。歷史約 ¥10／輪不是本次成本估算。
- P4／P8：施焊記錄未到，焊口聯合表及 H6 未實作，不冒充完成。外部平台查不到資料維持證據不足及查詢留痕。

## 可複核附件

- [按版本記錄的測試數字及日誌雜湊](test-results.json)
- [最後程式 CI 的所有步驟及結果](ci-354adfb.json)

- [按檔案與規則分類的 Ruff 差異](ruff-diff.json)
- [法規查詢呼叫方及 missing／unavailable 原因碼清單](regulatory-chain-inventory.json)（26 個查詢、252 個原因字串／模板；未逐項完成業務歸因）
- [離線回放摘要](offline-replay.json)
- [69 條詳細綁定與驗收狀態](review-release-matrix.json)
