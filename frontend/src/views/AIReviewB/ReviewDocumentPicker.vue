<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, computed, ref, watch } from 'vue'
import ReviewDocumentVersions from './ReviewDocumentVersions.vue'
import { cloneDocumentSelectionVersions, validDocumentPageRange } from './documentPageSelection'
import type { DocumentVersion } from '@/types/aicheck'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElTag
} from 'element-plus'
import { bindInspectionDocumentsApi, getDocumentDetailApi } from '@/api/aicheck'
import {
  getReviewVersionOriginal,
  listReviewDocuments,
  type ReviewDocument,
  type ReviewDocumentSelection
} from '@/api/aicheck/reviewDocuments'

const PdfEvidencePage = defineAsyncComponent(
  () => import('@/views/AICheck/components/PdfEvidencePage.vue')
)
const props = defineProps<{
  projectId: string
  nodeId: number
  projectEtag?: string
  disabled?: boolean
  selection: ReviewDocumentSelection | null
}>()
const emit = defineEmits<{ change: [selection: ReviewDocumentSelection | null]; bound: [] }>()
const enabled = import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true'
const pageRangesEnabled = import.meta.env.VITE_AICHECK_REVIEW_PAGE_RANGES_ENABLED === 'true'
const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const persistBindings = ref(false)
const bindingAttempts = new Map<string, string>()
const error = ref('')
const keyword = ref('')
const page = ref(1)
const total = ref(0)
const documents = ref<ReviewDocument[]>([])
const chosen = ref<ReviewDocumentSelection['versions']>([])
const mode = ref<ReviewDocumentSelection['reviewMode']>('gap_precheck')
const preview = ref<{ url: string; title: string; type: string } | null>(null)
const versionDocument = ref<{ id: string; fileName: string } | null>(null)
const toggleVersion = (version: DocumentVersion, checked: boolean) => {
  if (!versionDocument.value || saving.value) return
  toggle(
    {
      id: version.documentId,
      currentVersionId: version.id,
      fileName: version.fileName || versionDocument.value.fileName,
      bodyUploaded: Boolean(version.hash)
    } as ReviewDocument,
    checked
  )
  const selected = chosen.value.find((row) => row.versionId === version.id)
  if (selected) selected.versionNo = version.versionNo || version.id
}
let generation = 0
let searchGeneration = 0
let previewGeneration = 0
const chosenIds = computed(() => new Set(chosen.value.map((item) => item.versionId)))
const selectable = (item: ReviewDocument) =>
  Boolean(item.currentVersionId) && item.bodyUploaded !== false
