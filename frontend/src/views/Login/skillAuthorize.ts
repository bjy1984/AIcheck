/** skill 网页授权页用到的纯函数：解开 skill 生成的授权请求、校验回调地址、拼回调 URL。
 *
 * 授权请求整体编码在路径里（/skill-authorize/<base64url(JSON)>），不放查询串：
 * 未登录时路由守卫只把 to.path 带进 /login?redirect=，查询串会在登录这一步丢掉。
 * JSON 字段：r = 回调地址，s = state（skill 用来认出这次回调），c = PKCE code_challenge。
 */

export interface SkillAuthorizeRequest {
  redirectUri: string
  state: string
  codeChallenge: string
  port: number
}

/** 只认本机回调：与后端 libs/security/skill_auth.loopback_redirect_uri 同一套规则。 */
const LOOPBACK_CALLBACK = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):(\d{4,5})\/callback$/
const STATE = /^[A-Za-z0-9_-]{20,100}$/
const CHALLENGE = /^[A-Za-z0-9_-]{43}$/

export const loopbackCallbackPort = (value: unknown): number | null => {
  if (typeof value !== 'string' || value.length > 100) return null
  const match = LOOPBACK_CALLBACK.exec(value)
  if (!match) return null
  const port = Number(match[2])
  return port >= 1024 && port <= 65535 ? port : null
}

const decodeBase64Url = (value: string): string => {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/')
  return atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4))
}

export const decodeSkillAuthorizeRequest = (payload: unknown): SkillAuthorizeRequest | null => {
  if (typeof payload !== 'string' || !/^[A-Za-z0-9_-]{1,600}$/.test(payload)) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(decodeBase64Url(payload))
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  const { r, s, c } = parsed as Record<string, unknown>
  const port = loopbackCallbackPort(r)
  if (
    port === null ||
    typeof s !== 'string' ||
    !STATE.test(s) ||
    typeof c !== 'string' ||
    !CHALLENGE.test(c)
  ) {
    return null
  }
  return { redirectUri: r as string, state: s, codeChallenge: c, port }
}

/** 浏览器回到 skill：授权时带 code，拒绝时带 error；两种都带上 state。 */
export const skillCallbackUrl = (
  request: SkillAuthorizeRequest,
  result: { code: string } | { error: 'access_denied' }
): string =>
  `${request.redirectUri}?${new URLSearchParams({ ...result, state: request.state }).toString()}`

export const SKILL_AUTHORIZE_ROLES = ['inspection', 'admin']
