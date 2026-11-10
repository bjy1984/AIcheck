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

/**
 * 3 秒兜底轮询这一轮要不要刷新工作台。
 *
 * 原来的条件是「发过消息（executionStarted）或运行没落定」。executionStarted 发完一问
 * 就一直是 true——于是**问过一句之后，只要页面开着就每 3 秒刷一次工作台、消息、事件、
 * 审计视图**。2026-11-10 生产日志：回答落定后这套请求照样一轮接一轮，每个 5–10 秒，
 * 和后台跑着的 Agent 抢同一个 API 进程（问一句 1 分 44 秒，模型只占约 47 秒）。
 *
 * - 聊天回答进行中不刷：等结果的那段有自己的轮询（waitForAssistantCompletion）和 SSE，
 *   答完再收尾刷新一次。
 * - 正式复核发起中要刷：那个 POST 同步跑好几分钟，靠这里看运行状态。
 * - 其余只看运行是否落定。
 */
export const shouldRefreshLiveState = (state: {
  hidden: boolean
  sending: boolean
  reviewStarting: boolean
  runStatus?: string | null
}): boolean => {
  if (state.hidden || state.sending) return false
  if (state.reviewStarting) return true
  return !isRunSettled(state.runStatus)
}
