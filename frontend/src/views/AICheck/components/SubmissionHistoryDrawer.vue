<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElDrawer, ElEmpty, ElTable, ElTableColumn, ElTag } from 'element-plus'
import type { SubmissionDraftSummary, SubmissionSummary } from '@/api/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  drafts: SubmissionDraftSummary[]
  submissions: SubmissionSummary[]
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  refresh: []
  openDraft: [draftId: string]
  restoreDraft: [draftId: string]
  openSubmission: [submissionId: string]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const nodeText = (nodeNames: string[], nodeIds: number[]) =>
  nodeNames.length ? nodeNames.join('、') : nodeIds.join('、')

const withdrawalText = (row: SubmissionSummary) => {
  if (!row.withdrawal) return '未撤回'
  return `撤回 ${row.withdrawal.bindingCount} 项：${row.withdrawal.reason}`
}
</script>

<template>
  <ElDrawer
    v-model="visible"
    title="提交历史与草稿"
    size="min(860px, 92vw)"
    append-to-body
    class="submission-history-drawer"
  >
    <div v-loading="loading" class="submission-history">
      <div class="history-toolbar">
        <div>
          <div class="history-title">草稿和已提交批次</div>
          <div class="history-subtitle">从这里恢复草稿、核对节点范围，或追溯已提交快照。</div>
        </div>
        <ElButton :loading="loading" @click="emit('refresh')">刷新</ElButton>
      </div>

      <section class="history-section">
        <div class="section-title">
          <span>提交草稿</span>
          <ElTag type="info" effect="plain">{{ drafts.length }} 条</ElTag>
        </div>
        <ElTable
          v-if="drafts.length"
          :data="drafts"
          border
          height="240"
          class="submission-draft-table"
        >
          <ElTableColumn prop="batchName" label="草稿批次" min-width="210" show-overflow-tooltip>
            <template #default="{ row }">{{ row.batchName || row.draftId }}</template>
          </ElTableColumn>
          <ElTableColumn label="节点范围" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ nodeText(row.nodeNames, row.nodeIds) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="bindingCount" label="资料项" width="86" />
          <ElTableColumn prop="savedAt" label="保存时间" width="170" />
          <ElTableColumn label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <ElButton link type="primary" @click="emit('restoreDraft', row.draftId)">
                恢复草稿
              </ElButton>
              <ElButton link type="primary" @click="emit('openDraft', row.draftId)">
                详情
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="暂无提交草稿" />
      </section>

      <section class="history-section">
        <div class="section-title">
          <span>已提交批次</span>
          <ElTag type="success" effect="plain">{{ submissions.length }} 条</ElTag>
        </div>
        <ElTable
          v-if="submissions.length"
          :data="submissions"
          border
          height="260"
          class="submission-history-table"
        >
          <ElTableColumn prop="batchName" label="提交批次" min-width="210" show-overflow-tooltip>
            <template #default="{ row }">{{ row.batchName || row.submissionId }}</template>
          </ElTableColumn>
          <ElTableColumn label="节点范围" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ nodeText(row.nodeNames, row.nodeIds) }}</template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="116">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.nextStatus)" size="small" effect="plain">
                {{ row.nextStatus }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="撤回追溯" min-width="190" show-overflow-tooltip>
            <template #default="{ row }">
              <ElTag
                :type="row.withdrawal ? 'warning' : 'info'"
                size="small"
                effect="plain"
                class="withdrawal-tag"
              >
                {{ withdrawalText(row) }}
              </ElTag>
              <span v-if="row.withdrawal" class="withdrawal-time">
                {{ row.withdrawal.withdrawnAt }}
              </span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="bindingCount" label="资料项" width="86" />
          <ElTableColumn prop="todoCount" label="待办" width="76" />
          <ElTableColumn prop="submittedAt" label="提交时间" width="170" />
          <ElTableColumn label="操作" width="88" fixed="right">
            <template #default="{ row }">
              <ElButton link type="primary" @click="emit('openSubmission', row.submissionId)">
                详情
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElEmpty v-else description="暂无已提交批次" />
      </section>
    </div>
  </ElDrawer>
</template>

<style scoped>
.submission-history {
  min-height: 420px;
}

.history-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.history-title {
  font-size: 16px;
  font-weight: 700;
  color: #1f2937;
}

.history-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #667085;
}

.history-section + .history-section {
  margin-top: 20px;
}

.section-title {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
}

.withdrawal-tag {
  max-width: 100%;
}

.withdrawal-time {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
}

@media (width <= 768px) {
  .history-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
