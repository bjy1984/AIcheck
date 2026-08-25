# test目录 Qwen3.8-Max 分类评测（关闭思考）

- API成功：23/23
- 协议通过：20/23
- 分类完全匹配：16/23（69.57%）
- Micro Precision：60.00%
- Micro Recall：81.82%
- 输入Token：341634
- 输出Token：8394
- 推理Token：0
- 总Token：350028

| caseId | 金标 | Qwen分类 | 协议 | 匹配 | 输入 | 输出 | 耗时s |
|---|---|---|---|---:|---:|---:|---:|
| test-pipeline-summary-001 | pipeline_summary | 空 | accepted | 否 | 9950 | 121 | 3.39 |
| test-ndt-org-certificate-001 | ndt_org_certificate | ndt_org_certificate | accepted | 是 | 13892 | 230 | 5.44 |
| test-ndt-person-certificate-001 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 9833 | 248 | 5.68 |
| test-ndt-person-certificate-002 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 9623 | 291 | 6.29 |
| test-ndt-person-certificate-003 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 9574 | 325 | 6.86 |
| test-ndt-person-certificate-004 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 9938 | 241 | 5.17 |
| test-ndt-person-certificate-005 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 9599 | 234 | 5.18 |
| test-ndt-person-certificate-006 | ndt_person_certificate | ndt_person_certificate | accepted | 是 | 10002 | 259 | 5.58 |
| test-ndt-plan-001 | ndt_plan | ndt_plan | accepted | 是 | 22367 | 324 | 6.76 |
| test-design-license-001 | design_license | design_license | accepted | 是 | 9658 | 255 | 4.71 |
| test-construction-license-001 | construction_license | construction_license | accepted | 是 | 9635 | 278 | 6.62 |
| test-quality-manual-001 | quality_system_document | quality_system_document | accepted | 是 | 16616 | 363 | 6.15 |
| test-notice-receipt-001 | 空 | 空 | accepted | 是 | 9839 | 119 | 2.66 |
| test-construction-notice-001 | 空 | construction_license | accepted | 否 | 10137 | 198 | 4.47 |
| test-inspection-contract-001 | 空 | 空 | accepted | 是 | 10421 | 155 | 3.54 |
| test-construction-plan-001 | construction_organization_design | construction_schedule, construction_license, welder_certificate, welder_roster | rejected | 否 | 23580 | 1037 | 13.02 |
| test-drawing-review-001 | drawing_review_record | drawing_review_record | accepted | 是 | 9793 | 307 | 5.14 |
| test-design-document-001 | design_document | design_document, pipeline_summary, drawing_material_list, calculation_report | rejected | 否 | 52175 | 834 | 11.14 |
| test-component-checklist-001 | acceptance_witness_record | drawing_material_list | accepted | 否 | 10097 | 254 | 4.73 |
| test-material-submission-package-001 | acceptance_witness_record, quality_certificate, manufacturing_license, factory_inspection_report | acceptance_witness_record, quality_certificate, welding_material_certificate, manufacturing_license, type_test_report | rejected | 否 | 37497 | 1211 | 14.33 |
| test-wps-pqr-001 | wps_pqr | wps_pqr | accepted | 是 | 15341 | 296 | 4.56 |
| test-welder-social-security-001 | 空 | 空 | accepted | 是 | 9761 | 121 | 3.05 |
| test-welder-roster-001 | welder_roster | welder_certificate, welder_roster | accepted | 否 | 12306 | 693 | 10.44 |
