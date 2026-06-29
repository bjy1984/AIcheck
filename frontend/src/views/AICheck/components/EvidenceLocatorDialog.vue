<script setup lang="ts">
import { computed } from 'vue'
import { ElDescriptions, ElDescriptionsItem, ElDialog, ElEmpty, ElTag } from 'element-plus'
import type { EvidenceLink, ExtractedField } from '@/types/aicheck'

const props = defineProps<{
  modelValue: boolean
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
</script>

<template>
  <ElDialog v-model="visible" :title="locationTitle" width="720px" append-to-body>
    <template v-if="evidence">
      <ElDescriptions :column="2" border class="evidence-summary">
        <ElDescriptionsItem label="证据类型">
          <ElTag type="info" effect="plain">{{ evidence.objectType }}</ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="置信度">
          {{ evidence.confidence ? `${Math.round(evidence.confidence * 100)}%` : '-' }}
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

      <div class="locator-grid">
        <section class="preview-box">
          <div class="preview-title">定位预览</div>
          <div v-if="evidence.objectType === 'knowledgeClause'" class="clause-preview">
            <strong>{{ evidence.objectId }}</strong>
            <p>{{ evidence.quotedText || '标准条款内容将在真实知识库服务接入后展示。' }}</p>
          </div>
          <div v-else class="file-preview">
            <div class="mock-page">
              <span>{{ evidence.fileName || evidence.objectId }}</span>
              <strong>第 {{ evidence.pageNo || 1 }} 页</strong>
              <mark>{{ evidence.quotedText || linkedField?.fieldValue || '证据片段' }}</mark>
            </div>
          </div>
        </section>

        <section class="detail-box">
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

.locator-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(240px, 0.8fr);
  gap: 14px;
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
  font-weight: 700;
}

.file-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 210px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
}

.mock-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 78%;
  min-height: 160px;
  padding: 18px;
  color: #344054;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

.mock-page mark {
  padding: 4px 6px;
  color: #7c2d12;
  background: #fef3c7;
  border-radius: 4px;
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
