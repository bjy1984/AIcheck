<script setup lang="ts">
import { computed } from 'vue'
import { ElTag } from 'element-plus'

export type AuditStatusTone = 'blue' | 'green' | 'orange' | 'red' | 'gray'

const props = withDefaults(
  defineProps<{
    tone?: AuditStatusTone
    size?: 'large' | 'default' | 'small'
    effect?: 'dark' | 'light' | 'plain'
    round?: boolean
  }>(),
  {
    tone: 'blue',
    size: 'small',
    effect: 'light',
    round: false
  }
)

const tagType = computed(() => {
  const typeMap = {
    blue: 'primary',
    green: 'success',
    orange: 'warning',
    red: 'danger',
    gray: 'info'
  } as const
  return typeMap[props.tone]
})
</script>

<template>
  <ElTag
    class="audit-status-tag"
    :type="tagType"
    :size="size"
    :effect="effect"
    :round="round"
    disable-transitions
  >
    <slot></slot>
  </ElTag>
</template>

<style scoped>
.audit-status-tag {
  max-width: 100%;
  font-weight: 600;
  vertical-align: middle;
}

.audit-status-tag :deep(.el-tag__content) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
