<script setup lang="ts">
import { computed } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElSkeleton,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { ArchiveItemDetailPayload } from '@/api/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  detail?: ArchiveItemDetailPayload
  loading: boolean
  issue?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  preview: [url: string]
  download: [url: string]
  openExportTask: [exportId: string]
  retry: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
</script>

<template>
  <ElDrawer v-model="visible" title="归档资料详情" size="640px" class="archive-detail-drawer">
    <ElSkeleton v-if="loading" :rows="8" animated />

    <ElAlert
      v-else-if="issue"
      class="archive-detail-error"
      type="error"
      title="归档资料详情加载失败"
      :closable="false"
      show-icon
    >
      <div class="drawer-error-content">
        <span>{{ issue }}</span>
        <ElButton link type="primary" @click="emit('retry')">重新加载归档详情</ElButton>
      </div>
    </ElAlert>

    <template v-else-if="detail">
      <div class="archive-head">
        <div>
          <span>{{ detail.item.type }}</span>
          <strong>{{ detail.item.name }}</strong>
        </div>
        <ElTag :type="getStatusTagType(detail.item.status)" effect="plain">
          {{ detail.item.status || '可查看' }}
        </ElTag>
      </div>

      <ElDescriptions :column="2" border>
        <ElDescriptionsItem label="节点">{{ detail.item.nodeId || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="来源">{{ detail.item.sourceOrgName || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="更新时间">{{ detail.item.updatedAt }}</ElDescriptionsItem>
        <ElDescriptionsItem label="证据数量">{{ detail.evidenceLinks.length }}</ElDescriptionsItem>
        <ElDescriptionsItem label="关联报告">
          {{ detail.report?.reportNo || detail.document?.fileName || '-' }}
        </ElDescriptionsItem>
      </ElDescriptions>

      <div class="drawer-actions">
        <ElButton :disabled="!detail.preview?.url" @click="emit('preview', detail.preview!.url)">
          预览
        </ElButton>
        <ElButton
          type="primary"
          :disabled="!detail.download?.url"
          @click="emit('download', detail.download!.url)"
        >
          下载
        </ElButton>
      </div>

      <div class="section-title">证据引用</div>
      <ElTable :data="detail.evidenceLinks" border height="220">
        <ElTableColumn prop="objectType" label="类型" width="120" />
        <ElTableColumn prop="fileName" label="文件" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="pageNo" label="页码" width="72" />
        <ElTableColumn prop="quotedText" label="摘录" min-width="220" show-overflow-tooltip />
      </ElTable>

      <div class="section-title">导出任务</div>
      <ElTable :data="detail.relatedExportTasks" border height="170">
        <ElTableColumn prop="id" label="任务号" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="status" label="状态" width="96">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
              {{ row.status }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="createdAt" label="创建时间" width="150" />
        <ElTableColumn label="操作" width="74" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="emit('openExportTask', row.id)">详情</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </template>

    <ElEmpty v-else description="暂无归档详情" />
  </ElDrawer>
</template>

<style scoped>
.archive-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.archive-head span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.archive-head strong {
  color: #1f2937;
}

.drawer-actions {
  display: flex;
  gap: 10px;
  margin: 12px 0;
}

.drawer-actions :deep(.el-button) {
  margin-left: 0;
}

.section-title {
  margin: 14px 0 8px;
  font-size: 14px;
  font-weight: 700;
}

.drawer-error-content {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  line-height: 1.6;
}

.drawer-error-content span {
  overflow-wrap: anywhere;
}

@media (width <= 768px) {
  :global(.archive-detail-drawer.el-drawer) {
    width: 100vw !important;
    max-width: 100vw;
  }

  .drawer-error-content {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
