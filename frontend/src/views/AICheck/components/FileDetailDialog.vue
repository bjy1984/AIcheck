<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElTable,
  ElTableColumn,
  ElTabPane,
  ElTabs,
  ElTag
} from 'element-plus'
import { getDocumentOriginalBlobApi } from '@/api/aicheck'
import type { DocumentDetailPayload } from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { formatConfidence } from '@/utils/confidence'
import { bboxToPercentStyle, normalizeBbox } from '@/utils/bboxHighlight'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  detail?: DocumentDetailPayload
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  preview: [url: string]
  download: [url: string]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const document = computed(() => props.detail?.document)
const currentVersion = computed(() => props.detail?.currentVersion)
const ocrReadiness = computed(() => props.detail?.document?.ocrReadiness)
const ocrReadinessLabel = computed(() => {
  const labels: Record<string, string> = {
    not_started: '待处理',
    queued: '排队中',
    processing: '处理中',
    ready: '证据就绪',
    incomplete: '抽取不完整',
    inconsistent: '状态异常',
    failed: '处理失败'
  }
  return labels[String(ocrReadiness.value?.status || '')] || '等待产物校验'
})
const bindings = computed(() => props.detail?.bindings || [])
const extractedFields = computed(() => props.detail?.extractedFields || [])
const evidenceLinks = computed(() => props.detail?.evidenceLinks || [])
const versions = computed(() => props.detail?.versions || [])
const preview = computed(() => props.detail?.preview)
const download = computed(() => props.detail?.download)
const previewObjectUrl = ref('')
const previewLoadingOriginal = ref(false)
const previewOriginalError = ref('')

const fileSizeText = computed(() => {
  const size = currentVersion.value?.fileSize || download.value?.fileSize || 0
  if (!size) return '-'
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
})

const previewTitle = computed(() => {
  if (!preview.value) return '预览地址未生成'
  const labelMap: Record<string, string> = {
    pdf: 'PDF 预览',
    office: 'Office 预览',
    image: '图片预览',
    unsupported: '不支持预览'
  }
  return labelMap[preview.value.previewType] || '文件预览'
})

const previewAvailable = computed(
  () => !!preview.value?.url && preview.value.previewType !== 'unsupported'
)
const previewIsImage = computed(() => preview.value?.previewType === 'image')
const previewIsPdf = computed(() => preview.value?.previewType === 'pdf')
/** 仅 PDF/图片可安全内嵌；Office 等放入 iframe 会触发浏览器自动下载。 */
const previewBrowserInline = computed(() => previewIsPdf.value || previewIsImage.value)
const previewEmbeddable = computed(() => {
  const url = String(preview.value?.url || '')
  return previewAvailable.value && previewBrowserInline.value && !url.startsWith('mock://')
})
const previewRequiresBlob = computed(
  () => previewEmbeddable.value && String(preview.value?.url || '').startsWith('/api/')
)
const previewFrameUrl = computed(() => {
  const url = String(preview.value?.url || '')
  if (previewRequiresBlob.value) return previewObjectUrl.value
  return previewObjectUrl.value || url
})
const previewUnavailableText = computed(() => {
  const url = String(preview.value?.url || '')
  if (!url) return '当前文件详情没有返回原文地址。'
  if (url.startsWith('mock://'))
    return '当前接口返回的是 mock 占位地址，还没有拿到可预览的真实原文。'
  if (preview.value?.previewType === 'office')
    return 'Word/Excel 等 Office 文件暂不支持在线预览，请使用右上角「下载」查看原文。'
  if (preview.value?.previewType === 'unsupported') return '当前文件类型暂不支持在线预览。'
  return '当前文件没有可预览的真实原文。'
})

const revokePreviewObjectUrl = () => {
  if (!previewObjectUrl.value) return
  URL.revokeObjectURL(previewObjectUrl.value)
  previewObjectUrl.value = ''
}

