<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElCard, ElEmpty, ElTag, ElTree } from 'element-plus'
import type { ProjectTreePayload } from '@/api/aicheck'
import type { ProjectTreeNode } from '@/types/aicheck'
import { getStatusTagType } from './status'

type ProjectTreeViewNode =
  | {
      id: string
      label: string
      type: 'overview'
      nodeCount: number
      fileCount: number
    }
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
  showOverview?: boolean
  emptyDescription?: string
}>()

const emit = defineEmits<{
  select: [node: ProjectTreeNode]
  selectOverview: []
}>()

const treeProps = {
  children: 'children',
  label: 'label'
} as const
const treeRef = ref<InstanceType<typeof ElTree>>()
const expandedTreeKeys = ref<string[]>([])
const expansionInitialized = ref(false)

const totalNodeCount = computed(() =>
  props.groups.reduce((sum, group) => sum + group.nodes.length, 0)
)
const totalFileCount = computed(() =>
  props.groups.reduce(
    (sum, group) => sum + group.nodes.reduce((nodeSum, node) => nodeSum + node.fileCount, 0),
    0
  )
)

const treeData = computed<ProjectTreeViewNode[]>(() => {
  const groups = props.groups.map((group, index) => ({
    id: `group-${group.groupName || index}`,
    label: group.groupName,
    type: 'group' as const,
    children: group.nodes.map((node) => ({
      id: `node-${node.nodeId}`,
      label: node.name,
      type: 'node' as const,
      node
    }))
  }))
  if (props.showOverview === false) return groups
  return [
    {
      id: 'overview',
      label: '项目总览',
      type: 'overview',
      nodeCount: totalNodeCount.value,
      fileCount: totalFileCount.value
    },
    ...groups
  ]
})

const activeTreeKey = computed(() =>
  props.activeNodeId ? `node-${props.activeNodeId}` : 'overview'
)
const groupTreeKeys = computed(() =>
  treeData.value.filter((item) => item.type === 'group').map((item) => item.id)
)

const activeGroupKey = computed(() => {
  if (!props.activeNodeId) return ''
  const groupIndex = props.groups.findIndex((group) =>
    group.nodes.some((node) => Number(node.nodeId) === Number(props.activeNodeId))
  )
  if (groupIndex < 0) return ''
  const group = props.groups[groupIndex]
  return `group-${group.groupName || groupIndex}`
})

const syncExpandedKeys = async (expandActiveGroup = false) => {
  await nextTick()
  const validKeys = new Set(groupTreeKeys.value)
  const nextKeys = expandedTreeKeys.value.filter((key) => validKeys.has(key))
  if (expandActiveGroup && activeGroupKey.value && !nextKeys.includes(activeGroupKey.value)) {
    nextKeys.push(activeGroupKey.value)
  }
  expandedTreeKeys.value = nextKeys
  for (const key of nextKeys) {
    const node = treeRef.value?.getNode(key)
    if (node) node.expanded = true
  }
}

watch(
  () => props.groups,
  () => {
    if (!expansionInitialized.value) {
      expansionInitialized.value = true
      void syncExpandedKeys(true)
      return
    }
    void syncExpandedKeys(false)
  }
)

watch(
  () => props.activeNodeId,
  () => {
    void syncExpandedKeys(true)
  }
)

const handleNodeClick = (data: ProjectTreeViewNode) => {
  if (data.type === 'overview') {
    emit('selectOverview')
    return
  }
  if (data.type === 'node') {
    emit('select', data.node)
  }
}

const handleNodeExpand = (data: ProjectTreeViewNode) => {
  if (data.type !== 'group') return
  if (!expandedTreeKeys.value.includes(data.id)) {
    expandedTreeKeys.value = [...expandedTreeKeys.value, data.id]
  }
}

