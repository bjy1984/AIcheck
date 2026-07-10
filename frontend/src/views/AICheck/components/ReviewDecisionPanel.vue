<script setup lang="ts">
import { computed } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElSelect,
  ElTag
} from 'element-plus'
import type {
  ActionCode,
  AiReviewRun,
  EvidenceLink,
  ReviewOpinion,
  RoleCode
} from '@/types/aicheck'
import { formatConfidence } from '@/utils/confidence'
import { getStatusTagType } from './status'

const props = defineProps<{
  role: RoleCode
  actions: ActionCode[]
  latestAiRun?: AiReviewRun
  reviewResult: ReviewOpinion['result']
  reviewOpinion: string
  correctionReason: string
  evidenceCount: number
  confirmedEvidenceLinks?: EvidenceLink[]
  selectedEvidenceIds?: string[]
  saveDisabledReason?: string
  blockingReasons?: string[]
  requiresEvidenceSelection?: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  'update:reviewResult': [value: ReviewOpinion['result']]
  'update:reviewOpinion': [value: string]
  'update:correctionReason': [value: string]
  'update:selectedEvidenceIds': [value: string[]]
  saveReview: []
  returnCorrection: []
  adoptAi: [suggestionId: string]
  rejectAi: [suggestionId: string]
}>()

const actionSet = computed(() => new Set(props.actions))
const canReview = computed(() => props.role === 'inspection')
const canSave = computed(() => canReview.value && actionSet.value.has('review:save'))
const canReturn = computed(() => canReview.value && actionSet.value.has('review:return-correction'))
const canAdopt = computed(
  () => canReview.value && actionSet.value.has('ai:adopt') && props.latestAiRun
)
const canReject = computed(
  () => canReview.value && actionSet.value.has('ai:reject') && props.latestAiRun
)
const selectedEvidenceIds = computed({
  get: () => props.selectedEvidenceIds || [],
  set: (value: string[]) => emit('update:selectedEvidenceIds', value)
})
const confirmedEvidenceLinks = computed(() => props.confirmedEvidenceLinks || [])
const canSaveReview = computed(() => canSave.value && !props.saveDisabledReason)
const evidenceLabel = (evidence: EvidenceLink) =>
  [evidence.fieldName, evidence.fileName, evidence.pageNo ? `第 ${evidence.pageNo} 页` : '']
    .filter(Boolean)
    .join(' · ') || evidence.id
const evidenceText = (evidence: EvidenceLink) =>
  evidence.quotedText ||
  evidence.matchedEvidenceItems?.join('、') ||
  evidence.objectId ||
  evidence.id
</script>

