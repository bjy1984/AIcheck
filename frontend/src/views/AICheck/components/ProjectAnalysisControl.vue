<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElButton, ElDrawer, ElMessage, ElMessageBox, ElProgress } from 'element-plus'

import {
  createProjectAnalysisRunApi,
  getProjectAnalysisPreviewApi,
  getProjectAnalysisStatusApi,
  listProjectAnalysisRunsApi,
  type ProjectAnalysisPreview,
  type ProjectAnalysisRun,
  type ProjectAnalysisStatus
} from '@/api/aicheck'
import {
  projectAnalysisBannerState,
  projectAnalysisProgressView,
  projectAnalysisRequestFailure,
  type ProjectAnalysisBannerState
} from '../projectAnalysisPresentation'

const props = defineProps<{ projectId: string; disabled?: boolean }>()
const emit = defineEmits<{
  'state-change': [state: ProjectAnalysisBannerState | undefined]
}>()
const drawerVisible = ref(false)
const loading = ref(false)
const starting = ref(false)
const preview = ref<ProjectAnalysisPreview>()
const activeRun = ref<ProjectAnalysisRun>()
const status = ref<ProjectAnalysisStatus>()
const failureMessage = ref('')
let pollTimer: ReturnType<typeof setInterval> | undefined
const terminalPhases = new Set(['waiting_human_review', 'failed', 'partial_failure'])
const progress = computed(() =>
  status.value ? projectAnalysisProgressView(status.value) : undefined
)
const bannerState = computed(() => projectAnalysisBannerState(status.value, starting.value))
const isRunning = computed(() => bannerState.value?.tone === 'running')

const stopPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = undefined
}
const poll = async () => {
  if (!activeRun.value || !props.projectId) return
  try {
    const response = await getProjectAnalysisStatusApi(
      props.projectId,
      activeRun.value.projectAnalysisRunId
    )
    status.value = response.data.status
    failureMessage.value = ''
    if (terminalPhases.has(status.value.phase)) stopPolling()
  } catch (error) {
    const failure = projectAnalysisRequestFailure(error)
    failureMessage.value = failure.message
    if (failure.terminal) stopPolling()
  }
}
const startPolling = () => {
  stopPolling()
  void poll()
  pollTimer = setInterval(() => void poll(), 2000)
}
const load = async () => {
  if (!props.projectId) return
  loading.value = true
  try {
    const [previewResponse, runsResponse] = await Promise.all([
      getProjectAnalysisPreviewApi(props.projectId),
      listProjectAnalysisRunsApi(props.projectId)
    ])
    preview.value = previewResponse.data.preview
    activeRun.value = runsResponse.data.items[0]
    status.value = activeRun.value
    if (activeRun.value && !terminalPhases.has(activeRun.value.phase)) startPolling()
  } finally {
    loading.value = false
  }
}
const open = async () => {
  drawerVisible.value = true
  failureMessage.value = ''
  try {
    await load()
  } catch (error) {
    failureMessage.value = projectAnalysisRequestFailure(error).message
  }
}
const projectAnalysisIdempotencyKey = (
  projectId: string,
  preview: { snapshotHash: string; modelName?: string }
) =>
  [`project-analysis-${projectId}-${preview.snapshotHash}`, preview.modelName || '']
    .filter(Boolean)
    .join('-')

const start = async () => {
  if (!preview.value || preview.value.contextLimitExceeded || isRunning.value) return
  await ElMessageBox.confirm(
    `将把 ${preview.value.includedNodeCount} 个节点和 ${preview.value.uniqueFileCount} 份唯一 OCR 拼成一个请求，是否继续？`,
    '开始全工程一键分析',
    { type: 'warning', confirmButtonText: '开始分析', cancelButtonText: '取消' }
  )
  starting.value = true
  failureMessage.value = ''
  try {
    const response = await createProjectAnalysisRunApi(
      props.projectId,
      preview.value.snapshotHash,
      // 键里带实际模型：切换模型后同一份资料要能发起新运行。只按快照做键，
      // 服务端会原样重放切换前那次 POST 的响应，界面永远停在旧模型的结果上
      // （2026-09-02 切 DeepSeek→通义后实测）。
      { idempotencyKey: projectAnalysisIdempotencyKey(props.projectId, preview.value) }
    )
    activeRun.value = response.data.run
    status.value = response.data.run
    startPolling()
    ElMessage.success('全工程分析已启动')
  } catch (error) {
    stopPolling()
    failureMessage.value = projectAnalysisRequestFailure(error).message
  } finally {
    starting.value = false
  }
}

watch(bannerState, (value) => emit('state-change', value), { immediate: true })

watch(
  () => props.projectId,
  async (projectId) => {
    stopPolling()
    preview.value = undefined
    activeRun.value = undefined
    status.value = undefined
    failureMessage.value = ''
    drawerVisible.value = false
    if (!projectId) return
    try {
      await load()
    } catch {
      // 后台预取失败不弹抽屉错误；用户打开抽屉时会再次加载并看到可操作提示。
    }
  },
  { immediate: true }
)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="project-analysis-control">
    <ElButton type="primary" :loading="loading" :disabled="disabled || !projectId" @click="open">
      一键分析
    </ElButton>
    <ElDrawer v-model="drawerVisible" title="全工程一键分析" size="460px">
      <div v-if="preview" class="analysis-preview">
        <strong>分析范围</strong>
        <span>节点 {{ preview.includedNodeCount }}</span>
        <span>唯一文件 {{ preview.uniqueFileCount }}</span>
        <span>引用 {{ preview.fileReferenceCount }}</span>
        <span>预计 {{ preview.estimatedInputTokens.toLocaleString() }} tokens</span>
        <span>模型上限 {{ preview.maxContextTokens.toLocaleString() }}</span>
      </div>
      <div v-if="preview?.contextLimitExceeded" class="analysis-error">
        当前工程超过模型上下文上限，请使用节点级自动审查。
      </div>
      <div v-if="failureMessage" class="analysis-error">{{ failureMessage }}</div>
      <div v-if="preview && preview.includedNodeCount === 0" class="analysis-error">
        当前工程没有已挂接 OCR 资料，无法发起全量分析。
      </div>
      <div v-if="progress" class="analysis-progress">
        <ElProgress
          :percentage="progress.mode === 'determinate' ? progress.percent : 0"
          :indeterminate="progress.mode === 'indeterminate'"
          :duration="2"
        />
        <span>{{ progress.label }}</span>
        <small v-if="status?.lastHeartbeatAt">最近心跳：{{ status.lastHeartbeatAt }}</small>
      </div>
      <template #footer>
        <ElButton
          type="primary"
          :loading="starting"
          :disabled="
            !preview || preview.contextLimitExceeded || preview.includedNodeCount === 0 || isRunning
          "
          @click="start"
        >
          开始全量分析
        </ElButton>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped>
.project-analysis-control {
  display: inline-flex;
}

.analysis-preview,
.analysis-progress {
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.analysis-progress {
  margin-top: 16px;
}

.analysis-error {
  margin-top: 16px;
  color: var(--el-color-danger);
}
</style>
