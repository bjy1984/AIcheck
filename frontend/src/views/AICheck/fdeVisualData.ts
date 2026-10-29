import { reportedNumber } from './fdeReportedData'

/** Only server-reported measurements may become chart values. Zero remains a valid value. */
export const measuredScore = (
  value: unknown,
  scale: 'percent' | 'ratio' = 'percent'
): number | null => {
  const score = reportedNumber(value)
  return score !== null && score <= (scale === 'ratio' ? 1 : 100)
    ? score * (scale === 'ratio' ? 100 : 1)
    : null
}

export const measuredDuration = (row: Record<string, unknown>): number | null =>
  reportedNumber(row.durationMs) ?? reportedNumber(row.latencyMs)

export const measuredQualitySections = (rows: Array<Record<string, unknown>>) =>
  rows.map((row) => ({
    key: String(row.key || row.name || ''),
    name: String(row.name || row.key || '未命名维度'),
    score: reportedNumber(row.score),
    maxScore: reportedNumber(row.maxScore),
    status: String(row.status || 'unknown'),
    blockers: Array.isArray(row.blockers) ? row.blockers.map(String) : []
  }))

export const measuredCountRows = (rows: Array<Record<string, unknown>>, labelKey: string) =>
  rows
    .flatMap((row) => {
      const count = reportedNumber(row.count)
      return count !== null && Number.isInteger(count)
        ? [{ key: String(row[labelKey] || '未分类'), count }]
        : []
    })
    .sort((a, b) => b.count - a.count)

export const taskStatusRows = (groups: Record<string, Record<string, number>> | undefined) =>
  [
    { key: 'aiRun', label: 'AI 任务', route: '/fde/ai-runs' },
    { key: 'reviewRun', label: '审查任务', route: '/fde/review-runs' },
    { key: 'ocrRun', label: 'OCR 任务', route: '/fde/ocr-quality' }
  ].map((domain) => {
    const counts = groups?.[domain.key]
    const states = Object.entries(counts || {}).flatMap(([status, value]) => {
      const count = reportedNumber(value)
      return count !== null && Number.isInteger(count) ? [{ status, count }] : []
    })
    return {
      ...domain,
      available: Boolean(
        counts &&
          typeof counts === 'object' &&
          !Array.isArray(counts) &&
          Object.values(counts).every((value) => {
            const n = reportedNumber(value)
            return n !== null && Number.isInteger(n)
          })
      ),
      states,
      total: states.reduce((n, row) => n + row.count, 0)
    }
  })
