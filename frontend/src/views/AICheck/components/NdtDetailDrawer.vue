<script setup lang="ts">
import { computed } from 'vue'
import {
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElSkeleton,
  ElTabPane,
  ElTabs,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { NdtFeedbackDetailPayload, NdtReportDetailPayload } from '@/api/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  mode: 'report' | 'feedback'
  reportDetail?: NdtReportDetailPayload
  feedbackDetail?: NdtFeedbackDetailPayload
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const title = computed(() => (props.mode === 'report' ? '检测报告详情' : '监检反馈详情'))
</script>

<template>
  <ElDrawer v-model="visible" :title="title" size="680px" class="ndt-detail-drawer">
    <ElSkeleton v-if="loading" :rows="8" animated />

    <template v-else-if="mode === 'report' && reportDetail">
      <ElDescriptions :column="2" border>
        <ElDescriptionsItem label="报告编号">{{ reportDetail.report.reportNo }}</ElDescriptionsItem>
        <ElDescriptionsItem label="方法">{{ reportDetail.report.method }}</ElDescriptionsItem>
        <ElDescriptionsItem label="状态">
          <ElTag :type="getStatusTagType(reportDetail.report.status)" size="small" effect="plain">
            {{ reportDetail.report.status }}
          </ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="上传时间">{{
          reportDetail.report.uploadedAt
        }}</ElDescriptionsItem>
        <ElDescriptionsItem label="文件">{{
          reportDetail.document?.fileName || '-'
        }}</ElDescriptionsItem>
        <ElDescriptionsItem label="结论">{{
          reportDetail.report.conclusion || '-'
        }}</ElDescriptionsItem>
      </ElDescriptions>

      <ElTabs class="detail-tabs">
        <ElTabPane label="关联底片" name="films">
          <ElTable :data="reportDetail.films" border height="220">
            <ElTableColumn prop="filmNo" label="底片编号" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="method" label="方法" width="70" />
            <ElTableColumn prop="evaluationLevel" label="级别" width="80" />
            <ElTableColumn label="状态" width="96">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElTabPane>

        <ElTabPane label="检测记录" name="records">
          <ElTable :data="reportDetail.records" border height="240">
            <ElTableColumn prop="recordNo" label="记录编号" min-width="160" show-overflow-tooltip />
            <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="testDate" label="检测日期" width="112" />
            <ElTableColumn label="抽查状态" width="100">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.sampleStatus)" size="small" effect="plain">
                  {{ row.sampleStatus }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="conclusion" label="结论" min-width="220" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>

        <ElTabPane label="相关反馈" name="feedback">
          <ElTable :data="reportDetail.feedback" border height="220">
            <ElTableColumn prop="title" label="反馈事项" min-width="180" show-overflow-tooltip />
            <ElTableColumn prop="deadline" label="期限" width="150" />
            <ElTableColumn label="状态" width="96">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElTabPane>
      </ElTabs>
    </template>

    <template v-else-if="mode === 'feedback' && feedbackDetail">
      <ElDescriptions :column="2" border>
        <ElDescriptionsItem label="反馈事项">{{
          feedbackDetail.feedback.title
        }}</ElDescriptionsItem>
        <ElDescriptionsItem label="节点">{{ feedbackDetail.feedback.nodeId }}</ElDescriptionsItem>
        <ElDescriptionsItem label="状态">
          <ElTag
            :type="getStatusTagType(feedbackDetail.feedback.status)"
            size="small"
            effect="plain"
          >
            {{ feedbackDetail.feedback.status }}
          </ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="期限">{{
          feedbackDetail.feedback.deadline || '-'
        }}</ElDescriptionsItem>
        <ElDescriptionsItem label="说明">{{
          feedbackDetail.feedback.description
        }}</ElDescriptionsItem>
      </ElDescriptions>

      <ElTabs class="detail-tabs">
        <ElTabPane label="抽查记录" name="records">
          <ElTable :data="feedbackDetail.records" border height="240">
            <ElTableColumn prop="recordNo" label="记录编号" min-width="160" show-overflow-tooltip />
            <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="method" label="方法" width="70" />
            <ElTableColumn label="抽查状态" width="100">
              <template #default="{ row }">
                <ElTag :type="getStatusTagType(row.sampleStatus)" size="small" effect="plain">
                  {{ row.sampleStatus }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="conclusion" label="结论" min-width="220" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>

        <ElTabPane label="关联资料" name="related">
          <ElTable :data="feedbackDetail.reports" border height="160" class="stacked-table">
            <ElTableColumn prop="reportNo" label="报告编号" min-width="160" show-overflow-tooltip />
            <ElTableColumn prop="method" label="方法" width="70" />
            <ElTableColumn prop="conclusion" label="结论" min-width="220" show-overflow-tooltip />
          </ElTable>
          <ElTable :data="feedbackDetail.films" border height="160">
            <ElTableColumn prop="filmNo" label="底片编号" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
            <ElTableColumn prop="defectCode" label="问题" min-width="160" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>

        <ElTabPane label="处理轨迹" name="timeline">
          <ElTable :data="feedbackDetail.timeline" border height="220">
            <ElTableColumn prop="title" label="节点" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="actorName" label="处理人" width="90" />
            <ElTableColumn prop="status" label="状态" width="96" />
            <ElTableColumn prop="createdAt" label="时间" width="150" />
            <ElTableColumn prop="comment" label="说明" min-width="220" show-overflow-tooltip />
          </ElTable>
        </ElTabPane>
      </ElTabs>
    </template>

    <ElEmpty v-else description="暂无无损检测详情" />
  </ElDrawer>
</template>

<style scoped>
.detail-tabs {
  margin-top: 12px;
}

.stacked-table {
  margin-bottom: 12px;
}

@media (max-width: 768px) {
  .ndt-detail-drawer :deep(.el-drawer) {
    width: 100% !important;
  }
}
</style>
