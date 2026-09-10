const descriptions: Record<string, string> = {
  signature_authenticity_and_authority: '请核对签名是否有效、签字人是否有相应权限，系统目前只能核对签批记录。',
  owner_reply_validity_and_timing: '请核对建设单位批复是否有效、对应哪个方案版本，以及批复时间是否满足要求。',
  technical_parameters: '检测参数还没核对完整，请核对所用方法的参数、单位和适用条件。',
  design_requirements: '请确认本次检测采用哪份设计或规程，以及其中的要求是否适用。',
  report_results: '请核对报告结论、缺陷评定和签章，这些内容系统还没核验完整。',
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

export const automationLimitationScope = (atomicCheckId?: string): string => {
  const match = /^AC-R(\d{2})-(\d{2})$/.exec(atomicCheckId || '')
  if (!match || Number(match[1]) < 1 || Number(match[1]) > 69 || Number(match[2]) < 1)
    return ''
  return `节点 ${Number(match[1])} · 第 ${Number(match[2])} 项`
}
