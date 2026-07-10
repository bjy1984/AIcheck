import request from '@/axios'
import type { ChangePasswordPayload, LoginResult, UserLoginType, UserType } from './types'
import { getRoleDefaultPath } from '@/utils/roleAccess'

interface RoleParams {
  roleName: string
}

const normalizeLoginResult = (raw: UserType | { token?: string; user: UserType }): LoginResult => {
  const token = 'user' in raw ? raw.token : undefined
  const user = 'user' in raw ? raw.user : raw
  return {
    token,
    user,
    defaultPath: user.defaultPath || getRoleDefaultPath(user.role)
  }
}

export const loginApi = async (data: UserLoginType): Promise<IResponse<LoginResult>> => {
  if (import.meta.env.VITE_USE_MOCK === 'true') {
    const res = await request.post<UserType>({ url: '/mock/user/login', data })
    return { ...res, data: normalizeLoginResult(res.data) }
  }
  const res = await request.post<{ token: string; user: UserType }>({
    url: '/api/auth/login',
    data
  })
  return { ...res, data: normalizeLoginResult(res.data) }
}

export const loginOutApi = (): Promise<IResponse> => {
  const headers = {
    'X-Silent-Business-Error': 'true',
    'X-Silent-Http-Error': 'true'
  }
  return import.meta.env.VITE_USE_MOCK === 'true'
    ? request.get({ url: '/mock/user/loginOut', headers })
    : request.post({ url: '/api/auth/logout', headers })
}

export const changePasswordApi = async (
  data: ChangePasswordPayload
): Promise<IResponse<LoginResult>> => {
  const res = await request.post<{ token: string; user: UserType; defaultPath: string }>({
    url: '/api/auth/change-password',
    data,
    headers: {
      'X-Silent-Business-Error': 'true',
      'X-Silent-Http-Error': 'true'
    }
  })
  return { ...res, data: normalizeLoginResult(res.data) }
}

export const getUserListApi = ({ params }: AxiosConfig) => {
  return request.get<{
    code: string
    data: {
      list: UserType[]
      total: number
    }
  }>({ url: '/mock/user/list', params })
}

export const getAdminRoleApi = (
  params: RoleParams
): Promise<IResponse<AppCustomRouteRecordRaw[]>> => {
  return request.get({ url: '/mock/role/list', params })
}

export const getTestRoleApi = (params: RoleParams): Promise<IResponse<string[]>> => {
  return request.get({ url: '/mock/role/list2', params })
}
