// 把模型写进说明里的内部名词翻成监检读得懂的话。
//
// 一键分析的提示词第 10 条明确要求模型「不要把 certificateVerification、result、
// evidence_insufficient 这类字段名或枚举值写进 title/description」，模型照样会写：
// 生产里节点 1 的一条说明是「certificateVerification.result为evidence_insufficient；……
// 且valid_until_present检查未通过」，监检根本看不懂。提示词管不住，就在显示层兜底。
// 只改显示，不改存下来的内容；只替换认得的名词，认不出的原样保留。

// 校验项（check id）：翻成一句话，用「」括起来，读起来是「某某」这项检查
const CHECKS: Record<string, string> = {
  valid_until_present: '「有效期截止日期已识别」',
  valid_until_covers_period_end: '「有效期覆盖施工结束日」',
  valid_from_covers_period_start: '「发证日期不晚于施工开始日」',
  not_expired_on_reference_date: '「核验日当天未过期」',
  validity_dates_consistent: '「有效期起止日期合理」',
  holder_matches_registry: '「持证主体与公示平台一致」',
  holder_matches_project: '「持证主体与项目参建单位一致」',
  holder_present: '「持证主体已识别」',
  scope_covers_required: '「许可范围覆盖工程要求」',
  scope_present: '「许可范围已识别」'
}

// 失败原因和提示码：直接说出是什么情况
const REASONS: Record<string, string> = {
  certificate_holder_registry_mismatch: '持证主体与公示平台不一致',
  certificate_holder_project_mismatch: '持证主体与项目参建单位不一致',
  certificate_scope_not_covered: '许可范围未覆盖工程要求',
  certificate_expires_before_period_end: '证书在施工结束前到期',
  certificate_issued_after_period_start: '证书在施工开始后才签发',
  certificate_expired_on_reference_date: '证书在核验日已过期',
  certificate_valid_until_missing: '未识别到有效期截止日期',
  certificate_holder_missing: '未识别到持证主体',
  certificate_scope_missing: '未识别到许可范围',
  construction_period_missing_using_reference_date: '未填写施工起止日期，按核验日期判断',
  unsupported_scope_profile: '许可范围口径不受支持'
}

// 容器字段名和枚举值
const TERMS: Record<string, string> = {
  'certificateVerification.result': '服务端证照核验结论',
  certificateVerification: '服务端证照核验',
  evidence_insufficient: '证据不足',
  insufficient_evidence: '证据不足',
  partially_supported: '部分证据支持',
  human_confirm: '需人工确认',
  request_correction: '建议退回补正',
  requiresHumanConfirmation: '需人工确认',
  evidenceRefs: '原文引用',
  quotedText: '引用原文',
  failed: '未通过',
  passed: '通过'
}

const TABLE: Record<string, string> = { ...CHECKS, ...REASONS, ...TERMS }

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// 长的排前面：certificateVerification.result 要先于 certificateVerification 匹配。
// 不用后行断言（Safari 16.4 之前没有）：前面的那个非单词字符放进捕获组，替换时原样带回。
const PATTERN = new RegExp(
  `(^|[^A-Za-z0-9_])(${Object.keys(TABLE)
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join('|')})(?![A-Za-z0-9_])`,
  'g'
)

export const humanizeAiText = (value: unknown): string => {
  const text = String(value ?? '')
  if (!text) return text
  return text.replace(
    PATTERN,
    (_match, prefix: string, token: string) => `${prefix}${TABLE[token]}`
  )
}
