<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCol,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElRow,
  ElSelect,
  ElSpace,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag
} from 'element-plus'
import {
  closeFdeIncidentApi,
  createFdeDataExportApi,
  createFdeEvaluationRunApi,
  createFdeMaskingPolicyApi,
  createFdeOcrCorrectionApi,
  createFdeOcrEvaluationRunApi,
  expireFdeDataExportApi,
  exportFdeOcrAnnotationLabelStudioApi,
  getFdeAiRunApi,
  getFdeAuditEventsApi,
  getFdeBusinessPackDiffApi,
  getFdeCapabilityBundlesApi,
  getFdeCapabilityBundleDiffApi,
  getFdeCostBudgetsApi,
  getFdeDashboardApi,
  getFdeEvaluationReportApi,
  getFdeEvaluationSetsApi,
  getFdeMaskingPoliciesApi,
  getFdeOcrAnnotationTaskApi,
  getFdeOcrRunApi,
  getFdeOcrQualityApi,
  getFdeProjectAuditWorkspaceApi,
  importFdeOcrAnnotationPackApi,
  getFdeReleaseImpactApi,
  getFdeReviewRunApi,
  installFdeBusinessPackApi,
  listFdeAcceptanceReportsApi,
  listFdeAccessGrantsApi,
  listFdeAiRunsApi,
  listFdeFeedbackApi,
  listFdeIncidentsApi,
  listFdeProjectsApi,
  listFdeOcrAnnotationTasksApi,
  listFdeOcrRunsApi,
  listFdeReviewRunsApi,
  listFdeReleasesApi,
  markFdeShadowPassedApi,
  proposeFdeCostBudgetChangeApi,
  requestFdeAccessGrantApi,
  reviewFdeOcrAnnotationTaskApi,
  replayFdeAiRunApi,
  replayFdeReviewRunApi,
  saveFdeOcrAnnotationLabelApi,
  shadowFdeReviewRunApi,
  startFdeShadowApi,
  submitFdeReleaseApi,
  triageFdeFeedbackApi,
  updateFdeIncidentRcaApi,
  validateFdeBusinessPacksApi,
  verifyFdeOcrAnnotationTaskApi
} from '@/api/aicheck'
import type {
  BusinessPackValidateAllPayload,
  FdeAccessPayload,
  FdeAiRun,
  FdeAiRunDetailPayload,
  FdeCapabilityBundlePayload,
  FdeDashboardPayload,
  FdeEvaluationReportPayload,
  FdeEvaluationPayload,
  FdeFeedback,
  FdeOcrAnnotationTask,
  FdeIncidentPayload,
  FdeOcrAnnotationPayload,
  FdeOcrEvalRun,
  FdeOcrQualityPayload,
  FdeOcrRunDetailPayload,
  FdeProjectAuditSummary,
  FdeProjectAuditWorkspace,
  FdeReviewRun,
  FdeReviewRunDetailPayload,
  FdeReleasePayload
} from '@/api/aicheck'
import StaticPageShell from './components/StaticPageShell.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const activeFdeTab = ref('dashboard')
const dashboard = ref<FdeDashboardPayload | null>(null)
const aiRuns = ref<FdeAiRun[]>([])
const selectedRun = ref<FdeAiRunDetailPayload | null>(null)
const reviewRuns = ref<FdeReviewRun[]>([])
const selectedReviewRun = ref<FdeReviewRunDetailPayload | null>(null)
const reviewAuditDrawerVisible = ref(false)
const feedback = ref<FdeFeedback[]>([])
const selectedFeedback = ref<FdeFeedback | null>(null)
const evaluation = ref<FdeEvaluationPayload | null>(null)
const selectedEvaluationReport = ref<FdeEvaluationReportPayload | null>(null)
const bundles = ref<FdeCapabilityBundlePayload | null>(null)
const selectedBundleId = ref('')
const releases = ref<FdeReleasePayload | null>(null)
const selectedReleaseId = ref('')
const ocrQuality = ref<FdeOcrQualityPayload | null>(null)
const ocrRuns = ref<Array<Record<string, unknown>>>([])
const selectedOcrRun = ref<FdeOcrRunDetailPayload | null>(null)
const ocrAuditDrawerVisible = ref(false)
const ocrAnnotation = ref<FdeOcrAnnotationPayload | null>(null)
const labelStudioExportSummary = ref<Record<string, unknown> | null>(null)
const annotationEditorVisible = ref(false)
const annotationDetailLoading = ref(false)
const selectedAnnotationTask = ref<FdeOcrAnnotationTask | null>(null)
const annotationDraft = ref<Record<string, unknown>>({
  qualityStatus: 'needs_human_review',
  fields: [],
  tables: [],
  seals: []
})
const annotationBoxType = ref<'fields' | 'tables' | 'seals'>('fields')
const annotationLabelValue = ref('')
const annotationLabeler = ref('人工标注员')
const annotationReviewer = ref('FDE 工程师')
const annotationBoxForm = ref({ pageNo: 1, x1: 10, y1: 10, x2: 180, y2: 80 })
const annotationSections = ['fields', 'tables', 'seals'] as const
type AnnotationSection = (typeof annotationSections)[number]
type AnnotationOverlayItem = Record<string, unknown> & {
  index: number
  type: AnnotationSection
  label: string
  bbox?: unknown
}
type FdeElTagType = 'success' | 'warning' | 'info' | 'primary' | 'danger'
type ProjectAuditSubpage =
  | 'overview'
  | 'vectorization'
  | 'pageindex'
  | 'langgraph'
  | 'ocr-labeling'
  | 'evaluation'
  | 'node'
  | 'submissions'
  | 'agent'
  | 'ocr'
  | 'quality'
type ProjectAuditTreeFilter =
  | 'all'
  | 'blocked'
  | 'vectorization'
  | 'pageindex'
  | 'langgraph'
  | 'ocr-labeling'
  | 'evaluation'
type AgentSubpage = 'runs' | 'reasoning' | 'quality' | 'trace'
type OcrSubpage = 'overview' | 'annotation' | 'runtime' | 'evaluation'
const fdeDemoMode = ref(false)
const projectAuditSubpage = ref<ProjectAuditSubpage>('overview')
const projectAuditSearch = ref('')
const projectAuditFilter = ref<ProjectAuditTreeFilter>('all')
const fdeProjects = ref<FdeProjectAuditSummary[]>([])
const fdeDemoProjectWorkspaces = ref<FdeProjectAuditWorkspace[]>([])
const selectedFdeProjectId = ref('')
const selectedFdeNodeId = ref<number | undefined>()
const projectAuditWorkspace = ref<FdeProjectAuditWorkspace | null>(null)
const agentSubpage = ref<AgentSubpage>('runs')
const ocrSubpage = ref<OcrSubpage>('overview')
const incidentPayload = ref<FdeIncidentPayload | null>(null)
const selectedIncidentId = ref('')
const accessGrants = ref<Array<Record<string, unknown>>>([])
const costGovernance = ref<FdeAccessPayload | null>(null)
const acceptanceReports = ref<Array<Record<string, unknown>>>([])
const packValidation = ref<BusinessPackValidateAllPayload | null>(null)
const selectedBusinessPackId = ref('')
const auditEvents = ref<Array<Record<string, unknown>>>([])
const maskingPolicies = ref<Array<Record<string, unknown>>>([])
const bundleDiff = ref<Record<string, unknown> | null>(null)
const releaseImpact = ref<Record<string, unknown> | null>(null)
const businessPackDiff = ref<Record<string, unknown> | null>(null)

type FdePageActionKey =
  | 'go-ocr-label'
  | 'start-ocr-evaluation'
  | 'triage-feedback'
  | 'start-evaluation'
  | 'replay-ai-run'
  | 'replay-review-run'
  | 'shadow-review-run'
  | 'submit-release'
  | 'install-business-pack'
  | 'create-mask-policy'
  | 'update-rca'
  | 'budget-change'

type FdePageAction = {
  key: FdePageActionKey
  label: string
  type?: 'primary' | 'success' | 'warning'
  plain?: boolean
  disabled?: boolean
}

type FdeShellMenuItemPayload = {
  projectId?: string
  subpage?: string
  route?: string
}

const routeTabMap: Record<string, string> = {
  projects: 'project-audit',
  dashboard: 'dashboard',
  'ai-runs': 'runs',
  'review-runs': 'orchestration',
  feedback: 'feedback',
  evaluation: 'feedback',
  'capability-bundles': 'release',
  releases: 'release',
  'ocr-quality': 'delivery',
  'business-packs': 'delivery',
  security: 'delivery',
  incidents: 'delivery',
  costs: 'delivery',
  acceptance: 'delivery'
}

const fdeTabRouteMap: Record<string, string> = {
  'project-audit': '/fde/projects',
  dashboard: '/fde/dashboard',
  runs: '/fde/ai-runs',
  orchestration: '/fde/review-runs',
  feedback: '/fde/feedback',
  release: '/fde/capability-bundles',
  delivery: '/fde/ocr-quality'
}

const fdeRouteMeta: Record<
  string,
  {
    group: string
    label: string
    badge: string
    tone: 'blue' | 'green' | 'orange' | 'red'
    title: string
    subtitle: string
    nextAction: string
    actions?: FdePageAction[]
  }
> = {
  projects: {
    group: '项目审计',
    label: '项目审计工作台',
    badge: '项目',
    tone: 'blue',
    title: '项目审计工作台',
    subtitle:
      '按审计项目、节点、资料批次组织 OCR 与 Agent 编排数据，先定位项目内阻断，再进入证据、结果和人工修正。',
    nextAction: '先选择项目和节点，再查看 OCR 标注、Agent 审查链和质量阻断。'
  },
  dashboard: {
    group: '总览',
    label: 'OCR 与 Agent 工作台',
    badge: '总览',
    tone: 'blue',
    title: 'OCR 与 Agent 编排工作台',
    subtitle: '当前 FDE 面板只保留 OCR 质量标注和 Agent 审查编排两个重点工作流。',
    nextAction: '优先进入 Agent 编排排查链路，或进入 OCR 标注补齐评估样本。'
  },
  'ai-runs': {
    group: '运行追踪',
    label: 'AI Run 追踪',
    badge: 'Trace',
    tone: 'blue',
    title: 'AI Run 追踪',
    subtitle: '查看不可变 AI Run、Trace、输入输出 hash、脱敏策略和诊断重跑。',
    nextAction: '先选中一条 Run，再查看 Trace 明细或发起诊断重跑。',
    actions: [{ key: 'replay-ai-run', label: '诊断重跑', plain: true }]
  },
  'review-runs': {
    group: '重点工作台',
    label: 'Agent 审查编排',
    badge: '链路',
    tone: 'green',
    title: 'Agent 审查编排',
    subtitle: '查看 Temporal 外层 Workflow、LangGraph 内层节点和审查产物。',
    nextAction: '先选中 ReviewRun，再检查 Workflow 时间线和校验失败。',
    actions: [
      { key: 'replay-review-run', label: '诊断重跑', plain: true },
      { key: 'shadow-review-run', label: 'Shadow', plain: true }
    ]
  },
  feedback: {
    group: '样本评估',
    label: '人工反馈与样本池',
    badge: '样本',
    tone: 'orange',
    title: '人工反馈与样本池',
    subtitle: '把人工接受、修改、驳回和漏检反馈归因，并沉淀为评估或训练样本。',
    nextAction: '优先处理 needs_triage 的反馈。',
    actions: [{ key: 'triage-feedback', label: '归因首条', plain: true }]
  },
  evaluation: {
    group: '样本评估',
    label: '评估实验室',
    badge: '门禁',
    tone: 'green',
    title: '评估实验室',
    subtitle: '管理评估集、回归集和发布前门禁，用样本验证 Agent、Prompt 和模型版本。',
    nextAction: '选择评估集后发起评测。',
    actions: [{ key: 'start-evaluation', label: '发起评测', plain: true }]
  },
  'ocr-quality': {
    group: '重点工作台',
    label: 'OCR 质量与标注',
    badge: '识别',
    tone: 'green',
    title: 'OCR 质量与人工标定',
    subtitle: '检查 OCR 质量、低置信字段、表格/印章问题，并人工标定可评估样本。',
    nextAction: '优先打开待标注样本，补齐字段、表格和印章 bbox。',
    actions: [
      { key: 'go-ocr-label', label: '打开待标注样本', type: 'primary' },
      { key: 'start-ocr-evaluation', label: 'OCR 评测', plain: true }
    ]
  },
  'capability-bundles': {
    group: '版本发布',
    label: '能力版本组合',
    badge: 'Bundle',
    tone: 'blue',
    title: '能力版本组合',
    subtitle: '管理 Agent、Prompt、模型路由、规则、知识库和 OCR Profile 的发布组合。',
    nextAction: '点击组合查看与生产基线的差异。'
  },
  releases: {
    group: '版本发布',
    label: '发布治理',
    badge: '灰度',
    tone: 'orange',
    title: '发布治理',
    subtitle: '发起发布门禁、Shadow、灰度和生产审批，控制高风险 AI 变更。',
    nextAction: '先提交门禁，再进入 Shadow 或灰度。',
    actions: [{ key: 'submit-release', label: '提交门禁', plain: true }]
  },
  'business-packs': {
    group: '交付运维',
    label: '业务包工厂',
    badge: '复用',
    tone: 'blue',
    title: '业务包工厂',
    subtitle: '校验业务包的角色、节点、资料目录、规则、知识库、模板和可迁移性。',
    nextAction: '先查看业务包门禁分段和阻断项。',
    actions: [{ key: 'install-business-pack', label: '安装演练', plain: true }]
  },
  security: {
    group: '交付运维',
    label: '数据安全',
    badge: '脱敏',
    tone: 'red',
    title: '数据安全与脱敏',
    subtitle: '管理 FDE 原文访问、数据导出、脱敏策略和访问审计。',
    nextAction: '优先确认导出申请和异常访问审计。',
    actions: [{ key: 'create-mask-policy', label: '新增脱敏策略', plain: true }]
  },
  incidents: {
    group: '交付运维',
    label: '事故复盘',
    badge: '处置',
    tone: 'orange',
    title: '事故复盘',
    subtitle: '跟踪 AI、OCR、知识库、成本和发布事故的影响范围、根因和整改。',
    nextAction: '选中事故后更新 RCA 或关闭已处理事故。',
    actions: [{ key: 'update-rca', label: '更新 RCA', plain: true }]
  },
  costs: {
    group: '交付运维',
    label: '成本预算',
    badge: '预算',
    tone: 'blue',
    title: '成本预算',
    subtitle: '查看租户、项目、模型和 Agent 成本，提交预算调整建议。',
    nextAction: '先查看变更申请和异常成本。',
    actions: [{ key: 'budget-change', label: '预算变更', plain: true }]
  },
  acceptance: {
    group: '交付运维',
    label: '客户验收',
    badge: '客户',
    tone: 'green',
    title: '客户验收',
    subtitle: '查看交付验收报告、验收样本、客户确认和未通过整改项。',
    nextAction: '优先查看未通过或待确认的验收报告。'
  }
}

const fdeShellBoundaryRows = [
  { label: '聚焦', value: '按审计项目组织 OCR 与 Agent 编排数据' },
  { label: '层级', value: '项目 → 节点 → 批次/资料 → OCR/Agent 任务' },
  { label: 'Agent', value: 'Temporal Workflow + LangGraph 节点追踪' },
  { label: '边界', value: 'FDE 只做 AI 诊断、标注和治理，不办理业务审批' }
] as const

const syncTabFromRoute = () => {
  activeFdeTab.value = routeTabMap[currentFdeRouteKey.value] || 'dashboard'
}

const currentFdeRouteKey = computed(() =>
  String(route.path.split('/').filter(Boolean).pop() || 'dashboard')
)

const isFdeRoute = (...keys: string[]) => keys.includes(currentFdeRouteKey.value)

const firstQueryValue = (value: unknown) => {
  if (Array.isArray(value)) return value[0] ? String(value[0]) : ''
  return value === undefined || value === null ? '' : String(value)
}

const parseProjectAuditSubpage = (value: unknown): ProjectAuditSubpage | undefined => {
  const raw = firstQueryValue(value)
  return projectAuditSubpageItems.value.some((item) => item.key === raw)
    ? (raw as ProjectAuditSubpage)
    : undefined
}

const parseProjectAuditNodeId = (value: unknown) => {
  const raw = firstQueryValue(value)
  if (!raw) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : undefined
}

const getProjectAuditRouteState = () => ({
  projectId: firstQueryValue(route.query.projectId),
  subpage: parseProjectAuditSubpage(route.query.view),
  nodeId: parseProjectAuditNodeId(route.query.nodeId)
})

const getAuditDetailRouteState = () => ({
  reviewRunId: firstQueryValue(route.query.reviewRunId),
  ocrJobId: firstQueryValue(route.query.ocrJobId)
})

const buildProjectAuditRouteQuery = (
  projectId = selectedFdeProjectId.value,
  nodeId = selectedFdeNodeId.value,
  subpage = projectAuditSubpage.value,
  detail: { reviewRunId?: string; ocrJobId?: string } = {}
) => {
  const query: Record<string, string> = {
    projectId,
    view: subpage
  }
  if (nodeId !== undefined) {
    query.nodeId = String(nodeId)
  }
  if (detail.reviewRunId) {
    query.reviewRunId = detail.reviewRunId
  }
  if (detail.ocrJobId) {
    query.ocrJobId = detail.ocrJobId
  }
  return query
}

const sameProjectAuditRouteQuery = (query: Record<string, string>) => {
  return (
    firstQueryValue(route.query.projectId) === query.projectId &&
    firstQueryValue(route.query.view) === query.view &&
    firstQueryValue(route.query.nodeId) === (query.nodeId || '') &&
    firstQueryValue(route.query.reviewRunId) === (query.reviewRunId || '') &&
    firstQueryValue(route.query.ocrJobId) === (query.ocrJobId || '')
  )
}

const syncProjectAuditRoute = async (
  projectId = selectedFdeProjectId.value,
  nodeId = selectedFdeNodeId.value,
  subpage = projectAuditSubpage.value,
  replace = false,
  detail: { reviewRunId?: string; ocrJobId?: string } = {}
) => {
  if (!projectId) return
  const query = buildProjectAuditRouteQuery(projectId, nodeId, subpage, detail)
  if (route.path === '/fde/projects' && sameProjectAuditRouteQuery(query)) return
  await router[replace ? 'replace' : 'push']({
    path: '/fde/projects',
    query
  })
}

const buildCurrentStringQuery = () => {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(route.query)) {
    const stringValue = firstQueryValue(value)
    if (stringValue) {
      query[key] = stringValue
    }
  }
  return query
}

const syncAuditDetailRoute = async (detail: { reviewRunId?: string; ocrJobId?: string }) => {
  const query = buildCurrentStringQuery()
  delete query.reviewRunId
  delete query.ocrJobId
  if (detail.reviewRunId) {
    query.reviewRunId = detail.reviewRunId
  }
  if (detail.ocrJobId) {
    query.ocrJobId = detail.ocrJobId
  }
  if (route.path === '/fde/projects' && selectedFdeProjectId.value) {
    Object.assign(
      query,
      buildProjectAuditRouteQuery(selectedFdeProjectId.value, selectedFdeNodeId.value)
    )
    if (detail.reviewRunId) {
      query.reviewRunId = detail.reviewRunId
    }
    if (detail.ocrJobId) {
      query.ocrJobId = detail.ocrJobId
    }
  }
  if (
    firstQueryValue(route.query.reviewRunId) === (query.reviewRunId || '') &&
    firstQueryValue(route.query.ocrJobId) === (query.ocrJobId || '')
  ) {
    return
  }
  await router.push({ path: route.path, query })
}

const clearAuditDetailRoute = async (detailKey: 'reviewRunId' | 'ocrJobId') => {
  if (!firstQueryValue(route.query[detailKey])) return
  const query = buildCurrentStringQuery()
  delete query[detailKey]
  await router.replace({ path: route.path, query })
}

const rawProjectAuditMenuProjects = computed<FdeProjectAuditSummary[]>(() =>
  fdeProjects.value.length || !projectAuditWorkspace.value
    ? fdeProjects.value
    : [
        {
          project: projectAuditWorkspace.value.project,
          metrics: projectAuditWorkspace.value.metrics,
          currentNodeId: projectAuditWorkspace.value.selectedNodeId,
          currentNodeName: projectAuditWorkspace.value.selectedNode?.name,
          topBlockers: projectAuditWorkspace.value.qualityBlockers,
          updatedAt: projectAuditWorkspace.value.updatedAt
        } as FdeProjectAuditSummary
      ]
)

const matchesProjectAuditSearch = (item: FdeProjectAuditSummary) => {
  const keyword = projectAuditSearch.value.trim().toLowerCase()
  if (!keyword) return true
  return [
    item.project.name,
    item.project.code,
    item.project.type,
    item.project.region,
    item.project.businessPackId,
    item.currentNodeName
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(keyword))
}

const matchesProjectAuditFilter = (item: FdeProjectAuditSummary) => {
  const metrics = item.metrics || {}
  const blockerCount = Number(metrics.blockers || item.topBlockers?.length || 0)
  if (projectAuditFilter.value === 'blocked') return blockerCount > 0
  if (projectAuditFilter.value === 'vectorization') return Number(metrics.documents || 0) > 0
  if (projectAuditFilter.value === 'pageindex') return Number(metrics.reviewRuns || 0) > 0
  if (projectAuditFilter.value === 'langgraph') return Number(metrics.reviewRuns || 0) > 0
  if (projectAuditFilter.value === 'ocr-labeling') {
    return Number(metrics.annotationTasks || metrics.ocrJobs || 0) > 0
  }
  if (projectAuditFilter.value === 'evaluation') {
    return blockerCount > 0 || Number(metrics.reviewRuns || metrics.ocrJobs || 0) > 0
  }
  return true
}

const filteredProjectAuditMenuProjects = computed(() =>
  rawProjectAuditMenuProjects.value.filter(
    (item) => matchesProjectAuditSearch(item) && matchesProjectAuditFilter(item)
  )
)

const projectAuditMenuFilterOptions = computed(() => {
  const projects = rawProjectAuditMenuProjects.value
  const blocked = projects.filter((item) => {
    const metrics = item.metrics || {}
    return Number(metrics.blockers || item.topBlockers?.length || 0) > 0
  }).length
  const vectorization = projects.filter(
    (item) => Number((item.metrics || {}).documents || 0) > 0
  ).length
  const pageIndex = projects.filter(
    (item) => Number((item.metrics || {}).reviewRuns || 0) > 0
  ).length
  const langGraph = projects.filter(
    (item) => Number((item.metrics || {}).reviewRuns || 0) > 0
  ).length
  const ocrLabeling = projects.filter(
    (item) => Number((item.metrics || {}).annotationTasks || (item.metrics || {}).ocrJobs || 0) > 0
  ).length
  const evaluationReady = projects.filter((item) => {
    const metrics = item.metrics || {}
    return (
      Number(metrics.blockers || item.topBlockers?.length || 0) > 0 ||
      Number(metrics.reviewRuns || metrics.ocrJobs || 0) > 0
    )
  }).length
  return [
    { label: '全部', value: 'all', count: projects.length },
    { label: '有阻断', value: 'blocked', count: blocked },
    { label: '向量化', value: 'vectorization', count: vectorization },
    { label: 'PageIndex', value: 'pageindex', count: pageIndex },
    { label: 'LangGraph', value: 'langgraph', count: langGraph },
    { label: 'OCR打标', value: 'ocr-labeling', count: ocrLabeling },
    { label: '评估', value: 'evaluation', count: evaluationReady }
  ]
})

const projectAuditMenuEmptyText = computed(() => {
  const keyword = projectAuditSearch.value.trim()
  if (keyword) return `没有找到“${keyword}”相关项目`
  if (projectAuditFilter.value === 'blocked') return '当前没有质量阻断项目'
  if (projectAuditFilter.value === 'vectorization') return '当前没有可向量化资料'
  if (projectAuditFilter.value === 'pageindex') return '当前没有 PageIndex 审计项目'
  if (projectAuditFilter.value === 'langgraph') return '当前没有 LangGraph 编排项目'
  if (projectAuditFilter.value === 'ocr-labeling') return '当前没有 OCR 打标样本'
  if (projectAuditFilter.value === 'evaluation') return '当前没有可评估项目'
  return '当前没有可审计项目'
})

const setProjectAuditSearch = (value: string) => {
  projectAuditSearch.value = value
}

const setProjectAuditFilter = (value: string) => {
  if (
    [
      'all',
      'blocked',
      'vectorization',
      'pageindex',
      'langgraph',
      'ocr-labeling',
      'evaluation'
    ].includes(value)
  ) {
    projectAuditFilter.value = value as ProjectAuditTreeFilter
  }
}

const projectAuditMenuItemHint = (
  subpage: ProjectAuditSubpage,
  metrics: Record<string, unknown>,
  blockerCount: number,
  currentNodeName?: string
) => {
  if (subpage === 'overview')
    return `节点：${shortText(currentNodeName, '未选')} · 阻断 ${blockerCount}`
  if (subpage === 'vectorization') {
    return `资料 ${Number(metrics.documents || 0)} · 向量 ${Number(metrics.knowledgeVectors || 0)}`
  }
  if (subpage === 'pageindex') {
    return `PI节点 ${Number(metrics.pageIndexNodes || 0)} · ReviewRun ${Number(metrics.reviewRuns || 0)}`
  }
  if (subpage === 'langgraph') {
    return `ReviewRun ${Number(metrics.reviewRuns || 0)} · Agent链路`
  }
  if (subpage === 'ocr-labeling') {
    return `OCR ${Number(metrics.ocrJobs || 0)} · 样本 ${Number(metrics.annotationTasks || 0)}`
  }
  if (subpage === 'evaluation') {
    return `阻断 ${blockerCount} · 低置信 ${Number(metrics.lowConfidenceFields || 0)}`
  }
  return ''
}

const fdeShellMenuSections = computed(() => {
  const projects = filteredProjectAuditMenuProjects.value

  if (!projects.length) {
    return []
  }

  return projects.map((item) => {
    const metrics = item.metrics || {}
    const blockerCount = Number(metrics.blockers || item.topBlockers?.length || 0)
    return {
      id: `project-${item.project.id}`,
      title: item.project.name,
      meta: friendlyStatus(item.project.status),
      chips: [
        {
          label: '资料',
          value: Number(metrics.documents || 0),
          tone: 'green' as const
        },
        {
          label: 'PI',
          value: Number(metrics.pageIndexNodes || 0),
          tone: Number(metrics.pageIndexNodes || 0) ? ('green' as const) : ('orange' as const)
        },
        {
          label: '阻断',
          value: blockerCount,
          tone: blockerCount ? ('red' as const) : ('green' as const)
        }
      ],
      items: projectAuditSubpageItems.value.map((subpage, subpageIndex) => {
        const isActive =
          selectedFdeProjectId.value === item.project.id &&
          projectAuditSubpage.value === subpage.key
        return {
          index: String(subpageIndex + 1).padStart(2, '0'),
          label: subpage.label,
          hint: isActive
            ? projectAuditMenuItemHint(subpage.key, metrics, blockerCount, item.currentNodeName)
            : '',
          badge: isActive ? '当前' : undefined,
          tone:
            subpage.key === 'evaluation' && blockerCount
              ? ('red' as const)
              : subpage.key === 'ocr-labeling'
                ? ('orange' as const)
                : subpage.key === 'langgraph'
                  ? ('green' as const)
                  : ('blue' as const),
          projectId: item.project.id,
          subpage: subpage.key,
          active: isActive
        }
      })
    }
  })
})
const currentFdeRouteContext = computed(() => {
  return fdeRouteMeta[currentFdeRouteKey.value] || fdeRouteMeta.dashboard
})
const currentFdePageActions = computed(() => currentFdeRouteContext.value.actions || [])
const fdeTagType = (tone: string): FdeElTagType => {
  if (tone === 'red') return 'danger'
  if (tone === 'green') return 'success'
  if (tone === 'orange') return 'warning'
  return 'info'
}

const percent = (value?: number | string) => {
  const numeric = Number(value || 0)
  if (Number.isNaN(numeric)) return value || '-'
  return `${Math.round(numeric * 100)}%`
}

const scorePercent = (value?: number | string) => {
  const numeric = Number(value ?? 0)
  if (Number.isNaN(numeric)) return '-'
  return `${Math.round(numeric * 1000) / 10}%`
}

