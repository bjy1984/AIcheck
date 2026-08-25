# test / test2 两项目 OCR、LLM 分类与节点打靶评测

## 总结

| 项目 | 文件 | 适用节点 | 命中节点 | 正式证据节点 | 大类候选节点 | 自动绑定节点 | 69节点候选覆盖 | 69节点正式覆盖 | 适用节点匹配率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| test | 23 | 44 | 42 | 39 | 15 | 39 | 60.87% | 56.52% | 95.45% |
| test2 | 20 | 42 | 42 | 42 | 4 | 42 | 60.87% | 60.87% | 100.00% |

Token记录：

- test：输入 355250，输出 8314，合计 363564。
- test2：输入 321841，输出 6465，合计 328306。
- 两项目合计：输入 677091，输出 14779，合计 691870。

## 指标口径

- `适用节点`：根据LLM具体类型/大类、条件上下文和上传责任方计算；境外、新材料、穿跨越等不适用节点不进入分母。
- `命中节点`：产生正式或大类候选证据链接的节点。
- `正式证据节点`：OCR正文命中该节点证据项且类型、责任方兼容。
- `大类候选节点`：异常兜底产生，仅为待判断，不形成正式绑定，不改变节点状态。
- `自动绑定节点`：满足现有自动绑定门禁的节点。

## 项目差异

- 两项目共同正式覆盖：34 个节点。
- 仅 test 正式覆盖：17 压力管道元件以及安全附件产品验收的见证资料、抽样复验, 19 使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果, 20 新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续, 27 焊接材料的验收、保管、发放、使用和回收的管理, 36 无损检测方案。
- 仅 test2 正式覆盖：31 焊缝返修, 33 热处理设备用测温记录仪表, 34 热处理记录、报告曲线、硬度检测报告, 37 检测过程中发现问题的处理, 40 无损检测记录、报告, 41 射线检测底片抽查, 42 射线检测现场抽查, 65 无损检测报告和底片。

## test 逐文件

| 文件ID | LLM类型 | 大类兜底 | 命中节点数 | 正式节点数 | 候选节点数 | 绑定节点数 | 适用节点匹配率 |
|---|---|---|---:|---:|---:|---:|---:|
| test-pipeline-summary-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-ndt-org-certificate-001 | ndt_org_certificate | 空 | 2 | 2 | 0 | 2 | 100.00% |
| test-ndt-person-certificate-001 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-person-certificate-002 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-person-certificate-003 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-person-certificate-004 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-person-certificate-005 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-person-certificate-006 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-ndt-plan-001 | ndt_plan | 空 | 4 | 4 | 0 | 4 | 100.00% |
| test-design-license-001 | design_license | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-construction-license-001 | construction_license | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-quality-manual-001 | quality_system_document | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-notice-receipt-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-construction-notice-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-inspection-contract-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-construction-plan-001 | construction_organization_design, construction_schedule, drawing_review_record, construction_license, welder_roster, welder_certificate | 空 | 5 | 5 | 0 | 5 | 100.00% |
| test-drawing-review-001 | drawing_review_record | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test-design-document-001 | design_document, drawing_material_list, pipeline_summary, calculation_report | 空 | 23 | 23 | 0 | 23 | 92.00% |
| test-component-checklist-001 | component_compliance_checklist | 空 | 15 | 0 | 15 | 0 | 100.00% |
| test-material-submission-package-001 | acceptance_witness_record, quality_certificate, welding_material_certificate, manufacturing_license, type_test_report | 空 | 13 | 13 | 0 | 13 | 100.00% |
| test-wps-pqr-001 | wps_pqr | 空 | 3 | 3 | 0 | 3 | 100.00% |
| test-welder-social-security-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test-welder-roster-001 | welder_certificate, welder_roster | 空 | 2 | 2 | 0 | 2 | 100.00% |

未命中的适用节点：33 热处理设备用测温记录仪表, 34 热处理记录、报告曲线、硬度检测报告。
超出适用范围的误挂节点：无。

## test2 逐文件

| 文件ID | LLM类型 | 大类兜底 | 命中节点数 | 正式节点数 | 候选节点数 | 绑定节点数 | 适用节点匹配率 |
|---|---|---|---:|---:|---:|---:|---:|
| test2-001 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test2-002 | design_license | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test2-003 | welder_certificate | 空 | 2 | 2 | 0 | 2 | 100.00% |
| test2-004 | ndt_org_certificate | 空 | 2 | 2 | 0 | 2 | 100.00% |
| test2-005 | ndt_person_certificate | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test2-006 | quality_system_document | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test2-007 | 空 | 资质证照 | 4 | 0 | 4 | 0 | 100.00% |
| test2-008 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test2-009 | 空 | 空 | 0 | 0 | 0 | 0 | 100.00% |
| test2-010 | construction_organization_design | 空 | 1 | 1 | 0 | 1 | 50.00% |
| test2-011 | construction_organization_design, ndt_procedure | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test2-012 | drawing_review_record | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test2-013 | design_document, drawing_material_list, calculation_report, pipeline_summary | 空 | 24 | 24 | 0 | 24 | 100.00% |
| test2-014 | quality_certificate | 空 | 7 | 7 | 0 | 7 | 100.00% |
| test2-015 | manufacturing_license, type_test_report | 空 | 3 | 3 | 0 | 3 | 100.00% |
| test2-016 | type_test_report | 空 | 2 | 2 | 0 | 2 | 100.00% |
| test2-017 | manufacturing_license | 空 | 1 | 1 | 0 | 1 | 100.00% |
| test2-018 | quality_certificate, manufacturing_license, type_test_report | 空 | 9 | 9 | 0 | 9 | 100.00% |
| test2-019 | wps_pqr, ndt_report, welding_material_certificate | 空 | 6 | 6 | 0 | 6 | 100.00% |
| test2-020 | wps_pqr | 空 | 3 | 3 | 0 | 3 | 100.00% |

未命中的适用节点：无。
超出适用范围的误挂节点：无。

## 需要关注的业务问题

1. `test` 的节点33、34未匹配：现有设计资料出现热处理相关设计参数，但项目包中没有可定位的测温仪表证书、热处理记录/曲线和硬度报告。
2. `test2` 按当前LLM类型与适用规则实现42/42匹配，但检测施工方案同时具有 `ndt_plan` 特征，当前只标为 `construction_organization_design + ndt_procedure`；建议人工确认是否补标 `ndt_plan`，否则节点36不会进入适用分母。
3. 两个安装单位质量保证手册被识别为 `quality_system_document`，但正式映射目前只覆盖无损检测机构质量体系。责任方门禁阻止了误绑定；后续可考虑为安装单位质量手册新增分类或明确仅归档。
4. `component_compliance_checklist` 已按“材料验收与复验”大类产生咨询性候选，不替代其引用的许可证、型式试验和质量证明原文。

## 评测限制

- 分类请求未使用文件名和目录名。
- 本次离线打靶从MinerU Markdown重建了片段并生成模拟坐标，用于测试分类—节点映射和证据词命中；正式上线的页码/BBox准确率仍应使用MinerU原始内容列表复验。
- test2尚无独立人工逐文件金标，因此100%的“适用节点匹配率”表示打靶实现完整执行了LLM分类结果，不等同于LLM分类准确率100%。
