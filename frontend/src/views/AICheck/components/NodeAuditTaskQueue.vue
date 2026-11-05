<script setup lang="ts">
/**
 * 顶栏「审计任务」：每个节点最近一次 AI 复核走到哪了（2026-11-05 用户：
 * 「现在没法知道节点审计的任务状态」，要能看到进度、点了跳到节点继续）。
 *
 * 复核是排队一个个跑的（生产一个槽位，每个节点 5–13 分钟），发起之后要等很久。
 * 这里分三段：进行中（审查中、排队中，排队的写明前面还有几个）→ 要你处理（等你补充、
 * 失败、出了结果还没确认）→ 已处理（默认收起）。点一行直接进那个节点：要确认的落在
 * 人工结论，其余落在 AI 审查。
 *
 * 轮询：有任务在排或在跑、或抽屉开着时 15 秒一次，否则 60 秒一次；页面切到后台不发。
 * 有节点从「进行中」变成别的状态时发 settled，工作台据此刷新总览，并弹一条提示。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDrawer,
  ElEmpty,
  ElIcon,
  ElNotification,
  ElSkeleton,
  ElTag
} from 'element-plus'
import { ArrowRight, Refresh } from '@element-plus/icons-vue'
import { getNodeAuditTasksApi } from '@/api/aicheck'
import type { NodeAuditTask, NodeAuditTasksPayload } from '@/api/aicheck/nodeAuditTasks'
import {
  describeTask,
  groupTasks,
  queueBadge,
  settledSince,
  type TaskTone
} from './nodeAuditTaskPresentation'

const props = defineProps<{ projectId: string; disabled?: boolean }>()
const emit = defineEmits<{
  open: [nodeId: number, auditItem: 'ai_review' | 'human_review']
  settled: [tasks: NodeAuditTask[]]
}>()

const ACTIVE_POLL_MS = 15_000
const IDLE_POLL_MS = 60_000

const visible = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const payload = ref<NodeAuditTasksPayload | null>(null)
const settledOpen = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let requestSeq = 0
// 卸载时正在等响应的那一轮，回来后不能再排下一轮，否则卸载后还在后台一直轮询
let disposed = false

const sections = computed(() =>
  groupTasks(payload.value).map((section) => ({
    ...section,
    rows: section.tasks.map((task) => ({ task, view: describeTask(task) }))
  }))
)
const badge = computed(() => queueBadge(payload.value))
const summaryLine = computed(() => {
  const counts = payload.value?.counts
  if (!counts) return ''
  const attention = sections.value.find((section) => section.key === 'attention')?.rows.length
  return (
    [
      counts.running && `${counts.running} 个审查中`,
      counts.queued && `${counts.queued} 个排队`,
      attention && `${attention} 个要你处理`
    ]
      .filter(Boolean)
      .join(' · ') || '没有进行中的任务'
  )
})
const buttonAria = computed(() => {
  if (!badge.value) return '节点审计任务'
  return badge.value.tone === 'active'
    ? `节点审计任务，${badge.value.count} 个进行中`
    : `节点审计任务，${badge.value.count} 个要你处理`
})
const dataTime = computed(() => String(payload.value?.dataAsOf || '').slice(11, 19))
const hiddenSettled = computed(() =>
  Math.max(0, (payload.value?.settledTotal || 0) - (payload.value?.settledShown || 0))
)
const tagType = (tone: TaskTone) => tone
const toggleSection = (key: string) => {
  if (key === 'settled') settledOpen.value = !settledOpen.value
}

const notifyFinished = (tasks: NodeAuditTask[]) => {
  if (visible.value) return
  const failed = tasks.some((task) => task.state === 'failed')
  const first = tasks[0]
  ElNotification({
    type: failed ? 'warning' : 'success',
    title:
      tasks.length === 1
        ? `节点 ${first.nodeId} 审查${failed ? '没有完成' : '完成'}`
        : `${tasks.length} 个节点审查结束`,
    message:
      tasks.length === 1
        ? `${first.nodeName}：${describeTask(first).line}`
        : tasks
            .slice(0, 4)
            .map((task) => `${task.nodeId} ${task.nodeName}`)
            .join('、') +
          (tasks.length > 4 ? ' 等' : '') +
          '。点这里查看。',
    duration: 8000,
    onClick: () => {
      visible.value = true
    }
  })
}

// 同一项目同一时刻只发一个请求：轮询、打开抽屉、切回页面、发起复核可能挤在一起
let inFlight: { projectId: string; promise: Promise<void> } | null = null
let lastLoadedAt = 0

const load = (): Promise<void> => {
  const projectId = props.projectId
  if (!projectId) return Promise.resolve()
  if (inFlight?.projectId === projectId) return inFlight.promise
  const promise = fetchTasks(projectId).finally(() => {
    if (inFlight?.promise === promise) inFlight = null
  })
  inFlight = { projectId, promise }
  return promise
}

const fetchTasks = async (projectId: string) => {
  const seq = ++requestSeq
  loading.value = true
  try {
    const res = await getNodeAuditTasksApi(projectId)
    lastLoadedAt = Date.now()
    if (seq !== requestSeq || projectId !== props.projectId || !res?.data) return
    const finished = settledSince(payload.value, res.data)
    payload.value = res.data
    errorMessage.value = ''
    if (finished.length) {
      emit('settled', finished)
      notifyFinished(finished)
    }
  } catch {
    if (seq === requestSeq) errorMessage.value = '任务状态暂时取不到，稍后会自动重试。'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

const schedule = () => {
  clearTimeout(timer)
  if (disposed || !props.projectId) return
  const fast = visible.value || Boolean(payload.value?.active)
  timer = setTimeout(
    async () => {
      if (!document.hidden) await load()
      schedule()
    },
    fast ? ACTIVE_POLL_MS : IDLE_POLL_MS
  )
}

const refresh = async () => {
  await load()
  schedule()
}

const openTask = (task: NodeAuditTask, auditItem: 'ai_review' | 'human_review') => {
  visible.value = false
  emit('open', task.nodeId, auditItem)
}

// 切回页面时补一轮；窗口来回切换会连发好几次，5 秒内刚取过就不再取
const onVisibilityChange = () => {
  if (!document.hidden && props.projectId && Date.now() - lastLoadedAt > 5000) void refresh()
}

watch(
  () => props.projectId,
  () => {
    requestSeq += 1
    inFlight = null
    payload.value = null
    errorMessage.value = ''
    settledOpen.value = false
    loading.value = false
    void refresh()
  },
  { immediate: true }
)
watch(visible, (open) => {
  if (open) void refresh()
})
onMounted(() => document.addEventListener('visibilitychange', onVisibilityChange))
onBeforeUnmount(() => {
  disposed = true
  requestSeq += 1
  clearTimeout(timer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

/** 工作台发起复核后调一下，不用等下一轮轮询。 */
defineExpose({ refresh })
</script>