const shortText = (value: unknown, fallback = '-') => {
  if (value === undefined || value === null || value === '') return fallback
  if (Array.isArray(value)) {
    return value.length
      ? value
          .map((item) => shortText(item, ''))
          .filter(Boolean)
          .join('；')
      : fallback
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

const statusLabelMap: Record<string, string> = {
  active: '启用',
  accepted: '已接受',
  blocked_by_gate: '门禁阻断',
  cancelled: '已取消',
  completed: '已完成',
  degraded: '降级运行',
  draft: '草稿',
  draft_persisted: '草稿已保存',
  failed: '失败',
  fail: '未通过',
  labeled: '待二审',
  monitoring: '监控中',
  needs_human_review: '需人工复核',
  needs_labeling: '待标注',
  needs_triage: '待归因',
  normal: '正常',
  over_budget: '超预算',
  pass: '通过',
  passed: '通过',
  production: '生产中',
  production_approved: '生产已批准',
  queued: '排队中',
  ready_for_eval: '可入评估',
  rejected: '已驳回',
  request_correction: '建议发起补正',
  reviewed: '已复核',
  running: '运行中',
  submitted: '已提交',
  success: '成功',
  triaged: '已归因',
  approved_for_eval: '已准入评估集',
  unknown: '未知',
  hybrid_rag: 'Hybrid RAG',
  pageindex: 'PageIndex',
  pageindex_tree_search: 'PageIndex 树检索',
  vector_search: '向量检索',
  review_basis_search: '审查依据检索',
  long_document_cross_section: '长文档跨章节检索',
  shadow: '影子运行',
  waiting_human_review: '待人工复核',
  warning: '告警'
}

const friendlyStatus = (status: unknown, fallback = '-') => {
  const raw = String(status || '').trim()
  if (!raw) return fallback
  return statusLabelMap[raw] || raw
}

const techLabelMap: Record<string, string> = {
  evidence_validation: '证据校验',
  field_inconsistent: '字段不一致',
  field_missing: '字段缺失',
  load_document_context: '加载资料上下文',
  load_ocr_result: '读取 OCR 结果',
  llm_generate_findings: 'LLM 生成审查草稿',
  quality_gate: '质量门禁',
  retrieve_knowledge: '检索知识依据',
  run_rule_checks: '执行规则检查',
  waiting_human_review: '等待人工复核',
  hybrid_rag: 'Hybrid RAG',
  pageindex: 'PageIndex',
  pageindex_tree_search: 'PageIndex 树检索',
  vector_search: '向量检索',
  review_basis_search: '审查依据检索',
  long_document_cross_section: '长文档跨章节检索'
}

const friendlyTechLabel = (value: unknown, fallback = '-') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  return techLabelMap[raw] || statusLabelMap[raw] || raw
}

const statusType = (status?: string) => {
  if (!status) return 'info'
  const normalized = String(status)
  if (
    [
      '完成',
      'completed',
      'pass',
      'production',
      'production_approved',
      'accepted',
      'active',
      'passed',
      'ready_for_eval',
      'reviewed',
      'success',
      'triaged',
      'approved_for_eval',
      'draft_persisted'
    ].includes(normalized)
  ) {
    return 'success'
  }
  if (['失败', 'failed', 'fail', 'blocked_by_gate', 'rejected'].includes(normalized)) {
    return 'danger'
  }
  if (
    [
      'queued',
      'submitted',
      'monitoring',
      'running',
      'degraded',
      'waiting_human_review',
      'needs_human_review',
      'needs_labeling',
      'labeled',
      'needs_triage',
      '排队中'
    ].includes(normalized)
  ) {
    return 'warning'
  }
  return 'info'
}

const recordNumber = (record: Record<string, unknown> | undefined, key: string) => {
  const value = Number(record?.[key] || 0)
  return Number.isNaN(value) ? 0 : value
}

const toRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

const toRecordArray = (value: unknown): Array<Record<string, unknown>> =>
  Array.isArray(value) ? (value as Array<Record<string, unknown>>) : []

const nodeArtifactCount = (row: Record<string, unknown>, key: string) =>
  recordNumber(row.artifactCounts as Record<string, unknown> | undefined, key)

const firstEvaluationSetId = computed(() => String(evaluation.value?.sets?.[0]?.id || ''))
const firstEvaluationRunId = computed(() =>
  String(evaluation.value?.runs?.[0]?.id || evaluation.value?.reports?.[0]?.evaluationRunId || '')
)
const firstBundleId = computed(() => String(bundles.value?.bundles?.[0]?.id || ''))
const firstRunId = computed(() => String(aiRuns.value[0]?.id || ''))
const firstReviewRunId = computed(() =>
  String(reviewRuns.value[0]?.reviewRunId || reviewRuns.value[0]?.id || '')
)
const firstReportId = computed(() => String(evaluation.value?.reports?.[0]?.id || ''))
const firstReleaseId = computed(() => String(releases.value?.plans?.[0]?.id || ''))
const firstPackId = computed(() => String(packValidation.value?.results?.[0]?.summary?.id || ''))
const firstOcrJobId = computed(() => String(ocrRuns.value[0]?.id || ocrRuns.value[0]?.jobId || ''))
const activeRunId = computed(() => String(selectedRun.value?.run?.id || firstRunId.value || ''))
const activeReviewRunId = computed(() =>
  String(
    selectedReviewRun.value?.run?.reviewRunId ||
      selectedReviewRun.value?.run?.id ||
      firstReviewRunId.value ||
      ''
  )
)
const activeFeedbackId = computed(() =>
  String(selectedFeedback.value?.id || feedback.value[0]?.id || '')
)
const activeReleaseId = computed(() => selectedReleaseId.value || firstReleaseId.value)
const activeBundleId = computed(() => selectedBundleId.value || firstBundleId.value)
const activeBusinessPackId = computed(() => selectedBusinessPackId.value || firstPackId.value)
const firstDataExportId = computed(() => String(costGovernance.value?.exports?.[0]?.id || ''))
const firstBudgetId = computed(() => String(costGovernance.value?.budgets?.[0]?.id || ''))
const firstLowConfidenceField = computed(() => ocrQuality.value?.lowConfidenceFields?.[0])
const ocrRuntimeDoctor = computed(() => ocrQuality.value?.runtimeDoctor || null)
const firstRuntimeIssue = computed(() => ocrRuntimeDoctor.value?.topIssues?.[0] || null)
const ocr100Scorecard = computed(() => ocrQuality.value?.ocr100Scorecard || null)
const ocr100SectionRows = computed(() => ocr100Scorecard.value?.sections || [])
const ocr100BlockerRows = computed(() =>
  (ocr100Scorecard.value?.blockers || []).slice(0, 8).map((blocker, index) => ({
    id: index + 1,
    blocker
  }))
)
const ocrAnnotationSummary = computed(() => ocrAnnotation.value?.summary || null)
const ocrAnnotationRows = computed(() => ocrAnnotation.value?.page.items || [])
const ocrAnnotationBlockerRows = computed(() =>
  Object.entries(ocrAnnotationSummary.value?.blockerCounts || {}).map(([blocker, count]) => ({
    blocker,
    count
  }))
)
const firstOcrAnnotationTaskId = computed(() =>
  String(ocrAnnotationRows.value[0]?.taskId || ocrAnnotationRows.value[0]?.caseId || '')
)
const annotationItems = (section: AnnotationSection) => {
  const value = annotationDraft.value[section]
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : []
}
const annotationSectionTitle = (section: AnnotationSection) =>
  section === 'fields' ? '字段' : section === 'tables' ? '表格' : '印章'
const annotationFields = computed(() => annotationItems('fields'))
const annotationTables = computed(() => annotationItems('tables'))
const annotationSeals = computed(() => annotationItems('seals'))
const annotationPageSize = computed(() => {
  const rawDimensions = selectedAnnotationTask.value?.pageDimensions || {}
  const pageNo = String(annotationBoxForm.value.pageNo || selectedAnnotationTask.value?.pageNo || 1)
  const dimensions = rawDimensions[pageNo] || rawDimensions['1'] || [2000, 1500]
  const width = Number(dimensions[0] || 2000)
  const height = Number(dimensions[1] || 1500)
  return {
    width: Number.isFinite(width) && width > 0 ? width : 2000,
    height: Number.isFinite(height) && height > 0 ? height : 1500
  }
})
const annotationOverlayItems = computed<AnnotationOverlayItem[]>(() => [
  ...annotationFields.value.map((item, index) => ({
    ...item,
    index,
    type: 'fields' as const,
    label: String(item.fieldCode || '字段')
  })),
  ...annotationTables.value.map((item, index) => ({
    ...item,
    index,
    type: 'tables' as const,
    label: String(item.businessSchema || '表格')
  })),
  ...annotationSeals.value.map((item, index) => ({
    ...item,
    index,
    type: 'seals' as const,
    label: String(item.nameContains || item.sealType || '印章')
  }))
])
const selectedOcrResultSummary = computed(
  () => (selectedOcrRun.value?.job?.resultSummary || {}) as Record<string, unknown>
)
const selectedOcrPreprocessStatus = computed(
  () => (selectedOcrRun.value?.parseResult?.preprocessStatus || {}) as Record<string, unknown>
)
const selectedOcrRequestedVariants = computed(
  () => (selectedOcrPreprocessStatus.value.requestedVariants || []) as string[]
)
const selectedOcrGeneratedVariants = computed(
  () => (selectedOcrPreprocessStatus.value.generatedVariants || []) as string[]
)
const selectedOcrMissingVariants = computed(
  () => (selectedOcrPreprocessStatus.value.missingVariants || []) as string[]
)
const selectedOcrEngineRows = computed(
  () =>
    (selectedOcrRun.value?.parseResult?.engineRuns ||
      selectedOcrRun.value?.job?.engineRuns ||
      []) as Array<Record<string, unknown>>
)
const selectedOcrDiagnosticRows = computed(
  () => (selectedOcrRun.value?.parseResult?.diagnostics || []) as Array<Record<string, unknown>>
)
const selectedOcrCorrectionRows = computed(() => selectedOcrRun.value?.corrections || [])
const ocrFieldFailureRows = computed(
  () =>
    (ocrQuality.value?.failurePools?.fieldFailures || [])
      .slice(0, 8)
      .map((item) =>
        typeof item === 'string' ? { code: item, source: 'diagnostic' } : item
      ) as Array<Record<string, unknown>>
)
const ocrMissingEvidenceRows = computed(() =>
  (ocrQuality.value?.evidenceLevel?.missingEvidenceItems || []).slice(0, 8)
)
const topOcrQualityReason = computed(() => ocrQuality.value?.qualityReasonCounts?.[0] || null)
const topOcrFieldCode = computed(
  () => ocrQuality.value?.fieldLevel?.fieldCodeBreakdown?.[0] || null
)
const topOcrFieldFlag = computed(() => ocrQuality.value?.fieldLevel?.qualityFlagCounts?.[0] || null)
const topMissingRequiredField = computed(
  () => ocrQuality.value?.fieldLevel?.missingRequiredFieldBreakdown?.[0] || null
)
const topMissingRequiredTable = computed(
  () => ocrQuality.value?.tableLevel?.missingRequiredTableBreakdown?.[0] || null
)
const topMatchedExpectedSealType = computed(
  () => ocrQuality.value?.sealLevel?.matchedExpectedSealTypeBreakdown?.[0] || null
)
const topMissingExpectedSealType = computed(
  () => ocrQuality.value?.sealLevel?.missingExpectedSealTypeBreakdown?.[0] || null
)
const latestOcrEvalRun = computed<FdeOcrEvalRun | null>(
  () => ocrQuality.value?.evalRuns?.[0] || null
)
const latestOcrEvalReport = computed(() => latestOcrEvalRun.value?.evaluationReport || null)
const latestOcrEvalCompact = computed(() => latestOcrEvalRun.value?.evaluationSummary || null)
const latestOcrEvalSummary = computed(
  () => latestOcrEvalCompact.value?.summary || latestOcrEvalReport.value?.summary || {}
)
const latestOcrEvalCaseTotal = computed(
  () =>
    latestOcrEvalSummary.value.total ||
    latestOcrEvalSummary.value.cases ||
    Number(latestOcrEvalRun.value?.metrics?.caseCount || 0)
)
const latestOcrEvalOk = computed(
  () => latestOcrEvalCompact.value?.ok ?? latestOcrEvalReport.value?.ok ?? false
)
const latestOcrScenarioMetrics = computed(
  () => latestOcrEvalCompact.value?.scenarioMetrics || latestOcrEvalRun.value?.scenarioMetrics || {}
)
const ocrScenarioRows = computed(() =>
  Object.entries(latestOcrScenarioMetrics.value).map(([scenario, item]) => {
    const summary = 'summary' in item && item.summary ? item.summary : item
    return {
      scenario,
      ok: Boolean(item?.ok),
      total: summary?.total || summary?.cases || 0,
      passed: summary?.passed || 0,
      failed: summary?.failed || 0,
      averageScore: summary?.averageScore || 0,
      thresholdFailureCount: item?.thresholdFailures?.length || 0
    }
  })
)
const ocrThresholdFailureRows = computed(() => {
  const rows: Array<Record<string, unknown>> = []
  for (const item of latestOcrEvalCompact.value?.thresholdFailures ||
    latestOcrEvalReport.value?.thresholdFailures ||
    []) {
    rows.push({ scope: 'overall', ...item })
  }
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const failure of item?.thresholdFailures || []) {
      rows.push({ scope: scenario, ...failure })
    }
  }
  return rows
})
const ocrFindingCountRows = computed(() => {
  const rows: Array<{ scope: string; code: string; count: number }> = Object.entries(
    latestOcrEvalCompact.value?.findingCounts || latestOcrEvalReport.value?.findingCounts || {}
  ).map(([code, count]) => ({
    scope: 'overall',
    code,
    count: Number(count || 0)
  }))
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const [code, count] of Object.entries(item?.findingCounts || {})) {
      rows.push({ scope: scenario, code, count: Number(count || 0) })
    }
  }
  return rows.sort((left, right) => Number(right.count || 0) - Number(left.count || 0)).slice(0, 8)
})
const failedOcrCaseRows = computed(() =>
  (
    latestOcrEvalCompact.value?.failedCases ||
    (latestOcrEvalRun.value?.caseDiagnostics || []).filter(
      (item) => item.passed === false || Boolean(item.findings?.length)
    )
  )
    .slice(0, 8)
    .map((item) => {
      const firstFinding = item.findings?.[0]
      return {
        caseId: item.caseId,
        scenario: item.scenario,
        score: item.score || 0,
        finding:
          typeof firstFinding === 'string'
            ? firstFinding
            : String(firstFinding?.code || firstFinding?.message || '-')
      }
    })
)
const incidents = computed(() => incidentPayload.value?.incidents || [])
const rcaItems = computed(() => incidentPayload.value?.rca || [])
const activeIncidentId = computed(
  () => selectedIncidentId.value || String(incidents.value[0]?.id || '')
)
const bundleDiffRows = computed(
  () =>
    ((bundleDiff.value?.diff as Record<string, unknown> | undefined)?.changes || []) as Array<
      Record<string, unknown>
    >
)
const businessPackDiffRows = computed(
  () =>
    ((businessPackDiff.value?.diff as Record<string, unknown> | undefined)?.changes || []) as Array<
      Record<string, unknown>
    >
)
const releaseImpactSummary = computed(() => releaseImpact.value || {})
const releaseGateBlockers = computed(
  () =>
    ((releaseImpactSummary.value.gateSummary as Record<string, unknown> | undefined)?.blocked ||
      []) as string[]
)
const costChangeRequests = computed(() => costGovernance.value?.changeRequests || [])
const latestEvaluationReport = computed(
  () => selectedEvaluationReport.value?.report || evaluation.value?.reports?.[0] || null
)
const latestEvaluationCaseSummary = computed(
  () =>
    (latestEvaluationReport.value?.caseSummary || {}) as Record<string, number | string | boolean>
)
const evaluationCaseRows = computed(
  () =>
    selectedEvaluationReport.value?.caseResults || latestEvaluationReport.value?.caseResults || []
)
const failedEvaluationCaseRows = computed(() =>
  evaluationCaseRows.value.filter((item) => item.status !== 'passed').slice(0, 8)
)
const selectedReviewGraph = computed(() => selectedReviewRun.value?.graph || null)
const reviewGraphNodes = computed(() => selectedReviewGraph.value?.nodes || [])
const reviewGraphTimeline = computed(
  () => selectedReviewRun.value?.timeline || selectedReviewGraph.value?.timeline || []
)
const reviewGraphEdges = computed(() => selectedReviewGraph.value?.edges || [])
const selectedReviewTemporal = computed(() => selectedReviewRun.value?.temporal || {})
const reviewScorecard = computed(() => selectedReviewRun.value?.scorecard || null)
const reviewScorecardSections = computed(() => reviewScorecard.value?.sections || [])
const reviewScorecardBlockerRows = computed(() =>
  (reviewScorecard.value?.blockers || []).slice(0, 8).map((blocker, index) => ({
    id: index + 1,
    blocker
  }))
)
const reviewArtifactSummary = computed(() => selectedReviewGraph.value?.artifactSummary || {})
const reviewGraphArtifacts = computed(() => selectedReviewGraph.value?.artifacts || {})
const reviewRuleResultRows = computed(() => reviewGraphArtifacts.value.ruleCheckResults || [])
const reviewRetrievalTraceRows = computed(() => reviewGraphArtifacts.value.retrievalTraces || [])
const reviewFindingDraftRows = computed(() => {
  const runDrafts = toRecordArray(toRecord(selectedReviewRun.value?.run).findingDrafts)
  return runDrafts.length ? runDrafts : reviewGraphArtifacts.value.findingDrafts || []
})
const reviewReasoningTraceRows = computed(() => selectedReviewRun.value?.reasoningTrace || [])
const normalizedReviewReasoningRows = computed(() =>
  reviewReasoningTraceRows.value.map((row, index) => {
    const item = toRecord(row)
    const quality = toRecord(item.quality)
    const toolCalls = toRecordArray(item.toolCalls)
    const evidenceRefs = toRecordArray(item.evidenceRefs)
    const ruleRefs = toRecordArray(item.ruleRefs)
    const kbRefs = toRecordArray(item.kbRefs)
    const evidenceRefText = evidenceRefs
      .map((ref) => {
        const evidence = toRecord(ref)
        return [
          evidence.documentVersionId || evidence.documentId || evidence.fileName || evidence.source,
          evidence.pageNo ? `P${evidence.pageNo}` : '',
          evidence.bbox ? 'bbox' : ''
        ]
          .filter(Boolean)
          .join('@')
      })
      .filter(Boolean)
      .join('；')
    const ruleRefText = ruleRefs
      .map((ref) => {
        const rule = toRecord(ref)
        return rule.ruleCode || rule.code || rule.id
      })
      .filter(Boolean)
      .join('；')
    const kbRefText = kbRefs
      .map((ref) => {
        const clause = toRecord(ref)
        return clause.clauseId || clause.clause || clause.id
      })
      .filter(Boolean)
      .join('；')
    const rawEvidenceText = shortText(item.evidence, '')
    const evidenceText =
      rawEvidenceText ||
      [evidenceRefText, ruleRefText, kbRefText].filter(Boolean).join(' / ') ||
      '-'
    const qualityText =
      typeof item.quality === 'string'
        ? item.quality
        : quality.passed === true
          ? '通过'
          : quality.passed === false
            ? '需复核'
            : shortText(item.quality, '-')
    return {
      sequence: Number(item.sequence || index + 1),
      stepName: item.stepName || item.step || item.nodeKey || `步骤 ${index + 1}`,
      reasoningSummary:
        item.reasoningSummary || item.thought || item.summary || item.message || '-',
      evidence: evidenceText,
      toolCount: toolCalls.length,
      toolNames: toolCalls
        .map((tool) => tool.toolName || tool.name)
        .filter(Boolean)
        .join('，'),
      evidenceCount: evidenceRefs.length || (rawEvidenceText ? 1 : 0),
      ruleCount: ruleRefs.length || (typeof item.ruleRefs === 'string' && item.ruleRefs ? 1 : 0),
      kbCount: kbRefs.length || (typeof item.kbRefs === 'string' && item.kbRefs ? 1 : 0),
      qualityText,
      qualityPassed: quality.passed === true || String(item.quality || '').includes('可追溯')
    }
  })
)
const normalizedReviewFindingRows = computed(() =>
  reviewFindingDraftRows.value.map((row, index) => {
    const item = toRecord(row)
    return {
      id: item.id || `finding-${index + 1}`,
      findingType: item.findingType || item.type || '-',
      severity: item.severity || '-',
      title: item.title || item.description || item.finding || '-',
      confidence: item.confidence,
      evidenceCount: toRecordArray(item.evidenceRefs).length,
      referenceCount: toRecordArray(item.ruleRefs).length + toRecordArray(item.kbRefs).length,
      requiresHumanConfirmation: Boolean(item.requiresHumanConfirmation),
      suggestedAction: item.suggestedAction || '-'
    }
  })
)
const normalizedReviewQualityRows = computed(() =>
  (reviewQualityRows.value.length ? reviewQualityRows.value : reviewQualityGateRows.value).map(
    (row, index) => {
      const item = toRecord(row)
      return {
        id: item.name || item.dimension || item.gate || `quality-${index + 1}`,
        name: item.name || item.dimension || item.gate || `质量项 ${index + 1}`,
        status:
          item.status || (item.passed === true ? 'pass' : item.passed === false ? 'warning' : '-'),
        score: item.score,
        message: item.message || item.finding || item.description || '-',
        failureCount: item.failureCount,
        warningCount: item.warningCount
      }
    }
  )
)
const normalizedReviewHumanCorrectionRows = computed(() =>
  reviewHumanCorrectionRows.value.map((row, index) => {
    const item = toRecord(row)
    return {
      id: item.id || `correction-${index + 1}`,
      targetType: item.targetType || '-',
      correctionType: item.correctionType || item.feedbackType || '-',
      before: item.before || item.original || '-',
      after: item.after || item.corrected || '-',
      rootCause: item.rootCause || '-',
      status: item.status || '-',
      shouldEnterEvaluationSet: Boolean(item.shouldEnterEvaluationSet)
    }
  })
)
const projectAuditLangGraphAuditRows = computed(() => {
  const workflowId =
    selectedReviewTemporal.value.workflowId || selectedReviewRun.value?.run.workflowId
  const temporalEventCount = Number(
    selectedReviewTemporal.value.eventCount || reviewGraphTimeline.value.length || 0
  )
  const checkpointer = selectedReviewRun.value?.run.graphExecution?.checkpointer
  const toolCount = normalizedReviewReasoningRows.value.reduce(
    (total, row) => total + Number(row.toolCount || 0),
    0
  )
  const ruleCount = reviewRuleResultRows.value.length
  const retrievalCount = reviewRetrievalTraceRows.value.length
  const findingCount = normalizedReviewFindingRows.value.length
  const qualityStatus = String(reviewQualityEvaluation.value.status || '')
  const correctionCount = normalizedReviewHumanCorrectionRows.value.length
  const rows = [
    {
      stage: 'Temporal Workflow',
      status: workflowId ? '已持久化' : '缺少 Workflow',
      evidence: workflowId
        ? `事件 ${temporalEventCount} 个，Workflow ${workflowId}`
        : '未返回 workflowId',
      action: workflowId ? '可追踪外层长任务' : '检查 Temporal worker 和任务创建链路',
      healthy: Boolean(workflowId)
    },
    {
      stage: 'LangGraph Checkpoint',
      status: checkpointer ? `${shortText(checkpointer)} checkpointer` : '缺少 checkpoint',
      evidence: selectedReviewRun.value?.run.graphExecution?.persistence || '未返回持久化配置',
      action: checkpointer ? '可进行中断恢复和重放' : '启用 LangGraph Postgres checkpointer',
      healthy: Boolean(checkpointer)
    },
    {
      stage: '工具证据',
      status: normalizedReviewReasoningRows.value.length ? '已记录' : '缺少',
      evidence: `${normalizedReviewReasoningRows.value.length} 个推理摘要，${toolCount} 次工具调用`,
      action: normalizedReviewReasoningRows.value.length
        ? '检查每步证据和工具输出'
        : '补齐 reasoningTrace 和 toolCalls',
      healthy: normalizedReviewReasoningRows.value.length > 0
    },
    {
      stage: '规则与知识检索',
      status: ruleCount || retrievalCount ? '已记录' : '缺少',
      evidence: `规则 ${ruleCount} 条，检索 Trace ${retrievalCount} 条`,
      action:
        ruleCount || retrievalCount ? '抽查依据条款和 PageIndex 路由' : '补跑规则和知识检索节点',
      healthy: ruleCount > 0 && retrievalCount > 0
    },
    {
      stage: '审查草稿',
      status: findingCount ? '已生成' : '缺少',
      evidence: `${findingCount} 条草稿，证据/依据由门禁校验`,
      action: findingCount ? '检查低置信和需人工确认项' : '检查 LLM 输出 Schema 或门禁阻断',
      healthy: findingCount > 0
    },
    {
      stage: '质量门禁',
      status: qualityStatus === 'pass' ? '通过' : '需复核',
      evidence: `评分 ${shortText(reviewQualityEvaluation.value.score, '0')}/100，状态 ${friendlyStatus(
        qualityStatus,
        '未知'
      )}`,
      action: qualityStatus === 'pass' ? '可进入人工确认' : '优先处理失败门禁和低置信证据',
      healthy: qualityStatus === 'pass'
    },
    {
      stage: '人工修正',
      status: correctionCount ? '已回流' : '暂无修正',
      evidence: `${correctionCount} 条人工修正，可沉淀评估样本`,
      action: correctionCount ? '归因后进入评估集/训练集' : '等待监检员确认或驳回 AI 草稿',
      healthy: true
    }
  ]
  return rows
})

const projectAuditLangGraphIssueRows = computed(() =>
  projectAuditLangGraphAuditRows.value
    .filter((row) => !row.healthy)
    .map((row) => ({
      stage: row.stage,
      issue: row.status,
      action: row.action,
      evidence: row.evidence
    }))
)
const reviewLineage = computed<Record<string, unknown>>(
  () => selectedReviewRun.value?.lineage || {}
)
const reviewLineageRows = computed(() => [
  { label: '能力包 Hash', value: reviewLineage.value.capabilityBundleHash },
  { label: '业务包', value: reviewLineage.value.businessPackId },
  { label: '业务包版本', value: reviewLineage.value.businessPackVersion },
  { label: 'Agent', value: reviewLineage.value.agentId },
  { label: 'Agent 版本', value: reviewLineage.value.agentVersion },
  { label: 'Prompt 版本', value: reviewLineage.value.promptVersion },
  { label: '模型网关', value: reviewLineage.value.modelGateway },
  { label: '模型别名', value: reviewLineage.value.modelAlias },
  { label: '规则版本', value: reviewLineage.value.ruleSetVersion },
  { label: '知识库版本', value: reviewLineage.value.kbVersion },
  { label: '输入资料版本', value: reviewLineage.value.inputDocumentVersionIds },
  { label: 'OCR 结果版本', value: reviewLineage.value.ocrResultVersions },
  { label: '输入 Hash', value: reviewLineage.value.inputHash },
  { label: '输出 Hash', value: reviewLineage.value.outputHash }
])
const reviewQualityEvaluation = computed<Record<string, unknown>>(
  () => selectedReviewRun.value?.qualityEvaluation || {}
)
const reviewQualityRows = computed(
  () => (reviewQualityEvaluation.value.dimensions || []) as Array<Record<string, unknown>>
)
const reviewQualityGateRows = computed(
  () => (reviewQualityEvaluation.value.gates || []) as Array<Record<string, unknown>>
)
const reviewHumanCorrectionRows = computed(() => selectedReviewRun.value?.humanCorrections || [])
const reviewArtifactRows = computed(() => [
  { label: '工具调用', value: recordNumber(reviewArtifactSummary.value, 'toolCalls') },
  { label: '规则结果', value: recordNumber(reviewArtifactSummary.value, 'ruleCheckResults') },
  { label: '检索 Trace', value: recordNumber(reviewArtifactSummary.value, 'retrievalTraces') },
  { label: 'PageIndex', value: recordNumber(reviewArtifactSummary.value, 'pageIndexTraces') },
  { label: '草稿', value: recordNumber(reviewArtifactSummary.value, 'findingDrafts') },
  { label: '校验失败', value: recordNumber(reviewArtifactSummary.value, 'validationFailures') }
])
const reviewNodeStatusRows = computed(() => {
  const counts = selectedReviewRun.value?.run?.graphSummary?.statusCounts || {}
  return Object.entries(counts).map(([status, count]) => ({ status, count }))
})
const hasReviewRuns = computed(() => reviewRuns.value.length > 0)
const reviewRunConclusion = computed(() => {
  if (!selectedReviewRun.value) {
    return '暂无可审计 ReviewRun。请先从业务审查流程触发 AI 复核，或确认本地开发态已启用 Agent 编排。'
  }
  const run = selectedReviewRun.value.run
  const qualityStatus = String(reviewQualityEvaluation.value.status || '')
  const gateFailures = reviewQualityRows.value.reduce(
    (total, row) => total + Number(row.failureCount || 0),
    0
  )
  if (gateFailures > 0 || qualityStatus === 'fail') {
    return `当前 ${run.reviewRunId || run.id} 存在 ${gateFailures} 个质量失败项，需先定位证据、规则或检索问题。`
  }
  return `当前 ${run.reviewRunId || run.id} 已生成可审计结果，可检查决策链、溯源和人工修正记录。`
})
const agentStatusCards = computed(() => [
  {
    label: 'ReviewRun',
    value: String(reviewRuns.value.length),
    hint: hasReviewRuns.value ? '可追踪任务' : '等待业务触发',
    tone: hasReviewRuns.value ? 'green' : 'orange'
  },
  {
    label: '当前结论',
    value: selectedReviewRun.value
      ? reviewQualityEvaluation.value.status === 'pass'
        ? '可审查'
        : '需复核'
      : '无任务',
    hint: selectedReviewRun.value
      ? friendlyStatus(selectedReviewRun.value.run.status)
      : '未选中 Run',
    tone: selectedReviewRun.value
      ? reviewQualityEvaluation.value.status === 'pass'
        ? 'green'
        : 'orange'
      : 'orange'
  },
  {
    label: '质量门禁',
    value: String(reviewQualityGateRows.value.length),
    hint: reviewQualityRows.value.length ? '已生成评估' : '等待 Run 结果',
    tone: reviewQualityRows.value.some((row) => row.status !== 'pass') ? 'red' : 'green'
  },
  {
    label: '人工修正',
    value: String(reviewHumanCorrectionRows.value.length),
    hint: '可沉淀样本',
    tone: reviewHumanCorrectionRows.value.length ? 'blue' : 'green'
  }
])
const agentEmptyGuideRows = computed(() => [
  {
    label: '当前状态',
    value: '没有 ReviewRun，Agent 决策链、质量评估、人工修正和溯源快照暂不可用。'
  },
  {
    label: '如何触发任务',
    value:
      '从监检员审查页面发起 AI 复核；本地开发态需启用 review-orchestrator / Temporal / LangGraph 后再刷新。'
  },
  {
    label: 'FDE 先做什么',
    value: '先检查 OCR 运行时、OCR 100 阻断和待标注样本，避免后续 Agent 输入证据不足。'
  }
])
const ocrPendingAnnotationCount = computed(() =>
  Number(ocrAnnotationSummary.value?.missingHumanLabels || 0)
)
const ocrReadyForEvalCount = computed(() => Number(ocrAnnotationSummary.value?.readyForEval || 0))
const firstOcrBlockingSummary = computed(() => {
  if (firstRuntimeIssue.value) {
    return `${shortText(firstRuntimeIssue.value.name, 'runtime')}：${shortText(
      firstRuntimeIssue.value.message,
      '-'
    )}`
  }
  const ocr100Blocker = ocr100Scorecard.value?.blockers?.[0]
  if (ocr100Blocker) return ocr100Blocker
  const annotationBlocker = ocrAnnotationBlockerRows.value[0]
  if (annotationBlocker) return `${annotationBlocker.blocker} × ${annotationBlocker.count}`
  return '当前未发现首要阻断，建议发起 OCR 评测验证回归门禁。'
})
const ocrPriorityCards = computed(() => [
  {
    label: 'OCR 100',
    value: ocr100Scorecard.value
      ? `${ocr100Scorecard.value.score}/${ocr100Scorecard.value.targetScore}`
      : '-',
    hint: ocr100Scorecard.value?.ok ? '门禁就绪' : '存在阻断',
    tone: ocr100Scorecard.value?.ok ? 'green' : 'red'
  },
  {
    label: '运行时',
    value: friendlyStatus(ocrRuntimeDoctor.value?.status, '未知'),
    hint: `${ocrRuntimeDoctor.value?.summary?.fail || 0} fail / ${
      ocrRuntimeDoctor.value?.summary?.warn || 0
    } warn`,
    tone: ocrRuntimeDoctor.value?.ok ? 'green' : 'orange'
  },
  {
    label: '待标注',
    value: String(ocrPendingAnnotationCount.value),
    hint: `样本 ${ocrAnnotationSummary.value?.tasks || ocrAnnotationRows.value.length || 0}`,
    tone: ocrPendingAnnotationCount.value ? 'orange' : 'green'
  },
  {
    label: '可评估',
    value: String(ocrReadyForEvalCount.value),
    hint: '可入评估',
    tone: ocrReadyForEvalCount.value ? 'green' : 'orange'
  }
])
const ocrTopBlockerRows = computed(() => {
  const rows: Array<Record<string, unknown>> = []
  for (const item of ocrRuntimeDoctor.value?.topIssues || []) {
    rows.push({
      source: '运行时',
      blocker: `${shortText(item.name, 'issue')}：${shortText(item.message, '-')}`,
      action: '先修复本地 OCR 引擎、模型路径或 API base-url。'
    })
  }
  for (const blocker of ocr100Scorecard.value?.blockers || []) {
    rows.push({
      source: 'OCR 100',
      blocker,
      action: '按门禁域补齐引擎、Profile、预处理、标注或评测。'
    })
  }
  for (const row of ocrAnnotationBlockerRows.value) {
    rows.push({
      source: '人工标注',
      blocker: `${row.blocker} × ${row.count}`,
      action: '打开待标注样本，补齐字段、表格、印章 bbox 后二审。'
    })
  }
  return rows.slice(0, 6).map((row, index) => ({ id: index + 1, ...row }))
})
const ocrAnnotationStatusLabel = (row: FdeOcrAnnotationTask) => {
  if (row.readyForEval || row.collectionStatus === 'ready_for_eval') return '可入评估'
  if (row.collectionStatus === 'reviewed') return '待入评估'
  if (row.collectionStatus === 'labeled') return '待二审'
  return '待标注'
}
const ocrAnnotationStatusType = (row: FdeOcrAnnotationTask): FdeElTagType => {
  if (row.readyForEval || row.collectionStatus === 'ready_for_eval') return 'success'
  if (row.collectionStatus === 'labeled' || row.collectionStatus === 'reviewed') return 'warning'
  return 'info'
}
const agentSubpageItems = computed(() => [
  {
    key: 'runs' as const,
    label: '任务概览',
    description: 'ReviewRun 列表、Workflow 摘要和编排门禁。'
  },
  {
    key: 'reasoning' as const,
    label: '决策链',
    description: '可审计推理摘要、工具调用、证据和依据引用。'
  },
  {
    key: 'quality' as const,
    label: '质量与修正',
    description: '质量评估、人工修正和样本回流。'
  },
  {
    key: 'trace' as const,
    label: '底层 Trace',
    description: 'LangGraph 节点、Temporal 时间线、规则和检索产物。'
  }
])
const ocrSubpageItems = computed(() => [
  {
    key: 'overview' as const,
    label: '质量总览',
    description: 'OCR 100、运行时、待标注和首要阻断。'
  },
  {
    key: 'annotation' as const,
    label: '人工标定',
    description: '字段、表格、印章样本标注和二审。'
  },
  {
    key: 'runtime' as const,
    label: '运行诊断',
    description: 'OCR Job、候选图、引擎耗时、字段和证据问题。'
  },
  {
    key: 'evaluation' as const,
    label: '评估门禁',
    description: 'OCR release evaluation、场景分数和阈值失败。'
  }
])

const createDemoReviewRunDetail = (): FdeReviewRunDetailPayload => {
  const run: FdeReviewRun = {
    id: 'RR-DEMO-001',
    reviewRunId: 'RR-DEMO-001',
    aiRunId: 'AIR-DEMO-001',
    projectId: 'DEMO-PROJECT-PIPELINE',
    nodeId: 'material_review',
    businessPackId: 'engineering_inspection_v1',
    agentId: 'compliance_review_agent',
    agentVersion: '1.4.0-demo',
    promptVersion: 'review_prompt@2.1.0',
    modelAlias: 'deepseek-reasoner',
    modelGateway: 'litellm',
    workflowEngine: 'temporal',
    graphEngine: 'langgraph',
    graphRunner: 'postgres-checkpointer',
    workflowId: 'wf-review-demo-001',
    temporalRunId: 'temporal-demo-run-001',
    status: 'waiting_human_review',
    currentStep: 'waiting_human_review',
    runMode: 'demo',
    inputHash: 'sha256:demo-input-4b8c',
    outputHash: 'sha256:demo-output-19f2',
    graphSummary: {
      total: 7,
      statusCounts: { completed: 6, waiting_human_review: 1 }
    },
    graphExecution: {
      checkpointer: 'postgres',
      threadId: 'demo-thread-001'
    },
    createdAt: '2026-06-29 10:18:20',
    updatedAt: '2026-06-29 10:20:42'
  }
  const timeline = [
    {
      createdAt: '2026-06-29 10:18:20',
      eventType: 'WorkflowStarted',
      title: 'Temporal Workflow 接收审查任务',
      status: 'completed'
    },
    {
      createdAt: '2026-06-29 10:18:28',
      eventType: 'ActivityCompleted',
      title: '加载 OCR 字段、表格和印章证据',
      status: 'completed'
    },
    {
      createdAt: '2026-06-29 10:19:08',
      eventType: 'ActivityCompleted',
      title: '规则库与知识库检索完成',
      status: 'completed'
    },
    {
      createdAt: '2026-06-29 10:20:42',
      eventType: 'SignalWaiting',
      title: '等待监检员确认 AI 发现项',
      status: 'waiting_human_review'
    }
  ]
  return {
    run,
    graph: {
      reviewRunId: run.reviewRunId,
      nodes: [
        {
          sequence: 1,
          label: '加载项目上下文',
          nodeKey: 'load_context',
          taskQueue: 'review-orchestrator',
          status: 'completed',
          attempt: 1,
          toolCalls: [{ toolName: 'get_project_context' }],
          artifactCounts: { toolCalls: 1 }
        },
        {
          sequence: 2,
          label: '读取 OCR 证据',
          nodeKey: 'load_ocr_result',
          taskQueue: 'review-orchestrator',
          status: 'completed',
          attempt: 1,
          toolCalls: [{ toolName: 'get_ocr_result' }],
          artifactCounts: { toolCalls: 1 }
        },
        {
          sequence: 3,
          label: '执行规则检查',
          nodeKey: 'run_rule_engine',
          taskQueue: 'knowledge-rule',
          status: 'completed',
          attempt: 1,
          toolCalls: [{ toolName: 'run_rule_engine' }],
          artifactCounts: { ruleResults: 3, toolCalls: 1 }
        },
        {
          sequence: 4,
          label: '检索审查依据',
          nodeKey: 'retrieve_knowledge',
          taskQueue: 'knowledge-rule',
          status: 'completed',
          attempt: 1,
          toolCalls: [{ toolName: 'search_knowledge_base' }],
          artifactCounts: { retrievalTraces: 2, toolCalls: 1 }
        },
        {
          sequence: 5,
          label: '生成审查草稿',
          nodeKey: 'llm_review',
          taskQueue: 'litellm',
          status: 'completed',
          attempt: 1,
          toolCalls: [{ toolName: 'chat.completions' }],
          artifactCounts: { findingDrafts: 2, toolCalls: 1 }
        },
        {
          sequence: 6,
          label: '证据与依据校验',
          nodeKey: 'validate_output',
          taskQueue: 'review-orchestrator',
          status: 'completed',
          attempt: 1,
          artifactCounts: { validationFailures: 1 }
        }
      ],
      edges: [
        { source: 'load_context', target: 'load_ocr_result' },
        { source: 'load_ocr_result', target: 'run_rule_engine' },
        { source: 'run_rule_engine', target: 'retrieve_knowledge' },
        { source: 'retrieve_knowledge', target: 'llm_review' },
        { source: 'llm_review', target: 'validate_output' }
      ],
      timeline,
      artifactSummary: {
        toolCalls: 5,
        ruleCheckResults: 3,
        retrievalTraces: 2,
        pageIndexTraces: 1,
        findingDrafts: 2,
        validationFailures: 1
      },
      artifacts: {
        ruleCheckResults: [
          {
            ruleCode: 'QC_CERT_FIELD_003',
            result: 'failed',
            severity: 'medium',
            linkedClauseIds: ['clause-qc-5.3.2']
          },
          {
            ruleCode: 'SEAL_REQUIRED_001',
            result: 'passed',
            severity: 'high',
            linkedClauseIds: ['clause-seal-2.1']
          }
        ],
        retrievalTraces: [
          {
            retrievalTraceId: 'RT-DEMO-001',
            selectedRoute: 'hybrid_rag',
            selectedClauseCount: 3,
            pageIndexNodeCount: 0,
            selectedClauseIds: ['clause-qc-5.3.2', 'clause-qc-5.3.4']
          },
          {
            retrievalTraceId: 'RT-DEMO-002',
            selectedRoute: 'pageindex',
            selectedClauseCount: 2,
            pageIndexNodeCount: 4,
            selectedClauseIds: ['clause-appendix-a.1'],
            pageIndexTree: {
              candidateNodeCount: 4,
              linkedClauseIds: ['clause-appendix-a.1', 'clause-seal-2.1'],
              selectedNodes: [
                {
                  pageIndexNodeId: 'PIN-DEMO-001',
                  nodeId: 'appendix-a',
                  title: '附录 A 管道特性表审查要求',
                  summary: '说明管道特性表字段、焊接检测和签章要求。',
                  startPage: 31,
                  endPage: 34,
                  sectionPath: ['工程监检资料审查手册', '附录 A'],
                  linkedClauseIds: ['clause-appendix-a.1'],
                  score: 0.91
                },
                {
                  pageIndexNodeId: 'PIN-DEMO-002',
                  nodeId: 'seal-requirement',
                  title: '资料签章与有效期要求',
                  summary: '说明检测专用章、公章和有效期审查要求。',
                  startPage: 18,
                  endPage: 20,
                  sectionPath: ['工程监检资料审查手册', '第 2 章', '签章'],
                  linkedClauseIds: ['clause-seal-2.1'],
                  score: 0.86
                }
              ]
            }
          }
        ],
        findingDrafts: [
          {
            id: 'FD-DEMO-001',
            findingType: 'field_missing',
            severity: 'medium',
            confidence: 0.87,
            requiresHumanConfirmation: true
          },
          {
            id: 'FD-DEMO-002',
            findingType: 'seal_consistency_warning',
            severity: 'low',
            confidence: 0.76,
            requiresHumanConfirmation: true
          }
        ]
      }
    },
    timeline,
    temporal: {
      workflowId: run.workflowId,
      runId: run.temporalRunId,
      eventCount: 12,
      historyPolicy: 'ids_hashes_versions_only'
    },
    reasoningTrace: [
      {
        sequence: 1,
        stepName: '资料上下文整理',
        reasoningSummary: '识别到质量证明文件和管道特性表，资料类型与节点要求匹配。',
        toolCalls: [{ toolName: 'get_project_context' }, { toolName: 'get_ocr_result' }],
        evidenceRefs: [{ documentVersionId: 'docv-demo-001', pageNo: 1 }],
        ruleRefs: [],
        kbRefs: [],
        quality: { passed: true }
      },
      {
        sequence: 2,
        stepName: '确定性规则核对',
        reasoningSummary: '材料牌号字段未在 OCR 字段集中命中，触发中风险缺项规则。',
        toolCalls: [{ toolName: 'run_rule_engine' }],
        evidenceRefs: [
          { documentVersionId: 'docv-demo-001', pageNo: 1, bbox: [380, 260, 520, 310] }
        ],
        ruleRefs: [{ ruleCode: 'QC_CERT_FIELD_003' }],
        kbRefs: [{ clauseId: 'clause-qc-5.3.2' }],
        quality: { passed: true }
      },
      {
        sequence: 3,
        stepName: '草稿生成与校验',
        reasoningSummary:
          '生成 2 条 Finding 草稿，其中 1 条因证据 bbox 与表格单元格不一致进入人工复核。',
        toolCalls: [{ toolName: 'chat.completions' }],
        evidenceRefs: [{ documentVersionId: 'docv-demo-001', pageNo: 1 }],
        ruleRefs: [{ ruleCode: 'EVIDENCE_BBOX_REQUIRED' }],
        kbRefs: [{ clauseId: 'clause-appendix-a.1' }],
        quality: { passed: false }
      }
    ],
    lineage: {
      capabilityBundleHash: 'sha256:bundle-demo-20260629',
      businessPackId: 'engineering_inspection_v1',
      businessPackVersion: '1.2.0',
      agentId: 'compliance_review_agent',
      agentVersion: '1.4.0-demo',
      promptVersion: 'review_prompt@2.1.0',
      modelGateway: 'litellm',
      modelAlias: 'deepseek-reasoner',
      ruleSetVersion: 'engineering_rules@1.0.0',
      kbVersion: 'inspection_kb@1.0.0',
      inputDocumentVersionIds: ['docv-demo-001', 'docv-demo-002'],
      ocrResultVersions: ['ocr-demo-001'],
      inputHash: run.inputHash,
      outputHash: run.outputHash
    },
    qualityEvaluation: {
      score: 86,
      status: 'needs_human_review',
      humanReviewRequired: true,
      dimensions: [
        {
          dimension: '证据命中',
          status: 'pass',
          failureCount: 0,
          warningCount: 1,
          finding: '1 个 bbox 需人工确认'
        },
        {
          dimension: '依据引用',
          status: 'pass',
          failureCount: 0,
          warningCount: 0,
          finding: '条款版本有效'
        },
        {
          dimension: 'Schema 门禁',
          status: 'pass',
          failureCount: 0,
          warningCount: 0,
          finding: '结构化输出合规'
        }
      ],
      gates: [
        { gate: 'evidence_refs_present', status: 'pass' },
        { gate: 'human_confirmation_required', status: 'pass' },
        { gate: 'bbox_consistency', status: 'warning' }
      ]
    },
    humanCorrections: [
      {
        feedbackType: 'wrong_evidence',
        rootCause: 'ocr_table_cell_bbox_shift',
        beforeSummary: 'AI 引用整页表格区域作为材料牌号证据。',
        afterSummary: '人工修正到第 1 页材料牌号所在单元格。',
        status: 'triaged',
        shouldEnterEvaluationSet: true
      },
      {
        feedbackType: 'edited',
        rootCause: 'prompt_wording',
        beforeSummary: '补正建议措辞过泛。',
        afterSummary: '改为要求施工方补充对应炉批号质量证明页。',
        status: 'approved_for_eval',
        shouldEnterEvaluationSet: true
      }
    ],
    redactionPolicy: 'masked'
  }
}

