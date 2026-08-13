<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElEmpty,
  ElIcon,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSkeleton,
  ElTag
} from 'element-plus'
import {
  ArrowLeft,
  ChatDotRound,
  CircleCheck,
  Document,
  Files,
  MagicStick,
  Promotion,
  Refresh,
  Search,
  View
} from '@element-plus/icons-vue'
import {
  confirmNodeEvidenceLinkApi,
  getProjectTreeApi,
  listWorkbenchProjectsApi,
  requestAiRecheckApi,
  submitReviewHumanInputResponseApi
} from '@/api/aicheck'
import type {
  ProjectTreePayload,
  ReviewHumanInputResponsePayload,
  ReviewHumanInputTask,
  R12LicenseCandidate,
  R19EvidenceCandidate
} from '@/api/aicheck'
import {
  createReviewBSessionApi,
  getReviewBAuditViewApi,
  getReviewBWorkspaceApi,
  listReviewBEventsApi,
  listReviewBMessagesApi,
  streamReviewBEventsApi,
  runReviewBSessionActionApi,
  sendReviewBMessageApi,
  submitReviewBHumanDecisionApi
} from '@/api/aiReviewB'
import type {
  ReviewBAuditView,
  ReviewBBasisItem,
  ReviewBContentBlock,
  ReviewBEvent,
  ReviewBMessage,
  ReviewBReference,
  ReviewBWorkspace
} from '@/types/ai-review-b'
import type { EvidenceLink, ExtractedField, Project, ProjectTreeNode } from '@/types/aicheck'
import { useUserStore } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import EvidenceLocatorDialog from '@/views/AICheck/components/EvidenceLocatorDialog.vue'
import ProjectNodeTree from '@/views/AICheck/components/ProjectNodeTree.vue'
import R12RegistryVerificationDialog from '@/views/AICheck/components/R12RegistryVerificationDialog.vue'
import R19SemanticEvidenceDialog from '@/views/AICheck/components/R19SemanticEvidenceDialog.vue'
import ReviewMarkdownText from '@/views/AIReviewB/components/ReviewMarkdownText.vue'
import { resolveReviewWorkbenchContext } from '@/views/AIReviewB/embeddedReviewWorkbench'
import { formatReviewTokenUsage } from '@/views/AIReviewB/tokenUsage'

const props = withDefaults(
  defineProps<{
    embedded?: boolean
    projectId?: string
    nodeId?: number
  }>(),
  {
    embedded: false,
    projectId: '',
    nodeId: 0
  }
)

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const projects = ref<Project[]>([])
const treeGroups = ref<ProjectTreePayload['groups']>([])
const activeProjectId = ref('')
const activeNodeId = ref(0)
const workspace = ref<ReviewBWorkspace>()
const messages = ref<ReviewBMessage[]>([])
const events = ref<ReviewBEvent[]>([])
const auditView = ref<ReviewBAuditView>()
const loading = ref(false)
const nodeLoading = ref(false)
const sending = ref(false)
const cancelling = ref(false)
const actionLoading = ref(false)
const reviewStarting = ref(false)
const polling = ref(false)
const pageError = ref('')
const composer = ref('')
const timelineRef = ref<HTMLElement>()
const tracePanels = ref<string[]>([])
const activityExpanded = ref(false)
const executionStarted = ref(false)
const evidenceDialogVisible = ref(false)
const evidencePreview = ref<EvidenceLink>()
const r12DialogVisible = ref(false)
const r19DialogVisible = ref(false)
const humanTaskSubmitting = ref(false)
const humanDecision = ref<'accept' | 'edit' | 'reject'>('accept')
const humanComment = ref('')
const extractedFields = ref<ExtractedField[]>([])
let pollTimer: number | undefined
let liveTraceTimer: number | undefined
let liveTraceAbort: AbortController | undefined

const TIMELINE_BOTTOM_THRESHOLD = 80

const allNodes = computed(() => treeGroups.value.flatMap((group) => group.nodes))
const currentNode = computed(() => workspace.value?.node)
const session = computed(() => workspace.value?.session)
const activeRun = computed(() => workspace.value?.activeReviewRun)
const activeRunId = computed(() =>
  String(activeRun.value?.reviewRunId || activeRun.value?.id || '')
)
const readiness = computed(() => workspace.value?.evidenceReadiness)
const activeTask = computed(
  () => (workspace.value?.activeHumanInputTask || null) as ReviewHumanInputTask | null
)
const selectedEvidenceIds = computed(() => new Set(session.value?.selectedEvidenceLinkIds || []))
const selectedEvidence = computed(() =>
  (workspace.value?.evidenceLinks || []).filter((item) => selectedEvidenceIds.value.has(item.id))
)
const executionEvents = computed(() =>
  events.value.filter((event) => event.eventType !== 'session.created')
)
const latestExecutionEvents = computed(() => executionEvents.value.slice(-8).reverse())
const liveAgentTrace = computed(() => {
  const agentEvents = executionEvents.value.filter((event) =>
    String(event.eventType || '').startsWith('agent.')
  )
  return agentEvents.slice(-12)
})
const liveAgentTraceLatest = computed(() => liveAgentTrace.value.at(-1))
const displayUser = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '监检人员'
)
const businessBasis = computed(
  () => (workspace.value?.businessBasis || {}) as Record<string, unknown>
)
const conversationSubtitle = computed(() => {
  const subtitle = String(
    businessBasis.value.ruleName || businessBasis.value.inspectionItem || ''
  ).trim()
  return subtitle && subtitle !== String(currentNode.value?.name || '').trim() ? subtitle : ''
})
const currentTask = computed(
  () => workspace.value?.contextSummary.currentTask || currentNode.value?.name || '选择监检节点'
)
const canStartReview = computed(() => workspace.value?.permissions.canStartReview === true)
const canSubmitHumanDecision = computed(
  () => workspace.value?.permissions.canSubmitHumanDecision === true
)
const runStatus = computed(() => String(activeRun.value?.status || '未发起'))
const runStatusTone = computed(() => {
  if (['accepted_by_human', 'edited_by_human', 'completed', '完成'].includes(runStatus.value))
    return 'success'
  if (['failed', 'cancelled', 'rejected_by_human', '失败'].includes(runStatus.value))
    return 'danger'
  if (['waiting_human_input', 'waiting_human_review'].includes(runStatus.value)) return 'warning'
  if (['queued', 'running', 'resuming', '推理中'].includes(runStatus.value)) return 'primary'
  return 'info'
})
const conversationStarted = computed(
  () => executionStarted.value || messages.value.some((message) => message.role === 'user')
)
const latestAssistantExecution = computed(
  () =>
    [...messages.value]
      .reverse()
      .find((message) => message.role === 'assistant' && message.execution)?.execution
)
const executionActive = computed(
  () =>
    sending.value ||
    reviewStarting.value ||
    (conversationStarted.value &&
      ['queued', 'running', 'resuming', '推理中'].includes(runStatus.value))
)
const showExecutionActivity = computed(() => executionActive.value || conversationStarted.value)
const executionSummary = computed(() => {
  if (sending.value) {
    const latest = liveAgentTraceLatest.value
    if (latest?.title) return latest.title
    return '正在理解问题并核查当前节点上下文…'
  }
  if (reviewStarting.value) return '正在启动 AI 复核流程…'
  const execution = latestAssistantExecution.value
  if (execution?.mode === 'llm_agent') {
    const model = [execution.provider, execution.model].filter(Boolean).join(' / ') || '真实模型'
    return execution.toolCallCount
      ? `${model}，已调用 ${execution.toolCallCount} 个工具`
      : `${model} 已完成回答`
  }
  if (execution?.mode === 'deterministic_command') return '本地受控命令已完成，未调用模型'
  if (execution?.mode === 'deterministic_fallback') return '模型链路未完成，已返回确定性上下文摘要'
  if (messages.value.at(-1)?.role === 'assistant') return 'AI 复核助手已完成本次回复'
  return latestExecutionEvents.value[0]?.title || '本次处理已完成'
})
const executionStatusLabel = computed(() => {
  if (executionActive.value) return '执行中'
  if (['waiting_human_input', 'waiting_human_review'].includes(runStatus.value))
    return '等待人工处理'
  if (['failed', 'cancelled', 'rejected_by_human', '失败'].includes(runStatus.value))
    return '执行异常'
  if (latestAssistantExecution.value?.mode === 'llm_agent') return 'Agent 已完成'
  if (latestAssistantExecution.value?.mode === 'deterministic_fallback') return '已降级'
  if (latestAssistantExecution.value?.mode === 'deterministic_command') return '本地完成'
  return '已完成'
})
const graphNodes = computed(() => auditView.value?.graph.nodes || [])
const runProgress = computed(() => {
  const nodes = graphNodes.value
  if (!nodes.length) return null
  const completed = nodes.filter((node) =>
    ['succeeded', 'skipped', 'failed'].includes(String(node.status || ''))
  ).length
  return Math.round((completed / nodes.length) * 100)
})
const startReviewMode = computed<'formal' | 'gap_precheck'>(() =>
  readiness.value?.readyForAiFormal ? 'formal' : 'gap_precheck'
)
const taskType = computed(() => String(activeTask.value?.taskType || ''))
const canRenderActiveTask = computed(() =>
  ['official_registry_license_verification', 'r19_semantic_evidence_confirmation'].includes(
    taskType.value
  )
)
const selectedEvidenceSummary = computed(() =>
  selectedEvidence.value.length
    ? `已选择 ${selectedEvidence.value.length} 份文件资料`
    : '尚未选择文件资料'
)

