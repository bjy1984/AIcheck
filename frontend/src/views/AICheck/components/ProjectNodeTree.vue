<script setup lang="ts">
import { computed } from 'vue'
import { ElCard, ElEmpty, ElTag, ElTree } from 'element-plus'
import type { ProjectTreePayload } from '@/api/aicheck'
import type { ProjectTreeNode } from '@/types/aicheck'
import { getStatusTagType } from './status'

type ProjectTreeViewNode =
  | {
      id: string
      label: string
      type: 'group'
      children: ProjectTreeViewNode[]
    }
  | {
      id: string
      label: string
      type: 'node'
      node: ProjectTreeNode
    }

const props = defineProps<{
  groups: ProjectTreePayload['groups']
  activeNodeId: number
}>()

const emit = defineEmits<{
  select: [node: ProjectTreeNode]
}>()

const treeProps = {
  children: 'children',
  label: 'label'
} as const

const treeData = computed<ProjectTreeViewNode[]>(() =>
  props.groups.map((group, index) => ({
    id: `group-${index}`,
    label: group.groupName,
    type: 'group',
    children: group.nodes.map((node) => ({
      id: `node-${node.nodeId}`,
      label: node.name,
      type: 'node',
      node
    }))
  }))
)

const activeTreeKey = computed(() => `node-${props.activeNodeId}`)

const handleNodeClick = (data: ProjectTreeViewNode) => {
  if (data.type === 'node') {
    emit('select', data.node)
  }
}
</script>

<template>
  <ElCard shadow="never" class="panel tree-panel">
    <template #header>
      <div class="panel-header">
        <span>监检节点</span>
        <ElTag type="info" effect="plain">{{ groups.length }} 类</ElTag>
      </div>
    </template>

    <ElTree
      v-if="groups.length"
      class="tree-scroll node-tree"
      :data="treeData"
      node-key="id"
      :props="treeProps"
      :current-node-key="activeTreeKey"
      highlight-current
      :expand-on-click-node="false"
      @node-click="handleNodeClick"
    >
      <template #default="{ data }">
        <span v-if="data.type === 'group'" class="node-group-title">{{ data.label }}</span>
        <span
          v-else
          :aria-pressed="data.node.nodeId === activeNodeId"
          :class="['node-button', { 'is-active': data.node.nodeId === activeNodeId }]"
        >
          <span class="node-index">{{ data.node.nodeId }}</span>
          <span class="node-main">
            <span class="node-name">{{ data.node.name }}</span>
            <span class="node-meta">
              {{ data.node.inspectionType }} 类 · {{ data.node.requiredProgress.done }}/{{
                data.node.requiredProgress.total
              }}
            </span>
          </span>
          <ElTag :type="getStatusTagType(data.node.status)" size="small" effect="plain">
            {{ data.node.status }}
          </ElTag>
        </span>
      </template>
    </ElTree>
    <ElEmpty v-else description="暂无节点" />
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
  font-weight: 700;
}

.tree-scroll {
  max-height: calc(100vh - 270px);
  overflow: auto;
  background: transparent;
  --el-tree-node-hover-bg-color: transparent;
}

.node-group-title {
  display: block;
  width: 100%;
  padding: 8px 0;
  font-size: 13px;
  font-weight: 700;
  color: #475467;
  background: #ffffff;
}

.node-tree :deep(.el-tree-node__content) {
  height: auto;
  min-height: 34px;
  padding-left: 0 !important;
  color: #26364e;
  line-height: 1.2;
  background: transparent;
}

.node-tree :deep(.el-tree-node__content:hover),
.node-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: transparent;
}

.node-tree :deep(.el-tree-node__expand-icon) {
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  margin-right: 2px;
  color: #6e7d92;
  font-size: 18px;
}

.node-tree :deep(.el-tree-node__expand-icon svg) {
  width: 18px;
  height: 18px;
}

.node-tree :deep(.el-tree-node__children .el-tree-node__content) {
  padding-left: 0 !important;
}

.node-tree :deep(.el-tree-node__expand-icon.is-leaf) {
  flex: 0 0 0;
  width: 0;
  height: 0;
  margin-right: 0;
  visibility: hidden;
}

.node-button {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  width: 100%;
  min-height: 58px;
  padding: 9px 8px;
  margin-bottom: 6px;
  margin-left: 8px;
  color: #26364e;
  text-align: left;
  cursor: pointer;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  white-space: normal;
  --el-button-bg-color: #ffffff;
  --el-button-border-color: #e5e7eb;
  --el-button-hover-bg-color: #eff6ff;
  --el-button-hover-border-color: #2563eb;
  --el-button-hover-text-color: #26364e;
  --el-button-active-bg-color: #eff6ff;
  --el-button-active-border-color: #2563eb;
  --el-button-active-text-color: #26364e;
}

.node-button:hover,
.node-button:focus-visible,
.node-button.is-active {
  border-color: #2563eb;
  outline: none;
  background: #eff6ff;
}

.node-button.is-active {
  border-left-color: transparent;
}

.node-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  font-size: 13px;
  font-weight: 700;
  color: #1d4ed8;
  background: #dbeafe;
  border-radius: 6px;
}

.node-main {
  min-width: 0;
}

.node-name {
  display: block;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
  white-space: normal;
}

.node-meta {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #667085;
}

@media (max-width: 1280px) {
  .tree-panel {
    margin-bottom: 16px;
  }

  .tree-scroll {
    max-height: 520px;
  }
}
</style>
