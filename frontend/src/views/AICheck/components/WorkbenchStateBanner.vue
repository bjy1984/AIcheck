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
@media (width <= 768px) {
  .state-content {
    align-items: flex-start;
    flex-direction: column;
  }
}

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

/* 按横幅自身的 type 定色，而不是靠继承 Element 的 alert 颜色。
   全局覆盖已在 styles/index.less 修到 (0,4,0) 并实测 5.93:1，这一层不再是
   兜底；留着是因为颜色应当跟着 type 语义走（error/forbidden/readonly），
   而不是跟着它恰好映射到哪种 el-alert。两处取值一致。 */
.state-banner--error .state-content,
.state-banner--error .state-message {
  color: #b42318;
}

.state-banner--forbidden .state-content,
.state-banner--forbidden .state-message {
  color: #92400e;
}

.state-banner--readonly .state-content,
.state-banner--readonly .state-message {
  color: #334155;
}

.state-content span,
.state-message {
  overflow-wrap: anywhere;
}

.state-message {
  margin-bottom: 12px;
  color: #667085;
}
</style>
