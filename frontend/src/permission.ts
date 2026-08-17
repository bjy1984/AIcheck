import router from './router'
import { useAppStoreWithOut } from '@/store/modules/app'
import type { RouteRecordRaw } from 'vue-router'
import { useTitle } from '@/hooks/web/useTitle'
import { useNProgress } from '@/hooks/web/useNProgress'
import { usePermissionStoreWithOut } from '@/store/modules/permission'
import { usePageLoading } from '@/hooks/web/usePageLoading'
import { NO_REDIRECT_WHITE_LIST } from '@/constants'
import { useUserStoreWithOut } from '@/store/modules/user'
import { getRoleDefaultPath, isPathAllowedForRole, resolveRetiredPath } from '@/utils/roleAccess'

const { start, done } = useNProgress()

const { loadStart, loadDone } = usePageLoading()

router.beforeEach(async (to, from, next) => {
  start()
  loadStart()
  const permissionStore = usePermissionStoreWithOut()
  const appStore = useAppStoreWithOut()
  const userStore = useUserStoreWithOut()
  if (userStore.getUserInfo) {
    const currentRole = userStore.getUserInfo.role
    const defaultPath = getRoleDefaultPath(currentRole)
    if (userStore.getUserInfo.mustChangePassword) {
      if (to.path !== '/change-password') {
        next({ path: '/change-password', replace: true })
      } else {
        next()
      }
      return
    }
    if (to.path === '/change-password') {
      next({ path: defaultPath, replace: true })
      return
    }
    /* 已下线的路径（/ai-review-b）原地重定向。
     *
     * 收藏夹、历史待办、别人发来的链接里都存着老地址。直接 404 会让人以为
     * 功能被删了——实际上对话式复核只是搬进了 /workbench/inspection。
     * 查询串原样带过去，否则送到的是一个空工作台，还得自己重选项目和节点。
     */
    const retiredTarget = resolveRetiredPath(to.fullPath)
    if (retiredTarget) {
      next({ path: retiredTarget.split(/[?#]/, 1)[0], query: to.query, replace: true })
      return
    }
    if (to.path === '/login') {
      next({ path: defaultPath })
    } else {
      if (!isPathAllowedForRole(to.path, currentRole)) {
        if (to.path !== '/') {
          next({ path: defaultPath, replace: true })
          return
        }
      }
      if (permissionStore.getIsAddRouters) {
        next()
        return
      }

      // 开发者可根据实际情况进行修改
      const roleRouters = userStore.getRoleRouters || []

      // 是否使用动态路由
      if (appStore.getDynamicRouter) {
        appStore.serverDynamicRouter
          ? await permissionStore.generateRoutes('server', roleRouters as AppCustomRouteRecordRaw[])
          : await permissionStore.generateRoutes('frontEnd', roleRouters as string[])
      } else {
        await permissionStore.generateRoutes('static', undefined, currentRole)
      }

      permissionStore.getAddRouters.forEach((route) => {
        router.addRoute(route as unknown as RouteRecordRaw) // 动态添加可访问路由表
      })
      const redirectPath = from.query.redirect || to.path
      const redirect = decodeURIComponent(redirectPath as string)
      const nextData = to.path === redirect ? { ...to, replace: true } : { path: redirect }
      permissionStore.setIsAddRouters(true)
      next(to.path === '/' ? { path: defaultPath, replace: true } : nextData)
    }
  } else {
    /* 前缀匹配，不是精确匹配。
     *
     * 邀请页的路径是 /invite/<token>，而白名单里写的是 /invite。
     * 用 indexOf(to.path) 的话永远匹配不上——**白名单加了却不生效**，
     * 而且不报错：收件人点开链接被弹回登录页，看起来像链接坏了。
     *
     * 用 startsWith 时要带上分隔符判断，否则 /login-anything 也会被放行。 */
    const allowlisted = NO_REDIRECT_WHITE_LIST.some(
      (item) => to.path === item || to.path.startsWith(`${item}/`)
    )
    if (allowlisted) {
      next()
    } else {
      next(`/login?redirect=${to.path}`) // 否则全部重定向到登录页
    }
  }
})

router.afterEach((to) => {
  useTitle(to?.meta?.title as string)
  done() // 结束Progress
  loadDone()
})

/** 发版之后，开着旧页面的用户下一次路由跳转必然白屏——这里兜住。
 *
 * 每次构建 chunk 文件名的哈希全变，旧 chunk 在部署时被删除。而用户手上的
 * index.html 还是上一版的，它记的还是旧名字；一跳到尚未加载过的路由，
 * 就去要一个已经不存在的 chunk：
 *
 *   Failed to fetch dynamically imported module: /assets/Login-CjKYWBpL.js
 *
 * 后果不是报错，是**那个路由什么都渲染不出来**。2026-08-15 实测：部署后点退出
 * 登录，落到一片空白的登录页——标题在、表单没有，除了硬刷新没有出路，
 * 而普通用户不会知道要硬刷。
 *
 * 早前修 nginx 时已经把「返回 HTML 冒充 JS」改成干净的 404（错误信息不再误导），
 * 但「前端据此自愈」这一半一直没做。现在补上：重载一次页面就能拿到新的
 * index.html 和新的 chunk 名。
 *
 * 用 sessionStorage 打标记防死循环——万一重载后仍然失败（比如资源真的缺失），
 * 就不再自动重载，改为如实报错，免得把用户关进无限刷新里。
 */
const CHUNK_RELOAD_FLAG = 'aicheck:chunk-reloaded-at'
const CHUNK_RELOAD_COOLDOWN_MS = 60_000

const isStaleChunkError = (error: unknown): boolean => {
  const message = String((error as Error)?.message || error || '')
  return (
    message.includes('Failed to fetch dynamically imported module') ||
    message.includes('Importing a module script failed') ||
    message.includes('error loading dynamically imported module')
  )
}

router.onError((error) => {
  if (!isStaleChunkError(error)) return
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_FLAG) || 0)
  if (Date.now() - last < CHUNK_RELOAD_COOLDOWN_MS) {
    // 刚重载过还是失败，说明不是版本错位。别再刷了，把真相留在控制台。
    console.error('[aicheck] 资源加载失败，且刚刚已重载过一次，不再自动重试。', error)
    return
  }
  sessionStorage.setItem(CHUNK_RELOAD_FLAG, String(Date.now()))
  window.location.reload()
})
