/** Missing measurements must never be interpreted as a measured zero or a passed gate. */
export const reportedNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  if (typeof value !== 'number' && typeof value !== 'string') return null
  if (typeof value === 'string' && !value.trim()) return null
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : null
}

export const reportedCount = (value: unknown): string => {
  const number = reportedNumber(value)
  return number !== null && Number.isInteger(number) ? String(number) : '未提供'
}

export const reportedPercent = (value: unknown): string => {
  const number = reportedNumber(value)
  return number !== null && number <= 1 ? `${Math.round(number * 1000) / 10}%` : '未提供'
}

export const reportedBoolean = (value: unknown) => {
  if (value === true) return { label: '通过', tone: 'success' as const }
  if (value === false) return { label: '未通过', tone: 'danger' as const }
  return { label: '未提供', tone: 'info' as const }
}

export const reportedRatioGate = (value: unknown, target: number, direction: 'gte' | 'lte') => {
  const number = reportedNumber(value)
  if (number === null || number > 1) {
    return { actual: '未提供', status: 'unknown', passed: null }
  }
  const passed = direction === 'gte' ? number >= target : number <= target
  return { actual: reportedPercent(number), status: passed ? 'pass' : 'warning', passed }
}

export const standardFileReadiness = (row: Record<string, unknown>) => {
  const chunks = reportedNumber(row.chunkCount)
  const vectors = reportedNumber(row.vectorCount)
  const gap = reportedNumber(row.vectorGap)
  const ready = ['已向量化', 'ready', 'completed', 'vectorized'].includes(String(row.vectorStatus))
  const vectorTone =
    ready && chunks !== null && chunks > 0 && vectors !== null && vectors >= chunks && !gap
      ? ('success' as const)
      : ('warning' as const)
  const noise = reportedNumber(row.noiseLikeWatermarkCount)
  if (chunks === null || chunks === 0) {
    return { vectorTone, noiseLabel: '未检测', noiseTone: 'info' as const }
  }
  if (noise === null) return { vectorTone, noiseLabel: '未提供', noiseTone: 'info' as const }
  return {
    vectorTone,
    noiseLabel: noise ? `${noise} 条` : '未发现水印',
    noiseTone: noise ? ('danger' as const) : ('success' as const)
  }
}

export const standardLibraryIndexed = (metrics: Record<string, unknown>) => {
  const files = reportedNumber(metrics.fileCount)
  const indexed = reportedNumber(metrics.vectorizedFileCount)
  const chunks = reportedNumber(metrics.chunkCount)
  const vectors = reportedNumber(metrics.vectorCount)
  return (
    files !== null &&
    files > 0 &&
    indexed === files &&
    chunks !== null &&
    chunks > 0 &&
    vectors === chunks &&
    reportedNumber(metrics.vectorGap) === 0 &&
    reportedNumber(metrics.issueFileCount) === 0
  )
}

const bundleFieldLabels: Record<string, string> = {
  agentVersionId: '审查助手版本',
  businessPackId: '业务类型',
  knowledgeBaseVersion: '知识库版本',
  modelRouteVersionId: '模型配置版本',
  ocrProfileVersionId: 'OCR 解析配置',
  promptVersionId: '提示词版本',
  riskLevel: '风险等级',
  ruleSetVersion: '规则集版本',
  schemaVersion: '结果格式版本'
}
export const bundleFieldLabel = (field: unknown) =>
  bundleFieldLabels[String(field)] || String(field || '未提供')

export const completedTaskCount = (rows: Array<Record<string, unknown>>) =>
  rows.filter((row) =>
    [
      'succeeded',
      'success',
      'completed',
      'complete',
      'done',
      'pass',
      'passed',
      '已完成',
      '已识别'
    ].includes(String(row.status || row.parseStatus || '').toLowerCase())
  ).length
