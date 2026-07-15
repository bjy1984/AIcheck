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
  inspection: '/workbench/inspection',
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
  if (!path || path === '/') return false
  if (['/login', '/404', '/redirect'].some((prefix) => path.startsWith(prefix))) return true
  if (path === '/workbench/generic' || path.startsWith('/workbench/generic/')) {
    return ['admin', 'inspection', 'contractor', 'owner'].includes(normalizedRole)
  }
  if (normalizedRole === 'admin') return path.startsWith('/admin') || path.startsWith('/knowledge')
  if (normalizedRole === 'fde') return path.startsWith('/fde')
  if (normalizedRole === 'test') return path.startsWith('/workbench/inspection')
  return (
    path === ROLE_DEFAULT_PATHS[normalizedRole] ||
    path.startsWith(`${ROLE_DEFAULT_PATHS[normalizedRole]}/`)
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
  return isPathAllowedForRole(decoded, role) ? decoded : defaultPath
}
