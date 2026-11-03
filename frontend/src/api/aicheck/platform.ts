/** 平台管理：开通特检院与院管理员。后端见 backend/apps/api/platform_routes.py。 */

export type Institute = {
  id: string
  code: string
  name: string
  status: 'active' | 'disabled'
  builtin?: boolean
  createdAt?: string
  createdBy?: string
  userCount: number
  adminUsernames: string[]
  projectCount: number
}

type RequestConfig = { url: string; data?: unknown; headers?: Record<string, string> }
type RequestAdapter = {
  get: (config: RequestConfig) => Promise<any>
  post: (config: RequestConfig) => Promise<any>
}
type HeaderFactory = (options?: { idempotencyKey?: string }) => Record<string, string> | undefined

export const createPlatformApi = (adapter: RequestAdapter, mutationHeaders: HeaderFactory) => ({
  getInstitutesApi: (): Promise<IResponse<{ items: Institute[] }>> =>
    adapter.get({ url: '/api/platform/institutes' }),

  createInstituteApi: (
    payload: {
      code: string
      name: string
      adminUsername: string
      adminName?: string
      adminPassword?: string
    },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ institute: Institute; auditLogId: string }>> =>
    adapter.post({
      url: '/api/platform/institutes',
      data: payload,
      headers: mutationHeaders(options)
    }),

  setInstituteStatusApi: (
    tenantId: string,
    status: 'active' | 'disabled',
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ institute: Institute; auditLogId: string }>> =>
    adapter.post({
      url: `/api/platform/institutes/${encodeURIComponent(tenantId)}/status`,
      data: { status },
      headers: mutationHeaders(options)
    })
})
