<script setup lang="ts">
import { computed } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElIcon,
  ElInput,
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
import { evidenceStatusView, isSystemLinked } from '../evidenceProvenance'

const props = defineProps<{
  role: RoleCode
  actions: ActionCode[]
  latestAiRun?: AiReviewRun
  showAiSuggestion?: boolean
  reviewResult: ReviewOpinion['result'] | ''
  reviewOpinion: string
  correctionReason: string
  evidenceCount: number
  confirmedEvidenceLinks?: EvidenceLink[]
  selectedEvidenceIds?: string[]
  saveDisabledReason?: string
  blockingReasons?: string[]
  requiresEvidenceSelection?: boolean
  /** 必传资料或已确认证据不齐：「满足要求」直接置灰，原因在上方提示里。 */
  satisfiedBlocked?: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  'update:reviewResult': [value: ReviewOpinion['result']]
  'update:reviewOpinion': [value: string]
  'update:correctionReason': [value: string]
  'update:selectedEvidenceIds': [value: string[]]
  saveReview: []
  returnCorrection: []
  /** 需补正：先保存结论，再把同一段文字作为补正要求退回施工方。 */
  saveAndReturn: []
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
const systemLinkedCount = computed(
  () => confirmedEvidenceLinks.value.filter((evidence) => isSystemLinked(evidence)).length
)

/**
 * 同一份资料常被多个审查点各挂一条链接（节点 23 实测两条指向同一个 doc），
 * 逐条渲染就是同一段 300 字 OCR 表格连打两遍。选项一条都不能合并——勾选的是链接 id，
 * 合并会让「选中一条」变成「选中两条」——所以只把重复的引文折起来。
 */
const firstQuoteIds = computed(() => {
  const seen = new Set<string>()
  const ids = new Set<string>()
  for (const link of confirmedEvidenceLinks.value) {
    const key = [link.documentVersionId || link.fileName, link.pageNo, evidenceText(link)].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    ids.add(link.id)
  }
  return ids
})
const canSaveReview = computed(() => canSave.value && !props.saveDisabledReason)

const RESULT_OPTIONS: { value: ReviewOpinion['result']; label: string; hint: string }[] = [
  { value: '满足要求', label: '满足要求', hint: '资料和证据齐全，符合要求' },
  { value: '需补正', label: '需补正', hint: '要施工方补交或改正，可直接退回' },
  { value: '证据不足', label: '证据不足', hint: '证据不足，待补件后复核' },
  { value: '不适用', label: '不适用', hint: '本节点对这个工程不适用' }
]
const resultDisabled = (value: ReviewOpinion['result']) =>
  value === '满足要求' && Boolean(props.satisfiedBlocked)
const isCorrection = computed(() => props.reviewResult === '需补正')
const textareaId = `review-opinion-${Math.random().toString(36).slice(2, 8)}`

/** 需补正时一个框写两处：审查意见（存档）和补正要求（发给施工方）用同一段话。 */
const updateText = (value: string) => {
  emit('update:reviewOpinion', value)
  if (isCorrection.value) emit('update:correctionReason', value)
}
const selectResult = (value: ReviewOpinion['result']) => {
  emit('update:reviewResult', value)
  if (value !== '需补正') return
  // 从某条发现「据此退回补正」带过来的是补正原因：切到需补正时两边对齐成同一段
  if (!props.reviewOpinion.trim() && props.correctionReason.trim()) {
    emit('update:reviewOpinion', props.correctionReason)
  } else if (props.reviewOpinion.trim()) {
    emit('update:correctionReason', props.reviewOpinion)
  }
}

const submitMode = computed<'save' | 'saveAndReturn' | 'return'>(() => {
  if (!isCorrection.value || !canReturn.value) return 'save'
  return canSave.value ? 'saveAndReturn' : 'return'
})
const submitLabel = computed(() =>
  submitMode.value === 'saveAndReturn'
    ? '保存并退回补正'
    : submitMode.value === 'return'
      ? '退回补正'
      : '保存结论'
)
const submitHint = computed(() => {
  if (submitMode.value === 'return') return props.reviewOpinion.trim() ? '' : '请先写补正要求'
  if (props.saveDisabledReason) return props.saveDisabledReason
  if (!props.reviewOpinion.trim()) return isCorrection.value ? '请先写补正要求' : '请先写审查意见'
  return ''
})
const submitDisabled = computed(
  () =>
    !props.reviewOpinion.trim() || (submitMode.value === 'return' ? false : !canSaveReview.value)
)
const submit = () => {
  if (submitMode.value === 'saveAndReturn') emit('saveAndReturn')
  else if (submitMode.value === 'return') emit('returnCorrection')
  else emit('saveReview')
}
const evidenceLabel = (evidence: EvidenceLink) =>
  [evidence.fieldName, evidence.fileName, evidence.pageNo ? `第 ${evidence.pageNo} 页` : '']
    .filter(Boolean)
    .join(' · ') || evidence.id
// 人工挂载的整份资料没有字段/引用原文：说明它是怎么来的，而不是把链接 id 甩给用户
const manualBindingCaption = (evidence: EvidenceLink) => {
  const extra = evidence as { source?: string; confirmedByName?: string }
  if (extra.source !== 'manual_binding') return undefined
  return `整份资料 · 人工挂载${extra.confirmedByName ? `（${extra.confirmedByName}）` : ''}`
}
const evidenceText = (evidence: EvidenceLink) =>
  evidence.quotedText ||
  evidence.matchedEvidenceItems?.join('、') ||
  (manualBindingCaption(evidence) ?? '') ||
  evidence.objectId ||
  evidence.id
</script>

<template>
  <!-- 2026-11-04 节点页简化：结论区固定在右栏，一眼看到「能不能判满足要求、为什么」。
       四个结论平铺成一排按钮；只有一个输入框，选「需补正」时它就是发给施工方的补正要求；
       主按钮跟着结论变（需补正＝保存并退回补正），不用在两个框、两个按钮之间来回找。 -->
  <section v-if="canReview" class="review-panel" aria-label="审查结论">
    <h2 class="review-panel-title">审查结论</h2>

    <div v-if="blockingReasons?.length" class="review-gate" role="note">
      <ElIcon class="review-gate-icon" aria-hidden="true"><WarningFilled /></ElIcon>
      <div>
        <strong>暂不能判「满足要求」</strong>
        <ul class="review-gate-list">
          <li v-for="reason in blockingReasons" :key="reason">{{ reason }}</li>
        </ul>
      </div>
    </div>

    <ElAlert
      v-if="latestAiRun && showAiSuggestion !== false"
      :closable="false"
      type="info"
      show-icon
      class="ai-alert"
      :title="`AI 建议：${latestAiRun.suggestion.result} / 置信度 ${formatConfidence(latestAiRun.suggestion.confidence)}`"
      :description="latestAiRun.suggestion.opinionDraft"
    />

    <div v-if="latestAiRun && showAiSuggestion !== false" class="ai-actions">
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

    <div class="review-results" role="radiogroup" aria-label="审查结论">
      <button
        v-for="option in RESULT_OPTIONS"
        :key="option.value"
        type="button"
        role="radio"
        :aria-checked="reviewResult === option.value"
        :class="['review-result', { 'is-active': reviewResult === option.value }]"
        :disabled="!canSave || resultDisabled(option.value)"
        :title="
          resultDisabled(option.value) ? '必传资料或已确认证据还不齐，见上方提示' : option.hint
        "
        @click="selectResult(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="review-field">
      <div class="review-field-label">
        <span>引用证据</span>
        <small v-if="confirmedEvidenceLinks.length">
          {{ selectedEvidenceIds.length }}/{{ confirmedEvidenceLinks.length }} 条已选
          <template v-if="systemLinkedCount"
            >· 其中 {{ systemLinkedCount }} 条系统挂接未经人工核对</template
          >
        </small>
      </div>
      <p v-if="requiresEvidenceSelection" class="review-hint is-warning">
        AI 建议没有可直接采纳的已确认证据，请人工选择后再保存。
      </p>
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
        >
          <span class="review-evidence-label">{{ evidenceLabel(evidence) }}</span>
          <ElTag
            v-if="isSystemLinked(evidence)"
            type="info"
            size="small"
            :title="evidenceStatusView(evidence).hint"
            >系统挂接</ElTag
          >
          <!-- 引文区不跟着勾选：原生 label 激活控件不走冒泡，只 stop 挡不住，必须 prevent。
               用 v-text 而不是插值：pre-wrap 下模板缩进会变成可见的首行空白。 -->
          <small
            v-if="firstQuoteIds.has(evidence.id)"
            class="review-evidence-quote"
            :title="evidenceText(evidence)"
            @click.stop.prevent
            v-text="evidenceText(evidence)"
          ></small>
          <small v-else class="review-evidence-quote is-repeat">引文同上</small>
        </ElCheckbox>
      </ElCheckboxGroup>
      <p v-else class="review-hint is-warning">当前节点暂无已确认证据，不能保存「满足要求」。</p>
    </div>

    <div class="review-field">
      <label class="review-field-label" :for="textareaId">
        <span>{{ isCorrection ? '补正要求' : '审查意见' }}</span>
        <small v-if="isCorrection && canReturn">会随退回发给施工方</small>
      </label>
      <ElInput
        :id="textareaId"
        :model-value="reviewOpinion"
        :disabled="!canSave && !canReturn"
        type="textarea"
        :rows="4"
        :maxlength="isCorrection ? 300 : 500"
        show-word-limit
        :placeholder="
          isCorrection ? '写给施工方：需要补交或改正什么、为什么' : '写下你的判断和依据'
        "
        @update:model-value="updateText"
      />
    </div>

    <div class="review-actions">
      <ElButton
        type="primary"
        class="review-submit"
        :disabled="submitDisabled"
        :loading="loading"
        :title="submitHint"
        @click="submit"
      >
        {{ submitLabel }}
      </ElButton>
      <ElButton
        v-if="submitMode === 'saveAndReturn'"
        text
        :disabled="!canSaveReview || !reviewOpinion.trim()"
        :loading="loading"
        @click="emit('saveReview')"
      >
        只保存结论，先不退回
      </ElButton>
      <small v-if="submitHint" class="review-action-hint">{{ submitHint }}</small>
    </div>
  </section>
</template>

<style scoped>
.review-panel {
  display: grid;
  padding: 16px 18px 18px;
  background: #fff;
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 12px;

  /* 列宽要能缩：auto 列会被长证书表、单行引文撑开，顶出右边界（生产节点 1 实测） */
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.review-panel-title {
  margin: 0;
  font-size: 16px;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.review-gate {
  display: grid;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 20px;
  color: #8a4b08;
  background: #fff8eb;
  border: 1px solid #f3d9a8;
  border-radius: 8px;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
}

.review-gate-icon {
  margin-top: 2px;
  font-size: 16px;
  color: var(--aicheck-warning, #b45309);
}

.review-gate strong {
  display: block;
  font-weight: 600;
}

.review-gate-list {
  padding-left: 16px;
  margin: 2px 0 0;
}

.ai-alert,
.ai-actions {
  margin: 0;
}

.ai-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.review-results {
  display: grid;
  overflow: hidden;
  border: 1px solid #d6deea;
  border-radius: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.review-result {
  min-height: 38px;
  padding: 0 4px;
  font: inherit;
  font-size: 13px;
  color: #27364b;
  cursor: pointer;
  background: #fff;
  border: 0;
}

.review-result + .review-result {
  border-left: 1px solid #d6deea;
}

.review-result:hover:not(:disabled, .is-active) {
  background: #f3f7fd;
}

.review-result.is-active {
  font-weight: 600;
  color: #fff;
  background: var(--el-color-primary, #2f6bff);
}

.review-result:disabled {
  color: #b4bfcd;
  cursor: not-allowed;
  background: #f7f9fc;
}

.review-result:focus-visible {
  position: relative;
  outline: 2px solid var(--el-color-primary, #2f6bff);
  outline-offset: -2px;
}

.review-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.review-field-label {
  display: flex;
  gap: 8px;
  align-items: baseline;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: var(--aicheck-text-strong, #172033);
}

.review-field-label small {
  font-size: 12px;
  font-weight: 400;
  color: #667085;
  text-align: right;
}

.review-hint {
  margin: 0;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
}

.review-hint.is-warning {
  color: var(--aicheck-warning, #b45309);
}

.review-evidence-options {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 2px;
}

.review-evidence-options :deep(.el-checkbox) {
  align-items: flex-start;
  width: 100%;
  height: auto;
  padding: 6px 0;
  margin-right: 0;
  white-space: normal;
}

.review-evidence-options :deep(.el-checkbox__input) {
  margin-top: 3px;
}

.review-evidence-options :deep(.el-checkbox__label) {
  display: flex;
  min-width: 0;
  flex: 1 1 auto;
  padding-left: 8px;
  gap: 2px 6px;
  flex-wrap: wrap;
  align-items: center;
}

.review-evidence-label {
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
  overflow-wrap: anywhere;
}

/* 引文只留一行，悬停看全文：结论区要短，原文在左边核对项和原件里 */
.review-evidence-quote {
  display: block;
  width: 100%;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-actions {
  display: grid;
  gap: 6px;
  justify-items: stretch;
}

.review-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.review-submit {
  height: 40px;
  font-size: 14px;
}

.review-action-hint {
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  text-align: center;
}
</style>
