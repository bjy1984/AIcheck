# Jev 七項目新快照與中間報告（2026-09-23）

狀態：**輸入及盲標材料已備妥，實測驗收未完成**。本批沒有呼叫 Jev，沒有
監檢獨立標註或供應商帳單；不計算準確率，也不開放正式門檻、自動掛載或裁決變更。
此為外呼前的階段紀錄；其後已完成真實請求，最新數字見
[`真實外呼報告`](2026-09-23-jev-live-routing-evaluation.md)。

## 輸入與可重現性

- 從 `aicheck-prod-new` 的資料庫以**單一** `REPEATABLE READ READ ONLY` 交易
  唯讀取七個獲准測試工程。先前試匯出發現實際版本集合叫
  `document_versions`，修正匯出器後已重新取得單交易原始資料。
  本地完整解壓及 JSON 校驗通過；遠端暫存已刪除。
- 私有快照：`/Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-seven-single-20260923.json.zlib`
  （0600），SHA-256：`5e883da53327f8b9c303962b03ed2d0409b1657c8f388ca2668ffc194db542da`。
  快照含本地對照資訊，**不能直接發給 Jev 或提交倉庫**。
- 文件歸屬外呼入口只組裝當前完整 OCR 與固定節點題目；工程、文件名、版本、
  舊掛載、規則結果與帳號資料留在本地。原子題同樣只送 OCR 與固定題目。
  實際 JSON body 的錄製回應測試、跨工程、頁碼、最新失敗及修正測試已覆蓋。

## 新快照預檢（非實際請求）

| 指標 | 本批數字 |
|---|---:|
| 工程／文件／OCR 嘗試 | 7／194／196 |
| 通過完整輸入預檢 | 178 份 |
| 預計 Jev 請求 | 546 次 |
| OCR 尚不可用 | 3 份 |
| 整份文件超長 | 9 份 |
| 單題組請求超長 | 3 份 |
| 批次預算超出 | 1 份 |
| 證據連結／無效連結 | 434／0 |
| 相同版本多次 OCR | 2 份，均按最新嘗試選取 |
| **本批實際 Jev 請求／實際費用** | **0／未知** |

`test2-019` 與 `test2-020` 重新預檢為 2 份可處理、預計 8 次請求，實際 0 次。
不使用舊的 178／194、546 次估算充當實跑；本批雖得到相同數字，但來源是
上述單交易新快照。`--send` 現在必須附 `--expected-requests` 精確值；預檢數量變動
會在第一個外呼之前中止。單一輸入目前沒有自動重試，符合最多重試一次的上限。

## 真值準備與原子題限制

- 固定哈希在模型答案出現前抽每工程 4 份，共 28 份文件、1,904 個節點配對。
  空白標註表、含完整 OCR 和固定節點題目的**私有**監檢來源包均已建立；兩者
  均不含 Jev 預測或舊掛載。監檢員須逐項標「屬於／不屬於／不確定」，再按
  版本與輸入哈希複核。當前標註數 **0／1,904**，不能計算精確率或召回率。
- 411 個保留的歷史審查任務中，原子題發現 12 個形式上有凍結題目與規則
  結果的候選。8 個的資料來源指紋已與當前 OCR 不同，4 個完整輸入超長，
  **安全可外呼為 0**。與原始單交易資料直接重算資料來源指紋，8 個仍不相符，
  因此不是私有快照裁切造成的誤報。58 個多人題任務明確排除；其他非正式或缺結果的任務
  不冒充逐題真值。須增加合格測試任務才有機會抽滿 16 題分歧＋17 題 Jev
  判通過；不足時如實報告。
- R19 有 2 個歷史任務，但均是建議模式且無正式八題對照結果；可用 R19
  對照任務 **0**。R19 與 Qwen 須單列，不混進規則引擎的 33 題樣本。

私有資料目錄：`/Users/big67/.codex/aicheck-jev-eval/2026-09-23/`（0700）。其中
`aicheck-jev-routing-single-labels-20260923.json` 是可填寫的盲標表；
`aicheck-jev-inspector-single-sources-20260923.json` 含 OCR，僅交經授權的監檢員；
`aicheck-jev-seven-single-preflight-20260923.json`、兩份 atomic/R19 dry run 和
`aicheck-jev-decision-single-interim-20260923.json` 可本地重算。全為 0600。
與先前兩交易試匯出的 28 個抽中文件相比，**28 個輸入哈希全部相同**。

## 決策報告結論與下一次執行

新中間決策報告為 `incomplete`；阻塞項是三組實際調用、文件歸屬真值、
原子題 33 題真值、R19 真值與實際供應商帳單。`inputSnapshotSha256` 與上值
一致；跳過原因及請求預計數已在報告中。相同私有輸入重算應得到相同統計；
這不構成實測驗收。

重算入口：

```bash
cd backend
.venv/bin/python -m scripts.compile_jev_decision_report \
  --input-snapshot /Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-seven-single-20260923.json.zlib \
  --routing-preflight /Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-seven-single-preflight-20260923.json \
  --atomic-run /Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-atomic-single-dry-20260923.json \
  --r19-run /Users/big67/.codex/aicheck-jev-eval/2026-09-23/aicheck-jev-r19-single-dry-20260923.json \
  --output /private/new-path/interim.json
```

目前命令會因報告 `incomplete` 返回代碼 2；本批在相同私有輸入上逐欄重算，
報告完全一致。完整後端測試 **5,478 通過、81 跳過、0 失敗**；其後新增的
本地來源指紋保留測試與相關測試 **22 通過**，Ruff **286／286**，
`git diff --check` 通過。

輪換後的**新測試金鑰尚未配置在本機測試進程**，先前貼在聊天中的舊金鑰
不使用。金鑰到位後先以兩份 `test2`、`--expected-requests 8 --max-requests 8`
做獨立小批，核對模型版本、完整回覆、時延與帳單；再按新預檢的每批精確
請求數跑七項目。任何失敗保留紀錄，不重複同一輸入超過一次。完成實跑後才
抽 16＋17 風險題並交監檢員；真值和帳單到齊再重算決策報告。
