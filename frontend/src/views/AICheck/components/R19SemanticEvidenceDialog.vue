<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElInput,
  ElOption,
  ElSelect,
  ElTag,
  ElMessage
} from 'element-plus'
import type {
  R19EvidenceCandidate,
  R19HumanInputAnswer,
  R19HumanInputQuestion,
  ReviewHumanInputTask
} from '@/api/aicheck'

const props = defineProps<{
  modelValue: boolean
  task?: ReviewHumanInputTask | null
  loading?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'submit', payload: { answers: R19HumanInputAnswer[]; comment?: string }): void
  (event: 'locate', evidence: R19EvidenceCandidate): void
}>()

type AnswerDraft = R19HumanInputAnswer & {
  valueText: string
  sourceUrl: string
  attachmentText: string
}

const drafts = reactive<Record<string, AnswerDraft>>({})
const generalComment = ref('')
const questions = computed<R19HumanInputQuestion[]>(() => props.task?.questions || [])
const evidenceCandidates = computed<R19EvidenceCandidate[]>(
  () => props.task?.evidenceCandidates || []
)
const evidenceOptionLabel = (item: R19EvidenceCandidate) =>
  `${item.evidenceRefId} · ${item.fileName || item.documentVersionId || item.sourceType || '证据'}${
    item.pageNo ? ` · 第 ${item.pageNo} 页` : ''
  }`

const initializeDrafts = () => {
  const activeIds = new Set(questions.value.map((item) => item.questionId))
  for (const key of Object.keys(drafts)) {
    if (!activeIds.has(key)) delete drafts[key]
  }
  if (!props.modelValue) generalComment.value = ''
  for (const question of questions.value) {
    drafts[question.questionId] ||= {
      questionId: question.questionId,
      outcome: 'unknown',
      valueText: '',
      value: undefined,
      evidenceRefIds: [],
      sourceUrl: '',
      sourceRefs: [],
      attachmentText: '',
      attachmentIds: [],
      comment: '',
      attested: false
    }
  }
}

watch(
  () => [props.task?.taskId, props.modelValue],
  () => initializeDrafts(),
  { immediate: true }
)

const splitValues = (value: string) =>
  value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)

