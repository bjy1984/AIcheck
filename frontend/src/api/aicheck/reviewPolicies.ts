/** 院级审查口径开关与平台规则送达既有项目。后端见 review_policy_routes.py、pack_update_routes.py。 */

export type ReviewPolicySource = 'institute' | 'platform' | 'code'

export type ReviewPolicy = {
  key: string
  label: string
  description: string
  appliesTo: string
  options: Array<{ value: string; label: string }>
  codeDefault: string
  platformDefault: string | null
  instituteValue: string | null
  effective: { value: string; source: ReviewPolicySource }
  /** 只有平台管理员能看到：各院（含平台院）每个选项选了哪些院 */
  adoption?: Record<string, Array<{ name: string; source: ReviewPolicySource }>>
}

export type BusinessPackUpdate = {
  projectId: string
  projectName: string
  projectStatus: string
  businessPackId: string
  frozenVersion: string | null
  currentVersion: string
  upToDate: boolean
  archived: boolean
  upgradable: boolean
  affectedConclusionCount: number
  diff: {
    fromVersion: string | null
    toVersion: string
    upToDate: boolean
    sections: Array<{
      name: string
      label: string
      added: number
      removed: number
      changed: number
      sample: string[]
    }>
    otherChanges: string[]
    otherChangeLabels?: string[]
    affectedNodeIds: number[]
  }
}

type RequestConfig = { url: string; data?: unknown; headers?: Record<string, string> }
type RequestAdapter = {
  get: (config: RequestConfig) => Promise<any>
  post: (config: RequestConfig) => Promise<any>
  put: (config: RequestConfig) => Promise<any>
}
type HeaderFactory = (options?: { idempotencyKey?: string }) => Record<string, string> | undefined

export const createReviewPolicyApi = (adapter: RequestAdapter, mutationHeaders: HeaderFactory) => ({
  getReviewPoliciesApi: (): Promise<IResponse<{ items: ReviewPolicy[]; platformAdmin: boolean }>> =>
    adapter.get({ url: '/api/admin/review-policies' }),
  /** value = null：跟随平台默认 */
  setInstituteReviewPolicyApi: (
    key: string,
    value: string | null,
    options?: { idempotencyKey?: string }
  ) =>
    adapter.put({
      url: `/api/admin/review-policies/${encodeURIComponent(key)}`,
      data: { value },
      headers: mutationHeaders(options)
    }),
  setPlatformReviewPolicyDefaultApi: (
    key: string,
    value: string | null,
    options?: { idempotencyKey?: string }
  ) =>
    adapter.put({
      url: `/api/platform/review-policy-defaults/${encodeURIComponent(key)}`,
      data: { value },
      headers: mutationHeaders(options)
    }),
  getBusinessPackUpdatesApi: (): Promise<
    IResponse<{ items: BusinessPackUpdate[]; outdatedCount: number }>
  > => adapter.get({ url: '/api/admin/business-pack/updates' }),
  applyBusinessPackUpdatesApi: (
    projectIds: string[],
    options?: { idempotencyKey?: string }
  ): Promise<
    IResponse<{
      appliedCount: number
      results: Array<{
        projectId: string
        applied: boolean
        reason?: string
        fromVersion?: string
        toVersion?: string
        affectedNodeIds?: number[]
        affectedConclusionCount?: number
        updatedRequirementIds?: string[]
        boundRequirementIdsNotUpdated?: string[]
        retiredRequirementIds?: string[]
      }>
    }>
  > =>
    adapter.post({
      url: '/api/admin/business-pack/updates/apply',
      data: { projectIds },
      headers: mutationHeaders(options)
    })
})
