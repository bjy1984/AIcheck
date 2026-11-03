/** 意见反馈：各角色提给管理员，管理员回复、改状态。后端见 backend/apps/api/user_feedback_routes.py。 */

export type UserFeedbackCategory = 'usability' | 'audit_accuracy' | 'bug' | 'suggestion' | 'other'
export type UserFeedbackStatus = 'open' | 'acknowledged' | 'resolved' | 'declined'

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
  { value: 'declined', label: '暂不采纳' }
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
