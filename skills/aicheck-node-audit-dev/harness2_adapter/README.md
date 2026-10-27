# harness2 適配器

把 aicheck-node-audit 接成 harness2 的一個評測。兩條路：

- **真實路徑**（`codex_h2.py`、`run_codex.py`）：Codex 執行 skill 審一個節點，Codex 當 harness2 的改進者和選擇者，gold 只在循環結束後判分。
- **骨架**（`aicheck_h2.py`、`run_skeleton.py`）：執行器、改進者、選擇者都是確定性假部件，用來測流程本身，幾十秒跑完。

這個目錄是開發資產，不放進 skill 目錄。

## 文件

| 文件 | 作用 |
|---|---|
| `skill_tree.py` | 只用標準庫。把 skill 的 `references/*.md` 摺進 SKILL.md、再拆回來（harness2 只准改一組固定的文件，`references/` 不在裡面）。命令：export、import、check、roundtrip |
| `aicheck_h2.py` | 適配器 `AicheckAdapter`（實現 harness2 的 `BenchmarkAdapter` 協議）和腳本化的 `FakeProposer`。需要 harness2 源碼才能 import |
| `codex_h2.py` | 真實路徑：`CodexAdapter`（每次執行建一個工作區，裡面是 harness 的 AGENTS.md 和拆回原樣的 skill，再 `codex exec` 跑 `eval/codex-prompt.txt`）、`CodexProposer`（harness2 的 `Proposer`，換用 `codex exec` 開會話，快取、重試、取回 `context/harness` 都沿用它的） |
| `run_codex.py` | 真實路徑的兩步：`loop`（要先 `isolate.py prepare` 藏起 gold）跑 harness2 的 `run_domain`；`judge`（`isolate.py finish` 之後）用 score.py 給每次執行打分，把採納的 harness 寫回 `back-to-skill/` |
| `run_skeleton.py` | 造兩個合成項目和合成標準答案，驅動 harness2 的遞迴流程，最後用 `eval/score.py` 事後判分，再把採納的 harness 寫回成一個新的 skill 目錄 |

## 真實路徑跑法

harness2 裝在自己的 venv（`/Volumes/Volume/project/harness2/.venv`，`uv pip install -e .`，沒跑 `harness2-setup`）。Codex 用本機登錄的帳號和默認模型（`--ignore-user-config`；帳號不支援 config 裡的模型）；`AICHECK_H2_CODEX_MODEL` 可指定模型。

```bash
python3 skills/aicheck-node-audit-dev/eval/isolate.py prepare --tag <tag> --project <項目目錄>
AICHECK_BASE_URL=http://<服務器>:8081 PYTHONDONTWRITEBYTECODE=1 <harness2 venv>/bin/python \
  skills/aicheck-node-audit-dev/harness2_adapter/run_codex.py loop --root <runs 目錄> \
  --project ~/.aicheck-node-audit-<tag>/projects/<項目> --node 2 --label TEST-tank
python3 skills/aicheck-node-audit-dev/eval/isolate.py finish --tag <tag>
<harness2 venv>/bin/python skills/aicheck-node-audit-dev/harness2_adapter/run_codex.py judge --root <runs 目錄> \
  --gold ~/.aicheck-node-audit/eval/gold/<節點>.json
```

- k=1、parallel 模式一輪：基線 1 次執行 → 改進者 inv1、dom1 兩個提案各執行 1 次 → agg1 合成再執行 1 次 → k=1 不調選擇器（直接取 agg1）→ 反思寫經驗。共 4 次 Codex 審計、4 次 Codex 改進會話。
- 執行者的工作區：`AGENTS.md`、`skills/aicheck-node-audit/`（SKILL.md＋references/＋scripts/，和線上 skill 同形）、`.agents/skills/aicheck-node-audit` 指向它、`backend/.venv` 指向倉庫的 venv；`AICHECK_REPO` 指回倉庫找業務包和標準。執行者沙箱是 workspace-write＋開網（要連服務器查公示平台），改進者不開網。
- 執行者的軌跡取自 Codex 的會話 rollout（`~/.codex/sessions/**/rollout-*<thread_id>.jsonl`，執行者不加 `--ephemeral`，跑完複製成 run 目錄的 `rollout.jsonl`），由 `codex_h2.render_rollout` 渲染：`codex exec --json` 不記錄看圖，harness2 的渲染器也不渲染 `custom_tool_call`（這版 Codex 的所有工具調用都在裡面），只看 stream 的改進者會以為執行者從沒看過頁圖（2026-10-23 華潤 24 的 inv1 就據此改了 skill）。圖片本身換成佔位；找不到 rollout 時退回 stream 並在軌跡開頭註明看圖記錄缺失。改進者仍用 `--ephemeral`。
- 改進者看到的：harness2 的 `context/`，含 harness 樹、基線的過程記錄和 audit.md、整個項目目錄（`context/source/`）。gold 不在任何上下文裡。

## 骨架跑法（原地跑，不安裝）

harness2 要 Python 3.12 或 3.13；它這條路徑沒有第三方依賴。把它的源碼放在任意目錄：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<harness2 源碼目錄> python3.12 \
  skills/aicheck-node-audit-dev/harness2_adapter/run_skeleton.py --out <輸出目錄> --k 2 --reject-first
