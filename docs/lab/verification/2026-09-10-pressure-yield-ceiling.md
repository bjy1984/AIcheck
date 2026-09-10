# 氣壓試驗的第二個上限（屈服強度極限時試驗壓力的 90%）

## 缺口

GB/T 20801.1-2025 8.6.1.4 e)：氣壓試驗壓力不低於 1.1 倍設計壓力，**同時不超過下列壓力的較小者**——

1. 1.33 倍設計壓力；
2. 不超過管道屈服強度極限時的 90% 試驗壓力。

此前只接了第 1 條。於是一份「氣壓試驗、1.2 倍設計壓力」的方案在 1.33 倍那一條通過後就報 **passed**——第二個上限從未評估過，卻以通過的形式呈現。**只判了一半而報通過，比報證據不足更糟。**

## 修復

- 法規表 `gbt20801_inspection.pressureTest` 補結構化係數 `pneumaticYieldCeilingFactor: 0.90`，並寫明所需輸入（試驗溫度下屈服強度極限對應壓力，由外徑、最小壁厚與該溫度屈服強度算出）與「設計文件未給出時判證據不足，不得因 1.33 倍通過就放行」。
- `pressure_test_ratios()` 增 `pneumaticYieldFactor`；大於 1 的係數視為不可用（那會把上限抬高）。
- `design_facts` 計算 `yieldLimitPressureMPa` / `pneumaticYieldCeilingMPa` / `testPressureExceedsYieldCeiling`；算不出時保持 `None`，凍結判據把 `None` 判成未決。
- R09 的 `designSpecialRequirementRules` 與 R11 的 `constructionPlanProcessRules` 同步新增 `pneumatic_yield_ceiling` 判據（帶 `applicabilityPath`，液壓不適用），並補 `verifiedBy: null`——這是防止偽造人工核對的護欄，兩處都必須帶。

## 順帶修掉一個誤讀

「屈服強度極限時**試驗壓力**為 X MPa」這句話裡也含「試驗壓力…MPa」，會被試驗壓力的正則吃掉，再與倍率對不上就誤報壓力矛盾——與此前泄漏、氣密壓力被誤讀是同一類。已加負向斷言，並有專項用例。

## 行為變化（有意為之）

`test_pressure_ceiling_execution` 裡「氣壓 1.33 倍 → passed」「氣壓 1.1 倍 → passed」兩條改為 **evidence_insufficient**。這不是回歸：這些方案只寫了倍率，算不出絕對試驗壓力，第二個上限無從評估。要判通過必須同時給出屈服強度極限對應壓力。

## 驗收

- 新增／改寫用例：`test_pressure_ratio_availability.py`（係數無效不得成默認、屈服上限只由寫明的值算出、凍結判據帶第二上限）、`test_pressure_ceiling_execution.py`（誤讀防護、倍率式表述判證據不足、液壓不適用）、`test_r11_process_standards.py`（施工方案側同一條判據的四態）。
- 相關子集 391 條通過；完整後端回歸 **4945 通過、0 失敗、4 跳過**（256.64 秒）。
- Ruff 289／289、monolith 通過。

## 仍未完成

- **溫度應力修正**（8.6.1.3 公式 54 `pT = 1.5·p·S1/S2`）未接入判定；表裡有原文，缺結構化的許用應力取值路徑。
- 8.6.1.1.3 a) 的降壓例外、8.6.1.5 的免除情形、真空／外壓與夾套管的專門規定均未接入。
- 完整對象映射（多管線、多次試驗按具體對象／事件整理）未做。

整體工程估算仍約 60%。