const load = async () => {
  const context = generation
  const search = ++searchGeneration
  loading.value = true
  error.value = ''
  try {
    const response = await listReviewDocuments(props.projectId, {
      keyword: keyword.value.trim(),
      page: page.value,
      pageSize: 20
    })
    if (context !== generation || search !== searchGeneration) return
    documents.value = response.data.items
    total.value = response.data.total
  } catch {
    if (context === generation && search === searchGeneration)
      error.value = '文件列表加载失败，请重试。已选文件仍保留。'
  } finally {
    if (context === generation && search === searchGeneration) loading.value = false
  }
}
const open = () => {
  if (saving.value) return
  persistBindings.value = false
  chosen.value = cloneDocumentSelectionVersions(props.selection?.versions || [])
  mode.value = props.selection?.reviewMode || 'gap_precheck'
  keyword.value = ''
  page.value = 1
  visible.value = true
  void load()
}
const toggle = (item: ReviewDocument, checked: boolean) => {
  if (saving.value) return
  if (checked && selectable(item) && !chosenIds.value.has(item.currentVersionId)) {
    if (chosen.value.length >= 500) {
      error.value = '本次最多选择 500 份文件。'
      return
    }
    chosen.value.push({
      documentId: item.id,
      versionId: item.currentVersionId,
      fileName: item.fileName
    })
  } else if (!checked)
    chosen.value = chosen.value.filter((row) => row.versionId !== item.currentVersionId)
}
const search = () => {
  page.value = 1
  void load()
}
const save = async () => {
  if (!chosen.value.length || props.disabled || saving.value) return
  if (chosen.value.some((item) => !validDocumentPageRange(item.pageRange))) {
    error.value = '页码范围无效，请填写从1开始、结束页不小于起始页的整数页码。'
    return
  }
  const context = generation
  const projectId = props.projectId
  const nodeId = props.nodeId
  const selection = {
    versions: cloneDocumentSelectionVersions(chosen.value),
    reviewMode: mode.value
  }
  if (persistBindings.value) {
    const bindings = selection.versions
      .map((item) => ({
        documentId: item.documentId,
        documentVersionId: item.versionId,
        usage: '监检资料' as const
      }))
      .sort((a, b) => a.documentVersionId.localeCompare(b.documentVersionId))
    const fingerprint = JSON.stringify({ projectId, nodeId, bindings })
    const idempotencyKey = bindingAttempts.get(fingerprint) || `review-files-${crypto.randomUUID()}`
    bindingAttempts.set(fingerprint, idempotencyKey)
    saving.value = true
    error.value = ''
    try {
      await bindInspectionDocumentsApi(projectId, nodeId, bindings, {
        etag: props.projectEtag,
        idempotencyKey
      })
      if (context !== generation) return
      emit('bound')
    } catch {
      if (context === generation)
        error.value =
          '节点挂载未确认成功，已选文件仍保留。可重试；若工程已更新，请刷新工作台后再保存。'
      return
    } finally {
      saving.value = false
    }
  }
  if (context !== generation) return
  emit('change', selection)
  visible.value = false
}
const useNodeDocuments = () => {
  if (saving.value || props.disabled) return
  emit('change', null)
  visible.value = false
}
const clearPreview = () => {
  previewGeneration++
  if (preview.value) URL.revokeObjectURL(preview.value.url)
  preview.value = null
}
onBeforeUnmount(clearPreview)
const showPreview = async (item: ReviewDocument) => {
  clearPreview()
  const context = generation
  const attempt = previewGeneration
  error.value = ''
  try {
    const response = await getDocumentDetailApi(props.projectId, item.id)
    if (context !== generation || attempt !== previewGeneration) return
    if (response.data.document.currentVersionId !== item.currentVersionId) {
      error.value = '该文件已有新版本，请刷新列表后重新选择。'
      return
    }
    const blob = await getReviewVersionOriginal(props.projectId, item.id, item.currentVersionId)
    if (context !== generation || attempt !== previewGeneration) return
    preview.value = {
      url: URL.createObjectURL(blob),
      type:
        blob.type === 'application/pdf'
          ? 'pdf'
          : blob.type.startsWith('image/')
            ? 'image'
            : 'unsupported',
      title: item.fileName
    }
  } catch {
    if (context === generation && attempt === previewGeneration)
      error.value = '无法预览此文件，请稍后重试。'
  }
}
watch(
  () => [props.projectId, props.nodeId],
  () => {
    generation++
    searchGeneration++
    previewGeneration++
    visible.value = false
    versionDocument.value = null
    clearPreview()
    documents.value = []
    chosen.value = []
    loading.value = false
  }
)
watch(visible, (value) => {
  if (!value) {
    clearPreview()
    versionDocument.value = null
    searchGeneration++
    previewGeneration++
    loading.value = false
  }
})
</script>

