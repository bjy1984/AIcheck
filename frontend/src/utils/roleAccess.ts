import type { RoleCode } from '@/types/aicheck'

export type AicheckRole = RoleCode | 'test'

export const AICHECK_ROLE_LABELS: Record<AicheckRole, string> = {
  inspection: '监检人员',
  contractor: '施工方',
  ndt: '无损检测机构',
  owner: '建设单位',
  admin: '系统管理员',
  fde: 'FDE 工程师',
  test: '测试人员'
}

export const ROLE_DEFAULT_PATHS: Record<AicheckRole, string> = {
  inspection: '/ai-review-b',
  contractor: '/workbench/contractor',
  ndt: '/workbench/ndt',
  owner: '/workbench/owner',
  admin: '/admin/overview',
  fde: '/fde/dashboard',
  test: '/workbench/inspection'
}

const roleValues: AicheckRole[] = [
  'inspection',
  'contractor',
  'ndt',
  'owner',
  'admin',
  'fde',
  'test'
]

export const normalizeAicheckRole = (role?: string): AicheckRole => {
  return roleValues.includes(role as AicheckRole) ? (role as AicheckRole) : 'inspection'
}

export const getAicheckRoleLabel = (role?: string, fallback = '-') => {
  const value = String(role || '').trim()
  if (!value) return fallback
  return AICHECK_ROLE_LABELS[value.toLowerCase() as AicheckRole] || value
}

export const getRoleDefaultPath = (role?: string): string => {
  return ROLE_DEFAULT_PATHS[normalizeAicheckRole(role)]
}

export const isPathAllowedForRole = (path: string, role?: string): boolean => {
  const normalizedRole = normalizeAicheckRole(role)
  const pathname = path.split(/[?#]/, 1)[0]
  if (!pathname || pathname === '/') return false
  if (['/login', '/404', '/redirect'].some((prefix) => pathname.startsWith(prefix))) return true
  if (pathname === '/ai-review-b' || pathname.startsWith('/ai-review-b/')) {
    return normalizedRole === 'inspection'
  }
  if (pathname === '/workbench/generic' || pathname.startsWith('/workbench/generic/')) {
    return ['admin', 'inspection', 'contractor', 'owner'].includes(normalizedRole)
  }
  if (normalizedRole === 'admin')
    return pathname.startsWith('/admin') || pathname.startsWith('/knowledge')
  if (normalizedRole === 'fde') return pathname.startsWith('/fde')
  if (normalizedRole === 'test') return pathname.startsWith('/workbench/inspection')
  if (normalizedRole === 'inspection') return pathname.startsWith('/workbench/inspection')
  return (
    pathname === ROLE_DEFAULT_PATHS[normalizedRole] ||
    pathname.startsWith(`${ROLE_DEFAULT_PATHS[normalizedRole]}/`)
  )
}

export const resolveRoleEntryPath = (role?: string, redirect?: string): string => {
  const defaultPath = getRoleDefaultPath(role)
  if (!redirect || redirect === '/') return defaultPath
  let decoded = redirect
  try {
    decoded = decodeURIComponent(redirect)
  } catch {
    decoded = ''
  }
  if (
    !decoded ||
    ['/login', '/404', '/redirect', '/change-password'].some(
      (prefix) => decoded === prefix || decoded.startsWith(`${prefix}/`)
    )
  ) {
    return defaultPath
  }
  return isPathAllowedForRole(decoded, role) ? decoded : defaultPath
}

/** 本应用已知的业务路径前缀。用来区分「不存在」和「不属于你」。 */
const KNOWN_APP_PREFIXES = ['/ai-review-b', '/workbench', '/admin', '/fde', '/knowledge']

/**
 * 这个路径是不是本应用的业务页面（不论属于哪个角色）。
 *
 * 2026-08-14 审计 F-14：施工方 / 无损检测 / 建设方各试 5 条越权路由，
 * 4 条落到「404 页面不存在」，只有 /fde/* 那条正确退回工作台。
 *
 * 原因是通配路由 `/:path(.*)*` 无条件 redirect 到 /404——某个角色没被注册的
 * 路由，vue-router 匹配不上就当成不存在。而 /fde/* 注册了通配子路由，
 * 守卫才看得到真实路径。
 *
 * 访问本身是拦住了，没有安全问题；错在**语义**：权限不足说成「页面不存在」，
 * 用户以为页面没了，拿到同事分享链接的人以为链接失效——两种都会让人去找
 * 错误的原因。
 */
export const isKnownAppPath = (path: string): boolean => {
  const pathname = String(path || '').split(/[?#]/, 1)[0]
  if (!pathname) return false
  return KNOWN_APP_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  )
}
