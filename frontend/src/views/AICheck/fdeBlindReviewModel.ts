/** P12 F4 盲审页的纯逻辑：橡皮图章指数的显示与阈值判断。 */
import type { FdeRubberStampIndex } from '@/api/aicheck'

export const RESULT_OPTIONS = ['满足要求', '需补正', '不适用', '证据不足'] as const
/** 与 backend AICHECK_RUBBER_STAMP_ALERT_THRESHOLD 默认一致：指数低于它说明常规审查基本照抄 AI。 */
export const ALERT_THRESHOLD = 0.05
export const MIN_SAMPLE_FOR_ALERT = 5

export const formatPct = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`

export const indexLabel = (index: FdeRubberStampIndex | null) => {
  const value = index?.value
  if (value === null || value === undefined) return '待盲审'
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}`
}

export const indexAlert = (index: FdeRubberStampIndex | null, threshold = ALERT_THRESHOLD) => {
  const value = index?.value
  if (value === null || value === undefined) return false
  return (index?.sampleSize || 0) >= MIN_SAMPLE_FOR_ALERT && value < threshold
}
