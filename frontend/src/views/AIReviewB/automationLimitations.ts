const descriptions: Record<string, string> = {
  invalid_pending_capabilities: '这项规则的自动核验配置有问题，需要维护人员检查；请先人工核对。',
  procedure_reference_consistency:
    '规程与指导书的引用关系还没核对完整，请人工核对所有相关文件的编号和版本。',
  method_specific_technical_requirements:
    '所用检测方法的专项要求还没核对完整，请由相应专业人员核对技术要求。',
  complete_document_and_application_inventory:
    '相关文件和实际应用是否全部覆盖，系统还没核对完整，请人工核对清单。'
}
export const automationLimitationText = (code: string): string =>
  descriptions[code] || '这项自动核验能力尚未完成，需要人工核对相应要求。'
