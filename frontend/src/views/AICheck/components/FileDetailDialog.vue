<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import {
  ElAlert,
  ElButton,
  ElIcon,
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
import { getDocumentOfficePreviewApi, getDocumentOriginalBlobApi } from '@/api/aicheck'
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
/* ---------------- Office 在线预览（L-4） ----------------
 * 这个项目的资料全是 .docx，此前在系统里完全无法查看，界面只提示「请下载后用
 * Word 打开」——监检得离开系统、在本地比对，再回来填结论。
 *
 * 接 ONLYOFFICE Document Server，只读挂载。不做在线编辑：审查场景里原始资料
 * 一旦可改，证据链就断了（后端已把 permissions 全部关闭）。
 */
const officePreviewLoading = ref(false)
const officePreviewError = ref('')
const officeContainerId = `office-preview-${Math.random().toString(36).slice(2, 10)}`
let officeEditor: { destroyEditor?: () => void } | null = null

const previewIsOffice = computed(() => preview.value?.previewType === 'office')

const loadDocumentServerScript = (src: string) =>
  new Promise<void>((resolve, reject) => {
    // 本组件有个名为 document 的计算属性（当前文档记录），会遮蔽全局 document，
    // 所以操作 DOM 必须显式走 globalThis
    const dom = globalThis.document
    const existing = dom.querySelector<HTMLScriptElement>(`script[data-aicheck-ds="${src}"]`)
    if (existing) {
      if (existing.dataset.loaded === 'true') resolve()
      else {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error('加载失败')), { once: true })
      }
      return
    }
    const script = dom.createElement('script')
    script.src = src
    script.async = true
    script.dataset.aicheckDs = src
    script.addEventListener('load', () => {
      script.dataset.loaded = 'true'
      resolve()
    })
    script.addEventListener('error', () => reject(new Error('加载失败')))
    dom.head.appendChild(script)
  })

const destroyOfficeEditor = () => {
  try {
    officeEditor?.destroyEditor?.()
  } catch {
    // 弹窗关闭时 DS 可能已自行清理，销毁失败不影响业务
  }
  officeEditor = null
}

const mountOfficePreview = async () => {
  const projectId = props.detail?.document?.projectId
  const documentId = props.detail?.document?.id
  if (!projectId || !documentId) return
  officePreviewLoading.value = true
  officePreviewError.value = ''
  destroyOfficeEditor()
  try {
    const res = await getDocumentOfficePreviewApi(String(projectId), String(documentId))
    const payload = res?.data
    if (!payload?.apiScriptUrl) {
      officePreviewError.value = getAicheckErrorMessage(res, 'Office 预览服务暂不可用。')
      return
    }
    await loadDocumentServerScript(payload.apiScriptUrl)
    await nextTick()
    const DocsAPI = (
      window as unknown as { DocsAPI?: { DocEditor: new (...args: never[]) => never } }
    ).DocsAPI
    if (!DocsAPI) {
      officePreviewError.value = 'Office 预览组件未能加载。'
      return
    }
    officeEditor = new (DocsAPI.DocEditor as unknown as new (
      id: string,
      config: Record<string, unknown>
    ) => { destroyEditor?: () => void })(officeContainerId, payload.config)
  } catch (error) {
    officePreviewError.value = getAicheckErrorMessage(error, 'Office 预览加载失败，请下载后查看。')
  } finally {
    officePreviewLoading.value = false
  }
}

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
      if (previewIsOffice.value) void mountOfficePreview()
    } else {
      revokePreviewObjectUrl()
      previewOriginalError.value = ''
      officePreviewError.value = ''
      destroyOfficeEditor()
    }
  }
)

