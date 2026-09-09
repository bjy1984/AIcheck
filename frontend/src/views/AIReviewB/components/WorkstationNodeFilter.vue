<script setup lang="ts">
import { computed } from 'vue'
import { ElOption, ElSelect } from 'element-plus'
import type { ProjectTreePayload } from '@/api/aicheck'
import {
  filterWorkstationNodes,
  workstationCounts,
  workstationNavigation
} from '../workstationNavigation'
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
const stationNodes = computed(() =>
  filterWorkstationNodes(props.groups, props.modelValue, '').flatMap((group) => group.nodes)
)
const counts = computed(() => workstationCounts(props.groups, props.modelValue))
const stationOptions = computed(() =>
  workstationNavigation.map((station) => ({
    ...station,
    counts: workstationCounts(props.groups, station.id)
  }))
)
const statuses = computed(() => [
  ...new Set([
    ...stationNodes.value.map((node) => node.status),
    ...(props.status ? [props.status] : [])
  ])
])
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
        v-for="station in stationOptions"
        :key="station.id"
        :value="station.id"
        :label="`${station.id} · ${station.name}（${station.counts.total} 节点，${station.counts.review + station.counts.confirm} 待处理）`"
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
        :label="`${value}（${stationNodes.filter((node) => node.status === value).length}）`"
        :value="value"
      />
    </ElSelect>
    <p role="status" aria-live="polite">
      {{ modelValue ? '当前工位' : '全部工位' }}：{{ counts.review }} 待审查，{{
        counts.confirm
      }}
      待人工确认，{{ counts.correction }} 待补正。
    </p>
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
