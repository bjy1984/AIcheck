<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import echarts from '@/plugins/echarts'
import { debounce } from 'lodash-es'
import 'echarts-wordcloud'
import { propTypes } from '@/utils/propTypes'
import {
  computed,
  PropType,
  ref,
  unref,
  watch,
  nextTick,
  onMounted,
  onBeforeUnmount,
  onActivated
} from 'vue'
import { useAppStore } from '@/store/modules/app'
import { isString } from '@/utils/is'
import { useDesign } from '@/hooks/web/useDesign'

const { getPrefixCls, variables } = useDesign()

const prefixCls = getPrefixCls('echart')

const appStore = useAppStore()

const props = defineProps({
  options: {
    type: Object as PropType<EChartsOption>,
    required: true
  },
  width: propTypes.oneOfType([Number, String]).def('100%'),
  height: propTypes.oneOfType([Number, String]).def('500px')
})

const isDark = computed(() => appStore.getIsDark)

const theme = computed<boolean | 'auto'>(() => (unref(isDark) ? true : 'auto'))

const options = computed(() => {
  return {
    ...props.options,
    darkMode: unref(theme)
  }
})

const elRef = ref<ElRef>()

let echartRef: Nullable<echarts.ECharts> = null

const contentEl = ref<Element>()
let chartResizeObserver: ResizeObserver | null = null

const styles = computed(() => {
  const width = isString(props.width) ? props.width : `${props.width}px`
  const height = isString(props.height) ? props.height : `${props.height}px`

  return {
    width,
    height
  }
})

const initChart = () => {
  if (unref(elRef) && props.options) {
    echartRef = echarts.init(unref(elRef) as HTMLElement)
    echartRef?.setOption(unref(options))
  }
}

watch(
  () => options.value,
  (options) => {
    if (echartRef) {
      echartRef?.setOption(options)
    }
  },
  {
    deep: true
  }
)

const resizeChart = () => {
  if (echartRef) {
    const el = unref(elRef) as HTMLElement | undefined
    const rect = el?.getBoundingClientRect()
    if (rect && rect.width > 0 && rect.height > 0) {
      echartRef.resize({ width: Math.floor(rect.width), height: Math.floor(rect.height) })
      return
    }
    echartRef.resize()
  }
}

const resizeHandler = debounce(() => {
  resizeChart()
}, 100)

watch(
  () => [props.width, props.height],
  () => {
    nextTick(() => resizeHandler())
  },
  { flush: 'post' }
)

const contentResizeHandler = async (e: TransitionEvent) => {
  if (e.propertyName === 'width') {
    resizeHandler()
  }
}

onMounted(() => {
  setTimeout(() => {
    initChart()
    if (unref(elRef) && typeof ResizeObserver !== 'undefined') {
      chartResizeObserver = new ResizeObserver(() => resizeHandler())
      chartResizeObserver.observe(unref(elRef) as HTMLElement)
      const parentElement = (unref(elRef) as HTMLElement).parentElement
      if (parentElement) {
        chartResizeObserver.observe(parentElement)
      }
    }
  }, 0)

  window.addEventListener('resize', resizeHandler)

  contentEl.value = document.getElementsByClassName(`${variables.namespace}-layout-content`)[0]
  unref(contentEl) &&
    (unref(contentEl) as Element).addEventListener('transitionend', contentResizeHandler)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeHandler)
  chartResizeObserver?.disconnect()
  chartResizeObserver = null
  unref(contentEl) &&
    (unref(contentEl) as Element).removeEventListener('transitionend', contentResizeHandler)
})

onActivated(() => {
  nextTick(() => resizeChart())
})
</script>

<template>
  <div ref="elRef" :class="[$attrs.class, prefixCls]" :style="styles"></div>
</template>
