import { defineStore } from 'pinia'
import { store } from '../index'
import { UserType } from '@/api/login/types'
import { ElMessageBox } from 'element-plus'
import { useI18n } from '@/hooks/web/useI18n'
import { loginOutApi } from '@/api/login'
import { useTagsViewStore } from './tagsView'
import { usePermissionStoreWithOut } from './permission'
import router, { resetRouter } from '@/router'

interface UserState {
  userInfo?: UserType
  tokenKey: string
  token: string
  roleRouters?: string[] | AppCustomRouteRecordRaw[]
  rememberMe: boolean
  loginInfo?: string
}

const normalizeRememberedUsername = (value: unknown): string | undefined => {
  const username =
    typeof value === 'string'
      ? value
      : value && typeof value === 'object' && 'username' in value
        ? (value as { username?: unknown }).username
        : undefined
  if (typeof username !== 'string') return undefined
  return username.trim() || undefined
}

export const useUserStore = defineStore('user', {
  state: (): UserState => {
    return {
      userInfo: undefined,
      tokenKey: 'Authorization',
      token: '',
      roleRouters: undefined,
      // 记住我
      rememberMe: true,
      loginInfo: undefined
    }
  },
  getters: {
    getTokenKey(): string {
      return this.tokenKey
    },
    getToken(): string {
      return this.token
    },
    getUserInfo(): UserType | undefined {
      return this.userInfo
    },
    getRoleRouters(): string[] | AppCustomRouteRecordRaw[] | undefined {
      return this.roleRouters
    },
    getRememberMe(): boolean {
      return this.rememberMe
    },
    getLoginInfo(): string | undefined {
      return normalizeRememberedUsername(this.loginInfo)
    }
  },
  actions: {
    setTokenKey(tokenKey: string) {
      this.tokenKey = tokenKey
    },
    setToken(token: string) {
      this.token = token
    },
    setUserInfo(userInfo?: UserType) {
      this.userInfo = userInfo
    },
    setRoleRouters(roleRouters: string[] | AppCustomRouteRecordRaw[]) {
      this.roleRouters = roleRouters
    },
    logoutConfirm() {
      const { t } = useI18n()
      ElMessageBox.confirm(t('common.loginOutMessage'), t('common.reminder'), {
        confirmButtonText: t('common.ok'),
        cancelButtonText: t('common.cancel'),
        type: 'warning'
      })
        .then(async () => {
          await loginOutApi().catch(() => undefined)
          this.reset()
        })
        .catch(() => {})
    },
    reset() {
      const tagsViewStore = useTagsViewStore()
      const permissionStore = usePermissionStoreWithOut()
      tagsViewStore.delAllViews()
      this.setToken('')
      this.setUserInfo(undefined)
      this.setRoleRouters([])
      resetRouter()
      permissionStore.setIsAddRouters(false)
      permissionStore.routers = []
      permissionStore.addRouters = []
      permissionStore.menuTabRouters = []
      router.replace('/login')
    },
    logout() {
      this.reset()
    },
    setRememberMe(rememberMe: boolean) {
      this.rememberMe = rememberMe
    },
    setLoginInfo(loginInfo: unknown) {
      this.loginInfo = normalizeRememberedUsername(loginInfo)
    }
  },
  persist: [
    {
      pick: ['tokenKey', 'token', 'userInfo'],
      storage: sessionStorage
    },
    {
      pick: ['rememberMe', 'loginInfo'],
      storage: localStorage
    }
  ]
})

export const useUserStoreWithOut = () => {
  return useUserStore(store)
}