const humanizeStandardCode = (basis: ReviewBBasisItem) => {
  const raw = String(basis.standardCode || basis.standardRef || basis.standardName || '').trim()
  const internal = raw.replace(/^STD-/, '')
  const announcement = internal.match(/^SAMR-(\d{4})-(\d+)$/)
  if (announcement) return `市场监管总局公告 ${announcement[1]} 年第 ${announcement[2]} 号`
  const normalizedAnnouncement = raw.match(/^市场监管总局公告\s*(\d{4})\s*年\s*第\s*(\d+)\s*号$/)
  if (normalizedAnnouncement) {
    return `市场监管总局公告 ${normalizedAnnouncement[1]} 年第 ${normalizedAnnouncement[2]} 号`
  }
  if (basis.standardCode) return raw
  return internal
    .replace(/^TSG-D/, 'TSG D')
    .replace(/^TSG-/, 'TSG ')
    .replace(/^GBT-/, 'GB/T ')
    .replace(/^NBT-/, 'NB/T ')
    .replace(/^JBT-/, 'JB/T ')
    .replace(/^SYT-/, 'SY/T ')
    .replace(/^GB-/, 'GB ')
    .replace(/-(\d{4})$/, '—$1')
}

const humanizeClause = (value?: string) => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const clause = raw.replace(/(\d)-(?=\d)/g, '$1～')
  if (/^附件\s*\d/.test(clause)) {
    return clause.split('：')[0].replace(/^附件\s*(\d+)/, '附件 $1')
  }
  if (/^(附件|附录|表|第)/.test(clause)) return clause
  return `第 ${clause} 条`
}

const basisDisplayLabel = (basis: ReviewBBasisItem) =>
  [humanizeStandardCode(basis), humanizeClause(basis.clauseNo)].filter(Boolean).join(' ') ||
  String(basis.sourceLocatorId || basis.clauseId || '标准条款')

const basisReferenceAliases = (basis: ReviewBBasisItem) => {
  const standardRef = String(basis.standardRef || basis.standardName || '').trim()
  const standardCode = String(basis.standardCode || '').trim()
  const clauseNo = String(basis.clauseNo || '').trim()
  const fileStem = String(basis.fileName || '').replace(/\.[^.]+$/, '')
  const humanCode = humanizeStandardCode(basis)
  const humanClause = humanizeClause(clauseNo)
  return Array.from(
    new Set(
      [
        basis.sourceLocatorId,
        basis.clauseId,
        standardRef,
        standardCode,
        humanCode,
        basisDisplayLabel(basis),
        standardRef && clauseNo ? `${standardRef} ${clauseNo}` : '',
        standardCode && clauseNo ? `${standardCode} ${clauseNo}` : '',
        humanCode && clauseNo ? `${humanCode} ${clauseNo}` : '',
        humanCode && humanClause ? `${humanCode} ${humanClause}` : '',
        standardRef.replace(/^STD-/, ''),
        standardRef.replace(/^STD-/, '').replaceAll('-', ' '),
        fileStem
      ].filter((item): item is string => Boolean(item))
    )
  )
}

const basisToReference = (basis: ReviewBBasisItem): ReviewBReference => {
  const referenceId = String(basis.sourceLocatorId || basis.clauseId || '')
  return {
    kind: 'basis',
    referenceId,
    label: basisDisplayLabel(basis),
    aliases: basisReferenceAliases(basis),
    basis
  }
}

const evidenceToReference = (evidence: EvidenceLink): ReviewBReference => ({
  kind: 'evidence',
  referenceId: evidence.id,
  label: evidence.fileName || evidence.fieldName || evidence.id,
  aliases: [evidence.id, evidence.fileName, evidence.fieldName].filter((item): item is string =>
    Boolean(item)
  ),
  evidence
})

const visibleEvidenceFacts = (evidence: EvidenceLink) =>
  (evidence.evidenceFacts || []).filter((fact) => fact.formalEvidenceEligible && fact.quotedText)

const workspaceMessageReferences = computed<ReviewBReference[]>(() => [
  ...(workspace.value?.basisSnapshot || [])
    .filter((basis) => basis.sourceLocatorId || basis.clauseId)
    .map(basisToReference),
  ...(workspace.value?.evidenceLinks || [])
    .filter((evidence) => evidence.id)
    .map(evidenceToReference)
])

const blockReferences = (block: ReviewBContentBlock) => {
  const structured = (block as { references?: ReviewBReference[] }).references || []
  const references = new Map<string, ReviewBReference>()
  for (const reference of [...workspaceMessageReferences.value, ...structured]) {
    if (!reference.referenceId) continue
    if (reference.kind === 'basis') {
      const basis =
        reference.basis ||
        (workspace.value?.basisSnapshot || []).find(
          (item) => String(item.sourceLocatorId || item.clauseId) === String(reference.referenceId)
        )
      references.set(
        `${reference.kind}:${reference.referenceId}`,
        basis ? basisToReference(basis) : reference
      )
      continue
    }
    references.set(`${reference.kind}:${reference.referenceId}`, reference)
  }
  return [...references.values()]
}

const messageExecutionLabel = (message: ReviewBMessage) => {
  const execution = message.execution
  if (!execution || message.role !== 'assistant') return ''
  if (execution.mode === 'llm_agent') {
    const model = [execution.provider, execution.model].filter(Boolean).join(' / ') || '真实模型'
    const tools = execution.toolCallCount ? ` · ${execution.toolCallCount} 次工具调用` : ''
    return `${model} · Agent${tools}`
  }
  if (execution.mode === 'deterministic_command') return '本地受控命令 · 未调用模型'
  if (execution.mode === 'deterministic_fallback') return '确定性降级 · 模型回答未完成'
  return execution.modelCalled ? '模型调用已完成' : '未调用模型'
}

const messageTokenUsageLabel = (message: ReviewBMessage) => {
  if (message.role !== 'assistant') return ''
  return formatReviewTokenUsage(message.execution?.usage)
}

const mergeMessages = (incoming: ReviewBMessage[]) => {
  const byId = new Map(messages.value.map((item) => [item.id, item]))
  for (const item of incoming) byId.set(item.id, item)
  messages.value = [...byId.values()].sort((left, right) => left.sequence - right.sequence)
}

const mergeEvents = (incoming: ReviewBEvent[]) => {
  const byId = new Map(events.value.map((item) => [item.eventId, item]))
  for (const item of incoming) byId.set(item.eventId, item)
  events.value = [...byId.values()].sort((left, right) => left.sequence - right.sequence)
}

const isTimelineNearBottom = () => {
  const timeline = timelineRef.value
  if (!timeline) return true
  return (
    timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight <= TIMELINE_BOTTOM_THRESHOLD
  )
}

const scrollTimelineToEnd = async (force = false) => {
  if (!force && !isTimelineNearBottom()) return
  await nextTick()
  if (timelineRef.value) timelineRef.value.scrollTop = timelineRef.value.scrollHeight
}

const updateRouteQuery = async () => {
  if (props.embedded) return
  await router.replace({
    path: '/ai-review-b',
    query: {
      projectId: activeProjectId.value,
      nodeId: String(activeNodeId.value),
      ...(activeRunId.value ? { reviewRunId: activeRunId.value } : {})
    }
  })
}

const loadAuditView = async () => {
  if (!activeRunId.value) {
    auditView.value = undefined
    return
  }
  try {
    auditView.value = (await getReviewBAuditViewApi(activeRunId.value)).data
  } catch {
    auditView.value = undefined
  }
}

const loadSessionData = async (reset = false) => {
  if (!session.value?.id) return
  const sessionId = session.value.id
  if (reset) {
    messages.value = []
    events.value = []
  }
  const [messageRes, eventRes] = await Promise.all([
    listReviewBMessagesApi(sessionId, reset ? 0 : messages.value.at(-1)?.sequence || 0),
    // 执行事件会合并会话事件与 ReviewRun 事件；始终取完整快照，避免并发事件重排造成游标漏读。
    listReviewBEventsApi(sessionId, 0)
  ])
  // 在响应返回后再判断，避免用户恰好在轮询请求期间向上滚动时被带回底部。
  const shouldFollowLatest = reset || isTimelineNearBottom()
  mergeMessages(messageRes.data.messages)
  mergeEvents(eventRes.data.events)
  if (shouldFollowLatest) await scrollTimelineToEnd(true)
}

