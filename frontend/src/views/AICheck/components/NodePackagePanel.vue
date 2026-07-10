<script setup lang="ts">
import { computed } from 'vue'
import {
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElAlert,
  ElEmpty,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { NodePackagePayload } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  packageData?: NodePackagePayload
  loading: boolean
  issue?: {
    type: 'error' | 'forbidden' | 'readonly' | 'empty'
    title: string
    message?: string
  }
  retryLoading?: boolean
}>()

const emit = defineEmits<{
  openFile: [documentId: string]
  retry: []
}>()

const selectedNode = computed(() => props.packageData?.node)
const requirements = computed(() => props.packageData?.requirements || [])
const bindings = computed(() => props.packageData?.bindings || [])
const projectFiles = computed(() => props.packageData?.projectFiles || [])
const projectFileStatus = (file: NodePackagePayload['projectFiles'][number]) =>
  file.primaryBinding?.bindingStatus || file.bindings?.[0]?.bindingStatus || file.fileStatus
const boundProgress = computed(() => {
  const total = selectedNode.value?.requiredProgress.total || requirements.value.length || 0
  const done = selectedNode.value?.requiredProgress.done || bindings.value.length
  return total ? `${done}/${total}` : '-'
})
const alertType = computed(() => {
  if (props.issue?.type === 'error') return 'error'
  if (props.issue?.type === 'forbidden') return 'warning'
  return 'info'
})
</script>

<template>
  <ElCard shadow="never" class="panel node-panel" v-loading="loading">
    <template #header>
      <div class="panel-header">
        <div>
          <span>{{ selectedNode?.name || '节点包' }}</span>
          <div class="panel-subtitle">
            {{ selectedNode?.groupName || '-' }} · 节点 {{ selectedNode?.nodeId || '-' }}
          </div>
        </div>
        <ElTag :type="getStatusTagType(selectedNode?.status)" effect="light">
          {{ selectedNode?.status || '-' }}
        </ElTag>
      </div>
    </template>

    <div v-if="issue" class="node-issue">
      <ElEmpty v-if="issue.type === 'empty'" :description="issue.title">
        <div v-if="issue.message" class="node-issue-message">{{ issue.message }}</div>
        <ElButton type="primary" :loading="retryLoading" @click="emit('retry')">
          重新加载节点
        </ElButton>
      </ElEmpty>
      <ElAlert v-else :title="issue.title" :type="alertType" :closable="false" show-icon>
        <template #default>
          <div class="node-issue-content">
            <span>{{ issue.message }}</span>
            <ElButton size="small" :loading="retryLoading" @click="emit('retry')">
              重新加载节点
            </ElButton>
          </div>
        </template>
      </ElAlert>
    </div>

    <template v-else-if="packageData">
      <ElDescriptions :column="3" border class="node-descriptions">
        <ElDescriptionsItem label="检验类别">
          {{ selectedNode?.inspectionType || '-' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="必传进度">{{ boundProgress }}</ElDescriptionsItem>
        <ElDescriptionsItem label="资料数">{{ bindings.length }}</ElDescriptionsItem>
      </ElDescriptions>

      <div class="section-title">资料要求</div>
      <ElTable :data="requirements" border height="190">
        <ElTableColumn prop="name" label="资料名称" min-width="180" show-overflow-tooltip />
        <ElTableColumn label="要求" width="96">
          <template #default="{ row }">
            <ElTag :type="row.requiredType === '必传' ? 'danger' : 'info'" size="small">
              {{ row.requiredType }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="note" label="说明" min-width="160" show-overflow-tooltip />
      </ElTable>

      <div class="section-title">已挂载资料</div>
      <ElTable :data="bindings" border height="210">
        <ElTableColumn prop="fileName" label="文件" min-width="190" show-overflow-tooltip />
        <ElTableColumn prop="usage" label="用途" width="100" />
        <ElTableColumn prop="sourceOrgName" label="来源" width="130" show-overflow-tooltip />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.bindingStatus)" size="small" effect="plain">
              {{ row.bindingStatus }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="82" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="emit('openFile', row.documentId)">详情</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <div class="section-title">项目资料池</div>
      <ElTable :data="projectFiles" border height="180">
        <ElTableColumn prop="fileName" label="文件" min-width="190" show-overflow-tooltip />
        <ElTableColumn prop="sourceOrgName" label="来源" width="120" show-overflow-tooltip />
        <ElTableColumn prop="currentOcrStatus" label="OCR" width="90" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(projectFileStatus(row))" size="small" effect="plain">
              {{ projectFileStatus(row) }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="updatedAt" label="更新时间" width="160" />
        <ElTableColumn label="操作" width="82" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="emit('openFile', row.id)">详情</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <slot name="actions"></slot>
    </template>

    <ElEmpty v-else description="请选择节点" />
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.panel-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  font-weight: 600;
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #667085;
}

.node-descriptions {
  margin-bottom: 16px;
}

.node-issue {
  min-height: 420px;
}

.node-issue-content {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  line-height: 22px;
}

.node-issue-content span,
.node-issue-message {
  overflow-wrap: anywhere;
}

.node-issue-message {
  margin-bottom: 12px;
  color: #667085;
}

.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

@media (width <= 1280px) {
  .node-panel {
    margin-bottom: 16px;
  }
}

@media (width <= 768px) {
  .node-issue-content {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
