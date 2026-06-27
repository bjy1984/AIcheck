<script setup lang="ts">
import { computed } from 'vue'
import { ElCard, ElProgress, ElTable, ElTableColumn, ElTag } from 'element-plus'
import type { NodePackagePayload, Project, RoleCode, TodoItem } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  role: RoleCode
  project?: Project
  packageData?: NodePackagePayload
  todos: TodoItem[]
}>()

const ndtRecords = computed(() => [
  {
    reportNo: 'RT-R2-20260625',
    weldNo: 'W-24-RT-018',
    method: 'RT',
    filmCount: 18,
    status: props.packageData?.node.status || '待审查'
  },
  {
    reportNo: 'UT-U1-20260625',
    weldNo: 'W-40-UT-006',
    method: 'UT',
    filmCount: 0,
    status: '待提交'
  }
])

const ownerRows = computed(() => [
  { label: '项目编号', value: props.project?.code || '-' },
  { label: '建设单位', value: props.project?.ownerOrgName || '-' },
  { label: '施工单位', value: props.project?.contractorOrgName || '-' },
  { label: '监检机构', value: props.project?.inspectionOrgName || '-' }
])

const archiveProgress = computed(() => {
  const total = props.packageData?.node.requiredProgress.total || 69
  const done = props.packageData?.node.requiredProgress.done || 0
  return Math.min(100, Math.round((done / total) * 100))
})
</script>

<template>
  <ElCard v-if="role === 'ndt'" shadow="never" class="panel role-panel">
    <template #header>
      <div class="panel-header">
        <span>无损检测资料</span>
        <ElTag type="info" effect="plain">节点 40/41/42</ElTag>
      </div>
    </template>

    <ElTable :data="ndtRecords" border height="190">
      <ElTableColumn prop="reportNo" label="报告编号" min-width="150" />
      <ElTableColumn prop="weldNo" label="焊口/底片" min-width="130" />
      <ElTableColumn prop="method" label="方法" width="70" />
      <ElTableColumn prop="filmCount" label="底片" width="70" />
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </ElTag>
        </template>
      </ElTableColumn>
    </ElTable>
  </ElCard>

  <ElCard v-else-if="role === 'owner'" shadow="never" class="panel role-panel">
    <template #header>
      <div class="panel-header">
        <span>建设方只读概览</span>
        <ElTag type="success" effect="plain">只读</ElTag>
      </div>
    </template>

    <div class="owner-grid">
      <div v-for="row in ownerRows" :key="row.label" class="owner-item">
        <span>{{ row.label }}</span>
        <strong>{{ row.value }}</strong>
      </div>
    </div>

    <div class="progress-block">
      <div class="progress-title">
        <span>当前节点资料进度</span>
        <strong>{{ archiveProgress }}%</strong>
      </div>
      <ElProgress :percentage="archiveProgress" :stroke-width="8" />
    </div>
  </ElCard>

  <ElCard v-else-if="role === 'contractor'" shadow="never" class="panel role-panel">
    <template #header>
      <div class="panel-header">
        <span>施工方待办</span>
        <ElTag type="warning" effect="plain">{{ todos.length }} 项</ElTag>
      </div>
    </template>

    <div class="todo-compact">
      <div v-for="todo in todos.slice(0, 3)" :key="todo.id" class="todo-row">
        <strong>{{ todo.title }}</strong>
        <span>{{ todo.deadline || '无期限' }}</span>
      </div>
      <div v-if="!todos.length" class="empty-text">暂无施工方待办</div>
    </div>
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.role-panel {
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  font-weight: 700;
}

.owner-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.owner-item,
.todo-row {
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}

.owner-item span,
.todo-row span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.owner-item strong,
.todo-row strong {
  color: #1f2937;
}

.progress-block {
  margin-top: 14px;
}

.progress-title {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.todo-compact {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-text {
  color: #667085;
}

@media (max-width: 768px) {
  .owner-grid {
    grid-template-columns: 1fr;
  }
}
</style>