const createDemoOcrQuality = (): FdeOcrQualityPayload => ({
  fileLevel: { total: 18, success: 17, failed: 1, parseSuccessRate: 0.944 },
  jobLevel: { total: 18, success: 16, failed: 1, running: 1 },
  fieldLevel: {
    total: 168,
    lowConfidence: 9,
    manualCorrectionRate: 0.14,
    parseResultCount: 18,
    parseFieldCount: 168,
    lowConfidenceParseFieldCount: 9,
    conflictFieldCount: 3,
    evidenceMissingFieldCount: 5,
    missingRequiredFieldCount: 4,
    averageFieldConfidence: 0.89,
    missingRequiredFieldBreakdown: [
      { fieldCode: 'material_grade', count: 2 },
      { fieldCode: 'report_no', count: 1 }
    ],
    fieldCodeBreakdown: [
      { fieldCode: 'weld_no', count: 28 },
      { fieldCode: 'material_grade', count: 16 }
    ],
    qualityFlagCounts: [
      { flag: 'LOW_CONFIDENCE', count: 9 },
      { flag: 'BBOX_SHIFT', count: 5 }
    ],
    sampleFields: []
  },
  evidenceLevel: {
    parseResultCount: 18,
    scoredResultCount: 17,
    averageEvidenceCompleteness: 0.91,
    missingEvidence: 5,
    fieldEvidenceMissing: 3,
    tableEvidenceMissing: 1,
    sealEvidenceMissing: 1,
    unknownEvidenceMissing: 0,
    missingEvidenceItems: [
      {
        targetType: 'field',
        targetId: 'material_grade',
        parseResultId: 'parse-demo-001',
        profileId: 'quality_certificate_v1'
      },
      {
        targetType: 'seal',
        targetId: 'seal-demo-002',
        parseResultId: 'parse-demo-002',
        profileId: 'piping_characteristic_list_v1'
      }
    ]
  },
  tableLevel: {
    parseResultCount: 18,
    tableCount: 21,
    formalTableCount: 17,
    heuristicTableCount: 4,
    reviewRequiredCount: 3,
    missingRequiredTableCount: 2,
    businessRowCount: 126,
    normalizedRowCount: 118,
    cellCount: 1456,
    averageTableConfidence: 0.86,
    formalTableRate: 0.81,
    heuristicTableRate: 0.19,
    reviewRequiredRate: 0.14,
    missingRequiredTableBreakdown: [{ tableCode: 'weld_detection_result_table', count: 2 }],
    sourceBreakdown: [{ source: 'pp_structure_v3', count: 17 }],
    qualityFlagCounts: [{ flag: 'TABLE_STRUCTURE_LOW_CONFIDENCE', count: 3 }],
    sampleTables: []
  },
  sealLevel: {
    parseResultCount: 18,
    sealCount: 9,
    readableSealCount: 7,
    fragmentSealCount: 2,
    visualCandidateCount: 11,
    reviewRequiredCount: 2,
    missingExpectedSealTypeCount: 1,
    missingTextCount: 2,
    averageSealConfidence: 0.78,
    readableSealRate: 0.78,
    fragmentSealRate: 0.22,
    visualCandidateReviewRate: 0.18,
    sealTypeBreakdown: [{ sealType: 'company_official_seal', count: 5 }],
    readableSealTypeBreakdown: [{ sealType: 'company_official_seal', count: 4 }],
    matchedExpectedSealTypeBreakdown: [{ sealType: 'inspection_testing_seal', count: 3 }],
    missingExpectedSealTypeBreakdown: [{ sealType: 'inspection_testing_seal', count: 1 }],
    sourceBreakdown: [{ source: 'paddlex_seal', count: 7 }],
    qualityFlagCounts: [{ flag: 'SEAL_TEXT_LOW_CONFIDENCE', count: 2 }],
    sampleSeals: []
  },
  lowConfidenceFields: [],
  cacheMetrics: {
    engineRunCount: 28,
    engineCacheHits: 11,
    engineCacheHitRate: 0.39,
    variantCacheHits: 15,
    variantCacheHitRate: 0.54,
    resultCacheHits: 6,
    totalDurationMs: 93200,
    averageDurationMs: 3328,
    slowEngines: []
  },
  qualityReasonCounts: [
    { reason: 'TABLE_STRUCTURE_LOW_CONFIDENCE', count: 3 },
    { reason: 'SEAL_TEXT_LOW_CONFIDENCE', count: 2 }
  ],
  runtimeDoctor: {
    status: 'degraded',
    ok: false,
    summary: { pass: 6, warn: 2, fail: 1, total: 9 },
    topIssues: [
      {
        name: 'paddlex-seal-model',
        message: 'Seal 模型可用但 sealName 低置信，需要补充标注样本。'
      }
    ],
    subprocessPython: '.venv/bin/python',
    schemaVersion: 'ocr-runtime-doctor@1.0'
  },
  ocr100Scorecard: {
    schemaVersion: 'ocr100@1.0',
    targetScore: 100,
    score: 88,
    ok: false,
    sections: [
      { name: '运行时', score: 18, maxScore: 20, status: 'pass' },
      { name: '表格', score: 22, maxScore: 25, status: 'pass' },
      { name: '印章', score: 17, maxScore: 25, status: 'fail' },
      { name: '标注闭环', score: 13, maxScore: 15, status: 'pass' },
      { name: '评估门禁', score: 18, maxScore: 15, status: 'pass' }
    ],
    blockers: ['印章文字准确率未达到 92% 目标。', 'seal_text_profile 样本“可入评估”数量不足 5 个。']
  },
  evalRuns: [
    {
      id: 'OCR-EVAL-DEMO-001',
      profileId: 'all',
      status: 'completed',
      metrics: { caseCount: 12 },
      evaluationSummary: {
        ok: false,
        summary: { total: 12, passed: 9, failed: 3, averageScore: 0.89 },
        thresholdFailures: [
          { metric: 'sealNameAccuracy', actual: 0.84, expected: 0.92 },
          { metric: 'tableCellAccuracy', actual: 0.88, expected: 0.9 }
        ],
        scenarioMetrics: {
          seal_text_profile: {
            ok: false,
            cases: 4,
            passed: 2,
            failed: 2,
            averageScore: 0.82,
            thresholdFailures: [{ metric: 'sealNameAccuracy', actual: 0.84, expected: 0.92 }]
          },
          piping_table_profile: {
            ok: true,
            cases: 8,
            passed: 7,
            failed: 1,
            averageScore: 0.92,
            thresholdFailures: []
          }
        },
        failedCases: [
          {
            caseId: 'OCR-DEMO-SEAL-001',
            scenario: 'seal_text_profile',
            score: 0.78,
            findings: ['SEAL_TEXT_LOW_CONFIDENCE']
          }
        ]
      }
    }
  ],
  failurePools: {
    fieldFailures: [
      {
        code: 'FIELD_LOW_CONFIDENCE',
        fieldName: '材料牌号',
        fieldValue: 'GC2',
        confidence: 0.68
      }
    ],
    tableFailures: [],
    sealFailures: [],
    engineFailures: []
  }
})

const createDemoOcrAnnotationPayload = (): FdeOcrAnnotationPayload => ({
  summary: {
    tasks: 4,
    humanLabeled: 2,
    readyForEval: 1,
    missingHumanLabels: 2,
    completionRate: 0.5,
    statusCounts: { needs_labeling: 2, labeled: 1, ready_for_eval: 1 },
    blockerCounts: {
      MISSING_FIELD_LABELS: 2,
      MISSING_SEAL_BBOX: 1
    }
  },
  nextActions: ['补齐 seal_text_profile 样本印章 bbox', '二审 labeled 样本后进入评估集'],
  page: {
    page: 1,
    pageSize: 20,
    total: 4,
    items: [
      {
        taskId: 'ANNO-DEMO-001',
        caseId: 'OCR-DEMO-SEAL-001',
        scenario: 'seal_text_profile',
        profileId: 'piping_characteristic_list_v1',
        documentType: 'piping_characteristic_list',
        sourcePath: 'demo/piping-characteristic-list.png',
        pageNo: 1,
        collectionStatus: 'needs_labeling',
        readinessBlockers: ['MISSING_SEAL_BBOX'],
        candidateCounts: { fields: 8, tables: 1, seals: 2 },
        labelCounts: { fields: 5, tables: 1, seals: 0 },
        readyForEval: false
      },
      {
        taskId: 'ANNO-DEMO-002',
        caseId: 'OCR-DEMO-TABLE-001',
        scenario: 'piping_table_profile',
        profileId: 'piping_characteristic_list_v1',
        documentType: 'piping_characteristic_list',
        sourcePath: 'demo/piping-table.png',
        pageNo: 1,
        collectionStatus: 'labeled',
        candidateCounts: { fields: 12, tables: 2, seals: 1 },
        labelCounts: { fields: 12, tables: 2, seals: 1 },
        readyForEval: false
      },
      {
        taskId: 'ANNO-DEMO-003',
        caseId: 'OCR-DEMO-QC-001',
        scenario: 'quality_certificate_profile',
        profileId: 'quality_certificate_v1',
        documentType: 'quality_certificate',
        sourcePath: 'demo/quality-certificate.pdf',
        pageNo: 1,
        collectionStatus: 'ready_for_eval',
        candidateCounts: { fields: 10, tables: 2, seals: 1 },
        labelCounts: { fields: 10, tables: 2, seals: 1 },
        readyForEval: true
      },
      {
        taskId: 'ANNO-DEMO-004',
        caseId: 'OCR-DEMO-NDT-001',
        scenario: 'ndt_rt_table_profile',
        profileId: 'ndt_rt_report_v1',
        documentType: 'ndt_report',
        sourcePath: 'demo/ndt-rt-report.pdf',
        pageNo: 2,
        collectionStatus: 'needs_labeling',
        readinessBlockers: ['MISSING_TABLE_CELL_LABELS'],
        candidateCounts: { fields: 14, tables: 2, seals: 1 },
        labelCounts: { fields: 8, tables: 0, seals: 1 },
        readyForEval: false
      }
    ]
  }
})

const createDemoProjectAuditWorkspace = (): FdeProjectAuditWorkspace => {
  const demoReview = createDemoReviewRunDetail()
  const project = {
    id: 'DEMO-PROJECT-PIPELINE',
    code: 'GX-PIPE-2026-001',
    name: '珠海储能站新增两套卸车系统监检项目',
    type: '压力管道安装监检',
    region: '广东省珠海市',
    ownerOrgName: '珠海恒基达鑫国际化工仓储股份有限公司',
    contractorOrgName: '广东星燃石化设计院有限公司',
    ndtOrgName: '广东省建设工程勘察设计审查中心',
    inspectionOrgName: '广东省特检院',
    businessPackId: 'engineering_inspection_v1',
    businessPackVersion: '1.2.0',
    status: '监检审查中',
    todoCount: 3,
    messageCount: 2,
    currentNodeId: 201,
    riskLevel: '中',
    updatedAt: '2026-06-29 10:30:00',
    actions: ['project:view']
  } as FdeProjectAuditWorkspace['project']
  const nodes = [
    {
      id: 'node-demo-201',
      projectId: project.id,
      nodeId: 201,
      code: 'MATERIAL-REVIEW',
      name: '材料资料审查',
      groupName: '资料审查',
      inspectionType: 'A',
      status: '待人工确认',
      fileCount: 4,
      requiredProgress: { done: 3, total: 4 },
      actions: ['project:view']
    },
    {
      id: 'node-demo-202',
      projectId: project.id,
      nodeId: 202,
      code: 'NDT-REVIEW',
      name: '无损检测报告审查',
      groupName: '资料审查',
      inspectionType: 'B',
      status: 'AI 预审中',
      fileCount: 3,
      requiredProgress: { done: 2, total: 3 },
      actions: ['project:view']
    },
    {
      id: 'node-demo-301',
      projectId: project.id,
      nodeId: 301,
      code: 'REPORT',
      name: '报告生成与复核',
      groupName: '报告归档',
      inspectionType: 'C/B',
      status: '待提交',
      fileCount: 0,
      requiredProgress: { done: 0, total: 2 },
      actions: ['project:view']
    }
  ] as FdeProjectAuditWorkspace['groups'][number]['nodes']
  const documents = [
    {
      id: 'doc-demo-001',
      projectId: project.id,
      fileName: '管道特性表-第2版.png',
      fileType: 'image/png',
      sourceOrgName: '广东星燃石化设计院有限公司',
      uploaderName: '施工方 李工',
      currentVersionId: 'docv-demo-001',
      fileStatus: '已上传',
      currentOcrStatus: '人工修正',
      sliceStatus: '已切片',
      vectorStatus: '已向量化',
      chunkCount: 42,
      vectorCount: 42,
      embeddingModel: 'embedding-default',
      indexVersion: 'knowledge-index@2026.06.29',
      pageIndexStatus: '已构建',
      updatedAt: '2026-06-29 10:12:00',
      actions: ['file:view']
    },
    {
      id: 'doc-demo-002',
      projectId: project.id,
      fileName: '质量证明书-QX201903S.pdf',
      fileType: 'application/pdf',
      sourceOrgName: '广东星燃石化设计院有限公司',
      uploaderName: '施工方 李工',
      currentVersionId: 'docv-demo-002',
      fileStatus: '已上传',
      currentOcrStatus: '已识别',
      sliceStatus: '切片中',
      vectorStatus: '向量化中',
      chunkCount: 18,
      vectorCount: 12,
      embeddingModel: 'embedding-default',
      indexVersion: 'knowledge-index@2026.06.29',
      pageIndexStatus: '等待补齐切片',
      updatedAt: '2026-06-29 09:58:00',
      actions: ['file:view']
    },
    {
      id: 'doc-demo-003',
      projectId: project.id,
      fileName: 'RT检测报告-焊口清单.pdf',
      fileType: 'application/pdf',
      sourceOrgName: '广东省建设工程勘察设计审查中心',
      uploaderName: 'NDT 王工',
      currentVersionId: 'docv-demo-003',
      fileStatus: '已上传',
      currentOcrStatus: '已识别',
      sliceStatus: '已切片',
      vectorStatus: '向量化中',
      chunkCount: 28,
      vectorCount: 19,
      embeddingModel: 'embedding-default',
      indexVersion: 'knowledge-index@2026.06.29',
      pageIndexStatus: '待补齐向量',
      updatedAt: '2026-06-29 09:42:00',
      actions: ['file:view']
    },
    {
      id: 'doc-demo-004',
      projectId: project.id,
      fileName: '焊工资格证与外部查询截图.pdf',
      fileType: 'application/pdf',
      sourceOrgName: '广东星燃石化设计院有限公司',
      uploaderName: '施工方 李工',
      currentVersionId: 'docv-demo-004',
      fileStatus: '已上传',
      currentOcrStatus: '已识别',
      sliceStatus: '切片中',
      vectorStatus: '待向量化',
      chunkCount: 16,
      vectorCount: 0,
      embeddingModel: 'embedding-default',
      indexVersion: 'knowledge-index@2026.06.29',
      pageIndexStatus: '等待切片',
      updatedAt: '2026-06-29 09:30:00',
      actions: ['file:view']
    }
  ] as FdeProjectAuditWorkspace['documents']
  const bindings = [
    {
      id: 'bind-demo-001',
      projectId: project.id,
      nodeId: 201,
      requirementName: '管道特性表',
      documentId: 'doc-demo-001',
      documentVersionId: 'docv-demo-001',
      fileName: '管道特性表-第2版.png',
      versionNo: 'v2',
      usage: '监检资料',
      sourceOrgName: '广东星燃石化设计院有限公司',
      bindingStatus: '已提交',
      boundAt: '2026-06-29 10:12:00',
      actions: ['file:view']
    },
    {
      id: 'bind-demo-002',
      projectId: project.id,
      nodeId: 201,
      requirementName: '质量证明文件',
      documentId: 'doc-demo-002',
      documentVersionId: 'docv-demo-002',
      fileName: '质量证明书-QX201903S.pdf',
      versionNo: 'v1',
      usage: '证明材料',
      sourceOrgName: '广东星燃石化设计院有限公司',
      bindingStatus: '需补正',
      boundAt: '2026-06-29 09:58:00',
      actions: ['file:view']
    },
    {
      id: 'bind-demo-003',
      projectId: project.id,
      nodeId: 201,
      requirementName: '无损检测报告',
      documentId: 'doc-demo-003',
      documentVersionId: 'docv-demo-003',
      fileName: 'RT检测报告-焊口清单.pdf',
      versionNo: 'v1',
      usage: '检测报告',
      sourceOrgName: '广东省建设工程勘察设计审查中心',
      bindingStatus: '需人工复核',
      boundAt: '2026-06-29 09:42:00',
      actions: ['file:view']
    },
    {
      id: 'bind-demo-004',
      projectId: project.id,
      nodeId: 201,
      requirementName: '焊工资格证及外部查询截图',
      documentId: 'doc-demo-004',
      documentVersionId: 'docv-demo-004',
      fileName: '焊工资格证与外部查询截图.pdf',
      versionNo: 'v1',
      usage: '资质证明',
      sourceOrgName: '广东星燃石化设计院有限公司',
      bindingStatus: '已提交',
      boundAt: '2026-06-29 09:30:00',
      actions: ['file:view']
    }
  ] as FdeProjectAuditWorkspace['bindings']
  const reviewRuns = [
    demoReview.run,
    {
      ...demoReview.run,
      id: 'RR-DEMO-SHADOW-001',
      reviewRunId: 'RR-DEMO-SHADOW-001',
      runMode: 'shadow',
      status: 'draft_persisted',
      currentStep: 'quality_gate',
      workflowId: 'wf-review-demo-shadow-001',
      temporalRunId: 'temporal-demo-shadow-001'
    }
  ]
  const ocrJobs = [
    {
      id: 'OCR-JOB-DEMO-001',
      jobId: 'OCR-JOB-DEMO-001',
      documentVersionId: 'docv-demo-001',
      profileId: 'piping_characteristic_list_v1',
      status: 'needs_human_review',
      parseResultId: 'parse-demo-001',
      engineRuns: 4,
      updatedAt: '2026-06-29 10:17:00'
    },
    {
      id: 'OCR-JOB-DEMO-002',
      jobId: 'OCR-JOB-DEMO-002',
      documentVersionId: 'docv-demo-002',
      profileId: 'quality_certificate_v1',
      status: 'success',
      parseResultId: 'parse-demo-002',
      engineRuns: 3,
      updatedAt: '2026-06-29 10:02:00'
    },
    {
      id: 'OCR-JOB-DEMO-003',
      jobId: 'OCR-JOB-DEMO-003',
      documentVersionId: 'docv-demo-003',
      profileId: 'ndt_rt_report_v1',
      status: 'success',
      parseResultId: 'parse-demo-003',
      engineRuns: 3,
      updatedAt: '2026-06-29 09:50:00'
    },
    {
      id: 'OCR-JOB-DEMO-004',
      jobId: 'OCR-JOB-DEMO-004',
      documentVersionId: 'docv-demo-004',
      profileId: 'qualification_certificate_v1',
      status: 'needs_human_review',
      parseResultId: 'parse-demo-004',
      engineRuns: 3,
      updatedAt: '2026-06-29 09:38:00'
    }
  ]
  const ocrAnnotationPayload = createDemoOcrAnnotationPayload()
  const qualityBlockers = [
    {
      type: 'agent',
      level: 'warning',
      title: 'AI 审查任务等待人工确认',
      targetId: 'RR-DEMO-001',
      targetName: '资料复核员',
      action: '检查证据、依据和人工修正后确认。'
    },
    {
      type: 'ocr-annotation',
      level: 'warning',
      title: '印章 bbox 未标定',
      targetId: 'ANNO-DEMO-001',
      targetName: 'seal_text_profile',
      action: '进入 OCR 标注样本补齐印章框。'
    }
  ]
  return {
    project,
    selectedNodeId: 201,
    selectedNode: nodes[0],
    groups: [
      { groupName: '资料审查', nodes: nodes.slice(0, 2) },
      { groupName: '报告归档', nodes: nodes.slice(2) }
    ],
    nodeSummaries: [
      {
        node: nodes[0],
        nodeId: 201,
        nodeName: nodes[0].name,
        groupName: nodes[0].groupName,
        status: nodes[0].status,
        documentCount: 4,
        bindingCount: 4,
        submissionCount: 1,
        ocrJobCount: 4,
        reviewRunCount: 2,
        aiRunCount: 2,
        lowConfidenceFieldCount: 5,
        blockerCount: 2,
        latestReviewRun: demoReview.run
      },
      {
        node: nodes[1],
        nodeId: 202,
        nodeName: nodes[1].name,
        groupName: nodes[1].groupName,
        status: nodes[1].status,
        documentCount: 1,
        bindingCount: 1,
        submissionCount: 1,
        ocrJobCount: 1,
        reviewRunCount: 0,
        aiRunCount: 0,
        lowConfidenceFieldCount: 1,
        blockerCount: 1
      },
      {
        node: nodes[2],
        nodeId: 301,
        nodeName: nodes[2].name,
        groupName: nodes[2].groupName,
        status: nodes[2].status,
        documentCount: 0,
        bindingCount: 0,
        submissionCount: 0,
        ocrJobCount: 0,
        reviewRunCount: 0,
        aiRunCount: 0,
        lowConfidenceFieldCount: 0,
        blockerCount: 0
      }
    ],
    metrics: {
      nodes: 3,
      documents: 4,
      submissions: 1,
      ocrJobs: 4,
      reviewRuns: 2,
      annotationTasks: 4,
      blockers: 2,
      lowConfidenceFields: 5,
      knowledgeChunks: 128,
      knowledgeVectors: 104,
      vectorizedDocuments: 2,
      pageIndexNodes: 8
    },
    documents,
    bindings,
    submissions: [
      {
        id: 'SUB-DEMO-001',
        batchName: '材料资料首批提交',
        status: 'waiting_human_review',
        nodeIds: [201],
        nodeNames: ['材料资料审查'],
        bindingCount: 2,
        submittedAt: '2026-06-29 10:15:00',
        submitterName: '施工方 李工'
      }
    ],
    reviewRuns,
    aiRuns: [],
    ocrJobs,
    ocrAnnotationTasks: ocrAnnotationPayload.page.items,
    qualityBlockers,
    updatedAt: '2026-06-29 10:30:00'
  }
}

const createDemoProjectAuditWorkspaceVariant = (
  base: FdeProjectAuditWorkspace,
  options: {
    suffix: string
    id: string
    code: string
    name: string
    type: string
    status: FdeProjectAuditWorkspace['project']['status']
    region: string
    currentNodeId: number
    blockerCount: number
    blockerTitle?: string
    reviewRunStatus?: string
    ocrStatus?: string
  }
): FdeProjectAuditWorkspace => {
  const workspace = JSON.parse(JSON.stringify(base)) as FdeProjectAuditWorkspace
  workspace.project = {
    ...workspace.project,
    id: options.id,
    code: options.code,
    name: options.name,
    type: options.type,
    region: options.region,
    status: options.status,
    currentNodeId: options.currentNodeId,
    updatedAt: `2026-06-29 10:${30 + options.suffix.length}:00`
  }
  workspace.groups = workspace.groups.map((group) => ({
    ...group,
    nodes: group.nodes.map((node) => ({
      ...node,
      id: `${node.id}-${options.suffix}`,
      projectId: options.id,
      nodeId: Number(node.nodeId) + options.currentNodeId - 201,
      status:
        options.blockerCount > 0 && node.nodeId === 201
          ? options.status === 'AI 预审中'
            ? 'AI 预审中'
            : '待人工确认'
          : node.status
    }))
  }))
  const allNodes = workspace.groups.flatMap((group) => group.nodes)
  workspace.selectedNodeId = options.currentNodeId
  workspace.selectedNode =
    allNodes.find((node) => Number(node.nodeId) === Number(options.currentNodeId)) ||
    allNodes[0] ||
    null
  workspace.nodeSummaries = workspace.nodeSummaries.map((summary, index) => {
    const node = allNodes[index] || workspace.selectedNode
    return {
      ...summary,
      node,
      nodeId: node?.nodeId || summary.nodeId,
      nodeName: node?.name || summary.nodeName,
      groupName: node?.groupName || summary.groupName,
      status: node?.status || summary.status,
      blockerCount: index === 0 ? options.blockerCount : Number(summary.blockerCount || 0)
    }
  })
  workspace.documents = workspace.documents.map((document, index) => ({
    ...document,
    id: `${document.id}-${options.suffix}`,
    projectId: options.id,
    currentVersionId: `${document.currentVersionId}-${options.suffix}`,
    currentOcrStatus:
      index === 0
        ? (options.ocrStatus as never) || document.currentOcrStatus
        : document.currentOcrStatus
  }))
  workspace.bindings = workspace.bindings.map((binding, index) => ({
    ...binding,
    id: `${binding.id}-${options.suffix}`,
    projectId: options.id,
    nodeId: options.currentNodeId,
    documentId: workspace.documents[index % workspace.documents.length]?.id || binding.documentId,
    documentVersionId:
      workspace.documents[index % workspace.documents.length]?.currentVersionId ||
      binding.documentVersionId
  }))
  workspace.submissions = workspace.submissions.map((submission, index) => ({
    ...submission,
    id: `${submission.id}-${options.suffix}-${index + 1}`,
    status: options.reviewRunStatus || submission.status,
    nodeIds: [options.currentNodeId],
    nodeNames: [workspace.selectedNode?.name || '审计节点']
  }))
  workspace.reviewRuns = workspace.reviewRuns.map((run, index) => ({
    ...run,
    id: `RR-DEMO-${options.suffix}-${index + 1}`,
    reviewRunId: `RR-DEMO-${options.suffix}-${index + 1}`,
    projectId: options.id,
    nodeId: String(options.currentNodeId),
    workflowId: `wf-review-${options.suffix}-${index + 1}`,
    status: options.reviewRunStatus || run.status,
    currentStep: options.reviewRunStatus || run.currentStep
  }))
  workspace.ocrJobs = workspace.ocrJobs.map((job, index) => ({
    ...job,
    id: `OCR-JOB-DEMO-${options.suffix}-${index + 1}`,
    jobId: `OCR-JOB-DEMO-${options.suffix}-${index + 1}`,
    documentVersionId: workspace.documents[index % workspace.documents.length]?.currentVersionId,
    status: index === 0 ? options.ocrStatus || job.status : job.status
  }))
  workspace.ocrAnnotationTasks = workspace.ocrAnnotationTasks.map((task, index) => ({
    ...task,
    taskId: `ANNO-DEMO-${options.suffix}-${index + 1}`,
    caseId: `OCR-DEMO-${options.suffix}-${index + 1}`,
    projectId: options.id,
    nodeId: options.currentNodeId
  }))
  workspace.qualityBlockers =
    options.blockerCount > 0
      ? [
          {
            type: options.reviewRunStatus === 'failed' ? 'agent' : 'ocr-annotation',
            level: options.reviewRunStatus === 'failed' ? 'danger' : 'warning',
            title: options.blockerTitle || '存在待处理质量阻断',
            targetId: workspace.reviewRuns[0]?.reviewRunId || workspace.ocrJobs[0]?.jobId,
            targetName: workspace.selectedNode?.name,
            action: '进入对应审计子页检查证据、结果和人工修正。'
          }
        ]
      : []
  workspace.metrics = {
    ...workspace.metrics,
    blockers: workspace.qualityBlockers.length,
    reviewRuns: workspace.reviewRuns.length,
    ocrJobs: workspace.ocrJobs.length,
    annotationTasks: workspace.ocrAnnotationTasks.length,
    documents: workspace.documents.length
  }
  workspace.updatedAt = workspace.project.updatedAt
  return workspace
}

const getSelectedDemoWorkspace = (projectId: string, nodeId?: number) => {
  const workspace =
    fdeDemoProjectWorkspaces.value.find((item) => item.project.id === projectId) ||
    fdeDemoProjectWorkspaces.value[0]
  if (!workspace) return null
  const allNodes = workspace.groups.flatMap((group) => group.nodes)
  const selectedNode =
    allNodes.find((node) => Number(node.nodeId) === Number(nodeId || workspace.selectedNodeId)) ||
    allNodes[0] ||
    null
  return {
    ...workspace,
    selectedNodeId: selectedNode?.nodeId,
    selectedNode
  }
}

const createDemoOcrRunDetail = (jobId = 'OCR-JOB-DEMO-001'): FdeOcrRunDetailPayload => ({
  job: {
    id: jobId,
    jobId,
    parseResultId: `parse-${jobId.toLowerCase()}`,
    resultSummary: { fieldCount: 18, tableCount: 2, sealCount: 1 },
    engineRuns: [
      {
        engine: 'pp_structure_v3',
        status: 'success',
        durationMs: 2840,
        engineCacheHit: false,
        variantCacheHit: true
      },
      {
        engine: 'paddlex_seal',
        status: 'success',
        durationMs: 1980,
        engineCacheHit: true,
        variantCacheHit: true
      }
    ]
  },
  parseResult: {
    preprocessStatus: {
      requestedVariants: ['original', 'deskew', 'table_line_enhanced', 'seal_color_crop'],
      generatedVariants: ['original', 'deskew', 'table_line_enhanced', 'seal_color_crop'],
      missingVariants: []
    },
    engineRuns: [
      {
        engine: 'pp_structure_v3',
        status: 'success',
        durationMs: 2840,
        engineCacheHit: false,
        variantCacheHit: true
      },
      {
        engine: 'paddlex_seal',
        status: 'success',
        durationMs: 1980,
        engineCacheHit: true,
        variantCacheHit: true
      }
    ]
  },
  corrections: [
    {
      fieldCode: 'material_grade',
      before: 'GC?',
      after: 'GC2',
      rootCause: 'low_contrast_scan'
    }
  ]
})

const applyFdeDemoData = () => {
  const demoReview = createDemoReviewRunDetail()
  const demoWorkspace = createDemoProjectAuditWorkspace()
  const agentWorkspace = createDemoProjectAuditWorkspaceVariant(demoWorkspace, {
    suffix: 'AGENT',
    id: 'DEMO-PROJECT-AGENT',
    code: 'QC-AUDIT-2026-017',
    name: '佛山压力管道资料复核项目',
    type: '资料审查 AI 复核',
    status: 'AI 预审中',
    region: '广东省佛山市',
    currentNodeId: 211,
    blockerCount: 1,
    blockerTitle: 'Agent 证据 bbox 与表格单元格不一致',
    reviewRunStatus: 'waiting_human_review',
    ocrStatus: '已识别'
  })
  const readyWorkspace = createDemoProjectAuditWorkspaceVariant(demoWorkspace, {
    suffix: 'READY',
    id: 'DEMO-PROJECT-READY',
    code: 'ARCHIVE-2026-008',
    name: '惠州装置资料归档验收项目',
    type: '资料归档验收',
    status: '报告生成/复核中',
    region: '广东省惠州市',
    currentNodeId: 221,
    blockerCount: 0,
    reviewRunStatus: 'completed',
    ocrStatus: '已识别'
  })
  fdeDemoProjectWorkspaces.value = [demoWorkspace, agentWorkspace, readyWorkspace]
  reviewRuns.value = [
    ...fdeDemoProjectWorkspaces.value.flatMap((workspace) => workspace.reviewRuns),
    {
      ...demoReview.run,
      id: 'RR-DEMO-002',
      reviewRunId: 'RR-DEMO-002',
      workflowId: 'wf-review-demo-002',
      status: 'completed',
      currentStep: 'draft_persisted',
      updatedAt: '2026-06-29 10:26:05'
    }
  ]
  selectedReviewRun.value = demoReview
  projectAuditWorkspace.value = demoWorkspace
  fdeProjects.value = fdeDemoProjectWorkspaces.value.map((workspace) => ({
    project: workspace.project,
    metrics: workspace.metrics,
    currentNodeId: workspace.selectedNodeId,
    currentNodeName: workspace.selectedNode?.name,
    topBlockers: workspace.qualityBlockers.slice(0, 3),
    updatedAt: workspace.updatedAt
  }))
  selectedFdeProjectId.value = demoWorkspace.project.id
  selectedFdeNodeId.value = demoWorkspace.selectedNodeId
  ocrQuality.value = createDemoOcrQuality()
  ocrAnnotation.value = createDemoOcrAnnotationPayload()
  ocrRuns.value = [
    {
      id: 'OCR-JOB-DEMO-001',
      jobId: 'OCR-JOB-DEMO-001',
      status: 'success',
      profileId: 'piping_characteristic_list_v1',
      parseResultId: 'parse-demo-001',
      engineRuns: 4
    },
    {
      id: 'OCR-JOB-DEMO-002',
      jobId: 'OCR-JOB-DEMO-002',
      status: 'needs_human_review',
      profileId: 'seal_text_profile_v1',
      parseResultId: 'parse-demo-002',
      engineRuns: 3
    }
  ]
  selectedOcrRun.value = createDemoOcrRunDetail()
}

const ensureFdeDemoData = () => {
  if (!fdeDemoMode.value || !fdeDemoProjectWorkspaces.value.length) {
    fdeDemoMode.value = true
    applyFdeDemoData()
  }
}

const fdeTopStats = computed(() => [
  { label: '项目', value: fdeProjects.value.length || 0, tone: 'blue' as const },
  { label: 'ReviewRun', value: reviewRuns.value.length || 0, tone: 'green' as const },
  { label: 'OCR任务', value: ocrAnnotationRows.value.length || 0, tone: 'orange' as const }
])

const fdeShellRightCards = computed(() => [
  {
    title: '当前项目',
    rows: [
      { label: '项目', value: selectedFdeProject.value?.name || '-' },
      { label: '节点', value: projectAuditWorkspace.value?.selectedNode?.name || '-' },
      {
        label: '状态',
        value: friendlyStatus(selectedFdeProject.value?.status, '-'),
        valueTone: projectAuditBlockers.value.length ? ('orange' as const) : ('green' as const)
      },
      {
        label: '阻断',
        value: String(projectAuditBlockers.value.length),
        valueTone: projectAuditBlockers.value.length ? ('red' as const) : ('green' as const)
      }
    ]
  },
  {
    title: 'Agent 编排',
    rows: [
      { label: 'Review Run', value: String(reviewRuns.value.length) },
      { label: 'Graph 节点', value: String(reviewGraphNodes.value.length) },
      {
        label: '校验失败',
        value: String(recordNumber(reviewArtifactSummary.value, 'validationFailures'))
      },
      {
        label: 'Temporal 事件',
        value: String(selectedReviewTemporal.value.eventCount || reviewGraphTimeline.value.length)
      }
    ]
  },
  {
    title: 'OCR 质量与标注',
    rows: [
      { label: 'OCR Run', value: String(ocrRuns.value.length) },
      { label: '标注任务', value: String(ocrAnnotationRows.value.length) },
      {
        label: '最近评估',
        value: latestOcrEvalOk.value ? '通过' : '待改进',
        valueBadge: String(latestOcrEvalCaseTotal.value || 0),
        valueTone: latestOcrEvalOk.value ? ('green' as const) : ('orange' as const)
      },
      {
        label: '综合分',
        value: ocr100Scorecard.value
          ? `${ocr100Scorecard.value.score}/${ocr100Scorecard.value.targetScore}`
          : '-'
      }
    ]
  },
  {
    title: '当前策略',
    note: 'FDE 面板暂时只展示 OCR 和 Agent 编排；其它治理模块保留路由但从导航隐藏。'
  }
])

const metricTone = (label: string, index: number) => {
  if (/失败|风险|幻觉|告警|异常/.test(label)) return 'red'
  if (/采纳|证据|通过|成功|命中/.test(label)) return 'green'
  if (/成本|预算|Token|待审批|重试/.test(label)) return 'orange'
  return index % 4 === 1 ? 'green' : index % 4 === 2 ? 'orange' : 'blue'
}

const dashboardMetricCards = computed(() =>
  (dashboard.value?.metrics || []).map((metric, index) => ({
    ...metric,
    tone: metricTone(String(metric.label || ''), index)
  }))
)

const fdeWorkflowCards = computed(() => [
  {
    title: 'Agent 审查编排',
    description: '检查 Temporal Workflow、LangGraph 节点、工具调用、规则和检索产物。',
    route: '/fde/review-runs',
    action: '看编排',
    tone: 'green',
    metric: String(reviewRuns.value.length)
  },
  {
    title: '标定 OCR 样本',
    description: '补齐字段、表格和印章 bbox，让 OCR 评估集可用。',
    route: '/fde/ocr-quality',
    action: '去标注',
    tone: 'green',
    metric: `${ocrAnnotationSummary.value?.humanLabeled || 0}/${ocrAnnotationSummary.value?.tasks || 0}`
  }
])

const selectedFdeProject = computed(
  () =>
    projectAuditWorkspace.value?.project ||
    fdeProjects.value.find((item) => item.project.id === selectedFdeProjectId.value)?.project ||
    null
)

const projectAuditNodeRows = computed(
  () => (projectAuditWorkspace.value?.nodeSummaries || []) as Array<Record<string, unknown>>
)
const projectAuditBindings = computed(() => projectAuditWorkspace.value?.bindings || [])
const projectAuditDocuments = computed(() => projectAuditWorkspace.value?.documents || [])
const projectAuditSubmissions = computed(
  () => (projectAuditWorkspace.value?.submissions || []) as Array<Record<string, unknown>>
)
const projectAuditReviewRuns = computed(() => projectAuditWorkspace.value?.reviewRuns || [])
const projectAuditOcrJobs = computed(
  () => (projectAuditWorkspace.value?.ocrJobs || []) as Array<Record<string, unknown>>
)
const projectAuditAnnotationTasks = computed(
  () => (projectAuditWorkspace.value?.ocrAnnotationTasks || []) as Array<Record<string, unknown>>
)
const projectAuditBlockers = computed(
  () => (projectAuditWorkspace.value?.qualityBlockers || []) as Array<Record<string, unknown>>
)
const projectAuditNodeOptions = computed(() =>
  (projectAuditWorkspace.value?.groups || []).flatMap((group) =>
    group.nodes.map((node) => ({
      label: `${group.groupName} / ${node.name}`,
      value: node.nodeId,
      status: node.status
    }))
  )
)
const selectedProjectAuditNodeSummary = computed(() => {
  const nodeId = Number(projectAuditWorkspace.value?.selectedNodeId || selectedFdeNodeId.value || 0)
  return projectAuditNodeRows.value.find((item) => Number(item.nodeId) === nodeId) || null
})
const projectAuditMetrics = computed(() => projectAuditWorkspace.value?.metrics || {})
const projectAuditMetricCards = computed(() => [
  {
    label: '项目节点',
    value: String(projectAuditMetrics.value.nodes || projectAuditNodeRows.value.length || 0),
    hint: `当前节点：${shortText(projectAuditWorkspace.value?.selectedNode?.name, '未选择')}`,
    tone: 'blue'
  },
  {
    label: '资料文件',
    value: String(projectAuditMetrics.value.documents || projectAuditDocuments.value.length || 0),
    hint: `挂载 ${projectAuditBindings.value.length} 条`,
    tone: 'green'
  },
  {
    label: '提交批次',
    value: String(
      projectAuditMetrics.value.submissions || projectAuditSubmissions.value.length || 0
    ),
    hint: '按节点过滤展示',
    tone: 'blue'
  },
  {
    label: 'Agent任务',
    value: String(projectAuditMetrics.value.reviewRuns || projectAuditReviewRuns.value.length || 0),
    hint: `当前选中 ${selectedProjectAuditNodeSummary.value?.reviewRunCount || 0} 条`,
    tone: 'green'
  },
  {
    label: 'OCR任务',
    value: String(projectAuditMetrics.value.ocrJobs || projectAuditOcrJobs.value.length || 0),
    hint: `标注样本 ${projectAuditAnnotationTasks.value.length}`,
    tone: 'orange'
  },
  {
    label: '质量阻断',
    value: String(projectAuditMetrics.value.blockers || projectAuditBlockers.value.length || 0),
    hint: `低置信字段 ${projectAuditMetrics.value.lowConfidenceFields || 0}`,
    tone: projectAuditBlockers.value.length ? 'red' : 'green'
  }
])

const projectAuditVectorRows = computed(() =>
  projectAuditDocuments.value.map((document, index) => {
    const raw = document as Record<string, unknown>
    const ocrJob =
      projectAuditOcrJobs.value.find(
        (job) => String(job.documentVersionId || '') === String(document.currentVersionId || '')
      ) || projectAuditOcrJobs.value[index]
    const binding =
      projectAuditBindings.value.find(
        (item) => String(item.documentVersionId || '') === String(document.currentVersionId || '')
      ) || projectAuditBindings.value[index]
    const chunkCount = Number(raw.chunkCount ?? raw.knowledgeChunkCount ?? 0)
    const vectorCount = Number(raw.vectorCount ?? raw.embeddingCount ?? 0)
    return {
      id: document.id,
      fileName: document.fileName,
      requirementName: binding?.requirementName || raw.requirementName || '-',
      documentVersionId: document.currentVersionId,
      ocrStatus: document.currentOcrStatus,
      sliceStatus: raw.sliceStatus || (chunkCount > 0 ? '已切片' : '待切片'),
      vectorStatus:
        raw.vectorStatus ||
        (vectorCount > 0
          ? '已向量化'
          : document.currentOcrStatus === '已识别'
            ? '待向量化'
            : '等待OCR'),
      chunkCount,
      vectorCount,
      embeddingModel: raw.embeddingModel || raw.modelAlias || 'embedding-default',
      indexVersion: raw.indexVersion || raw.vectorIndexVersion || 'knowledge-index@local',
      vectorDimensions: Number(raw.vectorDimensions || 3072),
      pageIndexStatus: raw.pageIndexStatus || (chunkCount > 0 ? '可构建' : '等待切片'),
      pageIndexNodeCount: Number(raw.pageIndexNodeCount || 0),
      latestTask: raw.latestTask || raw.latestKnowledgeTask || ocrJob?.status || '-',
      updatedAt: document.updatedAt
    }
  })
)