const pollLiveAgentTrace = async () => {
  if (!session.value?.id) return
  try {
    const eventRes = await listReviewBEventsApi(session.value.id, 0)
    mergeEvents(eventRes.data.events)
  } catch {
    // 发送中的旁路轮询失败不影响主请求。
  }
}

// SSE 断开后的降级轮询间隔。原为 400ms，恰好与后端 0.4s 的重载节流同频——
// 多用户同时在线时会反复触发 Postgres 全集合重载（F-4）。这条路径只是 SSE
// 不可用时的兜底，1.5s 足以让执行动态看起来是连续的。
const LIVE_TRACE_FALLBACK_POLL_INTERVAL_MS = 1500

const startLivePolling = () => {
  if (liveTraceTimer) return
  void pollLiveAgentTrace()
  liveTraceTimer = window.setInterval(
    () => void pollLiveAgentTrace(),
    LIVE_TRACE_FALLBACK_POLL_INTERVAL_MS
  )
}

const startLiveAgentTrace = () => {
  stopLiveAgentTrace()
  activityExpanded.value = true
  const sessionId = session.value?.id
  if (!sessionId) return
  // 优先走 SSE 增量推送；连接失败或中途断开时降级为快速轮询。
  liveTraceAbort = new AbortController()
  const abort = liveTraceAbort
  streamReviewBEventsApi(
    sessionId,
    events.value.at(-1)?.sequence || 0,
    (event) => mergeEvents([event]),
    abort.signal
  ).catch(() => {
    if (!abort.signal.aborted) startLivePolling()
  })
}

const stopLiveAgentTrace = () => {
  if (liveTraceAbort) {
    liveTraceAbort.abort()
    liveTraceAbort = undefined
  }
  if (liveTraceTimer) {
    window.clearInterval(liveTraceTimer)
    liveTraceTimer = undefined
  }
}

const ensureSession = async () => {
  if (workspace.value?.session || !activeProjectId.value || !activeNodeId.value) return
  await createReviewBSessionApi(
    activeProjectId.value,
    activeNodeId.value,
    {
      currentTask: workspace.value?.businessBasis?.inspectionItem as string | undefined,
      reviewRunId: String(route.query.reviewRunId || '') || undefined
    },
    { idempotencyKey: `review-session-${activeProjectId.value}-${activeNodeId.value}` }
  )
  workspace.value = (
    await getReviewBWorkspaceApi(
      activeProjectId.value,
      activeNodeId.value,
      String(route.query.reviewRunId || '') || undefined
    )
  ).data
}

const loadNodeWorkspace = async (reset = true) => {
  if (!activeProjectId.value || !activeNodeId.value) return
  nodeLoading.value = true
  pageError.value = ''
  if (reset) {
    workspace.value = undefined
    auditView.value = undefined
    humanComment.value = ''
  }
  try {
    workspace.value = (
      await getReviewBWorkspaceApi(
        activeProjectId.value,
        activeNodeId.value,
        String(route.query.reviewRunId || '') || undefined
      )
    ).data
    await ensureSession()
    await Promise.all([loadSessionData(reset), loadAuditView()])
    if (reset) await updateRouteQuery()
  } catch (error) {
    pageError.value = getAicheckErrorMessage(error, 'AI 复核工作区加载失败，请稍后重试。')
  } finally {
    nodeLoading.value = false
  }
}

const loadProjectTree = async (preferredNodeId?: number) => {
  if (!activeProjectId.value) return
  const tree = (await getProjectTreeApi(activeProjectId.value)).data
  treeGroups.value = tree.groups
  const availableIds = new Set(allNodes.value.map((node) => node.nodeId))
  const candidate =
    (preferredNodeId && availableIds.has(preferredNodeId) && preferredNodeId) ||
    (tree.project.currentNodeId && availableIds.has(tree.project.currentNodeId)
      ? tree.project.currentNodeId
      : allNodes.value[0]?.nodeId)
  activeNodeId.value = Number(candidate || 0)
  if (activeNodeId.value) await loadNodeWorkspace(true)
}

const loadPage = async () => {
  loading.value = true
  pageError.value = ''
  try {
    projects.value = (await listWorkbenchProjectsApi('inspection')).data
    const requestedProjectId = String(route.query.projectId || '')
    activeProjectId.value =
      projects.value.find((project) => project.id === requestedProjectId)?.id ||
      projects.value[0]?.id ||
      ''
    await loadProjectTree(Number(route.query.nodeId || 0) || undefined)
  } catch (error) {
    pageError.value = getAicheckErrorMessage(error, 'AI 复核工作台初始化失败。')
  } finally {
    loading.value = false
  }
}

const loadEmbeddedContext = async () => {
  const context = resolveReviewWorkbenchContext(props)
  if (context.source !== 'embedded') return
  if (
    context.projectId === activeProjectId.value &&
    context.nodeId === activeNodeId.value &&
    workspace.value
  ) {
    return
  }
  stopLiveAgentTrace()
  activeProjectId.value = context.projectId
  activeNodeId.value = context.nodeId
  messages.value = []
  events.value = []
  executionStarted.value = false
  activityExpanded.value = false
  await loadNodeWorkspace(true)
}

const refreshLiveState = async () => {
  if (polling.value || !activeProjectId.value || !activeNodeId.value) return
  polling.value = true
  try {
    const previousRunId = activeRunId.value
    workspace.value = (
      await getReviewBWorkspaceApi(
        activeProjectId.value,
        activeNodeId.value,
        previousRunId || undefined
      )
    ).data
    await ensureSession()
    await Promise.all([loadSessionData(false), loadAuditView()])
    pageError.value = ''
  } catch {
    // 保留最后一次成功快照；下一次刷新成功后会清除旧错误提示。
  } finally {
    polling.value = false
  }
}

const handleProjectChange = async () => {
  messages.value = []
  events.value = []
  executionStarted.value = false
  activityExpanded.value = false
  await loadProjectTree()
}

const handleNodeSelect = async (node: ProjectTreeNode) => {
  if (node.nodeId === activeNodeId.value) return
  activeNodeId.value = node.nodeId
  messages.value = []
  events.value = []
  executionStarted.value = false
  activityExpanded.value = false
  await loadNodeWorkspace(true)
}

const handleBackToWorkbench = () => {
  void router.push({
    path: '/workbench/inspection',
    query: { projectId: activeProjectId.value, nodeId: String(activeNodeId.value) }
  })
}

const handleOpenFileLibrary = () => {
  void router.push({
    path: '/workbench/inspection',
    query: {
      projectId: activeProjectId.value,
      nodeId: String(activeNodeId.value),
      openFileLibrary: '1'
    }
  })
}

const handleStartReview = async () => {
  if (!canStartReview.value) {
    ElMessage.warning('当前节点尚不具备可执行的正式复核或缺项预审条件。')
    return
  }
  const modeLabel = startReviewMode.value === 'formal' ? '正式 AI 复核' : '缺项预审'
  await ElMessageBox.confirm(
    `将按当前文件版本、规则版本和适用标准条款包发起${modeLabel}，是否继续？`,
    `发起${modeLabel}`,
    { type: 'warning', confirmButtonText: '确认发起', cancelButtonText: '取消' }
  )
  actionLoading.value = true
  reviewStarting.value = true
  executionStarted.value = true
  activityExpanded.value = true
  try {
    const res = await requestAiRecheckApi(
      activeProjectId.value,
      activeNodeId.value,
      { reviewMode: startReviewMode.value },
      {
        idempotencyKey: `review-b-start-${activeProjectId.value}-${activeNodeId.value}-${Date.now()}`
      }
    )
    const reviewRunId = String(
      res.data.dispatch?.reviewRunId || res.data.latestRun?.reviewRunId || ''
    )
    if (session.value?.id && reviewRunId) {
      await runReviewBSessionActionApi(
        session.value.id,
        'set_active_review_run',
        { reviewRunId },
        {
          etag: session.value.etag,
          idempotencyKey: `review-b-link-${session.value.id}-${reviewRunId}`
        }
      ).catch(() => undefined)
    }
    ElMessage.success(`${modeLabel}已发起`)
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, `${modeLabel}发起失败。`))
  } finally {
    actionLoading.value = false
    reviewStarting.value = false
    activityExpanded.value = false
  }
}

/**
 * 后台执行期间，把 agent.message.delta / agent.reasoning.delta 事件渐进渲染进占位消息。
 * 串流片段（payload.streamed=true）按序原样拼接（不加分隔符）；推理流与正文分区展示。
 */