<template>
  <div class="audit-queue">
    <ElButton
      class="audit-queue-button"
      :disabled="disabled || !projectId"
      :aria-label="buttonAria"
      @click="visible = true"
    >
      <span v-if="badge?.tone === 'active'" class="audit-queue-pulse" aria-hidden="true"></span>
      审计任务
      <span v-if="badge" :class="['audit-queue-count', `is-${badge.tone}`]" aria-hidden="true">{{
        badge.count
      }}</span>
    </ElButton>

    <ElDrawer v-model="visible" size="460px" class="audit-queue-drawer">
      <template #header>
        <div class="audit-queue-head">
          <span class="audit-queue-title">
            <strong>节点审计任务</strong>
            <small>每个节点最近一次审查{{ summaryLine ? ` · ${summaryLine}` : '' }}</small>
          </span>
          <!-- 刷新放在标题行：抽屉右下角会被「AI审查」悬浮按钮挡住 -->
          <ElButton size="small" text :loading="loading" :icon="Refresh" @click="refresh"
            >刷新</ElButton
          >
        </div>
      </template>

      <ElAlert
        v-if="errorMessage"
        class="audit-queue-alert"
        type="warning"
        :closable="false"
        show-icon
        :title="errorMessage"
      />
      <ElSkeleton v-if="!payload && loading" :rows="6" animated />
      <ElEmpty
        v-else-if="payload && !payload.items.length"
        :image-size="64"
        description="这个项目还没有发起过节点审计"
      >
        <p class="audit-queue-empty-hint">
          在节点页点「开始审核」，或用顶栏的「一键分析」「自动审查」发起；发起后在这里看进度。
        </p>
      </ElEmpty>
      <template v-else-if="payload">
        <section
          v-for="section in sections"
          :key="section.key"
          :class="['audit-queue-section', `is-${section.key}`]"
        >
          <component
            :is="section.key === 'settled' ? 'button' : 'h4'"
            :type="section.key === 'settled' ? 'button' : undefined"
            :class="['audit-queue-section-title', { 'is-toggle': section.key === 'settled' }]"
            :aria-expanded="section.key === 'settled' ? settledOpen : undefined"
            @click="toggleSection(section.key)"
          >
            {{ section.title }}
            <span class="audit-queue-section-count">{{ section.rows.length }}</span>
            <ElIcon
              v-if="section.key === 'settled'"
              :class="['audit-queue-chevron', { 'is-open': settledOpen }]"
              aria-hidden="true"
              ><ArrowRight
            /></ElIcon>
          </component>
          <ul v-if="section.key !== 'settled' || settledOpen" class="audit-queue-list">
            <li v-for="{ task, view } in section.rows" :key="task.nodeId">
              <button
                type="button"
                :class="['audit-queue-row', `is-${task.state}`]"
                :aria-label="`节点 ${task.nodeId} ${task.nodeName}：${view.badge}，${view.line}。${view.action}`"
                @click="openTask(task, view.auditItem)"
              >
                <span class="audit-queue-node">{{ task.nodeId }}</span>
                <span class="audit-queue-main">
                  <span class="audit-queue-name">{{ task.nodeName }}</span>
                  <small class="audit-queue-line">{{ view.line }}</small>
                </span>
                <span class="audit-queue-end">
                  <ElTag size="small" effect="plain" :type="tagType(view.tone)">{{
                    view.badge
                  }}</ElTag>
                  <span class="audit-queue-action"
                    >{{ view.action }}<ElIcon aria-hidden="true"><ArrowRight /></ElIcon
                  ></span>
                </span>
                <span v-if="task.state === 'running'" class="audit-queue-meter" aria-hidden="true"
                  ><i></i
                ></span>
              </button>
            </li>
          </ul>
          <p
            v-if="section.key === 'settled' && settledOpen && hiddenSettled"
            class="audit-queue-more"
          >
            只列出最近 {{ payload.settledShown }} 个，另有 {{ hiddenSettled }} 个更早的。
          </p>
        </section>
      </template>

      <template #footer>
        <div class="audit-queue-foot">
          <small
            >{{ dataTime ? `更新于 ${dataTime}` : '' }}
            {{ payload?.active ? '· 每 15 秒自动刷新' : '' }}</small
          >
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped>
@keyframes audit-queue-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.35;
    transform: scale(0.75);
  }
}

