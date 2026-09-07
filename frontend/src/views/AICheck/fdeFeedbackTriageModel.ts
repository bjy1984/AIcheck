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
  rejected: '驳回',
  wrong_evidence: '证据有误',
  missed_issue: '漏报',
  guard_false_downgrade: '守卫误降级',
  human_override: '人工改判',
  return_for_correction: '退回补正'
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

export const stateTagType = (state?: string) => {
  if (state === 'promoted_to_eval' || state === 'ready_for_eval') return 'success'
  if (state === 'needs_adjudication') return 'danger'
  if (state === 'triaged') return 'info'
  return 'warning'
}

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
