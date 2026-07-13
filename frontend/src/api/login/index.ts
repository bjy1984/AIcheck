import request from '@/axios'
import type { ChangePasswordPayload, LoginResult, UserLoginType, UserType } from './types'
import { getRoleDefaultPath } from '@/utils/roleAccess'

interface RoleParams {
  roleName: string
}

const normalizeLoginResult = (raw: unknown): LoginResult => {
  if (!raw || typeof raw !== 'object') {
    throw new Error('登录接口未返回有效数据，请稍后重试。')
  }
  const candidate = raw as Record<string, unknown>
  const token = typeof candidate.token === 'string' ? candidate.token : undefined
  const user = (candidate.user ?? candidate) as Partial<UserType>
  if (
    typeof user.username !== 'string' ||
    typeof user.role !== 'string' ||
    typeof user.roleId !== 'string'
  ) {
    throw new Error('登录接口返回的用户信息无效，请稍后重试。')
  }
  const normalizedUser = user as UserType
  return {
    token,
    user: normalizedUser,
    defaultPath: normalizedUser.defaultPath || getRoleDefaultPath(normalizedUser.role)
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
