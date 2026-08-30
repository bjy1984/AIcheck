<script setup lang="ts">
/**
 * 条款/分块正文渲染：按 blockType 分支。
 *
 * - equation → KaTeX（trust:false，失败降级为原始 LaTeX 文本）
 * - table → StructuredTable（结构化行，不用 html）
 * - 其它 → 纯文本插值
 *
 * basis 卡片的 summary 装的是用途文案（「直接监检依据」），不是条款正文；
 * 公式/表格出现在条款 OCR 切片与检索命中上。
 */
import { computed, onMounted, ref, watch } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import StructuredTable from './StructuredTable.vue'
import { normalizedEquationSource } from './equationPresentation'

const props = defineProps<{
  text?: string
  blockType?: string
  latex?: string
  caption?: string
  tableColumns?: string[]
  tableRows?: Array<Record<string, string>>
  tableHeaderReliable?: boolean
}>()

const equationHtml = ref('')
const equationFailed = ref(false)

const normalizedType = computed(() =>
  String(props.blockType || '')
    .trim()
    .toLowerCase()
)
const isEquation = computed(() =>
  ['equation', 'interline_equation', 'inline_equation'].includes(normalizedType.value)
)
const isTable = computed(
  () =>
    normalizedType.value === 'table' &&
    Array.isArray(props.tableColumns) &&
    props.tableColumns.length > 0 &&
    Array.isArray(props.tableRows)
)

const equationSource = computed(() => {
  const raw = String(props.latex || props.text || '').trim()
  return normalizedEquationSource(raw)
})

const renderEquation = () => {
  equationFailed.value = false
  equationHtml.value = ''
  if (!isEquation.value || !equationSource.value) return
  try {
    equationHtml.value = katex.renderToString(equationSource.value, {
      displayMode: true,
      throwOnError: false,
      trust: false,
      strict: 'ignore'
    })
  } catch {
    equationFailed.value = true
  }
}

onMounted(renderEquation)
watch([isEquation, equationSource], renderEquation)
</script>

<template>
  <div class="clause-content">
    <div v-if="isEquation" class="clause-equation">
      <!-- KaTeX 自建 DOM，不是引擎 html；trust:false 禁掉 \href 等能造 URL 的命令 -->
      <div
        v-if="equationHtml && !equationFailed"
        class="clause-equation-math"
        v-html="equationHtml"
      />
      <pre v-else class="clause-equation-fallback">{{ latex || text }}</pre>
    </div>
    <StructuredTable
      v-else-if="isTable"
      :column-names="tableColumns || []"
      :rows="tableRows || []"
      :header-reliable="tableHeaderReliable"
      :caption="caption"
    />
    <p v-else class="clause-text">{{ text }}</p>
  </div>
</template>

<style scoped>
.clause-content {
  min-width: 0;
}

.clause-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.clause-equation-math {
  overflow-x: auto;
  padding: 4px 0;
}

.clause-equation {
  min-width: 0;
  overflow: hidden;
}

.clause-equation-math :deep(.katex-mathml) {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.clause-equation-fallback {
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
}
</style>
