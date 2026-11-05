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

const WAIT_TIMEOUT_MS = 6000
const WAIT_INTERVAL_MS = 120
const PAD = 6

export const guideSelector = (target: string) => `[data-guide="${target}"]`

const isShown = (element: Element) => {
  const rect = element.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0
}

/** 页面是异步加载的：等元素出现，最多等 6 秒。 */
export const waitForGuideTarget = (target: string, timeout = WAIT_TIMEOUT_MS) =>
  new Promise<Element | null>((resolve) => {
    const started = Date.now()
    const tick = () => {
      const element = document.querySelector(guideSelector(target))
      if (element && isShown(element)) return resolve(element)
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
  const rect = currentElement.getBoundingClientRect()
  spotlight.rect = {
    top: rect.top - PAD,
    left: rect.left - PAD,
    width: rect.width + PAD * 2,
    height: rect.height + PAD * 2
  }
}

const showSpot = async (router: Router | undefined, spot: GuideSpot) => {
  const id = ++runId
  if (spot.path && router && router.currentRoute.value.path !== spot.path) {
    await router.push(spot.path).catch(() => undefined)
  }
  const element = await waitForGuideTarget(spot.target)
  if (id !== runId) return
  currentElement = element
  spotlight.hint = element ? spot.hint : spot.emptyHint || `${spot.hint}（这一块现在没有显示）`
  spotlight.missing = !element
  spotlight.active = true
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // 平滑滚动要一点时间，先量一次，滚完再量一次
    measureSpotlight()
    window.setTimeout(measureSpotlight, 450)
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
