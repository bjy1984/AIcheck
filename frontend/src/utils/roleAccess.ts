import type { RoleCode } from '@/types/aicheck'

export type AicheckRole = RoleCode | 'test'

export const ROLE_DEFAULT_PATHS: Record<AicheckRole, string> = {
  inspection: '/workbench/inspection',
  contractor: '/workbench/contractor',
  ndt: '/workbench/ndt',
  owner: '/workbench/owner',
  admin: '/admin/overview',
  fde: '/fde/projects',
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

export const getRoleDefaultPath = (role?: string): string => {
  return ROLE_DEFAULT_PATHS[normalizeAicheckRole(role)]
}

export const isPathAllowedForRole = (path: string, role?: string): boolean => {
  const normalizedRole = normalizeAicheckRole(role)
  if (!path || path === '/') return false
  if (['/login', '/404', '/redirect'].some((prefix) => path.startsWith(prefix))) return true
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