const applyStreamingDeltas = (messageId: string) => {
  const placeholder = messages.value.find((item) => item.id === messageId)
  if (!placeholder || placeholder.status !== 'running') return
  const executionId = placeholder.execution?.executionId
  if (!executionId) return
  let reasoning = ''
  let content = ''
  for (const event of [...events.value].sort((a, b) => a.sequence - b.sequence)) {
    if (event.eventType !== 'agent.message.delta' && event.eventType !== 'agent.reasoning.delta') {
      continue
    }
    const payload = (event.payload || {}) as {
      executionId?: string
      content?: string
      streamed?: boolean
    }
    if (payload.executionId !== executionId) continue
    const piece = String(payload.content || '')
    if (!piece) continue
    if (event.eventType === 'agent.reasoning.delta') reasoning += piece
    else content += piece
  }
  if (!reasoning && !content) return
  const parts: string[] = []
  if (reasoning) parts.push(`〔推理〕${reasoning.trim()}`)
  if (content) parts.push(content.trim())
  placeholder.contentBlocks = [{ type: 'text', text: `${parts.join('\n\n')}\n\n——正在继续核查…` }]
}

/** 后台执行模式下等待占位 assistant 消息终态；完成消息会重新分配 sequence，因此始终取全量快照。 */
const waitForAssistantCompletion = async (sessionId: string, messageId: string) => {
  const deadline = Date.now() + 6 * 60 * 1000
  for (;;) {
    const current = messages.value.find((item) => item.id === messageId)
    if (current && current.status && current.status !== 'running') return
    if (Date.now() > deadline) {
      ElMessage.warning('AI 回答仍在执行中，可稍后回到本会话查看结果。')
      return
    }
    await new Promise((resolve) => window.setTimeout(resolve, 800))
    if (session.value?.id !== sessionId) return
    try {
      const res = await listReviewBMessagesApi(sessionId, 0)
      mergeMessages(res.data.messages)
      applyStreamingDeltas(messageId)
      await scrollTimelineToEnd()
    } catch {
      // 等待期间的轮询失败不终止等待，下一轮继续重试。
    }
  }
}

const sendMessage = async (preset?: string) => {
  const text = (preset || composer.value).trim()
  if (!text || !session.value?.id || sending.value) return
  const sessionId = session.value.id
  sending.value = true
  executionStarted.value = true
  activityExpanded.value = true
  startLiveAgentTrace()
  try {
    const res = await sendReviewBMessageApi(sessionId, text, {
      etag: session.value.etag
    })
    mergeMessages([res.data.userMessage, res.data.assistantMessage])
    if (!preset) composer.value = ''
    workspace.value = workspace.value
      ? { ...workspace.value, session: res.data.session }
      : undefined
    await scrollTimelineToEnd(true)
    if (res.data.status === 'accepted' || res.data.assistantMessage?.status === 'running') {
      // 后台执行：请求已受理，等待 Agent 执行完成或被停止。
      await waitForAssistantCompletion(sessionId, res.data.assistantMessage.id)
    }
    await Promise.all([loadSessionData(false), refreshLiveState()])
    await scrollTimelineToEnd(true)
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, 'AI 辅助消息发送失败。'))
  } finally {
    stopLiveAgentTrace()
    sending.value = false
    activityExpanded.value = false
  }
}

const stopCurrentAnswer = async () => {
  if (!session.value?.id || cancelling.value) return
  cancelling.value = true
  try {
    await runReviewBSessionActionApi(session.value.id, 'cancel_execution', {})
    ElMessage.info('已请求停止当前回答，正在等待 Agent 停止…')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '停止请求发送失败。'))
  } finally {
    cancelling.value = false
  }
}

const handleSuggestion = (actionKey: string, message?: ReviewBMessage) => {
  if (actionKey === 'search_evidence') return sendMessage('/检索证据')
  if (actionKey === 'explain_basis') return sendMessage('/标准条款')
  if (actionKey === 'draft_opinion') return sendMessage('/草拟意见')
  if (actionKey === 'copy_opinion_draft') {
    const textBlock = message?.contentBlocks.find((block) => block.type === 'text')
    humanComment.value = textBlock && 'text' in textBlock ? String(textBlock.text || '') : ''
    ElMessage.success('草稿已填入右侧人工意见')
  }
}

const openEvidence = (evidence: EvidenceLink) => {
  evidencePreview.value = evidence
  evidenceDialogVisible.value = true
}

const openMessageReference = (reference: ReviewBReference) => {
  if (reference.kind === 'evidence') {
    const evidence = (workspace.value?.evidenceLinks || []).find(
      (item) => item.id === reference.referenceId
    )
    if (evidence || reference.evidence)
      openEvidence(evidence || (reference.evidence as EvidenceLink))
    return
  }
  const basis =
    (workspace.value?.basisSnapshot || []).find(
      (item) =>
        item.sourceLocatorId === reference.referenceId || item.clauseId === reference.referenceId
    ) || reference.basis
  if (!basis) return
  const previewPage = Number(
    basis.sourcePage || basis.startPage || basis.previewUrl?.match(/#page=(\d+)/)?.[1] || 0
  )
  openEvidence({
    id: `BASIS-${reference.referenceId}`,
    projectId: activeProjectId.value,
    nodeId: activeNodeId.value,
    objectType: 'knowledgeClause',
    objectId: reference.referenceId,
    documentVersionId: basis.documentVersionId,
    fileName: basis.fileName,
    pageNo: previewPage || undefined,
    quotedText: [basis.standardRef || basis.standardName, basis.clauseNo, basis.summary]
      .filter(Boolean)
      .join(' · '),
    previewAvailable: basis.previewAvailable,
    previewUrl: basis.previewUrl,
    sourceLocatorId: basis.sourceLocatorId,
    sourceRelativePath: basis.sourceRelativePath,
    standardRef: basis.standardRef || basis.standardName,
    clauseNo: basis.clauseNo
  })
}

const toggleEvidenceSelection = async (evidence: EvidenceLink) => {
  if (!session.value?.id) return
  actionLoading.value = true
  const selected = selectedEvidenceIds.value.has(evidence.id)
  try {
    const res = await runReviewBSessionActionApi(
      session.value.id,
      selected ? 'remove_evidence' : 'select_evidence',
      { evidenceLinkId: evidence.id },
      { etag: session.value.etag }
    )
    if (workspace.value) workspace.value = { ...workspace.value, session: res.data.session }
    ElMessage.success(selected ? '已移出当前上下文' : '已加入当前上下文')
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '文件资料工作集更新失败。'))
  } finally {
    actionLoading.value = false
  }
}

const confirmEvidence = async (evidence: EvidenceLink) => {
  if (evidence.manualStatus === 'confirmed') return
  actionLoading.value = true
  try {
    await confirmNodeEvidenceLinkApi(activeProjectId.value, activeNodeId.value, evidence.id, {
      comment: '在 AI 复核 B 版工作台确认'
    })
    ElMessage.success('证据已确认')
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '证据确认失败。'))
  } finally {
    actionLoading.value = false
  }
}

const openActiveHumanTask = () => {
  if (taskType.value === 'official_registry_license_verification') {
    r12DialogVisible.value = true
  } else if (taskType.value === 'r19_semantic_evidence_confirmation') {
    r19DialogVisible.value = true
  } else {
    ElMessage.warning('当前人工任务尚未注册 B 版表单，请在原监检工作台处理。')
  }
}

const submitHumanTask = async (payload: ReviewHumanInputResponsePayload) => {
  if (!activeTask.value || !activeRunId.value) return
  humanTaskSubmitting.value = true
  try {
    await submitReviewHumanInputResponseApi(activeRunId.value, activeTask.value.taskId, payload, {
      etag: activeRun.value?.etag,
      idempotencyKey: `review-b-human-${activeTask.value.taskId}-${activeTask.value.inputHash}`
    })
    r12DialogVisible.value = false
    r19DialogVisible.value = false
    ElMessage.success('人工输入已提交，AI 复核将从暂停位置恢复')
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '人工输入提交失败。'))
  } finally {
    humanTaskSubmitting.value = false
  }
}

const locateR12Candidate = (candidate: R12LicenseCandidate) => {
  const matched = (workspace.value?.evidenceLinks || []).find(
    (item) =>
      item.documentVersionId === candidate.documentVersionId &&
      Number(item.pageNo || 0) === Number(candidate.pageNo || 0)
  )
  openEvidence(
    matched || {
      id: `R12-${candidate.candidateId}`,
      projectId: activeProjectId.value,
      nodeId: activeNodeId.value,
      objectType: 'documentVersion',
      objectId: candidate.documentVersionId,
      documentId: candidate.documentId,
      documentVersionId: candidate.documentVersionId,
      fileName: candidate.fileName,
      pageNo: candidate.pageNo,
      quotedText: candidate.evidence?.quotedText,
      confidence: candidate.evidence?.confidence
    }
  )
}