@keyframes audit-queue-flow {
  from {
    transform: translateX(-100%);
  }

  to {
    transform: translateX(340%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .audit-queue-pulse,
  .audit-queue-meter i {
    animation: none;
  }

  .audit-queue-meter i {
    width: 100%;
    opacity: 0.4;
  }
}

.audit-queue {
  display: inline-flex;
  align-items: center;
}

.audit-queue-button {
  gap: 6px;
  white-space: nowrap;
}

.audit-queue-count {
  display: inline-flex;
  height: 20px;
  min-width: 20px;
  padding: 0 6px;
  margin-left: 6px;
  font-size: 12px;
  font-weight: 600;
  line-height: 20px;
  border-radius: 999px;
  justify-content: center;
}

.audit-queue-count.is-active {
  color: #fff;
  background: var(--aicheck-primary);
}

.audit-queue-count.is-attention {
  color: var(--aicheck-warning);
  background: var(--aicheck-warning-bg);
  box-shadow: inset 0 0 0 1px var(--aicheck-warning-border);
}

/* 有任务在跑：按钮前一个会呼吸的小点，不用点开就知道「还在跑」 */
.audit-queue-pulse {
  width: 8px;
  height: 8px;
  margin-right: 6px;
  background: var(--aicheck-primary);
  border-radius: 50%;
  animation: audit-queue-pulse 1.6s ease-in-out infinite;
}

.audit-queue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.audit-queue-title {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.audit-queue-head strong {
  font-size: 16px;
  color: var(--aicheck-text-strong);
}

.audit-queue-head small,
.audit-queue-foot small,
.audit-queue-more {
  font-size: 12px;
  color: var(--aicheck-text-subtle);
}

.audit-queue-alert {
  margin-bottom: 12px;
}

.audit-queue-empty-hint {
  max-width: 300px;
  margin: 0 auto;
  font-size: 13px;
  line-height: 20px;
  color: var(--aicheck-text-muted);
}

.audit-queue-section + .audit-queue-section {
  margin-top: 18px;
}

.audit-queue-section-title {
  display: flex;
  width: 100%;
  padding: 0 2px;
  margin: 0 0 8px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--aicheck-text-muted);
  text-align: left;
  background: none;
  border: none;
  align-items: center;
  gap: 6px;
}

.audit-queue-section-title.is-toggle {
  cursor: pointer;
}

.audit-queue-section-title.is-toggle:hover {
  color: var(--aicheck-primary);
}

.audit-queue-section.is-attention .audit-queue-section-title {
  color: var(--aicheck-warning);
}

.audit-queue-section-count {
  font-weight: 500;
  color: var(--aicheck-text-subtle);
}

.audit-queue-chevron {
  margin-left: auto;
  transition: transform 0.2s ease;
}

.audit-queue-chevron.is-open {
  transform: rotate(90deg);
}

.audit-queue-list {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 6px;
}

.audit-queue-row {
  position: relative;
  display: grid;
  width: 100%;
  padding: 10px 12px;
  overflow: hidden;
  font: inherit;
  color: var(--aicheck-text);
  text-align: left;
  cursor: pointer;
  background: var(--aicheck-surface);
  border: 1px solid var(--aicheck-border-soft);
  border-radius: 8px;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease;
}

.audit-queue-row:hover {
  background: var(--aicheck-hover-bg);
  border-color: var(--aicheck-border-strong);
}

.audit-queue-row:focus-visible {
  outline: none;
  box-shadow: var(--aicheck-focus-ring);
}

.audit-queue-row.is-failed {
  border-color: var(--aicheck-danger-border);
}

.audit-queue-row.is-needs_input {
  border-color: var(--aicheck-warning-border);
}

.audit-queue-node {
  font-size: 13px;
  font-weight: 600;
  color: var(--aicheck-text-subtle);
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.audit-queue-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.audit-queue-name {
  overflow: hidden;
  font-size: 14px;
  color: var(--aicheck-text-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-queue-line {
  display: -webkit-box;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-subtle);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.audit-queue-row.is-failed .audit-queue-line {
  color: var(--aicheck-danger);
}

.audit-queue-end {
  display: grid;
  justify-items: end;
  gap: 4px;
}

.audit-queue-action {
  display: inline-flex;
  font-size: 12px;
  color: var(--aicheck-primary);
  white-space: nowrap;
  align-items: center;
  gap: 2px;
}

/* 审查中的行底部一条细的流动条：说明「在动」，不假装知道百分比 */
.audit-queue-meter {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  overflow: hidden;
  background: var(--el-color-primary-light-9);
}

.audit-queue-meter i {
  position: absolute;
  inset: 0 auto 0 0;
  width: 30%;
  background: var(--aicheck-primary);
  border-radius: 2px;
  animation: audit-queue-flow 1.8s ease-in-out infinite;
}

.audit-queue-more {
  margin: 8px 2px 0;
}

.audit-queue-foot {
  display: flex;
  align-items: center;
}
</style>

<style>
/* 抽屉本体由 ElDrawer 渲染，scoped 样式够不着；手机上不超过屏宽 */
.audit-queue-drawer.el-drawer {
  max-width: 100vw;
}
</style>