const normalizedProjectAuditVectorRows = computed(() =>
  projectAuditVectorRows.value.map((row, index) => {
    const item = toRecord(row)
    const chunkCount = Number(item.chunkCount || 0)
    const vectorCount = Number(item.vectorCount || 0)
    const pageIndexNodeCount = Number(item.pageIndexNodeCount || 0)
    const ocrStatus = String(item.ocrStatus || '')
    const sliceStatus = String(item.sliceStatus || '')
    const vectorStatus = String(item.vectorStatus || '')
    const pageIndexStatus = String(item.pageIndexStatus || '')
    const latestTask = item.latestTask
    const vectorGap = Math.max(0, chunkCount - vectorCount)
    const readyForRag = vectorCount > 0 && vectorStatus.includes('已向量化')
    const readyForPageIndex = pageIndexNodeCount > 0 || pageIndexStatus.includes('已构建')
    let issue = '无'
    let action = '保持索引版本，纳入审查评估'

    if (!ocrStatus.includes('已识别') && !ocrStatus.includes('人工修正')) {
      issue = 'OCR 未完成'
      action = '先完成 OCR 或进入人工标注'
    } else if (!sliceStatus.includes('已切片')) {
      issue = '知识切片未完成'
      action = '重跑 knowledge.slice'
    } else if (!readyForRag) {
      issue = '向量入库未完成'
      action = '重跑 knowledge.embed'
    } else if (vectorGap > 0) {
      issue = '向量条目少于切片'
      action = '排查失败 chunk 并补跑 embedding'
    } else if (!readyForPageIndex) {
      issue = 'PageIndex 未构建'
      action = '构建 PageIndex tree 后再用于长文档溯源'
    }

    return {
      ...item,
      id: item.id || `vector-row-${index + 1}`,
      fileName: item.fileName || '-',
      requirementName: item.requirementName || '-',
      documentVersionId: item.documentVersionId || '-',
      ocrStatus: item.ocrStatus || '-',
      sliceStatus: item.sliceStatus || '-',
      vectorStatus: item.vectorStatus || '-',
      embeddingModel: item.embeddingModel || 'embedding-default',
      indexVersion: item.indexVersion || 'knowledge-index@local',
      pageIndexStatus: item.pageIndexStatus || '-',
      rowIndex: index + 1,
      chunkCount,
      vectorCount,
      pageIndexNodeCount,
      vectorDimensions: Number(item.vectorDimensions || 3072),
      vectorGap,
      readyForRag,
      readyForPageIndex,
      readinessLabel: readyForRag && readyForPageIndex ? '可用于审查' : '需补齐',
      issue,
      action,
      latestTaskText: friendlyStatus(latestTask, '-')
    }
  })
)

const projectAuditVectorIssueRows = computed(() =>
  normalizedProjectAuditVectorRows.value.filter((row) => row.issue !== '无')
)

const projectAuditVectorIndexProfile = computed(() => {
  const rows = normalizedProjectAuditVectorRows.value
  const first = rows[0] || {}
  const readyForRagCount = rows.filter((row) => row.readyForRag).length
  const readyForPageIndexCount = rows.filter((row) => row.readyForPageIndex).length
  const issueCount = projectAuditVectorIssueRows.value.length
  return {
    embeddingModel: first.embeddingModel || 'embedding-default',
    indexVersion: first.indexVersion || 'knowledge-index@local',
    vectorDimensions: first.vectorDimensions || 3072,
    chunkPolicy: '按资料 Profile 切片，保留页码、bbox、表格和印章证据',
    ragReady: `${readyForRagCount}/${rows.length}`,
    pageIndexReady: `${readyForPageIndexCount}/${rows.length}`,
    issueSummary: issueCount ? `${issueCount} 个资料需处理` : '全部资料可进入审查'
  }
})

const projectAuditVectorCards = computed(() => {
  const rows = normalizedProjectAuditVectorRows.value
  const chunkCount =
    Number(projectAuditMetrics.value.knowledgeChunks || 0) ||
    rows.reduce((total, row) => total + Number(row.chunkCount || 0), 0)
  const vectorCount =
    Number(projectAuditMetrics.value.knowledgeVectors || 0) ||
    rows.reduce((total, row) => total + Number(row.vectorCount || 0), 0)
  const readyCount =
    Number(projectAuditMetrics.value.vectorizedDocuments || 0) ||
    rows.filter((row) => String(row.vectorStatus).includes('已向量化')).length
  const pageIndexNodeCount =
    Number(projectAuditMetrics.value.pageIndexNodes || 0) ||
    rows.reduce((total, row) => total + Number(row.pageIndexNodeCount || 0), 0)
  const issueCount = projectAuditVectorIssueRows.value.length
  return [
    {
      label: '资料版本',
      value: String(rows.length),
      hint: '当前项目纳入向量化的资料',
      tone: 'blue'
    },
    {
      label: '知识切片',
      value: String(chunkCount),
      hint: '用于 Hybrid RAG / PageIndex',
      tone: 'green'
    },
    {
      label: '向量条目',
      value: String(vectorCount),
      hint: 'Embedding 入库数量',
      tone: vectorCount ? 'green' : 'orange'
    },
    {
      label: 'PageIndex',
      value: String(pageIndexNodeCount),
      hint: `${readyCount}/${rows.length} 个资料已向量化`,
      tone: pageIndexNodeCount ? 'green' : 'orange'
    },
    {
      label: '入库缺口',
      value: String(issueCount),
      hint: issueCount ? '需要补跑或人工标注' : '可进入审查编排',
      tone: issueCount ? 'red' : 'green'
    }
  ]
})

const projectAuditPageIndexTraceRows = computed<Array<Record<string, unknown>>>(() =>
  reviewRetrievalTraceRows.value.map((trace, index) => {
    const item = toRecord(trace)
    const queryRouter = toRecord(item.queryRouter)
    const pageIndexTree = toRecord(item.pageIndexTree)
    const selectedNodes = toRecordArray(pageIndexTree.selectedNodes)
    const retrievalTraceId = String(item.retrievalTraceId || `retrieval-${index + 1}`)
    const selectedRoute = String(item.selectedRoute || queryRouter.selectedRoute || '-')
    const fallbackRoute = String(queryRouter.fallbackRoute || item.fallbackRoute || '-')
    const queryType = String(item.queryType || '-')
    const pageIndexUsed = selectedRoute.toLowerCase().includes('pageindex')
    const shouldUsePageIndex =
      pageIndexUsed ||
      queryType.toLowerCase().includes('long_document') ||
      queryType.includes('跨章节') ||
      String(item.query || '').includes('跨章节')
    const selectedClauseCount =
      Number(item.selectedClauseCount || 0) ||
      toRecordArray(item.selectedClauses).length ||
      toRecordArray(item.selectedClauseIds).length
    const pageIndexNodeCount =
      Number(item.pageIndexNodeCount || pageIndexTree.candidateNodeCount || 0) ||
      selectedNodes.length
    let issue = '无'
    let action = '保留当前路由，纳入检索评估'

    if (selectedClauseCount <= 0) {
      issue = '未命中依据条款'
      action = '补充条款索引或检查 metadata filter'
    } else if (pageIndexUsed && pageIndexNodeCount <= 0) {
      issue = '已触发 PageIndex 但缺少节点'
      action = '重建 PageIndex tree 并校验节点映射'
    } else if (shouldUsePageIndex && !pageIndexUsed) {
      issue = '长文档问题未触发 PageIndex'
      action = '检查 Query Router 或增加触发规则'
    } else if (fallbackRoute !== '-') {
      issue = '存在 fallback 路由'
      action = '对比 PageIndex 与 Hybrid RAG 命中质量'
    }

    return {
      id: retrievalTraceId,
      retrievalTraceId,
      query: item.query || '-',
      queryType,
      selectedRoute,
      fallbackRoute,
      routerReason: queryRouter.reason || item.routerReason || '-',
      selectedClauseCount,
      pageIndexNodeCount,
      pageIndexUsed,
      shouldUsePageIndex,
      routeDecision: pageIndexUsed
        ? '已触发 PageIndex'
        : shouldUsePageIndex
          ? '应触发未触发'
          : '未触发',
      issue,
      action,
      linkedClauseIds: item.selectedClauseIds || pageIndexTree.linkedClauseIds || '-',
      selectedNodes
    }
  })
)

const projectAuditPageIndexNodeRows = computed<Array<Record<string, unknown>>>(() =>
  projectAuditPageIndexTraceRows.value.flatMap((trace) => {
    const selectedNodes = toRecordArray(trace.selectedNodes)
    const retrievalTraceId = String(trace.retrievalTraceId || '-')
    return selectedNodes.length
      ? selectedNodes.map((node, index) => ({
          traceId: retrievalTraceId,
          nodeId: String(node.nodeId || node.pageIndexNodeId || `${retrievalTraceId}-${index + 1}`),
          title: String(node.title || '-'),
          sectionPath: Array.isArray(node.sectionPath)
            ? node.sectionPath.join(' / ')
            : String(node.sectionPath || '-'),
          pageRange:
            node.startPage || node.endPage
              ? `${String(node.startPage || '-')}-${String(node.endPage || '-')}`
              : '-',
          linkedClauseIds: Array.isArray(node.linkedClauseIds)
            ? node.linkedClauseIds.join('、')
            : String(node.linkedClauseIds || '-'),
          score: node.score
        }))
      : [
          {
            traceId: retrievalTraceId,
            nodeId: '-',
            title:
              String(trace.selectedRoute).toLowerCase() === 'pageindex'
                ? '已触发 PageIndex，但后端未返回节点明细'
                : '未触发 PageIndex',
            sectionPath: '-',
            pageRange: '-',
            linkedClauseIds: shortText(trace.linkedClauseIds),
            score: undefined
          }
        ]
  })
)

const projectAuditPageIndexCoverageRows = computed(() =>
  normalizedProjectAuditVectorRows.value.map((row) => ({
    ...row,
    coverageStatus: row.readyForPageIndex ? '已构建' : '待构建',
    coverageIssue: row.readyForPageIndex ? '无' : '资料未形成 PageIndex 节点',
    coverageAction: row.readyForPageIndex ? '可参与长文档溯源' : '先完成切片和 PageIndex tree 构建'
  }))
)

const projectAuditPageIndexIssueRows = computed(() => {
  const traceIssues = projectAuditPageIndexTraceRows.value
    .filter((row) => row.issue !== '无')
    .map((row) => ({
      object: row.retrievalTraceId,
      issue: row.issue,
      action: row.action,
      source: '检索路由'
    }))
  const coverageIssues = projectAuditPageIndexCoverageRows.value
    .filter((row) => row.coverageIssue !== '无')
    .map((row) => ({
      object: row.fileName,
      issue: row.coverageIssue,
      action: row.coverageAction,
      source: '资料覆盖'
    }))
  return [...traceIssues, ...coverageIssues]
})

const projectAuditPageIndexCards = computed(() => {
  const traces = projectAuditPageIndexTraceRows.value
  const triggered = traces.filter((row) => row.pageIndexUsed).length
  const expected = traces.filter((row) => row.shouldUsePageIndex).length
  const nodes = projectAuditPageIndexNodeRows.value.filter((row) => row.nodeId !== '-').length
  const mappedClauses = traces.reduce(
    (total, row) => total + Number(row.selectedClauseCount || 0),
    0
  )
  const coveredDocuments = projectAuditPageIndexCoverageRows.value.filter(
    (row) => row.readyForPageIndex
  ).length
  return [
    {
      label: 'PageIndex 触发',
      value: String(triggered),
      hint: `应触发 ${expected} 条检索`,
      tone: triggered >= expected ? 'green' : 'orange'
    },
    {
      label: '命中节点',
      value: String(nodes),
      hint: '映射到章节树节点',
      tone: nodes ? 'green' : 'orange'
    },
    {
      label: '依据条款',
      value: String(mappedClauses),
      hint: 'Trace 关联条款数量',
      tone: mappedClauses ? 'blue' : 'red'
    },
    {
      label: '资料覆盖',
      value: `${coveredDocuments}/${projectAuditPageIndexCoverageRows.value.length}`,
      hint: '已构建 PageIndex 的资料',
      tone: coveredDocuments ? 'green' : 'orange'
    },
    {
      label: '处理项',
      value: String(projectAuditPageIndexIssueRows.value.length),
      hint: projectAuditPageIndexIssueRows.value.length ? '需补构建或评估' : '暂无异常',
      tone: projectAuditPageIndexIssueRows.value.length ? 'red' : 'green'
    }
  ]
})

const projectAuditLangGraphCards = computed(() => [
  {
    label: 'Graph 节点',
    value: String(reviewGraphNodes.value.length),
    hint: 'LangGraph 内层执行节点',
    tone: reviewGraphNodes.value.length ? 'green' : 'orange'
  },
  {
    label: 'Graph 边',
    value: String(reviewGraphEdges.value.length),
    hint: '节点依赖关系',
    tone: 'blue'
  },
  {
    label: 'Temporal 事件',
    value: String(selectedReviewTemporal.value.eventCount || reviewGraphTimeline.value.length || 0),
    hint: '外层持久化 Workflow',
    tone: 'green'
  },
  {
    label: 'Checkpoint',
    value: shortText(selectedReviewRun.value?.run.graphExecution?.checkpointer, '-'),
    hint: '本地开发态建议 PostgreSQL checkpointer',
    tone: selectedReviewRun.value?.run.graphExecution?.checkpointer ? 'green' : 'orange'
  },
  {
    label: '质量门禁',
    value: shortText(reviewQualityEvaluation.value.score, '0'),
    hint: friendlyStatus(reviewQualityEvaluation.value.status, '未知'),
    tone: reviewQualityEvaluation.value.status === 'pass' ? 'green' : 'orange'
  },
  {
    label: '链路缺口',
    value: String(projectAuditLangGraphIssueRows.value.length),
    hint: projectAuditLangGraphIssueRows.value.length ? '需补齐编排证据' : '链路证据完整',
    tone: projectAuditLangGraphIssueRows.value.length ? 'red' : 'green'
  }
])

const normalizedProjectAuditAnnotationRows = computed(() =>
  projectAuditAnnotationTasks.value.map((row, index) => {
    const item = toRecord(row)
    const candidateCounts = toRecord(item.candidateCounts)
    const labelCounts = toRecord(item.labelCounts)
    const candidateTotal =
      Number(candidateCounts.fields || 0) +
      Number(candidateCounts.tables || 0) +
      Number(candidateCounts.seals || 0)
    const labelTotal =
      Number(labelCounts.fields || 0) +
      Number(labelCounts.tables || 0) +
      Number(labelCounts.seals || 0)
    const readinessBlockers = Array.isArray(item.readinessBlockers)
      ? item.readinessBlockers
      : item.readinessBlockers
        ? [item.readinessBlockers]
        : []
    const certificationBlockers = Array.isArray(item.certificationBlockers)
      ? item.certificationBlockers
      : item.certificationBlockers
        ? [item.certificationBlockers]
        : []
    const blockers = [...readinessBlockers, ...certificationBlockers].filter(Boolean)
    return {
      ...item,
      rowIndex: index + 1,
      taskId: item.taskId,
      caseId: item.caseId,
      scenario: item.scenario,
      profileId: item.profileId,
      pageNo: item.pageNo,
      collectionStatus: item.collectionStatus,
      candidateFields: Number(candidateCounts.fields || 0),
      candidateTables: Number(candidateCounts.tables || 0),
      candidateSeals: Number(candidateCounts.seals || 0),
      labelFields: Number(labelCounts.fields || 0),
      labelTables: Number(labelCounts.tables || 0),
      labelSeals: Number(labelCounts.seals || 0),
      candidateTotal,
      labelTotal,
      gapTotal: Math.max(0, candidateTotal - labelTotal),
      blockerText: blockers.length ? blockers.map((item) => shortText(item, '')).join('；') : '无',
      readyForEval: Boolean(item.readyForEval)
    }
  })
)

const projectAuditAnnotationSummary = computed(() => {
  const rows = normalizedProjectAuditAnnotationRows.value
  const total = rows.length
  const humanLabeled = rows.filter(
    (row) => String(row.collectionStatus || '') !== 'needs_labeling'
  ).length
  const readyForEval = rows.filter((row) => row.readyForEval).length
  const candidateTotal = rows.reduce((sum, row) => sum + Number(row.candidateTotal || 0), 0)
  const labelTotal = rows.reduce((sum, row) => sum + Number(row.labelTotal || 0), 0)
  return {
    total,
    humanLabeled,
    readyForEval,
    missingHumanLabels: Math.max(0, total - humanLabeled),
    candidateTotal,
    labelTotal,
    gapTotal: Math.max(0, candidateTotal - labelTotal),
    completionRate: total ? humanLabeled / total : 0
  }
})

const projectAuditAnnotationCoverageRows = computed(() => {
  const rows = normalizedProjectAuditAnnotationRows.value
  const build = (
    label: string,
    candidateKey: 'candidateFields' | 'candidateTables' | 'candidateSeals',
    labelKey: 'labelFields' | 'labelTables' | 'labelSeals'
  ) => {
    const candidates = rows.reduce((sum, row) => sum + Number(row[candidateKey] || 0), 0)
    const labeled = rows.reduce((sum, row) => sum + Number(row[labelKey] || 0), 0)
    return {
      label,
      candidates,
      labeled,
      gap: Math.max(0, candidates - labeled),
      coverage: candidates ? labeled / candidates : 1
    }
  }
  return [
    build('字段', 'candidateFields', 'labelFields'),
    build('表格', 'candidateTables', 'labelTables'),
    build('印章', 'candidateSeals', 'labelSeals')
  ]
})

const projectAuditAnnotationBlockerRows = computed(() => {
  const counts: Record<string, number> = {}
  for (const row of normalizedProjectAuditAnnotationRows.value) {
    const blockers = String(row.blockerText || '')
      .split('；')
      .map((item) => item.trim())
      .filter((item) => item && item !== '无')
    for (const blocker of blockers) {
      counts[blocker] = (counts[blocker] || 0) + 1
    }
  }
  return Object.entries(counts)
    .map(([blocker, count]) => ({ blocker, count }))
    .sort((left, right) => right.count - left.count)
})

const projectAuditAnnotationHealthRows = computed(() => {
  const summary = projectAuditAnnotationSummary.value
  const coverage = projectAuditAnnotationCoverageRows.value
  const minCoverage = coverage.length
    ? Math.min(...coverage.map((row) => Number(row.coverage || 0)))
    : 0
  const blockerCount = projectAuditAnnotationBlockerRows.value.reduce(
    (total, row) => total + Number(row.count || 0),
    0
  )
  return [
    {
      item: '样本数量',
      status: summary.total > 0 ? '通过' : '需补齐',
      evidence: `${summary.total} 个 OCR 标注样本`,
      action: summary.total > 0 ? '可继续检查覆盖率' : '从 OCR 任务生成标注样本',
      passed: summary.total > 0
    },
    {
      item: '人工标注完成',
      status: summary.missingHumanLabels ? '需补齐' : '通过',
      evidence: `${summary.humanLabeled}/${summary.total} 已人工标注`,
      action: summary.missingHumanLabels ? '优先完成 needs_labeling 样本' : '可进入二审或评估',
      passed: summary.missingHumanLabels === 0
    },
    {
      item: '字段/表格/印章覆盖',
      status: summary.gapTotal ? '存在缺口' : '通过',
      evidence: `最低覆盖率 ${scorePercent(minCoverage)}，缺口 ${summary.gapTotal}`,
      action: summary.gapTotal ? '补标低覆盖对象并确认 bbox' : '覆盖率可用于回归评估',
      passed: summary.gapTotal === 0
    },
    {
      item: '可入评估集',
      status: summary.readyForEval ? '有可用样本' : '暂无',
      evidence: `${summary.readyForEval}/${summary.total} 可入 OCR Regression Set`,
      action: summary.readyForEval ? '归档到评估集并绑定 Profile 版本' : '先完成标注和阻断归因',
      passed: summary.readyForEval > 0
    },
    {
      item: '阻断归因',
      status: blockerCount ? '需处理' : '通过',
      evidence: `${blockerCount} 个阻断原因`,
      action: blockerCount ? '处理低置信、缺 bbox、缺章等阻断' : '样本无阻断',
      passed: blockerCount === 0
    }
  ]
})

const projectAuditAnnotationIssueRows = computed(() => {
  const sampleIssues = normalizedProjectAuditAnnotationRows.value
    .filter((row) => row.gapTotal || !row.readyForEval || row.blockerText !== '无')
    .map((row) => ({
      object: row.taskId || row.caseId || row.scenario,
      issue: row.gapTotal ? `缺 ${row.gapTotal} 个标注对象` : row.blockerText,
      action: row.readyForEval ? '二审后进入评估集' : '补齐人工标注、bbox 和阻断归因',
      source: '标注样本'
    }))
  const coverageIssues = projectAuditAnnotationCoverageRows.value
    .filter((row) => row.gap)
    .map((row) => ({
      object: row.label,
      issue: `覆盖率 ${scorePercent(row.coverage)}，缺口 ${row.gap}`,
      action: `补标${row.label}候选并复核证据定位`,
      source: '覆盖率'
    }))
  return [...sampleIssues, ...coverageIssues]
})

const projectAuditOcrLabelCards = computed(() => [
  {
    label: '标注样本',
    value: String(projectAuditAnnotationSummary.value.total),
    hint: '当前项目/节点 OCR 样本',
    tone: 'blue'
  },
  {
    label: '已人工标注',
    value: String(projectAuditAnnotationSummary.value.humanLabeled),
    hint: `完成率 ${scorePercent(projectAuditAnnotationSummary.value.completionRate)}`,
    tone: projectAuditAnnotationSummary.value.missingHumanLabels ? 'orange' : 'green'
  },
  {
    label: '可入评估',
    value: String(projectAuditAnnotationSummary.value.readyForEval),
    hint: '可进入 OCR Regression Set',
    tone: projectAuditAnnotationSummary.value.readyForEval ? 'green' : 'orange'
  },
  {
    label: '标注缺口',
    value: String(projectAuditAnnotationSummary.value.gapTotal),
    hint: `${projectAuditAnnotationSummary.value.labelTotal}/${projectAuditAnnotationSummary.value.candidateTotal} 已标`,
    tone: projectAuditAnnotationSummary.value.gapTotal ? 'red' : 'green'
  }
])

const projectAuditEvaluationGateRows = computed(() => {
  const summary = latestEvaluationCaseSummary.value
  const buildRatioGate = (
    item: string,
    actual: number,
    target: number,
    direction: 'gte' | 'lte',
    action: string
  ) => {
    const passed = direction === 'gte' ? actual >= target : actual <= target
    return {
      item,
      actual: scorePercent(actual),
      target: `${direction === 'gte' ? '>=' : '<='} ${scorePercent(target)}`,
      status: passed ? 'pass' : 'warning',
      action,
      passed
    }
  }
  return [
    {
      item: 'OCR 100 门禁',
      actual: ocr100Scorecard.value
        ? `${ocr100Scorecard.value.score}/${ocr100Scorecard.value.targetScore}`
        : '-',
      target: '100/100',
      status: ocr100Scorecard.value?.ok ? 'pass' : 'warning',
      action: ocr100Scorecard.value?.ok ? '可作为 OCR 发布基线' : '先处理 OCR 阻断项',
      passed: Boolean(ocr100Scorecard.value?.ok)
    },
    {
      item: 'Agent 编排门禁',
      actual: reviewScorecard.value
        ? `${reviewScorecard.value.score}/${reviewScorecard.value.targetScore}`
        : '-',
      target: '达到目标分',
      status: reviewScorecard.value?.ok ? 'pass' : 'warning',
      action: reviewScorecard.value?.ok ? '可进入 shadow/canary' : '补齐证据、依据和门禁失败项',
      passed: Boolean(reviewScorecard.value?.ok)
    },
    buildRatioGate(
      'Case 通过率',
      Number(summary.casePassRate || 0),
      0.9,
      'gte',
      '补充失败样本归因并回归'
    ),
    buildRatioGate(
      '发现项召回',
      Number(summary.findingRecall || 0),
      0.85,
      'gte',
      '补充漏检样本和规则/Prompt 修正'
    ),
    buildRatioGate(
      '证据覆盖',
      Number(summary.evidenceCoverage || 0),
      0.9,
      'gte',
      '补齐 evidenceRefs、bbox 和 OCR 字段证据'
    ),
    buildRatioGate(
      '检索召回',
      Number(summary.retrievalRecall || 0),
      0.85,
      'gte',
      '检查 Hybrid RAG / PageIndex 路由和条款索引'
    ),
    buildRatioGate(
      '错误依据率',
      Number(summary.wrongReferenceRate || 0),
      0.03,
      'lte',
      '清理过期/不适用条款并重跑检索评估'
    )
  ]
})

const projectAuditEvaluationIssueRows = computed(() => {
  const gateIssues = projectAuditEvaluationGateRows.value
    .filter((row) => !row.passed)
    .map((row) => ({
      source: '评估门禁',
      object: row.item,
      issue: `${row.actual} 未达到 ${row.target}`,
      action: row.action
    }))
  const ocrIssues = failedOcrCaseRows.value.map((row) => ({
    source: 'OCR 样本',
    object: row.caseId,
    issue: `${row.scenario}：${row.finding}`,
    action: '进入 OCR 打标和 Profile 修正'
  }))
  const blockerIssues = projectAuditBlockers.value.map((row) => ({
    source: '项目阻断',
    object: row.title,
    issue: blockerTypeLabel(row.type),
    action: row.action || '按阻断项处理'
  }))
  return [...gateIssues, ...ocrIssues, ...blockerIssues].slice(0, 12)
})

const projectAuditEvaluationDecision = computed(() => {
  const failedGateCount = projectAuditEvaluationGateRows.value.filter((row) => !row.passed).length
  const blockerCount = projectAuditBlockers.value.length
  if (failedGateCount || blockerCount) {
    return {
      status: '暂不建议发布',
      tone: 'warning' as const,
      reason: `${failedGateCount} 个门禁未通过，${blockerCount} 个项目阻断`,
      action: '先处理失败样本、证据覆盖和错误依据，再重跑评估'
    }
  }
  return {
    status: '可进入灰度',
    tone: 'success' as const,
    reason: 'OCR、Agent 和检索评估门禁均已满足',
    action: '可创建 shadow/canary 计划并保留回滚方案'
  }
})

const projectAuditEvaluationCards = computed(() => [
  {
    label: 'OCR 100',
    value: ocr100Scorecard.value
      ? `${ocr100Scorecard.value.score}/${ocr100Scorecard.value.targetScore}`
      : '-',
    hint: ocr100Scorecard.value?.ok ? 'OCR 门禁通过' : 'OCR 门禁待修复',
    tone: ocr100Scorecard.value?.ok ? 'green' : 'red'
  },
  {
    label: 'Agent 评分',
    value: reviewScorecard.value
      ? `${reviewScorecard.value.score}/${reviewScorecard.value.targetScore}`
      : '-',
    hint: reviewScorecard.value?.ok ? '编排门禁通过' : '需检查证据和依据',
    tone: reviewScorecard.value?.ok ? 'green' : 'orange'
  },
  {
    label: '评估样本',
    value: String(latestOcrEvalCaseTotal.value || evaluationCaseRows.value.length || 0),
    hint: latestOcrEvalOk.value ? '最近 OCR 评估通过' : '最近 OCR 评估待改进',
    tone: latestOcrEvalOk.value ? 'green' : 'orange'
  },
  {
    label: '质量阻断',
    value: String(projectAuditBlockers.value.length),
    hint: '项目级阻断项',
    tone: projectAuditBlockers.value.length ? 'red' : 'green'
  }
])

const projectAuditSubpageItems = computed(() => [
  {
    key: 'overview' as const,
    label: '项目总览',
    description: '项目、节点、阻断项和当前治理摘要。'
  },
  {
    key: 'vectorization' as const,
    label: '资料向量化',
    description: '查看资料切片、Embedding、索引版本和向量化任务。'
  },
  {
    key: 'pageindex' as const,
    label: 'PageIndex 溯源',
    description: '查看长文档树检索路径、命中节点和条款映射。'
  },
  {
    key: 'langgraph' as const,
    label: 'LangGraph 可视化',
    description: '查看 Temporal Workflow、LangGraph 节点、边和检查点。'
  },
  {
    key: 'ocr-labeling' as const,
    label: 'OCR 打标',
    description: '查看 OCR Job、标注样本、字段/表格/印章人工修正。'
  },
  {
    key: 'evaluation' as const,
    label: '准确率评估',
    description: '查看 OCR、RAG、PageIndex、Agent 的质量门禁和失败样本。'
  }
])
const selectedProjectAuditSubpageItem = computed(
  () =>
    projectAuditSubpageItems.value.find((item) => item.key === projectAuditSubpage.value) ||
    projectAuditSubpageItems.value[0]
)
const projectAuditFocusFacts = computed(() => {
  const nodeName = shortText(projectAuditWorkspace.value?.selectedNode?.name, '未选择节点')
  const base = [
    {
      label: '当前节点',
      value: nodeName,
      tone: 'blue' as const
    }
  ]
  if (projectAuditSubpage.value === 'vectorization') {
    return [
      ...base,
      {
        label: '资料版本',
        value: String(normalizedProjectAuditVectorRows.value.length),
        tone: 'blue' as const
      },
      {
        label: '知识切片',
        value: String(projectAuditVectorCards.value[1]?.value || 0),
        tone: 'green' as const
      },
      {
        label: '向量条目',
        value: String(projectAuditVectorCards.value[2]?.value || 0),
        tone: 'green' as const
      }
    ]
  }
  if (projectAuditSubpage.value === 'pageindex') {
    return [
      ...base,
      {
        label: '检索 Trace',
        value: String(projectAuditPageIndexTraceRows.value.length),
        tone: 'blue' as const
      },
      {
        label: '命中节点',
        value: String(projectAuditPageIndexCards.value[1]?.value || 0),
        tone: 'green' as const
      },
      {
        label: '依据条款',
        value: String(projectAuditPageIndexCards.value[2]?.value || 0),
        tone: 'green' as const
      }
    ]
  }
  if (projectAuditSubpage.value === 'langgraph') {
    return [
      ...base,
      {
        label: 'ReviewRun',
        value: String(projectAuditReviewRuns.value.length),
        tone: 'blue' as const
      },
      { label: 'Graph节点', value: String(reviewGraphNodes.value.length), tone: 'green' as const },
      {
        label: 'Checkpointer',
        value: shortText(selectedReviewRun.value?.run.graphExecution?.checkpointer, '-'),
        tone: selectedReviewRun.value?.run.graphExecution?.checkpointer
          ? ('green' as const)
          : ('orange' as const)
      }
    ]
  }
  if (projectAuditSubpage.value === 'ocr-labeling') {
    return [
      ...base,
      {
        label: 'OCR任务',
        value: String(projectAuditOcrJobs.value.length),
        tone: 'orange' as const
      },
      {
        label: '标注样本',
        value: String(projectAuditAnnotationSummary.value.total),
        tone: 'blue' as const
      },
      {
        label: '可入评估',
        value: String(projectAuditAnnotationSummary.value.readyForEval),
        tone: 'green' as const
      }
    ]
  }
  if (projectAuditSubpage.value === 'evaluation') {
    return [
      ...base,
      {
        label: 'OCR评分',
        value: String(projectAuditEvaluationCards.value[0]?.value || '-'),
        tone: 'blue' as const
      },
      {
        label: 'Agent评分',
        value: String(projectAuditEvaluationCards.value[1]?.value || '-'),
        tone: 'green' as const
      },
      {
        label: '阻断',
        value: String(projectAuditBlockers.value.length),
        tone: projectAuditBlockers.value.length ? ('red' as const) : ('green' as const)
      }
    ]
  }
  return [
    ...base,
    {
      label: '资料文件',
      value: String(projectAuditDocuments.value.length),
      tone: 'green' as const
    },
    {
      label: 'Agent任务',
      value: String(projectAuditReviewRuns.value.length),
      tone: 'blue' as const
    },
    {
      label: 'OCR样本',
      value: String(projectAuditAnnotationTasks.value.length),
      tone: 'orange' as const
    }
  ]
})
const blockerTypeLabel = (type: unknown) => {
  const raw = String(type || '')
  if (raw === 'ocr') return 'OCR'
  if (raw === 'ocr-field') return '字段'
  if (raw === 'ocr-annotation') return '标注'
  if (raw === 'agent') return 'Agent'
  return raw || '-'
}
const blockerLevelType = (level: unknown): FdeElTagType => {
  if (level === 'danger' || level === 'error') return 'danger'
  if (level === 'warning') return 'warning'
  return 'info'
}
const nodeStatusSummary = computed(() => {
  const counts: Record<string, number> = {}
  for (const item of projectAuditNodeRows.value) {
    const status = friendlyStatus(item.status)
    counts[status] = (counts[status] || 0) + 1
  }
  return Object.entries(counts).map(([status, count]) => ({ status, count }))
})

const loadProjectAuditWorkspace = async (
  projectId = selectedFdeProjectId.value,
  nodeId = selectedFdeNodeId.value
) => {
  if (!projectId) {
    projectAuditWorkspace.value = null
    selectedFdeNodeId.value = undefined
    return
  }
  if (fdeDemoMode.value && fdeDemoProjectWorkspaces.value.length) {
    const demoWorkspace = getSelectedDemoWorkspace(projectId, nodeId)
    if (!demoWorkspace) return
    projectAuditWorkspace.value = demoWorkspace
    selectedFdeProjectId.value = demoWorkspace.project.id
    selectedFdeNodeId.value = demoWorkspace.selectedNodeId

    const reviewRun = demoWorkspace.reviewRuns[0]
    const reviewRunId = String(reviewRun?.reviewRunId || reviewRun?.id || '')
    if (reviewRunId) {
      await loadReviewRunDetail(reviewRunId)
    }

    const ocrJob = demoWorkspace.ocrJobs[0]
    const ocrJobId = String(ocrJob?.jobId || ocrJob?.id || '')
    if (ocrJobId) {
      await loadOcrRunDetail(ocrJobId)
    }
    return
  }
  const res = await getFdeProjectAuditWorkspaceApi(projectId, nodeId ? { nodeId } : undefined)
  const workspaceIsEmpty =
    !res.data.documents.length && !res.data.reviewRuns.length && !res.data.ocrJobs.length
  if (workspaceIsEmpty) {
    ensureFdeDemoData()
    return
  }
  projectAuditWorkspace.value = res.data
  selectedFdeProjectId.value = res.data.project.id
  selectedFdeNodeId.value = res.data.selectedNodeId

  const reviewRun = res.data.reviewRuns[0]
  const reviewRunId = String(reviewRun?.reviewRunId || reviewRun?.id || '')
  if (reviewRunId) {
    await loadReviewRunDetail(reviewRunId)
  }

  const ocrJob = res.data.ocrJobs[0]
  const ocrJobId = String(ocrJob?.jobId || ocrJob?.id || '')
  if (ocrJobId) {
    await loadOcrRunDetail(ocrJobId)
  }
}

const selectFdeProject = async (projectId: string) => {
  selectedFdeProjectId.value = projectId
  selectedFdeNodeId.value = undefined
  await loadProjectAuditWorkspace(projectId)
  await syncProjectAuditRoute(projectId, selectedFdeNodeId.value)
}

const selectFdeProjectNode = async (nodeId?: number) => {
  selectedFdeNodeId.value = nodeId
  await loadProjectAuditWorkspace(selectedFdeProjectId.value, nodeId)
  await syncProjectAuditRoute(selectedFdeProjectId.value, selectedFdeNodeId.value)
}

const handleFdeShellMenuSelect = async (item: FdeShellMenuItemPayload) => {
  if (!item.projectId) {
    if (item.route && item.route !== route.path) {
      await router.push(item.route)
    }
    return
  }
  if (
    item.subpage &&
    projectAuditSubpageItems.value.some((subpage) => subpage.key === item.subpage)
  ) {
    projectAuditSubpage.value = item.subpage as ProjectAuditSubpage
  }
  const projectChanged = selectedFdeProjectId.value !== item.projectId
  if (projectChanged) {
    selectedFdeNodeId.value = undefined
  }
  if (projectChanged || !projectAuditWorkspace.value) {
    selectedFdeProjectId.value = item.projectId
    await loadProjectAuditWorkspace(item.projectId, selectedFdeNodeId.value)
  }
  await syncProjectAuditRoute(item.projectId, selectedFdeNodeId.value, projectAuditSubpage.value)
}

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    const [
      dashboardRes,
      aiRunRes,
      reviewRunRes,
      feedbackRes,
      evaluationRes,
      bundleRes,
      releaseRes,
      ocrRes,
      ocrRunRes,
      ocrAnnotationRes,
      incidentRes,
      acceptanceRes,
      validationRes,
      accessRes,
      costRes,
      auditRes,
      maskingRes,
      projectRes
    ] = await Promise.all([
      getFdeDashboardApi(),
      listFdeAiRunsApi({ pageSize: 20 }),
      listFdeReviewRunsApi({ pageSize: 20 }),
      listFdeFeedbackApi(),
      getFdeEvaluationSetsApi(),
      getFdeCapabilityBundlesApi(),
      listFdeReleasesApi(),
      getFdeOcrQualityApi(),
      listFdeOcrRunsApi({ pageSize: 20 }),
      listFdeOcrAnnotationTasksApi({ pageSize: 20 }),
      listFdeIncidentsApi(),
      listFdeAcceptanceReportsApi(),
      validateFdeBusinessPacksApi(),
      listFdeAccessGrantsApi(),
      getFdeCostBudgetsApi(),
      getFdeAuditEventsApi({ limit: 50 }),
      getFdeMaskingPoliciesApi(),
      listFdeProjectsApi()
    ])
    dashboard.value = dashboardRes.data
    aiRuns.value = aiRunRes.data.items
    reviewRuns.value = reviewRunRes.data.items
    feedback.value = feedbackRes.data
    evaluation.value = evaluationRes.data
    bundles.value = bundleRes.data
    releases.value = releaseRes.data
    ocrQuality.value = ocrRes.data
    ocrRuns.value = ocrRunRes.data.items
    ocrAnnotation.value = ocrAnnotationRes.data
    incidentPayload.value = incidentRes.data
    acceptanceReports.value = acceptanceRes.data
    packValidation.value = validationRes.data
    accessGrants.value = accessRes.data
    costGovernance.value = costRes.data
    auditEvents.value = auditRes.data.events
    maskingPolicies.value = maskingRes.data
    fdeProjects.value = projectRes.data
    if (!fdeProjects.value.length) {
      ensureFdeDemoData()
      return
    }
    selectedFeedback.value = selectedFeedback.value || feedback.value[0] || null
    selectedBundleId.value = selectedBundleId.value || firstBundleId.value
    selectedReleaseId.value = selectedReleaseId.value || firstReleaseId.value
    selectedBusinessPackId.value = selectedBusinessPackId.value || firstPackId.value
    selectedIncidentId.value = selectedIncidentId.value || String(incidents.value[0]?.id || '')
    if (aiRuns.value[0]) {
      await loadRunDetail(aiRuns.value[0].id)
    }
    if (firstReviewRunId.value) {
      await loadReviewRunDetail(firstReviewRunId.value)
    }
    const routeState = getProjectAuditRouteState()
    if (routeState.subpage) {
      projectAuditSubpage.value = routeState.subpage
    }
    if (routeState.projectId) {
      selectedFdeProjectId.value = routeState.projectId
    }
    if (routeState.nodeId !== undefined) {
      selectedFdeNodeId.value = routeState.nodeId
    }
    if (!selectedFdeProjectId.value && fdeProjects.value[0]) {
      selectedFdeProjectId.value = fdeProjects.value[0].project.id
    }
    if (selectedFdeProjectId.value) {
      await loadProjectAuditWorkspace(selectedFdeProjectId.value, selectedFdeNodeId.value)
      if (route.path === '/fde/projects') {
        await syncProjectAuditRoute(
          selectedFdeProjectId.value,
          selectedFdeNodeId.value,
          projectAuditSubpage.value,
          true,
          getAuditDetailRouteState()
        )
      }
    }
    if (firstEvaluationRunId.value) {
      await loadEvaluationReportDetail(firstEvaluationRunId.value)
    } else {
      selectedEvaluationReport.value = null
    }
    if (firstOcrJobId.value) {
      await loadOcrRunDetail(firstOcrJobId.value)
    }
    await restoreAuditDetailFromRoute()
    if (activeBundleId.value) {
      await loadCapabilityBundleDiff(activeBundleId.value)
    }
    if (activeReleaseId.value) {
      await loadReleaseImpact(activeReleaseId.value)
    }
    if (activeBusinessPackId.value) {
      await loadBusinessPackDiff(activeBusinessPackId.value)
    }
    if (fdeDemoMode.value) {
      applyFdeDemoData()
    }
  } catch {
    error.value = 'FDE 后台数据加载失败。'
  } finally {
    loading.value = false
  }
}