const locateR19Evidence = (candidate: R19EvidenceCandidate) => {
  const matched = (workspace.value?.evidenceLinks || []).find(
    (item) =>
      item.documentVersionId === candidate.documentVersionId &&
      Number(item.pageNo || 0) === Number(candidate.pageNo || 0)
  )
  openEvidence(
    matched || {
      id: candidate.evidenceRefId,
      projectId: activeProjectId.value,
      nodeId: activeNodeId.value,
      objectType: 'documentVersion',
      objectId: candidate.documentVersionId,
      documentVersionId: candidate.documentVersionId,
      fileName: candidate.fileName,
      pageNo: candidate.pageNo,
      quotedText: candidate.quotedText,
      confidence: candidate.confidence
    }
  )
}

const handleSubmitHumanDecision = async () => {
  if (!activeRunId.value || !canSubmitHumanDecision.value) return
  if (!humanComment.value.trim()) {
    ElMessage.warning('请填写人工复核意见')
    return
  }
  const findingDrafts = activeRun.value?.findingDrafts || []
  if (humanDecision.value === 'edit' && !findingDrafts.length) {
    ElMessage.warning('当前运行没有可修改的 AI Finding，请选择采纳或驳回。')
    return
  }
  await ElMessageBox.confirm('人工结论提交后将结束本次 ReviewRun，是否继续？', '保存人工复核结论', {
    type: 'warning',
    confirmButtonText: '确认提交',
    cancelButtonText: '取消'
  })
  actionLoading.value = true
  try {
    const correctedOutput =
      humanDecision.value === 'edit'
        ? findingDrafts.map((draft) => ({
            ...draft,
            sourceDraftId: String(draft.id || ''),
            description: humanComment.value.trim()
          }))
        : undefined
    await submitReviewBHumanDecisionApi(
      activeRunId.value,
      {
        decision: humanDecision.value,
        comment: humanComment.value.trim(),
        correctedOutput,
        evidenceLinkIds: selectedEvidence.value
          .filter((item) => item.manualStatus === 'confirmed')
          .map((item) => item.id)
      },
      {
        etag: activeRun.value?.etag,
        idempotencyKey: `review-b-decision-${activeRunId.value}-${humanDecision.value}`
      }
    )
    ElMessage.success('人工复核结论已提交')
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '人工复核结论提交失败。'))
  } finally {
    actionLoading.value = false
  }
}

const blockItems = <T,>(block: ReviewBContentBlock): T[] =>
  Array.isArray((block as { items?: T[] }).items) ? ((block as { items?: T[] }).items as T[]) : []

const blockText = (block: ReviewBContentBlock) =>
  typeof (block as { text?: unknown }).text === 'string'
    ? String((block as { text: string }).text)
    : ''

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const legacyBasisLabels = (basis: ReviewBBasisItem) => {
  const standardRef = String(basis.standardRef || '').replace(/^STD-/, '')
  const standardCode = String(basis.standardCode || '').trim()
  const humanCode = humanizeStandardCode(basis)
  const clauseNo = String(basis.clauseNo || '').trim()
  const shortClause = clauseNo.split('：')[0]
  const codes = [
    standardCode,
    standardCode.replaceAll('—', '-'),
    humanCode,
    humanCode.replaceAll('—', '-'),
    standardRef,
    standardRef.replace(/^TSG-D/, 'TSG D').replace(/^TSG-/, 'TSG ')
  ]
  const clauses = [
    clauseNo,
    clauseNo.replaceAll('、', '/'),
    shortClause,
    shortClause.replaceAll('、', '/')
  ]
  return Array.from(
    new Set(
      codes.flatMap((code) => clauses.map((clause) => `${code} ${clause}`.trim())).filter(Boolean)
    )
  ).sort((left, right) => right.length - left.length)
}

const blockDisplayText = (block: ReviewBContentBlock) => {
  const citations: string[] = []
  let content = blockText(block).replace(/\[[^\]]+\]\((?:basis|evidence):[^)]+\)/g, (citation) => {
    const marker = `@@REVIEW_CITATION_${citations.length}@@`
    citations.push(citation)
    return marker
  })
  content = content.replace(/固定依据条款/g, '适用标准条款').replace(/固定条款/g, '适用标准条款')
  for (const reference of blockReferences(block)) {
    if (reference.kind !== 'basis' || !reference.basis) continue
    const marker = `\`?${escapeRegExp(reference.referenceId)}\`?`
    const displayLabel = reference.label
    for (const label of legacyBasisLabels(reference.basis)) {
      const legacyLabel = escapeRegExp(label)
      content = content.replace(
        new RegExp(`${marker}\\s*[（(]\\s*${legacyLabel}\\s*[）)]`, 'gi'),
        displayLabel
      )
      content = content.replace(new RegExp(`${marker}\\s+${legacyLabel}`, 'gi'), displayLabel)
    }
    content = content.replace(new RegExp(marker, 'gi'), displayLabel)
  }
  return content.replace(/@@REVIEW_CITATION_(\d+)@@/g, (_, index) => citations[Number(index)] || '')
}

const blockActions = (block: ReviewBContentBlock) =>
  Array.isArray((block as { actions?: Array<{ actionKey: string; label: string }> }).actions)
    ? (block as { actions?: Array<{ actionKey: string; label: string }> }).actions || []
    : []

const formatTime = (value?: string) => {
  if (!value) return ''
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date)
}

onMounted(async () => {
  const context = resolveReviewWorkbenchContext(props)
  if (context.source === 'standalone') await loadPage()
  else await loadEmbeddedContext()
  pollTimer = window.setInterval(() => void refreshLiveState(), 3000)
})

watch(
  () => [props.embedded, props.projectId, props.nodeId] as const,
  () => {
    if (props.embedded) void loadEmbeddedContext()
  }
)

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  stopLiveAgentTrace()
})
</script>

