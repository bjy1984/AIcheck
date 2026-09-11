# R43 第一次真實端到端：結論是 evidence_insufficient，而且是對的（2026-09-11）

## 鏈路

Token Plan 密鑰經生成器進 `runtime.env`（部署腳本修好假成功之後才真的部署上去）→
探針兩路綠 → `run_domain_judgment.py --persist` 讓 `qwen3.7-plus` 讀
`0常用管道元件核查记录-施工单位填写.doc` 的正文 → 寫入 `domain_judgments` →
`evaluate_rule_over_state.py --object-id 20260213951` 跑 R43 凍結判據。

## 三次真實調用，三個不同問題

| 次 | 結果 | 根因 | 修法 |
|---|---|---|---|
| 1 | 模型六個全 null；落庫撞 `Concurrent singleton update … admin_config` | 給模型的正文經過 `normalize_quote()`，空白全被吃掉，`20260213951` 與下一列序號黏成 `202602139512`；提示詞沒說審六個元件裡的哪一個；落庫用 `flush_state()` 連髒單例一起刷 | 給模型看原樣正文，歸一化只用於比對；加 `objectScope` 與中文列名；改 `flush_state_records` 只寫這一筆 |
| 2 | 六個全 null；落庫成功 | 推理 1508 token 在「已知值不必重填」上打轉 | 表格已讀出的值不再問模型，只問缺的 |
| 3 | 四個布林 null；落庫撞 `Concurrent persistence insert … DJ-D07DA9EA1870CF80` | 沒先載入 `domain_judgments`，同 id 被當 INSERT | 落庫前載入集合，同 id 走 UPDATE |

每一次都是先讀模型看到的 `messages.json` 與 `response.json` 再改，不憑印象。

## 四個 null 是對的

第三次模型看到的是原樣正文、明確的對象、四個帶條文的布林：

- 检查人员应通过审阅合格证、质量证明书、标记和其他证明文件进行确认
- 确信材料和管道组成件均为规定等级
- 确信材料和管道组成件已经过要求的热处理、检查和试验
- 检查人员应向检验人员提交……证明文件

這份文件是**施工方填的元件核查記錄**——一張元件清單。上面不會、也不該寫「檢查人員
已審閱並確認」：那是監檢員的動作，證據在監檢記錄或質量證明書原件的標記上。模型拒絕
編造，正是反編造閘門要的行為；判據把它們判成 `evidence_insufficient`，也正是設計的
邊界（判不了就不放過）。

所以 R43 對這份文件的真實結論：**兩個必填項有據通過（`documentNo=20260213951`、
`materialGrade=S30408`，引文是表格原文），四個判斷此文件無法支持 → evidence_insufficient。**
理由每一步可追溯。

## 要拿到 passed 缺什麼

不是程式。缺**質量證明書原件**（有標記、熱處理與試驗結果）和**監檢記錄**（檢查人員
的審閱與提交）。這回到動作清單的 A2：向工程方索取資料。

## 花費

三次調用共約 3.5k 輸入 + 5.6k 輸出 token（其中推理約 4.6k）。