const loadRunDetail = async (runId: string) => {
  const res = await getFdeAiRunApi(runId)
  selectedRun.value = res.data
}

const loadReviewRunDetail = async (reviewRunId: string) => {
  if (fdeDemoMode.value && reviewRunId.startsWith('RR-DEMO')) {
    selectedReviewRun.value = createDemoReviewRunDetail()
    selectedReviewRun.value.run.reviewRunId = reviewRunId
    selectedReviewRun.value.run.id = reviewRunId
    return
  }
  const res = await getFdeReviewRunApi(reviewRunId)
  selectedReviewRun.value = res.data
}

const loadOcrRunDetail = async (jobId: string) => {
  if (fdeDemoMode.value && jobId.startsWith('OCR-JOB-DEMO')) {
    selectedOcrRun.value = createDemoOcrRunDetail(jobId)
    return
  }
  const res = await getFdeOcrRunApi(jobId)
  selectedOcrRun.value = res.data
}

const openReviewAuditDrawer = async (reviewRunId: string, updateRoute = true) => {
  if (!reviewRunId) return
  await loadReviewRunDetail(reviewRunId)
  ocrAuditDrawerVisible.value = false
  reviewAuditDrawerVisible.value = true
  if (updateRoute) {
    await syncAuditDetailRoute({ reviewRunId })
  }
}

const openOcrAuditDrawer = async (jobId: string, updateRoute = true) => {
  if (!jobId) return
  await loadOcrRunDetail(jobId)
  reviewAuditDrawerVisible.value = false
  ocrAuditDrawerVisible.value = true
  if (updateRoute) {
    await syncAuditDetailRoute({ ocrJobId: jobId })
  }
}

const restoreAuditDetailFromRoute = async () => {
  const detail = getAuditDetailRouteState()
  if (detail.reviewRunId) {
    await openReviewAuditDrawer(detail.reviewRunId, false)
    return
  }
  if (detail.ocrJobId) {
    await openOcrAuditDrawer(detail.ocrJobId, false)
    return
  }
  reviewAuditDrawerVisible.value = false
  ocrAuditDrawerVisible.value = false
}

const loadEvaluationReportDetail = async (runId: string) => {
  const res = await getFdeEvaluationReportApi(runId)
  selectedEvaluationReport.value = res.data
}

const selectFeedback = (row: FdeFeedback) => {
  selectedFeedback.value = row
}

const selectBundle = async (row: Record<string, unknown>) => {
  selectedBundleId.value = String(row.id || '')
  if (selectedBundleId.value) {
    await loadCapabilityBundleDiff(selectedBundleId.value)
  }
}

const selectRelease = async (row: Record<string, unknown>) => {
  selectedReleaseId.value = String(row.id || '')
  if (selectedReleaseId.value) {
    await loadReleaseImpact(selectedReleaseId.value)
  }
}

const selectBusinessPack = async (row: Record<string, unknown>) => {
  selectedBusinessPackId.value = String(
    (row.summary as Record<string, unknown> | undefined)?.id || row.id || ''
  )
  if (selectedBusinessPackId.value) {
    await loadBusinessPackDiff(selectedBusinessPackId.value)
  }
}

const selectIncident = (row: Record<string, unknown>) => {
  selectedIncidentId.value = String(row.id || '')
}

const loadCapabilityBundleDiff = async (bundleId: string) => {
  const res = await getFdeCapabilityBundleDiffApi(bundleId)
  bundleDiff.value = res.data
}

const loadReleaseImpact = async (releaseId: string) => {
  const res = await getFdeReleaseImpactApi(releaseId)
  releaseImpact.value = res.data
}

const loadBusinessPackDiff = async (packId: string) => {
  const res = await getFdeBusinessPackDiffApi(packId, { tenantId: 'demo' })
  businessPackDiff.value = res.data
}

