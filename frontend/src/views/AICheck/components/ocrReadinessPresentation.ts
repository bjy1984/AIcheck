type Readiness = {
  status?: string
  blockingReasons?: Array<{
    code?: string
    message?: string
    fieldName?: string
    requirementName?: string
  }>
}

const labels: Record<string, string> = {
  not_started: '待处理',
  queued: '排队中',
  processing: '处理中',
  ready: '已完成',
  incomplete: '部分完成',
  inconsistent: '状态异常',
  failed: '处理失败'
}

export const ocrReadinessLabel = (status?: string): string =>
  labels[String(status || '')] || '等待产物校验'

export const ocrReadinessAlert = (readiness?: Readiness) => {
  if (!readiness) return undefined
  const status = String(readiness.status || '')
  const reasons = readiness.blockingReasons || []
  if (status === 'incomplete') {
    const coverage = reasons.find((reason) => reason.code === 'OCR_PAGE_COVERAGE_INCOMPLETE')
    if (coverage)
      return {
        title: '还有页面没辨识完',
        description: coverage.message || '已读到的内容会保留，请先核对剩余页的原文。'
      }
    const specific = reasons.find((reason) => reason.fieldName || reason.requirementName)
    if (specific)
      return {
        title: '未识别到必要内容',
        description:
          specific.message || `未识别到${specific.fieldName || specific.requirementName}。`
      }
    return {
      title: '文件还没核对完整',
      description:
        reasons.find((reason) => reason.message)?.message ||
        '已读到的内容可以查看，还有部分内容需要人工核对。'
    }
  }
  const fallbacks: Record<string, string> = {
    not_started: '文件尚未开始识别。',
    queued: '文件已进入识别队列。',
    processing: '正在识别文件内容。',
    inconsistent: 'OCR 状态异常，请重新识别。',
    failed: 'OCR 处理失败，请重新识别。'
  }
  if (!fallbacks[status]) return undefined
  return {
    title: `OCR ${ocrReadinessLabel(status)}`,
    description: reasons[0]?.message || fallbacks[status]
  }
}
