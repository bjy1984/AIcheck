<script setup lang="ts">
import { computed } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import type { ProjectTreePayload } from '@/api/aicheck'
import { filterWorkstationNodes, workstationNavigation } from '../workstationNavigation'
const props = defineProps<{
  groups: ProjectTreePayload['groups']
  modelValue: string
  status: string
  idPrefix: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:status': [value: string]
}>()
const nodes = computed(() => props.groups.flatMap((group) => group.nodes))
const statuses = computed(() => [...new Set(nodes.value.map((node) => node.status))])
const visibleCount = computed(() =>
  filterWorkstationNodes(props.groups, props.modelValue, props.status).reduce(
    (total, group) => total + group.nodes.length,
    0
  )
)
</script>
<template>
  <section class="workstation-node-filter" aria-label="工位与节点筛选">
    <label :for="`${idPrefix}-station`">工位</label>
    <ElSelect
      :id="`${idPrefix}-station`"
      placeholder="全部工位"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    >
      <ElOption label="全部工位" value="" />
      <ElOption
        v-for="station in workstationNavigation"
        :key="station.id"
        :value="station.id"
        :label="`${station.id} · ${station.name}（${nodes.filter((node) => station.nodeIds.includes(node.nodeId)).length}）`"
      />
    </ElSelect>
    <label :for="`${idPrefix}-status`">节点状态</label>
    <ElSelect
      :id="`${idPrefix}-status`"
      placeholder="全部状态"
      :model-value="status"
      @update:model-value="emit('update:status', $event)"
    >
      <ElOption label="全部状态" value="" /><ElOption
        v-for="value in statuses"
        :key="value"
        :label="value"
        :value="value"
      />
    </ElSelect>
    <p>显示 {{ visibleCount }} / {{ nodes.length }} 个节点。筛选列表不会切换当前节点。</p>
  </section>
</template>
<style scoped>
.workstation-node-filter {
  display: grid;
  padding: 0 0 16px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  gap: 8px;
}

.workstation-node-filter p {
  margin: 0;
  line-height: 1.6;
}

.workstation-node-filter :deep(.el-select__wrapper) {
  min-height: 44px;
}
</style>
