# 複合文件：逐頁標題與來源

## 實作與使用邊界

`libs/ocr/document_pages.py` 接入既有 OCR 後處理入口，按單頁完整標題提供 documentPageClassification：PQR、pWPS、WPS／焊接工藝卡、焊接記錄、RT／UT 報告。原文置信度須至少 0.75；只完整匹配標題，不把正文「應提供射線報告」或帶章節號的目錄項當成已提交的報告。

每頁狀態為 identified／unknown／ambiguous，保留所有匹配標題的原始片段及位置。多種類標題同頁不任選；沒有可靠標題的續頁不承接前頁分類。分類只覆蓋實際 fragments 出現的頁碼，complete=false，不推定 OCR 頁數完整、不生成文件起訖區間。

不改使用者指定的 profile、不拆分原文件、不替換原 fields，也不把分類當成批准／驗收或自動綁定對象。這是後端頁面分類資訊，前端選頁建議、分類人工確認與完整多文件路由仍待接線。

既有頁碼限制 restrict_parse_result 只用已選範圍內的 fragments 重算分類；不沿用全文件分類與其他頁標題，舊解析結果沒有該欄位時仍維持原契約。

## 真實回放

沿用前次 Apple Vision 本地辨識兩份 PDF 共 22 頁的 observations，非付費模型新跑：

- `test/8、焊接工艺评定/不锈钢氩弧焊HP022-2024焊接工艺评定.pdf`：6 頁均未達本規則的完整標題／置信度條件，保留 unknown。
- `test2/9.1金辉焊接工艺评定20.pdf`：第 1 頁 PQR，第 9 頁焊接記錄，第 10–11 頁 RT 報告；另外 12 頁 unknown。

總計 4 頁 identified、18 頁 unknown；這不是分類準確率評估，未建立獨立全頁人工標註真值。第 9 頁外觀「合格」不因此變成 RT 結論，兩頁 RT 標題也不代表它們必然同一份報告。

逐頁結果與原標題證據：`2026-09-09-real-document-pages.json`。

## 驗證

108 項相關測試通過，包括頁面分類、矛盾／未知、頁碼裁切原文隔離、既有 NDT 明確欄位／封閉格、規程／R40 來源及 fast-first。Ruff 289／289、monolith 與 diff check 通過；本輪未完整後端重跑。

後續仍需：更多真實標題／低品質 OCR 處理、續頁與區段歸屬、前端確認入口、分段後的正式 OCR／審查輸入、複合來源 grounding 和事件映射。R40 pendingCapabilities、36 試點與整體未達 90% 的狀態保持，不因新增分類欄位放行。
