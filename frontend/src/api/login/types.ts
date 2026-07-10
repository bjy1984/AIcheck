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
