type UserOrganizationIdentity = {
  orgId?: string
  orgName?: string
}

type OrganizationIdentity = {
  id?: string
  name?: string
}

export const userBelongsToOrganization = (
  user: UserOrganizationIdentity,
  organization?: OrganizationIdentity | null
) => {
  if (!organization) return false
  const userOrgId = String(user.orgId || '').trim()
  const organizationId = String(organization.id || '').trim()
  if (userOrgId && organizationId) return userOrgId === organizationId
  return String(user.orgName || '').trim() === String(organization.name || '').trim()
}

export const findFirstRoleWithoutCandidates = <Role extends string>(
  roles: readonly Role[],
  candidatesByRole: (role: Role) => readonly unknown[]
) => roles.find((role) => candidatesByRole(role).length === 0)

export const missingWizardMemberMessage = (roleLabel: string, organizationName: string) =>
  `所选${roleLabel}「${organizationName}」暂无启用且角色匹配的用户，请先在组织用户中配置。`
