<script setup lang="ts">
import { computed } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElSelect,
  ElTag
} from 'element-plus'
import type { ActionCode, AiReviewRun, ReviewOpinion, RoleCode } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  role: RoleCode
  actions: ActionCode[]
  latestAiRun?: AiReviewRun
  reviewResult: ReviewOpinion['result']
  reviewOpinion: string
  correctionReason: string
  evidenceCount: number
  loading: boolean
}>()

const emit = defineEmits<{
  'update:reviewResult': [value: ReviewOpinion['result']]
  'update:reviewOpinion': [value: string]
  'update:correctionReason': [value: string]
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
</script>

<template>
  <ElCard v-if="canReview" shadow="never" class="panel review-panel">
    <template #header>
      <div class="panel-header">
        <span>人工审查</span>
        <ElTag type="info" effect="plain">{{ evidenceCount }} 条证据</ElTag>
      </div>
    </template>

    <ElAlert
      v-if="latestAiRun"
      :closable="false"
      type="info"
      show-icon
      class="ai-alert"
      :title="`AI 建议：${latestAiRun.suggestion.result} / 置信度 ${latestAiRun.suggestion.confidence}%`"
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
      <ElButton type="primary" :disabled="!canSave" :loading="loading" @click="emit('saveReview')">
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
  font-weight: 700;
}

.ai-alert {
  margin-bottom: 12px;
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
</style>
