/** 一条提示词安装节点审计 skill（2026-11-04）。后端见 backend/apps/api/skill_install_routes.py。 */

export type SkillInstallLink = {
  /** 发给 AI 助手的那句话：含 10 分钟有效的安装说明链接和安装包 SHA-256 */
  prompt: string
  guideUrl: string
  packageUrl: string
  sha256: string
  size?: number
  revision?: string
  expiresAt: string
  validSeconds: number
}

type RequestConfig = {
  url: string
  data?: unknown
  headers?: Record<string, string>
}

type RequestAdapter = {
  post: (config: RequestConfig) => Promise<any>
}

type HeaderFactory = (options?: { idempotencyKey?: string }) => Record<string, string> | undefined

export const createSkillInstallApi = (adapter: RequestAdapter, mutationHeaders: HeaderFactory) => ({
  /** origin 是浏览器里平台的地址：安装说明里的下载、登录地址都用它 */
  createSkillInstallLinkApi: (origin: string): Promise<IResponse<SkillInstallLink>> =>
    adapter.post({ url: '/api/skill-install/links', data: { origin }, headers: mutationHeaders() })
})
