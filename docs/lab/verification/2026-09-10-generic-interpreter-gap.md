# 逐條核查：落在通用解釋器上、且判不出結論的原子項

對應目標第 6 項「R10、R43–R58、R63–R64、R66–R68 尚需逐條核查實作缺口並補驗，不能整批宣稱已有完整能力」。

## 查到什麼

綁定裡每條規則都寫著看起來像專用的工具名——`evaluate_corrosion_protection`、`evaluate_pipeline_installation`、`evaluate_safety_accessory`、`evaluate_leak_test`、`evaluate_stress_analysis`、`evaluate_blowing_cleaning`、`evaluate_alternative_standard`。

但 `business_tools` 的 `handlers` 映射裡**沒有任何一個的實作**，全部落到通用的 `evaluate_rule_profile`。而它要求調用方同時給出 `requiredFields` 與 `ruleChecks`，兩者都沒配時直接返回 `requiredFields_not_configured` 的證據不足——**資料再齊也判不出符合或不符合**。

一個工具覆蓋六條規則（R43、R44、R45、R46、R47、R50 共用 `evaluate_corrosion_protection`）本身就是信號：那不是專用判定，是佔位。

## 更深一層

`grep -rn ruleChecks libs apps` 的結果：**全倉只有 `business_tools.py` 在消費它，沒有任何地方產生它。**

所以這不是「暫時沒配」，而是**還沒有配置它的機制**。補齊方式不是往綁定裡填幾行，而是先要有產生判據的路徑——像 R09 的 `designSpecialRequirementRules` 與 R11 的 `constructionPlanProcessRules` 那樣，把判據凍結進規則包，再由事實側解析 `actualPath`。這兩處是目前唯二走通的樣板。

## 規模

**27 個原子項、23 條規則**（194 個原子項中）。與交接記錄的「28 條」對得上——2026-09-10 已把 AC-R11-03 補為專用判定，故少一條。

涉及規則：R10、R11、R43–R58、R63、R64、R66、R67、R68。

逐條明細見同目錄 `2026-09-10-generic-interpreter-gap-detail.txt`（每個原子項的指令原文、工具、必需事實數）。

## 釘住

`backend/tests/test_generic_interpreter_gap.py` 三條：

1. 數字與規則清單不許變大——補上判定就把常數減小；變多說明新綁定又只寫了工具名。
2. 這些原子項**資料再齊也只返回證據不足**，且提示必須是 `requiredFields_not_configured`——把「缺配置」和「缺資料」分開，不能一律顯示成「請補文件」（這正是目標第 6 項的要求）。
3. 全倉沒有 `ruleChecks` 的產生方；一旦出現就要同步更新本測試與補齊方案。

## 對發布門檻的意義

這 23 條規則的原子檢查目前**不可能產出符合或不符合**。發布時不能拿「綁定已存在」冒充「判定已具備」——**禁止只改 `lifecycleStatus` 就宣稱完成全量業務發布**。

## 建議的補齊順序

條款已核到頁碼、必需事實已定義的優先，例如 R45（防腐層電火花檢測，GB/T 19285-2026 5.3.2.2(c) 已 `source_verified`、SY/T 4113.11-2023 第 4–7 章已 `visual_verified`，必需事實三項齊備），只差判據與產生機制。

整體工程估算仍約 60%。
