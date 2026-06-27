export const getStatusTagType = (status?: string) => {
  if (!status) return 'info'
  if (status.includes('通过') || status.includes('归档') || status.includes('健康'))
    return 'success'
  if (status.includes('补正') || status.includes('作废') || status.includes('失败')) return 'danger'
  if (
    status.includes('AI') ||
    status.includes('待') ||
    status.includes('复审') ||
    status.includes('索引')
  ) {
    return 'warning'
  }
  return 'info'
}

export const getMetricClass = (tone?: string) => `metric-card metric-card--${tone || 'gray'}`