<template>
  <ElCard v-if="canReview" shadow="never" class="panel review-panel">
    <template #header>
      <div class="panel-header">
        <span>人工审查</span>
        <ElTag type="info" effect="plain">
          {{ confirmedEvidenceLinks.length }} / {{ evidenceCount }} 条 confirmed 证据
        </ElTag>
      </div>
    </template>

    <ElAlert
      v-if="blockingReasons?.length"
      class="review-gate-alert"
      type="warning"
      :closable="false"
      show-icon
      title="正式审查存在前置阻断"
    >
      <ul class="review-gate-list">
        <li v-for="reason in blockingReasons" :key="reason">{{ reason }}</li>
      </ul>
    </ElAlert>

    <ElAlert
      v-if="latestAiRun"
      :closable="false"
      type="info"
      show-icon
      class="ai-alert"
      :title="`AI 建议：${latestAiRun.suggestion.result} / 置信度 ${formatConfidence(latestAiRun.suggestion.confidence)}`"
      :description="latestAiRun.suggestion.opinionDraft"
    />

    <div v-if="latestAiRun" class="ai-actions">
      <ElButton
        :disabled="!canAdopt"
        :loading="loading"
        @click="emit('adoptAi', latestAiRun.suggestion.id)"
      >
        采纳为草稿
      </ElButton>
      <ElButton
        :disabled="!canReject"
        :loading="loading"
        @click="emit('rejectAi', latestAiRun.suggestion.id)"
      >
        驳回建议
      </ElButton>
      <ElTag :type="getStatusTagType(latestAiRun.status)" effect="plain">
        {{ latestAiRun.status }}
      </ElTag>
    </div>

    <ElForm label-position="top" class="review-form">
      <ElFormItem label="审查结论">
        <ElSelect
          :model-value="reviewResult"
          :disabled="!canSave"
          @update:model-value="emit('update:reviewResult', $event)"
        >
          <ElOption label="满足要求" value="满足要求" />
          <ElOption label="需补正" value="需补正" />
          <ElOption label="不适用" value="不适用" />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="结论引用证据">
        <ElAlert
          v-if="requiresEvidenceSelection"
          class="review-evidence-alert"
          type="warning"
          :closable="false"
          show-icon
          title="AI 建议没有可直接采纳的 confirmed 证据，请人工选择后再保存正式意见。"
        />
        <ElCheckboxGroup
          v-if="confirmedEvidenceLinks.length"
          v-model="selectedEvidenceIds"
          class="review-evidence-options"
          :disabled="!canSave"
        >
          <ElCheckbox
            v-for="evidence in confirmedEvidenceLinks"
            :key="evidence.id"
            :label="evidence.id"
            border
          >
            <span class="review-evidence-label">{{ evidenceLabel(evidence) }}</span>
            <small>{{ evidenceText(evidence) }}</small>
          </ElCheckbox>
        </ElCheckboxGroup>
        <ElAlert
          v-else
          type="warning"
          :closable="false"
          show-icon
          title="当前节点暂无 confirmed 证据，不能保存“满足要求”正式结论。"
        />
      </ElFormItem>
      <ElFormItem label="人工审查意见">
        <ElInput
          :model-value="reviewOpinion"
          :disabled="!canSave"
          type="textarea"
          :rows="4"
          maxlength="500"
          show-word-limit
          @update:model-value="emit('update:reviewOpinion', $event)"
        />
      </ElFormItem>
      <ElFormItem label="退回补正原因">
        <ElInput
          :model-value="correctionReason"
          :disabled="!canReturn"
          type="textarea"
          :rows="3"
          maxlength="300"
          show-word-limit
          @update:model-value="emit('update:correctionReason', $event)"
        />
      </ElFormItem>
    </ElForm>

    <div class="review-actions">
      <span v-if="saveDisabledReason" class="review-action-hint">{{ saveDisabledReason }}</span>
      <ElButton
        type="primary"
        :disabled="!canSaveReview"
        :loading="loading"
        :title="saveDisabledReason"
        @click="emit('saveReview')"
      >
        保存审查意见
      </ElButton>
      <ElButton
        type="danger"
        plain
        :disabled="!canReturn"
        :loading="loading"
        @click="emit('returnCorrection')"
      >
        退回补正
      </ElButton>
    </div>
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.review-panel {
  margin-bottom: 16px;
}

.panel-header,
.ai-actions,
.review-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.panel-header {
  min-height: 32px;
  font-weight: 600;
}

.ai-alert {
  margin-bottom: 12px;
}

.review-gate-alert,
.review-evidence-alert {
  margin-bottom: 12px;
}

.review-gate-list {
  padding-left: 18px;
  margin: 4px 0 0;
}

.ai-actions {
  justify-content: flex-start;
  margin-bottom: 12px;
}

.review-form {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.review-actions {
  justify-content: flex-end;
}

.review-evidence-options {
  display: grid;
  gap: 8px;
}

.review-evidence-options :deep(.el-checkbox) {
  align-items: flex-start;
  width: 100%;
  height: auto;
  min-height: 44px;
  padding: 8px 10px;
  margin-right: 0;
  white-space: normal;
}

.review-evidence-label,
.review-evidence-options small {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-evidence-options small,
.review-action-hint {
  font-size: 12px;
  color: #667085;
}

.review-action-hint {
  margin-right: auto;
}
</style>
