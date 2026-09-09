# 工位三組品質對照契約（Lab）

backend/scripts/workstation_quality_report.py 只讀取離線留存資料並產生統計，不調用模型、不發布綁定。尚未收集真實三組金標資料，沒有實測品質提升數字。

## 執行

從 backend 目錄執行：

```sh
.venv/bin/python scripts/workstation_quality_report.py --manifest /absolute/path/cases.json --output /absolute/path/new-report.json
```

output 必須是新檔案。沒有合格配對案例時仍產生報告，退出碼1；有配對案例退出0。退出0不代表品質改善或發布驗收完成。

## 輸入

根物件 schemaVersion=workstation-quality-cases-v1，cases 為清單，每項：
- caseId：唯一案例編號；ruleId：R01–R69。
- inputSha256：固定輸入內容的64位小寫十六進位雜湊。同節點同雜湊不得換案例編號重複計數。
- gold：result、approved=true、至少兩個去除首尾空白後不同的 reviewers。正式資料需先解決分歧；這些宣告不代替可信審核記錄。
- predictions：baseline（現況）、workstation（僅工位）、full（完整方案）三組。每組含 result、inputSha256、model、modelSettingsSha256、implementationVersion，可附 humanSeconds、latencySeconds、costCny。
- 金標 result 為 passed／failed／evidence_insufficient／not_applicable。預測另允許 execution_error／human_review_required，仍計入分母。

三組須對應同一固定輸入、模型及模型設定；實作版本可不同。缺組、缺配置、輸入／模型不一致或未雙人覆核案例不參與任何一組配對指標，excludedCases 明確列出首個排除原因。報告尚不自行開啟原始案例檔案驗證雜湊來源；後續須連接真實結果匯出與可信金標。

humanSeconds 應使用事先固定的完整人工流程計時口徑，包括查找、比對、修正、補件與重跑處理，不只計閱讀結果時間。缺值是未量測，零代表確實量測為零；負值、非有限數值、布林或數字字串均拒絕。

## 指標

每組與每個節點分別輸出分子、分母與比例，分母0為null：
- exactAgreement：四態與金標完全一致。
- unsafePassOnNoncompliance：金標不符合中被判通過。
- noncomplianceNotDetected：金標不符合中未判不符合，包含證據不足、轉人工及執行錯誤。
- falseNoncompliance：金標符合中被判不符合。
- unnecessaryInsufficiency：金標符合／不符合中被判證據不足。
- unsupportedPass：金標證據不足中被判通過。

工位／完整方案各與現況比較：improved 與 regressed 保留改正／新增錯誤筆數；agreementDelta 是一致率差（0.05代表5個百分點）；relativeErrorReduction 是相對錯誤減少，原本零錯誤時為null，退步時可為負值。

operationalMeasures 保存各組實際量測筆數、總量及平均，不把缺值填零。pairedOperationalMeasures 只用基準與候選均量測的同案例計算 meanDelta（候選減基準）與 relativeReduction（基準總量減候選總量／基準總量），逐項揭露配對筆數；沒有配對或基準總量0時適用結果為null。

這些是樣本描述統計，沒有提供顯著性、母體準確率、因果提升或引用語義支持率。少量案例、排除偏差、同工程相關案例与金標品質仍影響解讀。publicationApproved 固定false。真實樣本分層、盲審、引用支持性標註與可信來源核驗仍待完成。

## 本批驗證

2026-09-09：三組指標、舊文件流程評估、發布驗收、NDT重放及巨石基線相關60 passed；Ruff 289／289，無新增告警。合成資料驗證誤判／棄判分母、配對改正與退步、重複輸入防灌樣本、配置不一致排除、空類別null、缺成本與同案例成本比較。沒有以合成資料產生真實品質宣稱。本批未重跑完整後端。