const parsedValue = (text: string): unknown => {
  const value = text.trim()
  if (!value) return undefined
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

const validate = () => {
  for (const question of questions.value) {
    const item = drafts[question.questionId]
    if (!item?.outcome) return `请选择 ${question.questionId} 的确认结果`
    if (!item.attested) return `请确认 ${question.questionId} 已由本人核验`
    if (
      ['confirmed', 'rejected'].includes(item.outcome) &&
      !item.evidenceRefIds?.length &&
      !item.sourceUrl.trim() &&
      !item.attachmentText.trim()
    ) {
      return `${question.questionId} 选择已确认或已否定时，必须选择已有证据、填写来源 URL 或补充附件 ID`
    }
  }
  return ''
}

const submit = () => {
  const error = validate()
  if (error) {
    ElMessage.warning(error)
    return
  }
  emit('submit', {
    answers: questions.value.map((question) => {
      const item = drafts[question.questionId]
      return {
        questionId: question.questionId,
        outcome: item.outcome,
        value: parsedValue(item.valueText),
        evidenceRefIds: item.evidenceRefIds || [],
        sourceRefs: item.sourceUrl.trim()
          ? [
              {
                type: 'url',
                url: item.sourceUrl.trim(),
                title: `${question.questionId} 人工核验来源`
              }
            ]
          : [],
        attachmentIds: splitValues(item.attachmentText),
        comment: item.comment?.trim() || undefined,
        attested: item.attested
      }
    }),
    comment: generalComment.value.trim() || undefined
  })
}
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    width="min(1000px, 95vw)"
    title="R19 · 境外牌号材料关键事实确认"
    :close-on-click-modal="false"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <ElAlert
      type="warning"
      :closable="false"
      show-icon
      title="AI 复核已暂停，等待结构化人工输入"
      description="请只确认现有文件无法可靠确定的事实。提交内容会作为新的 EvidenceRef 注入恢复后的 R19 Agent；节点 AI 结论仍由八个原子项固定聚合。"
    />

    <p class="task-description">{{ task?.description }}</p>

    <section v-if="evidenceCandidates.length" class="evidence-pool">
      <div class="evidence-pool__title">
        <strong>AI 已定位证据候选</strong>
        <span
          >共 {{ evidenceCandidates.length }} 条，可查看原文并在问题中直接选择 EvidenceRef。</span
        >
      </div>
      <div class="evidence-pool__list">
        <div
          v-for="evidence in evidenceCandidates"
          :key="evidence.evidenceRefId"
          class="evidence-pool__item"
        >
          <div>
            <code>{{ evidence.evidenceRefId }}</code>
            <span>
              {{
                evidence.fileName || evidence.documentVersionId || evidence.sourceType || '人工证据'
              }}
              <template v-if="evidence.pageNo"> · 第 {{ evidence.pageNo }} 页</template>
            </span>
            <p>{{ evidence.quotedText || '无可展示原文片段' }}</p>
          </div>
          <ElButton
            v-if="evidence.documentVersionId"
            link
            type="primary"
            @click="emit('locate', evidence)"
          >
            查看原文
          </ElButton>
        </div>
      </div>
    </section>

    <div v-if="!questions.length" class="empty-questions">
      当前任务没有可填写的问题，请刷新复核运行。
    </div>
    <article v-for="question in questions" :key="question.questionId" class="question-card">
      <header>
        <div>
          <strong>{{ question.questionId }} · {{ question.title }}</strong>
          <p>{{ question.instruction }}</p>
        </div>
        <div class="clause-tags">
          <ElTag v-for="clause in question.clauseRefs" :key="clause" type="info">
            {{ clause }}
          </ElTag>
        </div>
      </header>

      <div v-if="drafts[question.questionId]" class="answer-grid">
        <label>
          <span>人工确认结果</span>
          <ElSelect v-model="drafts[question.questionId].outcome">
            <ElOption label="已确认" value="confirmed" />
            <ElOption label="已否定" value="rejected" />
            <ElOption label="仍无法确认" value="unknown" />
          </ElSelect>
        </label>
        <label>
          <span>结构化值（可填文本或 JSON）</span>
          <ElInput
            v-model="drafts[question.questionId].valueText"
            placeholder='例如：{"firstUse": true}'
          />
        </label>
        <label class="wide">
          <span>确认说明</span>
          <ElInput
            v-model="drafts[question.questionId].comment"
            type="textarea"
            :rows="3"
            placeholder="说明核验对象、判断事实和差异；不要只填写“同意”"
          />
        </label>
        <label class="wide">
          <span>已有 EvidenceRef（可多选）</span>
          <ElSelect
            v-model="drafts[question.questionId].evidenceRefIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择 AI 已定位且由你核验过的证据"
          >
            <ElOption
              v-for="evidence in evidenceCandidates"
              :key="evidence.evidenceRefId"
              :label="evidenceOptionLabel(evidence)"
              :value="evidence.evidenceRefId"
            />
          </ElSelect>
        </label>
        <label class="wide">
          <span>来源 URL（可选）</span>
          <ElInput v-model="drafts[question.questionId].sourceUrl" />
        </label>
        <label class="wide">
          <span>补充附件 ID（可选，逗号或换行分隔）</span>
          <ElInput v-model="drafts[question.questionId].attachmentText" />
        </label>
        <ElCheckbox v-model="drafts[question.questionId].attested" class="wide">
          我确认已核验本项事实，所填来源、附件和说明真实可追溯
        </ElCheckbox>
      </div>
    </article>

    <label class="general-comment">
      <span>本次人工确认总说明（可选）</span>
      <ElInput v-model="generalComment" type="textarea" :rows="2" />
    </label>

    <template #footer>
      <ElButton @click="emit('update:modelValue', false)">稍后处理</ElButton>
      <ElButton type="primary" :loading="loading" :disabled="!questions.length" @click="submit">
        提交并恢复 AI 复核
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.task-description,
.empty-questions {
  margin: 16px 0;
  color: var(--el-text-color-secondary);
}

.evidence-pool {
  padding: 14px;
  margin: 16px 0;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
}

.evidence-pool__title {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: var(--el-text-color-secondary);
}

.evidence-pool__title strong {
  color: var(--el-text-color-primary);
}

.evidence-pool__list {
  max-height: 220px;
  margin-top: 10px;
  overflow: auto;
}

.evidence-pool__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.evidence-pool__item code {
  margin-right: 8px;
}

.evidence-pool__item p {
  display: -webkit-box;
  margin: 6px 0 0;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.question-card {
  padding: 16px;
  margin-top: 16px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
}

.question-card header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.question-card header p {
  margin: 8px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.clause-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  min-width: 220px;
}

.answer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.answer-grid label,
.general-comment {
  display: grid;
  gap: 6px;
}

.answer-grid label span,
.general-comment span {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.answer-grid .wide {
  grid-column: 1 / -1;
}

.general-comment {
  margin-top: 18px;
}

@media (width <= 760px) {
  .question-card header {
    display: block;
  }

  .clause-tags {
    justify-content: flex-start;
    margin-top: 10px;
  }

  .answer-grid {
    grid-template-columns: 1fr;
  }

  .answer-grid .wide {
    grid-column: auto;
  }
}
</style>
