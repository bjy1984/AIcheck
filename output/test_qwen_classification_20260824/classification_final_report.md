# test目录 OCR → Qwen3.8-Max 分类最终报告

- 文件：23；API成功：23；证据协议通过：23
- 原金标完全匹配：17/23（73.91%）
- 建议复核金标完全匹配：22/23（95.65%）
- 输入Token：354238
- 输出Token：8266
- 总Token：362504

## 运行修正

- Qwen调用关闭思考模式，避免长输入超时和大量推理Token。
- 每类最多2条证据，quote限制为4至80字符。
- HTML表格的模型引用归一化为OCR Markdown中的真实连续片段。
- Office文件转PDF提交MinerU，同时追加Office原生文本用于分类。
- 文件正文仅引用某类许可证或报告时，不将当前文件误分类为被引用类型。
- sourceRefs、negativeSignals、basisLevel、materialCategories、documentPurpose未发送给Qwen。

## 逐文件结果

| caseId | 原金标 | 建议复核金标 | Qwen分类 | 原金标匹配 | 建议金标匹配 | 输入 | 输出 |
|---|---|---|---|---:|---:|---:|---:|
| test-pipeline-summary-001 | pipeline_summary | 空 | 空 | 否 | 是 | 9950 | 121 |
| test-ndt-org-certificate-001 | ndt_org_certificate | ndt_org_certificate | ndt_org_certificate | 是 | 是 | 13892 | 230 |
| test-ndt-person-certificate-001 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 9833 | 248 |
| test-ndt-person-certificate-002 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 9623 | 291 |
| test-ndt-person-certificate-003 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 9574 | 325 |
| test-ndt-person-certificate-004 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 9938 | 241 |
| test-ndt-person-certificate-005 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 9599 | 234 |
| test-ndt-person-certificate-006 | ndt_person_certificate | ndt_person_certificate | ndt_person_certificate | 是 | 是 | 10002 | 259 |
| test-ndt-plan-001 | ndt_plan | ndt_plan | ndt_plan | 是 | 是 | 22367 | 324 |
| test-design-license-001 | design_license | design_license | design_license | 是 | 是 | 9658 | 255 |
| test-construction-license-001 | construction_license | construction_license | construction_license | 是 | 是 | 9635 | 278 |
| test-quality-manual-001 | quality_system_document | quality_system_document | quality_system_document | 是 | 是 | 16616 | 363 |
| test-notice-receipt-001 | 空 | 空 | 空 | 是 | 是 | 9839 | 119 |
| test-construction-notice-001 | 空 | 空 | 空 | 是 | 是 | 10279 | 135 |
| test-inspection-contract-001 | 空 | 空 | 空 | 是 | 是 | 10421 | 155 |
| test-construction-plan-001 | construction_organization_design | construction_organization_design, construction_schedule, drawing_review_record, construction_license, welder_certificate, welder_roster | construction_organization_design, construction_schedule, drawing_review_record, construction_license, welder_roster, welder_certificate | 否 | 是 | 35758 | 1055 |
| test-drawing-review-001 | drawing_review_record | drawing_review_record | drawing_review_record | 是 | 是 | 9793 | 307 |
| test-design-document-001 | design_document | design_document, pipeline_summary, drawing_material_list, calculation_report | design_document, drawing_material_list, pipeline_summary, calculation_report | 否 | 是 | 52317 | 851 |
| test-component-checklist-001 | acceptance_witness_record | 空 | drawing_material_list | 否 | 否 | 10097 | 254 |
| test-material-submission-package-001 | acceptance_witness_record, quality_certificate, manufacturing_license, factory_inspection_report | acceptance_witness_record, quality_certificate, welding_material_certificate, manufacturing_license, type_test_report | acceptance_witness_record, quality_certificate, welding_material_certificate, manufacturing_license, type_test_report | 否 | 是 | 37639 | 1111 |
| test-wps-pqr-001 | wps_pqr | wps_pqr | wps_pqr | 是 | 是 | 15341 | 296 |
| test-welder-social-security-001 | 空 | 空 | 空 | 是 | 是 | 9761 | 121 |
| test-welder-roster-001 | welder_roster | welder_roster, welder_certificate | welder_certificate, welder_roster | 否 | 是 | 12306 | 693 |

## 尚需业务决定

1. `test-component-checklist-001` 的正文是“常用管道元件核查记录”，60类型中没有对应类型；建议新增 `component_checklist`，或者明确规定此类文件保持未分类。
2. `test-pipeline-summary-001` 的正文是“文件目录”，不是管线汇总表；建议将金标改为空，或者新增 `document_directory`。
3. 设计图包、施工方案包、材料报审包和焊工名册包均实际包含多个资料类型，原清单应按OCR正文补齐多标签。
