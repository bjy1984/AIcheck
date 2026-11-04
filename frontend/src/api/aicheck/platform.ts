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
  delete: (config: RequestConfig) => Promise<any>
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

  syncPlatformRulesApi: (options?: {
    idempotencyKey?: string
  }): Promise<
    IResponse<{ results: Record<string, { synced: number; removed: number }>; auditLogId: string }>
  > =>
    adapter.post({
      url: '/api/platform/institutes/sync-rules',
      data: {},
      headers: mutationHeaders(options)
    }),

  addInstituteAdminApi: (
    tenantId: string,
    payload: { username: string; name?: string; password?: string },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ admin: { username: string; name?: string }; auditLogId: string }>> =>
    adapter.post({
      url: `/api/platform/institutes/${encodeURIComponent(tenantId)}/admins`,
      data: payload,
      headers: mutationHeaders(options)
    }),

  resetInstituteAdminPasswordApi: (
    tenantId: string,
    username: string,
    payload: { password?: string },
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ username: string; mustChangePassword: boolean; auditLogId: string }>> =>
    adapter.post({
      url: `/api/platform/institutes/${encodeURIComponent(tenantId)}/admins/${encodeURIComponent(username)}/reset-password`,
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
    }),

  /** 只能删没有项目的院：停用、从列表隐藏、让出院内用户名；数据与审计保留，单位代码不能再用 */
  deleteInstituteApi: (
    tenantId: string,
    options?: { idempotencyKey?: string }
  ): Promise<IResponse<{ deleted: boolean; releasedUsernames: string[]; auditLogId: string }>> =>
    adapter.delete({
      url: `/api/platform/institutes/${encodeURIComponent(tenantId)}`,
      headers: mutationHeaders(options)
    })
})