<template>
  <div :class="['review-b-shell', { 'is-embedded': props.embedded }]">
    <header v-if="!props.embedded" class="review-b-topbar">
      <div class="brand">
        <span class="brand-mark">AI</span>
        <div>
          <strong>AI 工程监检复核工作台</strong>
        </div>
      </div>
      <ElSelect
        v-model="activeProjectId"
        class="project-switcher"
        :disabled="loading || !projects.length"
        @change="handleProjectChange"
      >
        <ElOption
          v-for="project in projects"
          :key="project.id"
          :label="project.name"
          :value="project.id"
        />
      </ElSelect>
      <div class="topbar-spacer"></div>
      <ElButton :icon="Refresh" :loading="polling" @click="refreshLiveState">刷新状态</ElButton>
      <ElButton :icon="Files" @click="handleOpenFileLibrary">文件库</ElButton>
      <ElButton type="primary" :icon="ArrowLeft" @click="handleBackToWorkbench">审查列表</ElButton>
      <div class="review-user"><span></span>{{ displayUser }}</div>
    </header>

    <ElAlert
      v-if="pageError"
      class="page-alert"
      type="error"
      :title="pageError"
      :closable="false"
      show-icon
    />

    <div class="review-b-layout" v-loading="loading">
      <aside v-if="!props.embedded" class="node-sidebar">
        <div class="sidebar-heading">
          <span>监检节点</span>
          <ElTag type="info" effect="plain">{{ allNodes.length }}</ElTag>
        </div>
        <ProjectNodeTree
          :groups="treeGroups"
          :active-node-id="activeNodeId"
          :show-overview="false"
          empty-description="暂无可复核节点"
          @select="handleNodeSelect"
        />
        <div class="sidebar-links">
          <button type="button" class="is-active"
            ><ElIcon><ChatDotRound /></ElIcon>当前对话</button
          >
          <button type="button" @click="tracePanels = ['trace']"
            ><ElIcon><Document /></ElIcon>执行记录</button
          >
        </div>
      </aside>

      <main class="conversation-column" v-loading="nodeLoading">
        <section class="conversation-head">
          <div>
            <h1>{{ currentNode?.nodeId || '-' }}. {{ currentNode?.name || '请选择节点' }}</h1>
            <p v-if="conversationSubtitle">{{ conversationSubtitle }}</p>
          </div>
          <div class="run-meta">
            <ElButton :icon="View" :disabled="!activeRunId" @click="tracePanels = ['trace']"
              >查看执行轨迹</ElButton
            >
          </div>
        </section>

        <section class="context-chips">
          <span class="primary-chip">当前问题：{{ currentTask }}</span>
          <span>文件资料 {{ selectedEvidence.length }}</span>
          <span>已确认 {{ workspace?.contextSummary.confirmedEvidenceCount || 0 }}</span>
          <span :class="{ warning: workspace?.contextSummary.processTodoCount }">
            过程待办 {{ workspace?.contextSummary.processTodoCount || 0 }}
          </span>
          <span :class="{ warning: workspace?.contextSummary.finalReviewTodoCount }">
            最终复核 {{ workspace?.contextSummary.finalReviewTodoCount || 0 }}
          </span>
        </section>

        <section ref="timelineRef" class="conversation-timeline">
          <ElSkeleton v-if="nodeLoading && !workspace" :rows="8" animated />
          <template v-else>
            <article v-if="!messages.length" class="welcome-card">
              <div>
                <strong>AI 复核助手已就绪</strong>
                <p>
                  已加载当前节点的固定规则、资料就绪状态和历史 ReviewRun。选择右侧“发起{{
                    startReviewMode === 'formal' ? '正式复核' : '缺项预审'
                  }}”可启动当前可用流程，也可以先检索证据或查看标准条款。
                </p>
                <div class="welcome-actions">
                  <ElButton size="small" @click="sendMessage('/检索证据')">检索证据</ElButton>
                  <ElButton size="small" @click="sendMessage('/标准条款')">标准条款</ElButton>
                  <ElButton size="small" @click="sendMessage('/草拟意见')">草拟意见</ElButton>
                </div>
              </div>
            </article>

            <article
              v-for="message in messages"
              :key="message.id"
              :class="['conversation-message', `is-${message.role}`]"
              :aria-label="message.role === 'user' ? `${displayUser}的消息` : 'AI 复核助手回复'"
            >
              <div class="message-body">
                <template
                  v-for="(block, blockIndex) in message.contentBlocks"
                  :key="`${message.id}-${blockIndex}`"
                >
                  <ReviewMarkdownText
                    v-if="block.type === 'text'"
                    :content="blockDisplayText(block)"
                    :references="blockReferences(block)"
                    @open-reference="openMessageReference"
                  />

                  <section v-else-if="block.type === 'basis_card'" class="content-card basis-card">
                    <h3
                      ><ElIcon><Document /></ElIcon>适用标准条款</h3
                    >
                    <div
                      v-for="basis in blockItems<Record<string, unknown>>(block)"
                      :key="String(basis.sourceLocatorId || basis.clauseId)"
                    >
                      <strong>{{ basisDisplayLabel(basis) }}</strong>
                      <p>{{ basis.summary || basis.title || '项目节点适用标准条款' }}</p>
                      <ElButton
                        v-if="basis.sourceLocatorId || basis.clauseId"
                        text
                        type="primary"
                        @click="openMessageReference(basisToReference(basis))"
                      >
                        查看原文
                      </ElButton>
                    </div>
                    <ElEmpty
                      v-if="!blockItems(block).length"
                      description="当前条款包暂无可展示条款"
                      :image-size="48"
                    />
                  </section>

                  <section
                    v-else-if="block.type === 'evidence_card'"
                    class="content-card evidence-card"
                  >
                    <h3
                      ><ElIcon><Files /></ElIcon
                      >{{ 'title' in block ? block.title || '证据候选' : '证据候选' }}</h3
                    >
                    <div
                      v-for="evidence in blockItems<EvidenceLink>(block)"
                      :key="evidence.id"
                      class="evidence-row"
                    >
                      <div>
                        <strong>{{
                          evidence.fileName || evidence.fieldName || evidence.id
                        }}</strong>
                        <small
                          >第 {{ evidence.pageNo || '-' }} 页 ·
                          {{ evidence.manualStatusLabel || evidence.manualStatus || '候选' }}</small
                        >
                        <p v-if="evidence.quotedText" class="evidence-quote">
                          {{ evidence.quotedText }}
                        </p>
                        <ul v-if="visibleEvidenceFacts(evidence).length > 1" class="evidence-facts">
                          <li
                            v-for="fact in visibleEvidenceFacts(evidence).slice(1, 4)"
                            :key="`${evidence.id}-${fact.targetCode}-${fact.pageNo}`"
                          >
                            <strong>{{ fact.targetName || '证据事实' }}</strong>
                            <span>{{ fact.quotedText }}</span>
                          </li>
                        </ul>
                      </div>
                      <ElButton text type="primary" @click="openEvidence(evidence)"
                        >查看原文</ElButton
                      >
                      <ElButton
                        v-if="!('advisory' in block && block.advisory)"
                        text
                        @click="toggleEvidenceSelection(evidence)"
                      >
                        {{ selectedEvidenceIds.has(evidence.id) ? '移出上下文' : '加入上下文' }}
                      </ElButton>
                    </div>
                  </section>

                  <section
                    v-else-if="block.type === 'judgment_summary'"
                    class="content-card judgment-card"
                  >
                    <h3
                      ><ElIcon><CircleCheck /></ElIcon>判断摘要</h3
                    >
                    <div class="judgment-grid">
                      <span
                        >ReviewRun<strong>{{
                          'reviewRunId' in block ? block.reviewRunId || '-' : '-'
                        }}</strong></span
                      >
                      <span
                        >状态<strong>{{
                          'status' in block ? block.status || '-' : '-'
                        }}</strong></span
                      >
                      <span
                        >当前步骤<strong>{{
                          'currentStep' in block ? block.currentStep || '-' : '-'
                        }}</strong></span
                      >
                    </div>
                  </section>

                  <div v-else-if="block.type === 'action_suggestions'" class="suggestion-actions">
                    <ElButton
                      v-for="action in blockActions(block)"
                      :key="action.actionKey"
                      size="small"
                      @click="handleSuggestion(action.actionKey, message)"
                    >
                      {{ action.label }}
                    </ElButton>
                  </div>
                </template>
                <p
                  v-if="messageExecutionLabel(message)"
                  :class="[
                    'message-execution-meta',
                    {
                      'is-agent': message.execution?.mode === 'llm_agent',
                      'is-fallback': message.execution?.mode === 'deterministic_fallback'
                    }
                  ]"
                >
                  {{ messageExecutionLabel(message) }}
                </p>
                <p v-if="messageTokenUsageLabel(message)" class="message-token-usage">
                  {{ messageTokenUsageLabel(message) }}
                </p>
              </div>
            </article>

            <section
              v-if="showExecutionActivity"
              :class="['execution-activity', { 'is-active': executionActive }]"
            >
              <button
                type="button"
                class="execution-summary"
                :aria-expanded="activityExpanded"
                @click="activityExpanded = !activityExpanded"
              >
                <span class="execution-state" aria-hidden="true">
                  <span v-if="executionActive" class="execution-spinner"></span>
                  <span v-else class="execution-check">✓</span>
                </span>
                <span class="execution-copy">
                  <strong>{{ executionStatusLabel }}</strong>
                  <small>{{ executionSummary }}</small>
                </span>
                <span :class="['execution-chevron', { 'is-open': activityExpanded }]">⌄</span>
              </button>

              <div v-if="activityExpanded" class="execution-details">
                <ElProgress
                  v-if="runProgress !== null"
                  :percentage="runProgress"
                  :stroke-width="4"
                  :show-text="false"
                />
                <ol v-if="(sending ? liveAgentTrace : latestExecutionEvents).length">
                  <li
                    v-for="event in sending ? liveAgentTrace : latestExecutionEvents"
                    :key="event.eventId"
                  >
                    <span class="execution-event-dot"></span>
                    <span>
                      {{ event.title || event.eventType }}
                      <small
                        v-if="
                          event.payload &&
                          typeof event.payload === 'object' &&
                          'summary' in event.payload &&
                          event.payload.summary
                        "
                      >
                        · {{ String(event.payload.summary) }}
                      </small>
                    </span>
                    <time>{{ formatTime(event.occurredAt) }}</time>
                  </li>
                </ol>
                <p v-else>等待首个执行步骤…</p>
              </div>
            </section>
          </template>
        </section>

        <section class="composer-card">
          <ElInput
            v-model="composer"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="4000"
            placeholder="向 AI 复核助手输入问题，或使用快捷命令继续处理…"
            @keydown.meta.enter.prevent="sendMessage()"
            @keydown.ctrl.enter.prevent="sendMessage()"
          />
          <div class="composer-actions">
            <div>
              <ElButton size="small" @click="sendMessage('/检索证据')">/检索证据</ElButton>
              <ElButton size="small" @click="sendMessage('/标准条款')">/标准条款</ElButton>
              <ElButton size="small" @click="sendMessage('/草拟意见')">/草拟意见</ElButton>
            </div>
            <div>
              <ElButton v-if="sending" :loading="cancelling" @click="stopCurrentAnswer"
                >停止回答</ElButton
              >
              <ElButton type="primary" :icon="Promotion" :loading="sending" @click="sendMessage()"
                >发送</ElButton
              >
            </div>
          </div>
        </section>

        <ElCollapse v-model="tracePanels" class="trace-collapse">
          <ElCollapseItem name="trace">
            <template #title>
              <span class="trace-title"
                >ReviewRun 执行轨迹 <small>{{ graphNodes.length }} 个步骤</small></span
              >
            </template>
            <div v-if="graphNodes.length" class="trace-grid">
              <article v-for="node in graphNodes" :key="String(node.nodeKey)">
                <span :class="['trace-status', `is-${node.status}`]"></span>
                <div>
                  <strong>{{ node.label || node.nodeKey }}</strong>
                  <small
                    >{{ node.status }} · Tool
                    {{ Array.isArray(node.toolCalls) ? node.toolCalls.length : 0 }}</small
                  >
                </div>
              </article>
            </div>
            <ElEmpty v-else description="当前暂无 ReviewRun 执行轨迹" :image-size="60" />
          </ElCollapseItem>
        </ElCollapse>
      </main>

      <aside class="context-panel">
        <section class="side-card">
          <h2>当前上下文</h2>
          <dl>
            <div
              ><dt>当前任务</dt><dd>{{ currentTask }}</dd></div
            >
            <div
              ><dt>当前状态</dt
              ><dd
                ><ElTag :type="runStatusTone">{{ runStatus }}</ElTag></dd
              ></div
            >
            <div
              ><dt>关联证据</dt><dd>{{ selectedEvidence.length }} 份</dd></div
            >
          </dl>
          <ElButton
            class="full-button"
            type="primary"
            :icon="MagicStick"
            :loading="actionLoading"
            :disabled="!canStartReview"
            @click="handleStartReview"
          >
            发起{{ startReviewMode === 'formal' ? '正式复核' : '缺项预审' }}
          </ElButton>
        </section>

        <section class="side-card evidence-workset">
          <div class="side-card-title">
            <h2>文件资料</h2><small>{{ selectedEvidenceSummary }}</small>
          </div>
          <div v-for="evidence in selectedEvidence" :key="evidence.id" class="selected-evidence">
            <div>
              <strong>{{ evidence.fileName || evidence.fieldName || evidence.id }}</strong>
              <small>第 {{ evidence.pageNo || '-' }} 页</small>
            </div>
            <ElTag
              :type="evidence.manualStatus === 'confirmed' ? 'success' : 'warning'"
              size="small"
            >
              {{ evidence.manualStatusLabel || evidence.manualStatus || '候选' }}
            </ElTag>
            <div class="selected-evidence-actions">
              <ElButton text type="primary" @click="openEvidence(evidence)">查看</ElButton>
              <ElButton
                v-if="evidence.manualStatus !== 'confirmed'"
                text
                type="success"
                @click="confirmEvidence(evidence)"
                >确认</ElButton
              >
              <ElButton text @click="toggleEvidenceSelection(evidence)">移除</ElButton>
            </div>
          </div>
          <ElEmpty v-if="!selectedEvidence.length" description="暂无文件资料" :image-size="52" />
        </section>

        <section class="side-card quick-actions">
          <h2>快捷操作</h2>
          <div>
            <ElButton :icon="Document" @click="sendMessage('/标准条款')">查看标准条款</ElButton>
            <ElButton :icon="Search" @click="sendMessage('/检索证据')">让 AI 补充证据</ElButton>
            <ElButton :icon="MagicStick" @click="sendMessage('/草拟意见')">生成意见草稿</ElButton>
          </div>
        </section>

        <section v-if="activeTask" class="side-card human-task-card">
          <div class="side-card-title"><h2>过程人工待办</h2><ElTag type="warning">1</ElTag></div>
          <strong>{{ activeTask.title }}</strong>
          <p>{{ activeTask.description }}</p>
          <ElButton
            class="full-button"
            type="warning"
            :disabled="!canRenderActiveTask"
            @click="openActiveHumanTask"
          >
            处理并恢复复核
          </ElButton>
        </section>

        <section class="side-card human-decision-card">
          <h2>最终人工结论</h2>
          <ElAlert
            v-if="!canSubmitHumanDecision"
            :title="activeTask ? '请先完成过程人工待办' : 'ReviewRun 完成后可提交最终结论'"
            type="info"
            :closable="false"
          />
          <label>审查结论</label>
          <ElRadioGroup v-model="humanDecision" :disabled="!canSubmitHumanDecision">
            <ElRadioButton value="accept">采纳</ElRadioButton>
            <ElRadioButton value="edit">修改</ElRadioButton>
            <ElRadioButton value="reject">驳回</ElRadioButton>
          </ElRadioGroup>
          <label>人工复核意见</label>
          <ElInput
            v-model="humanComment"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="请输入人工复核意见"
          />
          <ElButton
            class="full-button"
            type="primary"
            :loading="actionLoading"
            :disabled="!canSubmitHumanDecision"
            @click="handleSubmitHumanDecision"
          >
            保存人工复核结论
          </ElButton>
        </section>
      </aside>
    </div>

    <EvidenceLocatorDialog
      v-model="evidenceDialogVisible"
      :project-id="activeProjectId"
      :evidence="evidencePreview"
      :extracted-fields="extractedFields"
    />
    <R12RegistryVerificationDialog
      v-model="r12DialogVisible"
      :task="activeTask"
      :loading="humanTaskSubmitting"
      @submit="submitHumanTask"
      @locate="locateR12Candidate"
    />
    <R19SemanticEvidenceDialog
      v-model="r19DialogVisible"
      :task="activeTask"
      :loading="humanTaskSubmitting"
      @submit="submitHumanTask"
      @locate="locateR19Evidence"
    />
  </div>
