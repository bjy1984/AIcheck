<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { blockingReasonsAsItems, buildSuggestedQuestions } from './suggestedQuestions'
import { isRunSettled } from './runPolling'
import {
  ElAlert,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
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
  ArrowRight,
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
  returnCorrectionApi,
  saveReviewOpinionApi,
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
  cancelReviewRunApi,
  streamReviewBEventsApi,
  runReviewBSessionActionApi,
  sendReviewBMessageApi
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
import type {
  EvidenceLink,
  ExtractedField,
  Project,
  ProjectTreeNode,
  ReviewOpinion
} from '@/types/aicheck'
import { useUserStore } from '@/store/modules/user'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import EvidenceLocatorDialog from '@/views/AICheck/components/EvidenceLocatorDialog.vue'
import ProjectNodeTree from '@/views/AICheck/components/ProjectNodeTree.vue'
import R12RegistryVerificationDialog from '@/views/AICheck/components/R12RegistryVerificationDialog.vue'
import R19SemanticEvidenceDialog from '@/views/AICheck/components/R19SemanticEvidenceDialog.vue'
import ReviewMarkdownText from '@/views/AIReviewB/components/ReviewMarkdownText.vue'
import ReturnCorrectionDialog from '@/views/AIReviewB/components/ReturnCorrectionDialog.vue'
import {
  resolveReviewSidebarLayout,
  resolveReviewWorkbenchContext
} from '@/views/AIReviewB/embeddedReviewWorkbench'
import {
  buildFinalConclusionPayload,
  canSubmitFinalConclusion
} from '@/views/AIReviewB/finalConclusion'
import type { ReturnCorrectionRequest } from '@/views/AIReviewB/returnCorrection'
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
const leftSidebarCollapsed = ref(false)
const rightSidebarCollapsed = ref(false)
const sidebarLayout = computed(() =>
  resolveReviewSidebarLayout({
    embedded: props.embedded,
    leftCollapsed: leftSidebarCollapsed.value,
    rightCollapsed: rightSidebarCollapsed.value
  })
)
const executionStarted = ref(false)
const evidenceDialogVisible = ref(false)
const evidencePreview = ref<EvidenceLink>()
const r12DialogVisible = ref(false)
const r19DialogVisible = ref(false)
const humanTaskSubmitting = ref(false)
const returnCorrectionVisible = ref(false)
const reviewResult = ref<ReviewOpinion['result']>('证据不足')
const reviewOpinion = ref('')
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

// 正式复核跑的是 graph_node / quality_gate / review_run 这些事件，
// 一条都不是 agent.*。原来执行动态只认 agent.*，于是发起复核之后界面上
// 只有一个「执行中」在转，后台七八十条事件一条都没露面（实测用户反馈）。
const REVIEW_RUN_EVENT_PREFIXES = /^(graph_node|quality_gate|review_run|rule_check|retrieval)\./
const liveRunTrace = computed(() =>
  executionEvents.value
    .filter((event) => REVIEW_RUN_EVENT_PREFIXES.test(String(event.eventType || '')))
    .slice(-12)
)
/** 当前该展示哪一条流：聊天看 agent.*，复核看运行事件，闲时看最近几条。 */
const liveTrace = computed(() => {
  if (sending.value) return liveAgentTrace.value
  if (reviewStarting.value) return liveRunTrace.value
  return latestExecutionEvents.value
})
/** 有东西正在跑——聊天或复核，两条路径共用一个口径。 */
const executionInFlight = computed(() => sending.value || reviewStarting.value)
const displayUser = computed(
  () => userStore.getUserInfo?.displayName || userStore.getUserInfo?.username || '监检人员'
)
/* 推荐问题：按当前节点卡在哪、规则要求什么来拼，不经 LLM。
 *
 * 系统已经知道这个节点此刻的问题（items 里的 needs_attention issue）和它的
 * 审查要点（businessBasis.criteria / checkMethod）。让模型生成推荐，得先把这些
 * 事实喂给它——而喂进去的那一刻答案已经在手上了。详见 suggestedQuestions 模块。
 */
const suggestedQuestions = computed(() =>
  buildSuggestedQuestions(
    // 这个工作台手上没有七项审计明细，卡点信号在 evidenceReadiness 里
    blockingReasonsAsItems(workspace.value?.evidenceReadiness?.blockingReasons),
    businessBasis.value as never
  )
)

const useSuggestedQuestion = (text: string) => {
  // 填进输入框而不是直接发出去：监检往往要在这个基础上补一句
  // （「…针对第 3 份资料」）。直接发送会剥夺这次修改的机会。
  composer.value = text
}

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
const runStatus = computed(() => String(activeRun.value?.status || '未发起'))

/** 一条 queued/running 的运行，多久没动静就不能再叫「执行中」。
 *
 * 实测（2026-08-15）：工作台上挂着一条 09:59 建的 queued 运行，
 * 十几个小时之后仍显示「执行中」、顶部刷新状态一直转圈。
 * 它早就没有任何执行器在跑了——那是修 I-1 之前留下的僵尸运行。
 *
 * 「排队中」和「已经死了」在界面上长得一模一样，是这条问题最耗人的地方：
 * 监检不知道该继续等，还是该重新发起。
 */
const STALE_RUN_AFTER_MS = 10 * 60 * 1000

/** 服务端时钟。响应里的时间戳**不带时区**，拿浏览器本地时间去比会算出荒谬的结果。
 *
 * 实测：服务器写的是 `2026-08-15 13:56:11`，而浏览器在 GMT-0700 且当时是 09:40，
 * 按本地时区解析后这条运行「在 256 分钟之后」——差值为负，任何「过去多久」的
 * 判断都失效。两边都用服务端时钟，时区差自然抵消。
 */
const serverNow = ref(0)

const parseServerTimestamp = (value?: string | null) => {
  const raw = String(value || '').trim()
  if (!raw) return 0
  const parsed = new Date(raw.replace(' ', 'T')).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

const runLastActivityAt = computed(() =>
  parseServerTimestamp(activeRun.value?.updatedAt || activeRun.value?.createdAt)
)

/** 这条运行看着在跑，其实已经很久没动了。 */
const runLooksStalled = computed(() => {
  if (!['queued', 'running', 'resuming', '推理中'].includes(runStatus.value)) return false
  const at = runLastActivityAt.value
  if (!at || !serverNow.value) return false
  return serverNow.value - at > STALE_RUN_AFTER_MS
})
const canSubmitReviewOpinion = computed(() =>
  canSubmitFinalConclusion(workspace.value?.permissions, runStatus.value)
)
/** 本节点最近一次已保存的人工结论。
 *
 * 接口一直在 latestHumanDecision 里返回它，前端从来没渲染——于是保存成功之后
 * 页面上没有任何痕迹，监检只能凭记忆判断「我到底存没存」，然后再点一次。
 */
const savedHumanDecision = computed(() => {
  const raw = workspace.value?.latestHumanDecision
  if (!raw || typeof raw !== 'object') return undefined
  const result = String((raw as Record<string, unknown>).result || '').trim()
  const opinion = String((raw as Record<string, unknown>).opinion || '').trim()
  if (!result && !opinion) return undefined
  return {
    result: result || '（未填结论）',
    opinion,
    savedAt: String(
      (raw as Record<string, unknown>).updatedAt || (raw as Record<string, unknown>).createdAt || ''
    ).trim()
  }
})

const canReturnCorrection = computed(
  () => workspace.value?.permissions.canReturnCorrection === true
)
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
    // 久无动静的运行不再算「执行中」——否则一条僵尸运行会让转圈永远停不下来。
    (conversationStarted.value &&
      !runLooksStalled.value &&
      ['queued', 'running', 'resuming', '推理中'].includes(runStatus.value))
)
const showExecutionActivity = computed(() => executionActive.value || conversationStarted.value)
const executionSummary = computed(() => {
  // 停住的运行要给出「停在哪一刻」和「现在能做什么」，
  // 而不是继续显示一句像还在推进的话。
  if (runLooksStalled.value) {
    const at = runLastActivityAt.value
      ? formatTime(activeRun.value?.updatedAt || activeRun.value?.createdAt)
      : ''
    return `这次运行自${at ? ' ' + at + ' ' : ''}起没有新的进展，可重新发起复核。`
  }
  if (sending.value) {
    const latest = liveAgentTraceLatest.value
    if (latest?.title) return latest.title
    return '正在理解问题并核查当前节点上下文…'
  }
  if (reviewStarting.value) {
    // 「正在启动」只在真的还没跑起来时才成立。跑起来之后要报当前这步在做什么，
    // 否则一场几分钟的复核，用户全程只看到同一句话。
    const latest = liveRunTrace.value.at(-1)
    return latest?.title || latest?.eventType || '正在启动 AI 复核流程…'
  }
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
  // 说清楚是「停住了」，而不是继续假装在跑；下一句 executionSummary 给出停在哪一刻。
  if (runLooksStalled.value) return '执行已中断'
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

// 上一次真正取回来的那份 audit-view 对应的运行指纹。
// 实测：轮询每 3 秒把 339 KB 的 audit-view 整个再拉一遍，13 秒里拉了 4 次，
// 而且越拉越慢（1.4s → 3.0s → 4.4s → 13.2s）——服务端被自己人打崩了。
// 运行没变就没有任何新东西可看，重取纯属浪费。
let loadedAuditViewSignature = ''

const auditViewSignature = () =>
  [
    activeRunId.value,
    activeRun.value?.status,
    activeRun.value?.revision,
    activeRun.value?.updatedAt
  ]
    .map((item) => String(item ?? ''))
    .join('|')

const loadAuditView = async (force = false) => {
  if (!activeRunId.value) {
    auditView.value = undefined
    loadedAuditViewSignature = ''
    return
  }
  const signature = auditViewSignature()
  if (!force && auditView.value && signature === loadedAuditViewSignature) return
  try {
    auditView.value = (await getReviewBAuditViewApi(activeRunId.value)).data
    loadedAuditViewSignature = signature
  } catch {
    auditView.value = undefined
    // 指纹不留：下一轮要重试，别把一次失败当成「已经取过了」。
    loadedAuditViewSignature = ''
  }
}

/** 轮询取事件用的游标——往回退一段，别用 0。
 *
 * 原来每一轮都 `after=0` 取完整快照，理由是「合并会话事件与 ReviewRun 事件后
 * 会重排，用游标怕漏读」。这个担心是对的，但代价是每 3 秒 204 KB：
 * 切一次节点的 9 秒里就拉了 3 次、600 多 KB，纯背景流量。
 *
 * 重排只会发生在最近这一小段（后台刚追加、时间戳交错的那些），
 * 所以往回退一个安全窗口即可：既容忍重排，又不必每次搬运全部历史。
 * mergeEvents 本来就按 eventId 去重，重复取回来不会有副作用。
 */
const EVENT_POLL_OVERLAP = 30
const eventPollCursor = () => {
  const latest = events.value.at(-1)?.sequence || 0
  return Math.max(0, latest - EVENT_POLL_OVERLAP)
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
    listReviewBEventsApi(sessionId, reset ? 0 : eventPollCursor())
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
    const eventRes = await listReviewBEventsApi(session.value.id, eventPollCursor())
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
  workspace.value = await fetchWorkspace(String(route.query.reviewRunId || '') || undefined)
}

/** 取工作区，并顺手把服务端时钟对上。
 *
 * 直接调 getReviewBWorkspaceApi 的地方有两处，各自记得更新时钟迟早会漏一个——
 * 漏掉的那条路径上，「运行停了多久」就又变回拿浏览器时间去比。
 */
const fetchWorkspace = async (reviewRunId?: string) => {
  const res = await getReviewBWorkspaceApi(activeProjectId.value, activeNodeId.value, reviewRunId)
  const stamp = parseServerTimestamp((res as { serverTime?: string }).serverTime)
  if (stamp) serverNow.value = stamp
  return res.data
}

const loadNodeWorkspace = async (reset = true) => {
  if (!activeProjectId.value || !activeNodeId.value) return
  nodeLoading.value = true
  pageError.value = ''
  if (reset) {
    workspace.value = undefined
    auditView.value = undefined
    reviewOpinion.value = ''
  }
  try {
    workspace.value = await fetchWorkspace(String(route.query.reviewRunId || '') || undefined)
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
    workspace.value = await fetchWorkspace(previousRunId || undefined)
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

/** 退出用 logoutConfirm（带二次确认），与完整工作台那边一个口径。 */
const handleUserCommand = (command: string | number | object) => {
  if (command === 'logout') {
    userStore.logoutConfirm()
    return
  }
  if (command === 'workbench') handleBackToWorkbench()
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
  // ai-recheck 是**同步执行整场审查**的一次 POST，实测要跑好几分钟。
  // 在这几分钟里原来页面上什么都不动：没有进度、没有步骤、没有事件——
  // 监检不知道是在跑、卡住了、还是已经挂了，只能干等。
  //
  // 聊天路径早就有现成的执行动态（SSE 推送 + 轮询兜底，事件流里会合并
  // ReviewRun 事件），这里只是从来没接上。
  startLiveAgentTrace()
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
      // 这里原来是 `.catch(() => undefined)`——绑定失败悄悄丢掉。
      //
      // 后果不是「少了个链接」：工作台读的是会话上的 activeReviewRunId，
      // 绑不上就永远停在上一条运行。2026-08-15 实测，界面钉在 09:59 那条
      // 永久 queued 的旧运行上显示「执行中」，而新运行早已跑完。
      //
      // 失败的常见原因是 etag 过期（页面开着这段时间会话被别的请求改过），
      // 所以先取一份新的会话再重试一次；仍然不行就如实说，别让人对着
      // 一条陈旧的运行等下去。
      const bindActiveRun = (etag?: string) =>
        runReviewBSessionActionApi(
          session.value!.id,
          'set_active_review_run',
          { reviewRunId },
          { etag, idempotencyKey: `review-b-link-${session.value!.id}-${reviewRunId}` }
        )
      try {
        await bindActiveRun(session.value.etag)
      } catch {
        await loadNodeWorkspace(false)
        try {
          await bindActiveRun(session.value?.etag)
        } catch (error) {
          ElMessage.warning(
            getAicheckErrorMessage(
              error,
              '复核已发起，但没能把它设为当前运行；页面可能仍显示上一条运行，请刷新后查看。'
            )
          )
        }
      }
    }
    ElMessage.success(`${modeLabel}已发起`)
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, `${modeLabel}发起失败。`))
  } finally {
    stopLiveAgentTrace()
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
  // 推理单独成块并默认折叠。原先是 `〔推理〕${reasoning}` 直接拼进正文——
  // 换成推理模型（deepseek-v4-pro）后，这一段动辄上千字，监检打开看到的整屏
  // 都是模型的自言自语（「让我思考…」「实际上…」），真正的结论反而在最下面。
  //
  // 过程不是没价值：判定依据可追溯是这套系统的底线，出了结论要能问「你凭什么」。
  // 所以是折叠，不是丢弃。
  const blocks: ReviewBContentBlock[] = []
  if (reasoning) blocks.push({ type: 'reasoning', text: reasoning.trim() })
  const answered = content.trim()
  blocks.push({
    type: 'text',
    text: answered ? `${answered}\n\n——正在继续核查…` : '——正在核查…'
  })
  placeholder.contentBlocks = blocks
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

/** 叫停当前正在跑的东西：聊天走会话取消，复核走 ReviewRun 取消。
 *
 * 后端 /review-runs/{id}/cancel 一直都在，前端从来没接——所以正式复核
 * 一旦跑起来就没有任何办法停下。 */
const stopCurrentExecution = async () => {
  if (cancelling.value) return
  if (reviewStarting.value && activeRunId.value) {
    cancelling.value = true
    try {
      await cancelReviewRunApi(activeRunId.value)
      ElMessage.info('已请求停止本次复核，正在等待执行器响应…')
    } catch (error) {
      ElMessage.error(getAicheckErrorMessage(error, '停止复核失败。'))
    } finally {
      cancelling.value = false
    }
    return
  }
  await stopCurrentAnswer()
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
    reviewOpinion.value = textBlock && 'text' in textBlock ? String(textBlock.text || '') : ''
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

const handleSaveReviewOpinion = async () => {
  if (!canSubmitReviewOpinion.value) return
  if (!reviewOpinion.value.trim()) {
    ElMessage.warning('请填写人工复核意见')
    return
  }
  await ElMessageBox.confirm('是否保存当前节点的人工复核结论？', '保存人工复核结论', {
    type: 'warning',
    confirmButtonText: '确认保存',
    cancelButtonText: '取消'
  })
  actionLoading.value = true
  try {
    await saveReviewOpinionApi(
      activeProjectId.value,
      activeNodeId.value,
      buildFinalConclusionPayload(reviewResult.value, reviewOpinion.value, selectedEvidence.value),
      {
        etag: workspace.value?.project.etag
      }
    )
    ElMessage.success('人工复核结论已保存')
    // 清空输入框：内容已经保存，上方的「已保存」区块会把它显示出来。
    // 不清空的话，页面看起来和保存前一模一样——监检据此认为没存成功，
    // 于是再点一次。同一节点因此攒下过 3 条重复的「证据不足」。
    reviewOpinion.value = ''
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '人工复核结论保存失败。'))
  } finally {
    actionLoading.value = false
  }
}

const handleReturnCorrection = async (payload: ReturnCorrectionRequest) => {
  if (!canReturnCorrection.value) return
  const itemCount =
    payload.mode === 'return_correction'
      ? payload.bindingIds.length
      : payload.supplementRequirements.length
  const actionLabel = payload.mode === 'return_correction' ? '退回补正' : '发起补充资料单'
  await ElMessageBox.confirm(
    `将处理 ${itemCount} 项资料要求，节点转为“需补正”并通知责任方。是否${actionLabel}？`,
    actionLabel,
    {
      type: 'warning',
      confirmButtonText: '确认执行',
      cancelButtonText: '取消'
    }
  )
  actionLoading.value = true
  try {
    await returnCorrectionApi(
      activeProjectId.value,
      activeNodeId.value,
      {
        ...payload,
        evidenceLinkIds: selectedEvidence.value
          .filter((item) => item.manualStatus === 'confirmed')
          .map((item) => item.id)
      },
      { etag: workspace.value?.project.etag }
    )
    reviewResult.value = '需补正'
    reviewOpinion.value = payload.opinion
    returnCorrectionVisible.value = false
    ElMessage.success(payload.mode === 'return_correction' ? '已退回补正' : '补充资料单已创建')
    await refreshLiveState()
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, `${actionLabel}失败。`))
    await refreshLiveState()
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

/* 推理块只做字数统计与原样展示：这段是模型的内部过程，不参与引用解析，
   也不该被「固定依据条款→适用标准条款」这类正文改写规则动到。 */
const blockReasoningLength = (block: ReviewBContentBlock) => blockText(block).length

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
  pollTimer = window.setInterval(() => {
    // 原来是无条件每 3 秒打一次：不管有没有在跑、不管标签页是否在前台。
    //
    // 它不只是浪费。2026-08-15 线上实测，正是这个轮询把正在派发的 ReviewRun
    // 弄丢的——同一个「发起缺项预审」，工作台开着 5.4 秒返回 missing、运行永远
    // 停在排队中；工作台关掉 91 秒正常跑完。后端那条已单独修（找不到就回库里捞），
    // 但没有理由继续这样空转。
    //
    // 执行期间的动态由 SSE 推送承担，这里只负责收尾那一下。
    if (document.hidden) return
    if (!executionStarted.value && isRunSettled(activeRun.value?.status)) return
    void refreshLiveState()
  }, 3000)
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
          <strong>压力管道监检工作台</strong>
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
      <!-- 「文件列表」名不副实：它去的是完整的传统工作台（审计项总览 + 节点清单 +
           已提交资料）。Workbench.vue 里早就因为「有人问怎么切换回传统视图」改叫
           「完整工作台」了，这边漏改——而监检登录后落地的正是这一页。 -->
      <ElButton type="primary" :icon="ArrowLeft" @click="handleBackToWorkbench">
        完整工作台
      </ElButton>
      <!-- 这一页原来只把用户名当文字摆着：监检登录后落在这里，
           既切不回完整工作台（名字看不懂），也**没有任何退出登录的入口**。 -->
      <ElDropdown trigger="click" @command="handleUserCommand">
        <button class="review-user" type="button" aria-label="打开用户菜单">
          <span></span>{{ displayUser }}
        </button>
        <template #dropdown>
          <ElDropdownMenu>
            <ElDropdownItem command="workbench">完整工作台</ElDropdownItem>
            <ElDropdownItem command="logout" divided>退出登录</ElDropdownItem>
          </ElDropdownMenu>
        </template>
      </ElDropdown>
    </header>

    <ElAlert
      v-if="pageError"
      class="page-alert"
      type="error"
      :title="pageError"
      :closable="false"
      show-icon
    />

    <div :class="['review-b-layout', ...sidebarLayout.layoutClasses]" v-loading="loading">
      <aside v-if="!props.embedded" class="node-sidebar">
        <button
          type="button"
          class="sidebar-toggle is-left"
          :aria-label="sidebarLayout.leftLabel"
          :title="sidebarLayout.leftLabel"
          :aria-expanded="sidebarLayout.leftExpanded"
          aria-controls="review-node-sidebar-content"
          @click="leftSidebarCollapsed = !leftSidebarCollapsed"
        >
          <ElIcon>
            <ArrowLeft v-if="sidebarLayout.leftExpanded" />
            <ArrowRight v-else />
          </ElIcon>
        </button>
        <div
          v-show="sidebarLayout.leftExpanded"
          id="review-node-sidebar-content"
          class="sidebar-content node-sidebar-content"
        >
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
        </div>
      </aside>

      <main class="conversation-column" v-loading="nodeLoading">
        <section class="conversation-head">
          <div>
            <h1>{{ currentNode?.nodeId || '-' }}. {{ currentNode?.name || '请选择节点' }}</h1>
            <p v-if="conversationSubtitle">{{ conversationSubtitle }}</p>
          </div>
          <div v-if="!props.embedded" class="run-meta">
            <ElButton :icon="View" :disabled="!activeRunId" @click="tracePanels = ['trace']"
              >查看执行轨迹</ElButton
            >
          </div>
        </section>

        <section v-if="!props.embedded" class="context-chips">
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

                  <!-- 推理过程：默认折叠成一行。展开后可读，但不占据视线。
                       监检要的是结论，不是模型的自言自语；而「凭什么」这个问题
                       随时可能被问到，所以留着能展开。 -->
                  <details
                    v-else-if="block.type === 'reasoning'"
                    class="reasoning-block"
                    :data-length="blockReasoningLength(block)"
                  >
                    <summary class="reasoning-summary">
                      推理过程 · {{ blockReasoningLength(block) }} 字
                    </summary>
                    <pre class="reasoning-text">{{ blockDisplayText(block) }}</pre>
                  </details>

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
                <ol v-if="liveTrace.length">
                  <li v-for="event in liveTrace" :key="event.eventId">
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
          <!-- 推荐问题按「这个节点此刻卡在哪」定制，不经 LLM——系统已经知道答案，
               让模型再生成一遍只会加两秒延迟和一次 token（见 suggestedQuestions）。 -->
          <div v-if="suggestedQuestions.length" class="composer-suggestions">
            <span class="composer-suggestions-label">试试问：</span>
            <button
              v-for="question in suggestedQuestions"
              :key="question.text"
              type="button"
              class="composer-suggestion"
              :title="question.text"
              @click="useSuggestedQuestion(question.text)"
            >
              {{ question.text }}
            </button>
          </div>
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
              <!-- 停止/发送两个按钮原来只认聊天（sending）。正式复核跑起来时
                   sending 是 false：发送按钮不转圈、还能再点，也没有任何叫停的
                   入口——用户只能干等（实测反馈）。两条路径统一用 executionInFlight。 -->
              <ElButton
                v-if="executionInFlight"
                :loading="cancelling"
                @click="stopCurrentExecution"
              >
                {{ reviewStarting ? '停止复核' : '停止回答' }}
              </ElButton>
              <ElButton
                type="primary"
                :icon="Promotion"
                :loading="executionInFlight"
                :disabled="executionInFlight"
                @click="sendMessage()"
                >发送</ElButton
              >
            </div>
          </div>
        </section>

        <ElCollapse v-if="!props.embedded" v-model="tracePanels" class="trace-collapse">
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
        <button
          v-if="!props.embedded"
          type="button"
          class="sidebar-toggle is-right"
          :aria-label="sidebarLayout.rightLabel"
          :title="sidebarLayout.rightLabel"
          :aria-expanded="sidebarLayout.rightExpanded"
          aria-controls="review-context-panel-content"
          @click="rightSidebarCollapsed = !rightSidebarCollapsed"
        >
          <ElIcon>
            <ArrowRight v-if="sidebarLayout.rightExpanded" />
            <ArrowLeft v-else />
          </ElIcon>
        </button>
        <div
          v-show="props.embedded || sidebarLayout.rightExpanded"
          id="review-context-panel-content"
          class="sidebar-content context-panel-content"
        >
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
            <!-- 保存成功后，页面上必须留下痕迹。
                 实测：结论已写进库（OPN-6758E422），而界面上输入框原封不动、
                 任何地方都看不到刚保存的那条——监检只能再点一次。
                 同一节点因此攒下 3 条重复的「证据不足」。
                 数据本来就在 latestHumanDecision 里，只是从来没渲染过。 -->
            <div v-if="savedHumanDecision" class="saved-decision">
              <strong>已保存：{{ savedHumanDecision.result }}</strong>
              <small v-if="savedHumanDecision.savedAt">{{ savedHumanDecision.savedAt }}</small>
              <p v-if="savedHumanDecision.opinion">{{ savedHumanDecision.opinion }}</p>
            </div>
            <label>审查结论</label>
            <ElRadioGroup v-model="reviewResult" :disabled="!canSubmitReviewOpinion">
              <ElRadioButton value="满足要求">满足要求</ElRadioButton>
              <ElRadioButton value="需补正">需补正</ElRadioButton>
              <ElRadioButton value="不适用">不适用</ElRadioButton>
              <ElRadioButton value="证据不足">证据不足</ElRadioButton>
            </ElRadioGroup>
            <label>人工复核意见</label>
            <ElInput
              v-model="reviewOpinion"
              type="textarea"
              :rows="4"
              maxlength="2000"
              show-word-limit
              :disabled="!canSubmitReviewOpinion"
              placeholder="请输入人工复核意见"
            />
            <ElButton
              class="full-button"
              type="primary"
              :loading="actionLoading"
              :disabled="!canSubmitReviewOpinion"
              @click="handleSaveReviewOpinion"
            >
              保存人工复核结论
            </ElButton>
            <ElButton
              class="full-button"
              type="danger"
              plain
              :loading="actionLoading"
              :disabled="!canReturnCorrection"
              @click="returnCorrectionVisible = true"
            >
              退回补正
            </ElButton>
          </section>
        </div>
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
    <ReturnCorrectionDialog
      v-model="returnCorrectionVisible"
      :bindings="workspace?.returnableBindings || []"
      :missing-requirements="workspace?.evidenceReadiness.missingRequirements || []"
      :default-opinion="reviewOpinion"
      :loading="actionLoading"
      @submit="handleReturnCorrection"
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

/* 已保存的人工结论：绿色左条，一眼看出「这条已经存下了」 */
.saved-decision {
  padding: 8px 10px;
  margin-bottom: 10px;
  background: #f0f9f2;
  border-left: 3px solid #52a86a;
  border-radius: 6px;
}

.saved-decision strong {
  font-size: 13px;
  color: #1f6b3a;
}

.saved-decision small {
  margin-left: 8px;
  font-size: 12px;
  color: #667085;
}

.saved-decision p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #344054;
  word-break: break-word;
}

.review-user {
  display: flex;
  gap: 8px;
  align-items: center;
  /* 从 div 改成 button（要挂用户菜单），把浏览器默认按钮样式清掉，外观不变 */
  padding: 0;
  color: inherit;
  font-size: 13px;
  font-weight: 600;
  background: none;
  border: 0;
  cursor: pointer;
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
  transition: grid-template-columns 180ms ease;
}

.review-b-layout.is-left-collapsed {
  grid-template-columns: 28px minmax(650px, 1fr) 330px;
}

.review-b-layout.is-right-collapsed {
  grid-template-columns: minmax(300px, 404px) minmax(650px, 1fr) 28px;
}

.review-b-layout.is-left-collapsed.is-right-collapsed {
  grid-template-columns: 28px minmax(650px, 1fr) 28px;
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

.review-b-shell.is-embedded {
  display: flex;
  height: 100%;
  overflow: hidden;
  flex-direction: column;
}

.review-b-shell.is-embedded .review-b-layout {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  flex: 1;
}

.review-b-shell.is-embedded .conversation-column {
  display: grid;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.review-b-shell.is-embedded .conversation-timeline {
  max-height: none;
  min-height: 0;
}

.review-b-shell.is-embedded .context-panel {
  height: 100%;
  max-height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.node-sidebar,
.context-panel {
  position: sticky;
  top: 72px;
  align-self: start;
  height: calc(100vh - 72px);
  overflow: visible;
  background: #fff;
}

.node-sidebar {
  border-right: 1px solid var(--review-line);
}

.sidebar-content {
  height: 100%;
  overflow: auto;
}

.node-sidebar-content {
  padding: 18px 14px;
}

.sidebar-toggle {
  position: absolute;
  top: 16px;
  z-index: 5;
  display: grid;
  width: 32px;
  height: 32px;
  padding: 0;
  color: var(--review-blue);
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--review-line);
  border-radius: 50%;
  box-shadow: 0 4px 12px rgb(22 34 51 / 12%);
  transition:
    color 160ms ease,
    border-color 160ms ease,
    box-shadow 160ms ease;
  place-items: center;
}

.sidebar-toggle:hover,
.sidebar-toggle:focus-visible {
  color: #075bd8;
  border-color: #8bb6f4;
  outline: 0;
  box-shadow: 0 5px 16px rgb(20 104 232 / 20%);
}

.sidebar-toggle:focus-visible {
  box-shadow:
    0 0 0 3px rgb(20 104 232 / 18%),
    0 5px 16px rgb(20 104 232 / 20%);
}

.sidebar-toggle.is-left {
  right: 0;
  transform: translateX(50%);
}

.sidebar-toggle.is-right {
  left: 0;
  transform: translateX(-50%);
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

/* 推理过程：折叠态必须比结论轻。
   它是「需要时能查」的东西，不是要读的东西——做成和正文一样的分量，
   等于把上千字的自言自语重新摆回视线里。 */
.reasoning-block {
  margin: 6px 0 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.reasoning-summary {
  padding: 6px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.reasoning-summary::-webkit-details-marker {
  display: none;
}

.reasoning-summary::before {
  content: '▸';
  display: inline-block;
  margin-right: 6px;
  transition: transform 0.15s ease;
}

.reasoning-block[open] .reasoning-summary::before {
  transform: rotate(90deg);
}

.reasoning-summary:hover {
  color: var(--el-text-color-primary);
}

/* 展开后限高并可滚：推理动辄上千字，整段铺开会把下面的结论顶出屏幕，
   等于折叠了个寂寞。 */
.reasoning-text {
  max-height: 260px;
  margin: 0;
  padding: 0 10px 10px;
  overflow: auto;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
  word-break: break-word;
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
  padding: 0;
  margin: 6px 0 0;
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

/* 推荐问题：按当前节点卡点定制，点击填进输入框而不是直接发送。
   单行横向滚动——推荐最多 4 条，换行会把对话框顶高、挤掉消息区。
   滚动条隐藏——它出现在这么窄的一条上只是噪音，横向滚动靠触控板/滚轮即可。 */
.composer-suggestions {
  display: flex;

  /* min-width: 0 是这里的关键：flex 子项默认 min-width: auto，会被内容撑开，
     于是父容器跟着变宽、overflow-x 永远不触发。实测窄屏下对话卡被撑到 1182px
     而窗口只有 1000px——推荐条「能滚动」这件事从来没发生过。 */
  max-width: 100%;
  min-width: 0;
  margin-bottom: 8px;
  overflow-x: auto;
  gap: 6px;
  align-items: center;
  flex-wrap: nowrap;
  scrollbar-width: none;
}

.composer-suggestions::-webkit-scrollbar {
  display: none;
}

.composer-suggestions-label {
  font-size: 12px;
  color: #94a3b8;
  white-space: nowrap;
  flex: none;
}

.composer-suggestion {
  /* 不截断：既然已经横向滚动，再设 max-width + ellipsis 就是既滚又截——
     实测 4 条里 2 条被切掉后半句，而后半句往往才是限定条件
     （「…分别对应哪个审查点？」）。滚动是为了读全，不是为了少读。
     flex: none 是必须的：flex 默认收缩子项，会把所有按钮挤成一堆省略号。 */
  padding: 5px 12px;
  font: inherit;
  font-size: 12px;
  line-height: 1.5;
  color: #1d4ed8;
  white-space: nowrap;
  cursor: pointer;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  flex: none;
  transition:
    background 0.15s,
    border-color 0.15s,
    transform 0.1s;
}

.composer-suggestion:hover {
  background: #dbeafe;
  border-color: #93c5fd;
}

.composer-suggestion:active {
  transform: scale(0.97);
}

.composer-card {
  /* 不加约束时它会被内部最宽的子项撑开：实测 conversation-column 只有 270px，
     而这张卡撑到 1182px，直接溢出到父容器外面去。加推荐问题只是让这个既有
     缺陷显形——快捷命令那排按钮本来也在撑它，只是没人在窄屏下看过。 */
  max-width: 100%;
  min-width: 0;
  padding: 12px 14px 10px;
  background: #fff;
  border: 1px solid #dbe6f7;
  border-radius: 14px;
  /* 阴影收敛：原来 30px 的大扩散让这张卡在页面上「浮」得过重，
     压过了它上面的消息区——输入框是工具，不该比内容更显眼。 */
  box-shadow: 0 2px 12px rgb(20 104 232 / 6%);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

/* 聚焦时才强调：没在输入时它安静待着，光标进来才把注意力收过来 */
.composer-card:focus-within {
  border-color: #93c5fd;
  box-shadow: 0 2px 16px rgb(20 104 232 / 12%);
}

/* 输入框去掉自带边框，与卡片融为一体——两层框套着显得局促 */
.composer-card :deep(.el-textarea__inner) {
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.6;
  background: transparent;
  border: none;
  box-shadow: none;
}

.composer-card :deep(.el-textarea__inner::placeholder) {
  color: #b6c2d4;
}

/* 快捷命令是次要入口，不该与「发送」抢视觉重量 */
.composer-actions :deep(.el-button:not(.el-button--primary)) {
  color: #64748b;
  background: transparent;
  border-color: transparent;
}

.composer-actions :deep(.el-button:not(.el-button--primary):hover) {
  color: #1d4ed8;
  background: #f1f5f9;
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
  border-left: 1px solid var(--review-line);
}

.context-panel-content {
  padding: 18px 14px 28px;
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
  margin-left: 0;
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

  .review-b-layout.is-left-collapsed {
    grid-template-columns: 28px minmax(610px, 1fr) 302px;
  }

  .review-b-layout.is-right-collapsed {
    grid-template-columns: minmax(280px, 360px) minmax(610px, 1fr) 28px;
  }

  .review-b-layout.is-left-collapsed.is-right-collapsed {
    grid-template-columns: 28px minmax(610px, 1fr) 28px;
  }

  .brand {
    min-width: 240px;
  }

  .project-switcher {
    width: 240px;
  }
}
</style>
