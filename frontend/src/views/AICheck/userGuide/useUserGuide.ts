/** 使用帮助的开关、「带我去」和「开始引导」。
 *
 * 状态放在模块里：帮助面板和高亮层都挂在 AICheckStaticLayout 上，
 * 账号菜单里的「使用帮助」只需要调 openUserGuide()，不用层层传事件。
 *
 * 「带我去」= 关掉面板 → 需要的话切路由 → 等那一块出现 → 滚过去 → 高亮并说一句话。
 * 那一块此刻没显示（比如没有被退回的资料）就照实说，不假装找到了。 */
import { reactive, ref } from 'vue'
import type { Router } from 'vue-router'
import type { GuideSpot } from './guideTypes'

export const guideOpen = ref(false)

export const openUserGuide = () => {
  guideOpen.value = true
}

export type SpotlightRect = { top: number; left: number; width: number; height: number }

export const spotlight = reactive({
  active: false,
  /** 找不到元素时为 null：高亮层只显示提示，不画框 */
  rect: null as SpotlightRect | null,
  hint: '',
  missing: false,
  steps: [] as GuideSpot[],
  index: 0
})

let currentElement: Element | null = null
let runId = 0

/* 换页面时页面要异步加载，多等一会儿；同一页面里的下一步，元素没有就是真没有（比如没有被退回的资料），
 * 1.5 秒就照实说，别让人对着上一步的提示干等 6 秒（11-12 施工方手机实测） */
const WAIT_TIMEOUT_MS = 6000
const SAME_PAGE_TIMEOUT_MS = 1500
const WAIT_INTERVAL_MS = 120
const PAD = 6

export const guideSelector = (target: string) => `[data-guide="${target}"]`

/* 元素的可见范围。display: contents 的元素自己没有盒子（量出来是 0），
 * 要拿子元素拼起来：施工方手机顶栏的项目名就是这样，原来引导第一步一直说「没有显示」 */
const rectOf = (element: Element): DOMRect | null => {
  const own = element.getBoundingClientRect()
  if (own.width > 0 && own.height > 0) return own
  if (getComputedStyle(element).display !== 'contents') return null
  const parts = Array.from(element.children)
    .map(rectOf)
    .filter((rect): rect is DOMRect => Boolean(rect))
  if (!parts.length) return null
  const top = Math.min(...parts.map((rect) => rect.top))
  const left = Math.min(...parts.map((rect) => rect.left))
  const bottom = Math.max(...parts.map((rect) => rect.bottom))
  const right = Math.max(...parts.map((rect) => rect.right))
  return new DOMRect(left, top, right - left, bottom - top)
}

const isShown = (element: Element) => Boolean(rectOf(element))

/** 能滚动定位的元素：display: contents 自己滚不过去，用第一个看得见的子元素 */
const scrollTargetOf = (element: Element): Element => {
  if (element.getBoundingClientRect().height > 0) return element
  return Array.from(element.children).find((child) => rectOf(child)) || element
}

/** 页面是异步加载的：等元素出现，最多等 6 秒。 */
export const waitForGuideTarget = (target: string, timeout = WAIT_TIMEOUT_MS) =>
  new Promise<Element | null>((resolve) => {
    const started = Date.now()
    const tick = () => {
      // 同一个锚点可能有几处（电脑版、手机版各一处），取看得见的那个
      const element = Array.from(document.querySelectorAll(guideSelector(target))).find(isShown)
      if (element) return resolve(element)
      if (Date.now() - started >= timeout) return resolve(null)
      window.setTimeout(tick, WAIT_INTERVAL_MS)
    }
    tick()
  })

export const measureSpotlight = () => {
  if (!currentElement || !document.contains(currentElement)) {
    spotlight.rect = null
    return
  }
  const rect = rectOf(currentElement)
  if (!rect) {
    spotlight.rect = null
    return
  }
  spotlight.rect = {
    top: rect.top - PAD,
    left: rect.left - PAD,
    width: rect.width + PAD * 2,
    height: rect.height + PAD * 2
  }
}

const showSpot = async (router: Router | undefined, spot: GuideSpot) => {
  const id = ++runId
  const changesPage = Boolean(spot.path && router && router.currentRoute.value.path !== spot.path)
  // 先换上这一步的话，框等找到了再画：不然找元素的这段时间还显示着上一步的提示
  currentElement = null
  spotlight.rect = null
  spotlight.hint = spot.hint
  spotlight.missing = false
  if (changesPage && spot.path && router) {
    await router.push(spot.path).catch(() => undefined)
  }
  const element = await waitForGuideTarget(
    spot.target,
    changesPage || !spotlight.active ? WAIT_TIMEOUT_MS : SAME_PAGE_TIMEOUT_MS
  )
  if (id !== runId) return
  currentElement = element
  spotlight.hint = element ? spot.hint : spot.emptyHint || `${spot.hint}（这一块现在没有显示）`
  spotlight.missing = !element
  spotlight.active = true
  if (element) {
    scrollTargetOf(element).scrollIntoView({ behavior: 'smooth', block: 'center' })
    // 平滑滚动要一点时间（从页底回到顶部要近 1 秒），先量一次，滚的途中和滚完再量
    measureSpotlight()
    window.setTimeout(measureSpotlight, 450)
    window.setTimeout(measureSpotlight, 1000)
  } else {
    spotlight.rect = null
  }
}

/** 「带我去」：只高亮一块。 */
export const jumpToGuideSpot = async (router: Router | undefined, spot: GuideSpot) => {
  guideOpen.value = false
  spotlight.steps = [spot]
  spotlight.index = 0
  await showSpot(router, spot)
}

/** 「开始引导」：按顺序一块一块讲。 */
export const startGuideTour = async (router: Router | undefined, steps: GuideSpot[]) => {
  if (!steps.length) return
  guideOpen.value = false
  spotlight.steps = steps
  spotlight.index = 0
  await showSpot(router, steps[0])
}

export const moveGuideTour = async (router: Router | undefined, delta: number) => {
  const next = spotlight.index + delta
  if (next < 0 || next >= spotlight.steps.length) {
    closeSpotlight()
    return
  }
  spotlight.index = next
  await showSpot(router, spotlight.steps[next])
}

export const closeSpotlight = () => {
  runId += 1
  currentElement = null
  spotlight.active = false
  spotlight.rect = null
  spotlight.steps = []
  spotlight.index = 0
}
