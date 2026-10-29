import { getStatusTagType } from './components/status'
/** P12 F2 triage 页的纯逻辑：筛选、计数、指标格式化。页面只做渲染，这里可单测。 */
import type { FdeFeedback } from '@/api/aicheck'

/** 与 backend/apps/api/feedback_capture.AI_FEEDBACK_ROOT_CAUSES 一一对应。 */
export const ROOT_CAUSE_OPTIONS = [
  { value: 'data_table', label: 'A 数据表 / 限值' },
  { value: 'rule_logic', label: 'B 确定性规则' },
  { value: 'guard_downgrade', label: 'C 守卫误杀' },
  { value: 'evidence_extraction', label: 'D 证据抽取' },
  { value: 'prompt', label: 'E 提示词' },
  { value: 'policy', label: 'F 业务口径' },
  { value: 'external_source', label: 'G 外部源' },
  { value: 'other', label: '其它 / 未定' }
] as const

export const GOVERNANCE_LABELS: Record<string, string> = {
  needs_triage: '待归因',
  triaged: '已归因',
  ready_for_eval: '可入评测',
  promoted_to_eval: '已入评测',
  needs_adjudication: '待仲裁'
}

export const FEEDBACK_TYPE_LABELS: Record<string, string> = {
  accepted: '采纳',
  edited: '人工编辑',
  rejected: '驳回',
  rejected_false_positive: '驳回误报',
  wrong_evidence: '证据有误',
  wrong_rule_reference: '依据引用有误',
  wrong_severity: '风险等级有误',
  hallucination: '无依据内容',
  format_error: '格式有误',
  unsafe_output: '输出安全问题',
  missed_issue: '漏报',
  guard_false_downgrade: '守卫误降级',
  human_override: '人工改判',
  return_for_correction: '退回补正'
}

/** 后端仍支持这些历史根因；只翻译显示，不合并成新分类或改写提交值。 */
export const LEGACY_ROOT_CAUSE_LABELS: Record<string, string> = {
  ocr_error: 'OCR 识别错误',
  field_mapping_error: '字段映射错误',
  rule_error: '规则配置错误',
  kb_retrieval_error: '知识检索错误',
  kb_content_error: '知识内容错误',
  prompt_error: '提示词问题',
  model_reasoning_error: '模型推理问题',
  schema_error: '结构格式错误',
  business_pack_config_error: '业务类型配置问题',
  user_uploaded_bad_file: '上传文件问题',
  ambiguous_business_standard: '业务标准不明确',
  human_review_error: '人工审查问题'
}

export const feedbackTypeLabel = (value?: string) =>
  value ? FEEDBACK_TYPE_LABELS[value] || `其他类型（${value}）` : '未记录类型'

export const rootCauseLabel = (value?: string) => {
  if (!value) return '未归因'
  return (
    ROOT_CAUSE_OPTIONS.find((option) => option.value === value)?.label ||
    (LEGACY_ROOT_CAUSE_LABELS[value]
      ? `${LEGACY_ROOT_CAUSE_LABELS[value]}（历史分类）`
      : `其他分类（${value}）`)
  )
}

/** 只为当前数据中出现的旧分类补选项，避免展示所有历史类别。 */
export const historicalRootCauses = (rows: Pick<FdeFeedback, 'rootCause'>[]) =>
  [...new Set(rows.map((row) => row.rootCause).filter((value): value is string => Boolean(value)))]
    .filter((value) => !ROOT_CAUSE_OPTIONS.some((option) => option.value === value))
    .map((value) => ({ value, label: rootCauseLabel(value) }))

export const rootCauseOptionsFor = (value?: string) => [
  ...ROOT_CAUSE_OPTIONS,
  ...historicalRootCauses([{ rootCause: value }])
]

export const feedbackCommentPreview = (comment?: string) => {
  const text = String(comment || '').trim()
  return text.length > 140 ? `${text.slice(0, 140)}…` : text
}

export type WindowKey = 'week' | 'month' | 'all'

export const withinWindow = (
  row: Pick<FdeFeedback, 'createdAt'>,
  window: WindowKey,
  now = Date.now()
) => {
  if (window === 'all') return true
  const created = Date.parse(row.createdAt || '')
  if (Number.isNaN(created)) return true
  const days = window === 'week' ? 7 : 30
  return now - created <= days * 86400000
}

export const filterRows = (
  rows: FdeFeedback[],
  filters: { rootCause: string; state: string; window: WindowKey },
  now = Date.now()
) =>
  rows.filter((row) => {
    if (filters.rootCause && (row.rootCause || '') !== filters.rootCause) return false
    if (filters.state && (row.governanceState || 'needs_triage') !== filters.state) return false
    return withinWindow(row, filters.window, now)
  })

export const countBy = (rows: FdeFeedback[], pick: (row: FdeFeedback) => string) => {
  const counts: Record<string, number> = {}
  rows.forEach((row) => {
    const key = pick(row)
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
}

export const formatRatio = (item: unknown) => {
  if (!item || typeof item !== 'object') return '—'
  const value = (item as { value?: number | null }).value
  if (value === null || value === undefined) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

export const stateTagType = (state?: string) => getStatusTagType(state)

/** 归档提交体：勾了入评测集才用 approved_for_eval，否则只是 triaged。 */
export const triagePayload = (draft: {
  rootCause: string
  canUseForEval: boolean
  canUseForTraining: boolean
  adjudicationRequired: boolean
}) => ({
  rootCause: draft.rootCause,
  status: draft.canUseForEval ? 'approved_for_eval' : 'triaged',
  canUseForEval: draft.canUseForEval,
  canUseForTraining: draft.canUseForTraining,
  adjudicationRequired: draft.adjudicationRequired
})
