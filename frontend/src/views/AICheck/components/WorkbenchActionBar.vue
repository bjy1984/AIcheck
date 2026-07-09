<script setup lang="ts">
import { computed } from 'vue'
import { ElButton } from 'element-plus'
import type { ActionCode, RoleCode } from '@/types/aicheck'

const props = defineProps<{
  role: RoleCode
  actions: ActionCode[]
  loading: boolean
  readOnly: boolean
  aiRecheckDisabled?: boolean
  aiRecheckDisabledReason?: string
}>()

const emit = defineEmits<{
  upload: []
  bind: []
  saveDraft: []
  submit: []
  withdraw: []
  history: []
  rectify: []
  aiRecheck: []
}>()

const actionSet = computed(() => new Set(props.actions))
const canSubmit = computed(() => ['contractor', 'ndt'].includes(props.role))
const canReview = computed(() => props.role === 'inspection')
const hasAction = (action: ActionCode) => actionSet.value.has(action)
</script>

<template>
  <div v-if="!readOnly" class="action-bar">
    <ElButton
      v-if="canSubmit && hasAction('file:upload')"
      :loading="loading"
      @click="emit('upload')"
    >
      上传资料
    </ElButton>
    <ElButton v-if="canSubmit && hasAction('file:bind')" :loading="loading" @click="emit('bind')">
      {{ role === 'contractor' ? '关联审核环节' : '挂载资料' }}
    </ElButton>
    <ElButton
      v-if="canSubmit && hasAction('submission:draft')"
      :loading="loading"
      @click="emit('saveDraft')"
    >
      保存草稿
    </ElButton>
    <ElButton
      v-if="canSubmit && hasAction('submission:submit')"
      type="primary"
      :loading="loading"
      @click="emit('submit')"
    >
      提交批次
    </ElButton>
    <ElButton
      v-if="canSubmit && hasAction('submission:withdraw')"
      plain
      :loading="loading"
      @click="emit('withdraw')"
    >
      撤回未提交
    </ElButton>
    <ElButton v-if="canSubmit" plain :loading="loading" @click="emit('history')">
      提交历史
    </ElButton>
    <ElButton
      v-if="canSubmit && hasAction('rectification:submit')"
      type="warning"
      :loading="loading"
      @click="emit('rectify')"
    >
      提交补正
    </ElButton>
    <ElButton
      v-if="canReview && hasAction('ai:recheck')"
      :disabled="aiRecheckDisabled"
      :loading="loading"
      :title="aiRecheckDisabled ? aiRecheckDisabledReason : '发起正式 AI 复核'"
      @click="emit('aiRecheck')"
    >
      AI 复核
    </ElButton>
  </div>
</template>

<style scoped>
.action-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
