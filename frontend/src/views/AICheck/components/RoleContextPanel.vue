<script setup lang="ts">
import { computed } from 'vue'
import { ElCard, ElProgress, ElTag } from 'element-plus'
import type { NodePackagePayload, Project, RoleCode, TodoItem } from '@/types/aicheck'

const props = defineProps<{
  role: RoleCode
  project?: Project
  packageData?: NodePackagePayload
  todos: TodoItem[]
}>()

const ownerRows = computed(() => [
  { label: '项目编号', value: props.project?.code || '-' },
  { label: '建设单位', value: props.project?.ownerOrgName || '-' },
  { label: '施工单位', value: props.project?.contractorOrgName || '-' },
  { label: '监检机构', value: props.project?.inspectionOrgName || '-' }
])

const archiveProgress = computed(() => {
  const total = props.packageData?.node.requiredProgress.total ?? 0
  const done = props.packageData?.node.requiredProgress.done ?? 0
  return total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
})
</script>

<template>
  <ElCard v-if="role === 'owner'" shadow="never" class="panel role-panel">
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
  font-weight: 600;
}

.owner-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.owner-item,
.todo-row {
  padding: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
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

@media (width <= 768px) {
  .owner-grid {
    grid-template-columns: 1fr;
  }
}
</style>