</template>

<style scoped>
.review-b-shell {
  --review-blue: #1468e8;
  --review-ink: #172033;
  --review-muted: #667085;
  --review-line: #e3e9f3;
  --review-surface: #f6f8fc;

  min-width: 1120px;
  min-height: 100vh;
  color: var(--review-ink);
  background: var(--review-surface);
}

.review-b-topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  gap: 18px;
  align-items: center;
  height: 72px;
  padding: 0 22px;
  background: rgb(255 255 255 / 96%);
  border-bottom: 1px solid var(--review-line);
  box-shadow: 0 3px 16px rgb(22 34 51 / 5%);
  backdrop-filter: blur(12px);
}

.brand {
  display: flex;
  gap: 11px;
  align-items: center;
  min-width: 280px;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(145deg, #4387ff, #075bd8);
  border-radius: 12px;
  box-shadow: 0 7px 18px rgb(20 104 232 / 24%);
  place-items: center;
}

.brand strong {
  display: block;
}

.brand strong {
  font-size: 17px;
}

.project-switcher {
  width: 300px;
}

.topbar-spacer {
  flex: 1;
}

.review-user {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
}

.review-user span {
  width: 30px;
  height: 30px;
  background: linear-gradient(145deg, #367be8, #1954bb);
  border-radius: 50%;
}

.page-alert {
  margin: 12px 20px 0;
}

.review-b-layout {
  display: grid;
  grid-template-columns: minmax(300px, 404px) minmax(650px, 1fr) 330px;
  min-height: calc(100vh - 72px);
}

.review-b-shell.is-embedded {
  min-width: 0;
  min-height: 0;
  background: transparent;
}

.review-b-shell.is-embedded .page-alert {
  margin: 0 0 12px;
}

.review-b-shell.is-embedded .review-b-layout {
  grid-template-columns: minmax(0, 1fr) minmax(290px, 330px);
  min-height: 0;
}

.review-b-shell.is-embedded .context-panel {
  position: static;
  top: auto;
  height: auto;
  max-height: none;
}

.node-sidebar,
.context-panel {
  position: sticky;
  top: 72px;
  align-self: start;
  height: calc(100vh - 72px);
  overflow: auto;
  background: #fff;
}

.node-sidebar {
  padding: 18px 14px;
  border-right: 1px solid var(--review-line);
}

.sidebar-heading,
.side-card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-heading {
  padding: 0 8px 12px;
  font-weight: 700;
}

.node-sidebar :deep(.tree-panel) {
  border: 0;
}

.node-sidebar :deep(.tree-panel > .el-card__header) {
  display: none;
}

.node-sidebar :deep(.tree-panel > .el-card__body) {
  padding: 0;
}

.node-sidebar :deep(.tree-scroll) {
  max-height: calc(100vh - 245px);
}

.sidebar-links {
  display: grid;
  gap: 6px;
  padding-top: 14px;
  margin-top: 14px;
  border-top: 1px solid var(--review-line);
}

.sidebar-links button {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 10px 12px;
  color: #475467;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 8px;
}

.sidebar-links button:hover,
.sidebar-links button.is-active {
  color: var(--review-blue);
  background: #eef5ff;
}

.conversation-column {
  min-width: 0;
  padding: 20px 22px 28px;
}

.conversation-head {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  justify-content: space-between;
}

.conversation-head h1 {
  margin: 0;
  font-size: 25px;
}

.conversation-head p {
  margin: 7px 0 0;
  color: var(--review-muted);
}

.run-meta {
  display: flex;
  align-items: center;
}

.context-chips {
  display: flex;
  gap: 10px;
  padding: 10px;
  margin-top: 18px;
  overflow-x: auto;
  background: #fff;
  border: 1px solid var(--review-line);
  border-radius: 10px;
}

.context-chips span {
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #344054;
  background: #f8fafc;
  border: 1px solid #ebeff5;
  border-radius: 7px;
  flex: 0 0 auto;
}

.context-chips .primary-chip {
  color: var(--review-blue);
  background: #eef5ff;
  border-color: #d6e6ff;
}

.context-chips .warning {
  color: #b35b00;
  background: #fff8ec;
  border-color: #ffe0ad;
}

.conversation-timeline {
  max-height: calc(100vh - 360px);
  min-height: 420px;
  padding: 20px 4px 12px;
  overflow: auto;
  scroll-behavior: smooth;
}

.welcome-card,
.conversation-message {
  display: flex;
  margin-bottom: 18px;
}

.welcome-card > div {
  flex: 1;
  min-width: 0;
  padding: 4px 2px 10px;
}

.message-body {
  min-width: 0;
}

.welcome-card p {
  margin: 7px 0 12px;
  line-height: 1.65;
  color: var(--review-muted);
}

.conversation-message.is-user {
  justify-content: flex-end;
  margin-left: 72px;
}

.conversation-message.is-user .message-body {
  max-width: 78%;
  padding: 11px 16px;
  background: #f0f1f3;
  border-radius: 20px;
}

.conversation-message.is-assistant,
.conversation-message.is-system {
  padding: 4px 2px 10px;
  margin-right: 24px;
}

.conversation-message.is-assistant .message-body,
.conversation-message.is-system .message-body {
  width: 100%;
}

.message-execution-meta {
  margin: 9px 0 0;
  font-size: 11px;
  line-height: 1.4;
  color: #7a8494;
}

.message-execution-meta::before {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  vertical-align: 1px;
  background: #98a2b3;
  border-radius: 50%;
  content: '';
}

.message-execution-meta.is-agent {
  color: #15715a;
}

.message-execution-meta.is-agent::before {
  background: #20a47a;
}

.message-execution-meta.is-fallback {
  color: #a15c00;
}

.message-execution-meta.is-fallback::before {
  background: #e19a36;
}

.message-token-usage {
  margin: 3px 0 0 12px;
  font-size: 11px;
  line-height: 1.4;
  color: #98a2b3;
}

.content-card {
  padding: 13px;
  margin-top: 12px;
  background: #fbfcfe;
  border: 1px solid #e6ebf3;
  border-radius: 9px;
}

.content-card h3 {
  display: flex;
  gap: 7px;
  align-items: center;
  margin: 0 0 10px;
  font-size: 14px;
}

.basis-card > div {
  padding: 9px 0;
  border-top: 1px dashed #dbe3ef;
}

.basis-card p {
  margin: 5px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--review-muted);
}

.evidence-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  padding: 9px 0;
  border-top: 1px dashed #dbe3ef;
}

