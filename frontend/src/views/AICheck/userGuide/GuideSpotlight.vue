<script setup lang="ts">
/* 高亮层：框出页面上的一块，旁边一句话；引导时带「上一步 / 下一步」。
 * 点暗处或按 Esc 退出。框的位置跟着滚动和窗口大小走。 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { closeSpotlight, measureSpotlight, moveGuideTour, spotlight } from './useUserGuide'

const router = useRouter()
const bubbleRef = ref<HTMLElement>()
const GUTTER = 16
const GAP = 12
const BUBBLE_HEIGHT_GUESS = 140
/* 提示框真实高度：字多时比估的高，按估值摆会把按钮挤出屏幕 */
const bubbleHeight = ref(BUBBLE_HEIGHT_GUESS)
let bubbleObserver: ResizeObserver | undefined

const isTour = computed(() => spotlight.steps.length > 1)
const isLast = computed(() => spotlight.index >= spotlight.steps.length - 1)

const ringStyle = computed(() => {
  const rect = spotlight.rect
  if (!rect) return {}
  return {
    top: `${rect.top}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`
  }
})

/* 框外压暗用四块半透明板拼出来：一圈超大 box-shadow 在部分浏览器里画不出来 */
const shades = computed(() => {
  const rect = spotlight.rect
  if (!rect) return []
  const top = Math.max(0, rect.top)
  const bottom = Math.max(top, rect.top + rect.height)
  const left = Math.max(0, rect.left)
  const right = Math.max(left, rect.left + rect.width)
  return [
    { key: 'top', style: { top: '0', left: '0', right: '0', height: `${top}px` } },
    { key: 'bottom', style: { top: `${bottom}px`, left: '0', right: '0', bottom: '0' } },
    {
      key: 'left',
      style: { top: `${top}px`, left: '0', width: `${left}px`, height: `${bottom - top}px` }
    },
    {
      key: 'right',
      style: { top: `${top}px`, left: `${right}px`, right: '0', height: `${bottom - top}px` }
    }
  ]
})

const bubbleStyle = computed(() => {
  const rect = spotlight.rect
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const width = Math.min(340, viewportWidth - GUTTER * 2)
  const height = bubbleHeight.value
  if (!rect) {
    return {
      width: `${width}px`,
      left: `${(viewportWidth - width) / 2}px`,
      top: `${Math.max(GUTTER, viewportHeight / 2 - height / 2)}px`
    }
  }
  const left = Math.min(
    Math.max(GUTTER, rect.left + rect.width / 2 - width / 2),
    viewportWidth - width - GUTTER
  )
  const below = rect.top + rect.height + GAP
  const fitsBelow = below + height <= viewportHeight - GUTTER
  const fitsAbove = rect.top - GAP - height >= GUTTER
  // 目标比屏幕还高时，提示贴在屏幕下方，不盖住正中间
  const top = fitsBelow
    ? below
    : fitsAbove
      ? rect.top - GAP - height
      : viewportHeight - height - GUTTER
  const maxTop = viewportHeight - height - GUTTER
  return {
    width: `${width}px`,
    left: `${left}px`,
    top: `${Math.max(GUTTER, Math.min(top, maxTop))}px`
  }
})

const next = () => moveGuideTour(router, 1)
const previous = () => moveGuideTour(router, -1)

const onKeydown = (event: KeyboardEvent) => {
  if (!spotlight.active) return
  if (event.key === 'Escape') closeSpotlight()
}
const onViewportChange = () => {
  if (spotlight.active) measureSpotlight()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
  if (typeof ResizeObserver !== 'undefined') {
    bubbleObserver = new ResizeObserver(() => {
      if (bubbleRef.value) bubbleHeight.value = bubbleRef.value.offsetHeight || BUBBLE_HEIGHT_GUESS
    })
    if (bubbleRef.value) bubbleObserver.observe(bubbleRef.value)
  }
})
// 提示框随引导开关出现、消失，每次出现都重新盯它的高度
watch(bubbleRef, (element, previous) => {
  if (previous) bubbleObserver?.unobserve(previous)
  if (element) bubbleObserver?.observe(element)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  bubbleObserver?.disconnect()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="spotlight.active" class="guide-spotlight" role="dialog" aria-modal="true">
      <button
        type="button"
        :class="['guide-spotlight-backdrop', { 'is-dim': !spotlight.rect }]"
        aria-label="关闭引导"
        @click="closeSpotlight"
      ></button>
      <div
        v-for="shade in shades"
        :key="shade.key"
        class="guide-spotlight-shade"
        :style="shade.style"
        aria-hidden="true"
      ></div>
      <div v-if="spotlight.rect" class="guide-spotlight-ring" :style="ringStyle"></div>
      <div ref="bubbleRef" class="guide-spotlight-bubble" :style="bubbleStyle" aria-live="polite">
        <small v-if="isTour" class="guide-spotlight-step">
          第 {{ spotlight.index + 1 }} / {{ spotlight.steps.length }} 步
        </small>
        <p>{{ spotlight.hint }}</p>
        <div class="guide-spotlight-actions">
          <button v-if="isTour" type="button" class="is-quiet" @click="closeSpotlight">
            结束
          </button>
          <span class="guide-spotlight-spacer"></span>
          <button v-if="isTour && spotlight.index > 0" type="button" @click="previous">
            上一步
          </button>
          <button v-if="isTour && !isLast" type="button" class="is-primary" @click="next">
            下一步
          </button>
          <button v-else type="button" class="is-primary" @click="closeSpotlight">知道了</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.guide-spotlight {
  position: fixed;
  z-index: 3000;
  inset: 0;
}

.guide-spotlight-backdrop {
  position: absolute;
  padding: 0;
  cursor: default;
  background: transparent;
  border: 0;
  inset: 0;
}

.guide-spotlight-backdrop.is-dim {
  background: rgb(15 23 42 / 45%);
}

.guide-spotlight-shade {
  position: absolute;
  pointer-events: none;
  background: rgb(15 23 42 / 45%);
}

.guide-spotlight-ring {
  position: absolute;
  pointer-events: none;
  border: 2px solid #2f6bff;
  border-radius: 12px;
  box-shadow: 0 0 0 4px rgb(47 107 255 / 25%);
  transition:
    top 0.2s ease,
    left 0.2s ease,
    width 0.2s ease,
    height 0.2s ease;
}

.guide-spotlight-bubble {
  position: absolute;
  display: grid;
  padding: 14px 16px 12px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgb(15 23 42 / 24%);
  gap: 8px;
}

.guide-spotlight-step {
  font-size: 12px;
  color: #667085;
}

.guide-spotlight-bubble p {
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  color: #172033;
}

.guide-spotlight-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.guide-spotlight-spacer {
  flex: 1;
}

.guide-spotlight-actions button {
  min-height: 36px;
  padding: 0 14px;
  font: inherit;
  font-size: 14px;
  color: #1d3f8f;
  cursor: pointer;
  background: #f3f7ff;
  border: 1px solid #d6e2fb;
  border-radius: 8px;
}

.guide-spotlight-actions button.is-primary {
  color: #fff;
  background: #2f6bff;
  border-color: #2f6bff;
}

.guide-spotlight-actions button.is-quiet {
  padding: 0 4px;
  color: #667085;
  background: none;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .guide-spotlight-ring {
    transition: none;
  }
}
</style>
