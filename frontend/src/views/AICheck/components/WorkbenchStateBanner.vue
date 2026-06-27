<script setup lang="ts">
import { computed } from 'vue'
import { ElAlert, ElButton, ElEmpty } from 'element-plus'

const props = defineProps<{
  type: 'error' | 'forbidden' | 'readonly' | 'empty'
  title: string
  message?: string
  actionLabel?: string
  actionLoading?: boolean
}>()

const emit = defineEmits<{
  action: []
}>()

const alertType = computed(() => {
  if (props.type === 'error') return 'error'
  if (props.type === 'forbidden') return 'warning'
  if (props.type === 'readonly') return 'info'
  return 'info'
})
</script>

<template>
  <div class="state-banner" :class="`state-banner--${type}`">
    <ElEmpty v-if="type === 'empty'" :description="title">
      <div v-if="message" class="state-message">{{ message }}</div>
      <ElButton v-if="actionLabel" type="primary" :loading="actionLoading" @click="emit('action')">
        {{ actionLabel }}
      </ElButton>
    </ElEmpty>

    <ElAlert v-else :title="title" :type="alertType" :closable="false" show-icon>
      <template #default>
        <div class="state-content">
          <span>{{ message }}</span>
          <ElButton
            v-if="actionLabel"
            size="small"
            :loading="actionLoading"
            @click="emit('action')"
          >
            {{ actionLabel }}
          </ElButton>
        </div>
      </template>
    </ElAlert>
  </div>
</template>

<style scoped>
.state-banner {
  margin-bottom: 14px;
}

.state-content {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  line-height: 22px;
}

.state-content span,
.state-message {
  overflow-wrap: anywhere;
}

.state-message {
  margin-bottom: 12px;
  color: #667085;
}

@media (max-width: 768px) {
  .state-content {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
