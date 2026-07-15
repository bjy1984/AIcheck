<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDrawer,
  ElEmpty,
  ElMessage,
  ElMessageBox,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSkeleton,
  ElTag
} from 'element-plus'
import { useRouter } from 'vue-router'
import { cancelKnowledgeTaskApi, listOperationTasksApi, retryKnowledgeTaskApi } from '@/api/aicheck'
import type { OperationArea, OperationTask } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const props = defineProps<{
  area?: OperationArea
  projectId?: string
}>()

const router = useRouter()
const visible = ref(false)
const loading = ref(false)
const actionLoading = ref('')
const errorMessage = ref('')
const statusFilter = ref('all')
const tasks = ref<OperationTask[]>([])
const total = ref(0)
let refreshTimer: ReturnType<typeof setInterval> | undefined

const areaLabels: Record<OperationArea, string> = {
  admin: '系统管理',
  knowledge: '知识库',
  fde: 'AI 工程治理',
  workbench: '业务审查'
}

const taskTypeLabels: Record<string, string> = {
  knowledge: '知识处理',
  ocr_or_index: 'OCR / 索引',
  review_run: 'AI 复核',
  ocr: 'OCR 抽取',
  ocr_pipeline: '准确率优先 OCR',
  export: '导出任务'
}

const formatElapsed = (seconds?: number | null) => {
  if (seconds == null) return '--'
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${minutes} 分 ${remainder} 秒`
}

const formatCost = (value?: number | null) => `¥${Number(value || 0).toFixed(4)}`

const taskStatusCode = (task: OperationTask) => task.statusCode || 'unknown'

const filteredTasks = computed(() => {
  if (statusFilter.value === 'running') {
    return tasks.value.filter((task) =>
      ['queued', 'running', 'retrying', 'waiting_human', 'cancel_requested'].includes(
        taskStatusCode(task)
      )
    )
  }
  if (statusFilter.value === 'failed') {
    return tasks.value.filter((task) => ['failed', 'blocked'].includes(taskStatusCode(task)))
  }
  if (statusFilter.value === 'completed') {
    return tasks.value.filter((task) =>
      ['succeeded', 'cancelled', 'partial'].includes(taskStatusCode(task))
    )
  }
  return tasks.value
})

const latestDataTime = computed(() => {
  const values = tasks.value
    .map((task) => task.updatedAt || task.createdAt || '')
    .filter(Boolean)
    .sort()
  return values.length ? values[values.length - 1] : '--'
})

const statusType = (task: OperationTask) => {
  if (['failed', 'blocked'].includes(taskStatusCode(task))) return 'danger'
  if (['succeeded', 'cancelled'].includes(taskStatusCode(task))) return 'success'
  if (['queued', 'running', 'retrying', 'cancel_requested'].includes(taskStatusCode(task))) {
    return 'warning'
  }
  return 'info'
}

const loadTasks = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await listOperationTasksApi({
      area: props.area,
      projectId: props.projectId,
      pageSize: 100
    })
    tasks.value = response?.data?.items || []
    total.value = Number(response?.data?.total || 0)
  } catch (error) {
    tasks.value = []
    total.value = 0
    errorMessage.value = getAicheckErrorMessage(error, '任务状态加载失败，请重试。')
  } finally {
    loading.value = false
  }
}

const open = async () => {
  visible.value = true
  await loadTasks()
}

const taskRoute = (task: OperationTask) => {
  if (task.route) return task.route
  if (task.area === 'knowledge') return `/knowledge/tasks?taskId=${task.id}`
  if (task.area === 'fde' && task.taskType === 'ocr') return `/fde/ocr-quality?jobId=${task.id}`
  if (task.area === 'fde') return `/fde/review-runs?reviewRunId=${task.id}`
  if (task.area === 'admin') return '/admin/audit'
  if (task.area === 'workbench' && task.projectId) {
    return `/workbench/${router.currentRoute.value.params.role || 'inspection'}?projectId=${task.projectId}`
  }
  return ''
}

const openTask = async (task: OperationTask) => {
  const route = taskRoute(task)
  if (!route) return
  visible.value = false
  await router.push(route)
}

const handleKnowledgeAction = async (task: OperationTask, action: 'retry' | 'cancel') => {
  if (task.area !== 'knowledge') return
  if (action === 'cancel') {
    await ElMessageBox.confirm(`确认取消任务“${task.targetLabel}”吗？`, '取消任务', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '返回'
    })
  }
  actionLoading.value = `${task.id}-${action}`
  try {
    if (action === 'retry') await retryKnowledgeTaskApi(task.id, { reason: '从统一任务中心重试。' })
    else await cancelKnowledgeTaskApi(task.id, { reason: '从统一任务中心取消。' })
    ElMessage.success(action === 'retry' ? '已重新提交任务' : '任务已取消')
    await loadTasks()
  } catch (error) {
    ElMessage.error(
      getAicheckErrorMessage(error, action === 'retry' ? '任务重试失败' : '任务取消失败')
    )
  } finally {
    actionLoading.value = ''
  }
}

defineExpose({ open, loadTasks })

watch(visible, (isOpen) => {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = isOpen ? setInterval(loadTasks, 5000) : undefined
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <ElDrawer
    v-model="visible"
    class="operation-task-drawer"
    title="任务中心"
    size="min(680px, 100vw)"
    append-to-body
    destroy-on-close
  >
    <div class="task-toolbar">
      <div>
        <strong>显示 {{ filteredTasks.length }} / {{ total }} 项任务</strong>
        <span>数据截至 {{ latestDataTime }}</span>
      </div>
      <ElButton :loading="loading" @click="loadTasks">刷新</ElButton>
    </div>
    <ElRadioGroup v-model="statusFilter" class="task-filters" aria-label="任务状态筛选">
      <ElRadioButton value="all">全部</ElRadioButton>
      <ElRadioButton value="running">执行中</ElRadioButton>
      <ElRadioButton value="failed">失败</ElRadioButton>
      <ElRadioButton value="completed">已完成</ElRadioButton>
    </ElRadioGroup>

    <ElAlert
      v-if="errorMessage"
      class="task-error"
      type="error"
      :title="errorMessage"
      :closable="false"
      show-icon
    >
      <ElButton size="small" type="danger" plain @click="loadTasks">重试</ElButton>
    </ElAlert>
    <ElSkeleton v-else-if="loading" class="task-loading" animated :rows="8" />
    <ElEmpty v-else-if="!filteredTasks.length" description="当前范围没有任务" />
    <div v-else class="task-list">
      <article v-for="task in filteredTasks" :key="`${task.area}-${task.id}`" class="task-row">
        <div class="task-row-head">
          <div>
            <strong :title="task.targetLabel">{{ task.targetLabel }}</strong>
            <span
              >{{ taskTypeLabels[task.taskType] || task.taskType }} ·
              {{ areaLabels[task.area] }}</span
            >
          </div>
          <ElTag :type="statusType(task)" effect="light">{{ task.status }}</ElTag>
        </div>
        <ElProgress
          v-if="
            ['queued', 'running', 'retrying', 'cancel_requested'].includes(taskStatusCode(task)) ||
            task.progress > 0
          "
          :percentage="Math.max(0, Math.min(100, task.progress || 0))"
          :status="statusType(task) === 'danger' ? 'exception' : undefined"
        />
        <dl class="task-meta">
          <div
            ><dt>任务 ID</dt><dd>{{ task.id }}</dd></div
          >
          <div
            ><dt>Operation ID</dt><dd>{{ task.operationId || '--' }}</dd></div
          >
          <div
            ><dt>更新时间</dt><dd>{{ task.updatedAt || task.createdAt || '--' }}</dd></div
          >
          <div v-if="task.stageLabel || task.stage"
            ><dt>当前阶段</dt><dd>{{ task.stageLabel || task.stage }}</dd></div
          >
          <div v-if="task.queuePosition"
            ><dt>排队位置</dt><dd>第 {{ task.queuePosition }} 位</dd></div
          >
          <div
            ><dt>已用时间</dt><dd>{{ formatElapsed(task.elapsedSeconds) }}</dd></div
          >
          <div v-if="task.attempt"
            ><dt>执行次数</dt><dd>{{ task.attempt }}</dd></div
          >
          <div v-if="task.pageProgress?.total"
            ><dt>页面进度</dt
            ><dd>{{ task.pageProgress.completed || 0 }} / {{ task.pageProgress.total }}</dd></div
          >
          <div v-if="task.provider || task.model"
            ><dt>识别服务</dt><dd>{{ task.provider || '--' }} · {{ task.model || '--' }}</dd></div
          >
          <div v-if="task.callCount"
            ><dt>调用次数</dt><dd>{{ task.callCount }}</dd></div
          >
          <div v-if="task.costCny != null"
            ><dt>累计费用</dt><dd>{{ formatCost(task.costCny) }}</dd></div
          >
          <div v-if="task.lastHeartbeatAt"
            ><dt>最近心跳</dt><dd>{{ task.lastHeartbeatAt }}</dd></div
          >
        </dl>
        <p v-if="task.providerWaitReason" class="task-provider-wait" role="status">
          正在等待识别服务：{{ task.providerWaitReason }}
        </p>
        <p v-if="task.errorSummary" class="task-failure">{{ task.errorSummary }}</p>
        <div v-if="task.blockingReasons?.length" class="task-blockers" role="status">
          <strong>阻断原因</strong>
          <ul>
            <li
              v-for="(reason, index) in task.blockingReasons"
              :key="`${task.id}-blocker-${index}`"
            >
              {{ reason.message || reason.code || '需要人工复核' }}
            </li>
          </ul>
        </div>
        <p v-if="task.recommendedAction" class="task-recommendation">
          建议：{{ task.recommendedAction }}
        </p>
        <div class="task-actions">
          <ElButton v-if="taskRoute(task)" text type="primary" @click="openTask(task)"
            >查看详情</ElButton
          >
          <ElButton
            v-if="task.actions.includes('retry') && task.area === 'knowledge'"
            text
            type="primary"
            :loading="actionLoading === `${task.id}-retry`"
            @click="handleKnowledgeAction(task, 'retry')"
            >重试</ElButton
          >
          <ElButton
            v-if="task.actions.includes('cancel') && task.area === 'knowledge'"
            text
            type="danger"
            :loading="actionLoading === `${task.id}-cancel`"
            @click="handleKnowledgeAction(task, 'cancel')"
            >取消</ElButton
          >
        </div>
      </article>
    </div>
  </ElDrawer>
</template>

<style scoped>
.task-toolbar,
.task-row-head,
.task-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-toolbar {
  padding-bottom: 12px;
  border-bottom: 1px solid #dfe7f1;
}

.task-toolbar > div,
.task-row-head > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.task-toolbar strong,
.task-row-head strong {
  font-size: 14px;
  font-weight: 600;
  color: #172033;
}

.task-toolbar span,
.task-row-head span {
  font-size: 12px;
  color: #52647d;
}

.task-provider-wait {
  padding: 8px 10px;
  margin: 10px 0 0;
  color: #8a4b00;
  background: #fff7e6;
  border-left: 3px solid #8a4b00;
}

.task-filters {
  margin: 14px 0;
}

.task-error {
  display: flex;
  margin-top: 12px;
}

.task-error :deep(.el-alert__content) {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.task-loading {
  padding: 20px 4px;
}

.task-list {
  display: grid;
  gap: 10px;
}

.task-row {
  display: grid;
  padding: 14px;
  background: #fff;
  border: 1px solid #d4deeb;
  border-radius: 6px;
  gap: 12px;
}

.task-row-head strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  gap: 8px;
}

.task-meta div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.task-meta dt {
  font-size: 12px;
  color: #6e7d92;
}

.task-meta dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font:
    500 12px/1.5 ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  color: #304158;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-failure {
  padding: 8px 10px;
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #b42318;
  background: #fef3f2;
  border-left: 3px solid #d92d20;
}

.task-blockers,
.task-recommendation {
  padding: 8px 10px;
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
}

.task-blockers {
  color: #8a4b00;
  background: #fff7e6;
  border-left: 3px solid #d97706;
}

.task-blockers ul {
  padding-left: 18px;
  margin: 4px 0 0;
}

.task-recommendation {
  color: #26364e;
  background: #f4f7fb;
}

.task-actions {
  justify-content: flex-end;
}

@media (width <= 640px) {
  .task-meta {
    grid-template-columns: 1fr;
  }

  .task-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
