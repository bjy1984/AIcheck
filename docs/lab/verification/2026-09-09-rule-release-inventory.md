# 69 條規則發布驗收矩陣

此表由 `backend/scripts/audit_review_release.py` 產生。空輸入探針只驗證防誤通過；工具註冊及編譯不代表業務驗收完成。

四情境（符合／不符合／證據不足／不適用）及文件證據定位尚需逐條留存真實驗收記錄。全量發布門檻尚未達成。

| 規則 | 原試點 | 原子項 | 註冊完整 | 空輸入結果 | 未配置規則檔案的通用工具 | 尚未完成能力 |
|---|---|---:|---|---|---|---|
| R01 | 是 | 5 | True | evidence_insufficient | — | — |
| R02 | 是 | 4 | True | evidence_insufficient | — | — |
| R03 | 是 | 4 | True | evidence_insufficient | — | — |
| R04 | 是 | 4 | True | evidence_insufficient | — | — |
| R05 | 是 | 2 | True | evidence_insufficient | — | — |
| R06 | 是 | 4 | True | evidence_insufficient | — | — |
| R07 | 是 | 2 | True | evidence_insufficient | — | — |
| R08 | 是 | 2 | True | evidence_insufficient | — | — |
| R09 | 是 | 2 | True | evidence_insufficient | — | — |
| R10 | 否 | 4 | True | evidence_insufficient | evaluate_alternative_standard | — |
| R11 | 否 | 4 | True | evidence_insufficient | evaluate_construction_plan | owner_reply_validity_and_timing, signature_authenticity_and_authority |
| R12 | 是 | 2 | True | evidence_insufficient | — | — |
| R13 | 是 | 3 | True | evidence_insufficient | — | — |
| R14 | 是 | 4 | True | evidence_insufficient | — | — |
| R15 | 是 | 6 | True | evidence_insufficient | — | — |
| R16 | 是 | 7 | True | evidence_insufficient | — | — |
| R17 | 是 | 6 | True | evidence_insufficient | — | — |
| R18 | 是 | 7 | True | evidence_insufficient | — | — |
| R19 | 是 | 8 | True | evidence_insufficient | — | — |
| R20 | 是 | 2 | True | evidence_insufficient | — | — |
| R21 | 是 | 2 | True | evidence_insufficient | — | — |
| R22 | 是 | 2 | True | evidence_insufficient | — | — |
| R23 | 是 | 3 | True | evidence_insufficient | — | — |
| R24 | 是 | 5 | True | evidence_insufficient | — | — |
| R25 | 是 | 3 | True | evidence_insufficient | — | — |
| R26 | 是 | 3 | True | evidence_insufficient | — | — |
| R27 | 是 | 3 | True | evidence_insufficient | — | — |
| R28 | 是 | 2 | True | evidence_insufficient | — | — |
| R29 | 是 | 2 | True | evidence_insufficient | — | — |
| R30 | 是 | 3 | True | evidence_insufficient | — | — |
| R31 | 是 | 2 | True | evidence_insufficient | — | — |
| R32 | 是 | 2 | True | evidence_insufficient | — | — |
| R33 | 是 | 2 | True | evidence_insufficient | — | — |
| R34 | 是 | 3 | True | evidence_insufficient | — | — |
| R35 | 否 | 2 | True | evidence_insufficient | — | — |
| R36 | 否 | 2 | True | evidence_insufficient | — | — |
| R37 | 否 | 3 | True | evidence_insufficient | — | — |
| R38 | 是 | 2 | True | evidence_insufficient | — | — |
| R39 | 否 | 2 | True | evidence_insufficient | — | complete_document_and_application_inventory, method_specific_technical_requirements, procedure_reference_consistency |
| R40 | 否 | 2 | True | evidence_insufficient | — | design_requirements, report_results, technical_parameters |
| R41 | 否 | 2 | True | evidence_insufficient | — | — |
| R42 | 否 | 2 | True | evidence_insufficient | — | — |
| R43 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R44 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R45 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R46 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R47 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R48 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R49 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R50 | 否 | 2 | True | evidence_insufficient | evaluate_corrosion_protection | — |
| R51 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R52 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R53 | 否 | 3 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R54 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R55 | 否 | 2 | True | evidence_insufficient | evaluate_pipeline_installation | — |
| R56 | 否 | 3 | True | evidence_insufficient | evaluate_safety_accessory | — |
| R57 | 否 | 2 | True | evidence_insufficient | evaluate_safety_accessory | — |
| R58 | 否 | 2 | True | evidence_insufficient | evaluate_safety_accessory | — |
| R59 | 否 | 2 | True | evidence_insufficient | — | — |
| R60 | 是 | 2 | True | evidence_insufficient | — | — |
| R61 | 是 | 3 | True | evidence_insufficient | — | — |
| R62 | 是 | 2 | True | evidence_insufficient | — | — |
| R63 | 否 | 2 | True | evidence_insufficient | evaluate_stress_analysis | — |
| R64 | 否 | 2 | True | evidence_insufficient | evaluate_leak_test | — |
| R65 | 否 | 3 | True | evidence_insufficient | — | — |
| R66 | 否 | 2 | True | evidence_insufficient | evaluate_leak_test | — |
| R67 | 否 | 2 | True | evidence_insufficient | evaluate_leak_test | — |
| R68 | 否 | 2 | True | evidence_insufficient | evaluate_blowing_cleaning | — |
| R69 | 否 | 2 | True | evidence_insufficient | — | — |

完整必要事實、綁定及證據工具欄位見同目錄 JSON。`—` 只代表沒有發現此類靜態缺口，仍須業務情境驗收。
