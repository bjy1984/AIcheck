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
  ElTag
} from 'element-plus'
import { getDocumentOriginalBlobApi } from '@/api/aicheck'
import type { DocumentDetailPayload } from '@/api/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
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
const previewEmbeddable = computed(() => {
  const url = String(preview.value?.url || '')
  return previewAvailable.value && !url.startsWith('mock://')
})
const previewFrameUrl = computed(() => previewObjectUrl.value || preview.value?.url || '')

const revokePreviewObjectUrl = () => {
  if (!previewObjectUrl.value) return
  URL.revokeObjectURL(previewObjectUrl.value)
  previewObjectUrl.value = ''
}

const loadPreviewOriginal = async () => {
  revokePreviewObjectUrl()
  previewOriginalError.value = ''
  const url = String(preview.value?.url || '')
  if (!previewEmbeddable.value || !url.startsWith('/api/')) return
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
  if (typeof confidence !== 'number') return '-'
  return `${Math.round(confidence * 100)}%`
}
</script>

<template>
  <ElDialog v-model="visible" title="文件详情" width="960px" append-to-body class="file-dialog">
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
              :disabled="!previewAvailable"
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
            <div class="preview-body" :class="{ 'preview-body--disabled': !previewAvailable }">
              <template v-if="previewAvailable">
                <div
                  v-if="previewEmbeddable"
                  class="preview-frame-host"
                  v-loading="previewLoadingOriginal"
                >
                  <ElAlert
                    v-if="previewOriginalError"
                    :title="previewOriginalError"
                    type="warning"
                    :closable="false"
                    show-icon
                  />
                  <iframe
                    v-else
                    class="preview-frame"
                    :src="previewFrameUrl"
                    :title="document.fileName"
                  />
                </div>
                <template v-else>
                  <strong>{{ document.fileName }}</strong>
                  <span>{{ preview?.contentType || document.fileType }} · {{ fileSizeText }}</span>
                  <span>有效期至 {{ preview?.expiresAt }}</span>
                  <code>{{ preview?.url }}</code>
                </template>
              </template>
              <ElAlert
                v-else
                title="当前格式暂不支持在线预览"
                type="warning"
                :closable="false"
                show-icon
              />
            </div>
          </div>

          <div class="detail-side">
            <ElDescriptions :column="1" border>
              <ElDescriptionsItem label="文件状态">
                <ElTag :type="getStatusTagType(document.fileStatus)" size="small" effect="plain">
                  {{ document.fileStatus }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="OCR 状态">
                <ElTag :type="getStatusTagType(document.currentOcrStatus)" size="small">
                  {{ document.currentOcrStatus }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="当前版本">
                {{ currentVersion?.versionNo || '-' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="文件大小">{{ fileSizeText }}</ElDescriptionsItem>
              <ElDescriptionsItem label="绑定节点">{{ bindings.length }}</ElDescriptionsItem>
            </ElDescriptions>
          </div>
        </div>

        <div class="section-title">历史版本</div>
        <ElTable :data="versions" border height="150">
          <ElTableColumn prop="versionNo" label="版本" width="90" />
          <ElTableColumn prop="hash" label="文件 Hash" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="uploaderName" label="上传人" width="100" />
          <ElTableColumn prop="uploadTime" label="上传时间" width="170" />
          <ElTableColumn label="当前" width="80">
            <template #default="{ row }">
              <ElTag v-if="row.isCurrent" type="success" size="small" effect="plain">当前</ElTag>
              <span v-else>-</span>
            </template>
          </ElTableColumn>
        </ElTable>

        <div class="section-title">OCR 字段</div>
        <ElTable :data="extractedFields" border height="160">
          <ElTableColumn prop="fieldName" label="字段" width="140" show-overflow-tooltip />
          <ElTableColumn prop="fieldValue" label="识别值" min-width="180" show-overflow-tooltip />
          <ElTableColumn prop="pageNo" label="页码" width="80" />
          <ElTableColumn label="置信度" width="92">
            <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
          </ElTableColumn>
          <ElTableColumn label="复核状态" width="110">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.reviewStatus)" size="small" effect="plain">
                {{ row.reviewStatus }}
              </ElTag>
            </template>
          </ElTableColumn>
        </ElTable>

        <div class="section-title">证据定位</div>
        <ElTable :data="evidenceLinks" border height="150">
          <ElTableColumn prop="objectType" label="对象" width="140" />
          <ElTableColumn prop="fieldName" label="字段" width="120" show-overflow-tooltip />
          <ElTableColumn prop="quotedText" label="引用内容" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="pageNo" label="页码" width="80" />
          <ElTableColumn label="置信度" width="92">
            <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
          </ElTableColumn>
        </ElTable>
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
  font-weight: 700;
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
  grid-template-columns: minmax(0, 1.7fr) minmax(260px, 0.9fr);
  gap: 14px;
  align-items: stretch;
}

.preview-shell {
  min-height: 210px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.preview-toolbar {
  display: flex;
  height: 42px;
  padding: 0 12px;
  font-weight: 700;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.preview-body {
  display: flex;
  min-height: 168px;
  flex-direction: column;
  gap: 8px;
  justify-content: center;
  padding: 18px;
  color: #475467;
}

.preview-frame-host {
  width: 100%;
  min-height: 360px;
}

.preview-frame {
  width: 100%;
  min-height: 360px;
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
  min-width: 0;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 700;
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
