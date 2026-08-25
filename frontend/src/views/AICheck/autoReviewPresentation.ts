import type { AutoReviewPolicy, AutoReviewStatus } from '@/api/aicheck'

export const autoReviewModeLabel = (policy?: AutoReviewPolicy) => {
  if (!policy?.enabled) return '自动审查：已关闭'
  const realtime = policy.triggerModes.includes('ocr_mounted')
  const daily = policy.triggerModes.includes('daily_schedule')
  if (realtime && daily) return `自动审查：实时 + 每天 ${policy.dailyTime}`
  if (realtime) return '自动审查：实时'
  if (daily) return `自动审查：每天 ${policy.dailyTime}`
  return '自动审查：已开启'
}

export const autoReviewStatusSummary = (status?: AutoReviewStatus) => {
  if (!status) return '状态加载中'
  return [
    `待审节点 ${status.pendingNodeCount}`,
    `执行中 ${status.runningProjectRunCount}`,
    `失败 ${status.failedProjectRunCount}`
  ].join(' · ')
}
