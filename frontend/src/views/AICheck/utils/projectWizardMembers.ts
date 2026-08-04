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
