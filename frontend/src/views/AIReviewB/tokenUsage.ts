import type { ReviewBTokenUsage } from '@/types/ai-review-b'

const tokenCount = (value: number | undefined) => {
  if (!Number.isFinite(value) || Number(value) <= 0) return 0
  return Math.trunc(Number(value))
}

export const formatReviewTokenUsage = (usage?: ReviewBTokenUsage) => {
  if (!usage) return ''

  const input = tokenCount(usage.inputTokens ?? usage.prompt_tokens)
  const output = tokenCount(usage.outputTokens ?? usage.completion_tokens)
  const reportedTotal = tokenCount(usage.totalTokens ?? usage.total_tokens)
  const total = reportedTotal || input + output
  if (!input && !output && !total) return ''

  const formatter = new Intl.NumberFormat('zh-CN')
  return `输入 ${formatter.format(input)} · 输出 ${formatter.format(output)} · 总计 ${formatter.format(total)} Token`
}
