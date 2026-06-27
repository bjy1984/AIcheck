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
}

export interface LoginResult {
  token?: string
  user: UserType
  defaultPath: string
}
