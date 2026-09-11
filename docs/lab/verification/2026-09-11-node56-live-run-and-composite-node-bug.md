# 線上操作節點 56：抓出複合節點的真 bug，跑通並導出第二份驗收產物（2026-09-11）

## 經過

登入生產後台（使用者自行輸入口令，我只填帳號），逐節點看真實狀態：

- **節點 43「防腐及保温材料质量证明文件」**：今天 12:44 那次複核的結論是**實質正確**的——
  模型讀了施工圖的管路特性表，認出無縫鋼管／彎頭／法蘭／墊片／防火閥等元件與材質
  （S30408、CF8、PTFE），指出**防腐材料的質量證明文件確實未提供**。該節點掛的證據
  只有施工圖，判「證據不足」是對的。
- **節點 56「安全阀、爆破片和紧急切断阀…」**：掛的正是那份真實的元件核查記錄
  （`0常用管道元件核查记录-施工单位填写.doc`），引文就是那張六元件的表。

## 抓到的 bug：複合節點拿合成鍵去取表

對節點 56 發起複核 → **`REVIEW_WORKFLOW_FAILED`**，在 `load_context` 就死：

```
r561_review_identity_incomplete_or_wrong_node
```

一個業務節點有多個原子項時，登記本用**合成鍵**區分（10→101/102/103、53→530、
56→561/562）。`_build` 把合成鍵直接傳給 `read_ndt_tables`，而它斷言
`run["nodeId"] == node_id`——56 ≠ 561，當場拋錯。

**R10、R53、R56 只要真的執行就必死。** 單元測試把 `run["nodeId"]` 直接設成合成鍵，
所以測不出來；只有在生產上真的跑一次節點 56 才暴露。

修法：合成鍵仍是登記本索引，取表／來源覆蓋碼／判斷比對一律換回運行真實的節點號
（`COMPOSITE_NODE_IDS`）。測試釘住三條複合規則都能建出事實而不拋錯。

## 修完重跑

| | |
|---|---|
| 運行 | `RRUN-715C9E9D58` |
| 狀態 | `waiting_human_review`（不再 failed） |
| 凍結範圍 | 有，`DV-B06C2795-V1`／`DV-D66DB781-V1` |
| 結果 | `engineering-inspection-r56 → evidence_insufficient`，三個原子項同 |

## 第二份真實驗收產物

```
ruleId R56 | scenario insufficient | matchesExpected true | businessAcceptance not_reviewed
fixture.json 12.6 MB (sha 6496508a…) | output.json (sha 0bf73f95…)
```

位置：`/home/dev-bjy/aicheck-data/files/output/ops/acceptance-RRUN-715C9E9D58-20260911152858/`

`reviewer` 仍空——人工簽字不是機器能代的。

## 為什麼仍是 insufficient（而且是對的）

R56 的判據要讀 `r56_accessory_documents_domains` / `r56_accessory_installation_domains`
這兩種表結構，目前沒有對應的簽名（我只寫了 R43 的 `material_certificate_domains`）。
而那份元件核查記錄列的是管道元件，不是安全閥／爆破片／緊急切斷閥的資料——
**節點 56 要的安全附件資料本來就沒交**。判「證據不足」而不是「不符合」，落在四種
結果邊界裡「判不了就不放過、也不冤枉」那一條。

## 我沒做的

`采纳`／`驳回`／`保存审查意见`／`退回补正` 都是監檢員的業務判斷，會寫進生產的人工
結論——那是使用者的簽字，不代點。`一键分析` 是全工程、要花錢，不自作主張觸發。
