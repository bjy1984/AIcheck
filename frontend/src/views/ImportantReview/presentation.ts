import type { ReviewDocument } from '@/api/aicheck/reviewDocuments'
import type { ImportantRun } from '@/api/aicheck/importantReview'
import { friendlyEnumValue } from '@/views/AICheck/components/auditLabels'

export function parseStatus(file: ReviewDocument) {
  if (file.bodyUploaded === false) return '上传未完成'
  const status = file.ocrReadiness?.status
  if (status === 'ready') return '已解析'
  if (status === 'incomplete' || status === 'inconsistent') return '解析不完整'
  if (status === 'failed') return '解析失败'
  if (status === 'processing') return '解析中'
  if (status === 'queued') return '排队中'
  return (
    (
      {
        已识别: '已解析',
        人工修正: '已解析',
        识别中: '解析中',
        识别失败: '解析失败',
        抽取不完整: '解析不完整'
      } as Record<string, string>
    )[file.currentOcrStatus] || '待解析'
  )
}
export function executionStatus(status: string) {
  if (
    ['failed', 'failed_to_start', 'cancelled', 'review_incomplete', '失败', '已取消'].includes(
      status
    )
  )
    return '执行失败'
  if (status === 'waiting_human_input') return '待补充信息'
  if (
    [
      'completed',
      'waiting_human_review',
      'accepted_by_human',
      'edited_by_human',
      'rejected_by_human',
      '已完成',
      '完成'
    ].includes(status)
  )
    return '已完成'
  if (['queued', '排队中'].includes(status)) return '排队中'
  if (['running', 'started', 'processing', '执行中', '处理中', '审查中'].includes(status))
    return '审查中'
  return '状态待确认'
}
export const verdict = (value: string) =>
  (
    ({
      passed: '符合',
      failed: '不符合',
      warning: '预警',
      evidence_insufficient: '证据不足',
      insufficient_evidence: '证据不足',
      human_review_required: '需人工核查',
      not_applicable: '不适用'
    }) as Record<string, string>
  )[value] || '待确认'
export function nodeConclusion(run: ImportantRun) {
  if (executionStatus(run.status) !== '已完成') return '—'
  const outcomes = run.atomicCheckOutcomes.map((item) => item.result)
  if (outcomes.includes('failed')) return '不符合'
  if (outcomes.some((value) => ['evidence_insufficient', 'insufficient_evidence'].includes(value)))
    return '证据不足'
  if (outcomes.includes('warning')) return '预警'
  // Atomic checks do not certify that every v3 method has been executed.
  return '待人工复核'
}
export const tagType = (label: string): 'success' | 'danger' | 'warning' | 'info' | 'primary' => {
  if (['符合', '已完成', '已解析'].includes(label)) return 'success'
  if (['不符合', '执行失败', '解析失败', '上传未完成'].includes(label)) return 'danger'
  if (['预警', '证据不足', '需人工核查', '解析不完整'].includes(label)) return 'warning'
  if (['审查中', '解析中', '排队中'].includes(label)) return 'primary'
  return 'info'
}
export function displayValue(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map(displayValue).join('、') || '—'
  if (typeof value === 'object')
    return Object.entries(value)
      .map(([key, val]) => `${key}：${displayValue(val)}`)
      .join('；')
  if (value === 'design_document_other') return '其他设计文件'
  return friendlyEnumValue(String(value))
}
