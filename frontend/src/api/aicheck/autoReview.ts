export type AutoReviewTriggerMode = 'ocr_mounted' | 'daily_schedule'

export type AutoReviewPolicy = {
  id: string
  projectId: string
  tenantId: string
  enabled: boolean
  triggerModes: AutoReviewTriggerMode[]
  dailyTime: string
  timezone: string
  reviewMode: 'gap_precheck'
  debounceSeconds: number
  revision: number
  etag: string
  updatedAt?: string
  lastDailyRunLocalDate?: string
}

export type AutoReviewStatus = {
  policy: AutoReviewPolicy
  pendingNodeCount: number
  runningProjectRunCount: number
  failedProjectRunCount: number
  latestProjectRun?: Record<string, unknown> | null
}

export type AutoReviewPolicyInput = Pick<
  AutoReviewPolicy,
  'enabled' | 'triggerModes' | 'dailyTime' | 'timezone' | 'debounceSeconds'
>

export type AutoReviewMutationOptions = {
  etag?: string
  idempotencyKey?: string
  silentBusinessError?: boolean
  silentHttpError?: boolean
}

type RequestConfig = {
  url: string
  data?: unknown
  headers?: Record<string, string>
}

type RequestAdapter = {
  get: (config: RequestConfig) => Promise<any>
  put: (config: RequestConfig) => Promise<any>
  post: (config: RequestConfig) => Promise<any>
}

type HeaderFactory = (options?: AutoReviewMutationOptions) => Record<string, string> | undefined

export const createAutoReviewApi = (adapter: RequestAdapter, mutationHeaders: HeaderFactory) => ({
  getProjectAutoReviewPolicyApi: (
    projectId: string
  ): Promise<IResponse<{ policy: AutoReviewPolicy }>> =>
    adapter.get({ url: `/api/projects/${projectId}/inspection/auto-review-policy` }),

  updateProjectAutoReviewPolicyApi: (
    projectId: string,
    payload: AutoReviewPolicyInput,
    options?: AutoReviewMutationOptions
  ): Promise<IResponse<{ policy: AutoReviewPolicy; auditLogId: string }>> =>
    adapter.put({
      url: `/api/projects/${projectId}/inspection/auto-review-policy`,
      data: payload,
      headers: mutationHeaders(options)
    }),

  getProjectAutoReviewStatusApi: (projectId: string): Promise<IResponse<AutoReviewStatus>> =>
    adapter.get({ url: `/api/projects/${projectId}/inspection/auto-review-status` }),

  runProjectAutoReviewApi: (
    projectId: string,
    options?: AutoReviewMutationOptions
  ): Promise<IResponse<{ projectReviewRun: Record<string, unknown>; auditLogId: string }>> =>
    adapter.post({
      url: `/api/projects/${projectId}/inspection/auto-review/run`,
      headers: mutationHeaders(options)
    })
})