const loadPreviewOriginal = async () => {
  revokePreviewObjectUrl()
  previewOriginalError.value = ''
  const url = String(preview.value?.url || '')
  if (!previewRequiresBlob.value) return
  previewLoadingOriginal.value = true
  try {
    const res = await getDocumentOriginalBlobApi(url)
    previewObjectUrl.value = URL.createObjectURL(res.data)
  } catch (error) {
    previewOriginalError.value = getAicheckErrorMessage(
      error,
      '原文预览加载失败，请尝试下载后查看。'
    )
  } finally {
    previewLoadingOriginal.value = false
  }
}

const handlePreviewImageError = () => {
  previewOriginalError.value = '图片预览加载失败，请尝试下载后查看。'
}

watch(
  () => [visible.value, preview.value?.url, preview.value?.previewType] as const,
  ([open]) => {
    if (open) {
      void loadPreviewOriginal()
    } else {
      revokePreviewObjectUrl()
      previewOriginalError.value = ''
    }
  }
)

onBeforeUnmount(() => {
  revokePreviewObjectUrl()
})

const confidenceText = (confidence?: number) => {
  return formatConfidence(confidence)
}

/* ---------------- 证据定位（X-1 / X-2） ----------------
 * 监检的核心动作是「看着原文核对字段」。原先字段表在预览下方，两者无法同屏对照；
 * 而后端为可定位性付了完整代价（bbox 必填、bboxCoverage 就绪度指标），前端却没画。
 *
 * 能做到什么，取决于预览载体：
 *   图片 —— <img> 有 naturalWidth/Height，bbox 像素坐标可换算成百分比，能画真高亮；
 *   PDF  —— 走浏览器原生 viewer 的 <iframe>，内部布局与缩放不可控，画不了框；
 *           但 #page=N 锚点能跳页，这已经省掉用户手动翻页。
 * 要在 PDF 上画框必须引入 pdf.js 自行渲染到 canvas，属独立技术选型，不在本次范围。
 */
type LocatableItem = {
  key: string
  label: string
  value: string
  pageNo?: number
  bbox?: number[]
  confidence?: number
  status?: string
  kind: 'field' | 'evidence'
}

const sideTab = ref('fields')
const activeLocateKey = ref('')
const previewNaturalSize = ref<{ width: number; height: number } | null>(null)

/** OCR 字段自身不带 bbox，坐标在它 evidenceLinkId 指向的证据链条目上。 */
const bboxByEvidenceId = computed(() => {
  const map = new Map<string, number[]>()
  for (const link of evidenceLinks.value) {
    const bbox = normalizeBbox(link.bbox as number[] | undefined)
    if (link.id && bbox) map.set(String(link.id), bbox)
  }
  return map
})

const locatableItems = computed<LocatableItem[]>(() => [
  ...extractedFields.value.map((field, index) => ({
    key: `field-${field.id || index}`,
    label: String(field.fieldName || '未命名字段'),
    value: String(field.fieldValue ?? ''),
    pageNo: field.pageNo,
    bbox: field.evidenceLinkId
      ? bboxByEvidenceId.value.get(String(field.evidenceLinkId))
      : undefined,
    confidence: field.confidence,
    status: field.reviewStatus,
    kind: 'field' as const
  })),
  ...evidenceLinks.value.map((link, index) => ({
    key: `evidence-${link.id || index}`,
    label: String(link.fieldName || link.objectType || '证据引用'),
    value: String(link.quotedText ?? ''),
    pageNo: link.pageNo,
    bbox: normalizeBbox(link.bbox as number[] | undefined),
    confidence: link.confidence,
    kind: 'evidence' as const
  }))
])

const activeLocatable = computed(() =>
  locatableItems.value.find((item) => item.key === activeLocateKey.value)
)

/** 图片预览下，把 bbox 像素坐标换算成相对定位样式。 */
const highlightStyle = computed(() =>
  previewIsImage.value
    ? bboxToPercentStyle(activeLocatable.value?.bbox, previewNaturalSize.value)
    : null
)

/** PDF 无法叠加高亮，改用 #page=N 跳页；图片直接靠 highlightStyle 画框。 */
const previewSrcWithPage = computed(() => {
  const base = previewFrameUrl.value
  if (!base || !previewIsPdf.value) return base
  const page = activeLocatable.value?.pageNo
  if (!page) return base
  return `${base.split('#')[0]}#page=${page}`
})

