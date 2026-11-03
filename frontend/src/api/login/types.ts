export interface UserLoginType {
  username: string
  password: string
}

export interface UserType {
  id?: string
  username: string
  password?: string
  role: string
  roleId: string
  roleLabel?: string
  permissions?: string[]
  displayName?: string
  orgUnitName?: string
  defaultPath?: string
  mustChangePassword?: boolean
  /** 平台管理员：平台院的管理员，开通特检院和院管理员（2026-11-02） */
  platformAdmin?: boolean
  tenantId?: string
}

export interface LoginResult {
  token?: string
  user: UserType
  defaultPath: string
}

export interface ChangePasswordPayload {
  currentPassword: string
  newPassword: string
}
