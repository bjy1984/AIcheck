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
  runningNodeReviewCount: number
  reviewIncompleteNodeCount: number
  shardProgress: {
    expectedShardCount: number
    completedShardCount: number
    failedShardCount: number
  }
  latestFailure?: {
    reviewRunId: string
    nodeId: number
    errorCode?: string | null
    failedEvidenceShardIds: string[]
  } | null
  latestProjectRun?: Record<string, unknown> | null
}

export type ProjectReviewNodeSummary = {
  nodeId: number
  reviewRunId: string
  status: string
  findingCount: number
  highestSeverity?: 'low' | 'medium' | 'high' | 'critical' | null
  evidenceSnapshotId?: string | null
  evidenceManifestId?: string | null
  sourceEvidenceShardIds: string[]
  sourceModelAttemptIds: string[]
  evidenceCoverage: Record<string, unknown>
  failedEvidenceShardIds: string[]
  errorCode?: string | null
}

export type ProjectReviewSummary = {
  schemaVersion: 'ProjectReviewSummary@1.0.0'
  projectReviewRunId: string
  projectId: string
  triggerType?: string
  status: string
  nodeSummaries: ProjectReviewNodeSummary[]
  commonRisks: string[]
  priorityReviewNodeIds: number[]
  completion: {
    expectedNodeCount: number
    completedNodeCount: number
    failedNodeCount: number
    pendingNodeCount: number
  }
}

export type ProjectReviewRun = Record<string, unknown> & {
  projectReviewRunId: string
  projectId: string
  status: string
  summary?: ProjectReviewSummary
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

  listProjectReviewRunsApi: (
    projectId: string
  ): Promise<IResponse<{ projectReviewRuns: ProjectReviewRun[]; total: number }>> =>
    adapter.get({ url: `/api/projects/${projectId}/inspection/project-review-runs` }),

  getProjectReviewRunApi: (
    projectId: string,
    projectReviewRunId: string
  ): Promise<IResponse<{ projectReviewRun: ProjectReviewRun; summary: ProjectReviewSummary }>> =>
    adapter.get({
      url: `/api/projects/${projectId}/inspection/project-review-runs/${projectReviewRunId}`
    }),

  runProjectAutoReviewApi: (
    projectId: string,
    options?: AutoReviewMutationOptions
  ): Promise<IResponse<{ projectReviewRun: Record<string, unknown>; auditLogId: string }>> =>
    adapter.post({
      url: `/api/projects/${projectId}/inspection/auto-review/run`,
      headers: mutationHeaders(options)
    })
})
