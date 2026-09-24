<script setup lang="ts">
import type { InspectionWorkspaceView } from '../inspectionWorkspaceView'
defineProps<{ modelValue: InspectionWorkspaceView }>()
const emit = defineEmits<{ change: [value: InspectionWorkspaceView] }>()
const views: Array<{ value: InspectionWorkspaceView; label: string }> = [
  { value: 'ai', label: 'AI审查' },
  { value: 'important', label: '重要节点审查' },
  { value: 'list', label: '完整工作台' }
]
</script>
<template>
  <div class="view-segmented" role="tablist" aria-label="监检工作台视图">
    <button
      v-for="view in views"
      :key="view.value"
      type="button"
      role="tab"
      :aria-selected="modelValue === view.value"
      :class="['view-segment', { 'is-active': modelValue === view.value }]"
      @click="emit('change', view.value)"
      >{{ view.label }}</button
    >
  </div>
</template>
<style scoped>
.view-segmented {
  display: inline-flex;
  flex: none;
  padding: 2px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  gap: 2px;
}

.view-segment {
  display: inline-flex;
  padding: 8px 14px;
  font: inherit;
  font-size: 14px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: none;
  border-radius: 4px;
}

.view-segment:hover {
  color: var(--el-color-primary);
}

.view-segment.is-active {
  color: var(--el-color-primary);
  background: var(--el-bg-color);
  box-shadow: 0 1px 3px var(--el-border-color-light);
}
</style>