<template>
  <ElButton v-if="enabled" :disabled="saving || disabled || !projectId || !nodeId" @click="open">
    {{ selection ? `本次文件 ${selection.versions.length} 份` : '选择本次文件' }}
  </ElButton>
  <ElDialog
    v-model="visible"
    title="选择本次审查文件"
    width="min(900px, 94vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <ElAlert
      type="info"
      :closable="false"
      title="本次审查仅使用所选文件版本。默认仅本次使用；勾选下方选项可同时保存为节点补充资料。"
    />
    <ElAlert v-if="error" type="error" :closable="false" :title="error" />
    <ElForm label-position="top" class="document-picker-search" @submit.prevent="search">
      <ElFormItem label="搜索文件名称、来源单位或类别">
        <ElInput v-model="keyword" clearable @keyup.enter="search" />
      </ElFormItem>
      <ElButton :loading="loading" @click="search">搜索 / 刷新</ElButton>
      <ElButton :disabled="loading" @click="documents.forEach((item) => toggle(item, true))"
        >选择本页</ElButton
      >
    </ElForm>
    <div v-loading="loading" class="document-picker-list">
      <ElEmpty v-if="!loading && !documents.length" description="没有找到可访问的文件" />
      <div
        v-for="item in documents"
        :key="item.currentVersionId || item.id"
        class="document-picker-row"
      >
        <ElCheckbox
          :model-value="chosenIds.has(item.currentVersionId)"
          :disabled="saving || !selectable(item)"
          @change="(value) => toggle(item, Boolean(value))"
        >
          {{ item.fileName }}
        </ElCheckbox>
        <span
          >{{ item.currentOcrStatus || '待识别'
          }}{{ item.bodyUploaded === false ? ' · 文件未上传完整' : '' }}</span
        >
        <ElButton
          link
          :disabled="saving"
          @click="versionDocument = { id: item.id, fileName: item.fileName }"
          >版本</ElButton
        >
        <ElButton link :disabled="saving || !selectable(item)" @click="showPreview(item)"
          >预览</ElButton
        >
      </div>
    </div>
    <ElPagination
      v-model:current-page="page"
      :page-size="20"
      :total="total"
      layout="prev, pager, next"
      @current-change="load"
    />
    <p>已选 {{ chosen.length }} 份（跨页保留；待识别文件不会被视为已有 OCR 证据）</p>
    <div class="document-picker-chosen">
      <ElTag
        v-for="item in chosen"
        :key="item.versionId"
        :closable="!saving"
        @close="chosen = chosen.filter((row) => row.versionId !== item.versionId)"
        >{{ item.fileName }} · {{ item.versionNo || item.versionId }}</ElTag
      >
    </div>
    <section v-if="pageRangesEnabled && chosen.length" aria-label="本次文件页码范围">
      <p>默认使用整份选定版本。指定页码仅适用于本次审查的PDF，发起时会核对实际页数。</p>
      <div v-for="item in chosen" :key="item.versionId" class="document-page-range">
        <strong>{{ item.fileName }}</strong>
        <ElCheckbox
          :model-value="Boolean(item.pageRange)"
          :disabled="saving"
          @change="
            (value) => {
              if (value) item.pageRange = { start: 1, end: 1 }
              else delete item.pageRange
            }
          "
          >指定页码</ElCheckbox
        >
        <template v-if="item.pageRange">
          <label :for="`page-start-${item.versionId}`">起始页</label>
          <ElInputNumber
            :id="`page-start-${item.versionId}`"
            v-model="item.pageRange.start"
            :min="1"
            :step="1"
            :disabled="saving"
          />
          <label :for="`page-end-${item.versionId}`">结束页</label>
          <ElInputNumber
            :id="`page-end-${item.versionId}`"
            v-model="item.pageRange.end"
            :min="1"
            :step="1"
            :disabled="saving"
          />
        </template>
      </div>
    </section>
    <ElForm label-position="top">
      <ElFormItem label="本次审查方式">
        <ElRadioGroup v-model="mode" :disabled="saving">
          <ElRadioButton value="gap_precheck">缺项预审</ElRadioButton>
          <ElRadioButton value="formal">正式复核</ElRadioButton>
        </ElRadioGroup>
      </ElFormItem>
    </ElForm>
    <ElCheckbox v-model="persistBindings" :disabled="saving"> 同时保存为本节点补充资料 </ElCheckbox>
    <p v-if="persistBindings"
      >按所选版本新增挂载，不替换原挂载或自动匹配必传要求；未提交的版本仍需提交。旧版本不会自动成为正式审查证据。</p
    >
    <p v-if="persistBindings && chosen.some((item) => item.pageRange)"
      >补充资料挂载保存整份版本；页码范围仅保留在本次选择和新审查任务中。</p
    >
    <p>正式复核会重新检查所选文件是否满足要求；仅选择文件不会自动确认其证据。</p>
    <template #footer>
      <ElButton :disabled="disabled || saving" @click="useNodeDocuments">恢复使用节点资料</ElButton>
      <ElButton :disabled="saving" @click="visible = false">取消</ElButton>
      <ElButton
        type="primary"
        :loading="saving"
        :disabled="!chosen.length || disabled || saving"
        @click="save"
        >{{ persistBindings ? '保存选择并挂载' : '保存本次选择' }}</ElButton
      >
    </template>
  </ElDialog>
  <ReviewDocumentVersions
    v-if="versionDocument"
    :project-id="projectId"
    :document-id="versionDocument.id"
    :file-name="versionDocument.fileName"
    :selected-ids="[...chosenIds]"
    @toggle="toggleVersion"
    @close="versionDocument = null"
  />
  <ElDialog
    :model-value="Boolean(preview)"
    append-to-body
    :title="preview?.title"
    width="min(1000px, 96vw)"
    @close="clearPreview"
  >
    <PdfEvidencePage v-if="preview?.type === 'pdf'" :src="preview.url" :file-name="preview.title" />
    <img
      v-else-if="preview?.type === 'image'"
      :src="preview.url"
      :alt="preview.title"
      class="document-picker-image"
    />
    <ElEmpty v-else description="此格式暂不支持内嵌预览，请在文件资料库查看。" />
  </ElDialog>
</template>

<style scoped>
.document-picker-search {
  margin-top: 16px;
}

.document-page-range {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.document-page-range strong {
  flex-basis: 100%;
  overflow-wrap: anywhere;
}

.document-page-range :deep(.el-input-number) {
  min-height: 44px;
}

.document-picker-list {
  max-height: 320px;
  min-height: 120px;
  overflow: auto;
}

.document-picker-row {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.document-picker-row .el-checkbox {
  height: auto;
  min-width: 0;
  white-space: normal;
  flex: 1;
}

.document-picker-row :deep(.el-checkbox__label) {
  white-space: normal;
  overflow-wrap: anywhere;
}

.document-picker-row span {
  color: var(--el-text-color-secondary);
}

.document-picker-chosen {
  display: flex;
  max-height: 140px;
  margin-bottom: 16px;
  overflow: auto;
  flex-wrap: wrap;
  gap: 8px;
}

.document-picker-preview {
  width: 100%;
  height: 65vh;
  border: 0;
}

.document-picker-image {
  max-width: 100%;
  max-height: 65vh;
  object-fit: contain;
}
</style>
