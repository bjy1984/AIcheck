<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElButton,
  ElCheckbox,
  ElDrawer,
  ElForm,
  ElFormItem,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElSwitch,
  ElTimeSelect
} from 'element-plus'

import {
  getProjectAutoReviewPolicyApi,
  getProjectAutoReviewStatusApi,
  runProjectAutoReviewApi,
  updateProjectAutoReviewPolicyApi,
  type AutoReviewPolicy,
  type AutoReviewStatus,
  type AutoReviewTriggerMode
} from '@/api/aicheck'
import { autoReviewModeLabel, autoReviewStatusSummary } from '../autoReviewPresentation'

const props = defineProps<{
  projectId: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'policy-updated', policy: AutoReviewPolicy): void
  (event: 'run-started', run: Record<string, unknown>): void
}>()

const drawerVisible = ref(false)
const loading = ref(false)
const saving = ref(false)
const running = ref(false)
let loadGeneration = 0
const policy = ref<AutoReviewPolicy>()
const status = ref<AutoReviewStatus>()
const form = reactive({
  enabled: false,
  realtime: true,
  daily: true,
  dailyTime: '02:00',
  timezone: 'Asia/Shanghai',
  debounceSeconds: 300
})

const buttonLabel = computed(() => autoReviewModeLabel(policy.value))
const statusSummary = computed(() => autoReviewStatusSummary(status.value))
const triggerModes = computed<AutoReviewTriggerMode[]>(() => [
  ...(form.realtime ? (['ocr_mounted'] as const) : []),
  ...(form.daily ? (['daily_schedule'] as const) : [])
])

const syncForm = (value: AutoReviewPolicy) => {
  form.enabled = value.enabled
  form.realtime = value.triggerModes.includes('ocr_mounted')
  form.daily = value.triggerModes.includes('daily_schedule')
  form.dailyTime = value.dailyTime || '02:00'
  form.timezone = value.timezone || 'Asia/Shanghai'
  form.debounceSeconds = value.debounceSeconds ?? 300
}

const load = async () => {
  const generation = ++loadGeneration
  const requestProjectId = props.projectId
  if (!requestProjectId) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const [policyResponse, statusResponse] = await Promise.all([
      getProjectAutoReviewPolicyApi(requestProjectId),
      getProjectAutoReviewStatusApi(requestProjectId)
    ])
    if (generation !== loadGeneration || requestProjectId !== props.projectId) return
    policy.value = policyResponse.data.policy
    status.value = statusResponse.data
    syncForm(policy.value)
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

const openDrawer = async () => {
  drawerVisible.value = true
  await load()
}

const save = async () => {
  if (!policy.value) return
  if (form.enabled && triggerModes.value.length === 0) {
    ElMessage.warning('开启自动审查时至少选择一种触发方式')
    return
  }
  saving.value = true
  try {
    const response = await updateProjectAutoReviewPolicyApi(
      props.projectId,
      {
        enabled: form.enabled,
        triggerModes: triggerModes.value,
        dailyTime: form.dailyTime,
        timezone: form.timezone,
        debounceSeconds: form.debounceSeconds
      },
      {
        etag: policy.value.etag,
        idempotencyKey: `auto-review-policy-${props.projectId}-${policy.value.revision}-${Date.now()}`
      }
    )
    policy.value = response.data.policy
    syncForm(policy.value)
    emit('policy-updated', policy.value)
    ElMessage.success('自动审查设置已保存')
    await load()
  } finally {
    saving.value = false
  }
}

const runNow = async () => {
  await ElMessageBox.confirm(
    '将审查当前工程所有已挂接资料的业务节点，结果仍需人工确认。是否继续？',
    '立即执行全工程审查',
    { type: 'warning', confirmButtonText: '开始审查', cancelButtonText: '取消' }
  )
  running.value = true
  try {
    const response = await runProjectAutoReviewApi(props.projectId, {
      idempotencyKey: `manual-project-auto-review-${props.projectId}-${Date.now()}`
    })
    emit('run-started', response.data.projectReviewRun)
    ElMessage.success('全工程审查已进入队列')
    await load()
  } finally {
    running.value = false
  }
}

watch(
  () => props.projectId,
  () => {
    policy.value = undefined
    status.value = undefined
    drawerVisible.value = false
    void load()
  },
  { immediate: true }
)
</script>

<template>
  <div class="auto-review-control">
    <ElButton
      class="auto-review-control-button"
      :type="policy?.enabled ? 'success' : 'default'"
      :loading="loading"
      :disabled="disabled || !projectId"
      :aria-label="buttonLabel"
      @click="openDrawer"
    >
      {{ buttonLabel }}
    </ElButton>

    <ElDrawer v-model="drawerVisible" title="项目自动审查设置" size="430px">
      <ElForm label-position="top">
        <ElFormItem label="自动审查">
          <ElSwitch v-model="form.enabled" active-text="已开启" inactive-text="已关闭" />
        </ElFormItem>
        <ElFormItem label="触发方式">
          <ElCheckbox v-model="form.realtime">资料 OCR 成功并挂载后实时审查</ElCheckbox>
          <ElCheckbox v-model="form.daily">每天定时扫描补漏</ElCheckbox>
        </ElFormItem>
        <ElFormItem v-if="form.daily" label="每日审查时间">
          <ElTimeSelect
            v-model="form.dailyTime"
            start="00:00"
            step="00:30"
            end="23:30"
            placeholder="选择时间"
          />
        </ElFormItem>
        <ElFormItem label="项目时区">
          <ElSelect v-model="form.timezone">
            <ElOption label="中国标准时间（Asia/Shanghai）" value="Asia/Shanghai" />
            <ElOption label="UTC" value="UTC" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="实时触发合并窗口">
          <ElInputNumber v-model="form.debounceSeconds" :min="0" :max="3600" :step="60" />
          <span class="auto-review-form-hint">秒；同一批上传可合并为一次节点审查</span>
        </ElFormItem>
      </ElForm>

      <div class="auto-review-status-card">
        <strong>当前状态</strong>
        <span>{{ statusSummary }}</span>
      </div>

      <template #footer>
        <div class="auto-review-drawer-actions">
          <ElButton :loading="running" @click="runNow">立即执行全工程审查</ElButton>
          <ElButton type="primary" :loading="saving" @click="save">保存设置</ElButton>
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped>
.auto-review-control {
  display: inline-flex;
  align-items: center;
}

.auto-review-control-button {
  white-space: nowrap;
}

.auto-review-form-hint {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.auto-review-status-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.auto-review-drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
