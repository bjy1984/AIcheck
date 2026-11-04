/** 意见反馈：各角色提给管理员，管理员回复、改状态。后端见 backend/apps/api/user_feedback_routes.py。 */

export type UserFeedbackCategory = 'usability' | 'audit_accuracy' | 'bug' | 'suggestion' | 'other'
export type UserFeedbackStatus = 'open' | 'acknowledged' | 'resolved' | 'declined' | 'escalated'

/** 送平台审批后，平台改进任务的进度（后端 libs/improvement_tasks.feedback_mirror） */
export type UserFeedbackPlatformTask = {
  taskId: string
  status: string
  statusLabel: string
  title?: string
}

export type UserFeedbackScope = 'public' | 'gray'

export type UserFeedbackContext = {
  page?: string
  pageTitle?: string
  projectId?: string
  nodeId?: string
  aiRunId?: string
}

export type UserFeedback = {
  id: string
  category: UserFeedbackCategory
  categoryLabel: string
  content: string
  context: UserFeedbackContext
  status: UserFeedbackStatus
  statusLabel: string
  submittedBy: {
    userId: string
    username: string
    name: string
    role: string
    orgUnitName?: string
  }
  reply: { content: string; repliedBy: string; repliedAt: string } | null
  platformTask?: UserFeedbackPlatformTask
  escalation?: { by: string; at: string; scope: UserFeedbackScope; note: string }
  createdAt: string
  updatedAt: string
}

export type UserFeedbackListPayload = {
  items: UserFeedback[]
  categories: Record<UserFeedbackCategory, string>
  statuses: Record<UserFeedbackStatus, string>
  statusCounts?: Record<UserFeedbackStatus, number>
}

/** 下拉选项和后端 CATEGORIES 同序；后端返回的中文名优先，这里只在列表还没加载时兜底。 */
export const USER_FEEDBACK_CATEGORIES: Array<{
  value: UserFeedbackCategory
  label: string
  hint: string
}> = [
  { value: 'usability', label: '使用不便', hint: '找不到入口、步骤太绕、看不懂提示' },
  { value: 'audit_accuracy', label: '审计不准确', hint: 'AI 或规则的判断与资料不符' },
  { value: 'bug', label: '功能异常', hint: '报错、点了没反应、数据不对' },
  { value: 'suggestion', label: '功能建议', hint: '希望增加或改进的功能' },
  { value: 'other', label: '其他', hint: '' }
]

export const USER_FEEDBACK_STATUSES: Array<{ value: UserFeedbackStatus; label: string }> = [
  { value: 'open', label: '待处理' },
  { value: 'acknowledged', label: '已受理' },
  { value: 'resolved', label: '已解决' },
  { value: 'declined', label: '暂不采纳' },
  { value: 'escalated', label: '已送平台' }
]

/** 院管理员回复时能选的状态：「已送平台」只能走送审，不能手动选 */
export const USER_FEEDBACK_REPLY_STATUSES = USER_FEEDBACK_STATUSES.filter(
  (item) => item.value !== 'escalated'
)

export const USER_FEEDBACK_SCOPES: Array<{
  value: UserFeedbackScope
  label: string
  hint: string
}> = [
  {
    value: 'public',
    label: '公共改进',
    hint: '改给所有院都不会变差：功能异常、使用不便、按国家标准审计不准'
  },
  {
    value: 'gray',
    label: '各院口径不一',
    hint: '各院做法可能不同，平台会考虑做成院级开关，给一个默认值'
  }
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

export const createUserFeedbackApi = (adapter: RequestAdapter, mutationHeaders: HeaderFactory) => ({
  submitUserFeedbackApi: (
    payload: { category: UserFeedbackCategory; content: string; context?: UserFeedbackContext },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ feedback: UserFeedback; auditLogId: string }>> =>
    adapter.post({ url: '/api/user-feedback', data: payload, headers: mutationHeaders(options) }),

  getMyUserFeedbackApi: (): Promise<IResponse<UserFeedbackListPayload>> =>
    adapter.get({ url: '/api/user-feedback/mine' }),

  getAdminUserFeedbackApi: (filters?: {
    status?: UserFeedbackStatus | ''
    category?: UserFeedbackCategory | ''
    role?: string
  }): Promise<IResponse<UserFeedbackListPayload>> =>
    adapter.get({
      url: '/api/admin/user-feedback',
      params: Object.fromEntries(Object.entries(filters || {}).filter(([, value]) => value))
    }),

  escalateUserFeedbackApi: (
    feedbackId: string,
    payload: { scope: UserFeedbackScope; note?: string },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ feedback: UserFeedback; taskId: string; auditLogId: string }>> =>
    adapter.post({
      url: `/api/admin/user-feedback/${encodeURIComponent(feedbackId)}/escalate`,
      data: payload,
      headers: mutationHeaders(options)
    }),

  replyUserFeedbackApi: (
    feedbackId: string,
    payload: { status: UserFeedbackStatus; reply?: string },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ feedback: UserFeedback; auditLogId: string }>> =>
    adapter.post({
      url: `/api/admin/user-feedback/${encodeURIComponent(feedbackId)}/reply`,
      data: payload,
      headers: mutationHeaders(options)
    })
})
