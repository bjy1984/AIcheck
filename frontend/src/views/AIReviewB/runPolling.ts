/**
 * ReviewRun 是否已经尘埃落定——落定了就不必再轮询。
 *
 * 判据用**排除法**而不是白名单：只把明确的终态列出来，其余一律当作「还在动」。
 * 反过来写（列出所有进行中的状态）每加一个新状态就要回来改一次，漏改的后果是
 * 轮询提前停掉、界面停在旧状态不动——又一个静默的失败。
 */
const SETTLED_STATUSES = new Set([
  'completed',
  'succeeded',
  'failed',
  'failed_to_start',
  'cancelled',
  'canceled',
  'waiting_human_review',
  'waiting_human_input'
])

export const isRunSettled = (status?: string | null): boolean => {
  const value = String(status || '').trim()
  // 没有运行 = 没什么可等的。这条要显式写出来：
  // 空字符串落到「未知状态」里会让空节点也一直轮询。
  if (!value) return true
  return SETTLED_STATUSES.has(value)
}
