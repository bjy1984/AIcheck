export type ProjectAnalysisPhase =
  | 'preparing_snapshot'
  | 'building_prompt'
  | 'queued'
  | 'model_running'
  | 'validating_output'
  | 'persisting_results'
  | 'waiting_human_review'
  | 'failed'
  | 'partial_failure'

export type ProjectAnalysisPreview = {
  projectId: string
  snapshotHash: string
  includedNodeCount: number
  uniqueFileCount: number
  fileReferenceCount: number
  estimatedInputTokens: number
  maxContextTokens: number
  reservedOutputTokens: number
  availableInputTokens: number
  contextLimitExceeded: boolean
  modelAlias: string
  /** 实际会打到的模型（official_api:qwen3.8-max 之类）；换模型即新运行 */
  modelName?: string
  modelRouteVersion: string
}

export type ProjectAnalysisStatus = {
  projectAnalysisRunId: string
  projectId: string
  status: string
  phase: ProjectAnalysisPhase
  includedNodeCount: number
  uniqueFileCount: number
  fileReferenceCount: number
  estimatedInputTokens: number
  preparedNodeCount: number
  loadedFileCount: number
  totalFindingCount: number
  validatedFindingCount: number
  persistedNodeCount: number
  batchCount?: number
  currentBatchIndex?: number
  progressMode: 'determinate' | 'indeterminate'
  percent?: number
  queueTaskId?: string | null
  /** 排队中时前面还有几个大模型任务（服务端问 Redis 得来；问不到时没有） */
  queueAhead?: number | null
  lastHeartbeatAt?: string | null
  errorCode?: string | null
  errorMessage?: string | null
  createdAt?: string
  updatedAt?: string
  finishedAt?: string | null
}

export type ProjectAnalysisRun = ProjectAnalysisStatus & Record<string, unknown>
export type ProjectAnalysisMutationOptions = { idempotencyKey?: string }

type RequestConfig = {
  url: string
  data?: unknown
  headers?: Record<string, string>
}
type RequestAdapter = {
  get: (config: RequestConfig) => Promise<any>
  post: (config: RequestConfig) => Promise<any>
}
type HeaderFactory = (
  options?: ProjectAnalysisMutationOptions
) => Record<string, string> | undefined

export const createProjectAnalysisApi = (
  adapter: RequestAdapter,
  mutationHeaders: HeaderFactory
) => ({
  getProjectAnalysisPreviewApi: (
    projectId: string
  ): Promise<IResponse<{ preview: ProjectAnalysisPreview }>> =>
    adapter.get({ url: `/api/projects/${projectId}/inspection/full-project-analysis/preview` }),
  createProjectAnalysisRunApi: (
    projectId: string,
    snapshotHash: string,
    options?: ProjectAnalysisMutationOptions
  ): Promise<IResponse<{ run: ProjectAnalysisRun; auditLogId: string }>> =>
    adapter.post({
      url: `/api/projects/${projectId}/inspection/full-project-analysis/runs`,
      data: { snapshotHash },
      headers: mutationHeaders(options)
    }),
  listProjectAnalysisRunsApi: (
    projectId: string
  ): Promise<IResponse<{ items: ProjectAnalysisRun[]; total: number }>> =>
    adapter.get({ url: `/api/projects/${projectId}/inspection/full-project-analysis/runs` }),
  getProjectAnalysisRunApi: (
    projectId: string,
    runId: string
  ): Promise<IResponse<{ run: ProjectAnalysisRun }>> =>
    adapter.get({
      url: `/api/projects/${projectId}/inspection/full-project-analysis/runs/${runId}`
    }),
  getProjectAnalysisStatusApi: (
    projectId: string,
    runId: string
  ): Promise<IResponse<{ status: ProjectAnalysisStatus }>> =>
    adapter.get({
      url: `/api/projects/${projectId}/inspection/full-project-analysis/runs/${runId}/status`
    })
})
