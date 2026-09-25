<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElOption, ElSelect } from 'element-plus'
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
  handoffBusy?: boolean
  handoffError?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:status': [value: string]
  refreshHandoffs: []
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
    ...(props.status && !props.status.startsWith('handoff_') ? [props.status] : [])
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
    <div class="workstation-node-filter__fields">
      <div class="workstation-node-filter__field">
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
      </div>
      <div class="workstation-node-filter__field">
        <label :for="`${idPrefix}-status`">节点状态</label>
        <ElSelect
          :id="`${idPrefix}-status`"
          placeholder="全部状态"
          :model-value="status"
          @update:model-value="emit('update:status', $event)"
        >
          <ElOption label="全部状态" value="" />
          <ElOption
            :label="
              handoffBusy || handoffError
                ? '交接需重验（尚未核对）'
                : `交接需重验（${stationNodes.filter((node) => node.handoffRevalidation === 'requires_revalidation').length}）`
            "
            value="handoff_requires_revalidation"
            :disabled="handoffBusy || !!handoffError"
          />
          <ElOption
            :label="`交接尚未确认（${stationNodes.filter((node) => node.handoffRevalidation === 'unavailable').length}）`"
            value="handoff_unavailable"
          />
          <ElOption
            v-for="value in statuses"
            :key="value"
            :label="`${value}（${stationNodes.filter((node) => node.status === value).length}）`"
            :value="value"
          />
        </ElSelect>
      </div>
    </div>
    <ul
      class="workstation-node-filter__stats"
      role="status"
      aria-live="polite"
      :aria-label="`${modelValue ? '当前工位' : '全部工位'}：${counts.review} 待审查，${counts.confirm} 待人工确认，${counts.correction} 待补正。`"
    >
      <li :class="{ 'is-review': counts.review > 0 }">
        <strong>{{ counts.review }}</strong
        >待审查
      </li>
      <li :class="{ 'is-confirm': counts.confirm > 0 }">
        <strong>{{ counts.confirm }}</strong
        >待人工确认
      </li>
      <li :class="{ 'is-correction': counts.correction > 0 }">
        <strong>{{ counts.correction }}</strong
        >待补正
      </li>
    </ul>
    <div class="workstation-node-filter__handoff">
      <p v-if="handoffBusy" role="status">正在核对交接状态……</p>
      <p v-else-if="handoffError" role="alert" class="is-error">{{ handoffError }}</p>
      <p v-else role="status">
        交接：{{
          stationNodes.filter((node) => node.handoffRevalidation === 'requires_revalidation').length
        }}
        个节点需重验，
        {{ stationNodes.filter((node) => node.handoffRevalidation === 'unavailable').length }}
        个尚未确认
      </p>
      <ElButton
        link
        type="primary"
        size="small"
        aria-label="刷新工位交接状态"
        :loading="handoffBusy"
        @click="emit('refreshHandoffs')"
        >刷新</ElButton
      >
    </div>
    <p class="workstation-node-filter__foot">
      显示 {{ visibleCount }} / {{ nodes.length }} 个节点 · 筛选列表不会切换当前节点
    </p>
  </section>
</template>
<style scoped>
/* 触屏保留 44px 可点区域（选择器多一层，压过下面桌面端的 36px） */
@media (pointer: coarse) {
  .workstation-node-filter .workstation-node-filter__field :deep(.el-select__wrapper),
  .workstation-node-filter .workstation-node-filter__handoff :deep(.el-button) {
    min-height: 44px;
  }
}

.workstation-node-filter {
  display: grid;
  padding: 12px;
  margin: 0 18px 12px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  gap: 10px;
}

.workstation-node-filter p {
  margin: 0;
  line-height: 1.5;
}

.workstation-node-filter__fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
}

.workstation-node-filter__field {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.workstation-node-filter__field label {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

.workstation-node-filter__field :deep(.el-select__wrapper) {
  min-height: 36px;
}

.workstation-node-filter__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.workstation-node-filter__stats li {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 999px;
}

.workstation-node-filter__stats strong {
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-placeholder);
}

.workstation-node-filter__stats li.is-review {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.workstation-node-filter__stats li.is-confirm {
  color: var(--el-color-warning-dark-2, #b54708);
  background: var(--el-color-warning-light-9);
}

.workstation-node-filter__stats li.is-correction {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.workstation-node-filter__stats li[class^='is-'] strong {
  color: inherit;
}

.workstation-node-filter__handoff {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  border-top: 1px dashed var(--el-border-color-lighter);
}

.workstation-node-filter__handoff .is-error {
  color: var(--el-color-danger);
}

.workstation-node-filter__foot {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
</style>
