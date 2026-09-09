<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElAlert, ElButton } from 'element-plus'
import {
  version,
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
  type RenderTask
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerUrl
const props = defineProps<{ src: string; pageNo?: number; fileName?: string }>()
const canvas = ref<HTMLCanvasElement>()
const pdf = shallowRef<PDFDocumentProxy>()
const currentPage = ref(1)
const count = ref(0)
const loading = ref(false)
const error = ref('')
let generation = 0
let renderTask: RenderTask | undefined
let loadingTask: ReturnType<typeof getDocument> | undefined

const renderPage = async (pageNo: number) => {
  const document = pdf.value
  if (!document || loading.value) return
  const attempt = ++generation
  loading.value = true
  error.value = ''
  renderTask?.cancel()
  try {
    if (!Number.isInteger(pageNo) || pageNo < 1 || pageNo > document.numPages)
      throw new Error('引用页码不在这份文件中，请核对引用；系统不会跳到其他页替代。')
    const page = await document.getPage(pageNo)
    if (attempt !== generation) return
    await nextTick()
    const target = canvas.value
    if (!target) return
    const size = page.getViewport({ scale: 1 })
    if (![size.width, size.height].every((value) => Number.isFinite(value) && value > 0))
      throw new Error('文件页面尺寸无效，请核对原文件。')
    const viewport = page.getViewport({
      scale: Math.min(1.5, 4096 / Math.max(size.width, size.height))
    })
    target.width = viewport.width
    target.height = viewport.height
    const context = target.getContext('2d')
    if (!context) throw new Error('当前浏览器无法显示文件页面。')
    renderTask = page.render({ canvas: target, canvasContext: context, viewport })
    await renderTask.promise
    if (attempt === generation) currentPage.value = pageNo
  } catch (cause) {
    if (attempt === generation)
      error.value = cause instanceof Error ? cause.message : '这一页暂时无法显示，请重试。'
  } finally {
    if (attempt === generation) loading.value = false
  }
}
const clear = () => {
  generation++
  renderTask?.cancel()
  renderTask = undefined
  void loadingTask?.destroy()
  loadingTask = undefined
  pdf.value = undefined
  count.value = 0
  loading.value = false
}
const load = async () => {
  clear()
  const attempt = generation
  error.value = ''
  if (!props.src) return
  loading.value = true
  try {
    const assets = `${import.meta.env.BASE_URL}pdf-assets/${version}/`
    loadingTask = getDocument({
      url: props.src.split('#')[0],
      cMapUrl: `${assets}cmaps/`,
      cMapPacked: true,
      standardFontDataUrl: `${assets}standard_fonts/`,
      wasmUrl: `${assets}wasm/`,
      iccUrl: `${assets}iccs/`
    })
    const document = await loadingTask.promise
    if (attempt !== generation) return
    pdf.value = document
    count.value = document.numPages
    loading.value = false
    await renderPage(props.pageNo || 1)
  } catch {
    if (attempt === generation) {
      error.value = '这份PDF暂时无法显示。请重试；如果仍失败，请联系资料管理员核对文件。'
      loading.value = false
    }
  }
}
watch(() => [props.src, props.pageNo], load, { immediate: true })
onBeforeUnmount(clear)
</script>

<template>
  <section class="pdf-evidence" aria-label="PDF原文" :aria-busy="loading">
    <div class="pdf-page-actions">
      <ElButton
        :disabled="loading || !!error || currentPage <= 1"
        @click="renderPage(currentPage - 1)"
        >上一页</ElButton
      >
      <span role="status">{{ loading ? '正在显示原文…' : `第 ${currentPage} / ${count} 页` }}</span>
      <ElButton
        :disabled="loading || !!error || currentPage >= count"
        @click="renderPage(currentPage + 1)"
        >下一页</ElButton
      >
      <ElButton
        v-if="currentPage !== (pageNo || 1)"
        :disabled="loading"
        @click="renderPage(pageNo || 1)"
        >回到引用页</ElButton
      >
    </div>
    <ElAlert v-if="error" :title="error" type="warning" :closable="false" />
    <ElButton v-if="error" :loading="loading" @click="load">重试显示PDF</ElButton>
    <canvas
      v-show="!error"
      ref="canvas"
      role="img"
      :aria-label="`${fileName || 'PDF原文'}，第 ${currentPage} 页`"
    ></canvas>
  </section>
</template>

<style scoped>
.pdf-evidence {
  display: grid;
  gap: 12px;
  width: 100%;
}

.pdf-page-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.pdf-page-actions :deep(.el-button) {
  min-height: 44px;
  margin: 0;
}

canvas {
  width: 100%;
  height: auto;
  background: white;
}
</style>