.evidence-row strong,
.evidence-row small {
  display: block;
}

.evidence-row small {
  margin-top: 3px;
  color: var(--review-muted);
}

.evidence-quote {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--review-ink);
}

.evidence-facts {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.evidence-facts li {
  display: flex;
  gap: 6px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--review-muted);
}

.evidence-facts li strong {
  flex: 0 0 auto;
  color: var(--review-ink);
}

.judgment-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.judgment-grid span {
  font-size: 11px;
  color: var(--review-muted);
}

.judgment-grid strong {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--review-ink);
  overflow-wrap: anywhere;
}

.suggestion-actions,
.welcome-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.execution-activity {
  margin: -2px 0 18px;
}

.execution-summary {
  display: grid;
  width: 100%;
  padding: 8px 6px;
  color: #475467;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 8px;
  grid-template-columns: 22px minmax(0, 1fr) 20px;
  gap: 8px;
  align-items: center;
}

.execution-summary:hover {
  background: #f1f5fa;
}

.execution-state {
  display: grid;
  width: 18px;
  height: 18px;
  color: #15805d;
  background: #eaf8f2;
  border-radius: 50%;
  place-items: center;
}

.execution-activity.is-active .execution-state {
  color: var(--review-blue);
  background: #eaf2ff;
}

.execution-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid rgb(20 104 232 / 22%);
  border-top-color: var(--review-blue);
  border-radius: 50%;
  animation: execution-spin 0.8s linear infinite;
}

.execution-check {
  font-size: 11px;
  font-weight: 700;
}

.execution-copy {
  display: flex;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.execution-copy strong {
  font-size: 12px;
  color: #344054;
  white-space: nowrap;
}

.execution-copy small {
  overflow: hidden;
  font-size: 12px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-chevron {
  font-size: 15px;
  color: #98a2b3;
  transition: transform 0.18s ease;
}

.execution-chevron.is-open {
  transform: rotate(180deg);
}

.execution-details {
  padding: 10px 12px;
  margin: 2px 6px 0 30px;
  background: #f8fafc;
  border-left: 2px solid #d8e2f0;
  border-radius: 0 8px 8px 0;
}

.execution-details ol {
  padding: 0;
  margin: 8px 0 0;
  list-style: none;
}

.execution-details li {
  display: grid;
  padding: 5px 0;
  font-size: 12px;
  color: #475467;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.execution-details time,
.execution-details p {
  font-size: 11px;
  color: #98a2b3;
}

.execution-details p {
  margin: 0;
}

.execution-event-dot {
  width: 6px;
  height: 6px;
  background: #98a2b3;
  border-radius: 50%;
}

@keyframes execution-spin {
  to {
    transform: rotate(360deg);
  }
}

.composer-card {
  padding: 12px;
  background: #fff;
  border: 1px solid #b8d2ff;
  border-radius: 11px;
  box-shadow: 0 8px 30px rgb(20 104 232 / 8%);
}

.composer-card :deep(.el-textarea__inner) {
  box-shadow: none;
}

.composer-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding-top: 9px;
}

.trace-collapse {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--review-line);
  border-radius: 10px;
}

.trace-collapse :deep(.el-collapse-item__header) {
  padding: 0 15px;
  border-radius: 10px;
}

.trace-collapse :deep(.el-collapse-item__wrap) {
  border-radius: 0 0 10px 10px;
}

.trace-collapse :deep(.el-collapse-item__content) {
  padding: 4px 15px 15px;
}

.trace-title small {
  margin-left: 8px;
  font-weight: 400;
  color: var(--review-muted);
}

.trace-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.trace-grid article {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 10px;
  background: #f8fafc;
  border-radius: 8px;
}

.trace-grid strong,
.trace-grid small {
  display: block;
}

.trace-grid small {
  margin-top: 3px;
  color: var(--review-muted);
}

.trace-status {
  width: 9px;
  height: 9px;
  background: #98a2b3;
  border-radius: 50%;
}

.trace-status.is-succeeded {
  background: #12a56f;
}

.trace-status.is-running {
  background: var(--review-blue);
}

.trace-status.is-failed {
  background: #e5484d;
}

.trace-status.is-skipped {
  background: #f59e0b;
}

.context-panel {
  padding: 18px 14px 28px;
  border-left: 1px solid var(--review-line);
}

.side-card {
  padding: 15px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid var(--review-line);
  border-radius: 10px;
}

.side-card h2 {
  margin: 0 0 13px;
  font-size: 15px;
}

.side-card-title h2 {
  margin-bottom: 0;
}

.side-card-title {
  margin-bottom: 13px;
}

.side-card-title small {
  color: var(--review-muted);
}

.side-card dl {
  margin: 0 0 14px;
}

.side-card dl > div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 9px;
  padding: 7px 0;
}

.side-card dt {
  font-size: 12px;
  color: var(--review-muted);
}

.side-card dd {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.full-button {
  width: 100%;
  margin-top: 10px;
}

.selected-evidence {
  padding: 10px 0;
  border-top: 1px solid #edf0f5;
}

.selected-evidence > div:first-child {
  display: inline-block;
  width: calc(100% - 74px);
  vertical-align: middle;
}

.selected-evidence strong,
.selected-evidence small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selected-evidence small {
  margin-top: 3px;
  color: var(--review-muted);
}

.selected-evidence-actions {
  display: flex;
  margin-top: 5px;
}

.quick-actions > div {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.quick-actions .el-button {
  justify-content: flex-start;
  margin: 0;
}

.human-task-card {
  background: #fffaf1;
  border-color: #ffdfaa;
}

.human-task-card > strong {
  display: block;
  margin-bottom: 6px;
}

.human-task-card p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--review-muted);
}

.human-decision-card {
  display: grid;
  gap: 10px;
}

.human-decision-card h2 {
  margin-bottom: 0;
}

.human-decision-card label {
  font-size: 12px;
  font-weight: 600;
  color: #475467;
}

.human-decision-card :deep(.el-radio-group) {
  width: 100%;
}

.human-decision-card :deep(.el-radio-button) {
  flex: 1;
}

.human-decision-card :deep(.el-radio-button__inner) {
  width: 100%;
}

@media (width <= 1380px) {
  .review-b-layout {
    grid-template-columns: minmax(280px, 360px) minmax(610px, 1fr) 302px;
  }

  .brand {
    min-width: 240px;
  }

  .project-switcher {
    width: 240px;
  }
}
</style>
