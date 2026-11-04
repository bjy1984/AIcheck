<script lang="ts">
// 模块级计数：每个头像实例的渐变 / 裁剪 id 各不相同
let seed = 0
</script>

<script setup lang="ts">
/**
 * 顶栏用户头像（2026-11-03 用户：原来是一个空的渐变圆，换成 SVG 图标）。
 *
 * 品牌蓝渐变底 + 白色半身像；监检身份右下角加一枚盾牌对勾徽标（监检是放行的那一方）。
 * 图形按 32px 画、1px 对齐，缩放到 24–40px 都清楚；渐变 id 每个实例独立，同页多个头像不串色。
 */
const props = withDefaults(defineProps<{ size?: number; badge?: boolean; label?: string }>(), {
  size: 32,
  badge: false,
  label: ''
})
const uid = `ua-${++seed}`
</script>

<template>
  <svg
    class="user-avatar-icon"
    :width="props.size"
    :height="props.size"
    viewBox="0 0 32 32"
    :role="props.label ? 'img' : undefined"
    :aria-label="props.label || undefined"
    :aria-hidden="props.label ? undefined : 'true'"
  >
    <defs>
      <linearGradient :id="`${uid}-bg`" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#5b8ff9" />
        <stop offset="1" stop-color="#1e5ec8" />
      </linearGradient>
      <clipPath :id="`${uid}-clip`">
        <circle cx="16" cy="16" r="16" />
      </clipPath>
    </defs>
    <circle cx="16" cy="16" r="16" :fill="`url(#${uid}-bg)`" />
    <g :clip-path="`url(#${uid}-clip)`" fill="#fff">
      <circle cx="16" cy="12.5" r="5.25" />
      <path d="M5.5 29.5c0-5.8 4.7-10 10.5-10s10.5 4.2 10.5 10V33h-21z" opacity="0.92" />
    </g>
    <!-- 高光：一道很淡的上缘反光，免得平涂显得廉价 -->
    <path
      d="M5 10.5A12.5 12.5 0 0 1 27 10.5"
      fill="none"
      stroke="#fff"
      stroke-opacity="0.18"
      stroke-width="1.5"
      stroke-linecap="round"
    />
    <g v-if="props.badge" transform="translate(20.5 19.5)">
      <path
        d="M5.75 0.75 10.25 2.4v3.3c0 2.9-1.9 4.9-4.5 5.8-2.6-0.9-4.5-2.9-4.5-5.8V2.4z"
        fill="#16a34a"
        stroke="#fff"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <path
        d="m3.7 6 1.5 1.5 2.9-3"
        fill="none"
        stroke="#fff"
        stroke-width="1.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </g>
  </svg>
</template>

<style scoped>
.user-avatar-icon {
  display: block;
  flex: 0 0 auto;
  overflow: visible;
  filter: drop-shadow(0 1px 2px rgb(30 94 200 / 22%));
}
</style>
