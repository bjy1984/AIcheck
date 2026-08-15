<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElCard, ElEmpty, ElSkeleton, ElTabPane, ElTabs, ElTag } from 'element-plus'
import type { DateComparisonItem, StandardReference } from '@/api/aicheck'
import type {
  AiReviewRun,
  EvidenceLink,
  ExtractedField,
  MessageItem,
  ReviewOpinion,
  TodoItem
} from '@/types/aicheck'
import { formatConfidence } from '@/utils/confidence'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: string
  latestAiRun?: AiReviewRun
  extractedFields: ExtractedField[]
  evidenceLinks: EvidenceLink[]
  standards: StandardReference[]
  dateComparisons: DateComparisonItem[]
  inspectionLoading: boolean
  todos: TodoItem[]
  messages: MessageItem[]
  reviewOpinions: ReviewOpinion[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  locateEvidence: [evidence: EvidenceLink]
}>()

const activeTab = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const evidenceMap = computed(
  () => new Map(props.evidenceLinks.map((evidence) => [evidence.id, evidence]))
)

const getDateCompareType = (result: DateComparisonItem['result']) => {
  if (result === '覆盖') return 'success'
  if (result === '不覆盖') return 'danger'
  if (result === '缺失') return 'warning'
  return 'info'
}

const hasEvidence = (evidenceLinkId?: string) =>
  Boolean(evidenceLinkId && evidenceMap.value.has(evidenceLinkId))

const handleLocateById = (evidenceLinkId?: string) => {
  if (!evidenceLinkId) return
  const evidence = evidenceMap.value.get(evidenceLinkId)
  if (evidence) emit('locateEvidence', evidence)
}
</script>

