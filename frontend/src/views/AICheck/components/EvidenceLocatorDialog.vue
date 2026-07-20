<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElDescriptions, ElDescriptionsItem, ElDialog, ElEmpty, ElTag } from 'element-plus'
import { getDocumentDetailApi, getDocumentOriginalBlobApi } from '@/api/aicheck'
import type { DocumentDetailPayload } from '@/api/aicheck'
import type { EvidenceLink, ExtractedField } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { formatConfidence } from '@/utils/confidence'

const props = defineProps<{
  modelValue: boolean
  projectId?: string
  evidence?: EvidenceLink
  extractedFields: ExtractedField[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const linkedField = computed(() => {
  if (!props.evidence) return undefined
  if (props.evidence.objectType === 'extractedField') {
    return props.extractedFields.find((field) => field.id === props.evidence?.objectId)
  }
  return props.extractedFields.find((field) => field.evidenceLinkId === props.evidence?.id)
})

const locationTitle = computed(() => {
  if (!props.evidence) return '证据定位'
  if (props.evidence.objectType === 'knowledgeClause') return '标准条款定位'
  if (props.evidence.objectType === 'extractedField') return 'OCR 字段定位'
  return '文件证据定位'
})

const previewDetail = ref<DocumentDetailPayload>()
const previewObjectUrl = ref('')
const previewLoading = ref(false)
const previewError = ref('')
let previewRequestSeq = 0

const evidenceTypeLabel = computed(() => props.evidence?.objectType || 'nodeEvidenceLink')
const evidenceProjectId = computed(() => props.projectId || props.evidence?.projectId || '')
const evidenceDocumentId = computed(() => props.evidence?.documentId || '')
const directPreviewUrl = computed(() => String(props.evidence?.previewUrl || ''))
const previewTypeForSource = (source: string) => {
  const cleanSource = source.split('#')[0].split('?')[0].toLowerCase()
  if (cleanSource.endsWith('.pdf') || source.includes('/knowledge/files/')) return 'pdf'
  if (/\.(png|jpe?g|webp|gif|bmp)$/.test(cleanSource)) return 'image'
  return 'unsupported'
}
const filePreview = computed(
  () =>
    (directPreviewUrl.value
      ? {
          url: directPreviewUrl.value,
          previewType: previewTypeForSource(props.evidence?.fileName || directPreviewUrl.value) as
            | 'pdf'
            | 'image'
            | 'unsupported'
        }
      : previewDetail.value?.preview) || undefined
)
const canLoadFilePreview = computed(
  () =>
    visible.value &&
    !!props.evidence &&
    (props.evidence.objectType === 'knowledgeClause'
      ? !!directPreviewUrl.value
      : !!evidenceProjectId.value && !!evidenceDocumentId.value)
)
const filePreviewAvailable = computed(
  () => !!filePreview.value?.url && filePreview.value.previewType !== 'unsupported'
)
const filePreviewRequiresBlob = computed(
  () => filePreviewAvailable.value && String(filePreview.value?.url || '').startsWith('/api/')
)
const filePreviewFrameUrl = computed(() => {
  const url = String(filePreview.value?.url || '')
  if (filePreviewRequiresBlob.value) return previewObjectUrl.value
  return previewObjectUrl.value || url
})
const filePreviewSrc = computed(() => {
  const url = filePreviewFrameUrl.value
  if (!url || filePreview.value?.previewType !== 'pdf') return url
  const pageNo = Number(
    props.evidence?.pageNo || directPreviewUrl.value.match(/#page=(\d+)/)?.[1] || 0
  )
  const baseUrl = url.split('#')[0]
  return pageNo > 0 ? `${baseUrl}#page=${pageNo}` : url
})
const filePreviewIsImage = computed(() => filePreview.value?.previewType === 'image')
const filePreviewIsPdf = computed(() => filePreview.value?.previewType === 'pdf')
const filePreviewUnavailableText = computed(() => {
  if (props.evidence?.objectType === 'knowledgeClause' && !directPreviewUrl.value)
    return '该条款尚未关联规范库原文件，请联系知识库管理员补齐文件映射。'
  if (!evidenceDocumentId.value) return '当前证据没有关联项目文件，无法加载原文。'
  if (!filePreview.value?.url) return '当前文件详情没有返回原文地址。'
  if (String(filePreview.value.url).startsWith('mock://'))
    return '当前文件只有占位地址，尚未生成真实原文预览。'
  if (filePreview.value.previewType === 'unsupported') return '当前文件类型暂不支持在线预览。'
  return '当前文件没有可预览的真实原文。'
})

const revokePreviewObjectUrl = () => {
  if (!previewObjectUrl.value) return
  URL.revokeObjectURL(previewObjectUrl.value)
  previewObjectUrl.value = ''
}

const resetPreviewState = () => {
  previewRequestSeq += 1
  revokePreviewObjectUrl()
  previewDetail.value = undefined
  previewError.value = ''
  previewLoading.value = false
}

const loadFilePreview = async () => {
  const requestSeq = ++previewRequestSeq
  revokePreviewObjectUrl()
  previewDetail.value = undefined
  previewError.value = ''
  if (!canLoadFilePreview.value) return
  previewLoading.value = true
  try {
    let url = directPreviewUrl.value
    if (!url) {
      const detail = await getDocumentDetailApi(evidenceProjectId.value, evidenceDocumentId.value)
      if (requestSeq !== previewRequestSeq) return
      previewDetail.value = detail.data
      url = String(detail.data.preview?.url || '')
    }
    if (!url || url.startsWith('mock://') || filePreview.value?.previewType === 'unsupported')
      return
    const requestUrl = url.split('#')[0]
    if (requestUrl.startsWith('/api/')) {
      const res = await getDocumentOriginalBlobApi(requestUrl)
      if (requestSeq !== previewRequestSeq) return
      previewObjectUrl.value = URL.createObjectURL(res.data)
    }
  } catch (error) {
    if (requestSeq !== previewRequestSeq) return
    previewError.value = getAicheckErrorMessage(error, '原文预览加载失败，请尝试下载后查看。')
  } finally {
    if (requestSeq === previewRequestSeq) previewLoading.value = false
  }
}

const handlePreviewImageError = () => {
  previewError.value = '图片预览加载失败，请尝试下载后查看。'
}

watch(
  () =>
    [
      visible.value,
      props.evidence?.id,
      props.evidence?.documentId,
      props.evidence?.objectType,
      props.evidence?.previewUrl,
      props.projectId
    ] as const,
  ([open]) => {
    if (open) {
      void loadFilePreview()
    } else {
      resetPreviewState()
    }
  }
)

onBeforeUnmount(() => {
  resetPreviewState()
})
</script>

<template>
  <ElDialog v-model="visible" :title="locationTitle" width="1040px" append-to-body>
    <template v-if="evidence">
      <ElDescriptions
        v-if="evidence.objectType !== 'knowledgeClause'"
        :column="2"
        border
        class="evidence-summary"
      >
        <ElDescriptionsItem label="证据类型">
          <ElTag type="info" effect="plain">{{ evidenceTypeLabel }}</ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="置信度">
          {{ formatConfidence(evidence.confidence) }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="文件">
          {{ evidence.fileName || '-' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="页码">
          {{ evidence.pageNo || '-' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="字段">
          {{ evidence.fieldName || linkedField?.fieldName || '-' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="对象 ID">
          {{ evidence.objectId }}
        </ElDescriptionsItem>
      </ElDescriptions>

      <div v-else class="standard-file-name">
        <span>文件名称</span>
        <strong>{{ evidence.fileName || '-' }}</strong>
      </div>

      <div :class="['locator-grid', { 'is-standard': evidence.objectType === 'knowledgeClause' }]">
        <section class="preview-box">
          <div class="preview-title">定位预览</div>
          <div
            v-if="evidence.objectType === 'knowledgeClause' && !filePreviewAvailable"
            class="clause-preview"
          >
            <strong>{{ evidence.objectId }}</strong>
            <p>{{ evidence.quotedText || filePreviewUnavailableText }}</p>
          </div>
          <div v-else class="file-preview" v-loading="previewLoading">
            <ElAlert
              v-if="previewError"
              :title="previewError"
              type="warning"
              :closable="false"
              show-icon
            />
            <template v-else-if="filePreviewAvailable">
              <div v-if="!filePreviewFrameUrl" class="preview-placeholder">原文预览加载中</div>
              <img
                v-else-if="filePreviewIsImage"
                class="file-preview-image"
                :src="filePreviewSrc"
                :alt="evidence.fileName || '证据原文'"
                @error="handlePreviewImageError"
              />
              <iframe
                v-else-if="filePreviewIsPdf"
                class="file-preview-frame"
                :src="filePreviewSrc"
                :title="evidence.fileName || '证据原文'"
              ></iframe>
              <ElAlert
                v-else
                title="当前文件类型暂不支持在线定位预览"
                :description="filePreviewUnavailableText"
                type="warning"
                :closable="false"
                show-icon
              />
            </template>
            <ElAlert
              v-else
              title="当前文件没有可预览的真实原文"
              :description="filePreviewUnavailableText"
              type="warning"
              :closable="false"
              show-icon
            />
          </div>
        </section>

        <section v-if="evidence.objectType !== 'knowledgeClause'" class="detail-box">
          <div class="preview-title">提取信息</div>
          <div class="detail-row">
            <span>引用文本</span>
            <strong>{{ evidence.quotedText || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>OCR 字段</span>
            <strong>{{ linkedField?.fieldName || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>字段值</span>
            <strong>{{ linkedField?.fieldValue || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>复核状态</span>
            <strong>{{ linkedField?.reviewStatus || '-' }}</strong>
          </div>
        </section>
      </div>
    </template>
    <ElEmpty v-else description="未选择证据" />
  </ElDialog>
</template>

<style scoped>
.evidence-summary {
  margin-bottom: 14px;
}

.standard-file-name {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 14px;
  align-items: center;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.standard-file-name span {
  color: #667085;
}

.standard-file-name strong {
  color: #1f2937;
}

.locator-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(240px, 0.8fr);
  gap: 14px;
}

.locator-grid.is-standard {
  grid-template-columns: minmax(0, 1fr);
}

.preview-box,
.detail-box {
  min-height: 260px;
  padding: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.preview-title {
  margin-bottom: 10px;
  font-size: 14px;
  font-weight: 600;
}

.file-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 520px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
}

.preview-placeholder {
  display: flex;
  width: 100%;
  min-height: 520px;
  align-items: center;
  justify-content: center;
  color: #667085;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.file-preview-frame {
  width: 100%;
  min-height: 520px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.file-preview-image {
  display: block;
  width: 100%;
  max-height: 620px;
  object-fit: contain;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.clause-preview p {
  line-height: 1.7;
  color: #344054;
}

.detail-row {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid #eef2f7;
}

.detail-row span {
  color: #667085;
}

.detail-row strong {
  color: #1f2937;
}

@media (width <= 768px) {
  .locator-grid {
    grid-template-columns: 1fr;
  }
}
</style>
