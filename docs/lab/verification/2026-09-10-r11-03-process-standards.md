# AC-R11-03：施工方案的焊接與試驗內容是否滿足施工標準

## 缺口

AC-R11-03「焊接、試驗等內容是否滿足施工標準要求」原先只綁通用的 `evaluate_construction_plan`，`implementationStatus: binding_only`，走通用解釋器——等於沒有專用業務判定。

## 做法

判據**不由工具推導**，寫進規則包 `CLAUSE-PKG-R11` 的 `constructionPlanProcessRules`，四個領域：

| 領域 | 必需項 | 數值判據 |
|---|---|---|
| 焊接 | 焊材、預熱、焊後熱處理、檢測比例 | 均為 presence（GB 50236-2011 3.0.1、7.3.1） |
| 耐壓試驗 | 方法、試驗壓力、保壓時間 | 倍率達標、氣壓 1.33 倍上限（帶適用性開關）、保壓不少於 10min |
| 無損檢測 | 方法、比例、合格級別 | 比例達標、合格級別達標 |
| 泄漏試驗 | 方法、合格判據 | presence |

數值口徑與 R09 的 `designSpecialRequirementRules` **同源**——R09 問「設計有沒有寫夠」，這裡問「施工方案有沒有把它落下來」。所以工具復用 `business_tools.evaluate_rule_check` 與 `read_path`，不另寫一套比較語義。

`sourceReview.humanVerified: false`，並寫明三條局限（GB 50236 條號由既有業務規則文本轉述未逐頁對照；未覆蓋焊接工藝評定覆蓋性、焊工資格、焊材質量證明——那是序號 25／24／26）。**沒有偽造人工核對簽名。**

新工具 `libs/review_tools/r11_process_standards.py`，事實側 `r11_facts._process_standards`，綁定經 `scripts/atomic_binding_overrides.py` 生成（生成器才是真來源，手改 YAML 會被回歸抓住）。

## 四種結果的邊界

- **該寫沒寫**（requiredPaths 缺項、或整個領域方案裡沒有）→ **不符合**，不是證據不足。方案本來就該寫，算成缺證據等於替施工單位開脫。
- 寫了但低於標準 → 不符合。
- 適用性判不了（開關既不是 True 也不是 False）→ 證據不足，不按不適用放過。
- 明確不適用 → 不適用。
- 派生布林（比例／級別是否達標）取不到值 → 證據不足，不當成 False 也不當成 True。
- 證據不是所選方案版本、對象含糊、領域重複或未知 → 證據不足，不挑第一行。

## 驗收

`backend/tests/test_r11_process_standards.py` 14 條，逐條覆蓋上述邊界與註冊／綁定一致性。

- 相關子集 127 條通過（含業務包契約、綁定生成、工具註冊表、節點計劃編譯）。
- 完整後端回歸 **4933 通過、0 失敗、4 跳過**（418.96 秒）。
- Ruff 289／289、monolith 通過。

## 限制

合成參數用例，未跑真實案件。`implementationStatus` 沿用 `binding_only`：本專案這個欄位只表示是否屬試點實裝範圍（R04／R05／R12–R34），不表示有沒有專用工具——AC-R11-02 早有 `evaluate_r11_project_parameters` 也仍標 binding_only。改它會動到業務包契約的分組斷言，本輪不動。

R11 其餘缺口（簽名真實性、簽署權限、批復效力）不在本項範圍，仍阻擋發布。整體工程估算仍約 60%。