onBeforeUnmount(() => {
  revokePreviewObjectUrl()
  destroyOfficeEditor()
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

/* ---------------- 业务字段 vs 原文片段（L-3c） ----------------
 * 抽取管线没做字段识别时，会把正文切片按 OCR文本 / OCR文本2 … 顺序编号塞进
 * fields（后端 fields_from_fragments 兜底）。这些不是业务字段——监检要的是
 * 「证书编号」「设计压力」这类。
 *
 * 线上一份资料 10 个条目全是这种编号片段、置信度全 0，平铺在右侧，看不出
 * 哪条该核对。所以按语义分两组：真字段置顶，片段折叠收起。
 *
 * 判据与后端 libs/ocr_readiness.py 的 is_placeholder_field_name 保持一致。
 */
const PLACEHOLDER_FIELD_PATTERN = /^(?:OCR)?(?:文本|片段|text|fragment|field)\s*_?\d*$/i

const isPlaceholderField = (label: string) =>
  PLACEHOLDER_FIELD_PATTERN.test(String(label || '').trim())

/* ---------------- OCR 结构化内容分区 ----------------
 * 后端早就抽出了表格、印章、版面结构（线上一份资料 261 个正文块、1 张带
 * normalizedRows 的表格、2 枚印章），右侧却只显示了几个字段。
 *
 * 监检核对「焊丝牌号与母材是否匹配」靠的就是表格，确认「有没有盖章」靠的就是
 * 印章——这些不展示，等于让人对着一份读不懂的资料下结论。
 */
const ocrStructured = computed(() => props.detail?.ocrStructured)
const ocrTables = computed(() => ocrStructured.value?.tables || [])
const ocrSeals = computed(() => ocrStructured.value?.seals || [])
const ocrBlocks = computed(() => ocrStructured.value?.layoutBlocks || [])

/* 标注块类型，而不是伪造标题层级。
 *
 * 起初我把 header 当标题加粗——错了。OCR 语境里 header 是**页眉**，线上实际
 * 内容是「工程项目 | S05-DESIGN-001」「副本」，footer 是「国家市场监督管理
 * 总局制」这类页脚。全库统计（text 606 / table 113 / page_number 67 /
 * header 62 / footer 31 / seal 18 / image 11 / aside_text 5）里根本没有标题
 * 类型，加粗页眉只会把页面家具误导成章节标题。
 *
 * 页眉页脚也不直接扔：页眉带工程编号，页脚的「国家市场监督管理总局制」能
 * 佐证这是制式表格，都是证据。标出来让人自己判断，比替人删掉稳妥。 */
const BLOCK_TYPE_LABELS: Record<string, string> = {
  header: '页眉',
  footer: '页脚',
  table: '表格',
  image: '图片',
  seal: '印章',
  aside_text: '旁注'
}
const blockTypeLabel = (blockType: string) =>
  BLOCK_TYPE_LABELS[String(blockType || '').toLowerCase()] || ''

const sealKindLabel = (kind: string) => (kind === 'signature' ? '签名' : '印章')

/** sealName 里有时塞的是整段上下文，列表里要截断。 */
const sealDisplayName = (name: string) => {
  const text = String(name || '').trim()
  if (!text) return '（未命名）'
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

const structuredTabLabel = computed(() => {
  const counts: string[] = []
  if (businessFieldItems.value.length) counts.push(`字段 ${businessFieldItems.value.length}`)
  if (ocrTables.value.length) counts.push(`表格 ${ocrTables.value.length}`)
  if (ocrSeals.value.length) counts.push(`印章 ${ocrSeals.value.length}`)
  return counts.length ? `OCR 结构化内容（${counts.join(' · ')}）` : 'OCR 结构化内容'
})

const structuredIsEmpty = computed(
  () =>
    !businessFieldItems.value.length &&
    !ocrTables.value.length &&
    !ocrSeals.value.length &&
    !ocrBlocks.value.length &&
    !fragmentItems.value.length
)

const blocksExpanded = ref(false)

const businessFieldItems = computed(() =>
  locatableItems.value.filter((item) => !isPlaceholderField(item.label))
)
const fragmentItems = computed(() =>
  locatableItems.value.filter((item) => isPlaceholderField(item.label))
)
const fragmentsExpanded = ref(false)

/** 置信度 0 与「没给置信度」含义完全不同：前者是「判定为不可信」，
 *  后者是「管线没产出这个指标」。显示成 0% 会让监检误以为是前者。 */
const confidenceDisplay = (confidence?: number) =>
  typeof confidence === 'number' && confidence > 0 ? confidenceText(confidence) : '未提供置信度'

/** 表格/印章/正文块同样带页码与 bbox，纳入定位池后点一下就能跳到原文那页。 */
const structuredLocatables = computed<LocatableItem[]>(() => [
  ...ocrTables.value.map((table) => ({
    key: `table:${table.tableId}`,
    label: '表格',
    value: table.columnNames.join(' / '),
    pageNo: table.pageNo,
    bbox: table.bbox || undefined,
    confidence: table.confidence,
    kind: 'field' as const
  })),
  ...ocrSeals.value.map((seal) => ({
    key: `seal:${seal.id}`,
    label: sealKindLabel(seal.kind),
    value: seal.name,
    pageNo: seal.pageNo,
    bbox: seal.bbox || undefined,
    confidence: seal.confidence,
    kind: 'evidence' as const
  })),
  ...ocrBlocks.value.map((block) => ({
    key: `block:${block.blockId}`,
    label: block.blockType,
    value: block.text,
    pageNo: block.pageNo,
    bbox: block.bbox || undefined,
    kind: 'field' as const
  }))
])

const activeLocatable = computed(() =>
  [...locatableItems.value, ...structuredLocatables.value].find(
    (item) => item.key === activeLocateKey.value
  )
)

/** 结构化条目按 key 定位，不必构造完整 LocatableItem。 */
const toggleLocateKey = (key: string) => {
  activeLocateKey.value = activeLocateKey.value === key ? '' : key
}

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
            <div
              class="preview-body"
              :class="{ 'preview-body--disabled': !previewEmbeddable && !previewIsOffice }"
            >
              <!-- Office：交给 ONLYOFFICE 只读渲染 -->
              <template v-if="previewIsOffice">
                <div class="preview-frame-host" v-loading="officePreviewLoading">
                  <ElAlert
                    v-if="officePreviewError"
                    title="Office 在线预览不可用"
                    :description="`${officePreviewError} 可使用右上角「下载」查看原文。`"
                    type="warning"
                    :closable="false"
                    show-icon
                  />
                  <div v-else :id="officeContainerId" class="office-stage"></div>
                </div>
              </template>
              <template v-else-if="previewEmbeddable">
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
                title="当前格式暂不支持在线预览"
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
              <ElTabPane :label="structuredTabLabel" name="fields">
                <div v-if="structuredIsEmpty" class="side-empty">
                  <ElEmpty :image-size="60" description="暂无 OCR 结构化内容" />
                </div>
                <template v-else>
                  <ElAlert
                    v-if="!businessFieldItems.length"
                    type="warning"
                    :closable="false"
                    show-icon
                    title="未识别出业务字段"
                    description="只切出了原文片段，没有识别出证书编号、设计压力这类可核对的字段。核对前需人工补录或重跑抽取。"
                    class="side-alert"
                  />
                  <ul v-if="businessFieldItems.length" class="locate-list">
                    <li
                      v-for="item in businessFieldItems"
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
                            {{ confidenceDisplay(item.confidence) }}
                          </span>
                          <span v-if="item.status">{{ item.status }}</span>
                          <span v-if="item.bbox" class="locate-badge">可定位</span>
                        </div>
                      </button>
                    </li>
                  </ul>

                  <!-- 表格：监检核对参数表（焊丝牌号与母材是否匹配等）靠这个 -->
                  <div v-if="ocrTables.length" class="ocr-section">
                    <div class="ocr-section-head">
                      <span class="ocr-section-title">表格 {{ ocrTables.length }} 张</span>
                    </div>
                    <div v-for="table in ocrTables" :key="table.tableId" class="ocr-table-card">
                      <button
                        type="button"
                        :class="[
                          'ocr-table-meta',
                          'ocr-locate',
                          { 'is-active': activeLocateKey === `table:${table.tableId}` }
                        ]"
                        :aria-pressed="activeLocateKey === `table:${table.tableId}`"
                        @click="toggleLocateKey(`table:${table.tableId}`)"
                      >
                        <span v-if="table.pageNo">第 {{ table.pageNo }} 页</span>
                        <span v-if="table.rows && table.columns">
                          {{ table.rows }} 行 × {{ table.columns }} 列
                        </span>
                        <ElTag
                          v-if="table.matchedRequired"
                          size="small"
                          type="success"
                          effect="plain"
                        >
                          可作必备表格
                        </ElTag>
                        <ElTag
                          v-else-if="table.candidateOnly"
                          size="small"
                          type="info"
                          effect="plain"
                        >
                          候选
                        </ElTag>
                      </button>
                      <!-- 用 normalizedRows 自己画表，不渲染引擎产出的 html（XSS 面） -->
                      <div v-if="table.normalizedRows.length" class="ocr-table-scroll">
                        <table class="ocr-table">
                          <thead>
                            <tr>
                              <th v-for="col in table.columnNames" :key="col">{{ col }}</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="(row, index) in table.normalizedRows" :key="index">
                              <td v-for="col in table.columnNames" :key="col">{{
                                row[col] || ''
                              }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div v-else-if="table.cells.length" class="ocr-table-cells">
                        {{ table.cells.join(' | ') }}
                      </div>
                    </div>
                  </div>

                  <!-- 印章与签名：确认「盖没盖章」的直接依据 -->
                  <div v-if="ocrSeals.length" class="ocr-section">
                    <div class="ocr-section-head">
                      <span class="ocr-section-title">印章 / 签名 {{ ocrSeals.length }} 处</span>
                    </div>
                    <ul class="ocr-seal-list">
                      <li v-for="seal in ocrSeals" :key="seal.id">
                        <button
                          type="button"
                          :class="[
                            'ocr-seal-item',
                            'ocr-locate',
                            { 'is-active': activeLocateKey === `seal:${seal.id}` }
                          ]"
                          :aria-pressed="activeLocateKey === `seal:${seal.id}`"
                          @click="toggleLocateKey(`seal:${seal.id}`)"
                        >
                          <div class="ocr-seal-head">
                            <ElTag
                              size="small"
                              :type="seal.canSatisfyRequired ? 'success' : 'info'"
                              effect="plain"
                            >
                              {{ sealKindLabel(seal.kind) }}
                            </ElTag>
                            <span class="ocr-seal-name">{{ sealDisplayName(seal.name) }}</span>
                          </div>
                          <div class="ocr-seal-meta">
                            <span v-if="seal.pageNo">第 {{ seal.pageNo }} 页</span>
                            <span v-if="seal.sealType">{{ seal.sealType }}</span>
                            <span v-if="seal.confidence">{{
                              confidenceDisplay(seal.confidence)
                            }}</span>
                            <span v-if="seal.canSatisfyRequired" class="ocr-seal-ok"
                              >可满足必盖章要求</span
                            >
                          </div>
                        </button>
                      </li>
                    </ul>
                  </div>

                  <!-- 正文结构：按阅读顺序，保留标题层级 -->
                  <div v-if="ocrBlocks.length" class="ocr-section">
                    <button
                      type="button"
                      class="fragment-toggle"
                      :aria-expanded="blocksExpanded"
                      @click="blocksExpanded = !blocksExpanded"
                    >
                      <span>正文结构 {{ ocrBlocks.length }} 段</span>
                      <span class="fragment-hint">
                        {{
                          ocrStructured?.truncated
                            ? `共 ${ocrStructured.totalBlockCount} 段，仅显示前 ${ocrBlocks.length} 段`
                            : '按阅读顺序，含页眉页脚'
                        }}
                      </span>
                      <ElIcon :class="['fragment-chevron', { 'is-open': blocksExpanded }]">
                        <ArrowDown />
                      </ElIcon>
                    </button>
                    <div v-show="blocksExpanded" class="ocr-block-list">
                      <button
                        v-for="block in ocrBlocks"
                        :key="block.blockId"
                        type="button"
                        :class="[
                          'ocr-block',
                          'ocr-locate',
                          { 'is-active': activeLocateKey === `block:${block.blockId}` }
                        ]"
                        :aria-pressed="activeLocateKey === `block:${block.blockId}`"
                        @click="toggleLocateKey(`block:${block.blockId}`)"
                      >
                        <span v-if="blockTypeLabel(block.blockType)" class="ocr-block-kind">
                          {{ blockTypeLabel(block.blockType) }}
                        </span>
                        {{ block.text }}
                        <span v-if="block.pageNo" class="ocr-block-page">P{{ block.pageNo }}</span>
                      </button>
                    </div>
                  </div>

                  <div v-if="fragmentItems.length && !ocrBlocks.length" class="fragment-block">
                    <button
                      type="button"
                      class="fragment-toggle"
                      :aria-expanded="fragmentsExpanded"
                      @click="fragmentsExpanded = !fragmentsExpanded"
                    >
                      <span>原文片段 {{ fragmentItems.length }} 条</span>
                      <span class="fragment-hint">未命名的正文切片，非业务字段</span>
                      <ElIcon :class="['fragment-chevron', { 'is-open': fragmentsExpanded }]">
                        <ArrowDown />
                      </ElIcon>
                    </button>
                    <ul v-show="fragmentsExpanded" class="locate-list">
                      <li
                        v-for="item in fragmentItems"
                        :key="item.key"
                        :class="['locate-item', { 'is-active': item.key === activeLocateKey }]"
                      >
                        <button
                          type="button"
                          class="locate-button"
                          :aria-pressed="item.key === activeLocateKey"
                          @click="handleLocate(item)"
                        >
                          <div class="locate-value">{{ item.value || '（未识别到内容）' }}</div>
                          <div class="locate-meta">
                            <span v-if="item.pageNo">第 {{ item.pageNo }} 页</span>
                            <span v-if="item.bbox" class="locate-badge">可定位</span>
                          </div>
                        </button>
                      </li>
                    </ul>
                  </div>
                </template>
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

.office-stage {
  width: 100%;
  height: 100%;
  min-height: 420px;
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

/* OCR 结构化分区：表格 / 印章 / 正文结构 */
.ocr-section {
  padding-top: 10px;
  margin-top: 12px;
  border-top: 1px solid #eef1f5;
}

.ocr-section-head {
  display: flex;
  margin-bottom: 8px;
  gap: 8px;
  align-items: center;
}

.ocr-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.ocr-table-card {
  padding: 8px;
  margin-bottom: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ocr-table-meta {
  display: flex;
  margin-bottom: 6px;
  font-size: 12px;
  color: #64748b;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

/* 参数表列多，窄侧栏放不下——横向滚动，不压字 */
.ocr-table-scroll {
  overflow-x: auto;
}

.ocr-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}

.ocr-table th,
.ocr-table td {
  padding: 4px 6px;
  text-align: left;
  white-space: nowrap;
  border: 1px solid #e2e8f0;
}

.ocr-table th {
  font-weight: 600;
  color: #475569;
  background: #f1f5f9;
}

.ocr-table-cells {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
  word-break: break-all;
}

/* 可点定位的条目：按钮外观归零，选中时用左侧色条标出 */
.ocr-locate {
  display: block;
  width: 100%;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: none;
}

.ocr-locate.is-active {
  padding-left: 7px;
  background: #ecf5ff;
  border-left: 3px solid #409eff;
}

.ocr-table-meta.ocr-locate:hover,
.ocr-block.ocr-locate:hover {
  background: #f1f5f9;
}

.ocr-seal-list {
  display: flex;
  padding: 0;
  margin: 0;
  flex-direction: column;
  gap: 6px;
  list-style: none;
}

.ocr-seal-item {
  width: 100%;
  padding: 8px 10px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ocr-seal-head {
  display: flex;
  gap: 6px;
  align-items: center;
}

.ocr-seal-name {
  font-size: 13px;
  color: #1f2937;
  word-break: break-all;
}

.ocr-seal-meta {
  display: flex;
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
  gap: 8px;
  flex-wrap: wrap;
}

.ocr-seal-ok {
  color: #16a34a;
}

.ocr-block-list {
  max-height: 320px;
  margin-top: 8px;
  overflow-y: auto;
}

.ocr-block {
  margin: 0 0 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
  word-break: break-word;
}

/* 块类型角标：页眉/页脚等页面家具要能一眼认出，不能混进正文当内容读 */
.ocr-block-kind {
  padding: 0 4px;
  margin-right: 4px;
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 3px;
}

.ocr-block-page {
  margin-left: 6px;
  font-size: 11px;
  color: #cbd5e1;
}

/* 字段列表：一行一个可点击条目，点击后在左侧原文定位 */
.fragment-block {
  margin-top: 10px;
  border-top: 1px solid #eef1f5;
  padding-top: 10px;
}

.fragment-toggle {
  display: flex;
  width: 100%;
  padding: 8px 10px;
  font: inherit;
  color: inherit;
  text-align: left;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  gap: 8px;
  align-items: center;
  cursor: pointer;
}

.fragment-toggle:hover {
  background: #f1f5f9;
}

.fragment-hint {
  flex: 1;
  font-size: 12px;
  color: #94a3b8;
}

.fragment-chevron {
  font-size: 15px;
  color: #94a3b8;
  transition: transform 0.2s;
}

.fragment-chevron.is-open {
  transform: rotate(180deg);
}

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