const handleNodeCollapse = (data: ProjectTreeViewNode) => {
  if (data.type !== 'group') return
  expandedTreeKeys.value = expandedTreeKeys.value.filter((key) => key !== data.id)
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
      v-if="treeData.length"
      ref="treeRef"
      class="tree-scroll node-tree"
      :data="treeData"
      node-key="id"
      :props="treeProps"
      :current-node-key="activeTreeKey"
      :default-expanded-keys="expandedTreeKeys"
      highlight-current
      :expand-on-click-node="true"
      @node-click="handleNodeClick"
      @node-expand="handleNodeExpand"
      @node-collapse="handleNodeCollapse"
    >
      <template #default="{ data }">
        <span
          v-if="data.type === 'overview'"
          :aria-pressed="!activeNodeId"
          :class="['node-overview-button', { 'is-active': !activeNodeId }]"
        >
          <span class="node-index">总</span>
          <span class="node-main">
            <span class="node-name">{{ data.label }}</span>
            <span class="node-meta">节点 {{ data.nodeCount }} · 资料 {{ data.fileCount }}</span>
          </span>
          <ElTag type="primary" size="small" effect="plain">总览</ElTag>
        </span>
        <span v-else-if="data.type === 'group'" class="node-group-title">{{ data.label }}</span>
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
    <ElEmpty v-else :description="emptyDescription || '暂无节点'" />
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

.tree-scroll {
  --el-tree-node-hover-bg-color: transparent;

  max-height: calc(100vh - 270px);
  overflow: auto;
  background: transparent;
}

.node-group-title {
  display: block;
  width: 100%;
  padding: 8px 0;
  font-size: 13px;
  font-weight: 600;
  color: #475467;
  cursor: pointer;
  background: #fff;
  user-select: none;
}

.node-tree :deep(.el-tree-node__content) {
  height: auto;
  min-height: 32px;
  padding-left: 0 !important;
  line-height: 1.2;
  color: #26364e;
  background: transparent;
}

.node-tree :deep(.el-tree-node__content:hover),
.node-tree :deep(.el-tree-node.is-current > .el-tree-node__content) {
  background: transparent;
}

.node-tree :deep(.el-tree-node__expand-icon) {
  display: inline-flex;
  width: 22px;
  height: 22px;
  margin-right: 4px;
  font-size: 14px;
  color: #6e7d92;
  border-radius: 6px;
  flex: 0 0 22px;
  align-items: center;
  justify-content: center;
}

.node-tree :deep(.el-tree-node__expand-icon svg) {
  width: 13px;
  height: 13px;
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

.node-overview-button,
.node-button {
  --el-button-bg-color: #fff;
  --el-button-border-color: #e5e7eb;
  --el-button-hover-bg-color: #eff6ff;
  --el-button-hover-border-color: #2563eb;
  --el-button-hover-text-color: #26364e;
  --el-button-active-bg-color: #eff6ff;
  --el-button-active-border-color: #2563eb;
  --el-button-active-text-color: #26364e;

  display: grid;
  width: 100%;
  min-height: 46px;
  padding: 7px 8px;
  margin-bottom: 5px;
  margin-left: 4px;
  color: #26364e;
  text-align: left;
  white-space: normal;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.node-button:hover,
.node-button:focus-visible,
.node-overview-button:hover,
.node-overview-button:focus-visible,
.node-overview-button.is-active,
.node-button.is-active {
  background: #eff6ff;
  border-color: #2563eb;
  outline: none;
}

.node-overview-button {
  margin-bottom: 8px;
  margin-left: 0;
  background: linear-gradient(180deg, #f8fbff, #eef5ff);
  border-color: #cfe0ff;
}

.node-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 600;
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
  font-weight: 600;
  line-height: 1.35;
  white-space: normal;
  overflow-wrap: anywhere;
}

.node-meta {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  font-size: 12px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (width <= 1280px) {
  .tree-panel {
    margin-bottom: 16px;
  }

  .tree-scroll {
    max-height: 520px;
  }
}
</style>
