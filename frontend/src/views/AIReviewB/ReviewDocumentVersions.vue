<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCheckbox, ElDialog, ElEmpty } from 'element-plus'
import { getDocumentDetailApi } from '@/api/aicheck'
import { getReviewVersionOriginal } from '@/api/aicheck/reviewDocuments'
import type { DocumentVersion } from '@/types/aicheck'
const PdfEvidencePage = defineAsyncComponent(
  () => import('@/views/AICheck/components/PdfEvidencePage.vue')
)
const props = defineProps<{
  projectId: string
  documentId: string
  fileName: string
  selectedIds: string[]
}>()
const emit = defineEmits<{ close: []; toggle: [version: DocumentVersion, checked: boolean] }>()
const versions = ref<DocumentVersion[]>([])
const loading = ref(false)
const previewingId = ref('')
const error = ref('')
const preview = ref<{ url: string; type: string; label: string } | null>(null)
let generation = 0
let previewAttempt = 0
const clearPreview = () => {
  previewAttempt++
  previewingId.value = ''
  if (preview.value) URL.revokeObjectURL(preview.value.url)
  preview.value = null
}
const close = () => {
  generation++
  clearPreview()
  emit('close')
}
const previewVersion = async (version: DocumentVersion) => {
  clearPreview()
  const context = generation
  const attempt = previewAttempt
  error.value = ''
  previewingId.value = version.id
  try {
    const blob = await getReviewVersionOriginal(props.projectId, props.documentId, version.id)
    if (context !== generation || attempt !== previewAttempt) return
    if (blob.type !== 'application/pdf' && !blob.type.startsWith('image/')) {
      error.value = '此版本格式暂不支持内嵌预览，请在文件资料库查看。'
      return
    }
    preview.value = {
      url: URL.createObjectURL(blob),
      type: blob.type,
      label: `${version.fileName || props.fileName} · ${version.versionNo || version.id}`
    }
  } catch {
    if (context === generation && attempt === previewAttempt)
      error.value = '所选版本原文不可用，未切换到其他版本。'
  } finally {
    if (context === generation && attempt === previewAttempt) previewingId.value = ''
  }
}
watch(
  () => [props.projectId, props.documentId],
  async () => {
    const context = ++generation
    clearPreview()
    versions.value = []
    error.value = ''
    if (!props.documentId) return
    loading.value = true
    try {
      const response = await getDocumentDetailApi(props.projectId, props.documentId)
      if (context !== generation) return
      versions.value = response.data.versions.filter(
        (version) => version.documentId === props.documentId
      )
    } catch {
      if (context === generation) error.value = '版本列表加载失败，请关闭后重试。'
    } finally {
      if (context === generation) loading.value = false
    }
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  generation++
  clearPreview()
})
</script>
<template>
  <ElDialog
    :model-value="true"
    :title="`选择文件版本 · ${fileName}`"
    width="min(820px, 94vw)"
    @close="close"
  >
    <ElAlert
      type="info"
      :closable="false"
      title="可选择不同版本进行比较；每个版本单独计入本次输入。旧版本不会自动满足正式审查要求。"
    />
    <ElAlert v-if="error" type="error" :closable="false" :title="error" />
    <div v-loading="loading" class="version-list">
      <ElEmpty v-if="!loading && !versions.length" description="没有可访问的版本" />
      <div v-for="version in versions" :key="version.id" class="version-row">
        <ElCheckbox
          :model-value="selectedIds.includes(version.id)"
          :disabled="!version.hash"
          @change="(checked) => emit('toggle', version, Boolean(checked))"
        >
          {{ version.versionNo || version.id }} · {{ version.fileName || fileName }}
          {{ version.isCurrent ? '（当前版本）' : '（历史版本）' }}
        </ElCheckbox>
        <span v-if="!version.hash">文件未上传完整</span>
        <ElButton
          link
          :loading="previewingId === version.id"
          :disabled="!version.hash"
          @click="previewVersion(version)"
          >预览此版本</ElButton
        >
      </div>
    </div>
    <template #footer><ElButton @click="close">返回文件选择</ElButton></template>
  </ElDialog>
  <ElDialog
    :model-value="Boolean(preview)"
    append-to-body
    :title="preview?.label"
    width="min(1000px, 96vw)"
    @close="clearPreview"
  >
    <PdfEvidencePage
      v-if="preview?.type === 'application/pdf'"
      :src="preview.url"
      :file-name="preview.label"
    />
    <img v-else-if="preview" :src="preview.url" :alt="preview.label" class="version-image" />
  </ElDialog>
</template>
<style scoped>
.version-list {
  max-height: 50vh;
  min-height: 120px;
  overflow: auto;
}

.version-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.version-row .el-checkbox {
  height: auto;
  min-width: 0;
  flex: 1;
}

.version-row :deep(.el-checkbox__label) {
  white-space: normal;
  overflow-wrap: anywhere;
}

.version-preview {
  width: 100%;
  height: 65vh;
  border: 0;
}

.version-image {
  max-width: 100%;
  max-height: 65vh;
  object-fit: contain;
}

@media (width <= 600px) {
  .version-row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 12px;
  }

  .version-row .el-checkbox {
    min-height: 44px;
    grid-column: 1 / -1;
  }

  .version-row .el-button {
    min-height: 44px;
    grid-column: 2;
  }
}
</style>
