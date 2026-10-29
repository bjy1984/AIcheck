<script setup lang="ts">
import { computed } from 'vue'
import { ElIcon, ElTag } from 'element-plus'
import { CircleCheck, CircleClose, Clock, Minus, Refresh } from '@element-plus/icons-vue'
import { getStatusTagType } from './status'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ status?: string; label?: string }>()
const type = computed(() => getStatusTagType(props.status))
const icons = {
  success: CircleCheck,
  primary: Refresh,
  warning: Clock,
  danger: CircleClose,
  info: Minus
}
</script>

<template>
  <ElTag v-bind="$attrs" :type="type" class="status-tag">
    <ElIcon class="status-tag__icon" aria-hidden="true"><component :is="icons[type]" /></ElIcon>
    <span class="status-tag__label"
      ><slot>{{ label || status || '未知' }}</slot></span
    >
  </ElTag>
</template>

<style lang="less" scoped>
.status-tag :deep(.el-tag__content) {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  min-width: 0;
}

.status-tag__icon {
  flex-shrink: 0;
  font-size: 13px;
}

.status-tag__label {
  min-width: 0;
}
</style>