```

`--k 1` 約 20 秒；`--k 2` 才會調用選擇器；`--reject-first` 讓第一個提案帶一個 `references/` 文件，看 harness2 退回它。輸出目錄裡有 `library/`（採納的 harness，完整目錄樹）、`runs/`、`back-to-skill/`。

測試：`HARNESS2_SRC=<harness2 源碼目錄> python3 -m unittest discover -s skills/aicheck-node-audit-dev/tests`。不設 `HARNESS2_SRC` 時，需要 harness2 的測試會跳過。

## skill 和 harness 目錄互轉

```bash
python3 skills/aicheck-node-audit-dev/harness2_adapter/skill_tree.py export --skill-dir skills/aicheck-node-audit --out <新目錄>
python3 skills/aicheck-node-audit-dev/harness2_adapter/skill_tree.py check --harness <目錄> --skill-dir skills/aicheck-node-audit
python3 skills/aicheck-node-audit-dev/harness2_adapter/skill_tree.py import --harness <目錄> --out <新目錄> --skill-dir skills/aicheck-node-audit
```

- `import` 永遠寫到新目錄，不覆蓋現有 skill；報告裡列出哪些文件變了、哪些只存在於 harness 的文件（常開的 systemprompt、guardrails 等）變了。這些沒有對應的 skill 文件，要人來決定。
- 優化器的編輯是自由文本：加在摺疊文件末尾的內容會被算到最後一個 reference 頭上，所以寫回後一定要看變更報告和 diff。
- `check` 會擋：刪掉 `node_audit.py` 裡的 `def mask_value`、`def is_id_number`、`def check_report`（脫敏和報告校驗，凍結），或刪掉某份 reference 的摺疊標記。

## 哪些是真的、哪些是假的

- 真的：harness2 的遞迴和經驗庫流程、它對 harness 目錄的校驗、skill 的真實 `node_audit.py`（local-init、skeleton、report）、真實的 `score.py`。
- 假的：執行器（用規則代替模型填 audit.json）、改進者和選擇者（腳本）。基線故意去掉了「條件沒有觸發判符合」那一行，模擬這條規則加入前的 skill，編輯器才有東西可改。
- 評分不進循環：harness2 的編輯器和選擇器看不到標準答案，`score.py` 只在最後被調用。

## 事後驗收口徑 v2

`score.py` 輸出 `aicheck-node-audit-score@3`：`points/max/percent` 保留既有算法，另列 `standardEvidence`。`all_pass` 要同時滿足分數 ≥85%、無嚴重問題及固定主條款取證通過；待覆核不等於工程不符合。兩個適配器原樣傳遞此欄位，循環仍不讀評分，`back-to-skill` 仍只是候選匯出。

相對 @2，@3 的取證檢查支援同頁、同一存檔中分開的父條款與括號子項，並排除可辨識的目錄項、空條號及相鄰條款正文。仍需對應 canonical 文件、實際頁碼及精確存檔引用；未知版式、本地 PDF 與條件適用保留覆核。此項是結構檢查，不能證明條款解讀正確。歷史 @2 結果不可覆寫或與 @3 的驗收標記混稱同一口徑。離線案例與限制見 [offline-regression.md](../tests/offline-regression.md)。

取證檢查只讀資料包的 `rules.json`、報告引用及 `tool-results`，不用 gold 指定應調哪些工具。對 `primary` 且 `always` 的條款，核對存檔的檔案 ID、物理頁、正文中的完整條款號及報告引用的存檔路徑。`documented` 表示這些記錄能對上，不保證模型看懂或正確使用了條文。

- `not_recorded`：未找到取證存檔或引用，不能斷言模型從未看過。
- `retrieval_failed` / `content_unverified`：有嘗試，但失敗或正文未能驗證；成功回應但空正文不算取得。
- `retrieved_uncited` / `unbacked_citation`：存檔與報告引用缺一端。
- `local_citation_review`：以本地標準原件及頁碼引用，需人工對照看圖軌跡；不強制改走 API。
- `applicability_review`：條件適用或條款定位資料不全，需人工核對。無固定主條款時為 `not_required`，不代表其他標準依據都已核驗。

解析失敗及上述未完整情形均為 `review_required`。此檢查不讀原始 PDF、不改寫報告，也不把歷史分數與新驗收狀態混成一次提分。離線重評另存輸出，不覆寫舊 `judged.json`。

軌跡渲染的批次看圖程式保留全文，文字 observation 的截斷不再吞掉圖片返回標記；失敗的看圖呼叫不產生圖片標記。整份軌跡若超過上限，尾端標明 `trajectory incomplete`，不能宣稱完整傳遞。圖片像素仍不進文字軌跡。

## 已知限制

- Claude 當改進者走不通：harness2 的 claude_cli 通道寫死 Vertex，本機 `claude -p` 子進程 OAuth 失敗，所以改進者用 Codex。
- 一輪只對一個任務調整；harness2 不產出「一份最終 skill」，`judge` 寫回的是經驗庫裡採納的那棵樹，要人看 diff 再決定併不併進線上 skill。

細節見評估文檔「交接」頁第 8 節。
