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

/* 这段文字继承 Element 的 .el-alert__description 颜色，错误态实测 #f56c6c
   配 #fef0f0 只有 2.61:1。全局覆盖那几条改到 (0,3,0) 仍然没压住，而这里恰恰是
   加载失败、无权访问这类最需要被看清的提示。直接按横幅自身的 type 定色：
   作用域样式必定生效，语义也跟着 type 走，不依赖 Element 的层叠细节。 */
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
