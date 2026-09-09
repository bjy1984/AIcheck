# R40 明示參數要求對照

新增 evaluate_r40_parameters，已註冊工具、接入事實組裝、executor、R40 原子項及生成 override。使用既有有來源事件清單；member 明示 requiredParameters 與 parameterRequirementsComplete 後，按工程／對象／方法／事件與參數名唯一匹配 ndt_parameter_requirements 和 ndt_parameter_values。

支援明示 gte/lte/eq 數值比較與 eq 文字比較；數值要求與實測值須有限且非布林，單位必須明示且一致。文字級別僅逐字相等，不猜等級高低。沒有預設標準限值、單位換算或容差。未知、缺失、重複、單位／事件不符及清單外參數保留證據不足；有來源的不適用與矛盾參數分開。已確認的參數不符不被其他缺值抹掉。

60 項相關測試通過：來源到工具參數、完整節點執行、比較邊界、四態、NaN／布林／單位、重複／事件、低置信度、多參數缺值與已知不符合；R40 原文／頁码、生成及發布審計回歸通過。Ruff 289／289、monolith 通過。輸出：r40-parameters.txt。

範圍仍是合成標準化表。工具回傳 wholeRuleAcceptance=not_evaluated；尚需真實文件參數抽取、要求來源適用性／完整性、報告結論及真實案件驗收。technical_parameters/design_requirements/report_results 三項 pendingCapabilities 保留，完整 R40 仍為 evidence_insufficient，沒有發布或增加試點。最新發布矩陣已重產。