const replayFirstRun = async () => {
  if (!activeRunId.value) return
  actionLoading.value = true
  try {
    await replayFdeAiRunApi(activeRunId.value, {
      runType: 'diagnostic_replay',
      reason: 'FDE 诊断重跑'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const replayFirstReviewRun = async () => {
  if (!activeReviewRunId.value) return
  actionLoading.value = true
  try {
    await replayFdeReviewRunApi(activeReviewRunId.value, {
      runMode: 'diagnostic_replay',
      reason: 'FDE 诊断 ReviewRun 编排重跑'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const shadowFirstReviewRun = async () => {
  if (!activeReviewRunId.value) return
  actionLoading.value = true
  try {
    await shadowFdeReviewRunApi(activeReviewRunId.value, {
      reason: 'FDE 验证新 Agent Graph / Prompt 组合'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const triageFirstFeedback = async () => {
  if (!activeFeedbackId.value) return
  actionLoading.value = true
  try {
    await triageFdeFeedbackApi(activeFeedbackId.value, {
      rootCause: 'prompt_error',
      status: 'triaged',
      canUseForEval: true,
      canUseForTraining: false
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startEvaluation = async () => {
  if (!firstEvaluationSetId.value) return
  actionLoading.value = true
  try {
    const res = await createFdeEvaluationRunApi({
      evaluationSetId: firstEvaluationSetId.value,
      capabilityBundleId: firstBundleId.value || undefined
    })
    selectedEvaluationReport.value = {
      report: res.data.report,
      metrics: [],
      caseResults: res.data.caseResults || []
    }
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const requestRawAccess = async () => {
  if (!activeRunId.value) return
  actionLoading.value = true
  try {
    await requestFdeAccessGrantApi({
      targetType: 'ai_run',
      targetId: activeRunId.value,
      reason: 'FDE 诊断需要查看 AI Run 原文。'
    })
    await createFdeDataExportApi({
      targetType: 'ai_run',
      targetId: activeRunId.value,
      masked: true
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const submitReleaseGate = async () => {
  if (!activeReleaseId.value) return
  actionLoading.value = true
  try {
    await submitFdeReleaseApi(activeReleaseId.value, {
      evaluationReportId: firstReportId.value || undefined,
      rollbackPlanId: 'ROLLBACK-BUNDLE-202606'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startShadowRun = async () => {
  if (!activeReleaseId.value) return
  actionLoading.value = true
  try {
    await startFdeShadowApi(activeReleaseId.value, { sampleRate: 0 })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const markShadowPassed = async () => {
  if (!activeReleaseId.value) return
  actionLoading.value = true
  try {
    await markFdeShadowPassedApi(activeReleaseId.value, {
      metrics: {
        failedRuns: 0,
        evidenceHitRate:
          dashboard.value?.metrics?.find((item) => item.label === '证据命中率')?.value || 0
      }
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const installBusinessPack = async () => {
  if (!activeBusinessPackId.value) return
  actionLoading.value = true
  try {
    await installFdeBusinessPackApi(activeBusinessPackId.value, { tenantId: 'demo', dryRun: true })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const updateFirstRca = async () => {
  const incidentId = activeIncidentId.value
  if (!incidentId) return
  actionLoading.value = true
  try {
    await updateFdeIncidentRcaApi(incidentId, {
      status: 'open',
      rootCause: 'low_quality_scan',
      temporaryAction: '已要求低置信度字段人工复核。',
      longTermAction: '优化 OCR Profile 预处理参数。'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const closeSelectedIncident = async () => {
  if (!activeIncidentId.value) return
  actionLoading.value = true
  try {
    await closeFdeIncidentApi(activeIncidentId.value, {
      resolution: 'FDE 已完成 RCA、影响范围确认和整改追踪。'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const createMaskingPolicyDraft = async () => {
  actionLoading.value = true
  try {
    await createFdeMaskingPolicyApi({
      targetType: 'ai_run',
      fieldPath: 'findingDrafts.description',
      strategy: 'prefix',
      visibleChars: 80,
      riskLevel: 'high'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const expireFirstDataExport = async () => {
  if (!firstDataExportId.value) return
  actionLoading.value = true
  try {
    await expireFdeDataExportApi(firstDataExportId.value, { reason: 'FDE 手动过期演练导出。' })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const proposeFirstBudgetChange = async () => {
  if (!firstBudgetId.value) return
  actionLoading.value = true
  try {
    await proposeFdeCostBudgetChangeApi(firstBudgetId.value, {
      proposedLimit: 1000,
      proposedPolicy: { fallbackModel: 'review-chat', alertThreshold: 0.8 },
      reason: 'FDE 根据近期评测成本提交预算调整建议。'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const correctFirstOcrField = async () => {
  const field = firstLowConfidenceField.value
  if (!field) return
  actionLoading.value = true
  try {
    await createFdeOcrCorrectionApi({
      fieldId: field.id,
      documentVersionId: field.documentVersionId,
      correctedValue: String(field.fieldValue ?? ''),
      reason: 'FDE 复核低置信度字段'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const startOcrEvaluation = async () => {
  actionLoading.value = true
  try {
    await createFdeOcrEvaluationRunApi({
      profileId: String(selectedOcrRun.value?.job?.profileId || 'all')
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const cloneRecord = <T,>(value: T): T => JSON.parse(JSON.stringify(value))

const emptyAnnotationExpected = (): Record<string, unknown> => ({
  qualityStatus: 'needs_human_review',
  fields: [],
  tables: [],
  seals: []
})

const normalizeAnnotationExpected = (value?: Record<string, unknown>) => {
  const expected = cloneRecord(value || emptyAnnotationExpected())
  expected.qualityStatus = expected.qualityStatus || 'needs_human_review'
  expected.fields = Array.isArray(expected.fields) ? expected.fields : []
  expected.tables = Array.isArray(expected.tables) ? expected.tables : []
  expected.seals = Array.isArray(expected.seals) ? expected.seals : []
  return expected
}

const reloadOcrAnnotationTasks = async () => {
  const res = await listFdeOcrAnnotationTasksApi({ pageSize: 20 })
  ocrAnnotation.value = res.data
}

const openAnnotationEditor = async (row: FdeOcrAnnotationTask) => {
  const taskId = String(row.taskId || row.caseId || '')
  if (!taskId) return
  annotationEditorVisible.value = true
  annotationDetailLoading.value = true
  try {
    const res = await getFdeOcrAnnotationTaskApi(taskId)
    selectedAnnotationTask.value = res.data.task
    annotationDraft.value = normalizeAnnotationExpected(
      res.data.task.labeledExpected || res.data.task.suggestedExpected
    )
    annotationLabeler.value = res.data.task.labeler || '人工标注员'
    annotationReviewer.value = res.data.task.reviewer || 'FDE 工程师'
    annotationBoxForm.value.pageNo = Number(res.data.task.pageNo || 1)
  } finally {
    annotationDetailLoading.value = false
  }
}

const validAnnotationBox = () => {
  const form = annotationBoxForm.value
  return Number(form.x2) > Number(form.x1) && Number(form.y2) > Number(form.y1)
}

const addAnnotationBox = () => {
  if (!validAnnotationBox()) return
  const section = annotationBoxType.value
  const items = annotationItems(section)
  const bbox = [
    Number(annotationBoxForm.value.x1),
    Number(annotationBoxForm.value.y1),
    Number(annotationBoxForm.value.x2),
    Number(annotationBoxForm.value.y2)
  ]
  const pageNo = Number(annotationBoxForm.value.pageNo || 1)
  const label = annotationLabelValue.value.trim()
  if (section === 'fields') {
    items.push({
      fieldCode: label || `field_${items.length + 1}`,
      value: label || '待校对值',
      bbox,
      pageNo
    })
  } else if (section === 'tables') {
    items.push({
      businessSchema: label || `table_${items.length + 1}`,
      bbox,
      minRows: 1,
      minColumns: 1,
      pageNo
    })
  } else {
    items.push({
      sealType: 'company_official_seal',
      nameContains: label || '待校对印章',
      bbox,
      pageNo
    })
  }
  annotationDraft.value[section] = [...items]
  annotationLabelValue.value = ''
}

const removeAnnotationItem = (section: 'fields' | 'tables' | 'seals', index: number) => {
  const items = annotationItems(section)
  items.splice(index, 1)
  annotationDraft.value[section] = [...items]
}

const saveAnnotationDraft = async () => {
  const taskId = String(
    selectedAnnotationTask.value?.taskId || selectedAnnotationTask.value?.caseId || ''
  )
  if (!taskId) return
  actionLoading.value = true
  try {
    const res = await saveFdeOcrAnnotationLabelApi(
      taskId,
      {
        labeler: annotationLabeler.value,
        labeledExpected: cloneRecord(annotationDraft.value),
        pageDimensions: selectedAnnotationTask.value?.pageDimensions,
        pageNo: Number(annotationBoxForm.value.pageNo || selectedAnnotationTask.value?.pageNo || 1),
        collectionStatus: 'labeled'
      },
      { idempotencyKey: `fde-annotation-save-${taskId}-${Date.now()}` }
    )
    selectedAnnotationTask.value = res.data.task
    annotationDraft.value = normalizeAnnotationExpected(res.data.task.labeledExpected)
    await reloadOcrAnnotationTasks()
  } finally {
    actionLoading.value = false
  }
}

const verifyAnnotationFromEditor = async () => {
  const taskId = String(
    selectedAnnotationTask.value?.taskId || selectedAnnotationTask.value?.caseId || ''
  )
  if (!taskId) return
  actionLoading.value = true
  try {
    await saveFdeOcrAnnotationLabelApi(
      taskId,
      {
        labeler: annotationLabeler.value,
        labeledExpected: cloneRecord(annotationDraft.value),
        pageDimensions: selectedAnnotationTask.value?.pageDimensions,
        pageNo: Number(annotationBoxForm.value.pageNo || selectedAnnotationTask.value?.pageNo || 1),
        collectionStatus: 'labeled'
      },
      { idempotencyKey: `fde-annotation-save-before-verify-${taskId}-${Date.now()}` }
    )
    const res = await verifyFdeOcrAnnotationTaskApi(
      taskId,
      {
        labeler: annotationLabeler.value,
        reviewer: annotationReviewer.value,
        decision: 'approved',
        comment: 'FDE 内置标注台二审通过。'
      },
      { idempotencyKey: `fde-annotation-verify-${taskId}-${Date.now()}` }
    )
    selectedAnnotationTask.value = res.data.task
    annotationDraft.value = normalizeAnnotationExpected(res.data.task.labeledExpected)
    await reloadOcrAnnotationTasks()
  } finally {
    actionLoading.value = false
  }
}

const importDemoOcrAnnotationPack = async () => {
  actionLoading.value = true
  try {
    const res = await importFdeOcrAnnotationPackApi(
      {
        tasks: [
          {
            taskId: `ANNO-FDE-DEMO-${Date.now()}`,
            caseId: 'real-seal_text_profile-fde-demo',
            scenario: 'seal_text_profile',
            profileId: 'seal_text_profile_v1',
            documentType: 'seal_photo',
            collectionStatus: 'needs_labeling',
            suggestedExpected: {
              qualityStatus: 'needs_human_review',
              seals: [
                {
                  sealType: 'company_official_seal',
                  nameContains: '待校对印章',
                  bbox: [100, 100, 240, 220],
                  pageNo: 1
                }
              ]
            }
          }
        ]
      },
      { idempotencyKey: `fde-annotation-import-pack-${Date.now()}` }
    )
    ocrAnnotation.value = {
      summary: res.data.readiness.summary,
      nextActions: res.data.readiness.nextActions,
      page: res.data.page
    }
  } finally {
    actionLoading.value = false
  }
}

const exportOcrAnnotationToLabelStudio = async () => {
  actionLoading.value = true
  try {
    const res = await exportFdeOcrAnnotationLabelStudioApi({ includeWithoutImage: true })
    labelStudioExportSummary.value = res.data.summary
  } finally {
    actionLoading.value = false
  }
}

const markFirstOcrAnnotationReviewed = async () => {
  if (!firstOcrAnnotationTaskId.value) return
  actionLoading.value = true
  try {
    await reviewFdeOcrAnnotationTaskApi(firstOcrAnnotationTaskId.value, {
      labeler: '人工标注员',
      reviewer: 'FDE 工程师',
      comment: 'FDE 后台二审演练。',
      collectionStatus: 'ready_for_eval'
    })
    const res = await listFdeOcrAnnotationTasksApi({ pageSize: 20 })
    ocrAnnotation.value = res.data
  } finally {
    actionLoading.value = false
  }
}

const goFdeRoute = (target: string) => {
  if (target && route.path !== target) {
    router.push(target)
  }
}

const openFirstOcrAnnotationTask = async () => {
  const task = ocrAnnotationRows.value[0]
  if (task) {
    await openAnnotationEditor(task)
    return
  }
  await importDemoOcrAnnotationPack()
}

const runFdePageAction = async (key: FdePageActionKey) => {
  if (key === 'go-ocr-label') return openFirstOcrAnnotationTask()
  if (key === 'start-ocr-evaluation') return startOcrEvaluation()
  if (key === 'triage-feedback') return triageFirstFeedback()
  if (key === 'start-evaluation') return startEvaluation()
  if (key === 'replay-ai-run') return replayFirstRun()
  if (key === 'replay-review-run') return replayFirstReviewRun()
  if (key === 'shadow-review-run') return shadowFirstReviewRun()
  if (key === 'submit-release') return submitReleaseGate()
  if (key === 'install-business-pack') return installBusinessPack()
  if (key === 'create-mask-policy') return createMaskingPolicyDraft()
  if (key === 'update-rca') return updateFirstRca()
  if (key === 'budget-change') return proposeFirstBudgetChange()
}

watch(
  () => route.path,
  () => syncTabFromRoute(),
  { immediate: true }
)

watch(
  () => [route.path, route.query.projectId, route.query.view, route.query.nodeId],
  async () => {
    if (route.path !== '/fde/projects') return
    if (!fdeProjects.value.length && !projectAuditWorkspace.value) return
    const routeState = getProjectAuditRouteState()
    if (routeState.subpage) {
      projectAuditSubpage.value = routeState.subpage
    }
    const targetProjectId = routeState.projectId || selectedFdeProjectId.value
    if (!targetProjectId) return
    const shouldReloadProject = selectedFdeProjectId.value !== targetProjectId
    const shouldReloadNode =
      routeState.nodeId !== undefined && selectedFdeNodeId.value !== routeState.nodeId
    if (shouldReloadProject || shouldReloadNode || !projectAuditWorkspace.value) {
      await loadProjectAuditWorkspace(targetProjectId, routeState.nodeId)
    }
  }
)

watch(
  () => [route.query.reviewRunId, route.query.ocrJobId],
  async () => {
    await restoreAuditDetailFromRoute()
  }
)

watch(reviewAuditDrawerVisible, (visible) => {
  if (!visible) {
    void clearAuditDetailRoute('reviewRunId')
  }
})

watch(ocrAuditDrawerVisible, (visible) => {
  if (!visible) {
    void clearAuditDetailRoute('ocrJobId')
  }
})

watch(activeFdeTab, (tab) => {
  const segment = String(route.path.split('/').filter(Boolean).pop() || 'dashboard')
  if (routeTabMap[segment] === tab) return
  const target = fdeTabRouteMap[tab]
  if (target && route.path !== target) {
    if (target === '/fde/projects' && selectedFdeProjectId.value) {
      void syncProjectAuditRoute()
      return
    }
    router.push(target)
  }
})

onMounted(loadData)
</script>

<template>
  <StaticPageShell
    brand-mark="F"
    title="FDE 后台"
    search-placeholder="⌕ 搜索 ReviewRun / OCR / 样本"
    user-label="FDE 工程师"
    :top-stats="fdeTopStats"
    menu-title="FDE 菜单"
    menu-root="AI Delivery & Governance"
    :menu-sections="fdeShellMenuSections"
    menu-search-placeholder="搜索项目、编号、节点"
    :menu-search-value="projectAuditSearch"
    :menu-filters="projectAuditMenuFilterOptions"
    :menu-filter-value="projectAuditFilter"
    :menu-filters-collapsed-default="true"
    :menu-empty-text="projectAuditMenuEmptyText"
    boundary-title="职责边界"
    boundary-badge="不办业务审批"
    boundary-tone="green"
    :boundary-rows="fdeShellBoundaryRows"
    :boundary-collapsed-default="true"
    right-title="治理摘要"
    right-subtitle="Agent Orchestration / OCR"
    :right-cards="fdeShellRightCards"
    right-panel-mode="drawer"
    :right-collapsed-default="true"
    right-toggle-label="治理摘要"
    workspace-mode="wide"
    @menu-select="handleFdeShellMenuSelect"
    @menu-search-change="setProjectAuditSearch"
    @menu-filter-change="setProjectAuditFilter"
  >
    <div class="fde-console" v-loading="loading">
      <div class="page-toolbar">
        <div>
          <div class="page-title">{{ currentFdeRouteContext.title }}</div>
          <div class="page-subtitle">{{ currentFdeRouteContext.subtitle }}</div>
          <div class="page-title-tags">
            <ElTag type="info" effect="plain">脱敏默认</ElTag>
            <ElTag type="success" effect="plain">证据追踪</ElTag>
            <ElTag type="warning" effect="plain">发布门禁</ElTag>
          </div>
          <div class="route-context">
            <span>{{ currentFdeRouteContext.group }}</span>
            <strong>{{ currentFdeRouteContext.label }}</strong>
            <ElTag :type="fdeTagType(currentFdeRouteContext.tone)" effect="plain">
              {{ currentFdeRouteContext.badge }}
            </ElTag>
          </div>
          <div class="next-action">
            <span>推荐下一步</span>
            <strong>{{ currentFdeRouteContext.nextAction }}</strong>
          </div>
        </div>
        <ElSpace wrap>
          <ElTag v-if="fdeDemoMode" type="warning" effect="plain">前端演示数据</ElTag>
          <ElButton
            v-for="action in currentFdePageActions"
            :key="action.key"
            :type="action.type || 'default'"
            :plain="action.plain !== false"
            :disabled="action.disabled"
            :loading="actionLoading"
            @click="runFdePageAction(action.key)"
          >
            {{ action.label }}
          </ElButton>
          <ElTag :type="loading ? 'warning' : 'success'" effect="plain">
            {{ loading ? '加载中' : '已连接' }}
          </ElTag>
          <ElButton type="primary" plain :loading="loading" @click="loadData">刷新</ElButton>
        </ElSpace>
      </div>

      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="mb-12px"
      />

      <div v-if="isFdeRoute('dashboard')" class="metric-grid">
        <div
          v-for="metric in dashboardMetricCards"
          :key="metric.label"
          :class="`metric-card metric-card--${metric.tone}`"
        >
          <span>{{ metric.label }}</span>
          <strong>{{ metric.suffix === '%' ? percent(metric.value) : metric.value }}</strong>
        </div>
      </div>

      <div v-if="isFdeRoute('dashboard')" class="workflow-grid">
        <button
          v-for="card in fdeWorkflowCards"
          :key="card.title"
          type="button"
          :class="`workflow-card workflow-card--${card.tone}`"
          @click="goFdeRoute(card.route)"
        >
          <span>{{ card.title }}</span>
          <strong>{{ card.metric }}</strong>
          <small>{{ card.description }}</small>
          <em>{{ card.action }}</em>
        </button>
      </div>

      <div v-if="isFdeRoute('projects')" class="project-audit-workbench">
        <ElCard
          shadow="never"
          :class="[
            'project-audit-card',
            'project-audit-card--hero',
            { 'project-audit-card--compact': projectAuditSubpage !== 'overview' }
          ]"
        >
          <div class="project-audit-header">
            <div class="project-audit-title">
              <span>当前审计项目</span>
              <strong>{{ selectedFdeProject?.name || '请选择项目' }}</strong>
              <small>
                {{ selectedFdeProject?.code || '-' }} · {{ selectedFdeProject?.type || '-' }} ·
                {{ selectedFdeProject?.region || '-' }}
              </small>
            </div>
            <ElSpace wrap class="project-audit-selectors">
              <ElSelect
                v-model="selectedFdeProjectId"
                class="project-audit-select"
                placeholder="选择审计项目"
                filterable
                @change="(value) => selectFdeProject(String(value))"
              >
                <ElOption
                  v-for="item in fdeProjects"
                  :key="item.project.id"
                  :label="item.project.name"
                  :value="item.project.id"
                />
              </ElSelect>
              <ElSelect
                v-model="selectedFdeNodeId"
                class="project-audit-select"
                placeholder="选择节点"
                clearable
                @change="(value) => selectFdeProjectNode(value ? Number(value) : undefined)"
              >
                <ElOption
                  v-for="item in projectAuditNodeOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                >
                  <span>{{ item.label }}</span>
                  <ElTag size="small" effect="plain" class="ml-8px">
                    {{ friendlyStatus(item.status) }}
                  </ElTag>
                </ElOption>
              </ElSelect>
            </ElSpace>
          </div>
          <div v-if="projectAuditSubpage === 'overview'" class="project-audit-meta">
            <ElTag :type="statusType(selectedFdeProject?.status)" effect="plain">
              {{ friendlyStatus(selectedFdeProject?.status, '未选择') }}
            </ElTag>
            <ElTag type="info" effect="plain">
              业务包 {{ selectedFdeProject?.businessPackId || '-' }}
            </ElTag>
            <ElTag :type="projectAuditBlockers.length ? 'warning' : 'success'" effect="plain">
              {{ projectAuditBlockers.length ? '存在质量阻断' : '暂无阻断' }}
            </ElTag>
          </div>
        </ElCard>

        <div class="project-audit-module-bar">
          <div class="project-audit-module-title">
            <span>当前审计视图</span>
            <strong>{{ selectedProjectAuditSubpageItem?.label }}</strong>
            <small>{{ selectedProjectAuditSubpageItem?.description }}</small>
          </div>
          <div class="project-audit-focus-facts" aria-label="当前审计对象">
            <span
              v-for="fact in projectAuditFocusFacts"
              :key="`${fact.label}-${fact.value}`"
              :class="['project-audit-focus-fact', fact.tone]"
            >
              <em>{{ fact.label }}</em>
              <strong>{{ fact.value }}</strong>
            </span>
          </div>
        </div>

        <template v-if="projectAuditSubpage === 'overview'">
          <div class="workbench-summary-grid">
            <div
              v-for="card in projectAuditMetricCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <div class="project-audit-health-grid">
            <ElCard shadow="never" class="panel project-audit-health-panel">
              <template #header>
                <div class="panel-header">
                  <span>审查链路健康</span>
                  <ElTag effect="plain">{{ projectAuditLangGraphAuditRows.length }} 个环节</ElTag>
                </div>
              </template>
              <div class="audit-health-list" aria-label="审查链路健康">
                <article
                  v-for="row in projectAuditLangGraphAuditRows"
                  :key="row.stage"
                  :class="['audit-health-item', row.healthy ? 'is-healthy' : 'is-warning']"
                >
                  <span class="audit-health-dot" aria-hidden="true" />
                  <div class="audit-health-copy">
                    <strong>{{ row.stage }}</strong>
                    <small>{{ row.evidence }}</small>
                    <em>{{ row.action }}</em>
                  </div>
                  <ElTag :type="row.healthy ? 'success' : 'warning'" effect="plain">
                    {{ row.status }}
                  </ElTag>
                </article>
              </div>
            </ElCard>

            <ElCard shadow="never" class="panel project-audit-issue-panel">
              <template #header>
                <div class="panel-header">
                  <span>编排缺口与建议</span>
                  <ElTag
                    :type="projectAuditLangGraphIssueRows.length ? 'warning' : 'success'"
                    effect="plain"
                  >
                    {{ projectAuditLangGraphIssueRows.length || '无' }} 个缺口
                  </ElTag>
                </div>
              </template>
              <div v-if="projectAuditLangGraphIssueRows.length" class="audit-issue-list">
                <article
                  v-for="row in projectAuditLangGraphIssueRows"
                  :key="row.stage"
                  class="audit-issue-item"
                >
                  <ElTag type="warning" effect="plain">{{ row.issue }}</ElTag>
                  <strong>{{ row.stage }}</strong>
                  <small>{{ row.evidence }}</small>
                  <span>{{ row.action }}</span>
                </article>
              </div>
              <div v-else class="audit-empty-state">
                <strong>链路完整</strong>
                <span>Temporal、LangGraph、工具证据、规则检索和质量门禁均已返回。</span>
              </div>
            </ElCard>
          </div>

          <div class="project-audit-node-grid">
            <ElCard shadow="never" class="panel project-audit-node-panel">
              <template #header>
                <div class="panel-header">
                  <span>节点审计进度</span>
                  <ElTag effect="plain">{{ projectAuditNodeRows.length }} 个节点</ElTag>
                </div>
              </template>
              <div class="audit-node-list" aria-label="项目节点审计进度">
                <button
                  v-for="row in projectAuditNodeRows.slice(0, 8)"
                  :key="String(row.nodeId)"
                  type="button"
                  class="audit-node-item"
                  @click="selectFdeProjectNode(Number(row.nodeId))"
                >
                  <span>{{ shortText(row.groupName || '节点') }}</span>
                  <strong>{{ row.nodeName }}</strong>
                  <small>
                    资料 {{ row.documentCount }} · Agent {{ row.reviewRunCount }} · OCR
                    {{ row.ocrJobCount }}
                  </small>
                  <ElTag :type="statusType(String(row.status))" effect="plain">
                    {{ friendlyStatus(row.status) }}
                  </ElTag>
                  <em v-if="row.blockerCount">{{ row.blockerCount }} 个阻断</em>
                </button>
              </div>
            </ElCard>

            <div class="project-audit-side-stack">
              <ElCard shadow="never" class="panel">
                <template #header>当前节点上下文</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="节点">
                    {{ projectAuditWorkspace?.selectedNode?.name || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="状态">
                    {{ friendlyStatus(projectAuditWorkspace?.selectedNode?.status) }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="资料">
                    {{ selectedProjectAuditNodeSummary?.documentCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="低置信字段">
                    {{ selectedProjectAuditNodeSummary?.lowConfidenceFieldCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Agent任务">
                    {{ selectedProjectAuditNodeSummary?.reviewRunCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="OCR任务">
                    {{ selectedProjectAuditNodeSummary?.ocrJobCount || 0 }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
              <ElCard shadow="never" class="panel">
                <template #header>首要阻断</template>
                <div v-if="projectAuditBlockers.length" class="audit-blocker-list">
                  <article
                    v-for="row in projectAuditBlockers.slice(0, 5)"
                    :key="`${row.type}-${row.title}`"
                    class="audit-blocker-item"
                  >
                    <ElTag :type="blockerLevelType(row.level)" effect="plain">
                      {{ blockerTypeLabel(row.type) }}
                    </ElTag>
                    <strong>{{ row.title }}</strong>
                    <span>{{ row.action }}</span>
                  </article>
                </div>
                <div v-else class="audit-empty-state">
                  <strong>暂无阻断</strong>
                  <span>当前项目没有影响 OCR 或 Agent 审查的高优先级问题。</span>
                </div>
              </ElCard>
            </div>
          </div>
        </template>

        <template v-else-if="projectAuditSubpage === 'vectorization'">
          <div class="workbench-summary-grid project-subpage-kpis">
            <div
              v-for="card in projectAuditVectorCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <ElRow :gutter="16">
            <ElCol :xl="16" :lg="16" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>资料索引入库状态</span>
                    <ElTag effect="plain">
                      {{ normalizedProjectAuditVectorRows.length }} 个资料版本
                    </ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedProjectAuditVectorRows" border height="460">
                  <ElTableColumn
                    prop="fileName"
                    label="资料文件"
                    min-width="220"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="requirementName"
                    label="资料要求"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="documentVersionId"
                    label="版本"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="ocrStatus" label="OCR" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.ocrStatus))" effect="plain">
                        {{ friendlyStatus(row.ocrStatus) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="sliceStatus" label="切片" width="110">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.sliceStatus))" effect="plain">
                        {{ friendlyStatus(row.sliceStatus) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="vectorStatus" label="向量" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.vectorStatus))" effect="plain">
                        {{ friendlyStatus(row.vectorStatus) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="chunkCount" label="切片数" width="88" />
                  <ElTableColumn prop="vectorCount" label="向量数" width="88" />
                  <ElTableColumn prop="vectorGap" label="缺口" width="76">
                    <template #default="{ row }">
                      <ElTag :type="row.vectorGap ? 'danger' : 'success'" effect="plain">
                        {{ row.vectorGap }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="pageIndexNodeCount" label="PI节点" width="86" />
                  <ElTableColumn prop="readinessLabel" label="审查可用" width="112">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.readyForRag && row.readyForPageIndex ? 'success' : 'warning'"
                      >
                        {{ row.readinessLabel }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="indexVersion"
                    label="索引版本"
                    min-width="170"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>索引配置</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="Embedding 模型">
                    {{ projectAuditVectorIndexProfile.embeddingModel }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="向量维度">
                    {{ projectAuditVectorIndexProfile.vectorDimensions }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="索引版本">
                    {{ projectAuditVectorIndexProfile.indexVersion }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="RAG 就绪">
                    {{ projectAuditVectorIndexProfile.ragReady }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="PageIndex 就绪">
                    {{ projectAuditVectorIndexProfile.pageIndexReady }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="入库结论">
                    {{ projectAuditVectorIndexProfile.issueSummary }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="审计目标">
                    {{ projectAuditVectorIndexProfile.chunkPolicy }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
              <ElCard shadow="never" class="panel mt-16px">
                <template #header>向量入库状态</template>
                <ElTable :data="normalizedProjectAuditVectorRows" border height="220">
                  <ElTableColumn
                    prop="fileName"
                    label="资料"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="chunkCount" label="切片" width="82" />
                  <ElTableColumn prop="vectorCount" label="向量" width="82" />
                  <ElTableColumn prop="readyForRag" label="RAG" width="76">
                    <template #default="{ row }">
                      <ElTag :type="row.readyForRag ? 'success' : 'warning'" effect="plain">
                        {{ row.readyForRag ? '可用' : '待补' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
              <ElCard shadow="never" class="panel mt-16px">
                <template #header>异常与处理建议</template>
                <ElTable
                  :data="projectAuditVectorIssueRows"
                  border
                  height="220"
                  empty-text="暂无异常"
                >
                  <ElTableColumn
                    prop="fileName"
                    label="资料"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="issue" label="问题" min-width="130" show-overflow-tooltip />
                  <ElTableColumn prop="action" label="建议" min-width="180" show-overflow-tooltip />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </template>

        <template v-else-if="projectAuditSubpage === 'pageindex'">
          <div class="workbench-summary-grid project-subpage-kpis">
            <div
              v-for="card in projectAuditPageIndexCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <ElRow :gutter="16">
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>PageIndex 路由 Trace</span>
                    <ElTag effect="plain">{{ projectAuditPageIndexTraceRows.length }} 条</ElTag>
                  </div>
                </template>
                <div v-if="projectAuditPageIndexTraceRows.length" class="pageindex-trace-list">
                  <article
                    v-for="row in projectAuditPageIndexTraceRows"
                    :key="String(row.retrievalTraceId)"
                    class="pageindex-trace-card"
                  >
                    <div class="pageindex-trace-head">
                      <div>
                        <span>Trace</span>
                        <strong>{{ row.retrievalTraceId }}</strong>
                      </div>
                      <ElTag :type="row.pageIndexUsed ? 'success' : 'warning'" effect="plain">
                        {{ row.routeDecision }}
                      </ElTag>
                    </div>
                    <div class="pageindex-query-block">
                      <span>{{ friendlyTechLabel(row.queryType) }}</span>
                      <p>{{ row.query }}</p>
                    </div>
                    <div class="pageindex-route-flow" aria-label="PageIndex 路由决策">
                      <span>Query Router</span>
                      <i></i>
                      <strong>{{ friendlyTechLabel(row.selectedRoute) }}</strong>
                      <em v-if="row.fallbackRoute !== '-'">
                        fallback {{ friendlyTechLabel(row.fallbackRoute) }}
                      </em>
                    </div>
                    <div class="pageindex-trace-facts">
                      <span>
                        <em>节点</em>
                        <strong>{{ row.pageIndexNodeCount }}</strong>
                      </span>
                      <span>
                        <em>条款</em>
                        <strong>{{ row.selectedClauseCount }}</strong>
                      </span>
                      <span>
                        <em>路由原因</em>
                        <strong>{{ shortText(row.routerReason) }}</strong>
                      </span>
                      <span>
                        <em>条款映射</em>
                        <strong>{{ shortText(row.linkedClauseIds) }}</strong>
                      </span>
                    </div>
                    <div
                      :class="[
                        'pageindex-trace-action',
                        row.issue === '无' ? 'is-ok' : 'is-warning'
                      ]"
                    >
                      <span>{{ row.issue === '无' ? '路由决策可用' : row.issue }}</span>
                      <strong>{{ row.action }}</strong>
                    </div>
                  </article>
                </div>
                <ElEmpty v-else description="暂无 PageIndex 路由 Trace" />
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>PageIndex 资料覆盖</template>
                <ElTable :data="projectAuditPageIndexCoverageRows" border height="380">
                  <ElTableColumn
                    prop="fileName"
                    label="资料"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="pageIndexNodeCount" label="节点" width="76" />
                  <ElTableColumn prop="coverageStatus" label="状态" width="100">
                    <template #default="{ row }">
                      <ElTag :type="row.readyForPageIndex ? 'success' : 'warning'" effect="plain">
                        {{ row.coverageStatus }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="coverageAction"
                    label="处理口径"
                    min-width="180"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>命中节点与条款</template>
                <ElTable :data="projectAuditPageIndexNodeRows" border height="300">
                  <ElTableColumn
                    prop="title"
                    label="节点标题"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="sectionPath"
                    label="章节路径"
                    min-width="220"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="pageRange" label="页码" width="92" />
                  <ElTableColumn prop="score" label="得分" width="92">
                    <template #default="{ row }">
                      {{ row.score === undefined ? '-' : scorePercent(row.score) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="linkedClauseIds"
                    label="条款"
                    min-width="180"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>异常与处理建议</template>
                <ElTable
                  :data="projectAuditPageIndexIssueRows"
                  border
                  height="300"
                  empty-text="暂无异常"
                >
                  <ElTableColumn prop="source" label="来源" width="96" />
                  <ElTableColumn prop="object" label="对象" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="issue" label="问题" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="action" label="建议" min-width="200" show-overflow-tooltip />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElAlert
            class="mt-16px"
            type="info"
            show-icon
            :closable="false"
            title="PageIndex 用于长文档、跨章节、附录和表格依据检索；普通条款命中仍优先走 Clause Index / Hybrid RAG。"
          />
        </template>

        <template v-else-if="projectAuditSubpage === 'langgraph'">
          <div class="workbench-summary-grid project-subpage-kpis">
            <div
              v-for="card in projectAuditLangGraphCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <ElRow :gutter="16">
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>LangGraph 节点执行图</span>
                    <ElSpace>
                      <ElTag effect="plain">{{
                        selectedReviewRun?.run.reviewRunId || '未选中'
                      }}</ElTag>
                      <ElButton
                        v-if="activeReviewRunId"
                        data-testid="fde-open-review-detail"
                        size="small"
                        text
                        @click="openReviewAuditDrawer(String(activeReviewRunId))"
                      >
                        完整详情
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <div class="graph-node-grid">
                  <button
                    v-for="node in reviewGraphNodes"
                    :key="String(node.nodeKey || node.id || node.name)"
                    type="button"
                    class="graph-node-card"
                  >
                    <span>{{ friendlyTechLabel(node.nodeKey || node.id || node.name) }}</span>
                    <strong>{{ friendlyStatus(node.status) }}</strong>
                    <small>
                      队列 {{ shortText(node.taskQueue) }} · 工具
                      {{ toRecordArray(node.toolCalls).length }}
                    </small>
                  </button>
                </div>
                <ElEmpty v-if="!reviewGraphNodes.length" description="暂无 LangGraph 节点数据" />
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Temporal / Checkpoint</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="Workflow">
                    {{
                      selectedReviewTemporal.workflowId || selectedReviewRun?.run.workflowId || '-'
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Run ID">
                    {{ selectedReviewRun?.run.temporalRunId || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="事件数">
                    {{ selectedReviewTemporal.eventCount || reviewGraphTimeline.length || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Graph Runner">
                    {{ selectedReviewRun?.run.graphRunner || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Checkpointer">
                    {{ selectedReviewRun?.run.graphExecution?.checkpointer || '-' }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
              <ElCard shadow="never" class="panel mt-16px">
                <template #header>执行边与时间线</template>
                <ElTable :data="reviewGraphEdges" border height="180">
                  <ElTableColumn prop="source" label="来源" min-width="130" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.source) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="target" label="目标" min-width="130" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.target) }}</template>
                  </ElTableColumn>
                </ElTable>
                <ElTable
                  :data="reviewGraphTimeline.slice(0, 5)"
                  border
                  height="180"
                  class="mt-12px"
                >
                  <ElTableColumn prop="stepName" label="事件" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.stepName) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="110">
                    <template #default="{ row }">{{ friendlyStatus(row.status) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Agent 思考链与工具证据</span>
                    <ElTag effect="plain">{{ normalizedReviewReasoningRows.length }} 步</ElTag>
                  </div>
                </template>
                <ElAlert
                  class="mb-12px"
                  type="info"
                  show-icon
                  :closable="false"
                  title="展示的是可审计推理摘要、工具调用和证据引用，不展示模型内部隐式思维。"
                />
                <div v-if="normalizedReviewReasoningRows.length" class="audit-step-list">
                  <article
                    v-for="row in normalizedReviewReasoningRows"
                    :key="`${row.sequence}-${row.stepName}`"
                    class="audit-step-card"
                  >
                    <div class="audit-step-index">
                      <span>{{ String(row.sequence).padStart(2, '0') }}</span>
                    </div>
                    <div class="audit-step-body">
                      <div class="audit-step-title">
                        <strong>{{ friendlyTechLabel(row.stepName) }}</strong>
                        <ElTag :type="row.qualityPassed ? 'success' : 'warning'" effect="plain">
                          {{ row.qualityText }}
                        </ElTag>
                      </div>
                      <p>{{ row.reasoningSummary }}</p>
                      <div class="audit-step-evidence">
                        <span>证据/依据</span>
                        <strong>{{ shortText(row.evidence, '-') }}</strong>
                      </div>
                      <div class="audit-step-meta">
                        <span class="audit-step-meta-label">证据/规则/条款</span>
                        <span>工具 {{ row.toolCount }}</span>
                        <span>证据 {{ row.evidenceCount }}</span>
                        <span>规则 {{ row.ruleCount }}</span>
                        <span>条款 {{ row.kbCount }}</span>
                      </div>
                      <small v-if="row.toolNames">工具：{{ row.toolNames }}</small>
                    </div>
                  </article>
                </div>
                <ElEmpty v-else description="暂无可审计推理摘要" />
              </ElCard>
            </ElCol>

            <ElCol :xl="11" :lg="11" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>审查草稿结果</span>
                    <ElTag effect="plain">{{ normalizedReviewFindingRows.length }} 条</ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedReviewFindingRows" border height="322">
                  <ElTableColumn
                    prop="findingType"
                    label="类型"
                    min-width="150"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.findingType) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="severity" label="等级" width="82" />
                  <ElTableColumn
                    prop="title"
                    label="发现项"
                    min-width="240"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="置信度" width="90">
                    <template #default="{ row }">{{ scorePercent(row.confidence) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="evidenceCount" label="证据" width="72" />
                  <ElTableColumn prop="referenceCount" label="依据" width="72" />
                  <ElTableColumn label="人工" width="78">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.requiresHumanConfirmation ? 'warning' : 'success'"
                        effect="plain"
                      >
                        {{ row.requiresHumanConfirmation ? '需确认' : '可用' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>质量评估门禁</span>
                    <ElTag
                      :type="reviewQualityEvaluation.status === 'pass' ? 'success' : 'warning'"
                      effect="plain"
                    >
                      {{ reviewQualityEvaluation.score || 0 }}/100
                    </ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedReviewQualityRows" border height="240">
                  <ElTableColumn
                    prop="name"
                    label="门禁/维度"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="100">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'warning'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="评分" width="85">
                    <template #default="{ row }">
                      {{ row.score === undefined ? '-' : scorePercent(row.score) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="message"
                    label="说明"
                    min-width="240"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>

            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>人工修正与样本回流</span>
                    <ElTag effect="plain"
                      >{{ normalizedReviewHumanCorrectionRows.length }} 条</ElTag
                    >
                  </div>
                </template>
                <ElTable :data="normalizedReviewHumanCorrectionRows" border height="240">
                  <ElTableColumn
                    prop="targetType"
                    label="对象"
                    min-width="130"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="correctionType"
                    label="动作"
                    min-width="120"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="before"
                    label="AI 原值"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="after"
                    label="人工修正"
                    min-width="220"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="rootCause"
                    label="归因"
                    min-width="180"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </template>

        <template v-else-if="projectAuditSubpage === 'ocr-labeling'">
          <div class="workbench-summary-grid project-subpage-kpis">
            <div
              v-for="card in projectAuditOcrLabelCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <ElRow :gutter="16" class="mb-16px">
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>标注入评估健康</span>
                    <ElTag effect="plain">{{ projectAuditAnnotationHealthRows.length }} 项</ElTag>
                  </div>
                </template>
                <ElTable :data="projectAuditAnnotationHealthRows" border height="250">
                  <ElTableColumn prop="item" label="检查项" width="150" />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="row.passed ? 'success' : 'warning'" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="evidence"
                    label="证据"
                    min-width="230"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="action"
                    label="处理口径"
                    min-width="260"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>样本缺口与建议</template>
                <ElTable
                  :data="projectAuditAnnotationIssueRows"
                  border
                  height="250"
                  empty-text="暂无缺口"
                >
                  <ElTableColumn prop="source" label="来源" width="92" />
                  <ElTableColumn prop="object" label="对象" min-width="160" show-overflow-tooltip />
                  <ElTableColumn prop="issue" label="缺口" min-width="170" show-overflow-tooltip />
                  <ElTableColumn prop="action" label="建议" min-width="210" show-overflow-tooltip />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16">
            <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>OCR 人工打标样本</span>
                    <ElButton
                      size="small"
                      plain
                      :loading="actionLoading"
                      @click="openFirstOcrAnnotationTask"
                    >
                      打开首个样本
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="normalizedProjectAuditAnnotationRows"
                  border
                  height="460"
                  @row-click="(row) => openAnnotationEditor(row)"
                >
                  <ElTableColumn prop="taskId" label="任务" min-width="150" show-overflow-tooltip />
                  <ElTableColumn
                    prop="scenario"
                    label="场景"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="profileId"
                    label="Profile"
                    min-width="200"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="pageNo" label="页" width="72" />
                  <ElTableColumn label="候选" width="78">
                    <template #default="{ row }">{{ row.candidateTotal }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="已标" width="78">
                    <template #default="{ row }">{{ row.labelTotal }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="缺口" width="78">
                    <template #default="{ row }">
                      <ElTag :type="row.gapTotal ? 'warning' : 'success'" effect="plain">
                        {{ row.gapTotal }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="状态" width="130">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.collectionStatus))" effect="plain">
                        {{ friendlyStatus(row.collectionStatus) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="阻断" min-width="240" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.blockerText }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>标注覆盖率</template>
                <ElTable :data="projectAuditAnnotationCoverageRows" border height="178">
                  <ElTableColumn prop="label" label="对象" width="82" />
                  <ElTableColumn prop="candidates" label="候选" width="78" />
                  <ElTableColumn prop="labeled" label="已标" width="78" />
                  <ElTableColumn label="覆盖率" min-width="110">
                    <template #default="{ row }">
                      <ElTag :type="row.gap ? 'warning' : 'success'" effect="plain">
                        {{ scorePercent(row.coverage) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="gap" label="缺口" width="78" />
                </ElTable>
              </ElCard>
              <ElCard shadow="never" class="panel mt-16px">
                <template #header>阻断原因分布</template>
                <ElTable :data="projectAuditAnnotationBlockerRows" border height="156">
                  <ElTableColumn
                    prop="blocker"
                    label="阻断原因"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="count" label="数量" width="74" />
                </ElTable>
                <ElEmpty
                  v-if="!projectAuditAnnotationBlockerRows.length"
                  description="当前样本无标注阻断"
                />
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>OCR Job 与候选图</template>
                <ElTable
                  :data="projectAuditOcrJobs"
                  border
                  height="250"
                  @row-click="(row) => openOcrAuditDrawer(String(row.jobId || row.id))"
                >
                  <ElTableColumn prop="jobId" label="Job" min-width="160" show-overflow-tooltip />
                  <ElTableColumn
                    prop="profileId"
                    label="Profile"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="92" fixed="right">
                    <template #default="{ row }">
                      <ElButton
                        data-testid="fde-open-ocr-detail"
                        size="small"
                        text
                        @click.stop="openOcrAuditDrawer(String(row.jobId || row.id))"
                      >
                        详情
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel mt-16px">
                <template #header>当前 OCR 结果</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="字段">
                    {{ selectedOcrResultSummary.fieldCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="表格">
                    {{ selectedOcrResultSummary.tableCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="印章">
                    {{ selectedOcrResultSummary.sealCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="候选图">
                    {{ selectedOcrGeneratedVariants.join('、') || '-' }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
            </ElCol>
          </ElRow>
        </template>

        <template v-else-if="projectAuditSubpage === 'evaluation'">
          <div class="workbench-summary-grid project-subpage-kpis">
            <div
              v-for="card in projectAuditEvaluationCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>

          <ElCard shadow="never" class="panel mb-16px">
            <template #header>
              <div class="panel-header">
                <span>评估发布结论</span>
                <ElTag :type="projectAuditEvaluationDecision.tone" effect="plain">
                  {{ projectAuditEvaluationDecision.status }}
                </ElTag>
              </div>
            </template>
            <ElDescriptions :column="3" border>
              <ElDescriptionsItem label="结论">
                {{ projectAuditEvaluationDecision.status }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="原因">
                {{ projectAuditEvaluationDecision.reason }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="下一步">
                {{ projectAuditEvaluationDecision.action }}
              </ElDescriptionsItem>
            </ElDescriptions>
          </ElCard>

          <ElRow :gutter="16">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>准确率评估门禁</template>
                <ElTable :data="projectAuditEvaluationGateRows" border height="260">
                  <ElTableColumn prop="item" label="门禁" min-width="160" show-overflow-tooltip />
                  <ElTableColumn prop="actual" label="当前" width="110" />
                  <ElTableColumn prop="target" label="目标" width="125" />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'warning'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="action"
                    label="处理口径"
                    min-width="250"
                    show-overflow-tooltip
                  />
                </ElTable>
                <ElTable :data="ocrScenarioRows" border height="180" class="mt-12px">
                  <ElTableColumn
                    prop="scenario"
                    label="OCR 场景"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="平均分" width="100">
                    <template #default="{ row }">{{ scorePercent(row.averageScore) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="passed" label="通过" width="82" />
                  <ElTableColumn prop="failed" label="失败" width="82" />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>失败样本与阻断项</template>
                <ElTable :data="failedOcrCaseRows" border height="210">
                  <ElTableColumn prop="caseId" label="样本" min-width="150" show-overflow-tooltip />
                  <ElTableColumn
                    prop="scenario"
                    label="场景"
                    min-width="140"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="分数" width="90">
                    <template #default="{ row }">{{ scorePercent(row.score) }}</template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="finding"
                    label="问题"
                    min-width="220"
                    show-overflow-tooltip
                  />
                </ElTable>
                <ElTable
                  :data="projectAuditEvaluationIssueRows"
                  border
                  height="230"
                  class="mt-12px"
                >
                  <ElTableColumn prop="source" label="来源" width="96" />
                  <ElTableColumn prop="object" label="对象" min-width="160" show-overflow-tooltip />
                  <ElTableColumn prop="issue" label="问题" min-width="210" show-overflow-tooltip />
                  <ElTableColumn
                    prop="action"
                    label="处理建议"
                    min-width="250"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </template>

        <ElRow v-else-if="projectAuditSubpage === 'node'" :gutter="16">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>节点挂载资料</template>
              <ElTable :data="projectAuditBindings" border height="420">
                <ElTableColumn
                  prop="requirementName"
                  label="资料要求"
                  min-width="150"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="fileName" label="文件" min-width="220" show-overflow-tooltip />
                <ElTableColumn prop="versionNo" label="版本" width="82" />
                <ElTableColumn prop="bindingStatus" label="状态" width="120">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.bindingStatus))" effect="plain">
                      {{ friendlyStatus(row.bindingStatus) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn
                  prop="sourceOrgName"
                  label="来源单位"
                  min-width="180"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>资料版本与 OCR 状态</template>
              <ElTable :data="projectAuditDocuments" border height="420">
                <ElTableColumn prop="fileName" label="文件" min-width="230" show-overflow-tooltip />
                <ElTableColumn
                  prop="currentVersionId"
                  label="当前版本"
                  min-width="140"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="currentOcrStatus" label="OCR" width="120">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.currentOcrStatus))" effect="plain">
                      {{ friendlyStatus(row.currentOcrStatus) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn
                  prop="uploaderName"
                  label="上传人"
                  min-width="130"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="updatedAt"
                  label="更新时间"
                  min-width="150"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>

        <ElRow v-else-if="projectAuditSubpage === 'submissions'" :gutter="16">
          <ElCol :span="24">
            <ElCard shadow="never" class="panel">
              <template #header>提交批次</template>
              <ElTable :data="projectAuditSubmissions" border height="460">
                <ElTableColumn prop="id" label="批次" min-width="150" show-overflow-tooltip />
                <ElTableColumn
                  prop="batchName"
                  label="名称"
                  min-width="220"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="status" label="状态" width="145">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="节点范围" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ shortText(row.nodeNames || row.nodeIds) }}
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="bindingCount" label="资料数" width="90" />
                <ElTableColumn
                  prop="submitterName"
                  label="提交人"
                  min-width="130"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="submittedAt"
                  label="提交时间"
                  min-width="150"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>

        <ElRow v-else-if="projectAuditSubpage === 'agent'" :gutter="16">
          <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>Agent 审查任务</template>
              <ElTable
                :data="projectAuditReviewRuns"
                border
                height="420"
                @row-click="(row) => openReviewAuditDrawer(String(row.reviewRunId || row.id))"
              >
                <ElTableColumn
                  prop="reviewRunId"
                  label="ReviewRun"
                  min-width="180"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="workflowId"
                  label="Workflow"
                  min-width="190"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="agentId" label="Agent" min-width="170" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="145">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="当前步骤" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyStatus(row.currentStep) }}</template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="96" fixed="right">
                  <template #default="{ row }">
                    <ElButton
                      size="small"
                      text
                      @click.stop="openReviewAuditDrawer(String(row.reviewRunId || row.id))"
                    >
                      详情
                    </ElButton>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>当前任务溯源</template>
              <ElDescriptions v-if="selectedReviewRun" :column="1" border>
                <ElDescriptionsItem label="ReviewRun">
                  {{ selectedReviewRun.run.reviewRunId || selectedReviewRun.run.id }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="模型">
                  {{ selectedReviewRun.run.modelAlias || '-' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="Graph">
                  {{ selectedReviewRun.run.graphEngine || '-' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="Checkpoint">
                  {{ selectedReviewRun.run.graphExecution?.checkpointer || '-' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="输入 Hash">
                  {{ selectedReviewRun.run.inputHash || '-' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="输出 Hash">
                  {{ selectedReviewRun.run.outputHash || '-' }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElEmpty v-else description="请选择 Agent 审查任务" />
            </ElCard>
            <ElCard shadow="never" class="panel mt-16px">
              <template #header>决策链摘要</template>
              <ElTable :data="reviewReasoningTraceRows" border height="220">
                <ElTableColumn prop="stepName" label="步骤" min-width="150" show-overflow-tooltip />
                <ElTableColumn
                  prop="reasoningSummary"
                  label="摘要"
                  min-width="260"
                  show-overflow-tooltip
                />
                <ElTableColumn label="质量" width="95">
                  <template #default="{ row }">
                    <ElTag :type="row.quality?.passed ? 'success' : 'warning'" effect="plain">
                      {{ row.quality?.passed ? '通过' : '需复核' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>

        <ElRow v-else-if="projectAuditSubpage === 'ocr'" :gutter="16">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>OCR 运行任务</template>
              <ElTable
                :data="projectAuditOcrJobs"
                border
                height="420"
                @row-click="(row) => openOcrAuditDrawer(String(row.jobId || row.id))"
              >
                <ElTableColumn prop="jobId" label="Job" min-width="160" show-overflow-tooltip />
                <ElTableColumn
                  prop="profileId"
                  label="Profile"
                  min-width="210"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="status" label="状态" width="145">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn
                  prop="parseResultId"
                  label="结果"
                  min-width="150"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="engineRuns" label="引擎" width="82" />
                <ElTableColumn label="操作" width="96" fixed="right">
                  <template #default="{ row }">
                    <ElButton
                      size="small"
                      text
                      @click.stop="openOcrAuditDrawer(String(row.jobId || row.id))"
                    >
                      详情
                    </ElButton>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>OCR 人工标定样本</template>
              <ElTable
                :data="projectAuditAnnotationTasks"
                border
                height="420"
                @row-click="(row) => openAnnotationEditor(row)"
              >
                <ElTableColumn prop="taskId" label="任务" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="scenario" label="场景" min-width="180" show-overflow-tooltip />
                <ElTableColumn
                  prop="profileId"
                  label="Profile"
                  min-width="190"
                  show-overflow-tooltip
                />
                <ElTableColumn label="状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.collectionStatus))" effect="plain">
                      {{ friendlyStatus(row.collectionStatus) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="阻断" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ shortText(row.readinessBlockers || row.certificationBlockers) }}
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
        </ElRow>

        <ElRow v-else-if="projectAuditSubpage === 'quality'" :gutter="16">
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>质量阻断项</template>
              <ElTable :data="projectAuditBlockers" border height="420">
                <ElTableColumn label="域" width="92">
                  <template #default="{ row }">
                    <ElTag :type="blockerLevelType(row.level)" effect="plain">
                      {{ blockerTypeLabel(row.type) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="title" label="问题" min-width="220" show-overflow-tooltip />
                <ElTableColumn
                  prop="targetName"
                  label="对象"
                  min-width="150"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="action"
                  label="处理建议"
                  min-width="260"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>节点状态分布</template>
              <ElTable :data="nodeStatusSummary" border height="200">
                <ElTableColumn prop="status" label="状态" min-width="150" />
                <ElTableColumn prop="count" label="数量" width="90" />
              </ElTable>
            </ElCard>
            <ElCard shadow="never" class="panel mt-16px">
              <template #header>OCR 全局门禁参考</template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="OCR 100">
                  {{
                    ocr100Scorecard
                      ? `${ocr100Scorecard.score}/${ocr100Scorecard.targetScore}`
                      : '-'
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="运行时">
                  {{ friendlyStatus(ocrRuntimeDoctor?.status, '未知') }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="待标注">
                  {{ ocrPendingAnnotationCount }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="可评估">
                  {{ ocrReadyForEvalCount }}
                </ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
        </ElRow>
      </div>

      <ElTabs v-else v-model="activeFdeTab" class="fde-tabs">
        <ElTabPane label="AI 驾驶舱" name="dashboard">
          <ElRow :gutter="16">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Agent 绩效</template>
                <ElTable :data="dashboard?.agentPerformance || []" border height="320">
                  <ElTableColumn
                    prop="agentId"
                    label="Agent"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="version" label="版本" width="100" />
                  <ElTableColumn prop="riskLevel" label="风险" width="90" />
                  <ElTableColumn label="采纳率" width="95">
                    <template #default="{ row }">{{ percent(row.acceptanceRate) }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="证据" width="95">
                    <template #default="{ row }">{{ percent(row.evidenceHitRate) }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="幻觉" width="95">
                    <template #default="{ row }">{{ percent(row.hallucinationRate) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>风险告警</template>
                <ElTable :data="dashboard?.alerts || []" border height="320">
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn prop="title" label="告警" min-width="210" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="110" />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>治理摘要</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="Token">
                    {{ dashboard?.cost.tokenEstimate || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="估算费用">
                    {{ dashboard?.cost.estimatedPrice || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="预算状态">
                    {{ friendlyStatus(dashboard?.cost.budgetStatus) }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="能力组合">
                    {{ dashboard?.releaseStatus.bundles || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="待审批发布">
                    {{ dashboard?.releaseStatus.pendingApprovals || 0 }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>
        <ElTabPane label="AI Run 追踪" name="runs">
          <ElRow :gutter="16">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>不可变 Run 列表</span>
                    <ElButton size="small" plain :loading="actionLoading" @click="replayFirstRun">
                      诊断重跑
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="aiRuns"
                  border
                  height="360"
                  @row-click="(row) => loadRunDetail(row.id)"
                >
                  <ElTableColumn prop="id" label="Run ID" min-width="190" show-overflow-tooltip />
                  <ElTableColumn
                    prop="agentId"
                    label="Agent"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="110">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" effect="plain">{{
                        friendlyStatus(row.status)
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="runType" label="类型" width="130" />
                  <ElTableColumn prop="immutable" label="审计" width="90">
                    <template #default="{ row }">
                      <ElTag v-if="row.immutable" type="success" effect="plain">不可变</ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Trace 明细</span>
                    <ElButton size="small" plain :loading="actionLoading" @click="requestRawAccess">
                      申请原文
                    </ElButton>
                  </div>
                </template>
                <ElDescriptions v-if="selectedRun" :column="1" border>
                  <ElDescriptionsItem label="Run">{{ selectedRun.run.id }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="输入 Hash">{{
                    selectedRun.run.inputHash
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="输出 Hash">{{
                    selectedRun.run.outputHash
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="原文权限">
                    {{ selectedRun.accessPolicy.rawAccess ? '已授权' : '脱敏查看' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="重跑次数">{{
                    selectedRun.replays.length
                  }}</ElDescriptionsItem>
                </ElDescriptions>
                <ElTable v-if="selectedRun" :data="selectedRun.traceSteps" border class="mt-12px">
                  <ElTableColumn prop="sequence" label="#" width="112" />
                  <ElTableColumn prop="name" label="步骤" min-width="180" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="110" />
                  <ElTableColumn prop="latencyMs" label="耗时" width="110" />
                </ElTable>
                <ElEmpty v-else description="请选择 AI Run" />
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElAlert
                title="这里展示的是可审计 Agent 决策链：推理摘要、工具调用、证据、规则、知识引用和质量门禁；不会展示模型内部原始隐式思维。"
                type="info"
                show-icon
                :closable="false"
              />
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24" class="mt-12px">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Agent 决策链</span>
                    <ElTag effect="plain">summary only</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewReasoningTraceRows" border height="420">
                  <ElTableColumn prop="sequence" label="#" width="74" />
                  <ElTableColumn
                    prop="stepName"
                    label="步骤"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="reasoningSummary"
                    label="推理摘要"
                    min-width="320"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="工具" min-width="210" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{
                        (row.toolCalls || [])
                          .map((item) => item.toolName)
                          .filter(Boolean)
                          .join('，') || '-'
                      }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="引用" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">
                      证据 {{ (row.evidenceRefs || []).length }} / 规则
                      {{ (row.ruleRefs || []).length }} / 条款 {{ (row.kbRefs || []).length }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="质量" width="145">
                    <template #default="{ row }">
                      <ElTag :type="row.quality?.passed ? 'success' : 'danger'" effect="plain">
                        {{ row.quality?.passed ? '通过' : '需复核' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="输出 Hash" min-width="220" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ row.outputSummary?.outputHash || row.outputSummary?.detailsHash || '-' }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>溯源快照</template>
                <ElTable :data="reviewLineageRows" border height="320">
                  <ElTableColumn prop="label" label="项" width="130" show-overflow-tooltip />
                  <ElTableColumn label="值" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.value) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>质量评估</span>
                    <ElSpace>
                      <ElTag effect="plain">{{ reviewQualityGateRows.length }} 门禁</ElTag>
                      <ElTag
                        :type="reviewQualityEvaluation.status === 'pass' ? 'success' : 'warning'"
                        effect="plain"
                      >
                        {{ reviewQualityEvaluation.score || 0 }}/100
                      </ElTag>
                    </ElSpace>
                  </div>
                </template>
                <ElTable :data="reviewQualityRows" border height="320">
                  <ElTableColumn
                    prop="dimension"
                    label="评估项"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="95">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="failureCount" label="失败" width="80" />
                  <ElTableColumn prop="warningCount" label="告警" width="80" />
                  <ElTableColumn
                    prop="finding"
                    label="首要问题"
                    min-width="170"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24" class="mt-16px">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>人工修正与样本回流</span>
                    <ElTag effect="plain">{{ reviewHumanCorrectionRows.length }} 条</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewHumanCorrectionRows" border height="300">
                  <ElTableColumn
                    prop="feedbackType"
                    label="修正类型"
                    min-width="140"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="rootCause"
                    label="归因"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="beforeSummary"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.afterSummary) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="shouldEnterEvaluationSet" label="入评估集" width="100">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.shouldEnterEvaluationSet ? 'success' : 'info'"
                        effect="plain"
                      >
                        {{ row.shouldEnterEvaluationSet ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElAlert
                title="这里展示的是可审计 Agent 决策链：推理摘要、工具调用、证据、规则、知识引用和质量门禁；不会展示模型内部原始隐式思维。"
                type="info"
                show-icon
                :closable="false"
              />
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24" class="mt-12px">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Agent 决策链</span>
                    <ElTag effect="plain">summary only</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewReasoningTraceRows" border height="420">
                  <ElTableColumn prop="sequence" label="#" width="74" />
                  <ElTableColumn
                    prop="stepName"
                    label="步骤"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="reasoningSummary"
                    label="推理摘要"
                    min-width="320"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="工具" min-width="210" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{
                        (row.toolCalls || [])
                          .map((item) => item.toolName)
                          .filter(Boolean)
                          .join('，') || '-'
                      }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="引用" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">
                      证据 {{ (row.evidenceRefs || []).length }} / 规则
                      {{ (row.ruleRefs || []).length }} / 条款 {{ (row.kbRefs || []).length }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="质量" width="145">
                    <template #default="{ row }">
                      <ElTag :type="row.quality?.passed ? 'success' : 'danger'" effect="plain">
                        {{ row.quality?.passed ? '通过' : '需复核' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="输出 Hash" min-width="220" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ row.outputSummary?.outputHash || row.outputSummary?.detailsHash || '-' }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>溯源快照</template>
                <ElTable :data="reviewLineageRows" border height="320">
                  <ElTableColumn prop="label" label="项" width="130" show-overflow-tooltip />
                  <ElTableColumn label="值" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.value) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>质量评估</span>
                    <ElSpace>
                      <ElTag effect="plain">{{ reviewQualityGateRows.length }} 门禁</ElTag>
                      <ElTag
                        :type="reviewQualityEvaluation.status === 'pass' ? 'success' : 'warning'"
                        effect="plain"
                      >
                        {{ reviewQualityEvaluation.score || 0 }}/100
                      </ElTag>
                    </ElSpace>
                  </div>
                </template>
                <ElTable :data="reviewQualityRows" border height="320">
                  <ElTableColumn
                    prop="dimension"
                    label="评估项"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="95">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="failureCount" label="失败" width="80" />
                  <ElTableColumn prop="warningCount" label="告警" width="80" />
                  <ElTableColumn
                    prop="finding"
                    label="首要问题"
                    min-width="170"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24" class="mt-16px">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>人工修正与样本回流</span>
                    <ElTag effect="plain">{{ reviewHumanCorrectionRows.length }} 条</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewHumanCorrectionRows" border height="300">
                  <ElTableColumn
                    prop="feedbackType"
                    label="修正类型"
                    min-width="140"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="rootCause"
                    label="归因"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="beforeSummary"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.afterSummary) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="120" />
                  <ElTableColumn prop="shouldEnterEvaluationSet" label="入评估集" width="100">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.shouldEnterEvaluationSet ? 'success' : 'info'"
                        effect="plain"
                      >
                        {{ row.shouldEnterEvaluationSet ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>评估报告门禁</template>
                <ElDescriptions v-if="latestEvaluationReport" :column="1" border>
                  <ElDescriptionsItem label="状态">
                    <ElTag :type="statusType(latestEvaluationReport.status)" effect="plain">
                      {{ friendlyStatus(latestEvaluationReport.status) }}
                    </ElTag>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="样本">{{
                    latestEvaluationCaseSummary.cases || 0
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="通过率">{{
                    scorePercent(Number(latestEvaluationCaseSummary.casePassRate || 0))
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="Finding 召回">{{
                    scorePercent(Number(latestEvaluationCaseSummary.findingRecall || 0))
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="证据覆盖">{{
                    scorePercent(Number(latestEvaluationCaseSummary.evidenceCoverage || 0))
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="检索召回">{{
                    scorePercent(Number(latestEvaluationCaseSummary.retrievalRecall || 0))
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="错误依据率">{{
                    scorePercent(Number(latestEvaluationCaseSummary.wrongReferenceRate || 0))
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="PageIndex 触发">{{
                    scorePercent(Number(latestEvaluationCaseSummary.pageIndexTriggerRate || 0))
                  }}</ElDescriptionsItem>
                </ElDescriptions>
                <ElEmpty v-else description="暂无评估报告" />
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>样本级结果</span>
                    <ElTag effect="plain">失败 {{ failedEvaluationCaseRows.length }}</ElTag>
                  </div>
                </template>
                <ElTable :data="evaluationCaseRows" border height="320">
                  <ElTableColumn
                    prop="evaluationCaseId"
                    label="Case"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="110">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">{{
                        row.status
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="rootCause"
                    label="归因"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="matchedFindingCount" label="命中" width="80" />
                  <ElTableColumn prop="expectedFindingCount" label="预期" width="80" />
                  <ElTableColumn prop="evidencePassed" label="证据" width="90">
                    <template #default="{ row }">
                      <ElTag :type="row.evidencePassed ? 'success' : 'danger'" effect="plain">
                        {{ row.evidencePassed ? '通过' : '失败' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="retrievalPassed" label="检索" width="90">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.retrievalPassed === false ? 'danger' : 'success'"
                        effect="plain"
                      >
                        {{ row.retrievalPassed === false ? '失败' : '通过' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="selectedRoute"
                    label="路由"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="缺失条款" min-width="180" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ (row.missingClauseIds || []).join('；') || '-' }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="缺失 Finding" min-width="220" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ (row.missingFindings || []).join('；') || '-' }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="任务编排" name="orchestration">
          <div class="workbench-summary-grid">
            <div
              v-for="card in agentStatusCards"
              :key="card.label"
              :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </div>
          </div>
          <ElAlert
            class="mb-16px"
            :type="hasReviewRuns ? 'success' : 'warning'"
            show-icon
            :closable="false"
            :title="reviewRunConclusion"
          />
          <div class="subpage-switch mb-16px">
            <button
              v-for="item in agentSubpageItems"
              :key="item.key"
              type="button"
              :class="{ active: agentSubpage === item.key }"
              @click="agentSubpage = item.key"
            >
              <span>{{ item.label }}</span>
              <small>{{ item.description }}</small>
            </button>
          </div>
          <ElRow v-if="agentSubpage === 'runs'" :gutter="16">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Temporal Workflow / LangGraph Run</span>
                    <ElSpace>
                      <ElButton
                        size="small"
                        plain
                        :disabled="!firstReviewRunId"
                        :loading="actionLoading"
                        @click="replayFirstReviewRun"
                      >
                        诊断重跑
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :disabled="!firstReviewRunId"
                        :loading="actionLoading"
                        @click="shadowFirstReviewRun"
                      >
                        Shadow
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable
                  v-if="hasReviewRuns"
                  :data="reviewRuns"
                  border
                  height="360"
                  @row-click="(row) => openReviewAuditDrawer(String(row.reviewRunId || row.id))"
                >
                  <ElTableColumn
                    prop="reviewRunId"
                    label="ReviewRun"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="workflowId"
                    label="Workflow"
                    min-width="210"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="workflowEngine" label="外层" width="110" />
                  <ElTableColumn prop="graphEngine" label="内层" width="110" />
                  <ElTableColumn prop="status" label="状态" width="140">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="当前步骤" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ friendlyStatus(row.currentStep) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="96" fixed="right">
                    <template #default="{ row }">
                      <ElButton
                        size="small"
                        text
                        @click.stop="openReviewAuditDrawer(String(row.reviewRunId || row.id))"
                      >
                        详情
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <div v-else class="empty-workbench">
                  <div class="empty-workbench__copy">
                    <strong>暂无 ReviewRun</strong>
                    <span>
                      当前没有可追踪的 Agent 审查任务。FDE 可以先处理 OCR 阻断，或从业务审查页触发
                      AI 复核后回到这里审计决策链。
                    </span>
                  </div>
                  <div class="empty-workbench__steps">
                    <div v-for="item in agentEmptyGuideRows" :key="item.label">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                    </div>
                  </div>
                  <ElSpace wrap>
                    <ElButton type="primary" plain @click="goFdeRoute('/fde/ocr-quality')">
                      先检查 OCR 输入质量
                    </ElButton>
                    <ElButton plain :loading="loading" @click="loadData">刷新任务</ElButton>
                  </ElSpace>
                </div>
              </ElCard>
            </ElCol>
            <ElCol v-if="hasReviewRuns" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>编排审计摘要</template>
                <ElDescriptions v-if="selectedReviewRun" :column="1" border>
                  <ElDescriptionsItem label="ReviewRun">
                    {{ selectedReviewRun.run.reviewRunId }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="AI Run">
                    {{ selectedReviewRun.run.aiRunId || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="模型网关">
                    {{ selectedReviewRun.run.modelGateway || 'litellm' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="模型别名">
                    {{ selectedReviewRun.run.modelAlias || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Graph Runner">
                    {{
                      selectedReviewRun.run.graphRunner || selectedReviewRun.run.graphEngine || '-'
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Checkpoint">
                    {{
                      selectedReviewRun.run.graphExecution?.checkpointer ||
                      selectedReviewRun.run.graphExecution?.fallbackReason ||
                      '-'
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="输入 Hash">
                    {{ selectedReviewRun.run.inputHash || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="输出 Hash">
                    {{ selectedReviewRun.run.outputHash || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Temporal">
                    {{
                      selectedReviewTemporal.workflowId || selectedReviewRun.run.workflowId || '-'
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="事件数">
                    {{ selectedReviewTemporal.eventCount || reviewGraphTimeline.length }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Payload 策略">
                    {{ selectedReviewTemporal.historyPolicy || 'ids_hashes_versions_only' }}
                  </ElDescriptionsItem>
                </ElDescriptions>
                <div v-if="selectedReviewRun" class="artifact-summary-grid mt-12px">
                  <div
                    v-for="item in reviewArtifactRows"
                    :key="item.label"
                    class="artifact-summary-item"
                  >
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </div>
                </div>
                <template v-if="reviewScorecard">
                  <div class="gate-summary mt-12px">
                    <div class="gate-summary-item">
                      <span>编排 100</span>
                      <strong>{{ reviewScorecard.score }}/{{ reviewScorecard.targetScore }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>生产就绪</span>
                      <strong>
                        <ElTag :type="reviewScorecard.ok ? 'success' : 'danger'" effect="plain">
                          {{ reviewScorecard.ok ? '就绪' : '存在阻断' }}
                        </ElTag>
                      </strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>评分域</span>
                      <strong>{{ reviewScorecardSections.length }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>阻断项</span>
                      <strong>{{ reviewScorecard.blockers.length }}</strong>
                    </div>
                  </div>
                  <ElTable :data="reviewScorecardSections" border height="180" class="mt-12px">
                    <ElTableColumn
                      prop="name"
                      label="评分域"
                      min-width="130"
                      show-overflow-tooltip
                    />
                    <ElTableColumn label="分数" width="105">
                      <template #default="{ row }">{{ row.score }}/{{ row.maxScore }}</template>
                    </ElTableColumn>
                    <ElTableColumn prop="status" label="状态" width="95">
                      <template #default="{ row }">
                        <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                          {{ friendlyStatus(row.status) }}
                        </ElTag>
                      </template>
                    </ElTableColumn>
                  </ElTable>
                  <ElTable
                    v-if="reviewScorecardBlockerRows.length"
                    :data="reviewScorecardBlockerRows"
                    border
                    height="180"
                    class="mt-12px"
                  >
                    <ElTableColumn prop="id" label="#" width="112" />
                    <ElTableColumn
                      prop="blocker"
                      label="编排阻断项"
                      min-width="260"
                      show-overflow-tooltip
                    />
                  </ElTable>
                </template>
                <ElTable
                  v-if="reviewNodeStatusRows.length"
                  :data="reviewNodeStatusRows"
                  border
                  height="160"
                  class="mt-12px"
                >
                  <ElTableColumn label="节点状态">
                    <template #default="{ row }">
                      {{ friendlyStatus(row.status) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="count" label="数量" width="90" />
                </ElTable>
                <ElEmpty v-if="!selectedReviewRun" description="请选择 ReviewRun" />
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow
            v-if="hasReviewRuns && (agentSubpage === 'reasoning' || agentSubpage === 'quality')"
            :gutter="16"
            class="mt-16px"
          >
            <ElCol v-if="agentSubpage === 'reasoning'" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElAlert
                title="这里展示的是可审计 Agent 决策链：推理摘要、工具调用、证据、规则、知识引用和质量门禁；不会展示模型内部原始隐式思维。"
                type="info"
                show-icon
                :closable="false"
              />
            </ElCol>
            <ElCol
              v-if="agentSubpage === 'reasoning'"
              :xl="24"
              :lg="24"
              :md="24"
              :sm="24"
              :xs="24"
              class="mt-12px"
            >
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Agent 决策链</span>
                    <ElTag effect="plain">summary only</ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedReviewReasoningRows" border height="360">
                  <ElTableColumn prop="sequence" label="#" width="74" />
                  <ElTableColumn
                    prop="stepName"
                    label="步骤"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="reasoningSummary"
                    label="推理摘要"
                    min-width="320"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="工具" min-width="210" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ row.toolCount ? `${row.toolCount} 个：${row.toolNames || '-'}` : '-' }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="引用" min-width="230" show-overflow-tooltip>
                    <template #default="{ row }">
                      证据 {{ row.evidenceCount }} / 规则 {{ row.ruleCount }} / 条款 {{ row.kbCount }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="质量" width="120">
                    <template #default="{ row }">
                      <ElTag :type="row.qualityPassed ? 'success' : 'warning'" effect="plain">
                        {{ row.qualityText }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol
              v-if="agentSubpage === 'reasoning'"
              :xl="12"
              :lg="12"
              :md="24"
              :sm="24"
              :xs="24"
              class="mt-16px"
            >
              <ElCard shadow="never" class="panel">
                <template #header>溯源快照</template>
                <ElTable :data="reviewLineageRows" border height="300">
                  <ElTableColumn prop="label" label="项" width="130" show-overflow-tooltip />
                  <ElTableColumn label="值" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.value) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol
              v-if="agentSubpage === 'quality'"
              :xl="12"
              :lg="12"
              :md="24"
              :sm="24"
              :xs="24"
              class="mt-16px"
            >
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>质量评估</span>
                    <ElTag effect="plain">{{ reviewQualityGateRows.length }} 门禁</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewQualityRows" border height="300">
                  <ElTableColumn
                    prop="dimension"
                    label="评估项"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="95">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="failureCount" label="失败" width="80" />
                  <ElTableColumn prop="warningCount" label="告警" width="80" />
                  <ElTableColumn
                    prop="finding"
                    label="首要问题"
                    min-width="170"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol
              v-if="agentSubpage === 'quality'"
              :xl="12"
              :lg="12"
              :md="24"
              :sm="24"
              :xs="24"
              class="mt-16px"
            >
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>人工修正与样本回流</span>
                    <ElTag effect="plain">{{ reviewHumanCorrectionRows.length }} 条</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewHumanCorrectionRows" border height="260">
                  <ElTableColumn
                    prop="feedbackType"
                    label="修正类型"
                    min-width="140"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="rootCause"
                    label="归因"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="beforeSummary"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.afterSummary) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="120" />
                  <ElTableColumn prop="shouldEnterEvaluationSet" label="入评估集" width="100">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.shouldEnterEvaluationSet ? 'success' : 'info'"
                        effect="plain"
                      >
                        {{ row.shouldEnterEvaluationSet ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow v-if="hasReviewRuns && agentSubpage === 'trace'" :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  LangGraph 节点
                  <ElTag class="ml-8px" effect="plain">edges {{ reviewGraphEdges.length }}</ElTag>
                </template>
                <ElTable :data="reviewGraphNodes" border height="420">
                  <ElTableColumn prop="sequence" label="#" width="112" />
                  <ElTableColumn prop="label" label="节点" min-width="180" show-overflow-tooltip />
                  <ElTableColumn prop="nodeKey" label="Key" min-width="170" show-overflow-tooltip />
                  <ElTableColumn
                    prop="taskQueue"
                    label="队列"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="attempt" label="尝试" width="80" />
                  <ElTableColumn label="工具" min-width="170" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{
                        (row.toolCalls || [])
                          .map((item) => item.toolName)
                          .filter(Boolean)
                          .join(', ') || '-'
                      }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="产物" min-width="230">
                    <template #default="{ row }">
                      <ElSpace wrap>
                        <ElTag
                          v-if="nodeArtifactCount(row, 'ruleResults')"
                          type="success"
                          effect="plain"
                        >
                          规则 {{ nodeArtifactCount(row, 'ruleResults') }}
                        </ElTag>
                        <ElTag
                          v-if="nodeArtifactCount(row, 'retrievalTraces')"
                          type="primary"
                          effect="plain"
                        >
                          Trace {{ nodeArtifactCount(row, 'retrievalTraces') }}
                        </ElTag>
                        <ElTag v-if="nodeArtifactCount(row, 'toolCalls')" effect="plain">
                          工具 {{ nodeArtifactCount(row, 'toolCalls') }}
                        </ElTag>
                        <ElTag
                          v-if="nodeArtifactCount(row, 'validationFailures')"
                          type="danger"
                          effect="plain"
                        >
                          失败 {{ nodeArtifactCount(row, 'validationFailures') }}
                        </ElTag>
                        <span
                          v-if="
                            !nodeArtifactCount(row, 'ruleResults') &&
                            !nodeArtifactCount(row, 'retrievalTraces') &&
                            !nodeArtifactCount(row, 'toolCalls') &&
                            !nodeArtifactCount(row, 'validationFailures')
                          "
                        >
                          -
                        </span>
                      </ElSpace>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Workflow 时间线</template>
                <ElTable :data="reviewGraphTimeline" border height="420">
                  <ElTableColumn
                    prop="createdAt"
                    label="时间"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="eventType"
                    label="事件"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="title" label="说明" min-width="220" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow v-if="hasReviewRuns && agentSubpage === 'trace'" :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>规则结果</template>
                <ElTable :data="reviewRuleResultRows" border height="260">
                  <ElTableColumn
                    prop="ruleCode"
                    label="规则"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="result" label="结果" width="90">
                    <template #default="{ row }">
                      <ElTag :type="row.result === 'passed' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.result) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn label="条款" min-width="160" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ (row.linkedClauseIds || []).join('；') || '-' }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>检索 Trace</template>
                <ElTable :data="reviewRetrievalTraceRows" border height="260">
                  <ElTableColumn
                    prop="retrievalTraceId"
                    label="Trace"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="selectedRoute"
                    label="路由"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="selectedClauseCount" label="条款" width="80" />
                  <ElTableColumn prop="pageIndexNodeCount" label="PageIndex" width="105" />
                  <ElTableColumn label="命中条款" min-width="180" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ (row.selectedClauseIds || []).join('；') || '-' }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Finding Draft</template>
                <ElTable :data="normalizedReviewFindingRows" border height="260">
                  <ElTableColumn prop="id" label="Draft" min-width="145" show-overflow-tooltip />
                  <ElTableColumn
                    prop="findingType"
                    label="类型"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn
                    prop="title"
                    label="审查发现"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="置信度" width="90">
                    <template #default="{ row }">{{ scorePercent(row.confidence) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="evidenceCount" label="证据" width="72" />
                  <ElTableColumn prop="referenceCount" label="依据" width="72" />
                  <ElTableColumn prop="requiresHumanConfirmation" label="人工确认" width="100">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.requiresHumanConfirmation ? 'warning' : 'danger'"
                        effect="plain"
                      >
                        {{ row.requiresHumanConfirmation ? '需要' : '缺失' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="反馈与评估" name="feedback">
          <ElRow :gutter="16">
            <ElCol v-if="isFdeRoute('feedback')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>人工反馈池</span>
                    <ElButton
                      size="small"
                      plain
                      :loading="actionLoading"
                      @click="triageFirstFeedback"
                    >
                      归因首条
                    </ElButton>
                  </div>
                </template>
                <ElTable :data="feedback" border height="320" @row-click="selectFeedback">
                  <ElTableColumn prop="feedbackType" label="类型" width="150" />
                  <ElTableColumn prop="rootCause" label="归因" width="160" />
                  <ElTableColumn prop="status" label="状态" width="120" />
                  <ElTableColumn prop="governanceState" label="治理" width="145">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.governanceState === 'promoted_to_eval' ? 'success' : 'warning'"
                        effect="plain"
                      >
                        {{ row.governanceState || 'needs_triage' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="evaluationCaseId"
                    label="评估样本"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="canUseForEval" label="入评估" width="95">
                    <template #default="{ row }">
                      <ElTag :type="row.canUseForEval ? 'success' : 'info'" effect="plain">
                        {{ row.canUseForEval ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="canUseForTraining" label="训练" width="85">
                    <template #default="{ row }">
                      <ElTag :type="row.canUseForTraining ? 'success' : 'info'" effect="plain">
                        {{ row.canUseForTraining ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="adjudicationRequired" label="仲裁" width="85">
                    <template #default="{ row }">
                      <ElTag :type="row.adjudicationRequired ? 'danger' : 'info'" effect="plain">
                        {{ row.adjudicationRequired ? '需要' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="dataSensitivity" label="数据" width="100" />
                  <ElTableColumn
                    prop="comment"
                    label="说明"
                    min-width="220"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol v-if="isFdeRoute('evaluation')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>评估实验室</span>
                    <ElButton size="small" plain :loading="actionLoading" @click="startEvaluation">
                      发起评测
                    </ElButton>
                  </div>
                </template>
                <ElTable :data="evaluation?.sets || []" border height="320">
                  <ElTableColumn prop="name" label="评估集" min-width="220" show-overflow-tooltip />
                  <ElTableColumn prop="setType" label="类型" width="120" />
                  <ElTableColumn prop="caseCount" label="样本" width="90" />
                  <ElTableColumn prop="status" label="状态" width="110" />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="版本与发布" name="release">
          <ElRow :gutter="16">
            <ElCol
              v-if="isFdeRoute('capability-bundles')"
              :xl="24"
              :lg="24"
              :md="24"
              :sm="24"
              :xs="24"
            >
              <ElCard shadow="never" class="panel">
                <template #header>能力版本组合</template>
                <ElTable
                  :data="bundles?.bundles || []"
                  border
                  height="320"
                  @row-click="selectBundle"
                >
                  <ElTableColumn prop="name" label="组合" min-width="220" show-overflow-tooltip />
                  <ElTableColumn prop="riskLevel" label="风险" width="100" />
                  <ElTableColumn prop="status" label="状态" width="130">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">{{
                        row.status
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol v-if="isFdeRoute('releases')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>发布计划</span>
                    <ElSpace>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="importDemoOcrAnnotationPack"
                      >
                        导入示例
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="submitReleaseGate"
                      >
                        提交门禁
                      </ElButton>
                      <ElButton size="small" plain :loading="actionLoading" @click="startShadowRun">
                        Shadow
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="markShadowPassed"
                      >
                        Shadow 通过
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable
                  :data="releases?.plans || []"
                  border
                  height="320"
                  @row-click="selectRelease"
                >
                  <ElTableColumn prop="id" label="发布单" min-width="170" show-overflow-tooltip />
                  <ElTableColumn prop="riskLevel" label="风险" width="100" />
                  <ElTableColumn prop="status" label="状态" width="150" />
                  <ElTableColumn
                    prop="changeSummary"
                    label="摘要"
                    min-width="240"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
            <ElCol
              v-if="isFdeRoute('capability-bundles')"
              :xl="24"
              :lg="24"
              :md="24"
              :sm="24"
              :xs="24"
            >
              <ElCard shadow="never" class="panel">
                <template #header>能力组合差异</template>
                <ElTable :data="bundleDiffRows" border height="240">
                  <ElTableColumn prop="field" label="组件" min-width="160" show-overflow-tooltip />
                  <ElTableColumn
                    prop="before"
                    label="当前生产/基线"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="after"
                    label="候选值"
                    min-width="190"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol v-if="isFdeRoute('releases')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>发布影响范围</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="项目数">
                    {{ releaseImpactSummary.affectedProjectCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="ReviewRun">
                    {{ releaseImpactSummary.affectedReviewRunCount || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="门禁阻断">
                    {{ releaseGateBlockers.join('；') || '无' }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="交付治理" name="delivery">
          <ElRow :gutter="16">
            <ElCol v-if="isFdeRoute('business-packs')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>业务包门禁</span>
                    <ElButton
                      size="small"
                      plain
                      :loading="actionLoading"
                      @click="installBusinessPack"
                    >
                      安装演练
                    </ElButton>
                  </div>
                </template>
                <ElDescriptions v-if="packValidation" :column="1" border>
                  <ElDescriptionsItem label="整体状态">{{
                    packValidation.ok ? '通过' : '失败'
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="可迁移评分">
                    {{ packValidation.scorecard?.score ?? '-' }}/{{
                      packValidation.scorecard?.targetScore ?? 100
                    }}
                    <ElTag
                      v-if="packValidation.scorecard"
                      class="ml-8px"
                      :type="packValidation.scorecard.ok ? 'success' : 'danger'"
                      effect="plain"
                    >
                      {{ packValidation.scorecard.ok ? '100分门禁' : '需整改' }}
                    </ElTag>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="业务包数量">{{
                    packValidation.results.length
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem v-if="packValidation.scorecard" label="门禁分段">
                    <ElSpace wrap>
                      <ElTag
                        v-for="section in packValidation.scorecard.sections"
                        :key="section.name"
                        :type="section.status === 'pass' ? 'success' : 'danger'"
                        effect="plain"
                      >
                        {{ section.name }} {{ section.score }}/{{ section.maxScore }}
                      </ElTag>
                    </ElSpace>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem
                    v-if="packValidation.scorecard?.packs?.length"
                    label="可交付包"
                  >
                    <ElSpace wrap>
                      <ElTag
                        v-for="pack in packValidation.scorecard.packs"
                        :key="pack.packId"
                        :type="pack.ok ? 'success' : 'danger'"
                        effect="plain"
                      >
                        {{ pack.packId }} {{ pack.score }}
                      </ElTag>
                    </ElSpace>
                  </ElDescriptionsItem>
                  <ElDescriptionsItem
                    v-if="packValidation.scorecard?.blockers?.length"
                    label="阻断项"
                  >
                    {{ packValidation.scorecard.blockers.join('；') }}
                  </ElDescriptionsItem>
                </ElDescriptions>
                <ElTable
                  v-if="packValidation?.results?.length"
                  :data="packValidation.results"
                  border
                  height="220"
                  class="mt-12px"
                  @row-click="selectBusinessPack"
                >
                  <ElTableColumn label="业务包" min-width="190" show-overflow-tooltip>
                    <template #default="{ row }">{{ row.summary?.id || '-' }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="版本" width="100">
                    <template #default="{ row }">{{ row.summary?.version || '-' }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="校验" width="100">
                    <template #default="{ row }">
                      <ElTag :type="row.validation?.ok ? 'success' : 'danger'" effect="plain">
                        {{ row.validation?.ok ? '通过' : '失败' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElTable
                  v-if="businessPackDiffRows.length"
                  :data="businessPackDiffRows"
                  border
                  height="180"
                  class="mt-12px"
                >
                  <ElTableColumn
                    prop="field"
                    label="差异项"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="before"
                    label="已安装/基线"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="after"
                    label="当前包"
                    min-width="160"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol v-if="isFdeRoute('ocr-quality')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>OCR 质量与人工标定</span>
                    <ElSpace>
                      <ElButton
                        size="small"
                        type="primary"
                        plain
                        :loading="actionLoading"
                        @click="openFirstOcrAnnotationTask"
                      >
                        打开待标注样本
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :disabled="!firstLowConfidenceField"
                        :loading="actionLoading"
                        @click="correctFirstOcrField"
                      >
                        字段纠错
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="startOcrEvaluation"
                      >
                        OCR评测
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <div class="subpage-switch mb-16px">
                  <button
                    v-for="item in ocrSubpageItems"
                    :key="item.key"
                    type="button"
                    :class="{ active: ocrSubpage === item.key }"
                    @click="ocrSubpage = item.key"
                  >
                    <span>{{ item.label }}</span>
                    <small>{{ item.description }}</small>
                  </button>
                </div>
                <template v-if="ocrSubpage === 'overview'">
                  <div class="workbench-section-title">阻断项优先</div>
                  <div class="workbench-summary-grid">
                    <div
                      v-for="card in ocrPriorityCards"
                      :key="card.label"
                      :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
                    >
                      <span>{{ card.label }}</span>
                      <strong>{{ card.value }}</strong>
                      <small>{{ card.hint }}</small>
                    </div>
                  </div>
                  <ElAlert
                    class="mb-12px"
                    :type="ocr100Scorecard?.ok && ocrRuntimeDoctor?.ok ? 'success' : 'warning'"
                    show-icon
                    :closable="false"
                    :title="`当前首要阻断：${firstOcrBlockingSummary}`"
                  />
                  <ElTable
                    v-if="ocrTopBlockerRows.length"
                    :data="ocrTopBlockerRows"
                    border
                    height="220"
                    class="mb-12px"
                  >
                    <ElTableColumn prop="id" label="#" width="72" />
                    <ElTableColumn prop="source" label="来源" width="120" />
                    <ElTableColumn
                      prop="blocker"
                      label="阻断说明"
                      min-width="260"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="action"
                      label="处理动作"
                      min-width="260"
                      show-overflow-tooltip
                    />
                  </ElTable>
                  <ElDescriptions v-if="ocrQuality" :column="1" border>
                    <ElDescriptionsItem label="文件成功"
                      >{{ ocrQuality.fileLevel.success }}/{{
                        ocrQuality.fileLevel.total
                      }}</ElDescriptionsItem
                    >
                    <ElDescriptionsItem label="Job 成功"
                      >{{ ocrQuality.jobLevel?.success || 0 }}/{{
                        ocrQuality.jobLevel?.total || 0
                      }}</ElDescriptionsItem
                    >
                    <ElDescriptionsItem label="低置信度字段">{{
                      ocrQuality.fieldLevel.lowConfidence
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="解析字段">
                      {{ ocrQuality.fieldLevel.parseFieldCount || 0 }} · 平均置信
                      {{ percent(ocrQuality.fieldLevel.averageFieldConfidence) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="字段冲突">
                      {{ ocrQuality.fieldLevel.conflictFieldCount || 0 }} · 缺证据
                      {{ ocrQuality.fieldLevel.evidenceMissingFieldCount || 0 }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="必需字段缺失">
                      {{ ocrQuality.fieldLevel.missingRequiredFieldCount || 0 }}
                      <span v-if="topMissingRequiredField">
                        · {{ topMissingRequiredField.fieldCode }} ×
                        {{ topMissingRequiredField.count }}
                      </span>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="topOcrFieldCode" label="首要字段">
                      {{ topOcrFieldCode.fieldCode }} · {{ topOcrFieldCode.count }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="topOcrFieldFlag" label="字段质量标记">
                      {{ topOcrFieldFlag.flag }} · {{ topOcrFieldFlag.count }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="字段失败">{{
                      ocrQuality.failurePools?.fieldFailures?.length || 0
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="证据完整度">
                      {{ percent(ocrQuality.evidenceLevel?.averageEvidenceCompleteness) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="缺证据项">
                      {{ ocrQuality.evidenceLevel?.missingEvidence || 0 }} · 字段
                      {{ ocrQuality.evidenceLevel?.fieldEvidenceMissing || 0 }} / 表格
                      {{ ocrQuality.evidenceLevel?.tableEvidenceMissing || 0 }} / 印章
                      {{ ocrQuality.evidenceLevel?.sealEvidenceMissing || 0 }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="正式表格">
                      {{ ocrQuality.tableLevel?.formalTableCount || 0 }}/{{
                        ocrQuality.tableLevel?.tableCount || 0
                      }}
                      · {{ percent(ocrQuality.tableLevel?.formalTableRate) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="启发表格">
                      {{ ocrQuality.tableLevel?.heuristicTableCount || 0 }} ·
                      {{ percent(ocrQuality.tableLevel?.heuristicTableRate) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="业务行">
                      {{ ocrQuality.tableLevel?.businessRowCount || 0 }} 行 ·
                      {{ ocrQuality.tableLevel?.cellCount || 0 }} cells
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="必需表格缺失">
                      {{ ocrQuality.tableLevel?.missingRequiredTableCount || 0 }}
                      <span v-if="topMissingRequiredTable">
                        · {{ topMissingRequiredTable.tableCode }} ×
                        {{ topMissingRequiredTable.count }}
                      </span>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="印章可读">
                      {{ ocrQuality.sealLevel?.readableSealCount || 0 }}/{{
                        ocrQuality.sealLevel?.sealCount || 0
                      }}
                      · {{ percent(ocrQuality.sealLevel?.readableSealRate) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="片段融合章">
                      {{ ocrQuality.sealLevel?.fragmentSealCount || 0 }} ·
                      {{ percent(ocrQuality.sealLevel?.fragmentSealRate) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="期望章类型">
                      <span v-if="topMatchedExpectedSealType">
                        命中 {{ topMatchedExpectedSealType.sealType }} ×
                        {{ topMatchedExpectedSealType.count }}
                      </span>
                      <span v-else>命中 0</span>
                      <span v-if="topMissingExpectedSealType">
                        · 缺 {{ topMissingExpectedSealType.sealType }} ×
                        {{ topMissingExpectedSealType.count }}
                      </span>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="视觉章复核">
                      {{ ocrQuality.sealLevel?.reviewRequiredCount || 0 }}/{{
                        ocrQuality.sealLevel?.visualCandidateCount || 0
                      }}
                      · {{ percent(ocrQuality.sealLevel?.visualCandidateReviewRate) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="topOcrQualityReason" label="首要质量原因">
                      {{ topOcrQualityReason.reason }} · {{ topOcrQualityReason.count }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="人工修正率">{{
                      percent(ocrQuality.fieldLevel.manualCorrectionRate)
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="引擎缓存"
                      >{{ ocrQuality.cacheMetrics?.engineCacheHits || 0 }}/{{
                        ocrQuality.cacheMetrics?.engineRunCount || 0
                      }}
                      ·
                      {{ percent(ocrQuality.cacheMetrics?.engineCacheHitRate) }}</ElDescriptionsItem
                    >
                    <ElDescriptionsItem label="候选缓存"
                      >{{ ocrQuality.cacheMetrics?.variantCacheHits || 0 }}/{{
                        ocrQuality.cacheMetrics?.engineRunCount || 0
                      }}
                      ·
                      {{
                        percent(ocrQuality.cacheMetrics?.variantCacheHitRate)
                      }}</ElDescriptionsItem
                    >
                    <ElDescriptionsItem label="引擎耗时"
                      >{{ ocrQuality.cacheMetrics?.totalDurationMs || 0 }} ms</ElDescriptionsItem
                    >
                    <ElDescriptionsItem label="运行时">
                      <ElTag :type="ocrRuntimeDoctor?.ok ? 'success' : 'warning'" effect="plain">
                        {{ friendlyStatus(ocrRuntimeDoctor?.status, '未知') }}
                      </ElTag>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="Doctor"
                      >{{ ocrRuntimeDoctor?.summary?.fail || 0 }} fail /
                      {{ ocrRuntimeDoctor?.summary?.warn || 0 }} warn</ElDescriptionsItem
                    >
                    <ElDescriptionsItem v-if="firstRuntimeIssue" label="首要问题">
                      {{ firstRuntimeIssue.name }}：{{ firstRuntimeIssue.message }}
                    </ElDescriptionsItem>
                  </ElDescriptions>
                  <template v-if="ocr100Scorecard">
                    <div class="gate-summary mt-12px">
                      <div class="gate-summary-item">
                        <span>OCR 100</span>
                        <strong
                          >{{ ocr100Scorecard.score }}/{{ ocr100Scorecard.targetScore }}</strong
                        >
                      </div>
                      <div class="gate-summary-item">
                        <span>认证状态</span>
                        <strong>
                          <ElTag :type="ocr100Scorecard.ok ? 'success' : 'danger'" effect="plain">
                            {{ ocr100Scorecard.ok ? '100分就绪' : '存在阻断' }}
                          </ElTag>
                        </strong>
                      </div>
                      <div class="gate-summary-item">
                        <span>评分域</span>
                        <strong>{{ ocr100SectionRows.length }}</strong>
                      </div>
                      <div class="gate-summary-item">
                        <span>阻断项</span>
                        <strong>{{ ocr100Scorecard.blockers.length }}</strong>
                      </div>
                    </div>
                    <ElRow :gutter="12" class="mt-12px">
                      <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                        <ElTable :data="ocr100SectionRows" border height="180">
                          <ElTableColumn
                            prop="name"
                            label="评分域"
                            min-width="140"
                            show-overflow-tooltip
                          />
                          <ElTableColumn label="分数" width="105">
                            <template #default="{ row }"
                              >{{ row.score }}/{{ row.maxScore }}</template
                            >
                          </ElTableColumn>
                          <ElTableColumn prop="status" label="状态" width="95">
                            <template #default="{ row }">
                              <ElTag
                                :type="row.status === 'pass' ? 'success' : 'danger'"
                                effect="plain"
                              >
                                {{ friendlyStatus(row.status) }}
                              </ElTag>
                            </template>
                          </ElTableColumn>
                        </ElTable>
                      </ElCol>
                      <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                        <ElTable
                          v-if="ocr100BlockerRows.length"
                          :data="ocr100BlockerRows"
                          border
                          height="180"
                        >
                          <ElTableColumn prop="id" label="#" width="112" />
                          <ElTableColumn
                            prop="blocker"
                            label="OCR 100 阻断项"
                            min-width="260"
                            show-overflow-tooltip
                          />
                        </ElTable>
                        <ElAlert
                          v-else
                          type="success"
                          show-icon
                          :closable="false"
                          title="OCR 100 门禁未发现阻断项。"
                        />
                      </ElCol>
                    </ElRow>
                  </template>
                </template>
                <div v-if="ocrSubpage === 'annotation'" class="sub-section mt-12px">
                  <div class="panel-header">
                    <span>人工标注门禁</span>
                    <ElSpace>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="exportOcrAnnotationToLabelStudio"
                      >
                        导出LS
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :disabled="!firstOcrAnnotationTaskId"
                        :loading="actionLoading"
                        @click="markFirstOcrAnnotationReviewed"
                      >
                        二审演练
                      </ElButton>
                    </ElSpace>
                  </div>
                  <div class="gate-summary mt-12px">
                    <div class="gate-summary-item">
                      <span>样本</span>
                      <strong>{{ ocrAnnotationSummary?.tasks || 0 }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>已人工标注</span>
                      <strong>{{ ocrAnnotationSummary?.humanLabeled || 0 }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>可评估</span>
                      <strong>{{ ocrAnnotationSummary?.readyForEval || 0 }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>完成率</span>
                      <strong>{{ percent(ocrAnnotationSummary?.completionRate) }}</strong>
                    </div>
                  </div>
                  <ElAlert
                    v-if="labelStudioExportSummary"
                    class="mt-12px"
                    type="info"
                    show-icon
                    :closable="false"
                    :title="`Label Studio 导出任务 ${labelStudioExportSummary.tasks || 0} 个，跳过 ${labelStudioExportSummary.skipped || 0} 个。`"
                  />
                  <ElRow :gutter="12" class="mt-12px">
                    <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                      <ElTable :data="ocrAnnotationRows" border height="180">
                        <ElTableColumn
                          prop="caseId"
                          label="样本"
                          min-width="210"
                          show-overflow-tooltip
                        />
                        <ElTableColumn
                          prop="scenario"
                          label="场景"
                          min-width="150"
                          show-overflow-tooltip
                        />
                        <ElTableColumn label="标签" width="115">
                          <template #default="{ row }">
                            {{
                              (row.labelCounts?.fields || 0) +
                              (row.labelCounts?.tables || 0) +
                              (row.labelCounts?.seals || 0)
                            }}
                          </template>
                        </ElTableColumn>
                        <ElTableColumn prop="collectionStatus" label="状态" width="130">
                          <template #default="{ row }">
                            <ElTag :type="ocrAnnotationStatusType(row)" effect="plain">
                              {{ ocrAnnotationStatusLabel(row) }}
                            </ElTag>
                          </template>
                        </ElTableColumn>
                        <ElTableColumn label="操作" width="145" fixed="right">
                          <template #default="{ row }">
                            <ElSpace size="small">
                              <ElButton
                                size="small"
                                link
                                type="primary"
                                @click="openAnnotationEditor(row)"
                              >
                                编辑
                              </ElButton>
                              <ElButton
                                size="small"
                                link
                                type="success"
                                @click="openAnnotationEditor(row)"
                              >
                                二审
                              </ElButton>
                            </ElSpace>
                          </template>
                        </ElTableColumn>
                      </ElTable>
                    </ElCol>
                    <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                      <ElTable
                        v-if="ocrAnnotationBlockerRows.length"
                        :data="ocrAnnotationBlockerRows"
                        border
                        height="180"
                      >
                        <ElTableColumn
                          prop="blocker"
                          label="标注阻断项"
                          min-width="220"
                          show-overflow-tooltip
                        />
                        <ElTableColumn prop="count" label="数量" width="90" />
                      </ElTable>
                      <ElAlert
                        v-else
                        type="success"
                        show-icon
                        :closable="false"
                        title="标注样本已满足评估导出门禁。"
                      />
                    </ElCol>
                  </ElRow>
                </div>
                <template v-if="ocrSubpage === 'runtime'">
                  <ElTable
                    :data="ocrRuns"
                    border
                    height="220"
                    class="mt-12px"
                    @row-click="(row) => openOcrAuditDrawer(String(row.id || row.jobId))"
                  >
                    <ElTableColumn prop="id" label="Job" min-width="150" show-overflow-tooltip />
                    <ElTableColumn prop="status" label="状态" width="95">
                      <template #default="{ row }">
                        <ElTag :type="statusType(String(row.status))" effect="plain">
                          {{ friendlyStatus(row.status) }}
                        </ElTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="profileId"
                      label="Profile"
                      min-width="140"
                      show-overflow-tooltip
                    />
                    <ElTableColumn label="操作" width="96" fixed="right">
                      <template #default="{ row }">
                        <ElButton
                          size="small"
                          text
                          @click.stop="openOcrAuditDrawer(String(row.id || row.jobId))"
                        >
                          详情
                        </ElButton>
                      </template>
                    </ElTableColumn>
                  </ElTable>
                  <ElDescriptions v-if="selectedOcrRun" :column="1" border class="mt-12px">
                    <ElDescriptionsItem label="结果">{{
                      selectedOcrRun.job.parseResultId || '-'
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="字段">{{
                      selectedOcrResultSummary.fieldCount || 0
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="纠错">{{
                      selectedOcrRun.corrections.length
                    }}</ElDescriptionsItem>
                    <ElDescriptionsItem label="候选图"
                      >{{ selectedOcrGeneratedVariants.length }}/{{
                        selectedOcrRequestedVariants.length
                      }}</ElDescriptionsItem
                    >
                    <ElDescriptionsItem v-if="selectedOcrMissingVariants.length" label="缺失候选">
                      {{ selectedOcrMissingVariants.join(', ') }}
                    </ElDescriptionsItem>
                  </ElDescriptions>
                  <ElTable
                    v-if="selectedOcrEngineRows.length"
                    :data="selectedOcrEngineRows"
                    border
                    height="180"
                    class="mt-12px"
                  >
                    <ElTableColumn
                      prop="engine"
                      label="引擎"
                      min-width="180"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="status" label="状态" width="90">
                      <template #default="{ row }">
                        <ElTag :type="statusType(String(row.status))" effect="plain">
                          {{ friendlyStatus(row.status) }}
                        </ElTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn prop="durationMs" label="耗时" width="95" />
                    <ElTableColumn label="缓存" width="120">
                      <template #default="{ row }">
                        <ElSpace size="small">
                          <ElTag
                            v-if="row.engineCacheHit"
                            size="small"
                            type="success"
                            effect="plain"
                          >
                            引擎
                          </ElTag>
                          <ElTag v-if="row.variantCacheHit" size="small" type="info" effect="plain">
                            候选
                          </ElTag>
                          <span v-if="!row.engineCacheHit && !row.variantCacheHit">-</span>
                        </ElSpace>
                      </template>
                    </ElTableColumn>
                  </ElTable>
                  <ElTable
                    v-if="ocrFieldFailureRows.length"
                    :data="ocrFieldFailureRows"
                    border
                    height="180"
                    class="mt-12px"
                  >
                    <ElTableColumn
                      prop="code"
                      label="字段问题"
                      min-width="150"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="fieldName"
                      label="字段"
                      min-width="110"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="fieldValue"
                      label="值"
                      min-width="130"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="confidence" label="置信度" width="95" />
                  </ElTable>
                  <ElTable
                    v-if="ocrMissingEvidenceRows.length"
                    :data="ocrMissingEvidenceRows"
                    border
                    height="180"
                    class="mt-12px"
                  >
                    <ElTableColumn prop="targetType" label="缺证据类型" width="110" />
                    <ElTableColumn
                      prop="targetId"
                      label="目标"
                      min-width="120"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="parseResultId"
                      label="结果"
                      min-width="150"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="profileId"
                      label="Profile"
                      min-width="140"
                      show-overflow-tooltip
                    />
                  </ElTable>
                </template>
              </ElCard>
            </ElCol>
            <ElCol
              v-if="isFdeRoute('incidents', 'acceptance')"
              :xl="24"
              :lg="24"
              :md="24"
              :sm="24"
              :xs="24"
            >
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>{{ isFdeRoute('acceptance') ? '客户验收' : '事故复盘' }}</span>
                    <ElSpace>
                      <ElButton
                        v-if="isFdeRoute('incidents')"
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="updateFirstRca"
                      >
                        更新 RCA
                      </ElButton>
                      <ElButton
                        v-if="isFdeRoute('incidents')"
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="closeSelectedIncident"
                      >
                        关闭事故
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="事故数">{{ incidents.length }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="RCA">{{ rcaItems.length }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="验收报告">{{
                    acceptanceReports.length
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="发布计划">{{
                    releases?.plans.length || 0
                  }}</ElDescriptionsItem>
                </ElDescriptions>
                <ElTable
                  v-if="isFdeRoute('incidents')"
                  :data="incidents"
                  border
                  height="180"
                  class="mt-12px"
                  @row-click="selectIncident"
                >
                  <ElTableColumn prop="id" label="事故" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn prop="status" label="状态" width="110" />
                </ElTable>
                <ElTable v-else :data="acceptanceReports" border height="220" class="mt-12px">
                  <ElTableColumn prop="id" label="验收报告" min-width="190" show-overflow-tooltip />
                  <ElTableColumn
                    prop="businessPackId"
                    label="业务包"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="120">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="confirmedBy" label="确认人" width="130" />
                  <ElTableColumn
                    prop="confirmedAt"
                    label="确认时间"
                    min-width="160"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow
            v-if="isFdeRoute('ocr-quality') && ocrSubpage === 'evaluation'"
            :gutter="16"
            class="mt-16px"
          >
            <ElCol :span="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>OCR 评估门禁</span>
                    <ElSpace>
                      <ElTag
                        v-if="latestOcrEvalRun"
                        :type="latestOcrEvalOk ? 'success' : 'danger'"
                        effect="plain"
                      >
                        {{ latestOcrEvalOk ? '门禁通过' : '门禁失败' }}
                      </ElTag>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="startOcrEvaluation"
                      >
                        重新评测
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElAlert
                  v-if="!latestOcrEvalRun"
                  type="info"
                  show-icon
                  :closable="false"
                  title="暂无 OCR 评估记录，请先发起 OCR评测。"
                />
                <template v-else>
                  <div class="gate-summary">
                    <div class="gate-summary-item">
                      <span>Profile</span>
                      <strong>{{ latestOcrEvalRun.profileId || 'all' }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>平均分</span>
                      <strong>{{ scorePercent(latestOcrEvalSummary.averageScore) }}</strong>
                    </div>
                    <div class="gate-summary-item">
                      <span>样本</span>
                      <strong
                        >{{ latestOcrEvalSummary.passed || 0 }}/{{ latestOcrEvalCaseTotal }}</strong
                      >
                    </div>
                    <div class="gate-summary-item">
                      <span>门禁失败</span>
                      <strong>{{ ocrThresholdFailureRows.length }}</strong>
                    </div>
                  </div>
                  <ElRow :gutter="12" class="mt-12px">
                    <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                      <ElTable :data="ocrScenarioRows" border height="220">
                        <ElTableColumn
                          prop="scenario"
                          label="场景"
                          min-width="190"
                          show-overflow-tooltip
                        />
                        <ElTableColumn prop="averageScore" label="分数" width="95">
                          <template #default="{ row }">{{
                            scorePercent(row.averageScore)
                          }}</template>
                        </ElTableColumn>
                        <ElTableColumn prop="passed" label="通过" width="90" />
                        <ElTableColumn prop="failed" label="失败" width="90" />
                        <ElTableColumn prop="ok" label="门禁" width="95">
                          <template #default="{ row }">
                            <ElTag :type="row.ok ? 'success' : 'danger'" effect="plain">
                              {{ row.ok ? '通过' : '失败' }}
                            </ElTag>
                          </template>
                        </ElTableColumn>
                      </ElTable>
                    </ElCol>
                    <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
                      <ElTable
                        v-if="ocrThresholdFailureRows.length"
                        :data="ocrThresholdFailureRows"
                        border
                        height="220"
                      >
                        <ElTableColumn
                          prop="scope"
                          label="范围"
                          min-width="150"
                          show-overflow-tooltip
                        />
                        <ElTableColumn
                          prop="metric"
                          label="指标"
                          min-width="170"
                          show-overflow-tooltip
                        />
                        <ElTableColumn prop="actual" label="实际" width="95">
                          <template #default="{ row }">{{ scorePercent(row.actual) }}</template>
                        </ElTableColumn>
                        <ElTableColumn prop="expected" label="门槛" width="95">
                          <template #default="{ row }">{{ scorePercent(row.expected) }}</template>
                        </ElTableColumn>
                      </ElTable>
                      <ElTable
                        v-else-if="ocrFindingCountRows.length"
                        :data="ocrFindingCountRows"
                        border
                        height="220"
                      >
                        <ElTableColumn
                          prop="scope"
                          label="范围"
                          min-width="150"
                          show-overflow-tooltip
                        />
                        <ElTableColumn
                          prop="code"
                          label="失败原因"
                          min-width="230"
                          show-overflow-tooltip
                        />
                        <ElTableColumn prop="count" label="次数" width="90" />
                      </ElTable>
                      <ElTable v-else :data="failedOcrCaseRows" border height="220">
                        <ElTableColumn
                          prop="caseId"
                          label="Case"
                          min-width="190"
                          show-overflow-tooltip
                        />
                        <ElTableColumn
                          prop="scenario"
                          label="场景"
                          min-width="160"
                          show-overflow-tooltip
                        />
                        <ElTableColumn prop="score" label="分数" width="95">
                          <template #default="{ row }">{{ scorePercent(row.score) }}</template>
                        </ElTableColumn>
                        <ElTableColumn
                          prop="finding"
                          label="诊断"
                          min-width="160"
                          show-overflow-tooltip
                        />
                      </ElTable>
                    </ElCol>
                  </ElRow>
                </template>
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow v-if="isFdeRoute('security', 'costs')" :gutter="16" class="mt-16px">
            <ElCol v-if="isFdeRoute('security')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>数据安全</span>
                    <ElSpace>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="createMaskingPolicyDraft"
                      >
                        脱敏策略
                      </ElButton>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="expireFirstDataExport"
                      >
                        过期导出
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="访问授权">{{
                    accessGrants.length
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="导出申请">{{
                    costGovernance?.exports.length || 0
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="脱敏策略">{{
                    maskingPolicies.length
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="审计事件">{{ auditEvents.length }}</ElDescriptionsItem>
                </ElDescriptions>
                <ElTable :data="maskingPolicies" border height="160" class="mt-12px">
                  <ElTableColumn
                    prop="fieldPath"
                    label="字段"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="strategy" label="策略" width="90" />
                  <ElTableColumn prop="status" label="状态" width="100" />
                </ElTable>
                <ElTable :data="auditEvents" border height="180" class="mt-12px">
                  <ElTableColumn
                    prop="createdAt"
                    label="时间"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="action" label="动作" min-width="210" show-overflow-tooltip />
                  <ElTableColumn prop="objectType" label="对象" width="120" />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol v-if="isFdeRoute('costs')" :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>成本预算</span>
                    <ElButton
                      size="small"
                      plain
                      :loading="actionLoading"
                      @click="proposeFirstBudgetChange"
                    >
                      预算变更
                    </ElButton>
                  </div>
                </template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="预算数">{{
                    costGovernance?.budgets.length || 0
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="Run 数">{{
                    costGovernance?.usage.runCount || 0
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="估算费用">{{
                    costGovernance?.usage.estimatedPrice || 0
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="变更申请">{{
                    costChangeRequests.length
                  }}</ElDescriptionsItem>
                </ElDescriptions>
                <ElTable :data="costChangeRequests" border height="180" class="mt-12px">
                  <ElTableColumn prop="id" label="申请" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="130" />
                  <ElTableColumn prop="proposedLimit" label="建议额度" width="110" />
                  <ElTableColumn prop="reason" label="原因" min-width="210" show-overflow-tooltip />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>
      </ElTabs>

      <ElDrawer
        v-model="reviewAuditDrawerVisible"
        size="760px"
        class="fde-audit-drawer"
        destroy-on-close
        title="Agent 审查编排详情"
      >
        <template v-if="selectedReviewRun">
          <div class="audit-drawer-hero" data-testid="fde-review-drawer">
            <div>
              <span>ReviewRun</span>
              <strong>{{ selectedReviewRun.run.reviewRunId || selectedReviewRun.run.id }}</strong>
              <small>
                {{ selectedReviewRun.run.agentId || 'compliance_review_agent' }} ·
                {{ selectedReviewRun.run.modelAlias || '-' }}
              </small>
            </div>
            <ElTag :type="statusType(String(selectedReviewRun.run.status))" effect="plain">
              {{ friendlyStatus(selectedReviewRun.run.status) }}
            </ElTag>
          </div>

          <ElAlert
            class="mb-12px"
            type="info"
            show-icon
            :closable="false"
            title="这里展示可审计推理摘要、工具调用、证据引用、质量门禁和人工修正记录，不展示模型内部隐式思维。"
          />

          <div class="audit-drawer-actions">
            <ElButton plain :loading="actionLoading" @click="replayFirstReviewRun">
              诊断重跑
            </ElButton>
            <ElButton plain :loading="actionLoading" @click="shadowFirstReviewRun">
              Shadow 运行
            </ElButton>
          </div>

          <ElDescriptions :column="1" border class="mb-12px">
            <ElDescriptionsItem label="Workflow">
              {{ selectedReviewTemporal.workflowId || selectedReviewRun.run.workflowId || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="Graph Runner">
              {{ selectedReviewRun.run.graphRunner || selectedReviewRun.run.graphEngine || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="Checkpoint">
              {{
                selectedReviewRun.run.graphExecution?.checkpointer ||
                selectedReviewRun.run.graphExecution?.fallbackReason ||
                '-'
              }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="输入 Hash">
              {{ selectedReviewRun.run.inputHash || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="输出 Hash">
              {{ selectedReviewRun.run.outputHash || '-' }}
            </ElDescriptionsItem>
          </ElDescriptions>

          <div class="artifact-summary-grid mb-12px">
            <div v-for="item in reviewArtifactRows" :key="item.label" class="artifact-summary-item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>

          <ElTabs class="audit-drawer-tabs">
            <ElTabPane label="思考链" name="reasoning">
              <ElAlert
                class="mb-12px"
                type="info"
                show-icon
                :closable="false"
                title="这里展示可审计推理摘要、工具调用、证据引用和质量判断，不展示模型内部原始隐式思维。"
              />
              <div v-if="normalizedReviewReasoningRows.length" class="audit-step-list drawer-step-list">
                <article
                  v-for="row in normalizedReviewReasoningRows"
                  :key="`drawer-${row.sequence}-${row.stepName}`"
                  class="audit-step-card drawer-step-card"
                >
                  <div class="audit-step-index">
                    <span>{{ String(row.sequence).padStart(2, '0') }}</span>
                  </div>
                  <div class="audit-step-body">
                    <div class="audit-step-title">
                      <strong>{{ friendlyTechLabel(row.stepName) }}</strong>
                      <ElTag :type="row.qualityPassed ? 'success' : 'warning'" effect="plain">
                        {{ row.qualityText }}
                      </ElTag>
                    </div>
                    <p>{{ row.reasoningSummary }}</p>
                    <div class="audit-step-evidence">
                      <span>证据/依据</span>
                      <strong>{{ shortText(row.evidence, '-') }}</strong>
                    </div>
                    <div class="audit-step-meta">
                      <span class="audit-step-meta-label">证据/规则/条款</span>
                      <span>工具 {{ row.toolCount }}</span>
                      <span>证据 {{ row.evidenceCount }}</span>
                      <span>规则 {{ row.ruleCount }}</span>
                      <span>条款 {{ row.kbCount }}</span>
                    </div>
                    <small v-if="row.toolNames">工具：{{ row.toolNames }}</small>
                  </div>
                </article>
              </div>
              <ElEmpty v-else description="暂无可审计推理摘要" />
            </ElTabPane>
            <ElTabPane label="结果" name="findings">
              <ElTable :data="normalizedReviewFindingRows" border height="300">
                <ElTableColumn
                  prop="findingType"
                  label="类型"
                  min-width="130"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.findingType) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="severity" label="等级" width="90" />
                <ElTableColumn prop="title" label="发现项" min-width="260" show-overflow-tooltip />
                <ElTableColumn label="置信度" width="95">
                  <template #default="{ row }">{{ scorePercent(row.confidence) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="evidenceCount" label="证据" width="72" />
                <ElTableColumn prop="referenceCount" label="依据" width="72" />
                <ElTableColumn label="建议动作" min-width="130" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyStatus(row.suggestedAction) }}</template>
                </ElTableColumn>
                <ElTableColumn label="人工确认" width="95">
                  <template #default="{ row }">
                    <ElTag
                      :type="row.requiresHumanConfirmation ? 'warning' : 'success'"
                      effect="plain"
                    >
                      {{ row.requiresHumanConfirmation ? '需要' : '可用' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="质量" name="quality">
              <ElDescriptions :column="2" border class="mb-12px">
                <ElDescriptionsItem label="状态">
                  {{ friendlyStatus(reviewQualityEvaluation.status) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="评分">
                  {{ reviewQualityEvaluation.score || 0 }}/100
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable :data="normalizedReviewQualityRows" border height="220">
                <ElTableColumn prop="name" label="门禁/维度" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="110">
                  <template #default="{ row }">
                    <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="评分" width="85">
                  <template #default="{ row }">
                    {{ row.score === undefined ? '-' : scorePercent(row.score) }}
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="message" label="说明" min-width="260" show-overflow-tooltip />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="溯源" name="lineage">
              <ElTable :data="reviewLineageRows" border height="300">
                <ElTableColumn prop="label" label="字段" width="130" />
                <ElTableColumn label="值" min-width="320" show-overflow-tooltip>
                  <template #default="{ row }">{{ shortText(row.value) }}</template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="人工修正" name="human">
              <ElTable :data="normalizedReviewHumanCorrectionRows" border height="300">
                <ElTableColumn prop="targetType" label="对象" min-width="120" show-overflow-tooltip />
                <ElTableColumn
                  prop="correctionType"
                  label="类型"
                  min-width="140"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="before"
                  label="修正前"
                  min-width="220"
                  show-overflow-tooltip
                />
                <ElTableColumn label="修正后" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">{{ shortText(row.after) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="rootCause" label="归因" min-width="150" show-overflow-tooltip />
                <ElTableColumn label="入评估集" width="100">
                  <template #default="{ row }">
                    <ElTag :type="row.shouldEnterEvaluationSet ? 'success' : 'info'" effect="plain">
                      {{ row.shouldEnterEvaluationSet ? '是' : '否' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
          </ElTabs>
        </template>
        <ElEmpty v-else description="请选择 Agent 审查任务" />
      </ElDrawer>

      <ElDrawer
        v-model="ocrAuditDrawerVisible"
        size="760px"
        class="fde-audit-drawer"
        destroy-on-close
        title="OCR 任务审计详情"
      >
        <template v-if="selectedOcrRun">
          <div class="audit-drawer-hero" data-testid="fde-ocr-drawer">
            <div>
              <span>OCR Job</span>
              <strong>{{ selectedOcrRun.job.jobId || selectedOcrRun.job.id }}</strong>
              <small
                >{{ selectedOcrRun.job.profileId || '-' }} ·
                {{ selectedOcrRun.job.documentType || '-' }}</small
              >
            </div>
            <ElTag :type="statusType(String(selectedOcrRun.job.status))" effect="plain">
              {{ friendlyStatus(selectedOcrRun.job.status) }}
            </ElTag>
          </div>

          <div class="audit-drawer-actions">
            <ElButton plain :disabled="!firstLowConfidenceField" @click="correctFirstOcrField">
              字段纠错
            </ElButton>
            <ElButton plain @click="openFirstOcrAnnotationTask">打开标注样本</ElButton>
            <ElButton plain :loading="actionLoading" @click="startOcrEvaluation">OCR评测</ElButton>
          </div>

          <ElDescriptions :column="1" border class="mb-12px">
            <ElDescriptionsItem label="解析结果">
              {{ selectedOcrRun.job.parseResultId || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="字段 / 表格 / 印章">
              {{ selectedOcrResultSummary.fieldCount || 0 }} /
              {{ selectedOcrResultSummary.tableCount || 0 }} /
              {{ selectedOcrResultSummary.sealCount || 0 }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="候选图">
              {{ selectedOcrGeneratedVariants.length }}/{{ selectedOcrRequestedVariants.length }}
              <span v-if="selectedOcrMissingVariants.length">
                · 缺失 {{ selectedOcrMissingVariants.join('、') }}
              </span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="人工修正">
              {{ selectedOcrCorrectionRows.length }}
            </ElDescriptionsItem>
          </ElDescriptions>

          <ElTabs class="audit-drawer-tabs">
            <ElTabPane label="引擎" name="engines">
              <ElTable :data="selectedOcrEngineRows" border height="300">
                <ElTableColumn prop="engine" label="引擎" min-width="180" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="110">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="durationMs" label="耗时" width="95" />
                <ElTableColumn label="缓存" width="120">
                  <template #default="{ row }">
                    {{ row.engineCacheHit || row.variantCacheHit ? '命中' : '-' }}
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="字段问题" name="fields">
              <ElTable :data="ocrFieldFailureRows" border height="300">
                <ElTableColumn prop="code" label="问题" min-width="150" show-overflow-tooltip />
                <ElTableColumn
                  prop="fieldName"
                  label="字段"
                  min-width="130"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="fieldValue" label="值" min-width="160" show-overflow-tooltip />
                <ElTableColumn prop="confidence" label="置信度" width="95" />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="证据缺口" name="evidence">
              <ElTable :data="ocrMissingEvidenceRows" border height="300">
                <ElTableColumn prop="targetType" label="类型" width="110" />
                <ElTableColumn prop="targetId" label="目标" min-width="160" show-overflow-tooltip />
                <ElTableColumn
                  prop="parseResultId"
                  label="结果"
                  min-width="170"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="profileId"
                  label="Profile"
                  min-width="160"
                  show-overflow-tooltip
                />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="诊断" name="diagnostics">
              <ElTable :data="selectedOcrDiagnosticRows" border height="300">
                <ElTableColumn prop="code" label="诊断码" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="level" label="等级" width="100" />
                <ElTableColumn prop="message" label="说明" min-width="280" show-overflow-tooltip />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="人工修正" name="corrections">
              <ElTable :data="selectedOcrCorrectionRows" border height="300">
                <ElTableColumn
                  prop="fieldCode"
                  label="字段"
                  min-width="130"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="oldValue" label="原值" min-width="170" show-overflow-tooltip />
                <ElTableColumn prop="newValue" label="新值" min-width="170" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="110" />
              </ElTable>
            </ElTabPane>
          </ElTabs>
        </template>
        <ElEmpty v-else description="请选择 OCR 任务" />
      </ElDrawer>

      <ElDialog
        v-model="annotationEditorVisible"
        width="1180px"
        destroy-on-close
        class="ocr-annotation-dialog"
        title="OCR 人工标注工作台"
      >
        <ElRow :gutter="16" v-loading="annotationDetailLoading">
          <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
            <div class="annotation-canvas">
              <img
                v-if="selectedAnnotationTask?.previewUrl"
                class="annotation-image"
                :src="selectedAnnotationTask.previewUrl"
                alt="OCR annotation preview"
              />
              <div v-else class="annotation-placeholder">
                <strong>{{ selectedAnnotationTask?.sourcePath || '暂无预览图' }}</strong>
                <span>可使用右侧坐标框完成字段、表格、印章标注。</span>
              </div>
              <svg
                class="annotation-overlay"
                :viewBox="`0 0 ${annotationPageSize.width} ${annotationPageSize.height}`"
                preserveAspectRatio="none"
              >
                <g
                  v-for="item in annotationOverlayItems"
                  :key="`${item.type}-${item.index}`"
                  :class="`annotation-box-${item.type}`"
                >
                  <rect
                    v-if="Array.isArray(item.bbox)"
                    :x="Number(item.bbox[0] || 0)"
                    :y="Number(item.bbox[1] || 0)"
                    :width="Math.max(0, Number(item.bbox[2] || 0) - Number(item.bbox[0] || 0))"
                    :height="Math.max(0, Number(item.bbox[3] || 0) - Number(item.bbox[1] || 0))"
                  />
                  <text
                    v-if="Array.isArray(item.bbox)"
                    :x="Number(item.bbox[0] || 0) + 6"
                    :y="Math.max(16, Number(item.bbox[1] || 0) + 18)"
                  >
                    {{ item.label }}
                  </text>
                </g>
              </svg>
            </div>
            <ElDescriptions :column="2" border class="mt-12px">
              <ElDescriptionsItem label="任务">
                {{ selectedAnnotationTask?.taskId || '-' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="场景">
                {{ selectedAnnotationTask?.scenario || '-' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="页面尺寸">
                {{ annotationPageSize.width }} × {{ annotationPageSize.height }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="阻断">
                {{ selectedAnnotationTask?.readinessBlockers?.join('；') || '无' }}
              </ElDescriptionsItem>
            </ElDescriptions>
          </ElCol>
          <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
            <ElForm label-width="76px">
              <ElFormItem label="类型">
                <ElSelect v-model="annotationBoxType">
                  <ElOption label="字段" value="fields" />
                  <ElOption label="表格" value="tables" />
                  <ElOption label="印章" value="seals" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="标签值">
                <ElInput
                  v-model="annotationLabelValue"
                  placeholder="字段 code / 表格 schema / 印章名称"
                />
              </ElFormItem>
              <ElRow :gutter="8">
                <ElCol :span="8">
                  <ElFormItem label="页码">
                    <ElInputNumber v-model="annotationBoxForm.pageNo" :min="1" :controls="false" />
                  </ElFormItem>
                </ElCol>
                <ElCol :span="8">
                  <ElFormItem label="x1">
                    <ElInputNumber v-model="annotationBoxForm.x1" :min="0" :controls="false" />
                  </ElFormItem>
                </ElCol>
                <ElCol :span="8">
                  <ElFormItem label="y1">
                    <ElInputNumber v-model="annotationBoxForm.y1" :min="0" :controls="false" />
                  </ElFormItem>
                </ElCol>
                <ElCol :span="8">
                  <ElFormItem label="x2">
                    <ElInputNumber v-model="annotationBoxForm.x2" :min="0" :controls="false" />
                  </ElFormItem>
                </ElCol>
                <ElCol :span="8">
                  <ElFormItem label="y2">
                    <ElInputNumber v-model="annotationBoxForm.y2" :min="0" :controls="false" />
                  </ElFormItem>
                </ElCol>
              </ElRow>
              <ElSpace>
                <ElButton type="primary" plain @click="addAnnotationBox">添加框</ElButton>
                <ElButton :loading="actionLoading" @click="saveAnnotationDraft">保存草稿</ElButton>
                <ElButton
                  type="success"
                  :loading="actionLoading"
                  @click="verifyAnnotationFromEditor"
                >
                  二审通过
                </ElButton>
              </ElSpace>
              <ElDivider />
              <ElRow :gutter="8">
                <ElCol :span="12">
                  <ElFormItem label="标注员">
                    <ElInput v-model="annotationLabeler" />
                  </ElFormItem>
                </ElCol>
                <ElCol :span="12">
                  <ElFormItem label="复核人">
                    <ElInput v-model="annotationReviewer" />
                  </ElFormItem>
                </ElCol>
              </ElRow>
            </ElForm>

            <ElDivider>当前标注</ElDivider>
            <div class="annotation-list">
              <div v-for="section in annotationSections" :key="section" class="annotation-section">
                <strong>{{ annotationSectionTitle(section) }}</strong>
                <div
                  v-for="(item, index) in annotationItems(section)"
                  :key="`${section}-${index}`"
                  class="annotation-item"
                >
                  <span>
                    {{
                      item.fieldCode ||
                      item.businessSchema ||
                      item.nameContains ||
                      item.sealType ||
                      '-'
                    }}
                  </span>
                  <small>{{ Array.isArray(item.bbox) ? item.bbox.join(',') : '无 bbox' }}</small>
                  <ElButton
                    size="small"
                    link
                    type="danger"
                    @click="removeAnnotationItem(section, index)"
                  >
                    删除
                  </ElButton>
                </div>
              </div>
            </div>
          </ElCol>
        </ElRow>
      </ElDialog>
    </div>
  </StaticPageShell>
</template>

<style scoped lang="less">
.fde-console {
  min-height: 100%;
  color: #1f2937;
}

.page-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  justify-content: space-between;
  margin-bottom: 18px;
}

.page-title {
  font-size: 27px;
  font-weight: 900;
  line-height: 1.2;
  color: #172033;
}

.page-subtitle {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.5;
  color: #667085;
}

.page-title-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.route-context {
  display: inline-flex;
  max-width: 100%;
  padding: 7px 10px;
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.35;
  color: #667085;
  background: #f8fafc;
  border-radius: 8px;
  align-items: center;
  gap: 8px;
}

.route-context strong {
  font-size: 14px;
  color: #172033;
}

.next-action {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  max-width: 760px;
  padding: 10px 12px;
  margin-top: 10px;
  line-height: 1.45;
  color: #334155;
  background: #eef5ff;
  border: 1px solid #d9e8ff;
  border-radius: 8px;
}

.next-action span {
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
}

.next-action strong {
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
}

.workbench-section-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.4;
  color: #172033;
}

.project-audit-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.project-audit-workbench > * {
  min-width: 0;
  max-width: 100%;
}

.project-audit-card {
  min-width: 0;
  max-width: 100%;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.project-audit-card--hero {
  background: linear-gradient(135deg, rgb(239 246 255 / 94%), rgb(255 255 255 / 98%)), #fff;
}

.project-audit-card--compact :deep(.el-card__body) {
  padding: 10px 12px;
}

.project-audit-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: start;
}

.project-audit-card--compact .project-audit-header {
  gap: 12px;
  align-items: center;
}

.project-audit-title {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.project-audit-card--compact .project-audit-title {
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
}

.project-audit-title span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.project-audit-card--compact .project-audit-title span {
  display: none;
}

.project-audit-title strong {
  min-width: 0;
  overflow: hidden;
  font-size: 22px;
  font-weight: 900;
  line-height: 30px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-audit-card--compact .project-audit-title strong {
  font-size: 16px;
  line-height: 24px;
}

.project-audit-title small {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-audit-card--compact .project-audit-title small {
  display: none;
}

.project-audit-selectors {
  justify-content: flex-end;
}

.project-audit-select {
  width: min(360px, 38vw);
}

.project-audit-card--compact .project-audit-select {
  width: min(300px, 30vw);
}

.project-audit-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 14px;
  margin-top: 14px;
  border-top: 1px solid #dbe8f7;
}

.project-audit-module-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(360px, 1.25fr);
  gap: 14px;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  min-height: 52px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.project-audit-module-title {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.project-audit-module-title span {
  font-size: 12px;
  font-weight: 900;
  color: #2563eb;
}

.project-audit-module-title strong {
  font-size: 15px;
  font-weight: 900;
  color: #172033;
}

.project-audit-module-title small {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-audit-focus-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.project-audit-focus-fact {
  display: grid;
  min-width: 0;
  min-height: 48px;
  padding: 8px 9px;
  background: #f8fbff;
  border: 1px solid #e3edf9;
  border-radius: 8px;
}

.project-audit-focus-fact em {
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  line-height: 16px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-audit-focus-fact strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-audit-focus-fact.blue {
  background: #f3f8ff;
  border-color: #cfe0fb;
}

.project-audit-focus-fact.green {
  background: #f0fbf6;
  border-color: #c9eedb;
}

.project-audit-focus-fact.orange {
  background: #fff8ed;
  border-color: #ffdda9;
}

.project-audit-focus-fact.red {
  background: #fff3f2;
  border-color: #ffc8c1;
}

.workbench-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
  min-width: 0;
  max-width: 100%;
  margin-bottom: 16px;
}

.workbench-summary-card {
  min-width: 0;
  min-height: 108px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
}

.workbench-summary-card span,
.workbench-summary-card small,
.workbench-summary-card strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workbench-summary-card span {
  font-size: 12px;
  font-weight: 800;
  line-height: 18px;
  color: #64748b;
}

.workbench-summary-card strong {
  margin-top: 8px;
  font-size: 26px;
  line-height: 32px;
  color: #172033;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.workbench-summary-card small {
  margin-top: 6px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
}

.workbench-summary-card--green {
  border-color: #cfe8d7;
}

.workbench-summary-card--orange {
  border-color: #f0dfb8;
}

.workbench-summary-card--red {
  border-color: #efc8c8;
}

.workbench-summary-card--blue {
  border-color: #cbdcf8;
}

.project-subpage-kpis {
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.project-subpage-kpis .workbench-summary-card {
  min-height: 76px;
  padding: 10px 12px;
  box-shadow: 0 6px 14px rgb(15 23 42 / 3%);
}

.project-subpage-kpis .workbench-summary-card span {
  font-size: 11px;
  line-height: 16px;
}

.project-subpage-kpis .workbench-summary-card strong {
  margin-top: 4px;
  font-size: 20px;
  line-height: 25px;
}

.project-subpage-kpis .workbench-summary-card small {
  display: -webkit-box;
  margin-top: 3px;
  line-height: 16px;
  white-space: normal;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.project-audit-health-grid,
.project-audit-node-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.project-audit-node-grid {
  grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr);
}

.project-audit-side-stack {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.audit-health-list,
.audit-node-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}

.audit-health-item,
.audit-node-item,
.audit-issue-item,
.audit-blocker-item {
  min-width: 0;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.audit-health-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  min-height: 92px;
  padding: 12px;
  background: #f8fbff;
}

.audit-health-item.is-warning {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.audit-health-item.is-healthy {
  background: #f2fbf6;
  border-color: #c9ead8;
}

.audit-health-dot {
  width: 8px;
  height: 8px;
  margin-top: 7px;
  background: #16a34a;
  border-radius: 50%;
}

.audit-health-item.is-warning .audit-health-dot {
  background: #f59e0b;
}

.audit-health-copy {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.audit-health-copy strong,
.audit-node-item strong,
.audit-issue-item strong,
.audit-blocker-item strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-health-copy small,
.audit-health-copy em,
.audit-node-item small,
.audit-issue-item small,
.audit-issue-item span,
.audit-blocker-item span {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
}

.audit-health-copy small,
.audit-health-copy em,
.audit-issue-item span,
.audit-blocker-item span {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  white-space: normal;
  -webkit-line-clamp: 2;
}

.audit-health-copy em {
  font-style: normal;
  color: #475569;
}

.audit-issue-list,
.audit-blocker-list {
  display: grid;
  gap: 10px;
}

.audit-issue-item,
.audit-blocker-item {
  display: grid;
  gap: 6px;
  padding: 11px 12px;
  background: #fff;
}

.audit-issue-item {
  border-color: #f3d6a9;
}

.audit-issue-item :deep(.el-tag),
.audit-blocker-item :deep(.el-tag) {
  justify-self: start;
}

.audit-node-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px 10px;
  min-height: 112px;
  padding: 12px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #fff;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.audit-node-item:hover,
.audit-node-item:focus-visible {
  border-color: #9db8df;
  outline: 0;
  box-shadow: 0 10px 22px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.audit-node-item span {
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #2563eb;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-node-item strong,
.audit-node-item small,
.audit-node-item em {
  grid-column: 1 / -1;
}

.audit-node-item :deep(.el-tag) {
  grid-row: 1;
  grid-column: 2;
  justify-self: end;
  max-width: 112px;
}

.audit-node-item em {
  justify-self: start;
  min-height: 22px;
  padding: 2px 7px;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  line-height: 18px;
  color: #b45309;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 5px;
}

.audit-empty-state {
  display: grid;
  gap: 6px;
  min-height: 96px;
  padding: 16px;
  background: #f8fbff;
  border: 1px dashed #c8d8ed;
  border-radius: 8px;
  align-content: center;
}

.audit-empty-state strong {
  font-size: 14px;
  font-weight: 900;
  color: #172033;
}

.audit-empty-state span {
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
}

.graph-node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 12px;
}

.graph-node-card {
  position: relative;
  min-width: 0;
  min-height: 118px;
  padding: 14px 14px 14px 18px;
  text-align: left;
  cursor: default;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 5%);
}

.graph-node-card::before {
  position: absolute;
  top: 14px;
  bottom: 14px;
  left: 0;
  width: 4px;
  content: '';
  background: #2563eb;
  border-radius: 0 4px 4px 0;
}

.graph-node-card span,
.graph-node-card strong,
.graph-node-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-node-card span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
  white-space: nowrap;
}

.graph-node-card strong {
  margin-top: 10px;
  font-size: 18px;
  font-weight: 900;
  line-height: 24px;
  color: #172033;
  white-space: nowrap;
}

.graph-node-card small {
  margin-top: 8px;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
}

.audit-step-list {
  display: grid;
  gap: 10px;
  max-height: 322px;
  padding-right: 4px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: #c7d5e8 transparent;
}

.drawer-step-list {
  max-height: min(46vh, 420px);
}

.audit-step-card {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding: 12px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 1px solid #e0e9f6;
  border-radius: 8px;
}

.audit-step-index {
  display: flex;
  justify-content: center;
}

.audit-step-index span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 11px;
  font-weight: 900;
  color: #1f66d8;
  background: #eff6ff;
  border: 1px solid #c9dcfb;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}

.audit-step-body {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.audit-step-title {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.audit-step-title strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-step-body p {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #334155;
  overflow-wrap: anywhere;
}

.audit-step-evidence {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #e8eef7;
  border-radius: 7px;
}

.audit-step-evidence span {
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #64748b;
}

.audit-step-evidence strong {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  color: #26364e;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-step-card .audit-step-evidence strong,
.drawer-step-card .audit-step-body small {
  white-space: normal;
  overflow-wrap: anywhere;
}

.audit-step-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.audit-step-meta span {
  min-height: 22px;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #3568b7;
  background: #eff6ff;
  border: 1px solid #d4e3f8;
  border-radius: 999px;
}

.audit-step-meta .audit-step-meta-label {
  color: #475569;
  background: #f8fafc;
  border-color: #e2e8f0;
}

.audit-step-body small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-trace-list {
  display: grid;
  gap: 12px;
  max-height: 380px;
  padding-right: 4px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: #c7d5e8 transparent;
}

.pageindex-trace-card {
  display: grid;
  gap: 9px;
  min-width: 0;
  padding: 12px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 1px solid #dfeaf7;
  border-radius: 8px;
}

.pageindex-trace-head,
.pageindex-query-block,
.pageindex-trace-facts span,
.pageindex-trace-action {
  min-width: 0;
}

.pageindex-trace-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.pageindex-trace-head div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.pageindex-trace-head span,
.pageindex-query-block span,
.pageindex-trace-facts em {
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #64748b;
}

.pageindex-trace-head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-query-block {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #e8eef7;
  border-radius: 8px;
}

.pageindex-query-block p {
  margin: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  color: #26364e;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-route-flow {
  display: grid;
  grid-template-columns: max-content minmax(28px, 1fr) max-content max-content;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.pageindex-route-flow span,
.pageindex-route-flow strong,
.pageindex-route-flow em {
  min-width: 0;
  min-height: 24px;
  padding: 4px 8px;
  overflow: hidden;
  font-size: 12px;
  font-style: normal;
  font-weight: 900;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 999px;
}

.pageindex-route-flow span {
  color: #3568b7;
  background: #eff6ff;
  border: 1px solid #d4e3f8;
}

.pageindex-route-flow strong {
  color: #15803d;
  background: #ecfdf3;
  border: 1px solid #bfe8cf;
}

.pageindex-route-flow em {
  color: #b45309;
  background: #fff7ed;
  border: 1px solid #fed7aa;
}

.pageindex-route-flow i {
  display: block;
  height: 1px;
  background: linear-gradient(90deg, #c7d5e8, #8fb6f3);
}

.pageindex-trace-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.pageindex-trace-facts span {
  display: grid;
  gap: 2px;
  min-height: 42px;
  padding: 6px 8px;
  background: #f8fbff;
  border: 1px solid #e3edf9;
  border-radius: 8px;
}

.pageindex-trace-facts strong {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  line-height: 17px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-trace-action {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 8px;
}

.pageindex-trace-action span {
  font-size: 12px;
  font-weight: 900;
  line-height: 16px;
}

.pageindex-trace-action strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-trace-action.is-ok {
  color: #166534;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
}

.pageindex-trace-action.is-warning {
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

.empty-workbench {
  display: grid;
  gap: 16px;
  min-height: 300px;
  padding: 24px;
  background: linear-gradient(180deg, #f8fbff 0%, #fff 100%);
  border: 1px dashed #bfd3ef;
  border-radius: 8px;
  align-content: center;
}

.empty-workbench__copy {
  display: grid;
  gap: 8px;
  max-width: 780px;
}

.empty-workbench__copy strong {
  font-size: 20px;
  line-height: 1.35;
  color: #172033;
}

.empty-workbench__copy span {
  font-size: 14px;
  line-height: 1.6;
  color: #475569;
}

.empty-workbench__steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.empty-workbench__steps div {
  min-height: 86px;
  padding: 14px;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.empty-workbench__steps span {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 800;
  color: #2563eb;
}

.empty-workbench__steps strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.55;
  color: #334155;
}

.subpage-switch {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.subpage-switch button {
  min-height: 82px;
  padding: 13px 14px;
  color: #475569;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    background-color 180ms ease;
}

.subpage-switch button:hover,
.subpage-switch button.active {
  background: #f8fbff;
  border-color: #9fc1fb;
  box-shadow: 0 8px 18px rgb(37 99 235 / 8%);
}

.subpage-switch span {
  display: block;
  font-size: 14px;
  font-weight: 800;
  line-height: 20px;
  color: #172033;
}

.subpage-switch small {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  text-overflow: ellipsis;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(176px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.metric-card {
  min-height: 96px;
  padding: 18px;
  background: #fff;
  border: 0;
  border-radius: 8px;
  box-shadow:
    0 0 0 1px #e6edf7,
    0 8px 18px rgb(15 23 42 / 4%);
}

.metric-card span {
  display: block;
  margin-bottom: 12px;
  overflow: hidden;
  font-size: 13px;
  line-height: 18px;
  color: #667085;
  text-overflow: ellipsis;
}

.metric-card strong {
  display: block;
  overflow: hidden;
  font-size: 28px;
  line-height: 34px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.metric-card--green {
  box-shadow:
    0 0 0 1px #d9eadf,
    0 8px 18px rgb(15 23 42 / 4%);
}

.metric-card--orange {
  box-shadow:
    0 0 0 1px #f3e5c5,
    0 8px 18px rgb(15 23 42 / 4%);
}

.metric-card--red {
  box-shadow:
    0 0 0 1px #f2d2d2,
    0 8px 18px rgb(15 23 42 / 4%);
}

.metric-card--blue {
  box-shadow:
    0 0 0 1px #d8e4f8,
    0 8px 18px rgb(15 23 42 / 4%);
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.workflow-card {
  position: relative;
  display: grid;
  min-height: 150px;
  padding: 18px;
  overflow: hidden;
  color: #172033;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease;
}

.workflow-card:hover {
  border-color: #a9c8ff;
  box-shadow: 0 12px 24px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.workflow-card span,
.workflow-card strong,
.workflow-card small,
.workflow-card em {
  position: relative;
  z-index: 1;
}

.workflow-card span {
  font-size: 15px;
  font-weight: 800;
}

.workflow-card strong {
  margin-top: 10px;
  font-size: 28px;
  line-height: 34px;
  font-variant-numeric: tabular-nums;
}

.workflow-card small {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.5;
  color: #667085;
}

.workflow-card em {
  align-self: end;
  margin-top: 14px;
  font-size: 13px;
  font-style: normal;
  font-weight: 800;
  color: #2563eb;
}

.workflow-card::after {
  position: absolute;
  right: -32px;
  bottom: -36px;
  width: 112px;
  height: 112px;
  content: '';
  background: rgb(37 99 235 / 7%);
  border-radius: 999px;
}

.workflow-card--green::after {
  background: rgb(22 163 74 / 8%);
}

.workflow-card--orange::after {
  background: rgb(217 119 6 / 9%);
}

.panel {
  min-width: 0;
  max-width: 100%;
  margin-bottom: 20px;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.panel :deep(.el-card__header) {
  min-height: 52px;
  padding: 14px 18px;
  font-weight: 700;
  background: #fbfcfe;
  border-bottom: 1px solid #e8edf5;
}

.panel :deep(.el-card__body) {
  padding: 18px;
}

.panel-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  font-weight: 700;
}

.panel-header span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fde-tabs {
  margin-top: 2px;
}

.fde-tabs :deep(.el-row) {
  min-width: 0;
  max-width: 100%;
  row-gap: 18px;
}

.fde-tabs :deep(.el-col) {
  min-width: 0;
  max-width: 100%;
}

.fde-tabs :deep(.el-tabs__header) {
  display: none;
}

.fde-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.fde-tabs :deep(.el-tabs__item) {
  height: 46px;
  padding: 0 18px;
  font-weight: 700;
  color: #475467;
}

.fde-tabs :deep(.el-tabs__item.is-active) {
  color: #1f66d8;
}

.fde-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  background: #2563eb;
  border-radius: 999px;
}

.fde-console :deep(.el-table) {
  --el-table-header-bg-color: #f7f9fc;
  --el-table-row-hover-bg-color: #f4f8ff;

  width: 100%;
  overflow: hidden;
  font-size: 14px;
  border-radius: 6px;
}

.fde-console :deep(.el-table th.el-table__cell) {
  padding: 12px 0;
  font-weight: 700;
  color: #4b5563;
  background: #f7f9fc;
}

.fde-console :deep(.el-table td.el-table__cell) {
  padding: 11px 0;
  vertical-align: middle;
}

.fde-console :deep(.el-table .cell) {
  padding: 0 16px;
  line-height: 24px;
}

.fde-console :deep(.el-descriptions__label.el-descriptions__cell) {
  width: 140px;
  font-weight: 700;
  color: #475467;
  background: #f7f9fc;
}

.fde-console :deep(.el-descriptions__cell) {
  line-height: 22px;
}

.fde-console :deep(.el-button) {
  border-radius: 6px;
}

.fde-console :deep(.el-tag) {
  max-width: 100%;
  border-radius: 999px;
}

.gate-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.artifact-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.artifact-summary-item {
  min-height: 76px;
  padding: 14px;
  background: #fbfcfe;
  border: 1px solid #e8edf5;
  border-radius: 8px;
}

.artifact-summary-item span {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.artifact-summary-item strong {
  display: block;
  margin-top: 4px;
  font-size: 20px;
  color: #172033;
}

.audit-drawer-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: start;
  padding: 16px;
  margin-bottom: 12px;
  background: linear-gradient(135deg, #f1f7ff 0%, #fff 100%);
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.audit-drawer-hero span,
.audit-drawer-hero small,
.audit-drawer-hero strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.audit-drawer-hero span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.audit-drawer-hero strong {
  margin-top: 5px;
  font-size: 20px;
  font-weight: 900;
  line-height: 28px;
  color: #172033;
  white-space: nowrap;
}

.audit-drawer-hero small {
  margin-top: 4px;
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
}

.audit-drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.audit-drawer-tabs {
  margin-top: 12px;
}

:global(.fde-audit-drawer .el-drawer__header) {
  padding: 18px 20px 12px;
  margin-bottom: 0;
  border-bottom: 1px solid #e6edf7;
}

:global(.fde-audit-drawer .el-drawer__body) {
  padding: 16px 20px 24px;
  background: #f8fafc;
}

.gate-summary-item {
  min-height: 82px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 8px;
}

.gate-summary-item span {
  display: block;
  color: var(--el-text-color-secondary);
}

.gate-summary-item strong {
  display: block;
  margin-top: 8px;
  font-size: 18px;
  color: #172033;
}

.annotation-canvas {
  position: relative;
  min-height: 560px;
  overflow: hidden;
  background: linear-gradient(90deg, rgb(37 99 235 / 7%) 1px, transparent 1px),
    linear-gradient(rgb(37 99 235 / 7%) 1px, transparent 1px), #f8fafc;
  background-size: 40px 40px;
  border: 1px solid #cbd8ea;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 70%);
}

.annotation-image,
.annotation-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.annotation-image {
  object-fit: contain;
}

.annotation-overlay {
  pointer-events: none;
}

.annotation-overlay rect {
  fill: rgb(37 99 235 / 12%);
  stroke: #2563eb;
  stroke-width: 4;
}

.annotation-overlay text {
  fill: #1f2d3d;
  font-size: 28px;
  paint-order: stroke;
  stroke: #fff;
  stroke-width: 4;
}

.annotation-box-tables rect {
  fill: rgb(22 163 74 / 12%);
  stroke: #16a34a;
}

.annotation-box-seals rect {
  fill: rgb(220 38 38 / 12%);
  stroke: #dc2626;
}

.annotation-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--el-text-color-secondary);
  text-align: center;
}

.annotation-list {
  display: grid;
  gap: 16px;
  max-height: 390px;
  overflow: auto;
}

.annotation-section {
  display: grid;
  gap: 8px;
}

.annotation-section strong {
  line-height: 22px;
}

.annotation-item {
  display: grid;
  min-height: 46px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e8edf5;
  border-radius: 6px;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) auto;
  align-items: center;
  gap: 12px;
}

.annotation-item span,
.annotation-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.annotation-item small {
  color: var(--el-text-color-secondary);
}

:global(.ocr-annotation-dialog .el-dialog__header) {
  padding-bottom: 12px;
  border-bottom: 1px solid #e8edf5;
}

:global(.ocr-annotation-dialog .el-dialog__body) {
  padding-top: 18px;
}

:global(.ocr-annotation-dialog .el-form-item) {
  margin-bottom: 18px;
}

:global(.ocr-annotation-dialog .el-space) {
  flex-wrap: wrap;
  row-gap: 10px;
}

@media (width <= 1360px) {
  .project-audit-header {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-audit-selectors {
    width: 100%;
    min-width: 0;
    justify-content: stretch;
  }

  .project-audit-selectors :deep(.el-space__item) {
    flex: 1 1 280px;
    min-width: 0;
  }

  .project-audit-select {
    width: 100%;
  }

  .project-audit-module-bar {
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
  }

  .project-audit-focus-facts {
    grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  }

  .workbench-summary-grid {
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  }
}

@media (width <= 1180px) {
  .project-audit-health-grid,
  .project-audit-node-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
  }
}

@media (width <= 768px) {
  .page-toolbar {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-audit-header {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-audit-selectors {
    width: 100%;
    justify-content: stretch;
  }

  .project-audit-select {
    width: 100%;
  }

  .project-audit-module-bar {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-audit-module-title small {
    white-space: normal;
  }

  .project-audit-focus-facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-grid,
  .gate-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .annotation-canvas {
    min-height: 360px;
  }

  .annotation-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .audit-drawer-hero {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (width <= 520px) {
  .metric-grid,
  .gate-summary,
  .artifact-summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
