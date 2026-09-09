# R39：滲透檢測乳化劑施加方法

## 原文來源與範圍

- 庫內檔案：`rules/standards/NB_T_47013_split/NB_T 47013.5-2015 承压设备无损检测 第5部分 渗透检测.pdf`。
- SHA-256：`bf2262482463ff0e72a73a791a46d21c748c42eae1efb26af01bc37674d3832d`。
- 人眼核讀渲染頁：PDF 第9頁／印刷頁235的4.5.1表3（去除方法分類）；PDF 第11頁／印刷頁237的6.3.2（乳化劑施加方法）。這是開發核讀，不是工程人員人工核驗背書。
- 標準狀態查詢：[全國標準信息公共服務平台](https://std.samr.gov.cn/hb/search/stdHBDetailedCNF?id=8B1827F221ABBB19E05397BE0A0AB44A)，2026-09-09查得現行。該頁只支持版本狀態，條文內容依上述庫內原文。

## 本次實作

`evaluate_r39_pt_emulsifier_application` 僅核對乳化劑施加方法：B為親油型後乳化，D為親水型後乳化；兩者可浸或澆，D可噴灑，刷塗不符合，B噴灑不符合。A（水洗）或C（溶劑去除）且原文明確沒有乳化步驟，返回不適用。未知方法、未說明施加方式、分類和所述步驟相互矛盾，保留證據不足，不猜測適用性。

- scope固定工程、機構、文件與版本、文件類型、PT方法、對象及事件；process引用必須來自該文件版本。
- basis須同scope、明確採用NB/T47013.5-2015第6.3.2且有來源。沒有適用依據不執行判定。
- 解析表 `ndt_pt_context`、`ndt_pt_basis`、`ndt_pt_process` 各一筆；被審文件版本用 `reviewedDocumentVersionId`，來源版本由既有reader生成。重複或身份不一致不任取首筆。
- 接入R39固定版本事實、來源門檻、executor參數、工具註冊及實際AC-R39-01綁定；通用profile或模型ruleChecks不能代替專用事實。
- 保留99個工具的註冊／工位權限覆蓋檢查；不更改36條試點、生命週期或既有判定碼。

## 未完成邊界

這不是全部PT工藝驗收；溫度、時間、表面條件、檢測時機、靈敏度等未在本工具判定。單一文件／對象／事件不代表全部應用清單。非PT輸入為尚不支持，不能據此聲稱其他檢測方法不適用。原三類pendingCapabilities保持，R39仍不能發布。真實文件抽取及工程案例尚待驗收，本次端到端使用合成解析資料。

## 驗證

在backend執行 `.venv/bin/python -m pytest -q tests/test_r39*.py tests/test_review_business_tools.py tests/test_review_tool*.py tests/test_atomic_binding_generation.py tests/test_review_workstations.py tests/test_review_acceptance_gate.py`：557 passed。新增專項覆蓋四態、B/D方法、引用錯版、身份衝突、未知或格式錯誤、來源低可信、重複對象及編譯後工具結果。Ruff289/289、monolith及diff通過。
