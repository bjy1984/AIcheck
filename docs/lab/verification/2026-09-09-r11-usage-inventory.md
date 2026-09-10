# R11 多次採用事件清單驗收（2026-09-09）

已補 construction_plan_usage_inventory → 凍結事實 → 專用工具 → AC-R11-01 的多事件路徑。每筆 construction_plan_usage 使用 usageId；清單須具來源、相同工程／方案版本／業主／批復週期、complete=true、非空且不重複的 usageIds。

清單與實際事件須一致；漏項、額外項、重複身份、重複清單、不明來源均保留證據不足。逐事件只比較唯一記錄；另一事件缺失不能抹除已證實的晚批復。重複身份不任取首筆。單筆舊輸入仍相容；只代表所提供單筆，沒有完整工程事件背書。

198 項 R11／業務工具測試通過，包含來源表、凍結任務、實際節點執行的正常／晚批復／同日，以及漏項、重複事件、重複清單。輸入不變性、引用版本及原子 pending 阻擋亦有断言。日誌：2026-09-09-r11-usage-inventory-tests.txt。

工具版本 r11-documented-plan-approval-v3。兩项 pendingCapabilities 保留，R11 不因局部通過取得完整驗收資格；未發布工具、未遷移 ID 或改寫歷史。

範圍限制：清單 complete 是有來源的聲明，不證明真實工程已收齊。仍需 OCR／人工映射、簽名權限、撤回／附條件批復與有效性、多方案及真實案例驗收。完整後端回歸 4767 通過、0 失敗、75 跳過、6 警告，139.68 秒；日誌：2026-09-09-r11-usage-inventory-full-backend.txt。75 項跳過不視為本輪服務或真實外部查詢驗收。Ruff 289／289、monolith 與 git diff --check 通過。
