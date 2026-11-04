/** 改进任务：意见反馈送平台审批后的平台队列。后端见 backend/apps/api/improvement_routes.py。 */

export type ImprovementTaskStatus =
  | 'pending_review'
  | 'approved'
  | 'claimed'
  | 'in_review'
  | 'deployed'
  | 'closed'
  | 'declined'
  | 'merged'

export type ImprovementTaskScope = 'public' | 'gray'
export type ImprovementTaskPriority = 'P1' | 'P2' | 'P3'

export type ImprovementTaskSource = {
  sourceTenantId: string
  feedbackId: string
  category: string
  contentRedacted: string
  context: Record<string, string>
  submittedRole: string
  submittedAt: string
  escalatedBy?: string
  escalationNote?: string
}

export type ImprovementTask = {
  id: string
  status: ImprovementTaskStatus
  statusLabel: string
  scope: ImprovementTaskScope
  scopeLabel: string
  priority: ImprovementTaskPriority
  priorityLabel: string
  title: string
  taskStatement: string
  acceptanceCriteria: string
  sources: ImprovementTaskSource[]
  sourceCount: number
  sourceTenantCount: number
  sourceInstitutes: string[]
  claim: { by: string; agent: string; at: string; expiresAt: string } | null
  result: {
    prUrl: string
    commit?: string
    tests: string
    note?: string
    by: string
    at: string
  } | null
  history: Array<{
    at: string
    by: string
    action: string
    from?: string
    to?: string
    note?: string
  }>
  mergedInto?: string
  declineReason?: string
  reopenNote?: string
  createdAt: string
  updatedAt: string
}

export type ImprovementTaskListPayload = {
  items: ImprovementTask[]
  statusCounts: Record<ImprovementTaskStatus, number>
  statuses: Record<ImprovementTaskStatus, string>
  scopes: Record<ImprovementTaskScope, string>
  priorities: Record<ImprovementTaskPriority, string>
}

/** 列表上方的状态页签；顺序就是一条任务走的路 */
export const IMPROVEMENT_TASK_TABS: Array<{ value: ImprovementTaskStatus | ''; label: string }> = [
  { value: 'pending_review', label: '待平台审批' },
  { value: 'approved', label: '待开发' },
  { value: 'claimed', label: '开发中' },
  { value: 'in_review', label: '待审核合并' },
  { value: 'deployed', label: '已上线' },
  { value: 'closed', label: '已关闭' },
  { value: 'declined', label: '暂不采纳' },
  { value: '', label: '全部' }
]

type RequestConfig = {
  url: string
  data?: unknown
  params?: Record<string, unknown>
  headers?: Record<string, string>
}
type RequestAdapter = {
  get: (config: RequestConfig) => Promise<any>
  post: (config: RequestConfig) => Promise<any>
}
type HeaderFactory = (options?: { idempotencyKey?: string }) => Record<string, string> | undefined
type TaskResponse = Promise<IResponse<{ task: ImprovementTask; auditLogId: string }>>

export const createImprovementTaskApi = (
  adapter: RequestAdapter,
  mutationHeaders: HeaderFactory
) => {
  const act = (
    taskId: string,
    verb: string,
    data: unknown,
    options?: { idempotencyKey?: string }
  ): TaskResponse =>
    adapter.post({
      url: `/api/platform/improvement-tasks/${encodeURIComponent(taskId)}/${verb}`,
      data,
      headers: mutationHeaders(options)
    })
  return {
    getImprovementTasksApi: (filters?: {
      status?: ImprovementTaskStatus | ''
    }): Promise<IResponse<ImprovementTaskListPayload>> =>
      adapter.get({
        url: '/api/platform/improvement-tasks',
        params: Object.fromEntries(Object.entries(filters || {}).filter(([, value]) => value))
      }),
    approveImprovementTaskApi: (
      taskId: string,
      payload: {
        title: string
        taskStatement: string
        acceptanceCriteria: string
        priority: ImprovementTaskPriority
        scope: ImprovementTaskScope
      },
      options?: { idempotencyKey?: string }
    ) => act(taskId, 'approve', payload, options),
    declineImprovementTaskApi: (
      taskId: string,
      reason: string,
      options?: { idempotencyKey?: string }
    ) => act(taskId, 'decline', { reason }, options),
    mergeImprovementTaskApi: (
      taskId: string,
      intoTaskId: string,
      options?: { idempotencyKey?: string }
    ) => act(taskId, 'merge', { intoTaskId }, options),
    setImprovementTaskStatusApi: (
      taskId: string,
      status: 'deployed' | 'closed' | 'approved',
      note?: string,
      options?: { idempotencyKey?: string }
    ) => act(taskId, 'status', { status, note }, options)
  }
}
