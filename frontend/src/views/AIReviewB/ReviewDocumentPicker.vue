<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElTag
} from 'element-plus'
import { getDocumentDetailApi } from '@/api/aicheck'
import {
  listReviewDocuments,
  type ReviewDocument,
  type ReviewDocumentSelection
} from '@/api/aicheck/reviewDocuments'

const props = defineProps<{
  projectId: string
  nodeId: number
  disabled?: boolean
  selection: ReviewDocumentSelection | null
}>()
const emit = defineEmits<{ change: [selection: ReviewDocumentSelection | null] }>()
const enabled = import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true'
const visible = ref(false)
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const page = ref(1)
const total = ref(0)
const documents = ref<ReviewDocument[]>([])
const chosen = ref<ReviewDocumentSelection['versions']>([])
const mode = ref<ReviewDocumentSelection['reviewMode']>('gap_precheck')
const preview = ref<{ url: string; title: string; type: string } | null>(null)
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
  chosen.value = props.selection?.versions.map((item) => ({ ...item })) || []
  mode.value = props.selection?.reviewMode || 'gap_precheck'
  keyword.value = ''
  page.value = 1
  visible.value = true
  void load()
}
const toggle = (item: ReviewDocument, checked: boolean) => {
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
const save = () => {
  if (!chosen.value.length || props.disabled) return
  emit('change', { versions: chosen.value.map((item) => ({ ...item })), reviewMode: mode.value })
  visible.value = false
}
const useNodeDocuments = () => {
  emit('change', null)
  visible.value = false
}
const showPreview = async (item: ReviewDocument) => {
  const context = generation
  const attempt = ++previewGeneration
  error.value = ''
  try {
    const response = await getDocumentDetailApi(props.projectId, item.id)
    if (context !== generation || attempt !== previewGeneration) return
    if (response.data.document.currentVersionId !== item.currentVersionId) {
      error.value = '该文件已有新版本，请刷新列表后重新选择。'
      return
    }
    preview.value = {
      url: response.data.preview.url,
      type: response.data.preview.previewType,
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
    preview.value = null
    documents.value = []
    chosen.value = []
    loading.value = false
  }
)
watch(visible, (value) => {
  if (!value) {
    searchGeneration++
    previewGeneration++
    loading.value = false
  }
})
</script>

<template>
  <ElButton v-if="enabled" :disabled="disabled || !projectId || !nodeId" @click="open">
    {{ selection ? `本次文件 ${selection.versions.length} 份` : '选择本次文件' }}
  </ElButton>
  <ElDialog
    v-model="visible"
    title="选择本次审查文件"
    width="min(900px, 94vw)"
    :close-on-click-modal="false"
  >
    <ElAlert
      type="info"
      :closable="false"
      title="保存后，本次审查仅使用所选文件版本；不会修改节点挂载。取消则保留原选择。"
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
          :disabled="!selectable(item)"
          @change="(value) => toggle(item, Boolean(value))"
        >
          {{ item.fileName }}
        </ElCheckbox>
        <span
          >{{ item.currentOcrStatus || '待识别'
          }}{{ item.bodyUploaded === false ? ' · 文件未上传完整' : '' }}</span
        >
        <ElButton link :disabled="!selectable(item)" @click="showPreview(item)">预览</ElButton>
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
        closable
        @close="chosen = chosen.filter((row) => row.versionId !== item.versionId)"
        >{{ item.fileName }}</ElTag
      >
    </div>
    <ElForm label-position="top">
      <ElFormItem label="本次审查方式">
        <ElRadioGroup v-model="mode">
          <ElRadioButton value="gap_precheck">缺项预审</ElRadioButton>
          <ElRadioButton value="formal">正式复核</ElRadioButton>
        </ElRadioGroup>
      </ElFormItem>
    </ElForm>
    <p>正式复核会重新检查所选文件是否满足要求；仅选择文件不会自动确认其证据。</p>
    <template #footer>
      <ElButton :disabled="disabled" @click="useNodeDocuments">恢复使用节点资料</ElButton>
      <ElButton @click="visible = false">取消</ElButton>
      <ElButton type="primary" :disabled="!chosen.length || disabled" @click="save"
        >保存本次选择</ElButton
      >
    </template>
  </ElDialog>
  <ElDialog
    :model-value="Boolean(preview)"
    :title="preview?.title"
    width="min(1000px, 96vw)"
    @close="preview = null"
  >
    <iframe
      v-if="preview?.type === 'pdf'"
      :src="preview.url"
      :title="preview.title"
      class="document-picker-preview"
    ></iframe>
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
