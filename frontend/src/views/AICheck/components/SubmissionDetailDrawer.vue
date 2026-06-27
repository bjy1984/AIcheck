<script setup lang="ts">
import { computed } from 'vue'
import {
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { SubmissionDetailPayload, SubmissionDraftDetailPayload } from '@/api/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  detail?: SubmissionDraftDetailPayload | SubmissionDetailPayload
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const isSubmission = computed(() => Boolean(props.detail && 'submissionId' in props.detail))
const title = computed(() => (isSubmission.value ? '提交批次详情' : '提交草稿详情'))
const nodeText = computed(() =>
  props.detail?.nodes.map((node) => `${node.nodeId} ${node.name}`).join('、')
)
const detailId = computed(() => {
  if (!props.detail) return '-'
  return 'submissionId' in props.detail ? props.detail.submissionId : props.detail.draftId
})
const detailTime = computed(() => {
  if (!props.detail) return '-'
  return 'submittedAt' in props.detail ? props.detail.submittedAt : props.detail.savedAt
})
const detailNote = computed(() => {
  if (!props.detail) return '-'
  return 'draftId' in props.detail
    ? props.detail.remark || '-'
    : props.detail.submitterComment || '-'
})
const detailStatus = computed(() =>
  props.detail && 'nextStatus' in props.detail ? props.detail.nextStatus : ''
)
const withdrawal = computed(() =>
  props.detail && 'withdrawal' in props.detail ? props.detail.withdrawal : undefined
)
</script>

<template>
  <ElDrawer v-model="visible" :title="title" size="56%" append-to-body>
    <div v-loading="loading" class="submission-detail">
      <ElEmpty v-if="!detail" description="暂无详情" />
      <template v-else>
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem :label="isSubmission ? '提交编号' : '草稿编号'">
            {{ detailId }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="节点范围">{{ nodeText || '-' }}</ElDescriptionsItem>
          <ElDescriptionsItem label="批次名称">
            {{ detail.batchName || '未命名批次' }}
          </ElDescriptionsItem>
          <ElDescriptionsItem :label="isSubmission ? '提交时间' : '保存时间'">
            {{ detailTime }}
          </ElDescriptionsItem>
          <ElDescriptionsItem v-if="detailStatus" label="流转状态">
            <ElTag :type="getStatusTagType(detailStatus)" effect="light">
              {{ detailStatus }}
            </ElTag>
          </ElDescriptionsItem>
          <ElDescriptionsItem label="说明">
            {{ detailNote }}
          </ElDescriptionsItem>
          <ElDescriptionsItem v-if="withdrawal" label="撤回追溯">
            撤回 {{ withdrawal.bindingCount }} 项，{{ withdrawal.withdrawnAt }}，原因：{{
              withdrawal.reason
            }}
          </ElDescriptionsItem>
        </ElDescriptions>

        <div class="section-title">节点</div>
        <ElTable :data="detail.nodes" border height="180">
          <ElTableColumn prop="nodeId" label="节点" width="82" />
          <ElTableColumn prop="name" label="节点名称" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="groupName" label="分组" min-width="160" show-overflow-tooltip />
          <ElTableColumn label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
        </ElTable>

        <div class="section-title">资料项</div>
        <ElTable :data="detail.bindings" border height="240">
          <ElTableColumn prop="nodeId" label="节点" width="82" />
          <ElTableColumn prop="fileName" label="文件" min-width="220" show-overflow-tooltip />
          <ElTableColumn
            prop="requirementName"
            label="资料要求"
            min-width="180"
            show-overflow-tooltip
          />
          <ElTableColumn prop="usage" label="用途" width="110" />
          <ElTableColumn label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.bindingStatus)" size="small" effect="plain">
                {{ row.bindingStatus }}
              </ElTag>
            </template>
          </ElTableColumn>
        </ElTable>

        <template v-if="isSubmission && 'createdTodos' in detail">
          <div class="section-title">后续待办</div>
          <ElTable :data="detail.createdTodos" border height="160">
            <ElTableColumn prop="title" label="待办" min-width="240" show-overflow-tooltip />
            <ElTableColumn prop="assigneeName" label="处理人" width="110" />
            <ElTableColumn prop="priority" label="优先级" width="90" />
            <ElTableColumn prop="deadline" label="截止时间" width="170" />
          </ElTable>
        </template>
      </template>
    </div>
  </ElDrawer>
</template>

<style scoped>
.submission-detail {
  min-height: 360px;
}

.section-title {
  margin: 18px 0 8px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
}
</style>