<template>
  <ElCard shadow="never" class="panel side-panel">
    <ElTabs v-model="activeTab">
      <ElTabPane label="AI 审查" name="ai">
        <div v-if="latestAiRun" class="ai-box">
          <div class="ai-result">
            <ElTag :type="getStatusTagType(latestAiRun.suggestion.result)" effect="light">
              {{ latestAiRun.suggestion.result }}
            </ElTag>
            <strong>{{ formatConfidence(latestAiRun.suggestion.confidence) }}</strong>
          </div>
          <p>{{ latestAiRun.suggestion.opinionDraft }}</p>
          <div class="field-list">
            <div v-for="field in extractedFields" :key="field.id" class="field-item">
              <span>{{ field.fieldName }}</span>
              <strong>{{ field.fieldValue }}</strong>
              <ElTag :type="['低置信度', '置信度未知'].includes(field.reviewStatus) ? 'warning' : 'success'" size="small">
                {{ formatConfidence(field.confidence) }}
              </ElTag>
            </div>
          </div>
        </div>
        <ElEmpty v-else description="暂无 AI 审查结果" />
      </ElTabPane>

      <ElTabPane label="证据链" name="evidence">
        <div v-if="evidenceLinks.length" class="evidence-list">
          <div v-for="link in evidenceLinks" :key="link.id" class="evidence-item">
            <span class="evidence-type">{{ link.objectType }}</span>
            <strong>{{ link.fileName || link.fieldName || link.objectId }}</strong>
            <p>{{ link.quotedText || `证据对象：${link.objectId}` }}</p>
            <ElButton link type="primary" @click="emit('locateEvidence', link)">定位</ElButton>
          </div>
        </div>
        <ElEmpty v-else description="暂无证据链" />
      </ElTabPane>

      <ElTabPane label="标准依据" name="standards">
        <ElSkeleton v-if="inspectionLoading" :rows="4" animated />
        <div v-else-if="standards.length" class="standard-list">
          <div v-for="standard in standards" :key="standard.clauseId" class="standard-item">
            <div class="standard-title">
              <strong>{{ standard.title }}</strong>
              <ElTag size="small" effect="plain">{{ standard.clauseNo }}</ElTag>
            </div>
            <span>{{ standard.standardName }} · {{ standard.effectiveVersion }}</span>
            <p>{{ standard.summary }}</p>
            <ElButton
              link
              type="primary"
              :disabled="!hasEvidence(standard.evidenceLinkId)"
              @click="handleLocateById(standard.evidenceLinkId)"
            >
              定位依据
            </ElButton>
          </div>
        </div>
        <ElEmpty v-else description="暂无标准依据" />
      </ElTabPane>

      <ElTabPane label="日期比对" name="dates">
        <ElSkeleton v-if="inspectionLoading" :rows="4" animated />
        <div v-else-if="dateComparisons.length" class="date-list">
          <div v-for="item in dateComparisons" :key="item.fieldName" class="date-item">
            <div class="date-title">
              <strong>{{ item.fieldName }}</strong>
              <ElTag :type="getDateCompareType(item.result)" size="small" effect="plain">
                {{ item.result }}
              </ElTag>
            </div>
            <div class="date-compare-grid">
              <div>
                <span>{{ item.leftLabel }}</span>
                <strong>{{ item.leftValue }}</strong>
              </div>
              <div>
                <span>{{ item.rightLabel }}</span>
                <strong>{{ item.rightValue }}</strong>
              </div>
            </div>
            <ElButton
              v-if="item.evidenceLinkIds.length"
              link
              type="primary"
              :disabled="!hasEvidence(item.evidenceLinkIds[0])"
              @click="handleLocateById(item.evidenceLinkIds[0])"
            >
              定位证据
            </ElButton>
          </div>
        </div>
        <ElEmpty v-else description="暂无日期比对" />
      </ElTabPane>

      <ElTabPane label="待办消息" name="todo">
        <div class="todo-list">
          <div v-for="todo in todos" :key="todo.id" class="todo-item">
            <div>
              <strong>{{ todo.title }}</strong>
              <span>{{ todo.assigneeName || '未分配' }} · {{ todo.deadline || '无期限' }}</span>
            </div>
            <ElTag :type="todo.priority === '高' ? 'danger' : 'info'" size="small">
              {{ todo.priority }}
            </ElTag>
          </div>
          <ElEmpty v-if="!todos.length" description="暂无待办" />
        </div>
        <div class="message-list">
          <div v-for="message in messages" :key="message.id" class="message-item">
            <strong>{{ message.title }}</strong>
            <span>{{ message.createdAt }}</span>
          </div>
        </div>
      </ElTabPane>

      <ElTabPane label="审查记录" name="opinion">
        <div v-for="opinion in reviewOpinions" :key="opinion.id" class="opinion-item">
          <ElTag :type="getStatusTagType(opinion.result)" size="small">{{ opinion.result }}</ElTag>
          <p>{{ opinion.opinion }}</p>
          <span>{{ opinion.reviewerName }} · {{ opinion.createdAt }}</span>
        </div>
        <ElEmpty v-if="!reviewOpinions.length" description="暂无审查记录" />
      </ElTabPane>
    </ElTabs>
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.side-panel {
  min-height: 620px;
}

.ai-box p,
.evidence-item p,
.standard-item p,
.opinion-item p {
  margin: 10px 0;
  line-height: 1.7;
  color: #344054;
}

.ai-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.field-list,
.evidence-list,
.standard-list,
.date-list,
.todo-list,
.message-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-item,
.todo-item,
.message-item,
.evidence-item,
.standard-item,
.date-item,
.opinion-item {
  padding: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.field-item,
.todo-item,
.standard-title,
.date-title {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.field-item span,
.standard-item span,
.todo-item span,
.message-item span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #667085;
}

.evidence-type {
  display: inline-block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #667085;
}

.evidence-item :deep(.el-button) {
  padding-left: 0;
}

.standard-title strong,
.date-title strong {
  min-width: 0;
  overflow: hidden;
  color: #1f2937;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.date-compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
}

.date-compare-grid div {
  min-width: 0;
  padding: 8px;
  background: #f8fafc;
  border-radius: 6px;
}

.date-compare-grid span,
.date-compare-grid strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.date-compare-grid span {
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.message-list {
  margin-top: 14px;
}

@media (width <= 1280px) {
  .side-panel {
    margin-bottom: 16px;
  }
}
</style>
