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
