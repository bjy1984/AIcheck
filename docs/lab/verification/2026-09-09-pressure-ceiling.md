# 氣壓倍率上限實際判定（2026-09-09）

原問題：testPressureExceedsMax 雖已計算，凍結 pressureTest 只檢查下限，超過 1.33 的資料仍可通過這組基礎倍率檢查。

本次：凍結規則增加 pneumatic_ratio_ceiling，使用既有精確 exceedsMax 比較，來源為前批已目視核對的 GB/T 20801.1-2025 8.6.1.4 e)1)。保留 e)2) 屈服強度限制尚需核對的明確說明、verifiedBy=null 及原採信策略。

通用設計要求工具補 applicabilityPath：明確 true 才執行；false 記錄 notApplicableRules；未知保留 unresolvedRules，不猜適用與否。事實只有單一氣壓方法標為 true，明確液壓為 false，混合／未知不標。無上限不得正面通過，已知低於下限仍保留 failed。工具版本 r09-design-special-requirements-v2。

156 項相關測試通過：氣壓 1.3304 failed，1.33／1.1 基础檢查 passed，1.0996 failed，液壓該上限不適用，方法不明及缺值不足。完整後端回歸4835通過、0失敗、75跳過、6警告（202.01秒）；日誌2026-09-09-pressure-ceiling-full-backend.txt，涵蓋最近精度／管線錯配修復，跳過項不算實際服務驗收。Ruff 289／289、monolith 通過。

範圍限制：1.33 只是氣壓上限之一；屈服強度另一上限、完整適用性、材料／溫度、安全措施及 R11-03 完整施工技術判定仍未完成。局部基礎倍率 passed 不等於整個壓力試驗或 R11 驗收。歷史凍結規則未改、未發布工具。整體粗估仍約60%。