const locateHint = computed(() => {
  const item = activeLocatable.value
  if (!item) return ''
  if (!item.pageNo) return '该条证据未记录页码，无法定位到原文位置。'
  if (previewIsImage.value) {
    return item.bbox
      ? `已在原文第 ${item.pageNo} 页高亮该字段位置。`
      : `该条证据未记录坐标，只能定位到第 ${item.pageNo} 页。`
  }
  if (previewIsPdf.value) {
    return `已跳转到第 ${item.pageNo} 页。PDF 由浏览器内置阅读器渲染，暂不支持框选高亮。`
  }
  return `该条证据位于第 ${item.pageNo} 页。`
})

const handleLocate = (item: LocatableItem) => {
  activeLocateKey.value = activeLocateKey.value === item.key ? '' : item.key
}

const handlePreviewImageLoad = (event: Event) => {
  const image = event.target as HTMLImageElement
  previewNaturalSize.value = { width: image.naturalWidth, height: image.naturalHeight }
}

watch(visible, (open) => {
  if (!open) {
    activeLocateKey.value = ''
    previewNaturalSize.value = null
    sideTab.value = 'fields'
  }
})
</script>

<template>
  <ElDialog
    v-model="visible"
    title="文件详情"
    width="min(1400px, 92vw)"
    append-to-body
    class="file-dialog"
  >
    <div v-loading="loading" class="file-detail">
      <template v-if="detail && document">
        <div class="file-header">
          <div>
            <div class="file-title">{{ document.fileName }}</div>
            <div class="file-meta">
              {{ document.sourceOrgName }} · {{ document.uploaderName }} ·
              {{ document.updatedAt }}
            </div>
          </div>
          <div class="file-actions">
            <ElButton
              :disabled="!previewEmbeddable"
              @click="preview?.url && emit('preview', preview.url)"
            >
              预览
            </ElButton>
            <ElButton
              type="primary"
              :disabled="!download?.url"
              @click="download?.url && emit('download', download.url)"
            >
              下载
            </ElButton>
          </div>
        </div>

        <div class="file-layout">
          <div class="preview-shell">
            <div class="preview-toolbar">
              <span>{{ previewTitle }}</span>
              <ElTag v-if="preview?.readonly" size="small" type="success" effect="plain"
                >只读</ElTag
              >
            </div>
            <div v-if="locateHint" class="locate-hint">{{ locateHint }}</div>
            <div class="preview-body" :class="{ 'preview-body--disabled': !previewEmbeddable }">
              <template v-if="previewEmbeddable">
                <div class="preview-frame-host" v-loading="previewLoadingOriginal">
                  <ElAlert
                    v-if="previewOriginalError"
                    :title="previewOriginalError"
                    type="warning"
                    :closable="false"
                    show-icon
                  />
                  <div v-else-if="!previewFrameUrl" class="preview-placeholder">
                    原文预览加载中
                  </div>
                  <!-- 图片：bbox 可换算成百分比，叠一层高亮框 -->
                  <div v-else-if="previewIsImage" class="preview-image-stage">
                    <img
                      class="preview-image"
                      :src="previewFrameUrl"
                      :alt="document.fileName"
                      @load="handlePreviewImageLoad"
                      @error="handlePreviewImageError"
                    />
                    <span
                      v-if="highlightStyle"
                      class="preview-highlight"
                      :style="highlightStyle"
                    ></span>
                  </div>
                  <!-- PDF：浏览器内置阅读器，只能靠 #page= 跳页 -->
                  <iframe
                    v-else
                    class="preview-frame"
                    :src="previewSrcWithPage"
                    :title="document.fileName"
                  ></iframe>
                </div>
              </template>
              <ElAlert
                v-else
                :title="
                  preview?.previewType === 'office'
                    ? 'Office 文件不支持在线预览'
                    : '当前格式暂不支持在线预览'
                "
                :description="previewUnavailableText"
                type="warning"
                :closable="false"
                show-icon
              />
            </div>
          </div>

          <!-- 右侧不再放元数据摘要：核对字段才是主任务，元数据挪进「文件信息」页签 -->
          <div class="detail-side">
            <ElAlert
              v-if="ocrReadiness && ocrReadiness.status !== 'ready'"
              :title="`OCR ${ocrReadinessLabel}`"
              :description="
                ocrReadiness.blockingReasons?.[0]?.message || '当前文件暂不能作为可定位的正式证据。'
              "
              type="warning"
              :closable="false"
              show-icon
              class="side-alert"
            />
            <ElTabs v-model="sideTab" class="side-tabs">
              <ElTabPane :label="`识别字段 (${locatableItems.length})`" name="fields">
                <div v-if="!locatableItems.length" class="side-empty">
                  <ElEmpty :image-size="60" description="暂无识别字段" />
                </div>
                <ul v-else class="locate-list">
                  <li
                    v-for="item in locatableItems"
                    :key="item.key"
                    :class="['locate-item', { 'is-active': item.key === activeLocateKey }]"
                  >
                    <button
                      type="button"
                      class="locate-button"
                      :aria-pressed="item.key === activeLocateKey"
                      @click="handleLocate(item)"
                    >
                      <div class="locate-head">
                        <span class="locate-label">{{ item.label }}</span>
                        <ElTag
                          size="small"
                          effect="plain"
                          :type="item.kind === 'evidence' ? 'warning' : 'info'"
                        >
                          {{ item.kind === 'evidence' ? '证据引用' : 'OCR' }}
                        </ElTag>
                      </div>
                      <div class="locate-value">{{ item.value || '（未识别到内容）' }}</div>
                      <div class="locate-meta">
                        <span v-if="item.pageNo">第 {{ item.pageNo }} 页</span>
                        <span v-if="item.confidence !== undefined">
                          置信度 {{ confidenceText(item.confidence) }}
                        </span>
                        <span v-if="item.status">{{ item.status }}</span>
                        <span v-if="item.bbox" class="locate-badge">可定位</span>
                      </div>
                    </button>
                  </li>
                </ul>
              </ElTabPane>

              <ElTabPane label="文件信息" name="meta">
                <ElDescriptions :column="1" border size="small">
                  <ElDescriptionsItem label="文件状态">
                    <ElTag
                      :type="getStatusTagType(document.fileStatus)"
                      size="small"
                      effect="plain"
                    >
                      {{ document.fileStatus }}
                    </ElTag>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="OCR 状态">
                    <ElTag
                      :type="ocrReadiness?.status === 'ready' ? 'success' : 'warning'"
                      size="small"
                    >
                      {{ ocrReadinessLabel }}
                    </ElTag>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="OCR 产物">
                    {{ ocrReadiness?.fieldCount || 0 }} 字段 ·
                    {{ ocrReadiness?.fragmentCount || 0 }} 片段 · bbox
                    {{ Math.round((ocrReadiness?.bboxCoverage || 0) * 100) }}%
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="当前版本">
                    {{ currentVersion?.versionNo || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="文件大小">{{ fileSizeText }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="绑定节点">{{ bindings.length }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="Parse Result">
                    {{ ocrReadiness?.parseResultId || '-' }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElTabPane>

              <ElTabPane :label="`历史版本 (${versions.length})`" name="versions">
                <ElTable :data="versions" border size="small" max-height="100%">
                  <ElTableColumn prop="versionNo" label="版本" width="80" />
                  <ElTableColumn
                    prop="uploaderName"
                    label="上传人"
                    width="90"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="uploadTime" label="上传时间" min-width="150" />
                  <ElTableColumn label="当前" width="70">
                    <template #default="{ row }">
                      <ElTag v-if="row.isCurrent" type="success" size="small" effect="plain">
                        当前
                      </ElTag>
                      <span v-else>-</span>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElTabPane>
            </ElTabs>
          </div>
        </div>
      </template>

      <ElEmpty v-else description="请选择文件" />
    </div>
  </ElDialog>
</template>

<style scoped>
.file-detail {
  min-height: 420px;
}

.file-header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}

.file-title {
  max-width: 620px;
  overflow-wrap: anywhere;
  font-size: 18px;
  font-weight: 600;
  line-height: 26px;
  color: #1f2937;
}

.file-meta {
  margin-top: 4px;
  font-size: 13px;
  line-height: 20px;
  color: #667085;
}

.file-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.file-layout {
  display: grid;
  /* 固定工作区高度：预览与字段各自滚动，避免整页上下滚动来回找 */
  height: min(64vh, 680px);
  grid-template-columns: minmax(0, 1fr) minmax(320px, 400px);
  gap: 14px;
  align-items: stretch;
}

.preview-shell {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.preview-toolbar {
  display: flex;
  height: 42px;
  padding: 0 12px;
  font-weight: 600;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.preview-body {
  display: flex;
  min-height: 0;
  flex: 1;
  overflow: auto;
  min-height: 168px;
  flex-direction: column;
  gap: 8px;
  justify-content: center;
  padding: 18px;
  color: #475467;
}

.preview-frame-host {
  display: flex;
  width: 100%;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: auto;
}

/* 图片高亮舞台：相对定位，供 bbox 覆盖层换算百分比 */
.preview-image-stage {
  position: relative;
  display: inline-block;
  max-width: 100%;
  margin: 0 auto;
}

.preview-highlight {
  position: absolute;
  border: 2px solid #f59e0b;
  border-radius: 2px;
  background: rgb(245 158 11 / 18%);
  box-shadow: 0 0 0 9999px rgb(15 23 42 / 12%);
  pointer-events: none;
  animation: locate-flash 1.2s ease-out;
}

@keyframes locate-flash {
  0%,
  55% {
    border-color: #f97316;
    background: rgb(249 115 22 / 34%);
  }

  100% {
    border-color: #f59e0b;
    background: rgb(245 158 11 / 18%);
  }
}

.preview-placeholder {
  display: flex;
  min-height: 360px;
  align-items: center;
  justify-content: center;
  color: #667085;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.preview-image {
  display: block;
  width: 100%;
  height: auto;
  object-fit: contain;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.preview-frame {
  width: 100%;
  min-height: 0;
  flex: 1;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.preview-body strong {
  overflow-wrap: anywhere;
  font-size: 16px;
  line-height: 24px;
  color: #1f2937;
}

.preview-body code {
  display: block;
  max-width: 100%;
  padding: 8px;
  color: #475467;
  background: #f3f4f6;
  border-radius: 6px;
  overflow-wrap: anywhere;
}

.preview-body--disabled {
  justify-content: flex-start;
}

.detail-side {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.side-alert {
  margin: 8px 8px 0;
  width: auto;
}

.side-tabs {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  padding: 0 8px 8px;
}

.side-tabs :deep(.el-tabs__content) {
  min-height: 0;
  flex: 1;
  overflow: auto;
}

.side-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.side-empty {
  display: flex;
  height: 100%;
  align-items: center;
  justify-content: center;
}

/* 字段列表：一行一个可点击条目，点击后在左侧原文定位 */
.locate-list {
  display: flex;
  margin: 0;
  padding: 0;
  flex-direction: column;
  gap: 6px;
  list-style: none;
}

.locate-button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  font: inherit;
  text-align: left;
  color: inherit;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.locate-button:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.locate-item.is-active .locate-button {
  background: #fff7ed;
  border-color: #f59e0b;
}

.locate-head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.locate-label {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.locate-value {
  margin-top: 4px;
  font-size: 13px;
  color: #334155;
  overflow-wrap: anywhere;
}

.locate-meta {
  display: flex;
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
  gap: 10px;
  flex-wrap: wrap;
}

.locate-badge {
  padding: 0 6px;
  color: #b45309;
  background: #fef3c7;
  border-radius: 4px;
}

/* 定位提示条：说清这次定位到了哪里、能不能画框 */
.locate-hint {
  padding: 6px 12px;
  font-size: 12px;
  color: #92400e;
  background: #fffbeb;
  border-bottom: 1px solid #fde68a;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

@media (width <= 768px) {
  .file-header,
  .file-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .file-layout {
    grid-template-columns: 1fr;
  }
}
</style>
