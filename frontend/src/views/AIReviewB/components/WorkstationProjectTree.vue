<script setup lang="ts">
import { computed } from 'vue'
import type { ProjectTreePayload } from '@/api/aicheck'
import type { ProjectTreeNode } from '@/types/aicheck'
import ProjectNodeTree from '@/views/AICheck/components/ProjectNodeTree.vue'
import WorkstationNodeFilter from './WorkstationNodeFilter.vue'
import { filterWorkstationNodes } from '../workstationNavigation'
const props = defineProps<{
  groups: ProjectTreePayload['groups']
  enabled: boolean
  activeNodeId: number
  idPrefix: string
}>()
const station = defineModel<string>({ required: true })
const status = defineModel<string>('status', { required: true })
const emit = defineEmits<{ select: [ProjectTreeNode]; selectOverview: [] }>()
const filtered = computed(() =>
  props.enabled ? filterWorkstationNodes(props.groups, station.value, status.value) : props.groups
)
</script>
<template>
  <WorkstationNodeFilter
    v-if="enabled"
    v-model="station"
    v-model:status="status"
    :groups="groups"
    :id-prefix="idPrefix"
  />
  <ProjectNodeTree
    :groups="filtered"
    :overview-groups="groups"
    :active-node-id="activeNodeId"
    :show-overview="true"
    empty-description="暂无项目审核节点"
    @select="emit('select', $event)"
    @select-overview="emit('selectOverview')"
  />
</template>
