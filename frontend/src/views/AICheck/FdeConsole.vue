<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts'
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
  ElPagination,
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
  convertFdeOcrCapabilityTestToAnnotationApi,
  convertFdeOcrCapabilityTestToEvaluationCaseApi,
  createFdeDataExportApi,
  createFdeEvaluationRunApi,
  createFdeMaskingPolicyApi,
  createFdeOcrCapabilityTestRunApi,
  createFdeOcrCapabilityTestUploadSessionApi,
  createFdeOcrCorrectionApi,
  createFdeOcrEvaluationRunApi,
  createFdeReviewRunFeedbackApi,
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
  getFdeOcr100HandoffArtifactApi,
  getFdeOcrCapabilityTestPagePreviewApi,
  getFdeOcrCapabilityTestRunApi,
  getFdeOcrRunApi,
  getFdeOcrQualityApi,
  getFdeProjectAuditWorkspaceApi,
  getFdeProjectVectorFileDetailApi,
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
  listFdeOcrCapabilityTestRunsApi,
  listFdeOcrRunsApi,
  listFdeReviewRunsApi,
  listFdeReleasesApi,
  markFdeShadowPassedApi,
  proposeFdeCostBudgetChangeApi,
  requestFdeAccessGrantApi,
  refreshFdeOcr100ActionBoardApi,
  reviewFdeOcrAnnotationTaskApi,
  replayFdeAiRunApi,
  replayFdeReviewRunApi,
  saveFdeOcrAnnotationLabelApi,
  shadowFdeReviewRunApi,
  startFdeShadowApi,
  submitFdeReleaseApi,
  triageFdeFeedbackApi,
  updateFdeIncidentRcaApi,
  uploadFdeOcrCapabilityTestFileApi,
  validateFdeBusinessPacksApi,
  verifyFdeOcrAnnotationTaskApi
} from '@/api/aicheck'
import { Echart } from '@/components/Echart'
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
  FdeOcrCapabilityTestDetailPayload,
  FdeOcrCapabilityTestRun,
  FdeOcrAnnotationPayload,
  FdeOcrEvalRun,
  FdeOcrQualityPayload,
  FdeOcrRunDetailPayload,
  FdeProjectAuditSummary,
  FdeProjectAuditWorkspace,
  FdeReviewRun,
  FdeReviewRunDetailPayload,
  FdeReleasePayload,
  FdeVectorFileDetailPayload,
  FdeVectorQualityPayload
} from '@/api/aicheck'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  friendlyFieldLabel,
  friendlyRuleCode,
  statusLabelMap as sharedStatusLabelMap,
  techTermLabels as sharedTechTermLabels
} from './components/auditLabels'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const activeFdeTab = ref('dashboard')
const selectedFdeDashboardTab = ref<'agent' | 'ocr'>('agent')
const fdeChartZoom = ref<Record<FdeChartKey, number>>({
  ocrHeatmap: 1,
  vectorSankey: 1,
  pageIndexTree: 1,
  reviewTimeline: 1,
  langGraph: 1
})
const fdeChartPan = ref<Record<FdeChartKey, { x: number; y: number }>>({
  ocrHeatmap: { x: 0, y: 0 },
  vectorSankey: { x: 0, y: 0 },
  pageIndexTree: { x: 0, y: 0 },
  reviewTimeline: { x: 0, y: 0 },
  langGraph: { x: 0, y: 0 }
})
const dashboard = ref<FdeDashboardPayload | null>(null)
const aiRuns = ref<FdeAiRun[]>([])
const selectedRun = ref<FdeAiRunDetailPayload | null>(null)
const reviewRuns = ref<FdeReviewRun[]>([])
const selectedReviewRun = ref<FdeReviewRunDetailPayload | null>(null)
const reviewAuditDrawerVisible = ref(false)
const vectorFileQualityDrawerVisible = ref(false)
const selectedVectorFileQuality = ref<Record<string, unknown> | null>(null)
const selectedVectorFileDetail = ref<FdeVectorFileDetailPayload | null>(null)
const vectorFileDetailLoading = ref(false)
const vectorFileDetailError = ref('')
const selectedVectorFileSourceRow = ref<Record<string, unknown> | null>(null)
const selectedVectorEvidence = ref<Record<string, unknown> | null>(null)
const selectedVectorEvidenceType = ref('source')
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
const ocr100ActionBoardRefreshing = ref(false)
const ocr100HandoffOpening = ref('')
const ocrAuditDrawerVisible = ref(false)
const ocrAnnotation = ref<FdeOcrAnnotationPayload | null>(null)
const ocrCapabilityTestRuns = ref<FdeOcrCapabilityTestRun[]>([])
const selectedOcrCapabilityTest = ref<FdeOcrCapabilityTestDetailPayload | null>(null)
const selectedOcrCapabilityTestRunId = ref('')
const ocrCapabilityTestFile = ref<File | null>(null)
const ocrCapabilityLocalPreviewUrl = ref('')
const ocrCapabilityPdfPageObjectUrl = ref('')
const ocrCapabilityPdfPageObjectKey = ref('')
const ocrCapabilityPdfPagePreviewLoading = ref(false)
const ocrCapabilityPdfPagePreviewError = ref('')
const ocrCapabilityFileInputRef = ref<HTMLInputElement | null>(null)
const ocrCapabilityDialogVisible = ref(false)
const ocrSecondaryMenuVisible = ref(false)
const ocrCapabilityTestLoading = ref(false)
const ocrCapabilityRecordsLoading = ref(false)
const ocrCapabilityDetailLoading = ref(false)
const ocrCapabilityRecentOpen = ref(false)
const ocrCapabilityTestStage = ref('')
const ocrCapabilityTestPolling = ref<number | undefined>()
const ocrCapabilityTestForm = ref({
  profileId: 'auto',
  documentType: 'auto',
  maxPages: 1,
  enableTables: true,
  enableSeals: true,
  enableFallback: false,
  disableRemediation: true,
  quickMode: true
})
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
type FdeTone = 'blue' | 'green' | 'orange' | 'red'
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
type OcrSubpage = 'overview' | 'capability-test' | 'annotation' | 'runtime' | 'evaluation'
type OcrStatusTab = 'issue' | 'annotation' | 'runtime' | 'release'
type OcrStatusDialogType = OcrStatusTab | 'quality'
type OcrSecondaryTool = 'annotation' | 'runtime' | 'release' | 'quality'
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
const ocrStatusDialogVisible = ref(false)
const ocrStatusDialogType = ref<OcrStatusDialogType>('issue')
const selectedOcrStatusTab = ref<OcrStatusTab>('issue')
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
  | 'go-ocr-capability-test'
  | 'go-ocr-tools'
  | 'start-ocr-evaluation'
  | 'triage-feedback'
  | 'create-review-diagnostic-feedback'
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

type FdeChartKey = 'ocrHeatmap' | 'vectorSankey' | 'pageIndexTree' | 'reviewTimeline' | 'langGraph'

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
    badge: '溯源',
    tone: 'blue',
    title: 'AI Run 追踪',
    subtitle: '查看不可变 AI 运行、溯源明细、输入输出校验哈希、脱敏策略和诊断重跑。',
    nextAction: '先选中一条运行记录，再查看溯源明细或发起诊断重跑。',
    actions: [{ key: 'replay-ai-run', label: '诊断重跑', plain: true }]
  },
  'review-runs': {
    group: '重点工作台',
    label: 'Agent 审查编排',
    badge: '链路',
    tone: 'green',
    title: 'Agent 审查编排',
    subtitle: '查看流程编排、AI 员工节点和审查产物。',
    nextAction: '先选中审查任务，再检查工作流时间线和校验失败。',
    actions: [
      { key: 'replay-review-run', label: '诊断重跑', plain: true },
      { key: 'shadow-review-run', label: 'Shadow', plain: true },
      { key: 'create-review-diagnostic-feedback', label: '记录诊断修正', plain: true }
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
    subtitle: '管理评估集、回归集和发布前门禁，用样本验证 AI 员工、提示词和模型版本。',
    nextAction: '选择评估集后发起评测。',
    actions: [{ key: 'start-evaluation', label: '发起评测', plain: true }]
  },
  'ocr-quality': {
    group: '重点工作台',
    label: 'OCR 质量与标注',
    badge: '识别',
    tone: 'green',
    title: 'OCR 工作台',
    subtitle: '在线测试、识别问题定位、人工修正和发布前评测集中在这里。',
    nextAction: '只想测一份资料时，点“在线测 OCR”。',
    actions: [
      { key: 'go-ocr-capability-test', label: '在线测 OCR', type: 'primary' },
      { key: 'go-ocr-tools', label: '更多工具', plain: true }
    ]
  },
  'capability-bundles': {
    group: '版本发布',
    label: '能力版本组合',
    badge: 'Bundle',
    tone: 'blue',
    title: '能力版本组合',
    subtitle: '管理 AI 员工、提示词、模型路由、规则、知识库和 OCR 解析配置的发布组合。',
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
    label: '业务类型工厂',
    badge: '复用',
    tone: 'blue',
    title: '业务类型工厂',
    subtitle: '校验业务类型的角色、节点、资料目录、规则、知识库、模板和可迁移性。',
    nextAction: '先查看业务类型门禁分段和阻断项。',
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
  { label: 'AI 员工', value: '流程编排 + AI 员工节点追踪' },
  { label: '边界', value: 'FDE 只做 AI 诊断、标注和治理，不办理业务审批' }
] as const

const syncTabFromRoute = () => {
  activeFdeTab.value = routeTabMap[currentFdeRouteKey.value] || 'dashboard'
}

const parseFdeHashPath = () => {
  if (typeof window === 'undefined') return ''
  const hashPath = window.location.hash.replace(/^#/, '').split('?')[0]
  return hashPath.startsWith('/fde/') ? hashPath : ''
}

const parseFdeBrowserPath = () => {
  if (typeof window === 'undefined') return ''
  return window.location.pathname.startsWith('/fde/') ? window.location.pathname : ''
}

const currentFdePath = computed(() => {
  const routeFullPath = route.fullPath
  const routePath = routeFullPath.split('?')[0] || route.path
  return parseFdeHashPath() || parseFdeBrowserPath() || routePath
})

const currentFdeRouteKey = computed(() =>
  String(currentFdePath.value.split('/').filter(Boolean).pop() || 'dashboard')
)

const isFdeRoute = (...keys: string[]) => keys.includes(currentFdeRouteKey.value)

const chartBaseSizes: Record<FdeChartKey, { width: number; height: number }> = {
  ocrHeatmap: { width: 1100, height: 300 },
  vectorSankey: { width: 1280, height: 320 },
  pageIndexTree: { width: 1720, height: 470 },
  reviewTimeline: { width: 1160, height: 300 },
  langGraph: { width: 1080, height: 430 }
}
const chartZoomStep = 0.02
const chartGestureZoomSensitivity = 0.1
const chartZoom = (key: FdeChartKey) => fdeChartZoom.value[key] || 1
const chartPan = (key: FdeChartKey) => fdeChartPan.value[key] || { x: 0, y: 0 }
const chartZoomPercent = (key: FdeChartKey) => `${Math.round(chartZoom(key) * 100)}%`
const chartBaseWidth = (base: number) => `${base}px`
const chartBaseHeight = (base: number) => `${base}px`
const chartFrameStyle = (_key: FdeChartKey, _width: number, height: number) => ({
  width: '100%',
  height: `${height}px`
})
const chartContentStyle = (key: FdeChartKey, width: number, height: number) => ({
  width: `${width}px`,
  height: `${height}px`,
  transform: `translate3d(${chartPan(key).x}px, ${chartPan(key).y}px, 0) scale(${chartZoom(key)})`,
  transformOrigin: '0 0'
})
const clampChartZoom = (value: number) => Math.min(1.45, Math.max(1, Number(value.toFixed(2))))
const chartFrameIn = (shell?: HTMLElement | null) =>
  shell?.querySelector<HTMLElement>('.chart-zoom-frame') || null
const clampChartPan = (
  key: FdeChartKey,
  x: number,
  y: number,
  shell?: HTMLElement | null,
  zoom = chartZoom(key)
) => {
  const base = chartBaseSizes[key]
  const width = base.width
  const height = base.height
  const viewportWidth = shell?.clientWidth || width
  const viewportHeight = shell?.clientHeight || height
  const minX = Math.min(0, viewportWidth - width * zoom)
  const minY = Math.min(0, viewportHeight - height * zoom)
  return {
    x: Math.round(Math.min(0, Math.max(minX, x))),
    y: Math.round(Math.min(0, Math.max(minY, y)))
  }
}
const applyChartTransform = (
  key: FdeChartKey,
  value: number,
  pan = chartPan(key),
  shell?: HTMLElement | null
) => {
  const zoom = clampChartZoom(value)
  const clampedPan = clampChartPan(key, pan.x, pan.y, shell, zoom)
  fdeChartZoom.value = {
    ...fdeChartZoom.value,
    [key]: zoom
  }
  fdeChartPan.value = {
    ...fdeChartPan.value,
    [key]: zoom === 1 && !shell ? { x: 0, y: 0 } : clampedPan
  }
}
const setChartZoom = (key: FdeChartKey, value: number, shell?: HTMLElement | null) =>
  applyChartTransform(key, value, chartPan(key), shell)
const setChartPan = (key: FdeChartKey, pan: { x: number; y: number }, shell?: HTMLElement | null) =>
  applyChartTransform(key, chartZoom(key), pan, shell)
const zoomInChart = (key: FdeChartKey) => setChartZoom(key, chartZoom(key) + chartZoomStep)
const zoomOutChart = (key: FdeChartKey) => setChartZoom(key, chartZoom(key) - chartZoomStep)
const resetChartZoom = (key: FdeChartKey) => applyChartTransform(key, 1, { x: 0, y: 0 })
const chartGesturePoints = new Map<FdeChartKey, Map<number, { x: number; y: number }>>()
let chartDragState: {
  key: FdeChartKey
  pointerId: number
  shell: HTMLElement
  startX: number
  startY: number
  startPanX: number
  startPanY: number
} | null = null
let chartPinchState: {
  key: FdeChartKey
  shell: HTMLElement
  startDistance: number
  startZoom: number
} | null = null
let chartNativeGestureState: {
  key: FdeChartKey
  shell: HTMLElement
  startZoom: number
} | null = null
type NativeChartGestureEvent = Event & {
  scale?: number
  clientX?: number
  clientY?: number
}

const getChartShell = (event: Event) => event.currentTarget as HTMLElement
const chartPointsFor = (key: FdeChartKey) => {
  if (!chartGesturePoints.has(key)) {
    chartGesturePoints.set(key, new Map())
  }
  return chartGesturePoints.get(key)!
}
const distanceBetweenChartPoints = (points: Array<{ x: number; y: number }>) => {
  if (points.length < 2) return 0
  return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y)
}
const midpointBetweenChartPoints = (points: Array<{ x: number; y: number }>) => ({
  x: (points[0].x + points[1].x) / 2,
  y: (points[0].y + points[1].y) / 2
})
const zoomChartAt = (
  key: FdeChartKey,
  nextZoom: number,
  shell: HTMLElement,
  clientX: number,
  clientY: number
) => {
  const currentZoom = chartZoom(key)
  const clampedZoom = clampChartZoom(nextZoom)
  if (clampedZoom === currentZoom) return
  const frame = chartFrameIn(shell)
  const rect = frame?.getBoundingClientRect() || shell.getBoundingClientRect()
  const anchorX = clientX - rect.left
  const anchorY = clientY - rect.top
  const currentPan = chartPan(key)
  const contentX = (anchorX - currentPan.x) / currentZoom
  const contentY = (anchorY - currentPan.y) / currentZoom
  applyChartTransform(
    key,
    clampedZoom,
    {
      x: anchorX - contentX * clampedZoom,
      y: anchorY - contentY * clampedZoom
    },
    shell
  )
}
const handleChartWheel = (event: WheelEvent, key: FdeChartKey) => {
  event.preventDefault()
  event.stopPropagation()
  const shell = getChartShell(event)
  const unit = event.deltaMode === 1 ? 18 : event.deltaMode === 2 ? shell.clientHeight : 1
  if (event.ctrlKey || event.metaKey) {
    const normalizedDelta = Math.max(-3, Math.min(3, event.deltaY * unit * 0.01))
    zoomChartAt(
      key,
      chartZoom(key) - normalizedDelta * chartZoomStep,
      shell,
      event.clientX,
      event.clientY
    )
    return
  }
  const pan = chartPan(key)
  const wheelX = event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX
  const wheelY = event.shiftKey && !event.deltaX ? 0 : event.deltaY
  setChartPan(
    key,
    {
      x: pan.x - wheelX * unit,
      y: pan.y - wheelY * unit
    },
    shell
  )
}
const handleChartKeydown = (event: KeyboardEvent, key: FdeChartKey) => {
  const shell = getChartShell(event)
  const pan = chartPan(key)
  const panStep = event.shiftKey ? 80 : 32
  if (event.key === '+' || event.key === '=') {
    event.preventDefault()
    setChartZoom(key, chartZoom(key) + chartZoomStep, shell)
    return
  }
  if (event.key === '-' || event.key === '_') {
    event.preventDefault()
    setChartZoom(key, chartZoom(key) - chartZoomStep, shell)
    return
  }
  if (event.key === '0') {
    event.preventDefault()
    resetChartZoom(key)
    return
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    setChartPan(key, { x: pan.x + panStep, y: pan.y }, shell)
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    setChartPan(key, { x: pan.x - panStep, y: pan.y }, shell)
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    setChartPan(key, { x: pan.x, y: pan.y + panStep }, shell)
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    setChartPan(key, { x: pan.x, y: pan.y - panStep }, shell)
  }
}
const startChartGesture = (event: PointerEvent, key: FdeChartKey) => {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  const shell = getChartShell(event)
  const points = chartPointsFor(key)
  points.set(event.pointerId, { x: event.clientX, y: event.clientY })
  shell.setPointerCapture?.(event.pointerId)
  shell.classList.add('is-panning')
  if (points.size >= 2) {
    const pointList = [...points.values()]
    chartPinchState = {
      key,
      shell,
      startDistance: distanceBetweenChartPoints(pointList),
      startZoom: chartZoom(key)
    }
    chartDragState = null
  } else {
    chartDragState = {
      key,
      pointerId: event.pointerId,
      shell,
      startX: event.clientX,
      startY: event.clientY,
      startPanX: chartPan(key).x,
      startPanY: chartPan(key).y
    }
    chartPinchState = null
  }
}
const moveChartGesture = (event: PointerEvent, key: FdeChartKey) => {
  const points = chartPointsFor(key)
  if (!points.has(event.pointerId)) return
  event.stopPropagation()
  points.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (points.size >= 2 && chartPinchState?.key === key) {
    event.preventDefault()
    const pointList = [...points.values()]
    const distance = distanceBetweenChartPoints(pointList)
    if (!chartPinchState.startDistance || !distance) return
    const center = midpointBetweenChartPoints(pointList)
    zoomChartAt(
      key,
      chartPinchState.startZoom *
        (1 + (distance / chartPinchState.startDistance - 1) * chartGestureZoomSensitivity),
      chartPinchState.shell,
      center.x,
      center.y
    )
    return
  }
  if (chartDragState?.key === key && chartDragState.pointerId === event.pointerId) {
    event.preventDefault()
    setChartPan(
      key,
      {
        x: chartDragState.startPanX + (event.clientX - chartDragState.startX),
        y: chartDragState.startPanY + (event.clientY - chartDragState.startY)
      },
      chartDragState.shell
    )
  }
}
const endChartGesture = (event: PointerEvent, key: FdeChartKey) => {
  const points = chartPointsFor(key)
  points.delete(event.pointerId)
  const shell = getChartShell(event)
  if (shell.hasPointerCapture?.(event.pointerId)) {
    shell.releasePointerCapture?.(event.pointerId)
  }
  if (chartDragState?.key === key && chartDragState.pointerId === event.pointerId) {
    chartDragState.shell.classList.remove('is-panning')
    chartDragState = null
  }
  if (points.size < 2 && chartPinchState?.key === key) {
    chartPinchState.shell.classList.remove('is-panning')
    chartPinchState = null
  }
  if (!points.size) {
    shell.classList.remove('is-panning')
  }
}
const startNativeChartGesture = (event: NativeChartGestureEvent, key: FdeChartKey) => {
  event.preventDefault()
  event.stopPropagation()
  const shell = getChartShell(event)
  shell.classList.add('is-panning')
  chartNativeGestureState = {
    key,
    shell,
    startZoom: chartZoom(key)
  }
}
const changeNativeChartGesture = (event: NativeChartGestureEvent, key: FdeChartKey) => {
  if (chartNativeGestureState?.key !== key) return
  event.preventDefault()
  event.stopPropagation()
  const shell = chartNativeGestureState.shell
  const rect = shell.getBoundingClientRect()
  const scale = Number(event.scale || 1)
  zoomChartAt(
    key,
    chartNativeGestureState.startZoom * (1 + (scale - 1) * chartGestureZoomSensitivity),
    shell,
    Number(event.clientX || rect.left + rect.width / 2),
    Number(event.clientY || rect.top + rect.height / 2)
  )
}
const endNativeChartGesture = (event: NativeChartGestureEvent, key: FdeChartKey) => {
  if (chartNativeGestureState?.key !== key) return
  event.preventDefault()
  event.stopPropagation()
  chartNativeGestureState.shell.classList.remove('is-panning')
  chartNativeGestureState = null
}

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

const buildProjectAuditRoutePath = (
  projectId: string,
  nodeId?: number,
  subpage: ProjectAuditSubpage = projectAuditSubpage.value
) => {
  const query = new URLSearchParams(buildProjectAuditRouteQuery(projectId, nodeId, subpage))
  return `/fde/projects?${query.toString()}`
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
  if (currentFdePath.value === '/fde/projects' && sameProjectAuditRouteQuery(query)) return
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
  if (currentFdePath.value === '/fde/projects' && selectedFdeProjectId.value) {
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
    { label: '章节溯源', value: 'pageindex', count: pageIndex },
    { label: 'Agent 编排', value: 'langgraph', count: langGraph },
    { label: 'OCR打标', value: 'ocr-labeling', count: ocrLabeling },
    { label: '评估', value: 'evaluation', count: evaluationReady }
  ]
})

const projectAuditMenuEmptyText = computed(() => {
  const keyword = projectAuditSearch.value.trim()
  if (keyword) return `没有找到“${keyword}”相关项目`
  if (projectAuditFilter.value === 'blocked') return '当前没有质量阻断项目'
  if (projectAuditFilter.value === 'vectorization') return '当前没有可向量化资料'
  if (projectAuditFilter.value === 'pageindex') return '当前没有章节溯源审计项目'
  if (projectAuditFilter.value === 'langgraph') return '当前没有 Agent 编排项目'
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
    return `章节节点 ${Number(metrics.pageIndexNodes || 0)} · 审查任务 ${Number(metrics.reviewRuns || 0)}`
  }
  if (subpage === 'langgraph') {
    return `审查任务 ${Number(metrics.reviewRuns || 0)} · AI 员工链路`
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
  const ocrAnnotationSummary = toRecord(ocrAnnotation.value?.summary)
  const activePath = currentFdePath.value
  const globalSection = {
    id: 'fde-global-workbenches',
    title: '全局控制台',
    meta: '不绑定项目',
    defaultOpen: activePath !== '/fde/projects',
    chips: [
      {
        label: 'OCR样本',
        value: Number(ocrAnnotationSummary.tasks || 0),
        tone: 'orange' as const
      },
      {
        label: '可评估',
        value: Number(ocrAnnotationSummary.readyForEval || 0),
        tone: Number(ocrAnnotationSummary.readyForEval || 0)
          ? ('green' as const)
          : ('orange' as const)
      },
      {
        label: '运行',
        value: ocrRuns.value.length,
        tone: ocrRuns.value.length ? ('green' as const) : ('blue' as const)
      }
    ],
    items: [
      {
        index: '00',
        label: 'OCR 质量控制台',
        hint:
          activePath === '/fde/ocr-quality'
            ? `样本 ${Number(ocrAnnotationSummary.tasks || 0)} · 可评估 ${Number(ocrAnnotationSummary.readyForEval || 0)}`
            : '',
        badge: activePath === '/fde/ocr-quality' ? '当前' : undefined,
        tone: 'green' as const,
        route: '/fde/ocr-quality',
        active: activePath === '/fde/ocr-quality'
      },
      {
        index: '01',
        label: 'Agent 审查编排',
        hint:
          activePath === '/fde/review-runs'
            ? `审查任务 ${reviewRuns.value.length} · Agent 编排图`
            : '',
        badge: activePath === '/fde/review-runs' ? '当前' : undefined,
        tone: 'green' as const,
        route: '/fde/review-runs',
        active: activePath === '/fde/review-runs'
      },
      {
        index: '02',
        label: 'FDE 总览',
        hint: activePath === '/fde/dashboard' ? 'AI 交付与治理摘要' : '',
        badge: activePath === '/fde/dashboard' ? '当前' : undefined,
        tone: 'blue' as const,
        route: '/fde/dashboard',
        active: activePath === '/fde/dashboard'
      }
    ]
  }

  if (!projects.length) {
    return [globalSection]
  }

  const projectSections = projects.map((item) => {
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
          activePath === '/fde/projects' &&
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
          route: buildProjectAuditRoutePath(item.project.id, undefined, subpage.key),
          active: isActive
        }
      })
    }
  })
  return [globalSection, ...projectSections]
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

const score100 = (value: unknown, fallback = 0) => {
  const numeric = Number(value ?? fallback)
  if (Number.isNaN(numeric)) return fallback
  return Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric)))
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
  ...sharedStatusLabelMap,
  active: '启用',
  accepted: '已接受',
  edited: '人工已修改',
  false_positive: '误报',
  missed_issue: '漏检',
  wrong_evidence: '证据位置错误',
  wrong_rule_reference: '依据引用错误',
  hallucination: '疑似幻觉',
  ocr_error: 'OCR 识别错误',
  kb_retrieval_error: '知识检索错误',
  rule_error: '规则配置错误',
  prompt_error: '提示词问题',
  model_error: '模型推理问题',
  business_pack_config_error: '业务类型配置问题',
  field_correction: '字段纠错',
  evidence_correction: '证据纠错',
  severity_correction: '等级修正',
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
  needs_human_confirmation: '需要人工确认',
  needs_human_review: '需人工复核',
  needs_labeling: '待标注',
  needs_triage: '待归因',
  normal: '正常',
  ocr_queued: 'OCR 排队中',
  ocr_running: 'OCR 识别中',
  over_budget: '超预算',
  pass: '通过',
  passed: '通过',
  production: '生产中',
  production_approved: '生产已批准',
  queued: '排队中',
  ready: '就绪',
  ready_for_eval: '可入评估',
  rejected: '已驳回',
  request_correction: '建议发起补正',
  reviewed: '已复核',
  running: '运行中',
  submitted: '已提交',
  stale: '需刷新',
  success: '成功',
  triaged: '已归因',
  approved_for_eval: '已准入评估集',
  incomplete: '不完整',
  missing: '缺失',
  unknown: '未知',
  hybrid_rag: '混合检索',
  pageindex: '章节溯源',
  pageindex_tree_search: '章节树检索',
  vector_search: '向量检索',
  review_basis_search: '审查依据检索',
  long_document_cross_section: '长文档跨章节检索',
  shadow: '影子运行',
  waiting_human_review: '待人工复核',
  waiting_upload: '等待上传',
  warning: '告警'
}

const friendlyStatus = (status: unknown, fallback = '-') => {
  const raw = String(status || '').trim()
  if (!raw) return fallback
  return statusLabelMap[raw] || raw
}

const techLabelMap: Record<string, string> = {
  ...sharedTechTermLabels,
  AICHECK_OCR_BASE_URL: 'OCR 服务地址',
  AICHECK_REVIEW_ORCHESTRATION: '审查编排模式',
  AICHECK_REVIEW_LLM_EXECUTION: 'LLM 调用模式',
  AICHECK_TASK_DISPATCH: '任务分发模式',
  OCR_SERVICE_NOT_CONFIGURED: 'OCR 服务地址未配置',
  OCR_RUNTIME_DOCTOR_UNAVAILABLE: 'OCR 运行体检不可用',
  'ocr.base-url': 'OCR 服务地址',
  'ocr.runtime-doctor': 'OCR 运行体检',
  'ocr-service': 'OCR 服务',
  'base-url': '服务地址',
  '/internal/ocr/doctor': 'OCR 运行体检接口',
  RuntimeError: '运行时错误',
  IntegrationServiceError: '集成服务错误',
  overall: '整体',
  all: '全部',
  generic_document_v1: '通用资料',
  piping_characteristic_list_v1: '管道特性表',
  quality_certificate_v1: '质量证明文件',
  ndt_rt_report_v1: '射线检测报告',
  ndt_ut_report_v1: '超声检测报告',
  construction_record_v1: '施工记录',
  welding_record_v1: '焊接记录',
  qualification_certificate_v1: '资质证书',
  calibration_certificate_v1: '校验证书',
  engineering_table_photo: '工程表格照片',
  engineering_document: '通用工程资料',
  quality_certificate: '质量证明文件',
  ndt_report: 'NDT 检测报告',
  scanned_pdf: '扫描 PDF',
  electronic_pdf: '电子 PDF',
  project_proxy: '项目级代理',
  document_explicit: '文件级绑定',
  chunking: '知识切片',
  compliance_review_agent: '资料合规复核员',
  deepseek_reasoner: 'DeepSeek 推理模型',
  'deepseek-reasoner': 'DeepSeek 推理模型',
  embedding_default: '默认本地向量模型',
  'embedding-default': '默认本地向量模型',
  vector_integrity: '向量完整性',
  vector_ready: '向量已就绪',
  vector_missing: '向量缺失',
  metadata_missing: '元数据缺失',
  source_document: '源资料',
  ocr_result: 'OCR 解析结果',
  vector_record: '向量记录',
  knowledge_chunk: '知识切片',
  field_accuracy: '字段准确率',
  field_recall: '字段召回率',
  table_structure_accuracy: '表格结构准确率',
  seal_detection_recall: '印章检测召回率',
  seal_text_accuracy: '印章文字准确率',
  bbox_hit_rate: '证据框命中率',
  evidence_validation: '证据校验',
  EVIDENCE_BBOX_REQUIRED: '证据框必须可定位',
  field_inconsistent: '字段不一致',
  field_missing: '字段缺失',
  cross_document_consistency_warning: '跨资料一致性风险',
  required_field_missing: '必填字段缺失',
  required_table_missing: '必需表格缺失',
  low_confidence_field: '字段识别置信度低',
  needs_human_confirmation: '需要人工确认',
  FIELD_LOW_CONFIDENCE: '字段识别置信度低',
  REQUIRED_FIELD_MISSING: '必填字段缺失',
  FIELD_EVIDENCE_MISSING: '字段缺少证据定位',
  FIELD_VALUE_CONFLICT: '字段值冲突',
  FIELD_FORMAT_INVALID: '字段格式不符合要求',
  OCR_FIELD_CONF_002: 'OCR 字段置信度过低',
  QC_CERT_FIELD_003: '质量证明文件缺少关键字段',
  SEAL_NOT_FOUND: '未检测到必需印章',
  SEAL_TEXT_LOW_CONFIDENCE: '印章文字置信度低',
  SEAL_REQUIRED_001: '资料必须有有效签章',
  TABLE_CELL_EVIDENCE_LOW: '表格单元格证据不足',
  TABLE_STRUCTURE_LOW_CONFIDENCE: '表格结构置信度低',
  TABLE_EVIDENCE_MISSING: '表格缺少证据定位',
  TABLE_ENGINE_CONFLICT: '表格引擎结果冲突',
  REQUIRED_TABLE_MISSING: '必需表格缺失',
  SEAL_EVIDENCE_MISSING: '印章缺少证据定位',
  EXPECTED_SEAL_TYPE_MISSING: '期望印章类型缺失',
  MISSING_FIELD_LABELS: '缺少字段标签',
  MISSING_SEAL_BBOX: '缺少印章证据框',
  MISSING_TABLE_CELL_LABELS: '缺少表格单元格标注',
  OCR_EVAL_FIELD_MISSING: '评估样本字段缺失',
  OCR_EVAL_FIELD_VALUE_MISMATCH: '评估样本字段值不一致',
  OCR_EVAL_FIELD_EVIDENCE_MISSING: '评估样本字段缺少证据',
  OCR_EVAL_FIELD_BBOX_MISMATCH: '评估样本字段框不匹配',
  OCR_EVAL_TABLE_MISSING: '评估样本表格缺失',
  OCR_EVAL_TABLE_EVIDENCE_MISSING: '评估样本表格缺少证据',
  OCR_EVAL_TABLE_BBOX_MISMATCH: '评估样本表格框不匹配',
  OCR_EVAL_SEAL_MISSING: '评估样本印章缺失',
  OCR_EVAL_SEAL_EVIDENCE_MISSING: '评估样本印章缺少证据',
  OCR_EVAL_SEAL_BBOX_MISMATCH: '评估样本印章框不匹配',
  WELDER_CERT_001: '焊工资格证必须上传',
  load_context: '读取项目上下文',
  load_document_context: '加载资料上下文',
  load_ocr_result: '读取 OCR 结果',
  llm_review: '生成审查草稿',
  llm_generate_findings: 'LLM 生成审查草稿',
  quality_gate: '质量门禁',
  retrieve_knowledge: '检索知识依据',
  run_rule_engine: '执行规则引擎',
  run_rule_checks: '执行规则检查',
  validate_output: '校验证据与依据',
  waiting_human_review: '等待人工复核',
  hybrid_rag: '混合检索',
  pageindex: '章节溯源',
  pageindex_tree_search: '章节树检索',
  vector_search: '向量检索',
  bm25: '关键词检索',
  dense_vector: '语义向量检索',
  reranker: '重排模型',
  review_basis_search: '审查依据检索',
  long_document_cross_section: '长文档跨章节检索',
  field_extraction: '字段抽取',
  table_structure: '表格结构',
  seal_recognition: '印章识别',
  pageindex_evidence: '章节溯源证据'
}

const friendlyTechLabel = (value: unknown, fallback = '-') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  const direct = techLabelMap[raw] || statusLabelMap[raw]
  if (direct) return direct
  if (/^[a-z0-9_]+_agent$/i.test(raw)) return `AI 员工：${raw.replace(/_agent$/i, '')}`
  if (/^[a-z0-9_]+_service$/i.test(raw)) return `服务：${raw.replace(/_service$/i, '')}`
  if (/^[a-z0-9_]+_profile$/i.test(raw)) return `解析场景：${raw.replace(/_profile$/i, '')}`
  if (/^[a-z0-9_]+_v\d+$/i.test(raw)) return `配置版本：${raw}`
  return raw
}

const technicalTextTokenMap: Record<string, string> = {
  AICHECK_OCR_BASE_URL: 'OCR 服务地址（AICHECK_OCR_BASE_URL）',
  AICHECK_REVIEW_ORCHESTRATION: '审查编排模式（AICHECK_REVIEW_ORCHESTRATION）',
  AICHECK_REVIEW_LLM_EXECUTION: 'LLM 调用模式（AICHECK_REVIEW_LLM_EXECUTION）',
  AICHECK_TASK_DISPATCH: '任务分发模式（AICHECK_TASK_DISPATCH）',
  '/internal/ocr/doctor': 'OCR 运行体检接口（/internal/ocr/doctor）',
  'ocr.runtime-doctor': 'OCR 运行体检',
  'ocr.base-url': 'OCR 服务地址',
  compliance_review_agent: '资料合规复核员',
  engineering_table_photo: '工程表格照片',
  engineering_document: '通用工程资料',
  quality_certificate: '质量证明文件',
  ndt_report: 'NDT 检测报告',
  'deepseek-reasoner': 'DeepSeek 推理模型',
  'embedding-default': '默认本地向量模型',
  'OCR runtime doctor': 'OCR 运行体检',
  'ocr-service': 'OCR 服务',
  'API service': 'API 服务',
  'base-url': '服务地址',
  'not configured': '未配置',
  'is unavailable': '不可用',
  'Check ': '请检查 ',
  'Set ': '请配置 '
}

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const friendlyTechnicalText = (value: unknown, fallback = '-') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  const direct = friendlyTechLabel(raw, '')
  if (direct && direct !== raw) return direct
  let text = raw
  for (const [token, label] of Object.entries(technicalTextTokenMap).sort(
    (left, right) => right[0].length - left[0].length
  )) {
    const escaped = escapeRegExp(token)
    if (/^[a-z0-9_.-]+$/i.test(token)) {
      text = text.replace(
        new RegExp(`(^|[^A-Za-z0-9_.-])${escaped}(?=$|[^A-Za-z0-9_.-])`, 'g'),
        (_match: string, prefix: string) => `${prefix}${label}`
      )
    } else {
      text = text.replace(new RegExp(escaped, 'g'), label)
    }
  }
  for (const [token, label] of Object.entries(techLabelMap)
    .filter(([token, label]) => token.length >= 4 && label !== token && /[_@.-]|[A-Z]/.test(token))
    .sort((left, right) => right[0].length - left[0].length)) {
    const escaped = escapeRegExp(token)
    if (/^[a-z0-9_.@-]+$/i.test(token)) {
      text = text.replace(
        new RegExp(`(^|[^A-Za-z0-9_.@-])${escaped}(?=$|[^A-Za-z0-9_.@-])`, 'g'),
        (_match: string, prefix: string) => `${prefix}${label}`
      )
    } else {
      text = text.replace(new RegExp(escaped, 'g'), label)
    }
  }
  text = text.replace(/\b[A-Z][A-Z0-9_]{2,}\b/g, (token) => friendlyTechLabel(token, token))
  text = text.replace(/\b[a-z]+(?:[._-][a-z0-9]+)+\b/g, (token) => {
    const label = friendlyTechLabel(token, token)
    return label === token ? token : label
  })
  return text || fallback
}

const friendlyReferenceLabel = (value: unknown, fallback = '-') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  return friendlyRuleCode(raw)
}

const friendlyIssueLabel = (value: unknown, fallback = '-') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  const techLabel = friendlyTechLabel(raw, '')
  if (techLabel && techLabel !== raw) return techLabel
  return friendlyRuleCode(raw)
}

const friendlyIssueList = (value: unknown, fallback = '-') => {
  const items = Array.isArray(value)
    ? value
    : String(value || '')
        .split(/[;；/]/)
        .map((item) => item.trim())
        .filter(Boolean)
  if (!items.length) return fallback
  return (
    items
      .map((item) => friendlyIssueLabel(item, ''))
      .filter(Boolean)
      .join('；') || fallback
  )
}

const friendlyTechList = (value: unknown, fallback = '-') => {
  const items = Array.isArray(value)
    ? value
    : String(value || '')
        .split(/[;；,/]/)
        .map((item) => item.trim())
        .filter(Boolean)
  if (!items.length) return fallback
  return items.map((item) => friendlyTechLabel(item)).join('、')
}

const friendlyToolNames = (toolCalls: unknown) => {
  const names = toRecordArray(toolCalls)
    .map((tool) => friendlyTechLabel(tool.toolName || tool.name, ''))
    .filter(Boolean)
  return names.join('，')
}

const friendlyTaskQueueLabel = (value: unknown) => {
  const raw = String(value || '').trim()
  if (!raw || raw === '-') return '-'
  const normalized = raw.toLowerCase()
  if (normalized.includes('document-intelligence')) return '文档智能服务'
  if (normalized.includes('knowledge-rule')) return '知识规则服务'
  if (normalized.includes('review-orchestrator')) return '审查编排服务'
  if (normalized.includes('litellm')) return 'LiteLLM 网关'
  if (normalized.includes('business-review')) return '业务复核'
  if (normalized.includes('temporal')) return 'Temporal 工作流'
  return raw
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
      'needs_human_confirmation',
      'needs_human_review',
      'needs_labeling',
      'low_confidence_field',
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
const ocr100ActionBoard = computed(() => ocrQuality.value?.ocr100ActionBoard || null)
const ocr100ActionSummary = computed(() => ocr100ActionBoard.value?.summary || null)
const ocr100ActionRows = computed(() => ocr100ActionBoard.value?.actions || [])
const ocr100LaneCount = (lane: string) => Number(ocr100ActionSummary.value?.laneCounts?.[lane] || 0)
const ocr100SectionRows = computed(() => ocr100Scorecard.value?.sections || [])
const ocr100BlockerRows = computed(() =>
  (ocr100Scorecard.value?.blockers || []).slice(0, 8).map((blocker, index) => ({
    id: index + 1,
    blocker: friendlyIssueLabel(blocker)
  }))
)
const ocrAnnotationSummary = computed(() => ocrAnnotation.value?.summary || null)
const ocrAnnotationRows = computed(() => ocrAnnotation.value?.page.items || [])
const ocrAnnotationBlockerRows = computed(() =>
  Object.entries(ocrAnnotationSummary.value?.blockerCounts || {}).map(([blocker, count]) => ({
    blocker: friendlyIssueLabel(blocker),
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
    label: friendlyFieldLabel(String(item.fieldCode || '字段'))
  })),
  ...annotationTables.value.map((item, index) => ({
    ...item,
    index,
    type: 'tables' as const,
    label: friendlyTechLabel(item.businessSchema, '表格')
  })),
  ...annotationSeals.value.map((item, index) => ({
    ...item,
    index,
    type: 'seals' as const,
    label: friendlyTechLabel(item.nameContains || item.sealType, '印章')
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
      scenario: friendlyTechLabel(scenario),
      ok: Boolean(item?.ok),
      total: summary?.total || summary?.cases || 0,
      passed: summary?.passed || 0,
      failed: summary?.failed || 0,
      averageScore: summary?.averageScore || 0,
      thresholdFailureCount: item?.thresholdFailures?.length || 0
    }
  })
)
const ocrQualityHeatmapDimensions = ['平均分', '通过率', '阈值门禁', '发现项控制']
const ocrQualityHeatmapRows = computed(() => {
  const scenarioRows = ocrScenarioRows.value.length
    ? ocrScenarioRows.value
    : [
        {
          scenario: 'overall',
          ok: latestOcrEvalOk.value,
          total: latestOcrEvalCaseTotal.value || ocrQuality.value?.fileLevel?.total || 0,
          passed:
            latestOcrEvalSummary.value.passed ||
            ocrQuality.value?.fileLevel?.success ||
            ocrQuality.value?.jobLevel?.success ||
            0,
          failed:
            latestOcrEvalSummary.value.failed ||
            ocrQuality.value?.fileLevel?.failed ||
            ocrQuality.value?.jobLevel?.failed ||
            0,
          averageScore:
            latestOcrEvalSummary.value.averageScore ||
            Number(toRecord(toRecord(ocrQuality.value).overview).averageConfidence || 0) ||
            0,
          thresholdFailureCount: ocrThresholdFailureRows.value.length
        }
      ]
  return scenarioRows.map((row) => {
    const total = Number(row.total || 0)
    const passed = Number(row.passed || 0)
    const failed = Number(row.failed || 0)
    const thresholdFailures = Number(row.thresholdFailureCount || 0)
    const findingCount = ocrFindingCountRows.value
      .filter((item) => item.scope === row.scenario || item.scope === 'overall')
      .reduce((sum, item) => sum + Number(item.count || 0), 0)
    return {
      scenario: friendlyTechLabel(row.scenario),
      metrics: [
        score100(row.averageScore),
        total ? score100(passed / total) : row.ok ? 100 : 0,
        Math.max(0, 100 - thresholdFailures * 25),
        Math.max(0, 100 - (failed + findingCount) * 12)
      ],
      raw: row
    }
  })
})
const ocrQualityHeatmapOption = computed<EChartsOption>(() => {
  const rows = ocrQualityHeatmapRows.value.slice(0, 8)
  const yLabels = rows.map((row) => row.scenario)
  const data = rows.flatMap((row, rowIndex) =>
    row.metrics.map((value, metricIndex) => [metricIndex, rowIndex, value])
  )
  return {
    backgroundColor: 'transparent',
    grid: { left: 92, right: 28, top: 18, bottom: 36 },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: any) => {
        const [metricIndex, rowIndex, value] = params.value || []
        return [
          `<strong>${yLabels[rowIndex] || '-'}</strong>`,
          `${ocrQualityHeatmapDimensions[metricIndex] || '-'}：${value}/100`
        ].join('<br/>')
      }
    },
    xAxis: {
      type: 'category',
      data: ocrQualityHeatmapDimensions,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dbe8f7' } },
      axisLabel: { color: '#475569', fontWeight: 800 }
    },
    yAxis: {
      type: 'category',
      data: yLabels,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#475569', fontWeight: 800, width: 76, overflow: 'truncate' }
    },
    visualMap: {
      min: 0,
      max: 100,
      show: false,
      inRange: { color: ['#fee2e2', '#fed7aa', '#bfdbfe', '#bbf7d0'] }
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: { show: true, color: '#172033', fontSize: 11, fontWeight: 900 },
        itemStyle: { borderColor: '#ffffff', borderWidth: 3, borderRadius: 6 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgb(15 23 42 / 18%)' } }
      }
    ]
  } as EChartsOption
})
const ocrThresholdFailureRows = computed(() => {
  const rows: Array<Record<string, unknown>> = []
  for (const item of latestOcrEvalCompact.value?.thresholdFailures ||
    latestOcrEvalReport.value?.thresholdFailures ||
    []) {
    rows.push({
      scope: friendlyTechLabel('overall'),
      ...item,
      metric: friendlyTechLabel(item.metric)
    })
  }
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const failure of item?.thresholdFailures || []) {
      rows.push({
        scope: friendlyTechLabel(scenario),
        ...failure,
        metric: friendlyTechLabel(failure.metric)
      })
    }
  }
  return rows
})
const ocrFindingCountRows = computed(() => {
  const rows: Array<{ scope: string; code: string; count: number }> = Object.entries(
    latestOcrEvalCompact.value?.findingCounts || latestOcrEvalReport.value?.findingCounts || {}
  ).map(([code, count]) => ({
    scope: friendlyTechLabel('overall'),
    code,
    count: Number(count || 0)
  }))
  for (const [scenario, item] of Object.entries(latestOcrScenarioMetrics.value)) {
    for (const [code, count] of Object.entries(item?.findingCounts || {})) {
      rows.push({ scope: friendlyTechLabel(scenario), code, count: Number(count || 0) })
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
        scenario: friendlyTechLabel(item.scenario),
        score: item.score || 0,
        finding:
          typeof firstFinding === 'string'
            ? friendlyIssueLabel(firstFinding)
            : friendlyTechnicalText(
                firstFinding?.message || friendlyIssueLabel(firstFinding?.code, '-')
              )
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
        return friendlyReferenceLabel(rule.ruleCode || rule.code || rule.id, '')
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
      toolNames: friendlyToolNames(toolCalls),
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
    const evidenceRefs = toRecordArray(item.evidenceRefs)
    const ruleRefs = toRecordArray(item.ruleRefs)
    const kbRefs = toRecordArray(item.kbRefs)
    const confidence = Number(item.confidence ?? 0)
    return {
      id: String(item.id || `finding-${index + 1}`),
      findingType: String(item.findingType || item.type || '-'),
      severity: String(item.severity || '-'),
      title: String(item.title || item.description || item.finding || '-'),
      confidence: Number.isNaN(confidence) ? 0 : confidence,
      evidenceCount: evidenceRefs.length,
      referenceCount: ruleRefs.length + kbRefs.length,
      requiresHumanConfirmation: Boolean(item.requiresHumanConfirmation),
      suggestedAction: String(item.suggestedAction || '-'),
      severityLabel: friendlyStatus(item.severity || '-', '-'),
      evidenceText:
        evidenceRefs.length || ruleRefs.length || kbRefs.length
          ? `${evidenceRefs.length} 个证据位置 · ${ruleRefs.length + kbRefs.length} 条规则/依据`
          : '暂无可追溯证据，需补齐后再采纳',
      humanNextAction: item.requiresHumanConfirmation
        ? '请监检员确认、修改或驳回'
        : '可作为低风险建议进入人工复核',
      suggestedActionLabel: friendlyStatus(item.suggestedAction || '-', '-')
    }
  })
)
const normalizedReviewQualityRows = computed(() =>
  (reviewQualityRows.value.length ? reviewQualityRows.value : reviewQualityGateRows.value).map(
    (row, index) => {
      const item = toRecord(row)
      return {
        id: item.name || item.dimension || item.gate || `quality-${index + 1}`,
        name: friendlyTechnicalText(
          item.name || item.dimension || item.gate || `质量项 ${index + 1}`
        ),
        status:
          item.status || (item.passed === true ? 'pass' : item.passed === false ? 'warning' : '-'),
        score: item.score,
        message: friendlyTechnicalText(item.message || item.finding || item.description || '-'),
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
      targetType: friendlyTechnicalText(item.targetType || '-'),
      correctionType: friendlyStatus(item.correctionType || item.feedbackType || '-', '-'),
      before: friendlyTechnicalText(item.before || item.original || item.beforeSummary || '-'),
      after: friendlyTechnicalText(item.after || item.corrected || item.afterSummary || '-'),
      rootCause: friendlyTechnicalText(item.rootCause || '-'),
      status: friendlyStatus(item.status || '-', '-'),
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
      stage: '流程工作流',
      status: workflowId ? '已持久化' : '缺少工作流',
      evidence: workflowId
        ? `事件 ${temporalEventCount} 个，工作流 ${workflowId}`
        : '未返回 workflowId',
      action: workflowId ? '可追踪外层长任务' : '检查 Temporal worker 和任务创建链路',
      healthy: Boolean(workflowId)
    },
    {
      stage: 'Agent 检查点',
      status: checkpointer ? friendlyTechLabel(checkpointer) : '缺少检查点',
      evidence: selectedReviewRun.value?.run.graphExecution?.persistence || '未返回持久化配置',
      action: checkpointer ? '可进行中断恢复和重放' : '启用 Agent 编排的 PostgreSQL 检查点',
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
      evidence: `规则 ${ruleCount} 条，检索溯源 ${retrievalCount} 条`,
      action: ruleCount || retrievalCount ? '抽查依据条款和章节溯源路由' : '补跑规则和知识检索节点',
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
  {
    label: '能力组合校验哈希',
    value: friendlyTechnicalText(reviewLineage.value.capabilityBundleHash)
  },
  { label: '业务类型', value: friendlyTechnicalText(reviewLineage.value.businessPackId) },
  { label: '业务类型版本', value: friendlyTechnicalText(reviewLineage.value.businessPackVersion) },
  { label: 'AI 员工', value: friendlyTechnicalText(reviewLineage.value.agentId) },
  { label: 'AI 员工版本', value: friendlyTechnicalText(reviewLineage.value.agentVersion) },
  { label: '提示词版本', value: friendlyTechnicalText(reviewLineage.value.promptVersion) },
  { label: '模型网关', value: friendlyTechnicalText(reviewLineage.value.modelGateway) },
  { label: '模型别名', value: friendlyTechnicalText(reviewLineage.value.modelAlias) },
  { label: '规则版本', value: friendlyTechnicalText(reviewLineage.value.ruleSetVersion) },
  { label: '知识库版本', value: friendlyTechnicalText(reviewLineage.value.kbVersion) },
  { label: '输入资料版本', value: reviewLineage.value.inputDocumentVersionIds },
  { label: 'OCR 结果版本', value: reviewLineage.value.ocrResultVersions },
  { label: '输入校验哈希', value: reviewLineage.value.inputHash },
  { label: '输出校验哈希', value: reviewLineage.value.outputHash }
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
  { label: '检索溯源', value: recordNumber(reviewArtifactSummary.value, 'retrievalTraces') },
  { label: '章节溯源', value: recordNumber(reviewArtifactSummary.value, 'pageIndexTraces') },
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
    return '暂无可审计审查任务。请先从业务审查流程触发 AI 复核，或确认本地开发态已启用 Agent 编排。'
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
const agentStatusCards = computed<
  Array<{
    key: AgentSubpage
    label: string
    title: string
    value: string
    hint: string
    tone: FdeTone
  }>
>(() => [
  {
    key: 'runs',
    label: '任务',
    title: '有没有可审查任务',
    value: String(reviewRuns.value.length),
    hint: hasReviewRuns.value ? '可追踪任务' : '等待业务触发',
    tone: hasReviewRuns.value ? 'green' : 'orange'
  },
  {
    key: 'reasoning',
    label: '决策',
    title: '为什么这么判断',
    value: selectedReviewRun.value
      ? reviewQualityEvaluation.value.status === 'pass'
        ? '可审查'
        : '需复核'
      : '无任务',
    hint: selectedReviewRun.value
      ? `${normalizedReviewReasoningRows.value.length} 步摘要`
      : '未选中 Run',
    tone: selectedReviewRun.value
      ? reviewQualityEvaluation.value.status === 'pass'
        ? 'green'
        : 'orange'
      : 'orange'
  },
  {
    key: 'quality',
    label: '质量',
    title: '能不能进入复核',
    value: String(reviewQualityGateRows.value.length),
    hint: `${normalizedReviewHumanCorrectionRows.value.length} 条人工修正`,
    tone: reviewQualityRows.value.some((row) => row.status !== 'pass') ? 'red' : 'green'
  },
  {
    key: 'trace',
    label: '溯源',
    title: '底层链路是否完整',
    value: String(reviewGraphNodes.value.length),
    hint: `${selectedReviewTemporal.value.eventCount || reviewGraphTimeline.value.length || 0} 个事件`,
    tone: reviewGraphNodes.value.length ? 'blue' : 'orange'
  }
])
const selectedAgentStatusCard = computed(
  () =>
    agentStatusCards.value.find((card) => card.key === agentSubpage.value) ||
    agentStatusCards.value[0]
)
const agentEmptyGuideRows = computed(() => [
  {
    label: '当前状态',
    value: '没有审查任务，AI 判断依据、质量评估、人工修正和溯源快照暂不可用。'
  },
  {
    label: '如何触发任务',
    value:
      '从监检员审查页面发起 AI 复核；本地开发态需启用审查编排服务、流程引擎和 Agent 编排图后再刷新。'
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
    return `${friendlyTechnicalText(firstRuntimeIssue.value.name, '运行时问题')}：${shortText(
      friendlyTechnicalText(firstRuntimeIssue.value.message, '-'),
      '-'
    )}`
  }
  const ocr100Blocker = ocr100Scorecard.value?.blockers?.[0]
  if (ocr100Blocker) return friendlyIssueLabel(ocr100Blocker)
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
    hint: `${ocrRuntimeDoctor.value?.summary?.fail || 0} 失败 / ${
      ocrRuntimeDoctor.value?.summary?.warn || 0
    } 告警`,
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
const ocr100ActionCards = computed(() => [
  {
    label: '行动项',
    value: String(ocr100ActionSummary.value?.actions || 0),
    hint: friendlyStatus(ocr100ActionSummary.value?.status, '未生成'),
    tone: ocr100ActionSummary.value?.actions || 0 ? ('orange' as const) : ('green' as const)
  },
  {
    label: '采样',
    value: String(ocr100LaneCount('collect_samples')),
    hint: `缺 ${ocr100ActionSummary.value?.collectionMissingCases || 0} 份`,
    tone: ocr100LaneCount('collect_samples') ? ('red' as const) : ('green' as const)
  },
  {
    label: '标注',
    value: String(ocr100LaneCount('label_existing')),
    hint: `待人审 ${ocr100ActionSummary.value?.remainingHumanLabels || 0}`,
    tone: ocr100LaneCount('label_existing') ? ('orange' as const) : ('green' as const)
  },
  {
    label: '本地候选',
    value: String(ocr100ActionSummary.value?.newLocalCandidates || 0),
    hint: `重复 ${ocr100ActionSummary.value?.duplicateLocalCandidates || 0}`,
    tone:
      ocr100ActionSummary.value?.newLocalCandidates || 0 ? ('blue' as const) : ('green' as const)
  }
])
const ocrTopBlockerRows = computed<OcrTopBlockerRow[]>(() => {
  const rows: Array<Omit<OcrTopBlockerRow, 'id'>> = []
  for (const item of ocrRuntimeDoctor.value?.topIssues || []) {
    rows.push({
      source: '运行时',
      blocker: `${friendlyTechnicalText(item.name, '运行时问题')}：${shortText(
        friendlyTechnicalText(item.message, '-'),
        '-'
      )}`,
      action: '先修复本地 OCR 引擎、模型路径或 OCR 服务地址。'
    })
  }
  for (const blocker of ocr100Scorecard.value?.blockers || []) {
    rows.push({
      source: 'OCR 100',
      blocker: friendlyIssueLabel(blocker),
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
const ocr100ActionLaneLabel = (lane: unknown) => {
  const key = String(lane || '')
  if (key === 'collect_samples') return '采样'
  if (key === 'label_existing') return '标注'
  if (key === 'triage_candidates') return '候选'
  if (key === 'release_eval') return '导出'
  if (key === 'scorecard') return '评分'
  return friendlyStatus(key, '行动')
}
type Ocr100ActionBoardRow = {
  id: string
  taskId: string
  caseId: string
  lane: string
  laneLabel: string
  scenario: string
  title: string
  detailText: string
  sourcePath: string
  dropDirectory: string
  missingCases: number
  checklistText: string
  blockersText: string
  humanActionsText: string
  doneWhen: string
  canOpenAnnotation: boolean
}
type OcrTopBlockerRow = {
  id: number
  source: string
  blocker: string
  action: string
}
const ocr100ActionBoardRows = computed<Ocr100ActionBoardRow[]>(() =>
  ocr100ActionRows.value.map((row) => {
    const item = toRecord(row)
    const lane = String(item.lane || '')
    const taskId = String(item.taskId || item.caseId || '')
    const caseId = String(item.caseId || '')
    const scenario = String(item.scenario || '')
    const checklist = Array.isArray(item.checklist) ? item.checklist : []
    const dropDirectory = String(item.dropDirectory || '')
    const sourcePath = String(item.sourcePath || '')
    const missingCases = Number(item.missingCases || 0)
    const checklistText = checklist.slice(0, 2).join(' / ') || '按场景 README 标注'
    const blockers = Array.isArray(item.blockers) ? item.blockers : []
    const blockersText = friendlyIssueList(blockers.slice(0, 2), '待人工校对')
    const humanActions = Array.isArray(item.humanActions) ? item.humanActions : []
    const detailText =
      lane === 'collect_samples'
        ? `缺 ${missingCases} 份 · ${dropDirectory || '待生成采样目录'} · ${checklistText}`
        : lane === 'label_existing'
          ? `${sourcePath || caseId || taskId} · ${blockersText}`
          : String(item.doneWhen || '')
    return {
      id: String(item.id || item.caseId || item.title || ''),
      taskId,
      caseId,
      lane,
      scenario,
      title: String(item.title || '-'),
      detailText,
      sourcePath,
      dropDirectory,
      missingCases,
      checklistText: checklist.join('; '),
      blockersText: friendlyIssueList(blockers, ''),
      humanActionsText: humanActions.join('; '),
      doneWhen: String(item.doneWhen || ''),
      laneLabel: ocr100ActionLaneLabel(lane),
      canOpenAnnotation: lane === 'label_existing' && Boolean(taskId)
    }
  })
)
const ocr100ActionBoardView = computed<{
  cards: Array<{ label: string; value: string; hint: string; tone: string }>
  rows: Ocr100ActionBoardRow[]
}>(() => ({
  cards: ocr100ActionCards.value,
  rows: ocr100ActionBoardRows.value.slice(0, 6)
}))
const ocr100Handoff = computed(() => toRecord(ocr100ActionBoard.value?.handoff))
const ocr100HandoffFiles = computed(() =>
  toRecordArray(ocr100Handoff.value.files).map((file) => ({
    key: String(file.key || ''),
    label: String(file.label || file.key || '-'),
    owner: String(file.owner || 'FDE'),
    purpose: String(file.purpose || ''),
    path: String(file.path || ''),
    exists: Boolean(file.exists),
    sizeBytes: Number(file.sizeBytes || 0)
  }))
)
const ocr100HandoffVisibleFiles = computed(() => ocr100HandoffFiles.value.slice(0, 5))
const ocr100HandoffStaleReasons = computed(() => toRecordArray(ocr100Handoff.value.staleReasons))
const ocr100HandoffStatusType = computed<FdeElTagType>(() => {
  const status = String(ocr100Handoff.value.status || '')
  if (status === 'ready') return 'success'
  if (status === 'missing') return 'danger'
  return 'warning'
})
const ocr100HandoffHint = computed(() => {
  const status = String(ocr100Handoff.value.status || '')
  if (status === 'stale') {
    const reason = ocr100HandoffStaleReasons.value[0]
    const field = String(reason?.field || '行动板')
    return `交付包与当前行动板不同步：${field} 已变化，请重新生成 handoff。`
  }
  if (status === 'incomplete') return '部分交付文件缺失，请重新生成 handoff。'
  if (status === 'missing') return '尚未生成交付包，请运行 action board handoff 命令。'
  return ''
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
const ocrSubpageItems = computed(() => [
  {
    key: 'overview' as const,
    label: '当前状态',
    description: '服务、阻断、待修样本和发布分数。'
  },
  {
    key: 'capability-test' as const,
    label: '在线测 OCR',
    description: '上传临时 PDF/图片，查看识别结果。'
  },
  {
    key: 'annotation' as const,
    label: '修识别结果',
    description: '修字段、表格、印章和证据框。'
  },
  {
    key: 'runtime' as const,
    label: '查失败原因',
    description: '看任务、引擎耗时、错误和诊断。'
  },
  {
    key: 'evaluation' as const,
    label: '发布评测',
    description: '用回归样本确认能不能上线。'
  }
])
const ocrStatusDialogTitle = computed(() => {
  if (ocrStatusDialogType.value === 'issue') return '当前问题明细'
  if (ocrStatusDialogType.value === 'annotation') return '待人工修正明细'
  if (ocrStatusDialogType.value === 'runtime') return 'OCR 服务与运行诊断'
  if (ocrStatusDialogType.value === 'quality') return 'OCR 质量统计'
  return '发布评测明细'
})
const ocrStatusDialogHint = computed(() => {
  if (ocrStatusDialogType.value === 'issue') return '这里集中展示当前最需要先处理的阻断项。'
  if (ocrStatusDialogType.value === 'annotation')
    return '这里展示需要人工补字段、表格、印章或证据框的样本。'
  if (ocrStatusDialogType.value === 'runtime')
    return '这里用于判断 OCR 服务、模型路径和任务运行是否正常。'
  if (ocrStatusDialogType.value === 'quality')
    return '这里只放整体质量指标，日常在线测试不需要先看。'
  return '这里用于判断 OCR 结果能否作为发布或交付基线。'
})
const ocrInlineStatusTitle = computed(() => {
  if (selectedOcrStatusTab.value === 'issue') return '当前问题'
  if (selectedOcrStatusTab.value === 'annotation') return '待人工修正'
  if (selectedOcrStatusTab.value === 'runtime') return '服务诊断'
  return '发布评测'
})
const ocrInlineStatusHint = computed(() => {
  if (selectedOcrStatusTab.value === 'issue')
    return '先看阻断项和对应处理动作，避免被其它指标分散注意力。'
  if (selectedOcrStatusTab.value === 'annotation')
    return '只列需要人工确认的样本；点击行可以直接进入标注。'
  if (selectedOcrStatusTab.value === 'runtime')
    return '用于判断 OCR 服务地址、运行任务和错误原因是否正常。'
  return '用于判断当前 OCR 结果能不能作为发布或交付基线。'
})
const ocrSecondaryTools = computed<
  Array<{
    key: OcrSecondaryTool
    label: string
    description: string
    stat: string
    tone: 'blue' | 'green' | 'orange' | 'red'
  }>
>(() => [
  {
    key: 'annotation',
    label: '样本标注',
    description: '修 OCR 错误，补字段、表格、印章和证据框。',
    stat: `${ocrAnnotationRows.value.length} 条`,
    tone: ocrPendingAnnotationCount.value ? 'orange' : 'green'
  },
  {
    key: 'runtime',
    label: '运行诊断',
    description: '排查服务地址、模型路径、引擎耗时和任务失败。',
    stat: `${ocrRuntimeDoctor.value?.summary?.fail || 0} 失败`,
    tone: ocrRuntimeDoctor.value?.ok ? 'green' : 'red'
  },
  {
    key: 'release',
    label: '发布评测',
    description: '用回归样本判断这版 OCR 能不能上线交付。',
    stat: ocr100Scorecard.value
      ? `${ocr100Scorecard.value.score}/${ocr100Scorecard.value.targetScore}`
      : '待评估',
    tone: ocr100Scorecard.value?.ok ? 'green' : 'orange'
  },
  {
    key: 'quality',
    label: '质量统计',
    description: '查看成功率、低置信字段、表格和印章整体指标。',
    stat: `${ocrQuality.value?.fieldLevel?.lowConfidence || 0} 低置信`,
    tone: Number(ocrQuality.value?.fieldLevel?.lowConfidence || 0) ? 'orange' : 'green'
  }
])

const selectedOcrCapabilityRun = computed(() => selectedOcrCapabilityTest.value?.run || null)
const selectedOcrCapabilityParseResult = computed(
  () => selectedOcrCapabilityTest.value?.parseResult || null
)
const selectedOcrCapabilityPreview = computed(
  () => selectedOcrCapabilityTest.value?.preview || null
)
const resolveOcrCapabilityPreviewType = (file?: File | null) => {
  const text = `${file?.type || ''} ${file?.name || ''}`.toLowerCase()
  if (/pdf/.test(text)) return 'pdf'
  if (/image|png|jpe?g|webp|gif/.test(text)) return 'image'
  return 'unsupported'
}
const selectedOcrCapabilityPreviewSource = computed(() => {
  if (selectedOcrCapabilityPreview.value?.url) {
    return selectedOcrCapabilityPreview.value
  }
  if (ocrCapabilityLocalPreviewUrl.value) {
    return {
      url: ocrCapabilityLocalPreviewUrl.value,
      previewType: resolveOcrCapabilityPreviewType(ocrCapabilityTestFile.value),
      fileName: ocrCapabilityTestFile.value?.name
    }
  }
  return null
})
const stringifyOcrCapabilityText = (value: unknown): string => {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) {
    return value
      .map((item) => stringifyOcrCapabilityText(item))
      .filter(Boolean)
      .join('\n')
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    return stringifyOcrCapabilityText(
      record.text ??
        record.fullText ??
        record.rawText ??
        record.plainText ??
        record.content ??
        record.value ??
        record.fieldValue ??
        record.ocrText
    )
  }
  return ''
}
const selectedOcrCapabilitySummary = computed(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const runSummary = selectedOcrCapabilityRun.value?.resultSummary || {}
  const quality = (result.quality as Record<string, unknown> | undefined) || {}
  return {
    pages: Number(runSummary.pages ?? (Array.isArray(result.pages) ? result.pages.length : 0)),
    fields: Number(runSummary.fields ?? (Array.isArray(result.fields) ? result.fields.length : 0)),
    tables: Number(runSummary.tables ?? (Array.isArray(result.tables) ? result.tables.length : 0)),
    seals: Number(runSummary.seals ?? (Array.isArray(result.seals) ? result.seals.length : 0)),
    fragments: Number(
      runSummary.fragments ?? (Array.isArray(result.fragments) ? result.fragments.length : 0)
    ),
    diagnostics: Number(
      runSummary.diagnostics ?? (Array.isArray(result.diagnostics) ? result.diagnostics.length : 0)
    ),
    qualityStatus: String(runSummary.qualityStatus || quality.status || 'unknown'),
    confidence: Number(runSummary.overallConfidence ?? quality.overallConfidence ?? 0)
  }
})
const selectedOcrCapabilityFields = computed(() => {
  const fields = selectedOcrCapabilityParseResult.value?.fields
  return Array.isArray(fields) ? (fields as Array<Record<string, unknown>>).slice(0, 80) : []
})
const selectedOcrCapabilityTables = computed(() => {
  const tables = selectedOcrCapabilityParseResult.value?.tables
  return Array.isArray(tables) ? (tables as Array<Record<string, unknown>>).slice(0, 40) : []
})
const selectedOcrCapabilitySeals = computed(() => {
  const seals = selectedOcrCapabilityParseResult.value?.seals
  return Array.isArray(seals) ? (seals as Array<Record<string, unknown>>).slice(0, 40) : []
})
const selectedOcrCapabilityDiagnostics = computed(() => {
  const diagnostics =
    selectedOcrCapabilityParseResult.value?.diagnostics ||
    selectedOcrCapabilityRun.value?.diagnostics
  return Array.isArray(diagnostics) ? diagnostics.slice(0, 40) : []
})

type OcrCapabilityRoiTone = 'blue' | 'green' | 'orange' | 'red' | 'purple'

type OcrCapabilityRoi = {
  id: string
  type: string
  tone: OcrCapabilityRoiTone
  pageNo: number
  label: string
  text: string
  bbox: [number, number, number, number]
  confidence?: number
  source?: string
}

type OcrCapabilityStructuredRow = {
  id: string
  pageNo: number
  type: string
  name: string
  value: string
  bboxText: string
  confidence?: number
  source: string
}

type OcrCapabilitySealDisplayRow = {
  id: string
  title: string
  colorLabel: string
  typeLabel: string
  status: string
  tagType: 'success' | 'warning' | 'danger' | 'info'
  pageNo: number
  bboxText: string
  confidence?: number
  source: string
  contentLines: string[]
  meta: Array<{ label: string; value: string }>
}

type OcrCapabilityTablePreview = {
  id: string
  title: string
  meta: Array<{ label: string; value: string }>
  columns: Array<{ key: string; label: string }>
  rows: Array<{ id: string; cells: Record<string, string> }>
}

const ocrCapabilityRoiToneTypeMap: Record<
  OcrCapabilityRoiTone,
  'primary' | 'success' | 'warning' | 'danger' | 'info'
> = {
  blue: 'primary',
  green: 'success',
  orange: 'warning',
  red: 'danger',
  purple: 'info'
}

const normalizeOcrCapabilityBbox = (bbox: unknown): [number, number, number, number] | null => {
  if (!Array.isArray(bbox) || bbox.length < 4) return null
  let values: number[] = []
  if (Array.isArray(bbox[0])) {
    const points = bbox
      .filter((point): point is unknown[] => Array.isArray(point) && point.length >= 2)
      .map((point) => [Number(point[0]), Number(point[1])])
      .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
    if (!points.length) return null
    const xs = points.map(([x]) => x)
    const ys = points.map(([, y]) => y)
    values = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  } else {
    values = bbox.slice(0, 4).map((value) => Number(value))
  }
  if (values.some((value) => !Number.isFinite(value))) return null
  const [rawX1, rawY1, rawX2, rawY2] = values
  const x1 = Math.min(rawX1, rawX2)
  const y1 = Math.min(rawY1, rawY2)
  const x2 = Math.max(rawX1, rawX2)
  const y2 = Math.max(rawY1, rawY2)
  if (x2 <= x1 || y2 <= y1) return null
  return [x1, y1, x2, y2]
}

const ocrCapabilityRoiText = (record: Record<string, unknown>) =>
  stringifyOcrCapabilityText(
    record.text ??
      record.fullText ??
      record.fieldValue ??
      record.value ??
      record.sealName ??
      record.sealType ??
      record.label ??
      record.type
  )

const ocrCapabilityStructuredValue = (record: Record<string, unknown>) =>
  stringifyOcrCapabilityText(
    record.fieldValue ??
      record.value ??
      record.text ??
      record.fullText ??
      record.rawText ??
      record.content ??
      record.sealName ??
      record.sealType ??
      record.tableName ??
      record.label
  )

const ocrCapabilityTableSummary = (record: Record<string, unknown>) => {
  const rowCount = Number(record.rowCount ?? record.rows ?? 0)
  const columnCount = Number(record.columnCount ?? record.columns ?? 0)
  const cellCount = Array.isArray(record.cells) ? record.cells.length : 0
  const parts = [
    rowCount ? `${rowCount} 行` : '',
    columnCount ? `${columnCount} 列` : '',
    cellCount ? `${cellCount} 单元格` : ''
  ].filter(Boolean)
  return parts.join(' / ') || ocrCapabilityStructuredValue(record) || '表格结构'
}

const cleanOcrCapabilityTableText = (value: unknown) =>
  stringifyOcrCapabilityText(value)
    .replace(/\s*\n+\s*/g, ' / ')
    .replace(/\s+/g, ' ')
    .trim()

const uniqueOcrCapabilityTableKey = (base: string, used: Set<string>) => {
  let key = base || `col_${used.size + 1}`
  let index = 2
  while (used.has(key)) {
    key = `${base}_${index}`
    index += 1
  }
  used.add(key)
  return key
}

const createOcrCapabilityTablePreviewFromCells = (
  record: Record<string, unknown>,
  index: number
): OcrCapabilityTablePreview | null => {
  const cells = Array.isArray(record.cells) ? (record.cells as Array<Record<string, unknown>>) : []
  if (!cells.length) return null
  const rowIndexes = Array.from(
    new Set(cells.map((cell) => Number(cell.row ?? cell.rowIndex ?? 0)).filter(Number.isFinite))
  ).sort((left, right) => left - right)
  const colIndexes = Array.from(
    new Set(
      cells
        .map((cell) => Number(cell.col ?? cell.column ?? cell.colIndex ?? 0))
        .filter(Number.isFinite)
    )
  ).sort((left, right) => left - right)
  if (!rowIndexes.length || !colIndexes.length) return null
  const headerRow =
    rowIndexes.find((rowIndex) =>
      cells.some((cell) => Number(cell.row ?? cell.rowIndex ?? 0) === rowIndex && cell.isHeader)
    ) ?? rowIndexes[0]
  const cellText = (rowIndex: number, colIndex: number) =>
    cleanOcrCapabilityTableText(
      cells.find(
        (cell) =>
          Number(cell.row ?? cell.rowIndex ?? 0) === rowIndex &&
          Number(cell.col ?? cell.column ?? cell.colIndex ?? 0) === colIndex
      )?.text
    )
  const usedKeys = new Set<string>()
  const columns = colIndexes.slice(0, 14).map((colIndex, columnIndex) => {
    const label = cellText(headerRow, colIndex) || `列 ${columnIndex + 1}`
    return {
      key: uniqueOcrCapabilityTableKey(`col_${colIndex}`, usedKeys),
      label
    }
  })
  const dataRows = rowIndexes
    .filter((rowIndex) => rowIndex !== headerRow)
    .map((rowIndex) => {
      const cellsByKey: Record<string, string> = {}
      columns.forEach((column, columnIndex) => {
        cellsByKey[column.key] = cellText(rowIndex, colIndexes[columnIndex])
      })
      return {
        id: `${record.tableId || 'table'}-${index}-${rowIndex}`,
        cells: cellsByKey
      }
    })
    .filter((row) => Object.values(row.cells).some(Boolean))
    .slice(0, 30)
  if (!dataRows.length) return null
  return {
    id: String(record.tableId || `table-${index + 1}`),
    title: String(record.tableName || record.tableId || `表格 ${index + 1}`),
    meta: [
      { label: '规模', value: ocrCapabilityTableSummary(record) },
      {
        label: '置信度',
        value:
          record.structureConfidence === undefined
            ? '-'
            : scorePercent(Number(record.structureConfidence))
      },
      { label: '来源', value: String(record.sourceEngine || '-') },
      { label: '位置', value: ocrCapabilityBboxText(record.bbox) }
    ],
    columns,
    rows: dataRows
  }
}

const createOcrCapabilityTablePreviewFromRows = (
  record: Record<string, unknown>,
  index: number
): OcrCapabilityTablePreview | null => {
  const rows = Array.isArray(record.normalizedRows)
    ? (record.normalizedRows as Array<Record<string, unknown>>)
    : []
  const data = rows.filter((row) => row && typeof row === 'object').slice(0, 30)
  if (!data.length) return null
  const keys = Array.from(new Set(data.flatMap((row) => Object.keys(row)))).slice(0, 14)
  if (!keys.length) return null
  return {
    id: String(record.tableId || `table-${index + 1}`),
    title: String(record.tableName || record.tableId || `表格 ${index + 1}`),
    meta: [
      { label: '规模', value: ocrCapabilityTableSummary(record) },
      {
        label: '置信度',
        value:
          record.structureConfidence === undefined
            ? '-'
            : scorePercent(Number(record.structureConfidence))
      },
      { label: '来源', value: String(record.sourceEngine || '-') },
      { label: '位置', value: ocrCapabilityBboxText(record.bbox) }
    ],
    columns: keys.map((key) => ({ key, label: key })),
    rows: data.map((row, rowIndex) => ({
      id: `${record.tableId || 'table'}-${index}-${rowIndex}`,
      cells: Object.fromEntries(keys.map((key) => [key, cleanOcrCapabilityTableText(row[key])]))
    }))
  }
}

const createOcrCapabilityTablePreview = (
  record: Record<string, unknown>,
  index: number
): OcrCapabilityTablePreview | null =>
  createOcrCapabilityTablePreviewFromCells(record, index) ||
  createOcrCapabilityTablePreviewFromRows(record, index)

const selectedOcrCapabilityTablePreviews = computed<OcrCapabilityTablePreview[]>(() =>
  selectedOcrCapabilityTables.value
    .map((table, index) => createOcrCapabilityTablePreview(table, index))
    .filter((table): table is OcrCapabilityTablePreview => Boolean(table))
)

const ocrCapabilityBboxText = (bbox: unknown) => {
  const normalized = normalizeOcrCapabilityBbox(bbox)
  return normalized ? normalized.map((value) => Math.round(value * 100) / 100).join(', ') : '-'
}

const normalizeOcrCapabilityTextLines = (value: unknown): string[] =>
  stringifyOcrCapabilityText(value)
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)

const uniqueOcrCapabilityLines = (lines: string[]) => {
  const seen = new Set<string>()
  return lines.filter((line) => {
    const key = line.replace(/\s+/g, '').toLowerCase()
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

const isOcrCapabilityPlaceholderSealName = (value: unknown) => {
  const text = String(value || '').trim()
  return !text || text === '视觉印章候选' || text === '视觉蓝章候选' || /^visual_/i.test(text)
}

const ocrCapabilitySealColorLabel = (record: Record<string, unknown>) => {
  const text =
    `${record.visualColor || ''} ${record.sealType || ''} ${record.sealName || ''}`.toLowerCase()
  if (text.includes('blue')) return '蓝章'
  if (text.includes('red')) return '红章'
  const colorField = Array.isArray(record.fields)
    ? (record.fields as Array<Record<string, unknown>>).find((field) =>
        String(field.fieldName || '').includes('颜色')
      )
    : null
  const colorText = String(colorField?.fieldValue || '').toLowerCase()
  if (colorText.includes('blue')) return '蓝章'
  if (colorText.includes('red')) return '红章'
  return '印章'
}

const ocrCapabilitySealTypeLabel = (record: Record<string, unknown>) => {
  const type = String(record.sealType || '').toLowerCase()
  if (type.includes('blue')) return '蓝色印章候选'
  if (type.includes('red')) return '红色印章候选'
  if (type.includes('candidate')) return '印章候选'
  return String(record.sealType || record.type || '印章')
}

const ocrCapabilitySealFieldLines = (record: Record<string, unknown>) => {
  const fields = Array.isArray(record.fields)
    ? (record.fields as Array<Record<string, unknown>>)
    : []
  return fields.flatMap((field) => {
    const name = String(field.fieldName || field.fieldCode || field.name || '').trim()
    const value = stringifyOcrCapabilityText(field.fieldValue ?? field.value ?? field.text).trim()
    if (!value || name.includes('颜色') || name === '印章原文') return []
    return [`${name || '字段'}：${value}`]
  })
}

const ocrCapabilityBboxOverlapRatio = (
  first: [number, number, number, number],
  second: [number, number, number, number]
) => {
  const left = Math.max(first[0], second[0])
  const top = Math.max(first[1], second[1])
  const right = Math.min(first[2], second[2])
  const bottom = Math.min(first[3], second[3])
  const width = Math.max(0, right - left)
  const height = Math.max(0, bottom - top)
  const overlap = width * height
  if (!overlap) return 0
  const firstArea = (first[2] - first[0]) * (first[3] - first[1])
  const secondArea = (second[2] - second[0]) * (second[3] - second[1])
  return overlap / Math.max(1, Math.min(firstArea, secondArea))
}

const ocrCapabilityBboxCenterInside = (
  inner: [number, number, number, number],
  outer: [number, number, number, number]
) => {
  const centerX = (inner[0] + inner[2]) / 2
  const centerY = (inner[1] + inner[3]) / 2
  return centerX >= outer[0] && centerX <= outer[2] && centerY >= outer[1] && centerY <= outer[3]
}

const ocrCapabilityRoiArea = (bbox: [number, number, number, number]) =>
  Math.max(0, bbox[2] - bbox[0]) * Math.max(0, bbox[3] - bbox[1])

const ocrCapabilityRoiOverlapRatio = (first: OcrCapabilityRoi, second: OcrCapabilityRoi) =>
  ocrCapabilityBboxOverlapRatio(first.bbox, second.bbox)

const ocrCapabilitySealRoiHasTextEvidence = (source: Record<string, unknown>) => {
  const text = stringifyOcrCapabilityText(
    source.text ?? source.fullText ?? source.rawText ?? source.content ?? source.sealName
  ).replace(/\s+/g, '')
  if (/专用章|印章|许可|单位名称|业务范围|资质证书|有效期|有限公司|TS\d+/i.test(text)) {
    return true
  }
  const fields = Array.isArray(source.fields)
    ? (source.fields as Array<Record<string, unknown>>)
    : []
  return fields.some((field) => {
    const name = String(field.fieldName || field.fieldCode || '').trim()
    const value = stringifyOcrCapabilityText(field.fieldValue ?? field.value ?? field.text).replace(
      /\s+/g,
      ''
    )
    return (
      name !== '印章颜色' &&
      /专用章|印章|许可|单位名称|业务范围|资质证书|有效期|有限公司|TS\d+/i.test(value)
    )
  })
}

const shouldKeepOcrCapabilityRoi = (source: Record<string, unknown>, roi: OcrCapabilityRoi) => {
  if (roi.type !== '印章') return true
  const flags = Array.isArray(source.qualityFlags) ? source.qualityFlags.map(String) : []
  const candidateOnly =
    flags.includes('visual_candidate_only') ||
    flags.includes('requires_seal_ocr_text') ||
    source.candidateOnly === true
  if (!candidateOnly) return true
  return ocrCapabilitySealRoiHasTextEvidence(source)
}

const dedupeOcrCapabilityRois = (items: OcrCapabilityRoi[]) => {
  const sorted = [...items].sort((left, right) => {
    const typeWeight = (roi: OcrCapabilityRoi) =>
      roi.type === '表格' ? 4 : roi.type === '字段' ? 3 : roi.type === '印章' ? 2 : 1
    const textWeight = (roi: OcrCapabilityRoi) => (roi.text ? 1 : 0)
    return (
      typeWeight(right) - typeWeight(left) ||
      textWeight(right) - textWeight(left) ||
      ocrCapabilityRoiArea(right.bbox) - ocrCapabilityRoiArea(left.bbox)
    )
  })
  const kept: OcrCapabilityRoi[] = []
  sorted.forEach((roi) => {
    const duplicate = kept.some(
      (existing) =>
        existing.pageNo === roi.pageNo &&
        existing.type === roi.type &&
        ocrCapabilityRoiOverlapRatio(existing, roi) >= 0.68
    )
    if (!duplicate) kept.push(roi)
  })
  return kept.sort((left, right) => left.pageNo - right.pageNo || left.bbox[1] - right.bbox[1])
}

const createOcrCapabilityStructuredRow = (
  source: Record<string, unknown>,
  type: string,
  index: number,
  fallbackName: string
): OcrCapabilityStructuredRow | null => {
  const rawName =
    source.fieldName ||
    source.fieldCode ||
    source.name ||
    source.tableId ||
    source.sealName ||
    source.sealType ||
    source.type ||
    source.label ||
    fallbackName
  const name =
    type === '字段'
      ? friendlyFieldLabel(String(rawName || fallbackName))
      : String(rawName || fallbackName)
  const value =
    type === '表格' ? ocrCapabilityTableSummary(source) : ocrCapabilityStructuredValue(source)
  if (!value && !source.bbox) return null
  return {
    id: `${type}-${source.id || source.fragmentId || source.fieldCode || source.tableId || source.sealId || index}`,
    pageNo: Number(source.pageNo || 1),
    type,
    name,
    value,
    bboxText: ocrCapabilityBboxText(source.bbox),
    confidence:
      source.confidence !== undefined || source.ocrConfidence !== undefined
        ? Number(source.confidence ?? source.ocrConfidence)
        : undefined,
    source: String(source.sourceEngine || source.source || source.extractionMethod || '-')
  }
}

const createOcrCapabilityRoi = (
  source: Record<string, unknown>,
  type: string,
  tone: OcrCapabilityRoiTone,
  index: number,
  fallbackLabel: string
): OcrCapabilityRoi | null => {
  const bbox = normalizeOcrCapabilityBbox(source.bbox)
  if (!bbox) return null
  const rawLabel =
    source.fieldName ||
    source.fieldCode ||
    source.sealName ||
    source.sealType ||
    source.tableId ||
    source.type ||
    source.label ||
    fallbackLabel
  const label =
    type === '字段'
      ? friendlyFieldLabel(String(rawLabel || fallbackLabel))
      : String(rawLabel || fallbackLabel)
  return {
    id: `${type}-${source.id || source.fragmentId || source.fieldCode || source.tableId || source.sealId || index}`,
    type,
    tone,
    pageNo: Number(source.pageNo || 1),
    label,
    text: ocrCapabilityRoiText(source),
    bbox,
    confidence:
      source.confidence !== undefined || source.ocrConfidence !== undefined
        ? Number(source.confidence ?? source.ocrConfidence)
        : undefined,
    source: String(source.sourceEngine || source.source || '')
  }
}

const selectedOcrCapabilityRawRois = computed<OcrCapabilityRoi[]>(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const seen = new Set<string>()
  const rows: OcrCapabilityRoi[] = []
  const pushRows = (
    value: unknown,
    type: string,
    tone: OcrCapabilityRoiTone,
    labelPrefix: string
  ) => {
    if (!Array.isArray(value)) return
    value.forEach((item, index) => {
      if (!item || typeof item !== 'object') return
      const roi = createOcrCapabilityRoi(
        item as Record<string, unknown>,
        type,
        tone,
        index + 1,
        `${labelPrefix} ${index + 1}`
      )
      if (!roi) return
      if (!shouldKeepOcrCapabilityRoi(item as Record<string, unknown>, roi)) return
      const key = `${roi.type}-${roi.pageNo}-${roi.bbox.map((point) => Math.round(point)).join(',')}`
      if (seen.has(key)) return
      seen.add(key)
      rows.push(roi)
    })
  }
  pushRows(result.seals, '印章', 'red', '印章')
  pushRows(result.tables, '表格', 'orange', '表格')
  pushRows(result.fields, '字段', 'green', '字段')
  pushRows(result.layoutBlocks, '版面', 'purple', '版面')
  pushRows(result.fragments, '文字', 'blue', '文字')
  return dedupeOcrCapabilityRois(rows).slice(0, 80)
})

const selectedOcrCapabilityRoiPageSize = computed(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const pages = Array.isArray(result.pages) ? (result.pages as Array<Record<string, unknown>>) : []
  const page = pages.find((item) => Number(item.pageNo || 1) === 1) || pages[0] || {}
  const width = Number(
    page.width || page.pageWidth || page.imageWidth || result.width || result.pageWidth || 0
  )
  const height = Number(
    page.height || page.pageHeight || page.imageHeight || result.height || result.pageHeight || 0
  )
  if (width > 0 && height > 0) return { width, height }
  const maxX = Math.max(0, ...selectedOcrCapabilityRawRois.value.map((roi) => roi.bbox[2]))
  const maxY = Math.max(0, ...selectedOcrCapabilityRawRois.value.map((roi) => roi.bbox[3]))
  return { width: maxX || 1, height: maxY || 1 }
})

const selectedOcrCapabilityRois = computed(() => selectedOcrCapabilityRawRois.value)
const selectedOcrCapabilityOverlayRois = computed(() =>
  selectedOcrCapabilityRois.value.filter((roi) => roi.type !== '文字')
)
const selectedOcrCapabilityImageRois = computed(() =>
  selectedOcrCapabilityPreviewSource.value?.previewType === 'image'
    ? selectedOcrCapabilityOverlayRois.value.filter((roi) => roi.pageNo === 1)
    : []
)
const selectedOcrCapabilityPdfPagePreviewUrl = computed(() => {
  const preview = selectedOcrCapabilityPreviewSource.value as
    | (Record<string, unknown> & { previewType?: string })
    | null
  if (preview?.previewType !== 'pdf') return ''
  if (!preview.pagePreviewUrl) return ''
  return ocrCapabilityPdfPageObjectUrl.value
})
const selectedOcrCapabilityPdfRois = computed(() =>
  selectedOcrCapabilityPdfPagePreviewUrl.value
    ? selectedOcrCapabilityOverlayRois.value.filter((roi) => roi.pageNo === 1)
    : []
)

const ocrCapabilityRoiLegend = computed(() => {
  const definitions: Array<{ type: string; tone: OcrCapabilityRoiTone; label: string }> = [
    { type: '文字', tone: 'blue', label: '文字' },
    { type: '字段', tone: 'green', label: '字段' },
    { type: '表格', tone: 'orange', label: '表格' },
    { type: '印章', tone: 'red', label: '印章' },
    { type: '版面', tone: 'purple', label: '版面' }
  ]
  return definitions
    .map((item) => ({
      ...item,
      count: selectedOcrCapabilityOverlayRois.value.filter((roi) => roi.type === item.type).length
    }))
    .filter((item) => item.count > 0)
})

const ocrCapabilityRoiTagType = (tone: OcrCapabilityRoiTone) =>
  ocrCapabilityRoiToneTypeMap[tone] || 'info'

const selectedOcrCapabilitySealRows = computed<OcrCapabilitySealDisplayRow[]>(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const fragments = Array.isArray(result.fragments)
    ? (result.fragments as Array<Record<string, unknown>>)
    : []
  return selectedOcrCapabilitySeals.value.map((seal, index) => {
    const bbox = normalizeOcrCapabilityBbox(seal.bbox)
    const pageNo = Number(seal.pageNo || 1)
    const directName = isOcrCapabilityPlaceholderSealName(seal.sealName)
      ? ''
      : String(seal.sealName || '').trim()
    const directLines = normalizeOcrCapabilityTextLines(
      seal.text ?? seal.fullText ?? seal.rawText ?? seal.content
    )
    const fieldLines = ocrCapabilitySealFieldLines(seal)
    const qualityFlags = Array.isArray(seal.qualityFlags) ? seal.qualityFlags : []
    const hasDedicatedSealText =
      fieldLines.length > 0 ||
      directLines.length > 0 ||
      qualityFlags.includes('seal_text_from_crop_ocr')
    const fragmentLines =
      !hasDedicatedSealText && bbox
        ? fragments
            .filter((fragment) => {
              if (Number(fragment.pageNo || 1) !== pageNo) return false
              const fragmentBbox = normalizeOcrCapabilityBbox(fragment.bbox)
              if (!fragmentBbox) return false
              return (
                ocrCapabilityBboxCenterInside(fragmentBbox, bbox) ||
                ocrCapabilityBboxOverlapRatio(fragmentBbox, bbox) >= 0.35
              )
            })
            .sort((left, right) => {
              const leftBbox = normalizeOcrCapabilityBbox(left.bbox) || [0, 0, 0, 0]
              const rightBbox = normalizeOcrCapabilityBbox(right.bbox) || [0, 0, 0, 0]
              return leftBbox[1] - rightBbox[1] || leftBbox[0] - rightBbox[0]
            })
            .flatMap((fragment) =>
              normalizeOcrCapabilityTextLines(
                fragment.text ?? fragment.fullText ?? fragment.rawText
              )
            )
        : []
    const contentLines = uniqueOcrCapabilityLines([
      ...fieldLines,
      ...directLines,
      ...fragmentLines
    ]).slice(0, 18)
    const colorLabel = ocrCapabilitySealColorLabel(seal)
    const typeLabel = ocrCapabilitySealTypeLabel(seal)
    const confidence =
      seal.ocrConfidence !== undefined ||
      seal.visualConfidence !== undefined ||
      seal.confidence !== undefined
        ? Number(seal.ocrConfidence ?? seal.visualConfidence ?? seal.confidence)
        : undefined
    const source = String(seal.sourceEngine || seal.source || '-')
    const bboxText = ocrCapabilityBboxText(seal.bbox)
    const status = contentLines.length
      ? '已提取文字'
      : qualityFlags.includes('requires_seal_ocr_text')
        ? '文字待复核'
        : '暂无可读文字'
    return {
      id: String(seal.sealId || seal.id || `seal-${index + 1}`),
      title: directName || typeLabel,
      colorLabel,
      typeLabel,
      status,
      tagType: contentLines.length ? 'success' : 'warning',
      pageNo,
      bboxText,
      confidence,
      source,
      contentLines,
      meta: [
        { label: '页码', value: String(pageNo) },
        { label: '位置', value: bboxText },
        { label: '置信度', value: confidence === undefined ? '-' : scorePercent(confidence) },
        { label: '来源', value: source }
      ]
    }
  })
})

const selectedOcrCapabilityStructuredRows = computed<OcrCapabilityStructuredRow[]>(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const rows: OcrCapabilityStructuredRow[] = []
  const pushRows = (value: unknown, type: string, labelPrefix: string) => {
    if (!Array.isArray(value)) return
    value.forEach((item, index) => {
      if (!item || typeof item !== 'object') return
      const row = createOcrCapabilityStructuredRow(
        item as Record<string, unknown>,
        type,
        index + 1,
        `${labelPrefix} ${index + 1}`
      )
      if (row) rows.push(row)
    })
  }
  pushRows(result.fragments, '文本', '文本')
  pushRows(result.fields, '字段', '字段')
  pushRows(result.tables, '表格', '表格')
  selectedOcrCapabilitySealRows.value.forEach((seal, index) => {
    rows.push({
      id: `印章-${seal.id || index}`,
      pageNo: seal.pageNo,
      type: '印章',
      name: seal.title,
      value: seal.contentLines.join('\n') || seal.status,
      bboxText: seal.bboxText,
      confidence: seal.confidence,
      source: seal.source
    })
  })
  pushRows(result.layoutBlocks, '版面', '版面')
  return rows.slice(0, 120)
})

const ocrCapabilityRoiStyle = (roi: OcrCapabilityRoi) => {
  const [x1, y1, x2, y2] = roi.bbox
  const normalized = x2 <= 1.5 && y2 <= 1.5
  const width = normalized ? 1 : selectedOcrCapabilityRoiPageSize.value.width
  const height = normalized ? 1 : selectedOcrCapabilityRoiPageSize.value.height
  const clamp = (value: number) => Math.max(0, Math.min(100, value))
  return {
    left: `${clamp((x1 / width) * 100)}%`,
    top: `${clamp((y1 / height) * 100)}%`,
    width: `${Math.max(1.4, clamp(((x2 - x1) / width) * 100))}%`,
    height: `${Math.max(1.4, clamp(((y2 - y1) / height) * 100))}%`
  }
}

const selectedOcrCapabilityRunning = computed(() => {
  const status = String(selectedOcrCapabilityRun.value?.status || '')
  return Boolean(status) && !ocrCapabilityTerminalStatuses.has(status)
})

const ocrCapabilityProgressHint = computed(() => {
  if (ocrCapabilityTestStage.value) return ocrCapabilityTestStage.value
  if (selectedOcrCapabilityRunning.value) return 'OCR 正在识别，完成后会自动显示文本和 ROI。'
  return ''
})
const ocrCapabilityResultLoading = computed(
  () =>
    ocrCapabilityTestLoading.value ||
    ocrCapabilityDetailLoading.value ||
    selectedOcrCapabilityRunning.value
)
const selectedOcrCapabilityText = computed(() => {
  const result = selectedOcrCapabilityParseResult.value || {}
  const directText = stringifyOcrCapabilityText(
    result.fullText ??
      result.text ??
      result.rawText ??
      result.plainText ??
      result.ocrText ??
      result.markdown ??
      result.content
  )
  if (directText) return directText
  const pageText = stringifyOcrCapabilityText(result.pages)
  if (pageText) return pageText
  const fragmentText = stringifyOcrCapabilityText(result.fragments)
  if (fragmentText) return fragmentText
  const layoutText = stringifyOcrCapabilityText(result.layoutBlocks)
  if (layoutText) return layoutText
  const tableText = stringifyOcrCapabilityText(result.tables)
  if (tableText) return tableText
  return selectedOcrCapabilityFields.value
    .map((field) => {
      const label = friendlyFieldLabel(
        String(field.fieldCode || field.fieldName || field.name || '字段')
      )
      const value = stringifyOcrCapabilityText(field.fieldValue ?? field.value ?? field.text)
      return value ? `${label}：${value}` : ''
    })
    .filter(Boolean)
    .join('\n')
})
const selectedOcrCapabilityHasOutput = computed(
  () =>
    !!selectedOcrCapabilityText.value ||
    selectedOcrCapabilityStructuredRows.value.length > 0 ||
    selectedOcrCapabilityRois.value.length > 0 ||
    selectedOcrCapabilityFields.value.length > 0 ||
    selectedOcrCapabilityTables.value.length > 0 ||
    selectedOcrCapabilitySeals.value.length > 0 ||
    selectedOcrCapabilityDiagnostics.value.length > 0
)
const selectedOcrCapabilityTerminalNoOutput = computed(
  () =>
    Boolean(selectedOcrCapabilityRun.value) &&
    !selectedOcrCapabilityRunning.value &&
    !selectedOcrCapabilityHasOutput.value
)
const selectedOcrCapabilityCanPersist = computed(
  () =>
    selectedOcrCapabilityRun.value?.status === 'success' &&
    !!selectedOcrCapabilityRun.value?.parseResultId
)
const ocrCapabilityStatusType = (status: unknown): FdeElTagType =>
  statusType(String(status)) as FdeElTagType

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
      title: '流程工作流接收审查任务',
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
    blockers: ['印章文字准确率未达到 92% 目标。', '印章文字解析样本“可入评估”数量不足 5 个。']
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
  nextActions: ['补齐印章文字解析样本的印章框', '二审已标注样本后进入评估集'],
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
      targetName: '印章文字解析样本',
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
  { label: '审查任务', value: reviewRuns.value.length || 0, tone: 'green' as const },
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
const dashboardMetricHighlights = computed(() => dashboardMetricCards.value.slice(0, 4))

const fdeWorkflowCards = computed(() => [
  {
    key: 'agent' as const,
    title: 'Agent 审查编排',
    description: '检查流程编排、Agent 节点、工具调用、规则和检索产物。',
    route: '/fde/review-runs',
    action: '看编排',
    tone: 'green',
    metric: String(reviewRuns.value.length)
  },
  {
    key: 'ocr' as const,
    title: '标定 OCR 样本',
    description: '补齐字段、表格和印章 bbox，让 OCR 评估集可用。',
    route: '/fde/ocr-quality',
    action: '去标注',
    tone: 'green',
    metric: `${ocrAnnotationSummary.value?.humanLabeled || 0}/${ocrAnnotationSummary.value?.tasks || 0}`
  }
])
const selectedFdeWorkflowCard = computed(
  () =>
    fdeWorkflowCards.value.find((card) => card.key === selectedFdeDashboardTab.value) ||
    fdeWorkflowCards.value[0]
)

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
const projectAuditKnowledgeLineage = computed(() =>
  toRecord(projectAuditWorkspace.value?.knowledgeLineage)
)
const projectAuditLineageSourceLabel = computed(() => {
  const source = String(projectAuditKnowledgeLineage.value.source || '')
  if (source === 'backend_audit_projection') return '后端审计投影'
  if (source) return source
  return '前端推断'
})
const rawProjectAuditVectorQuality = computed<FdeVectorQualityPayload>(() => {
  const payload = projectAuditWorkspace.value?.vectorQuality
  return payload && typeof payload === 'object' ? payload : {}
})
const projectAuditTechnologyStack = computed(() =>
  toRecord(projectAuditWorkspace.value?.technologyStack)
)
const projectAuditTechnologyHotSwap = computed(() =>
  toRecord(projectAuditTechnologyStack.value.hotSwap)
)
const projectAuditTechnologySections = computed(() => {
  const sections = toRecordArray(projectAuditTechnologyStack.value.sections)
  if (sections.length) {
    return sections.map((section) => ({
      key: String(section.key || section.title || ''),
      title: String(section.title || section.key || '-'),
      primary: String(section.primary || '-'),
      secondary: String(section.secondary || ''),
      detail: String(section.detail || ''),
      status: String(section.status || 'active'),
      tone: String(section.tone || 'blue') as FdeTone
    }))
  }
  return [
    {
      key: 'embedding',
      title: '向量化',
      primary: String(projectAuditVectorIndexProfile.value.embeddingModel || 'embedding-default'),
      secondary: '本地 embedding-service',
      detail: `${projectAuditVectorIndexProfile.value.vectorDimensions || 1024}维，稳定别名可切换`,
      status: 'active',
      tone: 'green' as FdeTone
    },
    {
      key: 'retrieval',
      title: '检索',
      primary: '混合检索 + 章节溯源',
      secondary: '关键词检索 + 语义向量检索',
      detail: '按检索轨迹追踪召回和证据命中',
      status: 'active',
      tone: 'blue' as FdeTone
    }
  ]
})
const projectAuditEmbeddingRegistryRows = computed(() =>
  toRecordArray(projectAuditTechnologyStack.value.embeddingModelRegistry).map((row) => ({
    modelId: String(row.modelId || '-'),
    label: String(row.label || row.modelId || '-'),
    role: String(row.role || '-'),
    dimensions: Number(row.dimensions || 0),
    contextLength: Number(row.contextLength || 0),
    provider: String(row.provider || '-'),
    indexVersion: String(row.indexVersion || '-')
  }))
)
const projectAuditVectorQualityMetrics = computed(() =>
  toRecord(rawProjectAuditVectorQuality.value.metrics)
)
const projectAuditVectorQualityScore = computed(() =>
  score100(rawProjectAuditVectorQuality.value.score, 0)
)
const projectAuditVectorQualityStatus = computed(() =>
  String(rawProjectAuditVectorQuality.value.status || 'needs_attention')
)
const projectAuditVectorQualityTone = computed<FdeTone>(() => {
  const score = projectAuditVectorQualityScore.value
  if (projectAuditVectorQualityStatus.value === 'pass' && score >= 90) return 'green'
  if (score >= 80) return 'orange'
  return 'red'
})
const projectAuditVectorQualitySections = computed(() => {
  const sections = toRecordArray(rawProjectAuditVectorQuality.value.sections)
  if (sections.length) {
    return sections.map((section) => ({
      key: String(section.key || section.name || ''),
      name: String(section.name || section.key || '-'),
      score: Number(section.score || 0),
      maxScore: Number(section.maxScore || 100),
      metric: Number(section.metric || 0),
      status: String(section.status || 'warn'),
      blockers: Array.isArray(section.blockers) ? section.blockers.map((item) => String(item)) : []
    }))
  }
  const rows = normalizedProjectAuditVectorRows.value
  const total = rows.length || 1
  const chunkReady = rows.filter((row) => Number(row.chunkCount || 0) > 0).length / total
  const vectorReady = rows.filter((row) => row.readyForRag).length / total
  const pageIndexReady = rows.filter((row) => row.readyForPageIndex).length / total
  return [
    {
      key: 'corpus_metadata',
      name: '切片与 metadata',
      score: Math.round(chunkReady * 15),
      maxScore: 15,
      metric: chunkReady,
      status: chunkReady >= 0.9 ? 'pass' : 'warn',
      blockers: chunkReady >= 0.9 ? [] : ['切片覆盖不足']
    },
    {
      key: 'vector_index',
      name: '向量完整性',
      score: Math.round(vectorReady * 25),
      maxScore: 25,
      metric: vectorReady,
      status: vectorReady >= 0.95 ? 'pass' : 'warn',
      blockers: vectorReady >= 0.95 ? [] : ['部分资料未完成向量入库']
    },
    {
      key: 'retrieval',
      name: '检索命中',
      score: 0,
      maxScore: 30,
      metric: 0,
      status: 'warn',
      blockers: ['旧接口缺少检索轨迹评分']
    },
    {
      key: 'evidence',
      name: '证据可追溯',
      score: Math.round(pageIndexReady * 20),
      maxScore: 20,
      metric: pageIndexReady,
      status: pageIndexReady >= 0.8 ? 'pass' : 'warn',
      blockers: pageIndexReady >= 0.8 ? [] : ['章节溯源覆盖不足']
    },
    {
      key: 'stability',
      name: '稳定与门禁',
      score: 0,
      maxScore: 10,
      metric: 0,
      status: 'warn',
      blockers: ['旧接口缺少评估门禁数据']
    }
  ]
})
const projectAuditVectorQualityBlockers = computed(() => {
  const blockers = Array.isArray(rawProjectAuditVectorQuality.value.blockers)
    ? rawProjectAuditVectorQuality.value.blockers
    : []
  if (blockers.length) return blockers.map((item) => String(item))
  return projectAuditVectorQualitySections.value.flatMap((section) => section.blockers)
})
const projectAuditVectorQualityCards = computed(() => [
  {
    label: '质量评分',
    value: `${projectAuditVectorQualityScore.value}/100`,
    hint: String(rawProjectAuditVectorQuality.value.statusLabel || '按 FDE 向量质量口径量化'),
    tone: projectAuditVectorQualityTone.value
  },
  {
    label: 'Recall@5 代理',
    value: scorePercent(projectAuditVectorQualityMetrics.value.recallAt5Proxy as number),
    hint: `${Number(projectAuditVectorQualityMetrics.value.retrievalTraceCount || 0)} 条检索轨迹`,
    tone:
      Number(projectAuditVectorQualityMetrics.value.recallAt5Proxy || 0) >= 0.9 ? 'green' : 'orange'
  },
  {
    label: '证据命中',
    value: scorePercent(projectAuditVectorQualityMetrics.value.evidenceHitRate as number),
    hint: '页码 / bbox / 条款引用覆盖',
    tone:
      Number(projectAuditVectorQualityMetrics.value.evidenceHitRate || 0) >= 0.9
        ? 'green'
        : 'orange'
  },
  {
    label: '过滤泄漏',
    value: scorePercent(projectAuditVectorQualityMetrics.value.filterLeakageRate as number),
    hint: '跨项目/业务类型泄漏必须为 0',
    tone:
      Number(projectAuditVectorQualityMetrics.value.filterLeakageRate || 0) <= 0 ? 'green' : 'red'
  },
  {
    label: '金标样本',
    value: String(projectAuditVectorQualityMetrics.value.goldCaseCount || 0),
    hint: '带 expectedClauseIds 的检索评估样本',
    tone: Number(projectAuditVectorQualityMetrics.value.goldCaseCount || 0) > 0 ? 'green' : 'orange'
  }
])
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
      embeddingModelId: raw.embeddingModelId || raw.modelId || '',
      embeddingProvider: raw.embeddingProvider || '',
      embeddingServedModelName: raw.embeddingServedModelName || '',
      indexVersion: raw.indexVersion || raw.vectorIndexVersion || 'knowledge-index@local',
      vectorDimensions: Number(raw.vectorDimensions || 1024),
      pageIndexStatus: raw.pageIndexStatus || (chunkCount > 0 ? '可构建' : '等待切片'),
      pageIndexNodeCount: Number(raw.pageIndexNodeCount || 0),
      latestTask: raw.latestTask || raw.latestKnowledgeTask || ocrJob?.status || '-',
      knowledgeLineage: raw.knowledgeLineage || {},
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
    const knowledgeLineage = toRecord(item.knowledgeLineage)
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
      issue = '章节溯源未构建'
      action = '构建章节树后再用于长文档溯源'
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
      embeddingModelId: item.embeddingModelId || '',
      embeddingProvider: item.embeddingProvider || '',
      embeddingServedModelName: item.embeddingServedModelName || '',
      indexVersion: item.indexVersion || 'knowledge-index@local',
      pageIndexStatus: item.pageIndexStatus || '-',
      rowIndex: index + 1,
      chunkCount,
      vectorCount,
      pageIndexNodeCount,
      vectorDimensions: Number(item.vectorDimensions || 1024),
      vectorGap,
      readyForRag,
      readyForPageIndex,
      readinessLabel:
        String(knowledgeLineage.readinessLabel || '') ||
        (readyForRag && readyForPageIndex ? '可用于审查' : '需补齐'),
      issue,
      action,
      knowledgeLineage,
      lineageConclusion:
        String(knowledgeLineage.auditConclusion || '') ||
        (readyForRag && readyForPageIndex ? '可进入审查链' : '仍有知识资产缺口'),
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
      hint: '用于混合检索 / 章节溯源',
      tone: 'green'
    },
    {
      label: '向量条目',
      value: String(vectorCount),
      hint: 'Embedding 入库数量',
      tone: vectorCount ? 'green' : 'orange'
    },
    {
      label: '章节溯源',
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

const projectAuditVectorQualityDocumentRows = computed<Array<Record<string, unknown>>>(() => {
  const backendRows = toRecordArray(rawProjectAuditVectorQuality.value.documentScores)
  if (backendRows.length) {
    return backendRows.map((row, index) => ({
      ...row,
      id: String(row.documentVersionId || row.documentId || `vector-quality-doc-${index + 1}`),
      fileName: String(row.fileName || `资料 ${index + 1}`),
      score: score100(row.score, 0),
      chunkCount: Number(row.chunkCount || 0),
      vectorCount: Number(row.vectorCount || 0),
      vectorGap: Number(row.vectorGap || 0),
      issue: String(row.issue || '无')
    }))
  }
  return normalizedProjectAuditVectorRows.value.map((row, index) => {
    const rowRecord = toRecord(row)
    const chunkCount = Number(row.chunkCount || 0)
    const vectorCount = Number(row.vectorCount || 0)
    const vectorRatio = chunkCount ? Math.min(1, vectorCount / chunkCount) : 0
    const rowLineage = toRecord(row.knowledgeLineage)
    const score = Math.round(
      (0.25 * (chunkCount > 0 ? 1 : 0) +
        0.4 * vectorRatio +
        0.2 * (row.readyForPageIndex ? 1 : 0) +
        0.15 * (row.issue === '无' ? 1 : 0)) *
        100
    )
    return {
      id: String(row.documentVersionId || row.id || `vector-quality-doc-${index + 1}`),
      fileName: String(row.fileName || `资料 ${index + 1}`),
      score,
      chunkCount,
      vectorCount,
      vectorGap: Number(row.vectorGap || 0),
      issue: String(row.issue || '无'),
      embeddingModel: row.embeddingModel,
      indexVersion: row.indexVersion,
      vectorDimensions: row.vectorDimensions,
      requirementName: row.requirementName,
      knowledgeFileId: rowRecord.knowledgeFileId,
      documentVersionId: row.documentVersionId,
      qualityDimensions: [
        {
          key: 'chunking',
          name: '知识切片',
          score: chunkCount > 0 ? 100 : 0,
          metric: chunkCount > 0 ? 1 : 0,
          status: chunkCount > 0 ? 'pass' : 'warn',
          message: `切片 ${chunkCount} 条`
        },
        {
          key: 'vector_integrity',
          name: '向量完整性',
          score: Math.round(vectorRatio * 100),
          metric: vectorRatio,
          status: Number(row.vectorGap || 0) ? 'warn' : 'pass',
          message: `向量 ${vectorCount}/${chunkCount} 条，缺口 ${Number(row.vectorGap || 0)}`
        },
        {
          key: 'pageindex',
          name: '章节溯源',
          score: row.readyForPageIndex ? 100 : 0,
          metric: row.readyForPageIndex ? 1 : 0,
          status: row.readyForPageIndex ? 'pass' : 'warn',
          message: `章节节点 ${Number(row.pageIndexNodeCount || 0)} 个`
        }
      ],
      lineageStages: toRecordArray(rowLineage.stages),
      lineageBlockers: row.issue === '无' ? [] : [String(row.issue)],
      llmTrace: {
        scope: 'project_proxy',
        retrievalTraceCount: Number(
          projectAuditVectorQualityMetrics.value.retrievalTraceCount || 0
        ),
        hitRate: Number(projectAuditVectorQualityMetrics.value.recallAt5Proxy || 0),
        evidenceHitRate: Number(projectAuditVectorQualityMetrics.value.evidenceHitRate || 0)
      },
      retrievalTraceRows: toRecordArray(rawProjectAuditVectorQuality.value.retrievalProbeRows)
    }
  })
})

const selectedVectorFileQualityRecord = computed(() => toRecord(selectedVectorFileQuality.value))
const selectedVectorFileQualityDimensions = computed(() =>
  toRecordArray(selectedVectorFileQualityRecord.value.qualityDimensions).map((row, index) => ({
    id: String(row.key || row.name || `vector-file-dimension-${index + 1}`),
    name: friendlyTechnicalText(row.name || row.key || '-'),
    score: score100(row.score, 0),
    metric: row.metric === undefined ? '-' : scorePercent(row.metric as number),
    status: String(row.status || 'warn'),
    statusLabel: friendlyStatus(row.status || 'warn', '-'),
    message: friendlyTechnicalText(
      row.message || (Array.isArray(row.blockers) ? row.blockers.join('；') : '') || '-'
    )
  }))
)
const selectedVectorFileLineageStages = computed(() => {
  const stages = toRecordArray(selectedVectorFileQualityRecord.value.lineageStages)
  if (stages.length) {
    return stages.map((stage, index) => ({
      id: String(stage.key || `vector-file-stage-${index + 1}`),
      label: friendlyTechnicalText(stage.label || '-'),
      status: friendlyStatus(stage.status, '-'),
      done: Boolean(stage.done),
      evidence: friendlyTechnicalText(stage.evidence || '-'),
      action: friendlyTechnicalText(stage.action || '-')
    }))
  }
  return [
    {
      id: 'chunking',
      label: '知识切片',
      status: String(selectedVectorFileQualityRecord.value.sliceStatus || '-'),
      done: Number(selectedVectorFileQualityRecord.value.chunkCount || 0) > 0,
      evidence: `切片 ${Number(selectedVectorFileQualityRecord.value.chunkCount || 0)} 条`,
      action: '切片完成后进入向量入库'
    },
    {
      id: 'vector',
      label: '向量入库',
      status: String(selectedVectorFileQualityRecord.value.vectorStatus || '-'),
      done: Number(selectedVectorFileQualityRecord.value.vectorGap || 0) === 0,
      evidence: `向量 ${Number(selectedVectorFileQualityRecord.value.vectorCount || 0)}/${Number(selectedVectorFileQualityRecord.value.chunkCount || 0)} 条`,
      action: '向量完整后可参与混合检索'
    },
    {
      id: 'pageindex',
      label: '章节溯源',
      status: selectedVectorFileQualityRecord.value.pageIndexReady ? '已构建' : '待构建',
      done: Boolean(selectedVectorFileQualityRecord.value.pageIndexReady),
      evidence: `节点 ${Number(selectedVectorFileQualityRecord.value.pageIndexNodeCount || 0)} 个`,
      action: '用于长文档跨章节溯源'
    }
  ]
})
const selectedVectorFileRetrievalRows = computed(() =>
  toRecordArray(selectedVectorFileQualityRecord.value.retrievalTraceRows).map((row, index) => ({
    id: String(row.retrievalTraceId || `vector-file-retrieval-${index + 1}`),
    query: String(row.query || '-'),
    selectedRoute: friendlyTechLabel(row.selectedRoute),
    selectedClauseCount: Number(row.selectedClauseCount || 0),
    evidenceBacked: Boolean(row.evidenceBacked),
    filterScoped: Boolean(row.filterScoped)
  }))
)
const selectedVectorFileDetailRecord = computed(() => toRecord(selectedVectorFileDetail.value))
const selectedVectorFileLlmTrace = computed(() =>
  toRecord(selectedVectorFileQualityRecord.value.llmTrace)
)
const selectedVectorFileBlockers = computed(() => {
  const detailBlockers = selectedVectorFileDetail.value?.blockers
  if (Array.isArray(detailBlockers) && detailBlockers.length) {
    return detailBlockers.map((item) => friendlyIssueLabel(item, '')).filter(Boolean)
  }
  const blockers = selectedVectorFileQualityRecord.value.lineageBlockers
  if (Array.isArray(blockers))
    return blockers.map((item) => friendlyIssueLabel(item, '')).filter(Boolean)
  const issue = String(selectedVectorFileQualityRecord.value.issue || '')
  return issue && issue !== '无' ? [friendlyIssueLabel(issue)] : []
})
const selectedVectorFileSummaryCards = computed(() => [
  {
    label: '文件评分',
    value: `${score100(selectedVectorFileQualityRecord.value.score, 0)}/100`,
    hint: friendlyIssueLabel(selectedVectorFileQualityRecord.value.issue, '无异常'),
    tone: score100(selectedVectorFileQualityRecord.value.score, 0) >= 90 ? 'green' : 'orange'
  },
  {
    label: '切片/向量',
    value: `${Number(selectedVectorFileQualityRecord.value.chunkCount || 0)}/${Number(selectedVectorFileQualityRecord.value.vectorCount || 0)}`,
    hint: `缺口 ${Number(selectedVectorFileQualityRecord.value.vectorGap || 0)} 条`,
    tone: Number(selectedVectorFileQualityRecord.value.vectorGap || 0) ? 'red' : 'green'
  },
  {
    label: '证据命中',
    value: scorePercent(selectedVectorFileLlmTrace.value.evidenceHitRate as number),
    hint:
      selectedVectorFileLlmTrace.value.scope === 'document_explicit'
        ? '文件级审查任务'
        : '项目级代理溯源',
    tone: Number(selectedVectorFileLlmTrace.value.evidenceHitRate || 0) >= 0.9 ? 'green' : 'orange'
  },
  {
    label: '检索溯源',
    value: String(selectedVectorFileLlmTrace.value.retrievalTraceCount || 0),
    hint: '用于判断 LLM 依据质量',
    tone: Number(selectedVectorFileLlmTrace.value.retrievalTraceCount || 0) ? 'green' : 'orange'
  }
])
const selectedVectorFileChunkSummary = computed(() =>
  toRecord(selectedVectorFileDetailRecord.value.chunkSummary)
)
const selectedVectorFileChunkRows = computed(() =>
  toRecordArray(
    selectedVectorFileDetailRecord.value.chunkRows ||
      toRecord(selectedVectorFileDetailRecord.value.chunkPage).items
  ).map((row, index) => ({
    id: String(row.id || row.chunkId || `chunk-${index + 1}`),
    chunkNo: Number(row.chunkNo || index + 1),
    materialized: Boolean(row.materialized),
    pageNo: row.pageNo ?? '-',
    bbox: row.bbox,
    tokenCount: Number(row.tokenCount || 0),
    textPreview: String(row.textPreview || '-'),
    vectorStatus: String(row.vectorStatusLabel || row.vectorStatus || '-'),
    retrievalHitCount: Number(row.retrievalHitCount || 0),
    hasBbox: Boolean(row.bbox),
    metadataCompleteness: scorePercent(Number(row.metadataCompleteness || 0)),
    qualityFlags: Array.isArray(row.qualityFlags)
      ? row.qualityFlags.map((item) => friendlyIssueLabel(item, '')).filter(Boolean)
      : [],
    evidenceLabel: `Chunk ${Number(row.chunkNo || index + 1)}`
  }))
)
const selectedVectorFileDetailRetrievalRows = computed(() => {
  const rows = toRecordArray(selectedVectorFileDetailRecord.value.retrievalTraceRows)
  if (!rows.length) return selectedVectorFileRetrievalRows.value
  return rows.map((row, index) => ({
    id: String(row.retrievalTraceId || `vector-file-detail-retrieval-${index + 1}`),
    query: String(row.query || '-'),
    selectedRoute: friendlyTechLabel(row.selectedRoute),
    scope: row.scope === 'document_explicit' ? '文件级' : '项目代理',
    selectedClauseCount: Number(row.selectedClauseCount || 0),
    selectedChunkCount: Number(row.selectedChunkCount || 0),
    evidenceBacked: Boolean(row.evidenceBacked),
    filterScoped: Boolean(row.filterScoped)
  }))
})
const selectedVectorFileChunkCards = computed(() => [
  {
    label: '真实切片',
    value: `${Number(selectedVectorFileChunkSummary.value.materializedChunkCount || 0)}/${Number(selectedVectorFileChunkSummary.value.declaredChunkCount || 0)}`,
    hint: `缺明细 ${Number(selectedVectorFileChunkSummary.value.missingMaterializedChunkCount || 0)} 条`
  },
  {
    label: '页码覆盖',
    value: scorePercent(Number(selectedVectorFileChunkSummary.value.pageCoverage || 0)),
    hint: '每个切片应能回溯页码'
  },
  {
    label: 'bbox 覆盖',
    value: scorePercent(Number(selectedVectorFileChunkSummary.value.bboxCoverage || 0)),
    hint: '证据定位可点击的基础'
  },
  {
    label: '检索覆盖',
    value: scorePercent(Number(selectedVectorFileChunkSummary.value.retrievalCoverage || 0)),
    hint: `${Number(selectedVectorFileChunkSummary.value.retrievedChunkCount || 0)} 条被溯源命中`
  }
])
const selectedVectorFilePipeline = computed(() =>
  toRecord(selectedVectorFileDetailRecord.value.processingPipeline)
)
const selectedVectorFilePipelineSummary = computed(() =>
  toRecordArray(selectedVectorFilePipeline.value.summary).map((row, index) => ({
    id: String(row.key || `pipeline-stage-${index + 1}`),
    label: String(row.label || row.key || '-'),
    status: friendlyStatus(row.status, '-'),
    rawStatus: String(row.status || ''),
    metric: String(row.metric || '-'),
    done: ['ready', 'success', '已向量化', '已切片'].some((keyword) =>
      String(row.status || '').includes(keyword)
    )
  }))
)
const selectedVectorFilePipelineSource = computed(() =>
  toRecord(
    selectedVectorFileDetailRecord.value.sourcePreview || selectedVectorFilePipeline.value.source
  )
)
const selectedVectorFileSourcePages = computed(() =>
  toRecordArray(selectedVectorFilePipelineSource.value.pages).map((page, index) => ({
    id: String(page.pageNo || `page-${index + 1}`),
    pageNo: Number(page.pageNo || index + 1),
    width: Number(page.width || 1000),
    height: Number(page.height || 1400),
    previewUrl: String(page.previewUrl || selectedVectorFilePipelineSource.value.previewUrl || ''),
    imageObjectKey: String(page.imageObjectKey || '')
  }))
)
const selectedVectorActivePage = computed(() => {
  const evidencePage = Number(toRecord(selectedVectorEvidence.value).pageNo || 0)
  const pages = selectedVectorFileSourcePages.value
  return pages.find((page) => page.pageNo === evidencePage) || pages[0] || null
})
const selectedVectorPreviewUrl = computed(() =>
  String(
    selectedVectorActivePage.value?.previewUrl ||
      selectedVectorFilePipelineSource.value.previewUrl ||
      ''
  )
)
const selectedVectorPreviewType = computed(() =>
  String(
    selectedVectorFilePipelineSource.value.previewType ||
      selectedVectorFilePipelineSource.value.fileType ||
      ''
  )
)
const selectedVectorPreviewCanRender = computed(() => {
  const url = selectedVectorPreviewUrl.value
  if (!url || url.startsWith('mock://')) return false
  return /image|png|jpe?g|webp|gif|pdf/i.test(`${selectedVectorPreviewType.value} ${url}`)
})
const selectedVectorPreviewIsImage = computed(() =>
  /image|png|jpe?g|webp|gif/i.test(
    `${selectedVectorPreviewType.value} ${selectedVectorPreviewUrl.value}`
  )
)
const selectedVectorFilePipelineOcr = computed(() => toRecord(selectedVectorFilePipeline.value.ocr))
const selectedVectorFilePipelineOcrSummary = computed(() =>
  toRecord(selectedVectorFilePipelineOcr.value.summary)
)
const selectedVectorFilePipelineFieldRows = computed(() =>
  toRecordArray(selectedVectorFilePipelineOcr.value.fieldRows).map((row, index) => ({
    id: String(row.fieldCode || row.fieldName || `pipeline-field-${index + 1}`),
    fieldName: friendlyFieldLabel(String(row.fieldName || row.fieldCode || '-')),
    fieldValue: String(row.fieldValue ?? '-'),
    pageNo: row.pageNo ?? '-',
    confidence: row.confidence === undefined ? '-' : scorePercent(Number(row.confidence || 0)),
    source: friendlyTechnicalText(row.source || '-'),
    hasBbox: Boolean(row.bbox),
    bbox: row.bbox,
    evidenceLabel: friendlyFieldLabel(String(row.fieldName || row.fieldCode || `字段 ${index + 1}`))
  }))
)
const selectedVectorFilePipelineTextRows = computed(() =>
  toRecordArray(toRecord(selectedVectorFilePipeline.value.text).rows).map((row, index) => ({
    id: String(row.id || `pipeline-text-${index + 1}`),
    sourceType: friendlyTechnicalText(row.sourceType || '-'),
    sourceLabel: friendlyTechnicalText(row.sourceLabel || '-'),
    pageNo: row.pageNo ?? '-',
    tokenCount: row.tokenCount ?? '-',
    text: String(row.text || '-'),
    hasBbox: Boolean(row.bbox),
    bbox: row.bbox,
    evidenceLabel: String(row.sourceLabel || `文本 ${index + 1}`)
  }))
)
const selectedVectorFilePipelineVectorRows = computed(() =>
  toRecordArray(toRecord(selectedVectorFilePipeline.value.vectorFormat).rows).map((row, index) => {
    const embeddingInput = toRecord(row.embeddingInput)
    const vectorRecord = toRecord(row.vectorRecord)
    const indexRecord = toRecord(row.indexRecord)
    const metadata = toRecord(vectorRecord.metadata)
    return {
      id: String(row.id || `pipeline-vector-${index + 1}`),
      chunkNo: Number(row.chunkNo || index + 1),
      vectorStatus: friendlyStatus(
        row.vectorStatus,
        friendlyTechnicalText(row.vectorStatus || '-')
      ),
      textPreview: String(row.textPreview || '-'),
      model: String(embeddingInput.model || '-'),
      payloadHash: String(vectorRecord.payloadHash || '-'),
      dimensions: Number(vectorRecord.dimensions || 0),
      indexVersion: String(vectorRecord.indexVersion || '-'),
      vectorId: String(indexRecord.vectorId || vectorRecord.id || '-'),
      pageNo: metadata.pageNo ?? '-',
      bbox: metadata.bbox,
      hasBbox: Boolean(metadata.bbox),
      metadata: JSON.stringify(vectorRecord.metadata || {}, null, 2),
      evidenceLabel: `Chunk ${Number(row.chunkNo || index + 1)}`
    }
  })
)
const selectedVectorEvidenceRecord = computed(() => toRecord(selectedVectorEvidence.value))
const selectedVectorEvidenceBbox = computed(() => {
  const bbox = selectedVectorEvidenceRecord.value.bbox
  if (!Array.isArray(bbox) || bbox.length < 4) return null
  const values = bbox.slice(0, 4).map((value) => Number(value))
  return values.every((value) => Number.isFinite(value)) ? values : null
})
const selectedVectorEvidenceStyle = computed(() => {
  const bbox = selectedVectorEvidenceBbox.value
  const page = selectedVectorActivePage.value
  if (!bbox || !page) return {}
  const [x1, y1, x2, y2] = bbox
  const width = x2 > x1 ? x2 - x1 : x2
  const height = y2 > y1 ? y2 - y1 : y2
  return {
    left: `${Math.max(0, (x1 / page.width) * 100)}%`,
    top: `${Math.max(0, (y1 / page.height) * 100)}%`,
    width: `${Math.min(100, Math.max(2, (width / page.width) * 100))}%`,
    height: `${Math.min(100, Math.max(2, (height / page.height) * 100))}%`
  }
})
const selectedVectorEvidenceJson = computed(() =>
  JSON.stringify(selectedVectorEvidenceRecord.value, null, 2)
)
const selectedVectorQualityIssues = computed<Array<Record<string, unknown>>>(() =>
  toRecordArray(selectedVectorFileDetailRecord.value.qualityIssues).map((issue) => ({
    ...issue,
    code: friendlyIssueLabel(issue.code, '-'),
    severity: friendlyStatus(issue.severity, '-'),
    message: friendlyTechnicalText(issue.message || issue.code, '-')
  }))
)
const vectorFileTokenBuckets = computed(() =>
  toRecord(toRecord(selectedVectorFileDetailRecord.value.chunkCharts).tokenBuckets)
)
const vectorFilePageDistribution = computed(() =>
  toRecord(toRecord(selectedVectorFileDetailRecord.value.chunkCharts).pageDistribution)
)
const vectorFileFlagCounts = computed(() =>
  toRecord(toRecord(selectedVectorFileDetailRecord.value.chunkCharts).flagCounts)
)
const selectedVectorFileTokenOption = computed<EChartsOption>(() => {
  const entries = Object.entries(vectorFileTokenBuckets.value).map(([name, value]) => ({
    label: friendlyTechnicalText(name),
    value: Number(value || 0)
  }))
  return {
    grid: { top: 26, right: 12, bottom: 34, left: 38 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const entry = entries[Number(item?.dataIndex || 0)]
        return `${entry?.label || '-'}：${entry?.value ?? 0}`
      }
    },
    xAxis: { type: 'category', data: entries.map((entry) => entry.label) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: entries.map((entry) => entry.value), color: '#2563eb' }]
  }
})
const selectedVectorFilePageOption = computed<EChartsOption>(() => {
  const entries = Object.entries(vectorFilePageDistribution.value)
    .slice(0, 12)
    .map(([name, value]) => ({ label: friendlyTechnicalText(name), value: Number(value || 0) }))
  return {
    grid: { top: 26, right: 12, bottom: 34, left: 38 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const entry = entries[Number(item?.dataIndex || 0)]
        return `${entry?.label || '-'}：${entry?.value ?? 0}`
      }
    },
    xAxis: { type: 'category', data: entries.map((entry) => entry.label) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: entries.map((entry) => entry.value), color: '#16a34a' }]
  }
})
const selectedVectorFileFlagOption = computed<EChartsOption>(() => {
  const entries = Object.entries(vectorFileFlagCounts.value)
    .slice(0, 12)
    .map(([name, value]) => ({
      rawName: name,
      label: friendlyIssueLabel(name),
      value: Number(value || 0)
    }))
  return {
    grid: { top: 26, right: 12, bottom: 44, left: 38 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const dataIndex = Number(item?.dataIndex || 0)
        const entry = entries[dataIndex]
        return `${entry?.label || item?.name || '-'}：${entry?.value ?? item?.value ?? 0}`
      }
    },
    xAxis: {
      type: 'category',
      data: entries.map((entry) => entry.label),
      axisLabel: { interval: 0, rotate: 24 }
    },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: entries.map((entry) => entry.value), color: '#ea580c' }]
  }
})

const projectAuditVectorQualityRadarOption = computed<EChartsOption>(() => {
  const sections = projectAuditVectorQualitySections.value
  const indicators = sections.map((section) => ({
    name: section.name,
    max: section.maxScore || 100
  }))
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: () =>
        sections
          .map(
            (section) =>
              `${section.name}：${Math.round(section.score * 10) / 10}/${section.maxScore}`
          )
          .join('<br/>')
    },
    radar: {
      center: ['50%', '52%'],
      radius: '68%',
      indicator: indicators,
      axisName: {
        color: '#334155',
        fontSize: 12,
        fontWeight: 800
      },
      splitArea: {
        areaStyle: {
          color: ['#f8fbff', '#eef6ff']
        }
      },
      splitLine: {
        lineStyle: { color: '#d8e6f6' }
      },
      axisLine: {
        lineStyle: { color: '#d8e6f6' }
      }
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: sections.map((section) => Math.round(section.score * 100) / 100),
            name: '向量化质量',
            symbol: 'circle',
            symbolSize: 6,
            lineStyle: { color: '#2563eb', width: 3 },
            areaStyle: { color: 'rgba(37, 99, 235, 0.18)' },
            itemStyle: { color: '#2563eb' }
          }
        ]
      }
    ]
  } as EChartsOption
})

const projectAuditVectorQualityBarOption = computed<EChartsOption>(() => {
  const rows = projectAuditVectorQualityDocumentRows.value.slice(0, 10)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      confine: true,
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const row = rows[item?.dataIndex || 0]
        return [
          `<strong>${shortText(row?.fileName, '-')}</strong>`,
          `评分：${row?.score || 0}/100`,
          `切片/向量：${row?.chunkCount || 0}/${row?.vectorCount || 0}`,
          `缺口：${row?.vectorGap || 0}`,
          `问题：${row?.issue || '无'}`
        ].join('<br/>')
      }
    },
    grid: { left: 28, right: 20, top: 28, bottom: 72 },
    xAxis: {
      type: 'category',
      data: rows.map((row) => shortText(row.fileName, '-').slice(0, 10)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d8e6f6' } },
      axisLabel: {
        color: '#64748b',
        fontSize: 11,
        fontWeight: 800,
        rotate: rows.length > 5 ? 22 : 0,
        interval: 0
      }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#e6edf7' } },
      axisLabel: { color: '#64748b', fontWeight: 800 }
    },
    series: [
      {
        type: 'bar',
        barWidth: 22,
        data: rows.map((row) => {
          const score = Number(row.score || 0)
          return {
            value: score,
            itemStyle: {
              color: score >= 90 ? '#16a34a' : score >= 80 ? '#f59e0b' : '#dc2626',
              borderRadius: [7, 7, 0, 0]
            }
          }
        }),
        label: {
          show: true,
          position: 'top',
          color: '#334155',
          fontSize: 11,
          fontWeight: 900,
          formatter: '{c}'
        }
      }
    ]
  } as EChartsOption
})

const projectAuditVectorFlowRows = computed(() => {
  const lineageRows = toRecordArray(projectAuditKnowledgeLineage.value.vectorFlow)
  if (lineageRows.length) {
    return lineageRows.map((row, index) => ({
      step: String(row.step || `0${index + 1}`),
      label: String(row.label || '-'),
      description: String(row.description || '-'),
      done: Number(row.done || 0),
      total: Number(row.total || 0),
      tone: String(row.tone || 'blue')
    }))
  }
  const rows = normalizedProjectAuditVectorRows.value
  const total = rows.length
  const ocrReady = rows.filter((row) => String(row.ocrStatus).includes('已识别')).length
  const sliced = rows.filter((row) => String(row.sliceStatus).includes('已切片')).length
  const vectorized = rows.filter((row) => row.readyForRag).length
  const pageIndexed = rows.filter((row) => row.readyForPageIndex).length
  const reviewReady = rows.filter((row) => row.readyForRag && row.readyForPageIndex).length
  return [
    {
      step: '01',
      label: '资料解析',
      description: 'OCR 字段、表格、印章和页面证据已生成',
      done: ocrReady,
      total,
      tone: ocrReady === total ? 'green' : 'orange'
    },
    {
      step: '02',
      label: '知识切片',
      description: '按资料 Profile 拆成可检索片段，保留页码和 bbox',
      done: sliced,
      total,
      tone: sliced === total ? 'green' : 'orange'
    },
    {
      step: '03',
      label: '向量入库',
      description: '向量已写入本地索引，可参与混合检索',
      done: vectorized,
      total,
      tone: vectorized === total ? 'green' : 'orange'
    },
    {
      step: '04',
      label: '章节溯源',
      description: '长文档树节点已构建，可做跨章节依据溯源',
      done: pageIndexed,
      total,
      tone: pageIndexed === total ? 'green' : 'orange'
    },
    {
      step: '05',
      label: '审查可用',
      description: '资料可进入规则、知识检索和 Agent 审查编排',
      done: reviewReady,
      total,
      tone: reviewReady === total ? 'green' : 'red'
    }
  ]
})

const projectAuditVectorSankeyOption = computed<EChartsOption>(() => {
  const rows = normalizedProjectAuditVectorRows.value.slice(0, 6)
  const nodes = new Map<string, Record<string, unknown>>()
  const links = new Map<string, { source: string; target: string; value: number }>()
  const addNode = (name: string, color: string) => {
    if (!nodes.has(name)) {
      nodes.set(name, { name, itemStyle: { color, borderColor: '#ffffff', borderWidth: 2 } })
    }
  }
  const addLink = (source: string, target: string, value = 1) => {
    const key = `${source}->${target}`
    const current = links.get(key)
    if (current) {
      current.value += value
      return
    }
    links.set(key, { source, target, value })
  }

  addNode('资料文件', '#2563eb')
  addNode('OCR 证据', '#f59e0b')
  addNode('知识切片', '#16a34a')
  addNode('向量索引', '#0ea5e9')
  addNode('章节溯源树', '#6366f1')
  addNode('Agent 审查', '#15803d')

  rows.forEach((row) => {
    const fileName = shortText(row.fileName, '资料文件')
    const docNode = `资料 ${row.rowIndex}：${fileName.slice(0, 18)}`
    addNode(docNode, '#3b82f6')
    addLink('资料文件', docNode)
    addLink(docNode, 'OCR 证据')

    if (!String(row.ocrStatus).includes('已识别')) {
      addNode('阻断：OCR 待识别', '#dc2626')
      addLink('OCR 证据', '阻断：OCR 待识别')
      return
    }
    addLink('OCR 证据', '知识切片')

    if (!String(row.sliceStatus).includes('已切片')) {
      addNode('阻断：未切片', '#dc2626')
      addLink('知识切片', '阻断：未切片')
      return
    }
    addLink('知识切片', '向量索引')

    if (!row.readyForRag) {
      addNode('阻断：向量缺口', '#dc2626')
      addLink('向量索引', '阻断：向量缺口')
      return
    }
    addLink('向量索引', '章节溯源树')

    if (!row.readyForPageIndex) {
      addNode('阻断：PI 未构建', '#dc2626')
      addLink('章节溯源树', '阻断：章节树未构建')
      return
    }
    addLink('章节溯源树', 'Agent 审查')
  })

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: any) => {
        if (params.dataType === 'edge') {
          return `${params.data.source}<br/>→ ${params.data.target}<br/>资料数：${params.data.value}`
        }
        return String(params.name || '')
      }
    },
    series: [
      {
        type: 'sankey',
        left: 12,
        right: 18,
        top: 18,
        bottom: 18,
        nodeWidth: 12,
        nodeGap: 11,
        draggable: false,
        data: Array.from(nodes.values()),
        links: Array.from(links.values()),
        label: {
          color: '#172033',
          fontSize: 12,
          fontWeight: 800,
          width: 112,
          overflow: 'truncate'
        },
        lineStyle: {
          color: 'gradient',
          opacity: 0.24,
          curveness: 0.45
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { opacity: 0.55 }
        }
      }
    ]
  } as EChartsOption
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
      action = '补充条款索引或检查元数据过滤条件'
    } else if (pageIndexUsed && pageIndexNodeCount <= 0) {
      issue = '已触发章节溯源但缺少节点'
      action = '重建章节树并校验节点映射'
    } else if (shouldUsePageIndex && !pageIndexUsed) {
      issue = '长文档问题未触发章节溯源'
      action = '检查检索路由器或增加触发规则'
    } else if (fallbackRoute !== '-') {
      issue = '存在回退路由'
      action = '对比章节溯源与混合检索命中质量'
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
        ? '已触发章节溯源'
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

const projectAuditPageIndexFriendlyCards = computed(() =>
  projectAuditPageIndexTraceRows.value.slice(0, 4).map((row, index) => {
    const routeLabel = friendlyTechLabel(row.selectedRoute)
    const fallbackLabel =
      row.fallbackRoute === '-' ? '无回退' : friendlyTechLabel(row.fallbackRoute)
    const nodeCount = Number(row.pageIndexNodeCount || 0)
    const clauseCount = Number(row.selectedClauseCount || 0)
    const ok = row.issue === '无'
    return {
      id: String(row.retrievalTraceId || `pageindex-friendly-${index + 1}`),
      sequence: String(index + 1).padStart(2, '0'),
      queryType: friendlyTechLabel(row.queryType),
      query: shortText(row.query, '暂无检索问题'),
      routeLabel,
      fallbackLabel,
      ok,
      conclusion: ok
        ? `本次检索走 ${routeLabel}，命中 ${nodeCount} 个章节节点、${clauseCount} 条正式依据。`
        : `${row.issue}：${row.action}`,
      facts: [
        { label: '路由选择', value: routeLabel },
        { label: '节点命中', value: `${nodeCount} 个` },
        { label: '条款依据', value: `${clauseCount} 条` },
        { label: '回退策略', value: fallbackLabel }
      ],
      action: String(row.action || '-')
    }
  })
)

const projectAuditPageIndexTreeOption = computed<EChartsOption>(() => {
  const traces = projectAuditPageIndexTraceRows.value.slice(0, 3)
  const children = traces.map((trace, index) => {
    const selectedNodes = toRecordArray(trace.selectedNodes).slice(0, 3)
    const nodeChildren = selectedNodes.length
      ? selectedNodes.map((node) => ({
          name: shortText(node.title || node.nodeId, '命中节点').slice(0, 28),
          value: shortText(node.sectionPath || node.pageRange, '章节节点'),
          itemStyle: { color: '#6366f1' }
        }))
      : [
          {
            name: Number(trace.pageIndexNodeCount || 0) ? '后端未返回节点明细' : '未命中章节节点',
            value: trace.action,
            itemStyle: { color: '#f59e0b' }
          }
        ]
    return {
      name: `检索 ${String(index + 1).padStart(2, '0')}`,
      value: shortText(trace.query, '-'),
      itemStyle: { color: trace.issue === '无' ? '#2563eb' : '#f59e0b' },
      children: [
        {
          name: `问题：${friendlyTechLabel(trace.queryType)}`,
          value: trace.query,
          itemStyle: { color: '#0ea5e9' }
        },
        {
          name: `路由：${friendlyTechLabel(trace.selectedRoute)}`,
          value:
            trace.fallbackRoute === '-'
              ? '未触发回退'
              : `回退 ${friendlyTechLabel(trace.fallbackRoute)}`,
          itemStyle: { color: trace.pageIndexUsed ? '#16a34a' : '#f59e0b' }
        },
        {
          name: `节点：${Number(trace.pageIndexNodeCount || 0)} 个`,
          value: '章节、附录或表格节点',
          itemStyle: { color: '#6366f1' },
          children: nodeChildren
        },
        {
          name: `条款：${Number(trace.selectedClauseCount || 0)} 条`,
          value: shortText(trace.linkedClauseIds, '-'),
          itemStyle: { color: Number(trace.selectedClauseCount || 0) ? '#15803d' : '#dc2626' }
        },
        {
          name: trace.issue === '无' ? '结论：可用于审查' : `处理：${trace.issue}`,
          value: trace.action,
          itemStyle: { color: trace.issue === '无' ? '#16a34a' : '#dc2626' }
        }
      ]
    }
  })

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: any) =>
        [`<strong>${params.name}</strong>`, shortText(params.data?.value, '')]
          .filter(Boolean)
          .join('<br/>')
    },
    series: [
      {
        type: 'tree',
        data: [
          {
            name: '章节溯源检索审计',
            value: '从问题分类到路由、章节节点、正式条款和处理建议',
            itemStyle: { color: '#172033' },
            children
          }
        ],
        left: 36,
        right: 260,
        top: 32,
        bottom: 32,
        orient: 'LR',
        roam: true,
        scaleLimit: { min: 0.7, max: 1.6 },
        expandAndCollapse: false,
        initialTreeDepth: 4,
        symbol: 'roundRect',
        symbolSize: [126, 34],
        edgeShape: 'polyline',
        edgeForkPosition: '62%',
        lineStyle: {
          color: '#a7bddb',
          width: 1.5,
          curveness: 0.12
        },
        label: {
          position: 'inside',
          color: '#ffffff',
          fontSize: 11,
          fontWeight: 800,
          lineHeight: 14,
          width: 108,
          overflow: 'truncate'
        },
        leaves: {
          label: {
            position: 'right',
            color: '#26364e',
            fontSize: 11,
            fontWeight: 800,
            lineHeight: 14,
            width: 150,
            overflow: 'truncate'
          }
        },
        emphasis: {
          focus: 'descendant'
        }
      }
    ]
  } as EChartsOption
})

const projectAuditPageIndexFlowRows = computed(() => {
  const lineageRows = toRecordArray(projectAuditKnowledgeLineage.value.pageIndexFlow)
  if (lineageRows.length) {
    return lineageRows.map((row, index) => ({
      step: String(row.step || `0${index + 1}`),
      label: String(row.label || '-'),
      description: String(row.description || '-'),
      value: String(row.value || '-'),
      tone: String(row.tone || 'blue')
    }))
  }
  const traces = projectAuditPageIndexTraceRows.value
  const traceCount = traces.length
  const shouldUse = traces.filter((row) => row.shouldUsePageIndex).length
  const used = traces.filter((row) => row.pageIndexUsed).length
  const nodeHits = traces.reduce((sum, row) => sum + Number(row.pageIndexNodeCount || 0), 0)
  const clauseHits = traces.reduce((sum, row) => sum + Number(row.selectedClauseCount || 0), 0)
  const issues = projectAuditPageIndexIssueRows.value.length
  return [
    {
      step: '01',
      label: '问题分类',
      description: shouldUse
        ? `${shouldUse} 个长文档/跨章节问题需要章节溯源`
        : '当前问题可由普通条款检索处理',
      value: `${shouldUse}/${traceCount}`,
      tone: shouldUse ? 'blue' : 'green'
    },
    {
      step: '02',
      label: '路由选择',
      description: '检索路由器在条款索引、混合检索和章节溯源之间选择路径',
      value: `${used} 次`,
      tone: used >= shouldUse ? 'green' : 'orange'
    },
    {
      step: '03',
      label: '节点定位',
      description: '定位章节、附录或表格节点，并保留页码范围',
      value: `${nodeHits} 节点`,
      tone: nodeHits ? 'green' : 'orange'
    },
    {
      step: '04',
      label: '条款映射',
      description: '把命中节点映射回正式条款，供审查草稿引用',
      value: `${clauseHits} 条款`,
      tone: clauseHits ? 'green' : 'orange'
    },
    {
      step: '05',
      label: '质量判断',
      description: issues
        ? '存在路由或覆盖缺口，需要补构建或调规则'
        : '路由、节点和条款映射可用于审查',
      value: issues ? `${issues} 缺口` : '可用',
      tone: issues ? 'red' : 'green'
    }
  ]
})

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
                ? '已触发章节溯源，但后端未返回节点明细'
                : '未触发章节溯源',
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
    coverageIssue: row.readyForPageIndex ? '无' : '资料未形成章节节点',
    coverageAction: row.readyForPageIndex ? '可参与长文档溯源' : '先完成切片和章节树构建'
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
      label: '章节溯源触发',
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
      hint: '路由追踪关联条款数量',
      tone: mappedClauses ? 'blue' : 'red'
    },
    {
      label: '资料覆盖',
      value: `${coveredDocuments}/${projectAuditPageIndexCoverageRows.value.length}`,
      hint: '已构建章节溯源的资料',
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
    label: '编排节点',
    value: String(reviewGraphNodes.value.length),
    hint: 'Agent 内层执行节点',
    tone: reviewGraphNodes.value.length ? 'green' : 'orange'
  },
  {
    label: '依赖边',
    value: String(reviewGraphEdges.value.length),
    hint: '节点依赖关系',
    tone: 'blue'
  },
  {
    label: 'Temporal 事件',
    value: String(selectedReviewTemporal.value.eventCount || reviewGraphTimeline.value.length || 0),
    hint: '外层持久化工作流',
    tone: 'green'
  },
  {
    label: '检查点',
    value: friendlyTechLabel(selectedReviewRun.value?.run.graphExecution?.checkpointer),
    hint: '本地开发态建议使用 PostgreSQL 检查点',
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

const langGraphStageDefs = [
  {
    key: 'context',
    label: '上下文',
    hint: '读取项目、节点、批次和资料版本',
    tone: 'blue'
  },
  {
    key: 'ocr',
    label: 'OCR 证据',
    hint: '加载字段、表格、印章和 bbox',
    tone: 'orange'
  },
  {
    key: 'rules',
    label: '规则核对',
    hint: '执行确定性缺项、错项和状态规则',
    tone: 'green'
  },
  {
    key: 'retrieval',
    label: '知识检索',
    hint: '条款索引 / 混合检索 / 章节溯源取依据',
    tone: 'blue'
  },
  {
    key: 'llm',
    label: 'LLM 草稿',
    hint: '生成结构化审查发现草稿',
    tone: 'green'
  },
  {
    key: 'cog',
    label: 'COG 思考摘要',
    hint: '公开可审计的推理摘要，不展示模型内部隐式思维',
    tone: 'blue'
  },
  {
    key: 'validation',
    label: '质量门禁',
    hint: 'Schema、证据、依据和 Critic 校验',
    tone: 'orange'
  },
  {
    key: 'human',
    label: '人工确认',
    hint: '持久化草稿并等待监检员确认',
    tone: 'blue'
  }
] as const

const langGraphStageKey = (nodeKey: string) => {
  const key = nodeKey.toLowerCase()
  if (key.includes('ocr')) return 'ocr'
  if (key.includes('rule') || key.includes('consistency')) return 'rules'
  if (
    key.includes('knowledge') ||
    key.includes('retriev') ||
    key.includes('rag') ||
    key.includes('pageindex')
  ) {
    return 'retrieval'
  }
  if (
    key.includes('prompt') ||
    key.includes('llm') ||
    key.includes('finding') ||
    key.includes('generate') ||
    key.includes('aggregate')
  ) {
    return 'llm'
  }
  if (
    key.includes('validation') ||
    key.includes('validator') ||
    key.includes('critic') ||
    key.includes('quality') ||
    key.includes('gate')
  ) {
    return 'validation'
  }
  if (
    key.includes('cog') ||
    key.includes('reasoning') ||
    key.includes('thought') ||
    key.includes('summary')
  ) {
    return 'cog'
  }
  if (key.includes('persist') || key.includes('human') || key.includes('draft')) return 'human'
  return 'context'
}

const langGraphStatusTone = (status: unknown): FdeTone => {
  const value = String(status || '').toLowerCase()
  if (
    ['succeeded', 'success', 'completed', 'complete', 'done', 'pass', 'passed'].some((token) =>
      value.includes(token)
    )
  ) {
    return 'green'
  }
  if (['failed', 'fail', 'error', 'blocked', 'rejected'].some((token) => value.includes(token))) {
    return 'red'
  }
  if (
    ['running', 'queued', 'waiting', 'review', 'warning'].some((token) => value.includes(token))
  ) {
    return 'orange'
  }
  return 'blue'
}

const langGraphFlowGroups = computed(() => {
  const nodes = reviewGraphNodes.value.map((raw, index) => {
    const node = toRecord(raw)
    const nodeKey = String(node.nodeKey || node.id || node.name || `node-${index + 1}`)
    const toolCalls = toRecordArray(node.toolCalls)
    const artifactCounts = toRecord(node.artifactCounts)
    const duration = Number(node.durationMs || node.latencyMs || 0)
    const status = node.status || 'unknown'
    return {
      id: nodeKey,
      sequence: index + 1,
      nodeKey,
      label: friendlyTechLabel(node.label || node.title || nodeKey),
      status,
      statusLabel: friendlyStatus(status),
      tone: langGraphStatusTone(status),
      queue: friendlyTaskQueueLabel(node.taskQueue || node.queue || '-'),
      toolCount: toolCalls.length,
      artifactCount:
        Number(artifactCounts.ruleResults || 0) +
        Number(artifactCounts.retrievalTraces || 0) +
        Number(artifactCounts.findingDrafts || 0) +
        Number(artifactCounts.toolCalls || 0),
      durationMs: duration,
      durationText: duration ? `${duration}ms` : '-'
    }
  })
  if (normalizedReviewReasoningRows.value.length) {
    const toolCount = normalizedReviewReasoningRows.value.reduce(
      (sum, row) => sum + Number(row.toolCount || 0),
      0
    )
    nodes.push({
      id: 'cog_reasoning_summary',
      sequence: nodes.length + 1,
      nodeKey: 'cog_reasoning_summary',
      label: 'COG 思考摘要',
      status: 'completed',
      statusLabel: '已记录',
      tone: 'blue',
      queue: '审查编排服务',
      toolCount,
      artifactCount: normalizedReviewReasoningRows.value.length,
      durationMs: 0,
      durationText: '-'
    })
  }
  return langGraphStageDefs.map((stage, index) => {
    const stageNodes = nodes.filter((node) => langGraphStageKey(node.nodeKey) === stage.key)
    const hasNodes = stageNodes.length > 0
    const hasFailed = stageNodes.some((node) => node.tone === 'red')
    const hasWaiting = stageNodes.some((node) => node.tone === 'orange')
    const status = !hasNodes ? '未返回' : hasFailed ? '需处理' : hasWaiting ? '处理中' : '已完成'
    const tone = !hasNodes ? 'blue' : hasFailed ? 'red' : hasWaiting ? 'orange' : stage.tone
    return {
      ...stage,
      index: index + 1,
      nodes: stageNodes,
      nodeCount: stageNodes.length,
      toolCount: stageNodes.reduce((sum, node) => sum + node.toolCount, 0),
      artifactCount: stageNodes.reduce((sum, node) => sum + node.artifactCount, 0),
      durationMs: stageNodes.reduce((sum, node) => sum + node.durationMs, 0),
      status,
      tagType: (tone === 'green'
        ? 'success'
        : tone === 'red'
          ? 'danger'
          : tone === 'orange'
            ? 'warning'
            : 'info') as FdeElTagType,
      tone
    }
  })
})

const hasLangGraphFlowNodes = computed(() =>
  langGraphFlowGroups.value.some((group) => group.nodeCount > 0)
)

const reviewTimelineChartRows = computed(() => {
  const timelineRows = reviewGraphTimeline.value.length
    ? reviewGraphTimeline.value.map((row, index) => {
        const item = toRecord(row)
        const stepName = String(item.stepName || item.nodeKey || item.name || `step-${index + 1}`)
        const duration = Number(item.durationMs || item.latencyMs || 0)
        return {
          id: stepName,
          label: friendlyTechLabel(stepName),
          status: item.status || 'unknown',
          statusLabel: friendlyStatus(item.status, '未知'),
          queue: friendlyTaskQueueLabel(item.taskQueue || item.queue || '-'),
          startedAt: shortText(item.startedAt, '-'),
          durationMs: duration,
          displayDuration: duration || 80
        }
      })
    : langGraphFlowGroups.value.flatMap((group) =>
        group.nodes.map((node) => ({
          id: node.id,
          label: node.label,
          status: node.status,
          statusLabel: node.statusLabel,
          queue: node.queue,
          startedAt: '-',
          durationMs: node.durationMs,
          displayDuration: node.durationMs || 80
        }))
      )
  return timelineRows.slice(0, 10)
})

const langGraphToneColor = (tone: FdeTone) => {
  if (tone === 'green') return '#16a34a'
  if (tone === 'orange') return '#f59e0b'
  if (tone === 'red') return '#dc2626'
  return '#2563eb'
}

const reviewTimelineEchartOption = computed<EChartsOption>(() => {
  const rows = reviewTimelineChartRows.value
  return {
    backgroundColor: 'transparent',
    grid: { left: 108, right: 36, top: 16, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      confine: true,
      formatter: (params: any) => {
        const item = Array.isArray(params) ? params[0] : params
        const row = rows[item?.dataIndex || 0]
        return [
          `<strong>${row?.label || '-'}</strong>`,
          `状态：${row?.statusLabel || '-'}`,
          `队列：${row?.queue || '-'}`,
          `开始：${row?.startedAt || '-'}`,
          `耗时：${row?.durationMs ? `${row.durationMs}ms` : '等待/未返回'}`
        ].join('<br/>')
      }
    },
    xAxis: {
      type: 'value',
      name: '耗时 ms',
      nameTextStyle: { color: '#64748b', fontWeight: 800 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#e6edf7' } },
      axisLabel: { color: '#64748b' }
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      inverse: true,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#475569', fontWeight: 800, width: 96, overflow: 'truncate' }
    },
    series: [
      {
        type: 'bar',
        data: rows.map((row) => ({
          value: row.displayDuration,
          itemStyle: {
            color: langGraphToneColor(langGraphStatusTone(row.status))
          },
          label: {
            show: true,
            position: 'right',
            color: '#334155',
            fontSize: 11,
            fontWeight: 800,
            formatter: row.durationMs ? `${row.durationMs}ms` : row.statusLabel
          }
        })),
        barWidth: 14,
        itemStyle: { borderRadius: [0, 7, 7, 0] }
      }
    ]
  } as EChartsOption
})

const langGraphEchartOption = computed<EChartsOption>(() => {
  const stageYGap = 48
  const nodeXGap = 178
  const centerX = 430
  const baseY = 34
  const chartNodes = langGraphFlowGroups.value.flatMap((group, groupIndex) => {
    const nodes = group.nodes.length
      ? group.nodes
      : [
          {
            id: `${group.key}-empty`,
            sequence: group.index,
            nodeKey: `${group.key}-empty`,
            label: group.label,
            status: 'missing',
            statusLabel: '未返回',
            tone: 'blue' as FdeTone,
            queue: '-',
            toolCount: 0,
            artifactCount: 0,
            durationMs: 0,
            durationText: '-'
          }
        ]
    const offset = ((nodes.length - 1) * nodeXGap) / 2
    return nodes.map((node, nodeIndex) => ({
      name: node.id,
      value: node.label,
      x: centerX + nodeIndex * nodeXGap - offset,
      y: baseY + groupIndex * stageYGap,
      symbolSize: node.id.includes('-empty') ? [136, 34] : [160, 38],
      category: group.label,
      itemStyle: {
        color: node.id.includes('-empty') ? '#ffffff' : langGraphToneColor(node.tone),
        borderColor: node.id.includes('-empty') ? '#bfd2ea' : '#ffffff',
        borderWidth: node.id.includes('-empty') ? 1.5 : 3,
        shadowBlur: node.id.includes('-empty') ? 0 : 12,
        shadowColor: `${langGraphToneColor(node.tone)}33`
      },
      label: {
        show: true,
        formatter: node.label,
        color: node.id.includes('-empty') ? '#64748b' : '#ffffff',
        fontSize: 11,
        fontWeight: 800,
        lineHeight: 15,
        width: node.id.includes('-empty') ? 110 : 132,
        overflow: 'truncate' as const
      },
      meta: {
        stage: group.label,
        status: node.statusLabel,
        queue: node.queue,
        tools: node.toolCount,
        artifacts: node.artifactCount,
        duration: node.durationText
      }
    }))
  })
  const nonEmptyNodes = chartNodes.filter((node) => !String(node.name).includes('-empty'))
  const fallbackLinks = nonEmptyNodes
    .slice(1)
    .map((node, index) => ({
      source: String(nonEmptyNodes[index]?.name || ''),
      target: String(node.name)
    }))
    .filter((edge) => edge.source && edge.target)
  const links = fallbackLinks.map((edge) => ({
    ...edge,
    lineStyle: { color: '#8fb1df', width: 2, curveness: 0.08 }
  }))
  const stageLabels = langGraphFlowGroups.value.map((group, index) => ({
    type: 'text',
    left: 14,
    top: baseY + index * stageYGap - 12,
    style: {
      text: `${String(group.index).padStart(2, '0')} ${group.label}`,
      fill: langGraphToneColor(group.tone as FdeTone),
      font: '900 11px sans-serif',
      backgroundColor: '#ffffff',
      borderColor: '#dbe8f7',
      borderWidth: 1,
      borderRadius: 6,
      padding: [4, 7]
    },
    silent: true
  }))
  return {
    backgroundColor: 'transparent',
    graphic: stageLabels,
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (params: any) => {
        const meta = params.data?.meta
        if (!meta) return params.name
        return [
          `<strong>${params.data.value}</strong>`,
          `阶段：${meta.stage}`,
          `状态：${meta.status}`,
          `队列：${meta.queue}`,
          `工具：${meta.tools} 次`,
          `产物：${meta.artifacts} 个`,
          `耗时：${meta.duration}`
        ].join('<br/>')
      }
    },
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        scaleLimit: { min: 0.65, max: 1.8 },
        draggable: false,
        edgeSymbol: ['circle', 'arrow'],
        edgeSymbolSize: [3, 9],
        symbol: 'roundRect',
        data: chartNodes,
        links,
        lineStyle: {
          opacity: 0.82,
          width: 2,
          curveness: 0.18
        },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 4 }
        }
      }
    ]
  } as EChartsOption
})

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
      sourceTask: row,
      rowIndex: index + 1,
      taskId: item.taskId,
      caseId: item.caseId,
      scenario: friendlyTechLabel(item.scenario),
      profileId: friendlyTechLabel(item.profileId),
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
      blockerText: blockers.length ? friendlyIssueList(blockers, '无') : '无',
      readyForEval: Boolean(item.readyForEval),
      annotationTargetText: `字段 ${Number(candidateCounts.fields || 0)} · 表格 ${Number(candidateCounts.tables || 0)} · 印章 ${Number(candidateCounts.seals || 0)}`,
      annotationProgressText: `${labelTotal}/${candidateTotal || 0}`,
      annotationReasonText: blockers.length
        ? friendlyIssueList(blockers, '无')
        : candidateTotal > labelTotal
          ? `还有 ${Math.max(0, candidateTotal - labelTotal)} 个候选对象未确认`
          : item.readyForEval
            ? '已形成标准答案，可进入评估集'
            : '等待二审确认后入评估集',
      annotationNextAction: blockers.length
        ? '打开样本，处理阻断'
        : candidateTotal > labelTotal
          ? '补齐字段/表格/印章'
          : item.readyForEval
            ? '二审或入评估集'
            : '提交二审',
      priorityTone: blockers.length || candidateTotal > labelTotal ? 'orange' : 'green'
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
      action: row.gapTotal
        ? '打开样本，补齐字段/表格/印章标准答案'
        : row.blockerText !== '无'
          ? '处理阻断原因后再提交二审'
          : row.readyForEval
            ? '二审后进入评估集'
            : '补齐人工标注、bbox 和阻断归因',
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

const projectAuditAnnotationWorkflowRows = computed(() => {
  const summary = projectAuditAnnotationSummary.value
  const issueCount = projectAuditAnnotationIssueRows.value.length
  return [
    {
      step: '01',
      title: '选样本',
      description: '先从低置信、缺 bbox、表格/印章异常的 OCR 结果里选样本。',
      metric: `${summary.total} 个样本`,
      done: summary.total > 0
    },
    {
      step: '02',
      title: '核对标准答案',
      description: '确认字段值、表格单元格、印章名称和页面坐标是否正确。',
      metric: `${summary.labelTotal}/${summary.candidateTotal || 0} 已确认`,
      done: summary.gapTotal === 0 && summary.candidateTotal > 0
    },
    {
      step: '03',
      title: '处理缺口',
      description: '缺字段、缺表格、缺印章或证据框不准的样本，先补齐再二审。',
      metric: `${issueCount} 个待处理`,
      done: issueCount === 0
    },
    {
      step: '04',
      title: '进入评估',
      description: '二审通过的样本进入 OCR Regression Set，用来考核 Profile 和引擎版本。',
      metric: `${summary.readyForEval} 个可入评估`,
      done: summary.readyForEval > 0
    }
  ]
})

const projectAuditAnnotationPrimaryAction = computed(() => {
  const firstIssue = projectAuditAnnotationIssueRows.value[0]
  if (firstIssue) {
    return {
      title: firstIssue.issue,
      description: firstIssue.action,
      tone: 'orange' as const
    }
  }
  if (projectAuditAnnotationSummary.value.readyForEval) {
    return {
      title: '样本已可用于评估',
      description: '可以进入准确率评估页，重跑 OCR Regression Set。',
      tone: 'green' as const
    }
  }
  return {
    title: '等待生成 OCR 标注样本',
    description: '先运行 OCR 解析或从低置信字段创建样本。',
    tone: 'blue' as const
  }
})

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
      '补充漏检样本和规则/提示词修正'
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
      '检查混合检索 / 章节溯源路由和条款索引'
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
    label: '章节溯源',
    description: '查看长文档树检索路径、命中节点和条款映射。'
  },
  {
    key: 'langgraph' as const,
    label: 'LangGraph 可视化',
    description: '查看流程编排、Agent 节点、边和检查点。'
  },
  {
    key: 'ocr-labeling' as const,
    label: 'OCR 打标',
    description: '查看 OCR 任务、标注样本、字段/表格/印章人工修正。'
  },
  {
    key: 'evaluation' as const,
    label: '准确率评估',
    description: '查看 OCR、检索、章节溯源、Agent 的质量门禁和失败样本。'
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
        label: '检索溯源',
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
        label: '审查任务',
        value: String(projectAuditReviewRuns.value.length),
        tone: 'blue' as const
      },
      { label: '编排节点', value: String(reviewGraphNodes.value.length), tone: 'green' as const },
      {
        label: '检查点',
        value: friendlyTechLabel(selectedReviewRun.value?.run.graphExecution?.checkpointer),
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
const projectAuditNodeStatusBarRows = computed(() => {
  const rows = nodeStatusSummary.value.length
    ? nodeStatusSummary.value
    : [{ status: '暂无节点', count: 0 }]
  const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0)
  const max = Math.max(...rows.map((row) => Number(row.count || 0)), 0)
  return rows.map((row) => {
    const status = String(row.status || '')
    const tone =
      status.includes('通过') || status.includes('归档')
        ? 'green'
        : status.includes('补正') || status.includes('人工') || status.includes('阻断')
          ? 'red'
          : status.includes('预审') || status.includes('待审') || status.includes('提交')
            ? 'orange'
            : 'blue'
    const count = Number(row.count || 0)
    return {
      ...row,
      tone,
      percent: total ? Math.round((count / total) * 100) : 0,
      barPercent: max ? Math.max(3, Math.round((count / max) * 100)) : 0,
      ratioText: total ? `${Math.round((count / total) * 100)}%` : '0%'
    }
  })
})
const projectAuditCapabilityRows = computed(() => {
  const documents = Math.max(projectAuditDocuments.value.length, 1)
  const vectorized = Number(projectAuditMetrics.value.vectorizedDocuments || 0)
  const pageIndexNodes = Number(projectAuditMetrics.value.pageIndexNodes || 0)
  const lowConfidenceFields = Number(projectAuditMetrics.value.lowConfidenceFields || 0)
  const rows = [
    {
      key: 'ocr',
      label: 'OCR 解析',
      value: `${projectAuditOcrJobs.value.length} 个任务`,
      status: projectAuditOcrJobs.value.length ? '已接入' : '待接入',
      evidence: `低置信字段 ${lowConfidenceFields}，标注样本 ${projectAuditAnnotationTasks.value.length}`,
      blockers: projectAuditBlockers.value.filter((row) =>
        String(row.type || '')
          .toLowerCase()
          .includes('ocr')
      ).length,
      tone: projectAuditOcrJobs.value.length ? ('green' as const) : ('orange' as const),
      subpage: 'ocr-labeling' as ProjectAuditSubpage,
      score: projectAuditOcrJobs.value.length ? (lowConfidenceFields ? 76 : 92) : 36
    },
    {
      key: 'vectorization',
      label: '资料向量化',
      value: `${vectorized}/${documents} 份`,
      status: vectorized >= documents ? '已完成' : '待补齐',
      evidence: `切片 ${projectAuditMetrics.value.knowledgeChunks || 0}，向量 ${projectAuditMetrics.value.knowledgeVectors || 0}`,
      blockers: projectAuditVectorIssueRows.value.length,
      tone: vectorized >= documents ? ('green' as const) : ('orange' as const),
      subpage: 'vectorization' as ProjectAuditSubpage,
      score: Math.round((vectorized / documents) * 100)
    },
    {
      key: 'pageindex',
      label: '章节溯源',
      value: `${pageIndexNodes} 个节点`,
      status: pageIndexNodes ? '已构建' : '待构建',
      evidence: `溯源 ${projectAuditPageIndexTraceRows.value.length}，依据 ${projectAuditPageIndexCards.value[2]?.value || 0}`,
      blockers: projectAuditPageIndexIssueRows.value.length,
      tone: pageIndexNodes ? ('green' as const) : ('orange' as const),
      subpage: 'pageindex' as ProjectAuditSubpage,
      score: pageIndexNodes ? (projectAuditPageIndexIssueRows.value.length ? 78 : 94) : 32
    },
    {
      key: 'langgraph',
      label: 'Agent 编排',
      value: `${projectAuditReviewRuns.value.length} 个任务`,
      status: projectAuditLangGraphIssueRows.value.length ? '需补证据' : '链路完整',
      evidence: `Graph ${reviewGraphNodes.value.length} 节点，缺口 ${projectAuditLangGraphIssueRows.value.length}`,
      blockers: projectAuditLangGraphIssueRows.value.length,
      tone: projectAuditLangGraphIssueRows.value.length ? ('orange' as const) : ('green' as const),
      subpage: 'langgraph' as ProjectAuditSubpage,
      score: projectAuditLangGraphIssueRows.value.length ? 72 : 96
    },
    {
      key: 'evaluation',
      label: '准确率评估',
      value: `${projectAuditEvaluationCards.value[0]?.value || '-'} / ${projectAuditEvaluationCards.value[1]?.value || '-'}`,
      status: projectAuditEvaluationIssueRows.value.length ? '门禁待处理' : '可验收',
      evidence: `评估门禁 ${projectAuditEvaluationGateRows.value.length}，阻断 ${projectAuditBlockers.value.length}`,
      blockers: projectAuditEvaluationIssueRows.value.length,
      tone: projectAuditEvaluationIssueRows.value.length ? ('red' as const) : ('green' as const),
      subpage: 'evaluation' as ProjectAuditSubpage,
      score: projectAuditEvaluationIssueRows.value.length ? 70 : 94
    }
  ]
  return rows
})
const projectAuditCapabilityOption = computed<EChartsOption>(() => ({
  aria: {
    enabled: true,
    description:
      'AI 能力健康评分柱状图，展示 OCR、资料向量化、章节溯源、Agent 编排和准确率评估状态。'
  },
  color: ['#2563eb'],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    formatter: (params) => {
      const item = Array.isArray(params) ? params[0] : params
      const row = projectAuditCapabilityRows.value.find((entry) => entry.label === item?.name)
      return `${item?.name || '-'}<br/>评分：${Number(item?.value || 0)}/100<br/>${row?.evidence || ''}`
    }
  },
  grid: { top: 12, right: 42, bottom: 12, left: 92, containLabel: true },
  xAxis: {
    type: 'value',
    max: 100,
    splitLine: { lineStyle: { color: '#edf2f7' } },
    axisLabel: { color: '#8a94a6' }
  },
  yAxis: {
    type: 'category',
    data: projectAuditCapabilityRows.value.map((row) => row.label),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#d8e5f5' } },
    axisLabel: {
      color: '#667085',
      fontWeight: 700,
      width: 78,
      overflow: 'truncate'
    }
  },
  series: [
    {
      name: '健康度',
      type: 'bar',
      barMaxWidth: 18,
      data: projectAuditCapabilityRows.value.map((row) => ({
        value: row.score,
        itemStyle: {
          color: row.tone === 'red' ? '#dc2626' : row.tone === 'orange' ? '#f59e0b' : '#16a34a',
          borderRadius: [0, 7, 7, 0]
        }
      })),
      label: { show: true, position: 'right', formatter: '{c}', color: '#172033', fontWeight: 900 }
    }
  ]
}))
const projectAuditRecentTaskRows = computed(() => {
  const rows = [
    ...projectAuditReviewRuns.value.slice(0, 3).map((row) => {
      const raw = toRecord(row)
      return {
        type: 'Agent',
        title: row.reviewRunId || row.id || '审查任务',
        status: row.status || raw.currentStep || '-',
        time: raw.startedAt || raw.createdAt || raw.updatedAt || '-',
        tone: projectAuditLangGraphIssueRows.value.length
          ? ('orange' as const)
          : ('green' as const),
        subpage: 'langgraph' as ProjectAuditSubpage
      }
    }),
    ...projectAuditOcrJobs.value.slice(0, 3).map((row) => ({
      type: 'OCR',
      title: row.jobId || row.id || row.documentVersionId || 'OCR 任务',
      status: row.status || row.parseStatus || '-',
      time: row.finishedAt || row.startedAt || row.createdAt || '-',
      tone: String(row.status || '').includes('fail') ? ('red' as const) : ('orange' as const),
      subpage: 'ocr-labeling' as ProjectAuditSubpage
    })),
    ...projectAuditSubmissions.value.slice(0, 2).map((row) => ({
      type: '批次',
      title: row.batchName || row.submissionId || '提交批次',
      status: row.status || '-',
      time: row.submittedAt || row.updatedAt || '-',
      tone: 'blue' as const,
      subpage: 'overview' as ProjectAuditSubpage
    })),
    ...projectAuditAnnotationTasks.value.slice(0, 2).map((row) => ({
      type: '标注',
      title: row.title || row.taskId || row.id || 'OCR 标注样本',
      status: row.collectionStatus || row.status || '-',
      time: row.updatedAt || row.createdAt || '-',
      tone: 'orange' as const,
      subpage: 'ocr-labeling' as ProjectAuditSubpage
    }))
  ]
  return rows.slice(0, 8)
})
const projectAuditNextActionRows = computed(() => {
  const blockerActions = projectAuditBlockers.value.slice(0, 4).map((row) => ({
    title: shortText(row.title, '质量阻断'),
    description: shortText(row.action, '进入对应子页处理阻断项'),
    tag: blockerTypeLabel(row.type),
    tone: blockerLevelType(row.level) === 'danger' ? ('red' as const) : ('orange' as const),
    subpage: String(row.type || '').includes('ocr')
      ? ('ocr-labeling' as ProjectAuditSubpage)
      : ('langgraph' as ProjectAuditSubpage)
  }))
  const capabilityActions = projectAuditCapabilityRows.value
    .filter((row) => row.blockers || row.tone !== 'green')
    .slice(0, 3)
    .map((row) => ({
      title: `${row.label}：${row.status}`,
      description: row.evidence,
      tag: row.value,
      tone: row.tone,
      subpage: row.subpage
    }))
  return [...blockerActions, ...capabilityActions].slice(0, 5)
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
  selectedVectorFileQuality.value = null
  selectedVectorFileDetail.value = null
  vectorFileQualityDrawerVisible.value = false

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

const openVectorFileQualityDrawer = async (row: Record<string, unknown>) => {
  const versionId = String(row.documentVersionId || row.currentVersionId || '')
  const fileName = String(row.fileName || '')
  selectedVectorFileSourceRow.value = row
  selectedVectorEvidence.value = null
  selectedVectorEvidenceType.value = 'source'
  vectorFileDetailError.value = ''
  const qualityRow =
    projectAuditVectorQualityDocumentRows.value.find(
      (item) => String(item.documentVersionId || item.id || '') === versionId
    ) ||
    projectAuditVectorQualityDocumentRows.value.find(
      (item) => String(item.fileName || '') === fileName
    )
  selectedVectorFileQuality.value = {
    ...row,
    ...(qualityRow || {}),
    knowledgeLineage: row.knowledgeLineage || qualityRow?.knowledgeLineage
  }
  vectorFileQualityDrawerVisible.value = true
  selectedVectorFileDetail.value = null
  if (!selectedFdeProjectId.value || !versionId) return
  vectorFileDetailLoading.value = true
  try {
    const res = await getFdeProjectVectorFileDetailApi(selectedFdeProjectId.value, versionId, {
      pageSize: 80
    })
    if (res?.data) {
      selectedVectorFileDetail.value = res.data
      selectedVectorFileQuality.value = {
        ...selectedVectorFileQuality.value,
        ...res.data
      }
    }
  } catch {
    vectorFileDetailError.value =
      '文件级切片详情加载失败，请检查后端 FDE vector-detail 接口或重试。'
    selectedVectorFileDetail.value = {
      schemaVersion: 'FdeVectorFileDetail@client-fallback',
      documentVersionId: versionId,
      fileName,
      blockers: [vectorFileDetailError.value],
      chunkRows: [],
      retrievalTraceRows: []
    }
  } finally {
    vectorFileDetailLoading.value = false
  }
}

const retryVectorFileDetail = async () => {
  if (selectedVectorFileSourceRow.value) {
    await openVectorFileQualityDrawer(selectedVectorFileSourceRow.value)
  }
}

const selectVectorEvidence = (row: Record<string, unknown>, type: string) => {
  selectedVectorEvidence.value = row
  selectedVectorEvidenceType.value = type
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

const goProjectAuditSubpage = (subpage: ProjectAuditSubpage) => {
  projectAuditSubpage.value = subpage
  void syncProjectAuditRoute(selectedFdeProjectId.value, selectedFdeNodeId.value, subpage)
}

const handleFdeShellMenuSelect = async (item: FdeShellMenuItemPayload) => {
  if (!item.projectId) {
    if (item.route && item.route !== currentFdePath.value) {
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

const normalizeFdeBrowserRoute = async () => {
  if (typeof window === 'undefined') return
  const browserPath = parseFdeBrowserPath()
  if (!browserPath) return
  const hashPath = parseFdeHashPath()
  const hashHasQuery = window.location.hash.includes('?')
  if (hashPath && (hashPath !== '/fde/projects' || hashHasQuery)) return
  if (hashPath === browserPath) return
  const query: Record<string, string> = {}
  window.location.search
    .replace(/^\?/, '')
    .split('&')
    .filter(Boolean)
    .forEach((part) => {
      const [key, value = ''] = part.split('=')
      if (key) query[decodeURIComponent(key)] = decodeURIComponent(value)
    })
  await router.replace({ path: browserPath, query })
}

const hydrateProjectAuditRoute = async () => {
  if (!fdeProjects.value.length) {
    ensureFdeDemoData()
    return
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
  if (!selectedFdeProjectId.value) return
  await loadProjectAuditWorkspace(selectedFdeProjectId.value, selectedFdeNodeId.value)
  if (currentFdePath.value === '/fde/projects') {
    await syncProjectAuditRoute(
      selectedFdeProjectId.value,
      selectedFdeNodeId.value,
      projectAuditSubpage.value,
      true,
      getAuditDetailRouteState()
    )
  }
}

const loadFdeSupportingData = async () => {
  const [
    aiRunRes,
    reviewRunRes,
    feedbackRes,
    evaluationRes,
    bundleRes,
    releaseRes,
    ocrRes,
    ocrRunRes,
    ocrAnnotationRes,
    ocrCapabilityTestRes,
    incidentRes,
    acceptanceRes,
    validationRes,
    accessRes,
    costRes,
    auditRes,
    maskingRes
  ] = await Promise.allSettled([
    listFdeAiRunsApi({ pageSize: 20 }),
    listFdeReviewRunsApi({ pageSize: 20 }),
    listFdeFeedbackApi(),
    getFdeEvaluationSetsApi(),
    getFdeCapabilityBundlesApi(),
    listFdeReleasesApi(),
    getFdeOcrQualityApi(),
    listFdeOcrRunsApi({ pageSize: 20 }),
    listFdeOcrAnnotationTasksApi({ pageSize: 20 }),
    listFdeOcrCapabilityTestRunsApi({ pageSize: 20 }),
    listFdeIncidentsApi(),
    listFdeAcceptanceReportsApi(),
    validateFdeBusinessPacksApi(),
    listFdeAccessGrantsApi(),
    getFdeCostBudgetsApi(),
    getFdeAuditEventsApi({ limit: 50 }),
    getFdeMaskingPoliciesApi()
  ])
  if (aiRunRes.status === 'fulfilled') aiRuns.value = aiRunRes.value.data.items
  if (reviewRunRes.status === 'fulfilled') reviewRuns.value = reviewRunRes.value.data.items
  if (feedbackRes.status === 'fulfilled') feedback.value = feedbackRes.value.data
  if (evaluationRes.status === 'fulfilled') evaluation.value = evaluationRes.value.data
  if (bundleRes.status === 'fulfilled') bundles.value = bundleRes.value.data
  if (releaseRes.status === 'fulfilled') releases.value = releaseRes.value.data
  if (ocrRes.status === 'fulfilled') ocrQuality.value = ocrRes.value.data
  if (ocrRunRes.status === 'fulfilled') ocrRuns.value = ocrRunRes.value.data.items
  if (ocrAnnotationRes.status === 'fulfilled') ocrAnnotation.value = ocrAnnotationRes.value.data
  if (ocrCapabilityTestRes.status === 'fulfilled') {
    ocrCapabilityTestRuns.value = ocrCapabilityTestRes.value.data.items
  }
  if (incidentRes.status === 'fulfilled') incidentPayload.value = incidentRes.value.data
  if (acceptanceRes.status === 'fulfilled') acceptanceReports.value = acceptanceRes.value.data
  if (validationRes.status === 'fulfilled') packValidation.value = validationRes.value.data
  if (accessRes.status === 'fulfilled') accessGrants.value = accessRes.value.data
  if (costRes.status === 'fulfilled') costGovernance.value = costRes.value.data
  if (auditRes.status === 'fulfilled') auditEvents.value = auditRes.value.data.events
  if (maskingRes.status === 'fulfilled') maskingPolicies.value = maskingRes.value.data

  selectedFeedback.value = selectedFeedback.value || feedback.value[0] || null
  selectedBundleId.value = selectedBundleId.value || firstBundleId.value
  selectedReleaseId.value = selectedReleaseId.value || firstReleaseId.value
  selectedBusinessPackId.value = selectedBusinessPackId.value || firstPackId.value
  selectedIncidentId.value = selectedIncidentId.value || String(incidents.value[0]?.id || '')

  await Promise.allSettled([
    aiRuns.value[0]?.id ? loadRunDetail(aiRuns.value[0].id) : Promise.resolve(),
    firstReviewRunId.value ? loadReviewRunDetail(firstReviewRunId.value) : Promise.resolve(),
    firstEvaluationRunId.value
      ? loadEvaluationReportDetail(firstEvaluationRunId.value)
      : Promise.resolve((selectedEvaluationReport.value = null)),
    firstOcrJobId.value ? loadOcrRunDetail(firstOcrJobId.value) : Promise.resolve(),
    !selectedOcrCapabilityTestRunId.value && preferredOcrCapabilityTestRun()?.runId
      ? loadOcrCapabilityTestDetail(String(preferredOcrCapabilityTestRun()?.runId))
      : Promise.resolve(),
    activeBundleId.value ? loadCapabilityBundleDiff(activeBundleId.value) : Promise.resolve(),
    activeReleaseId.value ? loadReleaseImpact(activeReleaseId.value) : Promise.resolve(),
    activeBusinessPackId.value
      ? loadBusinessPackDiff(activeBusinessPackId.value)
      : Promise.resolve()
  ])
  await restoreAuditDetailFromRoute()
}

const loadOcrQualitySnapshot = async () => {
  const res = await getFdeOcrQualityApi()
  ocrQuality.value = res.data
}

const loadOcrWorkbenchPageData = async () => {
  ocrCapabilityRecordsLoading.value = true
  try {
    const [
      dashboardRes,
      projectRes,
      reviewRunRes,
      ocrRunRes,
      ocrAnnotationRes,
      ocrCapabilityTestRes
    ] = await Promise.allSettled([
      getFdeDashboardApi(),
      listFdeProjectsApi(),
      listFdeReviewRunsApi({ pageSize: 20 }),
      listFdeOcrRunsApi({ pageSize: 20 }),
      listFdeOcrAnnotationTasksApi({ pageSize: 20 }),
      listFdeOcrCapabilityTestRunsApi({ pageSize: 20 })
    ])

    if (dashboardRes.status === 'fulfilled') {
      dashboard.value = dashboardRes.value.data
    }
    if (projectRes.status !== 'fulfilled') {
      throw projectRes.reason
    }
    fdeProjects.value = projectRes.value.data
    if (reviewRunRes.status === 'fulfilled') reviewRuns.value = reviewRunRes.value.data.items
    if (ocrRunRes.status === 'fulfilled') ocrRuns.value = ocrRunRes.value.data.items
    if (ocrAnnotationRes.status === 'fulfilled') ocrAnnotation.value = ocrAnnotationRes.value.data
    if (ocrCapabilityTestRes.status === 'fulfilled') {
      ocrCapabilityTestRuns.value = ocrCapabilityTestRes.value.data.items
    }
  } finally {
    ocrCapabilityRecordsLoading.value = false
  }

  const preferredRun = preferredOcrCapabilityTestRun()
  if (!selectedOcrCapabilityTestRunId.value && preferredRun?.runId) {
    void loadOcrCapabilityTestDetail(preferredRun.runId, false).catch(() => undefined)
  }

  void loadOcrQualitySnapshot().catch(() => undefined)
  void hydrateProjectAuditRoute().catch(() => undefined)
}

const loadProjectAuditPageData = async () => {
  const [dashboardRes, projectRes] = await Promise.allSettled([
    getFdeDashboardApi(),
    listFdeProjectsApi()
  ])
  if (dashboardRes.status === 'fulfilled') {
    dashboard.value = dashboardRes.value.data
  }
  if (projectRes.status !== 'fulfilled') {
    throw projectRes.reason
  }
  fdeProjects.value = projectRes.value.data
  await hydrateProjectAuditRoute()
  void loadFdeSupportingData()
}

const loadFullFdeData = async () => {
  const [dashboardRes, projectRes] = await Promise.all([getFdeDashboardApi(), listFdeProjectsApi()])
  dashboard.value = dashboardRes.data
  fdeProjects.value = projectRes.data
  await loadFdeSupportingData()
  await hydrateProjectAuditRoute()
}

const loadData = async () => {
  loading.value = true
  error.value = ''
  try {
    if (currentFdePath.value === '/fde/projects') {
      await loadProjectAuditPageData()
    } else if (isFdeRoute('ocr-quality')) {
      await loadOcrWorkbenchPageData()
    } else {
      await loadFullFdeData()
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

const clearOcrCapabilityPdfPagePreview = () => {
  if (ocrCapabilityPdfPageObjectUrl.value) {
    URL.revokeObjectURL(ocrCapabilityPdfPageObjectUrl.value)
    ocrCapabilityPdfPageObjectUrl.value = ''
  }
  ocrCapabilityPdfPageObjectKey.value = ''
  ocrCapabilityPdfPagePreviewLoading.value = false
  ocrCapabilityPdfPagePreviewError.value = ''
}

const loadOcrCapabilityPdfPagePreview = async (
  detail: FdeOcrCapabilityTestDetailPayload | null
) => {
  const preview = detail?.preview
  const runId = String(detail?.run?.runId || detail?.run?.id || '')
  const pagePreviewUrl = String(preview?.pagePreviewUrl || '')
  if (preview?.previewType !== 'pdf' || !runId || !pagePreviewUrl) {
    clearOcrCapabilityPdfPagePreview()
    return
  }
  const previewKey = `${runId}:${pagePreviewUrl}`
  if (ocrCapabilityPdfPageObjectKey.value === previewKey && ocrCapabilityPdfPageObjectUrl.value) {
    return
  }
  clearOcrCapabilityPdfPagePreview()
  ocrCapabilityPdfPageObjectKey.value = previewKey
  ocrCapabilityPdfPagePreviewLoading.value = true
  ocrCapabilityPdfPagePreviewError.value = ''
  try {
    const response = await getFdeOcrCapabilityTestPagePreviewApi(runId, { pageNo: 1 })
    const blob = response?.data instanceof Blob ? response.data : new Blob([response?.data || ''])
    if (!String(blob.type || '').startsWith('image/')) {
      throw new Error('PDF 页图预览返回的不是图片。')
    }
    const objectUrl = URL.createObjectURL(blob)
    if (ocrCapabilityPdfPageObjectKey.value !== previewKey) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    ocrCapabilityPdfPageObjectUrl.value = objectUrl
  } catch (err) {
    if (ocrCapabilityPdfPageObjectKey.value === previewKey) {
      if (ocrCapabilityPdfPageObjectUrl.value) {
        URL.revokeObjectURL(ocrCapabilityPdfPageObjectUrl.value)
        ocrCapabilityPdfPageObjectUrl.value = ''
      }
      ocrCapabilityPdfPagePreviewError.value =
        err instanceof Error ? err.message : 'PDF 页面图预览生成失败。'
    }
    console.warn('OCR capability PDF page preview failed.', err)
  } finally {
    if (ocrCapabilityPdfPageObjectKey.value === previewKey) {
      ocrCapabilityPdfPagePreviewLoading.value = false
    }
  }
}

const loadOcrCapabilityTestRuns = async () => {
  ocrCapabilityRecordsLoading.value = true
  try {
    const res = await listFdeOcrCapabilityTestRunsApi({ pageSize: 20 })
    ocrCapabilityTestRuns.value = res.data.items
  } finally {
    ocrCapabilityRecordsLoading.value = false
  }
}

const preferredOcrCapabilityTestRun = () =>
  ocrCapabilityTestRuns.value.find((run) => {
    const summary = run.resultSummary || {}
    const outputCount =
      Number(summary.fields || 0) +
      Number(summary.tables || 0) +
      Number(summary.seals || 0) +
      Number(summary.fragments || 0)
    return String(run.status) === 'success' && (!!run.parseResultId || outputCount > 0)
  }) || ocrCapabilityTestRuns.value[0]

const loadOcrCapabilityTestDetail = async (runId: string, schedulePoll = true) => {
  if (!runId) return
  ocrCapabilityDetailLoading.value = true
  try {
    const res = await getFdeOcrCapabilityTestRunApi(runId)
    selectedOcrCapabilityTest.value = res.data
    selectedOcrCapabilityTestRunId.value = runId
    await loadOcrCapabilityPdfPagePreview(res.data)
    if (ocrCapabilityTerminalStatuses.has(String(res.data.run?.status || ''))) {
      ocrCapabilityTestStage.value = ''
    }
    if (schedulePoll) {
      scheduleOcrCapabilityTestPolling(res.data.run)
    }
  } finally {
    ocrCapabilityDetailLoading.value = false
  }
}

const ocrCapabilityTerminalStatuses = new Set(['success', 'failed', 'cancelled'])

const scheduleOcrCapabilityTestPolling = (run?: FdeOcrCapabilityTestRun) => {
  if (ocrCapabilityTestPolling.value) {
    window.clearTimeout(ocrCapabilityTestPolling.value)
    ocrCapabilityTestPolling.value = undefined
  }
  const currentRun = run || selectedOcrCapabilityTest.value?.run
  if (!currentRun || ocrCapabilityTerminalStatuses.has(String(currentRun.status))) return
  const runId = String(currentRun.runId || currentRun.id || '')
  if (!runId) return
  ocrCapabilityTestStage.value = 'OCR 正在识别，完成后会自动显示文本和 ROI。'
  ocrCapabilityTestPolling.value = window.setTimeout(async () => {
    await loadOcrCapabilityTestRuns()
    await loadOcrCapabilityTestDetail(runId)
  }, 1800)
}

const handleOcrCapabilityTestFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (ocrCapabilityLocalPreviewUrl.value) {
    URL.revokeObjectURL(ocrCapabilityLocalPreviewUrl.value)
    ocrCapabilityLocalPreviewUrl.value = ''
  }
  clearOcrCapabilityPdfPagePreview()
  ocrCapabilityTestFile.value = input.files?.[0] || null
  if (ocrCapabilityTestFile.value) {
    ocrCapabilityLocalPreviewUrl.value = URL.createObjectURL(ocrCapabilityTestFile.value)
    selectedOcrCapabilityTest.value = null
    selectedOcrCapabilityTestRunId.value = ''
    ocrCapabilityTestStage.value = '文件已选择，点击“开始测试”上传并识别。'
  }
}

const chooseOcrCapabilityTestFile = () => {
  ocrCapabilityFileInputRef.value?.click()
}

const resolveOcrCapabilityUploadUrl = (uploadUrl: string) => {
  const proxyOrigin = import.meta.env.VITE_MINIO_UPLOAD_PROXY_ORIGIN
  if (!proxyOrigin) return uploadUrl
  try {
    const sourceUrl = new URL(uploadUrl)
    const targetUrl = new URL(proxyOrigin)
    sourceUrl.protocol = targetUrl.protocol
    sourceUrl.host = targetUrl.host
    return sourceUrl.toString()
  } catch {
    return uploadUrl
  }
}

const isOcrCapabilityHeaderNameSafe = (name: string) => /^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/.test(name)

const isOcrCapabilityHeaderValueSafe = (value: string) => /^[\t\x20-\xff]*$/.test(value)

const normalizeOcrCapabilityContentType = (value: string) => {
  const contentType = String(value || '').trim()
  return /^[A-Za-z0-9!#$%&'*+.^_`|~-]+\/[A-Za-z0-9!#$%&'*+.^_`|~-]+(?:\s*;\s*[A-Za-z0-9!#$%&'*+.^_`|~-]+=[A-Za-z0-9!#$%&'*+.^_`|~-]+)*$/.test(
    contentType
  )
    ? contentType
    : 'application/octet-stream'
}

const sanitizeOcrCapabilityUploadHeaders = (
  rawHeaders: Record<string, string> | undefined,
  fallbackContentType: string
) => {
  const headers: Record<string, string> = {}
  Object.entries(rawHeaders || {}).forEach(([rawName, rawValue]) => {
    const name = String(rawName || '').trim()
    const value = String(rawValue ?? '').trim()
    if (!name || !isOcrCapabilityHeaderNameSafe(name) || !isOcrCapabilityHeaderValueSafe(value)) {
      return
    }
    headers[name] = value
  })
  if (!Object.keys(headers).some((name) => name.toLowerCase() === 'content-type')) {
    headers['Content-Type'] = normalizeOcrCapabilityContentType(fallbackContentType)
  }
  return headers
}

const startOcrCapabilityTest = async () => {
  const file = ocrCapabilityTestFile.value
  if (!file) {
    error.value = '请先选择一个 PDF 或图片测试文件。'
    ocrCapabilityTestStage.value = '请先选择一个 PDF 或图片测试文件。'
    return
  }
  error.value = ''
  ocrCapabilityTestLoading.value = true
  ocrCapabilityTestStage.value = '正在创建上传会话...'
  try {
    const fileMeta = {
      fileName: file.name,
      fileType: file.type || file.name.split('.').pop() || 'application/octet-stream',
      contentType: file.type || 'application/octet-stream',
      fileSize: file.size
    }
    const sessionRes = await createFdeOcrCapabilityTestUploadSessionApi(
      { file: fileMeta },
      { idempotencyKey: `fde-ocr-test-upload-${file.size}-${Date.now()}` }
    )
    let uploadSession = sessionRes.data.uploadSession
    const headers = sanitizeOcrCapabilityUploadHeaders(uploadSession.headers, fileMeta.contentType)
    let signedUploadComplete = false
    if (uploadSession.uploadUrl && !String(uploadSession.uploadUrl).startsWith('mock://')) {
      ocrCapabilityTestStage.value = '正在上传测试文件...'
      const uploadUrl = resolveOcrCapabilityUploadUrl(uploadSession.uploadUrl)
      try {
        const uploadRes = await fetch(uploadUrl, {
          method: uploadSession.method || 'PUT',
          headers,
          body: file
        })
        signedUploadComplete = uploadRes.ok
      } catch (uploadErr) {
        console.warn(
          'OCR capability presigned upload failed, falling back to backend upload.',
          uploadErr
        )
      }
    }
    if (!signedUploadComplete) {
      ocrCapabilityTestStage.value = String(uploadSession.uploadUrl).startsWith('mock://')
        ? '正在通过后端保存测试文件...'
        : '上传地址不可用，正在通过后端保存测试文件...'
      const fallbackUploadRes = await uploadFdeOcrCapabilityTestFileApi(
        uploadSession.uploadSessionId,
        file,
        { idempotencyKey: `fde-ocr-test-file-${uploadSession.uploadSessionId}` }
      )
      uploadSession = {
        ...uploadSession,
        ...fallbackUploadRes.data.uploadSession
      }
    }
    ocrCapabilityTestStage.value = '文件已上传，正在提交 OCR 识别任务...'
    const runRes = await createFdeOcrCapabilityTestRunApi(
      {
        uploadSessionId: uploadSession.uploadSessionId,
        ...ocrCapabilityTestForm.value
      },
      { idempotencyKey: `fde-ocr-test-run-${uploadSession.uploadSessionId}` }
    )
    selectedOcrCapabilityTest.value = {
      run: runRes.data.run,
      parseResult: null,
      uploadSession
    }
    selectedOcrCapabilityTestRunId.value = runRes.data.run.runId
    ocrCapabilityTestStage.value = 'OCR 正在识别，完成后会自动显示文本和 ROI。'
    await loadOcrCapabilityTestRuns()
    await loadOcrCapabilityTestDetail(runRes.data.run.runId)
  } catch (err) {
    error.value =
      err instanceof Error ? `OCR 能力测试启动失败：${err.message}` : 'OCR 能力测试启动失败。'
    ocrCapabilityTestStage.value = error.value
  } finally {
    ocrCapabilityTestLoading.value = false
  }
}

const convertOcrCapabilityTestToAnnotation = async () => {
  const runId = selectedOcrCapabilityTestRunId.value
  if (!runId) return
  actionLoading.value = true
  try {
    await convertFdeOcrCapabilityTestToAnnotationApi(
      runId,
      {},
      { idempotencyKey: `fde-ocr-test-to-annotation-${runId}` }
    )
    await Promise.all([
      loadOcrCapabilityTestDetail(runId, false),
      listFdeOcrAnnotationTasksApi({ pageSize: 20 }).then((res) => {
        ocrAnnotation.value = res.data
      })
    ])
  } finally {
    actionLoading.value = false
  }
}

const convertOcrCapabilityTestToEvaluationCase = async () => {
  const runId = selectedOcrCapabilityTestRunId.value
  if (!runId) return
  actionLoading.value = true
  try {
    await convertFdeOcrCapabilityTestToEvaluationCaseApi(
      runId,
      {},
      { idempotencyKey: `fde-ocr-test-to-eval-${runId}` }
    )
    await loadOcrCapabilityTestDetail(runId, false)
  } finally {
    actionLoading.value = false
  }
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
      reason: 'FDE 诊断审查任务编排重跑'
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
      reason: 'FDE 验证新 Agent 编排图 / 提示词组合'
    })
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const createReviewDiagnosticFeedback = async () => {
  if (!activeReviewRunId.value) return
  actionLoading.value = true
  try {
    await createFdeReviewRunFeedbackApi(
      activeReviewRunId.value,
      {
        feedbackType: 'wrong_evidence',
        rootCause: 'prompt_error',
        comment: 'FDE 诊断修正：证据范围或依据引用需要复核，不改变正式业务结论。',
        correctedOutput: [
          {
            description: '建议补齐证据页码、bbox、规则编号和知识条款映射后再进入生产采纳。'
          }
        ],
        shouldEnterEvaluationSet: true
      },
      { idempotencyKey: `fde-review-feedback-${activeReviewRunId.value}-${Date.now()}` }
    )
    await loadReviewRunDetail(activeReviewRunId.value)
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

const openOcr100ActionAnnotation = async (row: Ocr100ActionBoardRow) => {
  if (!row.canOpenAnnotation || !row.taskId) return
  await openAnnotationEditor({
    taskId: row.taskId,
    caseId: row.caseId || row.taskId,
    scenario: '',
    collectionStatus: 'needs_labeling'
  } as FdeOcrAnnotationTask)
}

const csvCell = (value: unknown) => {
  const text = String(value ?? '')
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

const downloadTextFile = (filename: string, content: string, type = 'text/csv;charset=utf-8') => {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

const exportOcr100ActionBoardCsv = () => {
  const rows = ocr100ActionBoardRows.value
  if (!rows.length) return
  const headers = [
    'lane',
    'scenario',
    'title',
    'sourcePath',
    'dropDirectory',
    'missingCases',
    'checklist',
    'blockers',
    'humanActions',
    'doneWhen'
  ]
  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      [
        row.lane,
        row.scenario,
        row.title,
        row.sourcePath,
        row.dropDirectory,
        row.missingCases || '',
        row.checklistText,
        row.blockersText,
        row.humanActionsText,
        row.doneWhen
      ]
        .map(csvCell)
        .join(',')
    )
  ]
  downloadTextFile('ocr_100_action_board.csv', lines.join('\n'))
}

const refreshOcr100ActionBoard = async () => {
  ocr100ActionBoardRefreshing.value = true
  try {
    const res = await refreshFdeOcr100ActionBoardApi()
    if (ocrQuality.value) {
      ocrQuality.value = {
        ...ocrQuality.value,
        ocr100ActionBoard: res.data.board
      }
    } else {
      await loadData()
    }
  } finally {
    ocr100ActionBoardRefreshing.value = false
  }
}

const openOcr100HandoffFile = async (file: { key: string; exists: boolean; label: string }) => {
  if (!file.exists || !file.key || ocr100HandoffOpening.value) return
  const previewWindow = window.open('about:blank', '_blank')
  ocr100HandoffOpening.value = file.key
  try {
    const res = await getFdeOcr100HandoffArtifactApi(file.key)
    const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
    const url = URL.createObjectURL(blob)
    if (previewWindow) {
      previewWindow.opener = null
      previewWindow.document.title = file.label || 'OCR 100 handoff'
      previewWindow.location.href = url
    } else {
      const link = document.createElement('a')
      link.href = url
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      document.body.appendChild(link)
      link.click()
      link.remove()
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (err) {
    previewWindow?.close()
    void err
  } finally {
    ocr100HandoffOpening.value = ''
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

const openOcrCapabilityTestPanel = async () => {
  ocrSubpage.value = 'capability-test'
  ocrCapabilityDialogVisible.value = true
  if (!ocrCapabilityTestRuns.value.length) {
    try {
      await loadOcrCapabilityTestRuns()
    } catch {
      error.value = 'OCR 能力测试记录加载失败，可直接选择文件开始测试。'
    }
  }
  const preferredRun = preferredOcrCapabilityTestRun()
  const selectedRunIsUseful =
    selectedOcrCapabilityTestRunId.value &&
    (selectedOcrCapabilityHasOutput.value ||
      selectedOcrCapabilityRun.value?.status === 'success' ||
      selectedOcrCapabilityRunning.value)
  if (!selectedRunIsUseful && preferredRun?.runId) {
    await loadOcrCapabilityTestDetail(preferredRun.runId, false)
  }
}

const openOcrStatusDialog = (type: OcrStatusDialogType) => {
  ocrStatusDialogType.value = type
  ocrStatusDialogVisible.value = true
}

const selectOcrStatusTab = (tab: OcrStatusTab) => {
  selectedOcrStatusTab.value = tab
}

const openOcrSecondaryMenu = () => {
  ocrSecondaryMenuVisible.value = true
}

const openOcrSecondaryTool = (tool: OcrSecondaryTool) => {
  ocrSecondaryMenuVisible.value = false
  if (tool === 'quality') return openOcrStatusDialog('quality')
  selectOcrStatusTab(tool)
}

const selectOcrSubpage = (subpage: OcrSubpage) => {
  if (subpage === 'capability-test') {
    void openOcrCapabilityTestPanel()
    return
  }
  ocrSubpage.value = subpage
}

const runFdePageAction = async (key: FdePageActionKey) => {
  if (key === 'go-ocr-label') return openFirstOcrAnnotationTask()
  if (key === 'go-ocr-capability-test') return openOcrCapabilityTestPanel()
  if (key === 'go-ocr-tools') return openOcrSecondaryMenu()
  if (key === 'start-ocr-evaluation') return startOcrEvaluation()
  if (key === 'triage-feedback') return triageFirstFeedback()
  if (key === 'start-evaluation') return startEvaluation()
  if (key === 'replay-ai-run') return replayFirstRun()
  if (key === 'replay-review-run') return replayFirstReviewRun()
  if (key === 'shadow-review-run') return shadowFirstReviewRun()
  if (key === 'create-review-diagnostic-feedback') return createReviewDiagnosticFeedback()
  if (key === 'submit-release') return submitReleaseGate()
  if (key === 'install-business-pack') return installBusinessPack()
  if (key === 'create-mask-policy') return createMaskingPolicyDraft()
  if (key === 'update-rca') return updateFirstRca()
  if (key === 'budget-change') return proposeFirstBudgetChange()
}

watch(
  () => route.fullPath,
  () => syncTabFromRoute(),
  { immediate: true }
)

watch(
  () => [route.path, route.query.projectId, route.query.view, route.query.nodeId],
  async () => {
    if (currentFdePath.value !== '/fde/projects') return
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
  const segment = currentFdeRouteKey.value
  if (routeTabMap[segment] === tab) return
  const target = fdeTabRouteMap[tab]
  if (target && currentFdePath.value !== target) {
    if (target === '/fde/projects' && selectedFdeProjectId.value) {
      void syncProjectAuditRoute()
      return
    }
    router.push(target)
  }
})

onMounted(async () => {
  await normalizeFdeBrowserRoute()
  await loadData()
})

onBeforeUnmount(() => {
  if (ocrCapabilityTestPolling.value) {
    window.clearTimeout(ocrCapabilityTestPolling.value)
    ocrCapabilityTestPolling.value = undefined
  }
  if (ocrCapabilityLocalPreviewUrl.value) {
    URL.revokeObjectURL(ocrCapabilityLocalPreviewUrl.value)
    ocrCapabilityLocalPreviewUrl.value = ''
  }
  clearOcrCapabilityPdfPagePreview()
})
</script>

<template>
  <StaticPageShell
    brand-mark="F"
    title="FDE 后台"
    search-placeholder="⌕ 搜索审查任务 / OCR / 样本"
    user-label="FDE 工程师"
    :top-stats="fdeTopStats"
    menu-title="FDE 菜单"
    menu-root="AI 交付与治理"
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
    right-subtitle="AI 审查编排 / OCR"
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

      <div v-if="isFdeRoute('ocr-quality')" class="ocr-command-center">
        <section class="ocr-online-entry" aria-label="OCR 在线测试入口">
          <div class="ocr-online-entry__copy">
            <span>在线测 OCR</span>
            <strong>上传 PDF / 图片，立即看识别结果</strong>
            <small>临时验证一份资料的识别效果，不进入正式项目资料。</small>
          </div>
          <ElButton type="primary" size="large" @click="openOcrCapabilityTestPanel">
            在线测 OCR
          </ElButton>
        </section>

        <div class="ocr-step-grid" role="tablist" aria-label="OCR 当前状态">
          <button
            type="button"
            class="ocr-step-card ocr-step-card--red"
            :class="{ 'is-active': selectedOcrStatusTab === 'issue' }"
            role="tab"
            aria-controls="ocr-status-panel"
            :aria-selected="selectedOcrStatusTab === 'issue'"
            aria-label="切换到当前问题明细"
            @click="selectOcrStatusTab('issue')"
          >
            <span>问题</span>
            <strong>最先处理什么</strong>
            <small>{{ firstOcrBlockingSummary }}</small>
          </button>
          <button
            type="button"
            class="ocr-step-card ocr-step-card--orange"
            :class="{ 'is-active': selectedOcrStatusTab === 'annotation' }"
            role="tab"
            aria-controls="ocr-status-panel"
            :aria-selected="selectedOcrStatusTab === 'annotation'"
            aria-label="切换到待人工修正明细"
            @click="selectOcrStatusTab('annotation')"
          >
            <span>待修</span>
            <strong>还有多少要人工看</strong>
            <small
              >待标注 {{ ocrPendingAnnotationCount }}，样本
              {{ ocrAnnotationSummary?.tasks || 0 }}</small
            >
          </button>
          <button
            type="button"
            class="ocr-step-card ocr-step-card--blue"
            :class="{ 'is-active': selectedOcrStatusTab === 'runtime' }"
            role="tab"
            aria-controls="ocr-status-panel"
            :aria-selected="selectedOcrStatusTab === 'runtime'"
            aria-label="切换到 OCR 服务与运行诊断"
            @click="selectOcrStatusTab('runtime')"
          >
            <span>服务</span>
            <strong>OCR 服务是否健康</strong>
            <small>
              {{ friendlyStatus(ocrRuntimeDoctor?.status, '未知') }} ·
              {{ ocrRuntimeDoctor?.summary?.fail || 0 }} 失败 /
              {{ ocrRuntimeDoctor?.summary?.warn || 0 }} 告警
            </small>
          </button>
          <button
            type="button"
            class="ocr-step-card ocr-step-card--green"
            :class="{ 'is-active': selectedOcrStatusTab === 'release' }"
            role="tab"
            aria-controls="ocr-status-panel"
            :aria-selected="selectedOcrStatusTab === 'release'"
            aria-label="切换到发布评测明细"
            @click="selectOcrStatusTab('release')"
          >
            <span>发布</span>
            <strong>能不能作为交付基线</strong>
            <small>
              {{
                ocr100Scorecard
                  ? `${ocr100Scorecard.score}/${ocr100Scorecard.targetScore}`
                  : '待评估'
              }}
              · 可评估 {{ ocrReadyForEvalCount }}
            </small>
          </button>
        </div>

        <section
          id="ocr-status-panel"
          class="ocr-status-tabs"
          role="tabpanel"
          aria-label="OCR 状态明细"
          aria-live="polite"
        >
          <div class="ocr-status-tabs__header">
            <div>
              <span>状态明细</span>
              <strong>{{ ocrInlineStatusTitle }}</strong>
            </div>
            <small>{{ ocrInlineStatusHint }}</small>
          </div>

          <div class="ocr-status-tabs__body">
            <template v-if="selectedOcrStatusTab === 'issue'">
              <ElTable v-if="ocrTopBlockerRows.length" :data="ocrTopBlockerRows" border>
                <ElTableColumn prop="id" label="#" width="72" />
                <ElTableColumn prop="source" label="来源" width="120" />
                <ElTableColumn prop="blocker" label="问题" min-width="260" show-overflow-tooltip />
                <ElTableColumn
                  prop="action"
                  label="处理动作"
                  min-width="260"
                  show-overflow-tooltip
                />
              </ElTable>
              <ElEmpty v-else description="当前没有 OCR 阻断项。" />
            </template>

            <template v-else-if="selectedOcrStatusTab === 'annotation'">
              <ElTable
                v-if="ocrAnnotationRows.length"
                :data="ocrAnnotationRows"
                border
                @row-click="(row) => openAnnotationEditor(row)"
              >
                <ElTableColumn prop="taskId" label="样本" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="scenario" label="场景" min-width="170" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.scenario) }}</template>
                </ElTableColumn>
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="170"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
                <ElTableColumn label="状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="ocrAnnotationStatusType(row)" effect="plain">
                      {{ ocrAnnotationStatusLabel(row) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="92" fixed="right">
                  <template #default="{ row }">
                    <ElButton size="small" text @click.stop="openAnnotationEditor(row)">
                      标注
                    </ElButton>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElEmpty v-else description="当前没有待人工修正样本。" />
            </template>

            <template v-else-if="selectedOcrStatusTab === 'runtime'">
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="运行时状态">
                  <ElTag :type="ocrRuntimeDoctor?.ok ? 'success' : 'warning'" effect="plain">
                    {{ friendlyStatus(ocrRuntimeDoctor?.status, '未知') }}
                  </ElTag>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="体检结果">
                  {{ ocrRuntimeDoctor?.summary?.fail || 0 }} 失败 /
                  {{ ocrRuntimeDoctor?.summary?.warn || 0 }} 告警
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="firstRuntimeIssue" label="首要问题">
                  {{ friendlyTechnicalText(firstRuntimeIssue.name) }}：{{
                    friendlyTechnicalText(firstRuntimeIssue.message)
                  }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable
                v-if="ocrRuns.length"
                :data="ocrRuns"
                border
                class="mt-12px"
                @row-click="(row) => openOcrAuditDrawer(String(row.id || row.jobId))"
              >
                <ElTableColumn prop="id" label="任务编号" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="100">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="150"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="92" fixed="right">
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
              <ElEmpty
                v-else-if="!(ocrRuntimeDoctor?.topIssues || []).length"
                description="暂无 OCR 任务。"
              />
              <ElTable
                v-if="(ocrRuntimeDoctor?.topIssues || []).length"
                :data="ocrRuntimeDoctor?.topIssues || []"
                border
                class="mt-12px"
              >
                <ElTableColumn label="问题" min-width="190" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechnicalText(row.name) }}</template>
                </ElTableColumn>
                <ElTableColumn label="说明" min-width="300" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechnicalText(row.message) }}</template>
                </ElTableColumn>
              </ElTable>
            </template>

            <template v-else>
              <template v-if="ocr100Scorecard">
                <div class="gate-summary">
                  <div class="gate-summary-item">
                    <span>OCR 100</span>
                    <strong>{{ ocr100Scorecard.score }}/{{ ocr100Scorecard.targetScore }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>认证状态</span>
                    <strong
                      class="gate-status-pill"
                      :class="
                        ocr100Scorecard.ok
                          ? 'gate-status-pill--success'
                          : 'gate-status-pill--danger'
                      "
                    >
                      <i aria-hidden="true"></i>
                      <span>{{ ocr100Scorecard.ok ? '100分就绪' : '存在阻断' }}</span>
                      <small>{{
                        ocr100Scorecard.ok
                          ? '可作为交付基线'
                          : `${ocr100Scorecard.blockers.length} 个阻断待处理`
                      }}</small>
                    </strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>可评估样本</span>
                    <strong>{{ ocrReadyForEvalCount }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>阻断项</span>
                    <strong>{{ ocr100Scorecard.blockers.length }}</strong>
                  </div>
                </div>
                <ElTable :data="ocr100SectionRows" border class="mt-12px">
                  <ElTableColumn prop="name" label="评分域" min-width="150" show-overflow-tooltip />
                  <ElTableColumn label="分数" width="105">
                    <template #default="{ row }">{{ row.score }}/{{ row.maxScore }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="100">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElTable
                  v-if="ocr100BlockerRows.length"
                  :data="ocr100BlockerRows"
                  border
                  class="mt-12px"
                >
                  <ElTableColumn prop="id" label="#" width="72" />
                  <ElTableColumn
                    prop="blocker"
                    label="OCR 100 阻断项"
                    min-width="260"
                    show-overflow-tooltip
                  />
                </ElTable>
              </template>
              <ElEmpty v-else description="暂无 OCR 发布评测数据。" />
            </template>
          </div>
        </section>

        <ElDialog
          v-model="ocrStatusDialogVisible"
          :title="ocrStatusDialogTitle"
          width="min(980px, 96vw)"
          class="ocr-status-dialog"
        >
          <div class="ocr-status-dialog__body">
            <ElAlert type="info" show-icon :closable="false" :title="ocrStatusDialogHint" />

            <template v-if="ocrStatusDialogType === 'issue'">
              <ElTable
                v-if="ocrTopBlockerRows.length"
                :data="ocrTopBlockerRows"
                border
                class="mt-12px"
              >
                <ElTableColumn prop="id" label="#" width="72" />
                <ElTableColumn prop="source" label="来源" width="120" />
                <ElTableColumn prop="blocker" label="问题" min-width="260" show-overflow-tooltip />
                <ElTableColumn
                  prop="action"
                  label="处理动作"
                  min-width="260"
                  show-overflow-tooltip
                />
              </ElTable>
              <ElEmpty v-else class="mt-12px" description="当前没有 OCR 阻断项。" />
            </template>

            <template v-else-if="ocrStatusDialogType === 'annotation'">
              <ElTable
                v-if="ocrAnnotationRows.length"
                :data="ocrAnnotationRows"
                border
                class="mt-12px"
                @row-click="(row) => openAnnotationEditor(row)"
              >
                <ElTableColumn prop="taskId" label="样本" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="scenario" label="场景" min-width="170" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.scenario) }}</template>
                </ElTableColumn>
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="170"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
                <ElTableColumn label="状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="ocrAnnotationStatusType(row)" effect="plain">
                      {{ ocrAnnotationStatusLabel(row) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="92" fixed="right">
                  <template #default="{ row }">
                    <ElButton size="small" text @click.stop="openAnnotationEditor(row)">
                      标注
                    </ElButton>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElEmpty v-else class="mt-12px" description="当前没有待人工修正样本。" />
              <ElTable
                v-if="ocrAnnotationBlockerRows.length"
                :data="ocrAnnotationBlockerRows"
                border
                class="mt-12px"
              >
                <ElTableColumn
                  prop="blocker"
                  label="标注阻断项"
                  min-width="220"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="count" label="数量" width="90" />
              </ElTable>
            </template>

            <template v-else-if="ocrStatusDialogType === 'runtime'">
              <ElDescriptions :column="1" border class="mt-12px">
                <ElDescriptionsItem label="运行时状态">
                  <ElTag :type="ocrRuntimeDoctor?.ok ? 'success' : 'warning'" effect="plain">
                    {{ friendlyStatus(ocrRuntimeDoctor?.status, '未知') }}
                  </ElTag>
                </ElDescriptionsItem>
                <ElDescriptionsItem label="体检结果">
                  {{ ocrRuntimeDoctor?.summary?.fail || 0 }} 失败 /
                  {{ ocrRuntimeDoctor?.summary?.warn || 0 }} 告警
                </ElDescriptionsItem>
                <ElDescriptionsItem v-if="firstRuntimeIssue" label="首要问题">
                  {{ friendlyTechnicalText(firstRuntimeIssue.name) }}：{{
                    friendlyTechnicalText(firstRuntimeIssue.message)
                  }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable
                v-if="(ocrRuntimeDoctor?.topIssues || []).length"
                :data="ocrRuntimeDoctor?.topIssues || []"
                border
                class="mt-12px"
              >
                <ElTableColumn label="问题" min-width="190" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechnicalText(row.name) }}</template>
                </ElTableColumn>
                <ElTableColumn label="说明" min-width="300" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechnicalText(row.message) }}</template>
                </ElTableColumn>
              </ElTable>
              <ElTable
                v-if="ocrRuns.length"
                :data="ocrRuns"
                border
                class="mt-12px"
                @row-click="(row) => openOcrAuditDrawer(String(row.id || row.jobId))"
              >
                <ElTableColumn prop="id" label="任务编号" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="100">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.status))" effect="plain">
                      {{ friendlyStatus(row.status) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="150"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="92" fixed="right">
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
            </template>

            <template v-else-if="ocrStatusDialogType === 'quality'">
              <ElDescriptions :column="1" border class="mt-12px">
                <ElDescriptionsItem label="文件成功">
                  {{ ocrQuality?.fileLevel?.success || 0 }}/{{ ocrQuality?.fileLevel?.total || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="Job 成功">
                  {{ ocrQuality?.jobLevel?.success || 0 }}/{{ ocrQuality?.jobLevel?.total || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="低置信度字段">
                  {{ ocrQuality?.fieldLevel?.lowConfidence || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="必需字段缺失">
                  {{ ocrQuality?.fieldLevel?.missingRequiredFieldCount || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="正式表格">
                  {{ ocrQuality?.tableLevel?.formalTableCount || 0 }}/{{
                    ocrQuality?.tableLevel?.tableCount || 0
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="印章可读">
                  {{ ocrQuality?.sealLevel?.readableSealCount || 0 }}/{{
                    ocrQuality?.sealLevel?.sealCount || 0
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="引擎耗时">
                  {{ ocrQuality?.cacheMetrics?.totalDurationMs || 0 }} ms
                </ElDescriptionsItem>
              </ElDescriptions>
            </template>

            <template v-else>
              <template v-if="ocr100Scorecard">
                <div class="gate-summary mt-12px">
                  <div class="gate-summary-item">
                    <span>OCR 100</span>
                    <strong>{{ ocr100Scorecard.score }}/{{ ocr100Scorecard.targetScore }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>认证状态</span>
                    <strong
                      class="gate-status-pill"
                      :class="
                        ocr100Scorecard.ok
                          ? 'gate-status-pill--success'
                          : 'gate-status-pill--danger'
                      "
                    >
                      <i aria-hidden="true"></i>
                      <span>{{ ocr100Scorecard.ok ? '100分就绪' : '存在阻断' }}</span>
                      <small>{{
                        ocr100Scorecard.ok
                          ? '可作为交付基线'
                          : `${ocr100Scorecard.blockers.length} 个阻断待处理`
                      }}</small>
                    </strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>可评估样本</span>
                    <strong>{{ ocrReadyForEvalCount }}</strong>
                  </div>
                  <div class="gate-summary-item">
                    <span>阻断项</span>
                    <strong>{{ ocr100Scorecard.blockers.length }}</strong>
                  </div>
                </div>
                <ElTable :data="ocr100SectionRows" border class="mt-12px">
                  <ElTableColumn prop="name" label="评分域" min-width="150" show-overflow-tooltip />
                  <ElTableColumn label="分数" width="105">
                    <template #default="{ row }">{{ row.score }}/{{ row.maxScore }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="100">
                    <template #default="{ row }">
                      <ElTag :type="row.status === 'pass' ? 'success' : 'danger'" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElTable
                  v-if="ocr100BlockerRows.length"
                  :data="ocr100BlockerRows"
                  border
                  class="mt-12px"
                >
                  <ElTableColumn prop="id" label="#" width="72" />
                  <ElTableColumn
                    prop="blocker"
                    label="OCR 100 阻断项"
                    min-width="260"
                    show-overflow-tooltip
                  />
                </ElTable>
              </template>
              <ElEmpty v-else class="mt-12px" description="暂无 OCR 发布评测数据。" />
            </template>
          </div>
        </ElDialog>

        <ElDialog
          v-model="ocrSecondaryMenuVisible"
          title="更多 OCR 工具"
          width="min(720px, 94vw)"
          class="ocr-secondary-dialog"
        >
          <div class="ocr-secondary-menu">
            <ElAlert
              type="info"
              show-icon
              :closable="false"
              title="这些是低频或 FDE 专用工具，日常在线测试可以先不看。"
            />
            <button
              v-for="tool in ocrSecondaryTools"
              :key="tool.key"
              type="button"
              :class="`ocr-secondary-tool ocr-secondary-tool--${tool.tone}`"
              @click="openOcrSecondaryTool(tool.key)"
            >
              <span>{{ tool.label }}</span>
              <strong>{{ tool.stat }}</strong>
              <small>{{ tool.description }}</small>
            </button>
          </div>
        </ElDialog>

        <ElDialog
          v-model="ocrCapabilityDialogVisible"
          title="OCR 能力测试"
          width="min(1180px, 96vw)"
          class="ocr-capability-dialog"
          destroy-on-close
        >
          <section class="ocr-capability-shell">
            <div class="ocr-capability-hero">
              <div>
                <span>基础能力测试</span>
                <strong>上传一份临时资料，验证 OCR 是否真的能识别。</strong>
                <small>测试文件只用于 FDE 诊断，不进入正式项目资料，不改变审查结论。</small>
              </div>
              <ElSpace>
                <ElButton
                  plain
                  :loading="ocrCapabilityRecordsLoading"
                  @click="loadOcrCapabilityTestRuns"
                >
                  刷新记录
                </ElButton>
                <ElButton
                  type="primary"
                  :loading="ocrCapabilityTestLoading"
                  @click="startOcrCapabilityTest"
                >
                  {{ ocrCapabilityTestLoading ? '处理中' : '开始测试' }}
                </ElButton>
              </ElSpace>
            </div>
            <ElAlert
              v-if="ocrCapabilityProgressHint"
              type="info"
              show-icon
              :closable="false"
              :title="ocrCapabilityProgressHint"
            />
            <div class="ocr-capability-layout">
              <section class="ocr-capability-card ocr-capability-card--setup">
                <div class="ocr-capability-card__head">
                  <strong>1. 选择测试文件</strong>
                  <ElTag effect="plain">PDF / 图片</ElTag>
                </div>
                <input
                  ref="ocrCapabilityFileInputRef"
                  class="sr-only-input"
                  type="file"
                  accept="application/pdf,image/*,.pdf,.png,.jpg,.jpeg"
                  @change="handleOcrCapabilityTestFileChange"
                />
                <button
                  type="button"
                  class="ocr-capability-upload"
                  @click="chooseOcrCapabilityTestFile"
                >
                  <strong>{{ ocrCapabilityTestFile?.name || '点击选择 PDF 或图片' }}</strong>
                  <span v-if="ocrCapabilityTestFile">
                    {{ Math.ceil((ocrCapabilityTestFile.size || 0) / 1024) }} KB
                  </span>
                  <span v-else>建议用真实扫描件、表格照片或盖章资料做测试。</span>
                </button>
                <div class="ocr-capability-form">
                  <label>
                    <span>解析配置</span>
                    <ElSelect v-model="ocrCapabilityTestForm.profileId" size="small">
                      <ElOption label="自动判断" value="auto" />
                      <ElOption
                        label="管道特性表 / 工程表格"
                        value="piping_characteristic_list_v1"
                      />
                      <ElOption label="质量证明书" value="quality_certificate_v1" />
                      <ElOption label="NDT RT 报告" value="ndt_rt_report_v1" />
                      <ElOption label="通用资料" value="all" />
                    </ElSelect>
                  </label>
                  <label>
                    <span>资料类型</span>
                    <ElSelect v-model="ocrCapabilityTestForm.documentType" size="small">
                      <ElOption label="自动判断" value="auto" />
                      <ElOption label="工程表格照片" value="engineering_table_photo" />
                      <ElOption label="质量证明文件" value="quality_certificate" />
                      <ElOption label="NDT 检测报告" value="ndt_report" />
                      <ElOption label="通用工程资料" value="engineering_document" />
                    </ElSelect>
                  </label>
                  <label>
                    <span>快速页数</span>
                    <ElInputNumber
                      v-model="ocrCapabilityTestForm.maxPages"
                      size="small"
                      :min="1"
                      :max="10"
                      controls-position="right"
                    />
                  </label>
                </div>
                <div class="ocr-capability-switches">
                  <label>
                    <input v-model="ocrCapabilityTestForm.enableTables" type="checkbox" />
                    表格识别
                  </label>
                  <label>
                    <input v-model="ocrCapabilityTestForm.enableSeals" type="checkbox" />
                    印章识别（稍慢）
                  </label>
                  <label>
                    <input v-model="ocrCapabilityTestForm.enableFallback" type="checkbox" />
                    复杂页兜底
                  </label>
                </div>
              </section>
              <section
                :class="[
                  'ocr-capability-card',
                  'ocr-capability-card--recent',
                  { 'ocr-capability-card--collapsed': !ocrCapabilityRecentOpen }
                ]"
                v-loading="ocrCapabilityRecordsLoading"
              >
                <div class="ocr-capability-card__head">
                  <strong>2. 最近测试</strong>
                  <ElSpace>
                    <ElTag effect="plain">{{ ocrCapabilityTestRuns.length }} 条</ElTag>
                    <ElButton
                      size="small"
                      plain
                      @click="ocrCapabilityRecentOpen = !ocrCapabilityRecentOpen"
                    >
                      {{ ocrCapabilityRecentOpen ? '收起' : '展开' }}
                    </ElButton>
                  </ElSpace>
                </div>
                <ElTable
                  v-if="ocrCapabilityRecentOpen"
                  :data="ocrCapabilityTestRuns"
                  class="ocr-capability-table"
                  @row-click="(row) => loadOcrCapabilityTestDetail(String(row.runId || row.id))"
                >
                  <ElTableColumn
                    prop="fileName"
                    label="文件"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="115">
                    <template #default="{ row }">
                      <ElTag :type="ocrCapabilityStatusType(row.status)" effect="plain">
                        {{ friendlyStatus(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="结果" width="105">
                    <template #default="{ row }">
                      {{
                        Number(row.resultSummary?.fields || 0) +
                        Number(row.resultSummary?.tables || 0) +
                        Number(row.resultSummary?.seals || 0)
                      }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </section>
            </div>
            <section class="ocr-capability-result">
              <div class="ocr-capability-preview" v-loading="ocrCapabilityResultLoading">
                <div class="ocr-capability-card__head">
                  <strong>3. 文件预览</strong>
                  <ElTag v-if="selectedOcrCapabilityRun" effect="plain">
                    {{ friendlyStatus(selectedOcrCapabilityRun.status) }}
                  </ElTag>
                  <ElTag v-if="selectedOcrCapabilityRois.length" type="success" effect="plain">
                    ROI {{ selectedOcrCapabilityRois.length }}
                  </ElTag>
                </div>
                <div
                  v-if="ocrCapabilityRoiLegend.length"
                  class="ocr-roi-legend"
                  aria-label="ROI 类型图例"
                >
                  <span
                    v-for="item in ocrCapabilityRoiLegend"
                    :key="item.type"
                    :class="['ocr-roi-legend__item', `ocr-roi-legend__item--${item.tone}`]"
                  >
                    <i aria-hidden="true"></i>
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.count }}</small>
                  </span>
                </div>
                <div v-if="selectedOcrCapabilityPreviewSource?.url" class="ocr-preview-stage">
                  <div
                    v-if="selectedOcrCapabilityPreviewSource.previewType === 'image'"
                    class="ocr-preview-image-frame"
                  >
                    <img :src="selectedOcrCapabilityPreviewSource.url" alt="OCR 测试文件预览" />
                    <div
                      v-if="selectedOcrCapabilityImageRois.length"
                      class="ocr-roi-layer"
                      aria-label="OCR ROI 标注"
                    >
                      <button
                        v-for="roi in selectedOcrCapabilityImageRois"
                        :key="roi.id"
                        type="button"
                        :class="['ocr-roi-box', `ocr-roi-box--${roi.tone}`]"
                        :style="ocrCapabilityRoiStyle(roi)"
                        :title="`${roi.type} · ${roi.label}${roi.text ? ` · ${roi.text}` : ''}`"
                        :aria-label="`${roi.type} 标注：${roi.label}${roi.text ? `，${roi.text}` : ''}`"
                      >
                        <span>{{ roi.text || roi.label || roi.type }}</span>
                      </button>
                    </div>
                  </div>
                  <div
                    v-else-if="
                      selectedOcrCapabilityPreviewSource.previewType === 'pdf' &&
                      selectedOcrCapabilityPdfPagePreviewUrl
                    "
                    class="ocr-preview-image-frame ocr-preview-pdf-page-frame"
                  >
                    <img :src="selectedOcrCapabilityPdfPagePreviewUrl" alt="OCR 测试 PDF 页预览" />
                    <div
                      v-if="selectedOcrCapabilityPdfRois.length"
                      class="ocr-roi-layer"
                      aria-label="OCR PDF ROI 标注"
                    >
                      <button
                        v-for="roi in selectedOcrCapabilityPdfRois"
                        :key="roi.id"
                        type="button"
                        :class="['ocr-roi-box', `ocr-roi-box--${roi.tone}`]"
                        :style="ocrCapabilityRoiStyle(roi)"
                        :title="`${roi.type} · ${roi.label}${roi.text ? ` · ${roi.text}` : ''}`"
                        :aria-label="`${roi.type} 标注：${roi.label}${roi.text ? `，${roi.text}` : ''}`"
                      >
                        <span>{{ roi.text || roi.label || roi.type }}</span>
                      </button>
                    </div>
                  </div>
                  <div
                    v-else-if="selectedOcrCapabilityPreviewSource.previewType === 'pdf'"
                    class="ocr-preview-pdf-fallback"
                    v-loading="ocrCapabilityPdfPagePreviewLoading"
                  >
                    <ElEmpty
                      :description="
                        ocrCapabilityPdfPagePreviewError ||
                        (ocrCapabilityPdfPagePreviewLoading
                          ? '正在生成 PDF 页面图预览...'
                          : 'PDF 页面图预览暂未生成，可先查看 OCR 结果。')
                      "
                    />
                  </div>
                  <ElEmpty v-else description="该文件类型暂不支持页面内预览，可查看 OCR 结果。" />
                </div>
                <ElEmpty v-else description="选择测试记录后显示文件预览。" />
              </div>
              <div class="ocr-capability-summary" v-loading="ocrCapabilityResultLoading">
                <div class="ocr-capability-card__head">
                  <strong>4. 识别结果</strong>
                  <ElSpace>
                    <ElButton
                      size="small"
                      plain
                      :disabled="!selectedOcrCapabilityCanPersist"
                      :loading="actionLoading"
                      @click="convertOcrCapabilityTestToAnnotation"
                    >
                      转入OCR标注
                    </ElButton>
                    <ElButton
                      size="small"
                      plain
                      :disabled="!selectedOcrCapabilityCanPersist"
                      :loading="actionLoading"
                      @click="convertOcrCapabilityTestToEvaluationCase"
                    >
                      生成评估样本草稿
                    </ElButton>
                  </ElSpace>
                </div>
                <div class="ocr-capability-kpis">
                  <div>
                    <span>页数</span>
                    <strong>{{ selectedOcrCapabilitySummary.pages }}</strong>
                  </div>
                  <div>
                    <span>字段</span>
                    <strong>{{ selectedOcrCapabilitySummary.fields }}</strong>
                  </div>
                  <div>
                    <span>表格</span>
                    <strong>{{ selectedOcrCapabilitySummary.tables }}</strong>
                  </div>
                  <div>
                    <span>印章</span>
                    <strong>{{ selectedOcrCapabilitySummary.seals }}</strong>
                  </div>
                  <div>
                    <span>质量状态</span>
                    <strong>{{
                      friendlyStatus(selectedOcrCapabilitySummary.qualityStatus)
                    }}</strong>
                  </div>
                  <div>
                    <span>诊断</span>
                    <strong>{{ selectedOcrCapabilitySummary.diagnostics }}</strong>
                  </div>
                </div>
                <ElAlert
                  v-if="selectedOcrCapabilityTerminalNoOutput"
                  class="mt-12px"
                  type="warning"
                  show-icon
                  :closable="false"
                  title="本次测试还没有返回可展示的识别内容，请稍后刷新记录或检查 OCR 服务状态。"
                />
                <ElTabs class="ocr-capability-output-tabs">
                  <ElTabPane label="全文">
                    <pre v-if="selectedOcrCapabilityText" class="ocr-capability-text-output">{{
                      selectedOcrCapabilityText
                    }}</pre>
                    <ElEmpty v-else description="开始测试后，这里显示 OCR 识别文本。" />
                  </ElTabPane>
                  <ElTabPane :label="`结构化 ${selectedOcrCapabilityStructuredRows.length || ''}`">
                    <ElTable
                      v-if="selectedOcrCapabilityStructuredRows.length"
                      :data="selectedOcrCapabilityStructuredRows"
                    >
                      <ElTableColumn prop="pageNo" label="页" width="62" />
                      <ElTableColumn prop="type" label="类型" width="82" />
                      <ElTableColumn
                        prop="name"
                        label="名称"
                        min-width="130"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="value"
                        label="内容 / 值"
                        min-width="220"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="bboxText"
                        label="bbox"
                        min-width="150"
                        show-overflow-tooltip
                      />
                      <ElTableColumn label="置信度" width="96">
                        <template #default="{ row }">
                          {{ row.confidence === undefined ? '-' : scorePercent(row.confidence) }}
                        </template>
                      </ElTableColumn>
                      <ElTableColumn
                        prop="source"
                        label="来源"
                        min-width="150"
                        show-overflow-tooltip
                      />
                    </ElTable>
                    <ElEmpty v-else description="暂无可结构化的识别内容。" />
                  </ElTabPane>
                  <ElTabPane :label="`ROI ${selectedOcrCapabilityRois.length || ''}`">
                    <ElTable
                      v-if="selectedOcrCapabilityRois.length"
                      :data="selectedOcrCapabilityRois"
                    >
                      <ElTableColumn label="类型" width="96">
                        <template #default="{ row }">
                          <ElTag :type="ocrCapabilityRoiTagType(row.tone)" effect="plain">
                            {{ row.type }}
                          </ElTag>
                        </template>
                      </ElTableColumn>
                      <ElTableColumn
                        prop="label"
                        label="对象"
                        min-width="130"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="text"
                        label="文本"
                        min-width="180"
                        show-overflow-tooltip
                      />
                      <ElTableColumn label="bbox" min-width="160" show-overflow-tooltip>
                        <template #default="{ row }">{{ row.bbox.join(', ') }}</template>
                      </ElTableColumn>
                      <ElTableColumn label="置信度" width="96">
                        <template #default="{ row }">
                          {{ row.confidence === undefined ? '-' : scorePercent(row.confidence) }}
                        </template>
                      </ElTableColumn>
                    </ElTable>
                    <ElEmpty v-else description="OCR 结果暂无可标注 ROI。" />
                  </ElTabPane>
                  <ElTabPane label="字段">
                    <ElTable
                      v-if="selectedOcrCapabilityFields.length"
                      :data="selectedOcrCapabilityFields"
                    >
                      <ElTableColumn
                        prop="fieldCode"
                        label="字段"
                        min-width="150"
                        show-overflow-tooltip
                      >
                        <template #default="{ row }">{{
                          friendlyFieldLabel(row.fieldCode || row.fieldName)
                        }}</template>
                      </ElTableColumn>
                      <ElTableColumn
                        prop="fieldValue"
                        label="识别值"
                        min-width="180"
                        show-overflow-tooltip
                      />
                      <ElTableColumn prop="confidence" label="置信度" width="95" />
                    </ElTable>
                    <ElEmpty v-else description="暂无结构化字段输出。" />
                  </ElTabPane>
                  <ElTabPane label="表格">
                    <div
                      v-if="selectedOcrCapabilityTablePreviews.length"
                      class="ocr-table-result-list"
                    >
                      <article
                        v-for="table in selectedOcrCapabilityTablePreviews"
                        :key="table.id"
                        class="ocr-table-result-card"
                      >
                        <div class="ocr-table-result-card__head">
                          <strong>{{ table.title }}</strong>
                          <dl class="ocr-table-meta">
                            <div v-for="item in table.meta" :key="item.label">
                              <dt>{{ item.label }}</dt>
                              <dd>{{ item.value }}</dd>
                            </div>
                          </dl>
                        </div>
                        <table class="ocr-structured-table">
                          <thead>
                            <tr>
                              <th v-for="column in table.columns" :key="column.key">
                                {{ column.label }}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="row in table.rows" :key="row.id">
                              <td v-for="column in table.columns" :key="column.key">
                                {{ row.cells[column.key] || '-' }}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </article>
                    </div>
                    <ElEmpty v-else description="暂无表格输出。" />
                  </ElTabPane>
                  <ElTabPane label="印章">
                    <div v-if="selectedOcrCapabilitySealRows.length" class="ocr-seal-result-list">
                      <article
                        v-for="seal in selectedOcrCapabilitySealRows"
                        :key="seal.id"
                        class="ocr-seal-result-card"
                      >
                        <div class="ocr-seal-result-card__head">
                          <div>
                            <span>{{ seal.colorLabel }} · {{ seal.typeLabel }}</span>
                            <strong>{{ seal.title }}</strong>
                          </div>
                          <ElTag :type="seal.tagType" effect="plain">{{ seal.status }}</ElTag>
                        </div>
                        <dl class="ocr-seal-meta">
                          <div v-for="item in seal.meta" :key="item.label">
                            <dt>{{ item.label }}</dt>
                            <dd>{{ item.value }}</dd>
                          </div>
                        </dl>
                        <div class="ocr-seal-content">
                          <span>格式化内容</span>
                          <template v-if="seal.contentLines.length">
                            <p v-for="line in seal.contentLines" :key="line">{{ line }}</p>
                          </template>
                          <small v-else>已定位印章框，但当前 OCR 未读出可格式化文字。</small>
                        </div>
                      </article>
                    </div>
                    <ElEmpty v-else description="暂无印章输出。" />
                  </ElTabPane>
                  <ElTabPane label="诊断">
                    <ElTable
                      v-if="selectedOcrCapabilityDiagnostics.length"
                      :data="selectedOcrCapabilityDiagnostics"
                    >
                      <ElTableColumn prop="code" label="问题" min-width="180" show-overflow-tooltip>
                        <template #default="{ row }">{{
                          friendlyIssueLabel(row.code || row)
                        }}</template>
                      </ElTableColumn>
                      <ElTableColumn
                        prop="message"
                        label="说明"
                        min-width="260"
                        show-overflow-tooltip
                      />
                    </ElTable>
                    <ElEmpty v-else description="暂无诊断输出。" />
                  </ElTabPane>
                </ElTabs>
              </div>
            </section>
          </section>
        </ElDialog>

        <div class="workbench-summary-grid ocr-command-kpis">
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

        <ElRow :gutter="16">
          <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel chart-panel">
              <template #header>
                <div class="panel-header">
                  <span>质量分布</span>
                  <ElSpace wrap>
                    <ElTag effect="plain">OCR 场景质量热力图</ElTag>
                    <span class="chart-zoom-value">{{ chartZoomPercent('ocrHeatmap') }}</span>
                    <ElButton
                      size="small"
                      text
                      aria-label="缩小 OCR 场景质量热力图"
                      @click="zoomOutChart('ocrHeatmap')"
                      >缩小</ElButton
                    >
                    <ElButton
                      size="small"
                      text
                      aria-label="放大 OCR 场景质量热力图"
                      @click="zoomInChart('ocrHeatmap')"
                      >放大</ElButton
                    >
                    <ElButton
                      size="small"
                      text
                      aria-label="重置 OCR 场景质量热力图"
                      @click="resetChartZoom('ocrHeatmap')"
                      >重置</ElButton
                    >
                  </ElSpace>
                </div>
              </template>
              <div
                class="knowledge-chart-shell knowledge-chart-shell--heatmap"
                role="img"
                tabindex="0"
                aria-label="OCR 场景质量热力图"
                @wheel.capture="handleChartWheel($event, 'ocrHeatmap')"
                @keydown="handleChartKeydown($event, 'ocrHeatmap')"
                @gesturestart.capture="startNativeChartGesture($event, 'ocrHeatmap')"
                @gesturechange.capture="changeNativeChartGesture($event, 'ocrHeatmap')"
                @gestureend.capture="endNativeChartGesture($event, 'ocrHeatmap')"
                @pointerdown.capture="startChartGesture($event, 'ocrHeatmap')"
                @pointermove.capture="moveChartGesture($event, 'ocrHeatmap')"
                @pointerup.capture="endChartGesture($event, 'ocrHeatmap')"
                @pointercancel.capture="endChartGesture($event, 'ocrHeatmap')"
              >
                <div class="chart-zoom-frame" :style="chartFrameStyle('ocrHeatmap', 1100, 300)">
                  <div
                    class="chart-zoom-content"
                    :style="chartContentStyle('ocrHeatmap', 1100, 300)"
                  >
                    <Echart
                      :options="ocrQualityHeatmapOption"
                      :width="chartBaseWidth(1100)"
                      :height="chartBaseHeight(300)"
                      class="knowledge-echart"
                    />
                  </div>
                </div>
              </div>
            </ElCard>
          </ElCol>
          <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel ocr-priority-panel">
              <template #header>
                <div class="panel-header">
                  <span>优先处理</span>
                  <ElTag :type="ocrTopBlockerRows.length ? 'warning' : 'success'" effect="plain">
                    {{ ocrTopBlockerRows.length || '无' }} 项
                  </ElTag>
                </div>
              </template>
              <div v-if="ocrTopBlockerRows.length" class="ocr-blocker-list">
                <article v-for="row in ocrTopBlockerRows.slice(0, 4)" :key="String(row.id)">
                  <ElTag type="warning" effect="plain">{{ friendlyTechLabel(row.source) }}</ElTag>
                  <strong>{{ row.blocker }}</strong>
                  <small>{{ row.action }}</small>
                </article>
              </div>
              <ElEmpty v-else description="当前没有 OCR 阻断项" />
            </ElCard>
          </ElCol>
        </ElRow>

        <ElRow :gutter="16" class="mt-16px">
          <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>待标注样本</span>
                  <ElTag effect="plain">{{ ocrAnnotationRows.length }} 条</ElTag>
                </div>
              </template>
              <ElTable :data="ocrAnnotationRows.slice(0, 6)" border>
                <ElTableColumn label="样本" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ row.caseId || row.taskId || '-' }}
                  </template>
                </ElTableColumn>
                <ElTableColumn label="资料类型" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">{{
                    friendlyTechLabel(row.documentType || row.scenario || '-')
                  }}</template>
                </ElTableColumn>
                <ElTableColumn label="状态" width="120">
                  <template #default="{ row }">
                    <ElTag :type="ocrAnnotationStatusType(row)" effect="plain">
                      {{ ocrAnnotationStatusLabel(row) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="120">
                  <template #default="{ row }">
                    <ElButton size="small" text @click="openAnnotationEditor(row)">标注</ElButton>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElCard>
          </ElCol>
          <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
            <ElCard shadow="never" class="panel">
              <template #header>
                <div class="panel-header">
                  <span>评估门禁</span>
                  <ElTag :type="ocr100Scorecard?.ok ? 'success' : 'warning'" effect="plain">
                    {{ ocr100Scorecard?.ok ? '可发布' : '需修复' }}
                  </ElTag>
                </div>
              </template>
              <ElDescriptions :column="1" border>
                <ElDescriptionsItem label="OCR 100">
                  {{
                    ocr100Scorecard
                      ? `${ocr100Scorecard.score}/${ocr100Scorecard.targetScore}`
                      : '-'
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="可评估样本">{{
                  ocrReadyForEvalCount
                }}</ElDescriptionsItem>
                <ElDescriptionsItem label="字段低置信">
                  {{ ocrQuality?.fieldLevel?.lowConfidence || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="表格结构">
                  {{ ocrQuality?.tableLevel?.formalTableCount || 0 }}/{{
                    ocrQuality?.tableLevel?.tableCount || 0
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="印章可读">
                  {{ ocrQuality?.sealLevel?.readableSealCount || 0 }}/{{
                    ocrQuality?.sealLevel?.sealCount || 0
                  }}
                </ElDescriptionsItem>
              </ElDescriptions>
            </ElCard>
          </ElCol>
        </ElRow>
      </div>

      <div v-if="isFdeRoute('dashboard')" class="metric-grid">
        <div
          v-for="metric in dashboardMetricHighlights"
          :key="metric.label"
          :class="`metric-card metric-card--${metric.tone}`"
        >
          <span>{{ metric.label }}</span>
          <strong>{{ metric.suffix === '%' ? percent(metric.value) : metric.value }}</strong>
        </div>
      </div>

      <details
        v-if="
          isFdeRoute('dashboard') && dashboardMetricCards.length > dashboardMetricHighlights.length
        "
        class="project-overview-diagnostics fde-dashboard-secondary"
      >
        <summary>
          <span>更多总览指标</span>
          <small
            >{{ dashboardMetricCards.length - dashboardMetricHighlights.length }} 个低频指标</small
          >
        </summary>
        <div class="metric-grid metric-grid--secondary">
          <div
            v-for="metric in dashboardMetricCards.slice(dashboardMetricHighlights.length)"
            :key="metric.label"
            :class="`metric-card metric-card--${metric.tone}`"
          >
            <span>{{ metric.label }}</span>
            <strong>{{ metric.suffix === '%' ? percent(metric.value) : metric.value }}</strong>
          </div>
        </div>
      </details>

      <div
        v-if="isFdeRoute('dashboard')"
        class="workflow-grid workflow-grid--tabs"
        role="tablist"
        aria-label="FDE 重点工作流"
      >
        <button
          v-for="card in fdeWorkflowCards"
          :key="card.key"
          type="button"
          :class="[
            'workflow-card',
            `workflow-card--${card.tone}`,
            { 'is-active': selectedFdeDashboardTab === card.key }
          ]"
          role="tab"
          aria-controls="fde-dashboard-workflow-panel"
          :aria-selected="selectedFdeDashboardTab === card.key"
          @click="selectedFdeDashboardTab = card.key"
        >
          <span>{{ card.title }}</span>
          <strong>{{ card.metric }}</strong>
          <small>{{ card.description }}</small>
          <em>{{ selectedFdeDashboardTab === card.key ? '当前' : card.action }}</em>
        </button>
      </div>

      <section
        v-if="isFdeRoute('dashboard')"
        id="fde-dashboard-workflow-panel"
        class="fde-dashboard-detail"
        role="tabpanel"
        aria-live="polite"
      >
        <div class="fde-dashboard-detail__header">
          <div>
            <span>当前重点</span>
            <strong>{{ selectedFdeWorkflowCard?.title }}</strong>
            <small>{{ selectedFdeWorkflowCard?.description }}</small>
          </div>
          <ElButton plain type="primary" @click="goFdeRoute(selectedFdeWorkflowCard.route)">
            进入详情
          </ElButton>
        </div>

        <template v-if="selectedFdeDashboardTab === 'agent'">
          <ElAlert
            :type="hasReviewRuns ? 'success' : 'warning'"
            show-icon
            :closable="false"
            :title="reviewRunConclusion"
          />
          <ElTable
            v-if="hasReviewRuns"
            :data="reviewRuns.slice(0, 5)"
            border
            class="mt-12px"
            @row-click="(row) => openReviewAuditDrawer(String(row.reviewRunId || row.id))"
          >
            <ElTableColumn
              prop="reviewRunId"
              label="审查任务"
              min-width="190"
              show-overflow-tooltip
            />
            <ElTableColumn prop="workflowEngine" label="外层" width="110">
              <template #default="{ row }">{{ friendlyTechLabel(row.workflowEngine) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="graphEngine" label="内层" width="110">
              <template #default="{ row }">{{ friendlyTechLabel(row.graphEngine) }}</template>
            </ElTableColumn>
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
                  size="small"
                  text
                  @click.stop="openReviewAuditDrawer(String(row.reviewRunId || row.id))"
                >
                  详情
                </ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </template>

        <template v-else>
          <div class="gate-summary">
            <div class="gate-summary-item">
              <span>待标注样本</span>
              <strong>{{ ocrPendingAnnotationCount }}</strong>
            </div>
            <div class="gate-summary-item">
              <span>可评估样本</span>
              <strong>{{ ocrReadyForEvalCount }}</strong>
            </div>
            <div class="gate-summary-item">
              <span>OCR 100</span>
              <strong>
                {{
                  ocr100Scorecard
                    ? `${ocr100Scorecard.score}/${ocr100Scorecard.targetScore}`
                    : '待评估'
                }}
              </strong>
            </div>
            <div class="gate-summary-item">
              <span>首要问题</span>
              <strong>{{ ocrTopBlockerRows.length }}</strong>
            </div>
          </div>
          <ElTable
            v-if="ocrTopBlockerRows.length"
            :data="ocrTopBlockerRows.slice(0, 4)"
            border
            class="mt-12px"
          >
            <ElTableColumn prop="source" label="来源" width="120" />
            <ElTableColumn prop="blocker" label="问题" min-width="260" show-overflow-tooltip />
            <ElTableColumn prop="action" label="处理动作" min-width="260" show-overflow-tooltip />
          </ElTable>
          <ElEmpty v-else class="mt-12px" description="当前没有 OCR 阻断项。" />
        </template>
      </section>

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
              业务类型 {{ friendlyTechLabel(selectedFdeProject?.businessPackId) }}
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

          <div class="project-overview-command-grid">
            <ElCard shadow="never" class="panel project-overview-chart-panel">
              <template #header>
                <div class="panel-header">
                  <span>项目节点态势</span>
                  <ElTag effect="plain">{{ projectAuditNodeRows.length }} 个节点</ElTag>
                </div>
              </template>
              <div class="project-overview-node-status-bars" aria-label="项目节点状态分布">
                <article
                  v-for="row in projectAuditNodeStatusBarRows"
                  :key="row.status"
                  :class="[
                    'project-overview-node-status-row',
                    `project-overview-node-status-row--${row.tone}`
                  ]"
                  :aria-label="`${row.status}：${row.count} 个节点，占比 ${row.percent}%`"
                >
                  <span>{{ row.status }}</span>
                  <div class="project-overview-node-status-track">
                    <i :style="{ width: `${row.barPercent}%` }"></i>
                  </div>
                  <strong>
                    {{ row.count }}
                    <small>{{ row.ratioText }}</small>
                  </strong>
                </article>
              </div>
            </ElCard>

            <ElCard shadow="never" class="panel project-overview-chart-panel">
              <template #header>
                <div class="panel-header">
                  <span>AI 能力健康</span>
                  <ElTag
                    :type="
                      projectAuditCapabilityRows.some((row) => row.blockers) ? 'warning' : 'success'
                    "
                    effect="plain"
                  >
                    {{
                      projectAuditCapabilityRows.some((row) => row.blockers) ? '需处理' : '可审查'
                    }}
                  </ElTag>
                </div>
              </template>
              <Echart
                :options="projectAuditCapabilityOption"
                height="240px"
                class="project-overview-echart"
              />
            </ElCard>
          </div>

          <div class="project-overview-governance-grid">
            <ElCard shadow="never" class="panel project-overview-governance-panel">
              <template #header>
                <div class="panel-header">
                  <span>AI 能力处理清单</span>
                  <ElTag effect="plain">{{ projectAuditCapabilityRows.length }} 类能力</ElTag>
                </div>
              </template>
              <div class="project-overview-capability-list">
                <button
                  v-for="row in projectAuditCapabilityRows"
                  :key="row.key"
                  type="button"
                  :class="[
                    'project-overview-capability-item',
                    `project-overview-item--${row.tone}`
                  ]"
                  @click="goProjectAuditSubpage(row.subpage)"
                >
                  <span>{{ row.label }}</span>
                  <strong>{{ row.status }}</strong>
                  <small>{{ row.value }} · {{ row.evidence }}</small>
                  <ElTag :type="fdeTagType(row.tone)" effect="plain">
                    {{ row.blockers ? `${row.blockers} 个缺口` : '正常' }}
                  </ElTag>
                </button>
              </div>
            </ElCard>

            <ElCard shadow="never" class="panel project-overview-governance-panel">
              <template #header>
                <div class="panel-header">
                  <span>最近任务流</span>
                  <ElTag effect="plain">{{ projectAuditRecentTaskRows.length }} 条</ElTag>
                </div>
              </template>
              <div class="project-overview-task-list">
                <button
                  v-for="row in projectAuditRecentTaskRows"
                  :key="`${row.type}-${row.title}`"
                  type="button"
                  :class="['project-overview-task-item', `project-overview-item--${row.tone}`]"
                  @click="goProjectAuditSubpage(row.subpage)"
                >
                  <span>{{ row.type }}</span>
                  <strong>{{ row.title }}</strong>
                  <small>{{ friendlyStatus(row.status) }} · {{ row.time }}</small>
                </button>
                <div v-if="!projectAuditRecentTaskRows.length" class="audit-empty-state">
                  <strong>暂无任务</strong>
                  <span>当前项目尚未返回 OCR、Agent 或提交批次任务。</span>
                </div>
              </div>
            </ElCard>

            <ElCard shadow="never" class="panel project-overview-governance-panel">
              <template #header>
                <div class="panel-header">
                  <span>下一步动作</span>
                  <ElTag
                    :type="projectAuditNextActionRows.length ? 'warning' : 'success'"
                    effect="plain"
                  >
                    {{ projectAuditNextActionRows.length || '无' }}
                  </ElTag>
                </div>
              </template>
              <div class="project-overview-action-list">
                <button
                  v-for="row in projectAuditNextActionRows"
                  :key="`${row.tag}-${row.title}`"
                  type="button"
                  :class="['project-overview-action-item', `project-overview-item--${row.tone}`]"
                  @click="goProjectAuditSubpage(row.subpage)"
                >
                  <span>{{ row.tag }}</span>
                  <strong>{{ row.title }}</strong>
                  <small>{{ row.description }}</small>
                </button>
                <div v-if="!projectAuditNextActionRows.length" class="audit-empty-state">
                  <strong>无待处理动作</strong>
                  <span>当前项目的 OCR、资料向量化、章节溯源和 Agent 门禁均未返回阻断。</span>
                </div>
              </div>
            </ElCard>
          </div>

          <details class="project-overview-diagnostics">
            <summary>
              <span>详细诊断</span>
              <small>
                链路 {{ projectAuditLangGraphAuditRows.length }} 环节 · 缺口
                {{ projectAuditLangGraphIssueRows.length }} · 阻断 {{ projectAuditBlockers.length }}
              </small>
            </summary>

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
                    <span class="audit-health-dot" aria-hidden="true"></span>
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
                  <span>流程编排、Agent 图、工具证据、规则检索和质量门禁均已返回。</span>
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
          </details>
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

          <section class="vector-lineage-intro" aria-label="资料知识资产溯源">
            <div>
              <span>资料知识资产溯源</span>
              <strong>每份资料为什么能进入 Agent 审查</strong>
              <small>
                以资料版本为主线串联 OCR 解析、知识切片、向量入库、章节溯源和审查可用性。
              </small>
            </div>
            <ElTag :type="fdeTagType(projectAuditVectorQualityTone)" effect="plain">
              {{ projectAuditVectorIndexProfile.issueSummary }}
            </ElTag>
          </section>

          <ElCard shadow="never" class="panel technology-stack-panel mb-16px">
            <template #header>
              <div class="panel-header">
                <span>当前技术选型</span>
                <ElSpace wrap>
                  <ElTag type="success" effect="plain">本地私有化</ElTag>
                  <ElTag effect="plain">
                    {{
                      friendlyTechLabel(
                        projectAuditTechnologyHotSwap.stableAlias || 'embedding-default'
                      )
                    }}
                    可切换
                  </ElTag>
                </ElSpace>
              </div>
            </template>
            <section class="technology-stack-grid" aria-label="当前技术选型">
              <article
                v-for="section in projectAuditTechnologySections"
                :key="section.key"
                :class="['technology-stack-card', `technology-stack-card--${section.tone}`]"
              >
                <span>{{ section.title }}</span>
                <strong>{{ section.primary }}</strong>
                <em v-if="section.secondary">{{ section.secondary }}</em>
                <small>{{ section.detail }}</small>
              </article>
            </section>
            <ElTable
              v-if="projectAuditEmbeddingRegistryRows.length"
              :data="projectAuditEmbeddingRegistryRows"
              border
              class="technology-model-table"
            >
              <ElTableColumn
                prop="label"
                label="可切换模型"
                min-width="190"
                show-overflow-tooltip
              />
              <ElTableColumn prop="modelId" label="模型 ID" min-width="240" show-overflow-tooltip />
              <ElTableColumn prop="role" label="角色" width="150" show-overflow-tooltip />
              <ElTableColumn prop="dimensions" label="维度" width="90" />
              <ElTableColumn prop="contextLength" label="上下文" width="105" />
              <ElTableColumn prop="provider" label="服务" width="130" show-overflow-tooltip />
              <ElTableColumn
                prop="indexVersion"
                label="索引版本"
                min-width="210"
                show-overflow-tooltip
              />
            </ElTable>
          </ElCard>

          <section class="audit-flow-strip" aria-label="资料向量化审计流程">
            <article
              v-for="row in projectAuditVectorFlowRows"
              :key="row.step"
              :class="['audit-flow-card', `audit-flow-card--${row.tone}`]"
            >
              <span>{{ row.step }}</span>
              <div>
                <strong>{{ row.label }}</strong>
                <small>{{ row.description }}</small>
              </div>
              <em>{{ row.done }}/{{ row.total }}</em>
            </article>
          </section>

          <section class="vector-quality-board" aria-label="向量化质量量化">
            <article
              v-for="card in projectAuditVectorQualityCards"
              :key="card.label"
              :class="['vector-quality-card', `vector-quality-card--${card.tone}`]"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.hint }}</small>
            </article>
          </section>

          <ElRow :gutter="16" class="mb-16px">
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel vector-quality-panel">
                <template #header>
                  <div class="panel-header">
                    <span>向量质量维度</span>
                    <ElTag :type="fdeTagType(projectAuditVectorQualityTone)" effect="plain">
                      {{ rawProjectAuditVectorQuality.statusLabel || '需补齐质量证据' }}
                    </ElTag>
                  </div>
                </template>
                <Echart
                  :options="projectAuditVectorQualityRadarOption"
                  height="300px"
                  class="vector-quality-echart"
                />
              </ElCard>
            </ElCol>
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel vector-quality-panel">
                <template #header>
                  <div class="panel-header">
                    <span>资料级向量分数</span>
                    <ElTag effect="plain">
                      {{ projectAuditVectorQualityDocumentRows.length }} 个资料版本
                    </ElTag>
                  </div>
                </template>
                <Echart
                  :options="projectAuditVectorQualityBarOption"
                  height="300px"
                  class="vector-quality-echart"
                />
              </ElCard>
            </ElCol>
          </ElRow>

          <ElAlert
            v-if="projectAuditVectorQualityBlockers.length"
            class="mb-16px"
            type="warning"
            :closable="false"
            show-icon
          >
            <template #title>
              向量质量阻断：{{ projectAuditVectorQualityBlockers.slice(0, 3).join('；') }}
            </template>
          </ElAlert>

          <ElCard shadow="never" class="panel chart-panel mb-16px">
            <template #header>
              <div class="panel-header">
                <span>资料向量化链路图</span>
                <ElSpace wrap>
                  <ElTag effect="plain">Sankey</ElTag>
                  <span class="chart-zoom-value">{{ chartZoomPercent('vectorSankey') }}</span>
                  <ElButton
                    size="small"
                    text
                    aria-label="缩小资料向量化链路图"
                    @click="zoomOutChart('vectorSankey')"
                    >缩小</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="放大资料向量化链路图"
                    @click="zoomInChart('vectorSankey')"
                    >放大</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="重置资料向量化链路图"
                    @click="resetChartZoom('vectorSankey')"
                    >重置</ElButton
                  >
                </ElSpace>
              </div>
            </template>
            <div
              class="knowledge-chart-shell knowledge-chart-shell--sankey"
              role="img"
              tabindex="0"
              aria-label="资料向量化链路图"
              @wheel.capture="handleChartWheel($event, 'vectorSankey')"
              @keydown="handleChartKeydown($event, 'vectorSankey')"
              @gesturestart.capture="startNativeChartGesture($event, 'vectorSankey')"
              @gesturechange.capture="changeNativeChartGesture($event, 'vectorSankey')"
              @gestureend.capture="endNativeChartGesture($event, 'vectorSankey')"
              @pointerdown.capture="startChartGesture($event, 'vectorSankey')"
              @pointermove.capture="moveChartGesture($event, 'vectorSankey')"
              @pointerup.capture="endChartGesture($event, 'vectorSankey')"
              @pointercancel.capture="endChartGesture($event, 'vectorSankey')"
            >
              <div class="chart-zoom-frame" :style="chartFrameStyle('vectorSankey', 1280, 320)">
                <div
                  class="chart-zoom-content"
                  :style="chartContentStyle('vectorSankey', 1280, 320)"
                >
                  <Echart
                    :options="projectAuditVectorSankeyOption"
                    :width="chartBaseWidth(1280)"
                    :height="chartBaseHeight(320)"
                    class="knowledge-echart"
                  />
                </div>
              </div>
            </div>
          </ElCard>

          <ElRow :gutter="16">
            <ElCol :span="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>资料索引入库状态</span>
                    <ElTag effect="plain">
                      {{ normalizedProjectAuditVectorRows.length }} 个资料版本
                    </ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedProjectAuditVectorRows" border>
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
                  <ElTableColumn prop="ocrStatus" label="OCR 识别" width="120">
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
                  <ElTableColumn label="质量分" width="88">
                    <template #default="{ row }">
                      {{
                        projectAuditVectorQualityDocumentRows.find(
                          (item) =>
                            String(item.documentVersionId || item.id) ===
                            String(row.documentVersionId || row.id)
                        )?.score ?? '-'
                      }}
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
                  <ElTableColumn label="操作" width="100" fixed="right">
                    <template #default="{ row }">
                      <ElButton
                        size="small"
                        text
                        data-testid="fde-open-vector-file-detail"
                        aria-label="查看文件向量质量详情"
                        @click.stop="openVectorFileQualityDrawer(row)"
                      >
                        详情
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>索引配置</template>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="向量模型">
                    {{ friendlyTechLabel(projectAuditVectorIndexProfile.embeddingModel) }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="向量维度">
                    {{ projectAuditVectorIndexProfile.vectorDimensions }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="索引版本">
                    {{ projectAuditVectorIndexProfile.indexVersion }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="Lineage 来源">
                    {{ projectAuditLineageSourceLabel }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="RAG 就绪">
                    {{ projectAuditVectorIndexProfile.ragReady }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="章节溯源就绪">
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
            </ElCol>
            <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>向量入库状态</template>
                <ElTable :data="normalizedProjectAuditVectorRows" border>
                  <ElTableColumn
                    prop="fileName"
                    label="资料"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="chunkCount" label="切片" width="82" />
                  <ElTableColumn prop="vectorCount" label="向量" width="82" />
                  <ElTableColumn prop="readyForRag" label="知识检索" width="92">
                    <template #default="{ row }">
                      <ElTag :type="row.readyForRag ? 'success' : 'warning'" effect="plain">
                        {{ row.readyForRag ? '可用' : '待补' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>异常与处理建议</template>
                <ElTable :data="projectAuditVectorIssueRows" border empty-text="暂无异常">
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

          <section class="audit-flow-strip" aria-label="章节溯源路由审计流程">
            <article
              v-for="row in projectAuditPageIndexFlowRows"
              :key="row.step"
              :class="['audit-flow-card', `audit-flow-card--${row.tone}`]"
            >
              <span>{{ row.step }}</span>
              <div>
                <strong>{{ row.label }}</strong>
                <small>{{ row.description }}</small>
              </div>
              <em>{{ row.value }}</em>
            </article>
          </section>

          <ElCard shadow="never" class="panel chart-panel mb-16px">
            <template #header>
              <div class="panel-header">
                <span>章节溯源检索树</span>
                <ElSpace wrap>
                  <ElTag effect="plain">Tree</ElTag>
                  <span class="chart-zoom-value">{{ chartZoomPercent('pageIndexTree') }}</span>
                  <ElButton
                    size="small"
                    text
                    aria-label="缩小章节溯源检索树"
                    @click="zoomOutChart('pageIndexTree')"
                    >缩小</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="放大章节溯源检索树"
                    @click="zoomInChart('pageIndexTree')"
                    >放大</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="重置章节溯源检索树"
                    @click="resetChartZoom('pageIndexTree')"
                    >重置</ElButton
                  >
                </ElSpace>
              </div>
            </template>
            <div
              class="knowledge-chart-shell knowledge-chart-shell--tree"
              role="img"
              tabindex="0"
              aria-label="章节溯源树"
              @wheel.capture="handleChartWheel($event, 'pageIndexTree')"
              @keydown="handleChartKeydown($event, 'pageIndexTree')"
              @gesturestart.capture="startNativeChartGesture($event, 'pageIndexTree')"
              @gesturechange.capture="changeNativeChartGesture($event, 'pageIndexTree')"
              @gestureend.capture="endNativeChartGesture($event, 'pageIndexTree')"
              @pointerdown.capture="startChartGesture($event, 'pageIndexTree')"
              @pointermove.capture="moveChartGesture($event, 'pageIndexTree')"
              @pointerup.capture="endChartGesture($event, 'pageIndexTree')"
              @pointercancel.capture="endChartGesture($event, 'pageIndexTree')"
            >
              <div class="chart-zoom-frame" :style="chartFrameStyle('pageIndexTree', 1720, 470)">
                <div
                  class="chart-zoom-content"
                  :style="chartContentStyle('pageIndexTree', 1720, 470)"
                >
                  <Echart
                    :options="projectAuditPageIndexTreeOption"
                    :width="chartBaseWidth(1720)"
                    :height="chartBaseHeight(470)"
                    class="knowledge-echart"
                  />
                </div>
              </div>
            </div>
          </ElCard>

          <section class="pageindex-friendly-grid" aria-label="章节溯源友好判读">
            <article class="pageindex-friendly-intro">
              <span>章节溯源友好判读</span>
              <strong>每次检索为什么这样走</strong>
              <small> 先看问题类型、路由、节点、条款和回退策略；需要追责时再进入原始溯源。 </small>
            </article>
            <article
              v-for="card in projectAuditPageIndexFriendlyCards"
              :key="card.id"
              class="pageindex-friendly-card"
            >
              <div class="pageindex-friendly-card__head">
                <span>{{ card.sequence }}</span>
                <div>
                  <strong>{{ card.query }}</strong>
                  <small>{{ friendlyTechLabel(card.queryType) }}</small>
                </div>
                <ElTag :type="card.ok ? 'success' : 'warning'" effect="plain">
                  {{ card.ok ? '可用于审查' : '需处理' }}
                </ElTag>
              </div>
              <div class="pageindex-friendly-facts">
                <span v-for="fact in card.facts" :key="`${card.id}-${fact.label}`">
                  <em>{{ fact.label }}</em>
                  <strong>{{ fact.value }}</strong>
                </span>
              </div>
              <p>{{ card.conclusion }}</p>
            </article>
          </section>

          <ElRow :gutter="16">
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>章节溯源路由追踪</span>
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
                        <span>追踪ID</span>
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
                    <div class="pageindex-route-flow" aria-label="章节溯源路由决策">
                      <span>检索路由器</span>
                      <i></i>
                      <strong>{{ friendlyTechLabel(row.selectedRoute) }}</strong>
                      <em v-if="row.fallbackRoute !== '-'">
                        回退 {{ friendlyTechLabel(row.fallbackRoute) }}
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
                <ElEmpty v-else description="暂无章节溯源路由追踪" />
              </ElCard>
            </ElCol>
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>章节溯源资料覆盖</template>
                <ElTable :data="projectAuditPageIndexCoverageRows" border>
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
                <ElTable :data="projectAuditPageIndexNodeRows" border>
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
                <ElTable :data="projectAuditPageIndexIssueRows" border empty-text="暂无异常">
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
            title="章节溯源用于长文档、跨章节、附录和表格依据检索；普通条款命中仍优先走条款索引和混合检索。"
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

          <ElCard shadow="never" class="panel chart-panel mb-16px">
            <template #header>
              <div class="panel-header">
                <span>Temporal 执行时间线</span>
                <ElSpace wrap>
                  <ElTag effect="plain">{{ reviewTimelineChartRows.length }} 个环节</ElTag>
                  <span class="chart-zoom-value">{{ chartZoomPercent('reviewTimeline') }}</span>
                  <ElButton
                    size="small"
                    text
                    aria-label="缩小 Temporal 执行时间线"
                    @click="zoomOutChart('reviewTimeline')"
                    >缩小</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="放大 Temporal 执行时间线"
                    @click="zoomInChart('reviewTimeline')"
                    >放大</ElButton
                  >
                  <ElButton
                    size="small"
                    text
                    aria-label="重置 Temporal 执行时间线"
                    @click="resetChartZoom('reviewTimeline')"
                    >重置</ElButton
                  >
                </ElSpace>
              </div>
            </template>
            <div
              class="knowledge-chart-shell knowledge-chart-shell--timeline"
              role="img"
              tabindex="0"
              aria-label="Temporal 执行时间线"
              @wheel.capture="handleChartWheel($event, 'reviewTimeline')"
              @keydown="handleChartKeydown($event, 'reviewTimeline')"
              @gesturestart.capture="startNativeChartGesture($event, 'reviewTimeline')"
              @gesturechange.capture="changeNativeChartGesture($event, 'reviewTimeline')"
              @gestureend.capture="endNativeChartGesture($event, 'reviewTimeline')"
              @pointerdown.capture="startChartGesture($event, 'reviewTimeline')"
              @pointermove.capture="moveChartGesture($event, 'reviewTimeline')"
              @pointerup.capture="endChartGesture($event, 'reviewTimeline')"
              @pointercancel.capture="endChartGesture($event, 'reviewTimeline')"
            >
              <div class="chart-zoom-frame" :style="chartFrameStyle('reviewTimeline', 1160, 300)">
                <div
                  class="chart-zoom-content"
                  :style="chartContentStyle('reviewTimeline', 1160, 300)"
                >
                  <Echart
                    :options="reviewTimelineEchartOption"
                    :width="chartBaseWidth(1160)"
                    :height="chartBaseHeight(300)"
                    class="knowledge-echart"
                  />
                </div>
              </div>
            </div>
          </ElCard>

          <ElRow :gutter="16">
            <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>Agent 编排图</span>
                    <ElSpace wrap>
                      <ElTag effect="plain">{{
                        selectedReviewRun?.run.reviewRunId || '未选中'
                      }}</ElTag>
                      <span class="chart-zoom-value">{{ chartZoomPercent('langGraph') }}</span>
                      <ElButton
                        size="small"
                        text
                        aria-label="缩小 Agent 审查编排图"
                        @click="zoomOutChart('langGraph')"
                        >缩小</ElButton
                      >
                      <ElButton
                        size="small"
                        text
                        aria-label="放大 Agent 审查编排图"
                        @click="zoomInChart('langGraph')"
                        >放大</ElButton
                      >
                      <ElButton
                        size="small"
                        text
                        aria-label="重置 Agent 审查编排图"
                        @click="resetChartZoom('langGraph')"
                        >重置</ElButton
                      >
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
                <div
                  v-if="hasLangGraphFlowNodes"
                  class="langgraph-chart-shell"
                  role="img"
                  tabindex="0"
                  aria-label="LangGraph Agent 编排图"
                  @wheel.capture="handleChartWheel($event, 'langGraph')"
                  @keydown="handleChartKeydown($event, 'langGraph')"
                  @gesturestart.capture="startNativeChartGesture($event, 'langGraph')"
                  @gesturechange.capture="changeNativeChartGesture($event, 'langGraph')"
                  @gestureend.capture="endNativeChartGesture($event, 'langGraph')"
                  @pointerdown.capture="startChartGesture($event, 'langGraph')"
                  @pointermove.capture="moveChartGesture($event, 'langGraph')"
                  @pointerup.capture="endChartGesture($event, 'langGraph')"
                  @pointercancel.capture="endChartGesture($event, 'langGraph')"
                >
                  <div class="chart-zoom-frame" :style="chartFrameStyle('langGraph', 1080, 430)">
                    <div
                      class="chart-zoom-content"
                      :style="chartContentStyle('langGraph', 1080, 430)"
                    >
                      <Echart
                        :options="langGraphEchartOption"
                        :width="chartBaseWidth(1080)"
                        :height="chartBaseHeight(430)"
                        class="langgraph-echart"
                      />
                    </div>
                  </div>
                </div>
                <section v-if="normalizedReviewReasoningRows.length" class="langgraph-cog-panel">
                  <div class="langgraph-cog-head">
                    <div>
                      <span>COG 可审计思考摘要</span>
                      <strong>展示公开推理摘要、工具和证据，不展示模型内部隐式思维</strong>
                    </div>
                    <ElTag effect="plain">{{ normalizedReviewReasoningRows.length }} 步</ElTag>
                  </div>
                  <div class="langgraph-cog-list">
                    <article
                      v-for="row in normalizedReviewReasoningRows.slice(0, 3)"
                      :key="`langgraph-cog-${row.sequence}`"
                    >
                      <span>{{ String(row.sequence).padStart(2, '0') }}</span>
                      <div>
                        <strong>{{ friendlyTechLabel(row.stepName) }}</strong>
                        <p>{{ row.reasoningSummary }}</p>
                      </div>
                      <em>{{ row.toolCount }} 工具 · {{ row.evidenceCount }} 证据</em>
                    </article>
                  </div>
                </section>
                <ElEmpty v-if="!reviewGraphNodes.length" description="暂无 Agent 编排节点数据" />
              </ElCard>
            </ElCol>
            <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>阶段泳道</template>
                <div class="langgraph-lane-list" aria-label="Agent 编排阶段泳道">
                  <article
                    v-for="group in langGraphFlowGroups"
                    :key="group.key"
                    :class="['langgraph-lane', `langgraph-lane--${group.tone}`]"
                  >
                    <div class="langgraph-lane-main">
                      <span>{{ String(group.index).padStart(2, '0') }}</span>
                      <strong>{{ group.label }}</strong>
                      <small>{{ group.hint }}</small>
                    </div>
                    <div class="langgraph-lane-meta">
                      <ElTag :type="group.tagType" effect="plain">{{ group.status }}</ElTag>
                      <em>{{ group.nodeCount }} 节点</em>
                      <em>{{ group.toolCount }} 工具</em>
                    </div>
                  </article>
                </div>
              </ElCard>
            </ElCol>
          </ElRow>

          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>流程恢复与检查点</span>
                    <ElTag effect="plain">可重放</ElTag>
                  </div>
                </template>
                <section class="agent-friendly-note mb-12px">
                  <strong>用来回答：任务失败后能不能恢复？</strong>
                  <small>
                    这里记录外层工作流、运行编号、事件数和 LangGraph 检查点，便于 FDE
                    判断是否可以重跑、回放和追责。
                  </small>
                </section>
                <ElDescriptions :column="1" border>
                  <ElDescriptionsItem label="工作流编号">
                    {{
                      selectedReviewTemporal.workflowId || selectedReviewRun?.run.workflowId || '-'
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="运行编号">
                    {{ selectedReviewRun?.run.temporalRunId || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="事件数">
                    {{ selectedReviewTemporal.eventCount || reviewGraphTimeline.length || 0 }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="编排执行器">
                    {{ friendlyTechLabel(selectedReviewRun?.run.graphRunner) }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="检查点">
                    {{ friendlyTechLabel(selectedReviewRun?.run.graphExecution?.checkpointer) }}
                  </ElDescriptionsItem>
                </ElDescriptions>
              </ElCard>
            </ElCol>
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>执行路径与事件时间线</span>
                    <ElTag effect="plain">{{ reviewGraphEdges.length }} 条边</ElTag>
                  </div>
                </template>
                <section class="agent-friendly-note mb-12px">
                  <strong>用来回答：Agent 节点按什么顺序执行？</strong>
                  <small>
                    上表展示节点之间的流向，下表展示最近事件和状态，用于定位卡在哪个节点或哪次工具调用。
                  </small>
                </section>
                <ElTable :data="reviewGraphEdges" border>
                  <ElTableColumn prop="source" label="来源" min-width="130" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.source) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="target" label="目标" min-width="130" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.target) }}</template>
                  </ElTableColumn>
                </ElTable>
                <ElTable :data="reviewGraphTimeline.slice(0, 5)" border class="mt-12px">
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
                    <span>AI 判断依据</span>
                    <ElTag effect="plain">{{ normalizedReviewReasoningRows.length }} 步</ElTag>
                  </div>
                </template>
                <section class="agent-friendly-note mb-12px">
                  <strong>用来回答：AI 为什么提出这些问题？</strong>
                  <small>
                    这里展示可公开审计的判断摘要、调用过的工具、引用的证据和规则；不展示模型内部隐式思维。
                  </small>
                </section>
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
                        <span>AI 看过的证据/依据</span>
                        <strong>{{ shortText(row.evidence, '-') }}</strong>
                      </div>
                      <div class="audit-step-meta">
                        <span class="audit-step-meta-label">可追溯材料</span>
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
                    <span>待人工确认的问题</span>
                    <ElTag effect="plain">{{ normalizedReviewFindingRows.length }} 条</ElTag>
                  </div>
                </template>
                <section class="agent-friendly-note mb-12px">
                  <strong>用来回答：AI 建议监检员处理哪些问题？</strong>
                  <small>
                    这些只是审查建议草稿，不会直接改变业务结论。监检员需要确认、修改或驳回后才生效。
                  </small>
                </section>
                <div v-if="normalizedReviewFindingRows.length" class="finding-friendly-list">
                  <article
                    v-for="row in normalizedReviewFindingRows"
                    :key="row.id"
                    class="finding-friendly-card"
                  >
                    <div class="finding-friendly-main">
                      <span
                        >{{ friendlyTechLabel(row.findingType) }} · {{ row.severityLabel }}</span
                      >
                      <strong>{{ row.title }}</strong>
                      <small>{{ row.evidenceText }}</small>
                    </div>
                    <div class="finding-friendly-side">
                      <ElTag
                        :type="row.requiresHumanConfirmation ? 'warning' : 'success'"
                        effect="plain"
                      >
                        {{ row.requiresHumanConfirmation ? '需要人工确认' : '低风险建议' }}
                      </ElTag>
                      <strong>{{ scorePercent(row.confidence) }}</strong>
                      <small>{{ row.humanNextAction }}</small>
                    </div>
                  </article>
                </div>
                <ElEmpty v-else description="暂无审查建议草稿" />
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
                <ElTable :data="normalizedReviewQualityRows" border>
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
                    <ElSpace>
                      <ElTag effect="plain"
                        >{{ normalizedReviewHumanCorrectionRows.length }} 条</ElTag
                      >
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="createReviewDiagnosticFeedback"
                      >
                        记录诊断修正
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable :data="normalizedReviewHumanCorrectionRows" border>
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
          <section class="ocr-labeling-focus" aria-label="OCR 打标工作台说明">
            <div class="ocr-labeling-focus-copy">
              <span>OCR 打标台</span>
              <strong>把识别结果修成标准答案，用来评估和优化 OCR。</strong>
              <small>本页不审批业务结论，只处理字段、表格、印章和 bbox 的人工标准答案。</small>
            </div>
            <div class="ocr-labeling-focus-steps" aria-label="OCR 打标操作顺序">
              <span
                v-for="row in projectAuditAnnotationWorkflowRows.slice(0, 3)"
                :key="row.step"
                :class="{ done: row.done }"
              >
                {{ row.title }}
              </span>
            </div>
            <div class="ocr-labeling-focus-progress">
              <span>标准答案</span>
              <strong>
                {{ projectAuditAnnotationSummary.labelTotal }}/{{
                  projectAuditAnnotationSummary.candidateTotal || 0
                }}
              </strong>
              <small>可入评估 {{ projectAuditAnnotationSummary.readyForEval }} 个</small>
            </div>
          </section>

          <section class="ocr-labeling-workspace" aria-label="OCR 打标任务区">
            <ElCard shadow="never" class="panel ocr-labeling-queue-panel">
              <template #header>
                <div class="panel-header">
                  <span>待处理样本</span>
                  <ElTag
                    :type="projectAuditAnnotationSummary.gapTotal ? 'warning' : 'success'"
                    effect="plain"
                  >
                    缺口 {{ projectAuditAnnotationSummary.gapTotal }}
                  </ElTag>
                </div>
              </template>
              <div class="ocr-labeling-task-list">
                <article
                  v-for="row in normalizedProjectAuditAnnotationRows"
                  :key="String(row.taskId || row.caseId || row.rowIndex)"
                  :class="[
                    'ocr-labeling-task-card',
                    `ocr-labeling-task-card--${row.priorityTone}`,
                    {
                      active:
                        String(selectedAnnotationTask?.taskId || '') === String(row.taskId || '')
                    }
                  ]"
                  @click="openAnnotationEditor(row.sourceTask)"
                >
                  <div class="ocr-labeling-task-main">
                    <span>{{
                      friendlyTechLabel(row.scenario || row.profileId || 'OCR 样本')
                    }}</span>
                    <strong>{{ row.taskId || row.caseId }}</strong>
                    <small>{{ row.annotationReasonText }}</small>
                  </div>
                  <div class="ocr-labeling-task-meta">
                    <span>{{ row.annotationTargetText }}</span>
                    <strong>{{ row.annotationProgressText }}</strong>
                    <ElTag :type="statusType(String(row.collectionStatus))" effect="plain">
                      {{ friendlyStatus(row.collectionStatus) }}
                    </ElTag>
                  </div>
                  <ElButton
                    size="small"
                    type="primary"
                    plain
                    @click.stop="openAnnotationEditor(row.sourceTask)"
                  >
                    {{ row.annotationNextAction }}
                  </ElButton>
                </article>
                <ElEmpty
                  v-if="!normalizedProjectAuditAnnotationRows.length"
                  description="当前项目暂无 OCR 打标样本"
                />
              </div>
            </ElCard>

            <aside class="ocr-labeling-action-panel" aria-label="OCR 打标操作面板">
              <section
                :class="[
                  'ocr-labeling-action-card',
                  `ocr-labeling-action-card--${projectAuditAnnotationPrimaryAction.tone}`
                ]"
              >
                <span>下一步</span>
                <strong>{{ projectAuditAnnotationPrimaryAction.title }}</strong>
                <small>{{ projectAuditAnnotationPrimaryAction.description }}</small>
                <ElButton
                  type="primary"
                  :loading="actionLoading"
                  @click="openFirstOcrAnnotationTask"
                >
                  打开优先样本
                </ElButton>
              </section>

              <section class="ocr-labeling-plain-guide">
                <span>操作顺序</span>
                <ol>
                  <li>点开左侧样本。</li>
                  <li>核对并修正 OCR 标准答案。</li>
                  <li>二审通过后进入评估集。</li>
                </ol>
              </section>

              <section class="ocr-labeling-mini-stats">
                <article>
                  <span>样本</span>
                  <strong>{{ projectAuditAnnotationSummary.total }}</strong>
                </article>
                <article>
                  <span>已标</span>
                  <strong>{{ projectAuditAnnotationSummary.humanLabeled }}</strong>
                </article>
                <article>
                  <span>评估</span>
                  <strong>{{ projectAuditAnnotationSummary.readyForEval }}</strong>
                </article>
              </section>
            </aside>
          </section>

          <details class="ocr-labeling-diagnostics">
            <summary>
              <span>高级诊断</span>
              <small>覆盖率、完成标准、OCR 任务、候选图和不能入评估的原因</small>
            </summary>
            <ElRow :gutter="16">
              <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
                <ElCard shadow="never" class="panel">
                  <template #header>标准答案覆盖</template>
                  <div class="ocr-labeling-coverage-card ocr-labeling-coverage-card--flat">
                    <article
                      v-for="row in projectAuditAnnotationCoverageRows"
                      :key="row.label"
                      class="ocr-labeling-coverage-row"
                    >
                      <span>{{ row.label }}</span>
                      <div>
                        <i
                          :style="{ width: `${Math.round(Number(row.coverage || 0) * 100)}%` }"
                        ></i>
                      </div>
                      <strong>{{ scorePercent(row.coverage) }}</strong>
                    </article>
                  </div>
                </ElCard>
              </ElCol>
              <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
                <ElCard shadow="never" class="panel">
                  <template #header>完成标准</template>
                  <ElTable :data="projectAuditAnnotationHealthRows" border>
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
              <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
                <ElCard shadow="never" class="panel">
                  <template #header>不能入评估的原因</template>
                  <ElTable :data="projectAuditAnnotationBlockerRows" border>
                    <ElTableColumn
                      prop="blocker"
                      label="原因"
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
              <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
                <ElCard shadow="never" class="panel mt-16px">
                  <template #header>OCR 解析任务</template>
                  <ElTable
                    :data="projectAuditOcrJobs"
                    border
                    @row-click="(row) => openOcrAuditDrawer(String(row.jobId || row.id))"
                  >
                    <ElTableColumn
                      prop="jobId"
                      label="OCR 任务编号"
                      min-width="160"
                      show-overflow-tooltip
                    />
                    <ElTableColumn
                      prop="profileId"
                      label="解析配置"
                      min-width="180"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                    </ElTableColumn>
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
                  <template #header>选中 OCR 结果快照</template>
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
          </details>
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
                <ElTable :data="projectAuditEvaluationGateRows" border>
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
                <ElTable :data="ocrScenarioRows" border class="mt-12px">
                  <ElTableColumn
                    prop="scenario"
                    label="OCR 场景"
                    min-width="180"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.scenario) }}</template>
                  </ElTableColumn>
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
                <ElTable :data="failedOcrCaseRows" border>
                  <ElTableColumn prop="caseId" label="样本" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="scenario" label="场景" min-width="140" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechLabel(row.scenario) }}</template>
                  </ElTableColumn>
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
                <ElTable :data="projectAuditEvaluationIssueRows" border class="mt-12px">
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
              <ElTable :data="projectAuditBindings" border>
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
              <ElTable :data="projectAuditDocuments" border>
                <ElTableColumn prop="fileName" label="文件" min-width="230" show-overflow-tooltip />
                <ElTableColumn
                  prop="currentVersionId"
                  label="当前版本"
                  min-width="140"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="currentOcrStatus" label="OCR 识别" width="120">
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
              <ElTable :data="projectAuditSubmissions" border>
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
                @row-click="(row) => openReviewAuditDrawer(String(row.reviewRunId || row.id))"
              >
                <ElTableColumn
                  prop="reviewRunId"
                  label="审查任务编号"
                  min-width="180"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="workflowId"
                  label="工作流编号"
                  min-width="190"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="agentId" label="AI 员工" min-width="170" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.agentId) }}</template>
                </ElTableColumn>
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
                <ElDescriptionsItem label="审查任务编号">
                  {{ selectedReviewRun.run.reviewRunId || selectedReviewRun.run.id }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="模型">
                  {{ friendlyTechLabel(selectedReviewRun.run.modelAlias) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="编排引擎">
                  {{ friendlyTechLabel(selectedReviewRun.run.graphEngine) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="检查点">
                  {{ friendlyTechLabel(selectedReviewRun.run.graphExecution?.checkpointer) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="输入校验哈希">
                  {{ selectedReviewRun.run.inputHash || '-' }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="输出校验哈希">
                  {{ selectedReviewRun.run.outputHash || '-' }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElEmpty v-else description="请选择 Agent 审查任务" />
            </ElCard>
            <ElCard shadow="never" class="panel mt-16px">
              <template #header>决策链摘要</template>
              <ElTable :data="reviewReasoningTraceRows" border>
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
                @row-click="(row) => openOcrAuditDrawer(String(row.jobId || row.id))"
              >
                <ElTableColumn
                  prop="jobId"
                  label="OCR 任务编号"
                  min-width="160"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="210"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
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
                @row-click="(row) => openAnnotationEditor(row)"
              >
                <ElTableColumn prop="taskId" label="任务" min-width="150" show-overflow-tooltip />
                <ElTableColumn prop="scenario" label="场景" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.scenario) }}</template>
                </ElTableColumn>
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="190"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
                <ElTableColumn label="状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="statusType(String(row.collectionStatus))" effect="plain">
                      {{ friendlyStatus(row.collectionStatus) }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="阻断" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ friendlyIssueList(row.readinessBlockers || row.certificationBlockers) }}
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
              <ElTable :data="projectAuditBlockers" border>
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
              <ElTable :data="nodeStatusSummary" border>
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

      <ElTabs
        v-else-if="!isFdeRoute('dashboard', 'ocr-quality', 'projects')"
        v-model="activeFdeTab"
        :class="['fde-tabs', { 'fde-tabs--single-route': isFdeRoute('review-runs') }]"
      >
        <ElTabPane label="AI 驾驶舱" name="dashboard">
          <ElRow :gutter="16">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Agent 绩效</template>
                <ElTable :data="dashboard?.agentPerformance || []" border>
                  <ElTableColumn
                    prop="agentId"
                    label="AI 员工"
                    min-width="190"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.agentId) }}</template>
                  </ElTableColumn>
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
                <ElTable :data="dashboard?.alerts || []" border>
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
                  <ElDescriptionsItem label="Token 用量">
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
                <ElTable :data="aiRuns" border @row-click="(row) => loadRunDetail(row.id)">
                  <ElTableColumn prop="id" label="运行编号" min-width="190" show-overflow-tooltip />
                  <ElTableColumn
                    prop="agentId"
                    label="AI 员工"
                    min-width="160"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.agentId) }}</template>
                  </ElTableColumn>
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
                    <span>溯源明细</span>
                    <ElButton size="small" plain :loading="actionLoading" @click="requestRawAccess">
                      申请原文
                    </ElButton>
                  </div>
                </template>
                <ElDescriptions v-if="selectedRun" :column="1" border>
                  <ElDescriptionsItem label="运行编号">{{ selectedRun.run.id }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="输入校验哈希">{{
                    selectedRun.run.inputHash
                  }}</ElDescriptionsItem>
                  <ElDescriptionsItem label="输出校验哈希">{{
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
                    <ElTag effect="plain">公开摘要</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewReasoningTraceRows" border>
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
                          .map((item) => friendlyTechLabel(item.toolName))
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
                  <ElTableColumn label="输出校验哈希" min-width="220" show-overflow-tooltip>
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
                <ElTable :data="reviewLineageRows" border>
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
                <ElTable :data="normalizedReviewQualityRows" border>
                  <ElTableColumn prop="name" label="评估项" min-width="150" show-overflow-tooltip />
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
                    prop="message"
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
                    <ElSpace>
                      <ElTag effect="plain">{{ reviewHumanCorrectionRows.length }} 条</ElTag>
                      <ElButton
                        size="small"
                        plain
                        :loading="actionLoading"
                        @click="createReviewDiagnosticFeedback"
                      >
                        记录诊断修正
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable :data="normalizedReviewHumanCorrectionRows" border>
                  <ElTableColumn
                    prop="correctionType"
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
                    prop="before"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.after) }}</template>
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
                    <ElTag effect="plain">公开摘要</ElTag>
                  </div>
                </template>
                <ElTable :data="reviewReasoningTraceRows" border>
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
                          .map((item) => friendlyTechLabel(item.toolName))
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
                  <ElTableColumn label="输出校验哈希" min-width="220" show-overflow-tooltip>
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
                <ElTable :data="reviewLineageRows" border>
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
                <ElTable :data="normalizedReviewQualityRows" border>
                  <ElTableColumn prop="name" label="评估项" min-width="150" show-overflow-tooltip />
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
                    prop="message"
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
                <ElTable :data="normalizedReviewHumanCorrectionRows" border>
                  <ElTableColumn
                    prop="correctionType"
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
                    prop="before"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.after) }}</template>
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
                  <ElDescriptionsItem label="章节溯源触发">{{
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
                <ElTable :data="evaluationCaseRows" border>
                  <ElTableColumn
                    prop="evaluationCaseId"
                    label="Case"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="status" label="状态" width="110">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">{{
                        friendlyStatus(row.status)
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="归因" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">{{
                      friendlyTechnicalText(row.rootCause)
                    }}</template>
                  </ElTableColumn>
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
                  >
                    <template #default="{ row }">{{
                      friendlyTechLabel(row.selectedRoute)
                    }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="缺失条款" min-width="180" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ (row.missingClauseIds || []).join('；') || '-' }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="缺失 Finding" min-width="220" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ friendlyIssueList(row.missingFindings, '-') }}
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="任务编排" name="orchestration">
          <div
            class="workbench-summary-grid agent-status-tabs"
            role="tablist"
            aria-label="Agent 审查状态"
          >
            <button
              v-for="card in agentStatusCards"
              :key="card.key"
              type="button"
              :class="[
                'workbench-summary-card',
                'workbench-summary-card--button',
                `workbench-summary-card--${card.tone}`,
                { 'is-active': agentSubpage === card.key }
              ]"
              role="tab"
              aria-controls="agent-status-panel"
              :aria-selected="agentSubpage === card.key"
              @click="agentSubpage = card.key"
            >
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <small>{{ card.title }} · {{ card.hint }}</small>
            </button>
          </div>
          <ElAlert
            class="mb-16px"
            :type="hasReviewRuns ? 'success' : 'warning'"
            show-icon
            :closable="false"
            :title="reviewRunConclusion"
          />
          <section
            id="agent-status-panel"
            class="agent-status-panel mb-16px"
            role="tabpanel"
            aria-live="polite"
          >
            <div>
              <span>当前明细</span>
              <strong>{{ selectedAgentStatusCard?.title }}</strong>
            </div>
            <small>{{ selectedAgentStatusCard?.hint }}</small>
          </section>
          <ElRow v-if="agentSubpage === 'runs'" :gutter="16">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>流程编排 / AI 审查任务</span>
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
                  @row-click="(row) => openReviewAuditDrawer(String(row.reviewRunId || row.id))"
                >
                  <ElTableColumn
                    prop="reviewRunId"
                    label="审查任务编号"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="workflowId"
                    label="工作流编号"
                    min-width="210"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="workflowEngine" label="外层" width="110">
                    <template #default="{ row }">{{
                      friendlyTechLabel(row.workflowEngine)
                    }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="graphEngine" label="内层" width="110">
                    <template #default="{ row }">{{ friendlyTechLabel(row.graphEngine) }}</template>
                  </ElTableColumn>
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
                    <strong>暂无审查任务</strong>
                    <span>
                      当前没有可追踪的 AI 审查任务。FDE 可以先处理 OCR 阻断，或从业务审查页触发 AI
                      复核后回到这里审计决策链。
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
                  <ElDescriptionsItem label="审查任务编号">
                    {{ selectedReviewRun.run.reviewRunId }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="AI 运行编号">
                    {{ selectedReviewRun.run.aiRunId || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="模型网关">
                    {{ friendlyTechLabel(selectedReviewRun.run.modelGateway || 'litellm') }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="模型别名">
                    {{ friendlyTechLabel(selectedReviewRun.run.modelAlias) }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="编排执行器">
                    {{
                      friendlyTechLabel(
                        selectedReviewRun.run.graphRunner || selectedReviewRun.run.graphEngine
                      )
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="检查点">
                    {{
                      friendlyTechLabel(
                        selectedReviewRun.run.graphExecution?.checkpointer ||
                          selectedReviewRun.run.graphExecution?.fallbackReason
                      )
                    }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="输入校验哈希">
                    {{ selectedReviewRun.run.inputHash || '-' }}
                  </ElDescriptionsItem>
                  <ElDescriptionsItem label="输出校验哈希">
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
                    {{
                      friendlyTechLabel(
                        selectedReviewTemporal.historyPolicy || 'ids_hashes_versions_only'
                      )
                    }}
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
                  <ElTable :data="reviewScorecardSections" border class="mt-12px">
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
                  class="mt-12px"
                >
                  <ElTableColumn label="节点状态">
                    <template #default="{ row }">
                      {{ friendlyStatus(row.status) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="count" label="数量" width="90" />
                </ElTable>
                <ElEmpty v-if="!selectedReviewRun" description="请选择审查任务" />
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
                    <span>AI 判断依据</span>
                    <ElTag effect="plain">公开摘要</ElTag>
                  </div>
                </template>
                <ElTable :data="normalizedReviewReasoningRows" border>
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
                      证据 {{ row.evidenceCount }} / 规则 {{ row.ruleCount }} / 条款
                      {{ row.kbCount }}
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
                <ElTable :data="reviewLineageRows" border>
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
                <ElTable :data="normalizedReviewQualityRows" border>
                  <ElTableColumn prop="name" label="评估项" min-width="150" show-overflow-tooltip />
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
                    prop="message"
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
                <ElTable :data="normalizedReviewHumanCorrectionRows" border>
                  <ElTableColumn
                    prop="correctionType"
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
                    prop="before"
                    label="修正前"
                    min-width="260"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="修正后" min-width="260" show-overflow-tooltip>
                    <template #default="{ row }">{{ shortText(row.after) }}</template>
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
                  AI 员工节点
                  <ElTag class="ml-8px" effect="plain">edges {{ reviewGraphEdges.length }}</ElTag>
                </template>
                <ElTable :data="reviewGraphNodes" border>
                  <ElTableColumn prop="sequence" label="#" width="112" />
                  <ElTableColumn prop="label" label="节点" min-width="180" show-overflow-tooltip />
                  <ElTableColumn
                    prop="nodeKey"
                    label="节点键"
                    min-width="170"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.nodeKey) }}</template>
                  </ElTableColumn>
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
                          .map((item) => friendlyTechLabel(item.toolName))
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
                          溯源 {{ nodeArtifactCount(row, 'retrievalTraces') }}
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
                <template #header>工作流时间线</template>
                <ElTable :data="reviewGraphTimeline" border>
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
                  >
                    <template #default="{ row }">{{ friendlyTechLabel(row.eventType) }}</template>
                  </ElTableColumn>
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
                <ElTable :data="reviewRuleResultRows" border>
                  <ElTableColumn prop="ruleCode" label="规则" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">
                      {{ friendlyReferenceLabel(row.ruleCode) }}
                    </template>
                  </ElTableColumn>
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
                <template #header>
                  检索溯源
                  <span class="panel-title-alias">检索 Trace</span>
                </template>
                <ElTable :data="reviewRetrievalTraceRows" border>
                  <ElTableColumn
                    prop="retrievalTraceId"
                    label="溯源记录"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="selectedRoute"
                    label="路由"
                    min-width="170"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{
                      friendlyTechLabel(row.selectedRoute)
                    }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="selectedClauseCount" label="条款" width="80" />
                  <ElTableColumn prop="pageIndexNodeCount" label="章节溯源" width="105" />
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
                <template #header>
                  审查问题草稿
                  <span class="panel-title-alias">Finding Draft</span>
                </template>
                <ElTable :data="normalizedReviewFindingRows" border>
                  <ElTableColumn prop="id" label="草稿编号" min-width="145" show-overflow-tooltip />
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
                <ElTable :data="feedback" border @row-click="selectFeedback">
                  <ElTableColumn label="类型" width="150">
                    <template #default="{ row }">{{ friendlyStatus(row.feedbackType) }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="归因" width="160">
                    <template #default="{ row }">{{
                      friendlyTechnicalText(row.rootCause)
                    }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="状态" width="120">
                    <template #default="{ row }">{{ friendlyStatus(row.status) }}</template>
                  </ElTableColumn>
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
                <ElTable :data="evaluation?.sets || []" border>
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
                <ElTable :data="bundles?.bundles || []" border @row-click="selectBundle">
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
                <ElTable :data="releases?.plans || []" border @row-click="selectRelease">
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
                <ElTable :data="bundleDiffRows" border>
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
                  <ElDescriptionsItem label="审查任务编号">
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
                    <span>业务类型门禁</span>
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
                  <ElDescriptionsItem label="业务类型数量">{{
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
                  class="mt-12px"
                  @row-click="selectBusinessPack"
                >
                  <ElTableColumn label="业务类型" min-width="190" show-overflow-tooltip>
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
                    :class="{
                      active:
                        (ocrSubpage === item.key &&
                          (item.key === 'capability-test' || !ocrCapabilityDialogVisible)) ||
                        (item.key === 'capability-test' && ocrCapabilityDialogVisible)
                    }"
                    @click="selectOcrSubpage(item.key)"
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
                  <ElCard shadow="never" class="panel chart-panel mb-12px">
                    <template #header>
                      <div class="panel-header">
                        <span>OCR 场景质量热力图</span>
                        <ElTag effect="plain">Heatmap</ElTag>
                      </div>
                    </template>
                    <div class="knowledge-chart-shell knowledge-chart-shell--heatmap">
                      <Echart
                        :options="ocrQualityHeatmapOption"
                        height="300px"
                        class="knowledge-echart"
                      />
                    </div>
                  </ElCard>
                  <ElTable
                    v-if="ocrTopBlockerRows.length"
                    :data="ocrTopBlockerRows"
                    border
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
                  <div v-if="ocr100ActionSummary" class="ocr-action-board mb-12px">
                    <div class="panel-header panel-header--compact">
                      <span>OCR 100 行动板</span>
                      <ElSpace>
                        <ElTag :type="ocr100ActionBoard?.ok ? 'success' : 'warning'" effect="plain">
                          {{ friendlyStatus(ocr100ActionSummary.status, '待推进') }}
                        </ElTag>
                        <ElButton
                          size="small"
                          type="primary"
                          plain
                          :loading="ocr100ActionBoardRefreshing"
                          @click="refreshOcr100ActionBoard"
                        >
                          刷新交付包
                        </ElButton>
                        <ElButton
                          size="small"
                          plain
                          :disabled="!ocr100ActionBoardRows.length"
                          @click="exportOcr100ActionBoardCsv"
                        >
                          导出CSV
                        </ElButton>
                      </ElSpace>
                    </div>
                    <div class="workbench-summary-grid project-subpage-kpis">
                      <div
                        v-for="card in ocr100ActionBoardView.cards"
                        :key="card.label"
                        :class="`workbench-summary-card workbench-summary-card--${card.tone}`"
                      >
                        <span>{{ card.label }}</span>
                        <strong>{{ card.value }}</strong>
                        <small>{{ card.hint }}</small>
                      </div>
                    </div>
                    <div
                      v-if="ocr100Handoff.status || ocr100HandoffVisibleFiles.length"
                      class="ocr-handoff"
                    >
                      <div class="ocr-handoff__head">
                        <div>
                          <strong>人工交付包</strong>
                          <span>{{
                            ocr100Handoff.outputDir || ocr100Handoff.manifestPath || '待生成'
                          }}</span>
                          <small v-if="ocr100HandoffHint">{{ ocr100HandoffHint }}</small>
                        </div>
                        <ElTag :type="ocr100HandoffStatusType" effect="plain">
                          {{ friendlyStatus(ocr100Handoff.status, '待生成') }}
                        </ElTag>
                      </div>
                      <div v-if="ocr100HandoffVisibleFiles.length" class="ocr-handoff__files">
                        <div
                          v-for="file in ocr100HandoffVisibleFiles"
                          :key="file.key || file.path"
                          class="ocr-handoff__file"
                        >
                          <div>
                            <strong>{{ file.label }}</strong>
                            <span>{{ file.owner }} · {{ file.purpose }}</span>
                            <small>{{ file.path }}</small>
                          </div>
                          <div class="ocr-handoff__actions">
                            <ElTag
                              :type="file.exists ? 'success' : 'danger'"
                              effect="plain"
                              size="small"
                            >
                              {{ file.exists ? '已生成' : '缺失' }}
                            </ElTag>
                            <ElButton
                              size="small"
                              text
                              type="primary"
                              :disabled="!file.exists"
                              :loading="ocr100HandoffOpening === file.key"
                              @click="openOcr100HandoffFile(file)"
                            >
                              打开
                            </ElButton>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div v-if="ocr100ActionBoardView.rows.length" class="ocr-action-list">
                      <div
                        v-for="row in ocr100ActionBoardView.rows"
                        :key="String(row.id || row.title)"
                        class="ocr-action-row"
                      >
                        <ElTag size="small" effect="plain">{{ row.laneLabel }}</ElTag>
                        <strong>{{ row.title }}</strong>
                        <span>{{ row.detailText }}</span>
                        <ElButton
                          v-if="row.canOpenAnnotation"
                          size="small"
                          plain
                          :loading="annotationDetailLoading"
                          @click="openOcr100ActionAnnotation(row)"
                        >
                          打开
                        </ElButton>
                      </div>
                    </div>
                  </div>
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
                        · {{ friendlyFieldLabel(topMissingRequiredField.fieldCode) }} ×
                        {{ topMissingRequiredField.count }}
                      </span>
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="topOcrFieldCode" label="首要字段">
                      {{ friendlyFieldLabel(topOcrFieldCode.fieldCode) }} ·
                      {{ topOcrFieldCode.count }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem v-if="topOcrFieldFlag" label="字段质量标记">
                      {{ friendlyIssueLabel(topOcrFieldFlag.flag) }} · {{ topOcrFieldFlag.count }}
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
                      {{ friendlyIssueLabel(topOcrQualityReason.reason) }} ·
                      {{ topOcrQualityReason.count }}
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
                    <ElDescriptionsItem label="运行体检"
                      >{{ ocrRuntimeDoctor?.summary?.fail || 0 }} 失败 /
                      {{ ocrRuntimeDoctor?.summary?.warn || 0 }} 告警</ElDescriptionsItem
                    >
                    <ElDescriptionsItem v-if="firstRuntimeIssue" label="首要问题">
                      {{ friendlyTechnicalText(firstRuntimeIssue.name) }}：{{
                        friendlyTechnicalText(firstRuntimeIssue.message)
                      }}
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
                        <strong
                          class="gate-status-pill"
                          :class="
                            ocr100Scorecard.ok
                              ? 'gate-status-pill--success'
                              : 'gate-status-pill--danger'
                          "
                        >
                          <i aria-hidden="true"></i>
                          <span>{{ ocr100Scorecard.ok ? '100分就绪' : '存在阻断' }}</span>
                          <small>{{
                            ocr100Scorecard.ok
                              ? '可作为交付基线'
                              : `${ocr100Scorecard.blockers.length} 个阻断待处理`
                          }}</small>
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
                        <ElTable :data="ocr100SectionRows" border>
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
                        <ElTable v-if="ocr100BlockerRows.length" :data="ocr100BlockerRows" border>
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
                <ElDialog
                  v-model="ocrCapabilityDialogVisible"
                  title="OCR 能力测试"
                  width="min(1180px, 96vw)"
                  class="ocr-capability-dialog"
                  destroy-on-close
                >
                  <section class="ocr-capability-shell">
                    <div class="ocr-capability-hero">
                      <div>
                        <span>基础能力测试</span>
                        <strong>上传一份临时资料，验证 OCR 是否真的能识别。</strong>
                        <small>
                          测试文件只用于 FDE 诊断，不进入正式项目资料，不改变审查结论。
                        </small>
                      </div>
                      <ElSpace>
                        <ElButton
                          plain
                          :loading="ocrCapabilityRecordsLoading"
                          @click="loadOcrCapabilityTestRuns"
                        >
                          刷新记录
                        </ElButton>
                        <ElButton
                          type="primary"
                          :loading="ocrCapabilityTestLoading"
                          @click="startOcrCapabilityTest"
                        >
                          {{ ocrCapabilityTestLoading ? '处理中' : '开始测试' }}
                        </ElButton>
                      </ElSpace>
                    </div>
                    <ElAlert
                      v-if="ocrCapabilityProgressHint"
                      type="info"
                      show-icon
                      :closable="false"
                      :title="ocrCapabilityProgressHint"
                    />
                    <div class="ocr-capability-layout">
                      <section class="ocr-capability-card ocr-capability-card--setup">
                        <div class="ocr-capability-card__head">
                          <strong>1. 选择测试文件</strong>
                          <ElTag effect="plain">PDF / 图片</ElTag>
                        </div>
                        <input
                          ref="ocrCapabilityFileInputRef"
                          class="sr-only-input"
                          type="file"
                          accept="application/pdf,image/*,.pdf,.png,.jpg,.jpeg"
                          @change="handleOcrCapabilityTestFileChange"
                        />
                        <button
                          type="button"
                          class="ocr-capability-upload"
                          @click="chooseOcrCapabilityTestFile"
                        >
                          <strong>{{
                            ocrCapabilityTestFile?.name || '点击选择 PDF 或图片'
                          }}</strong>
                          <span v-if="ocrCapabilityTestFile">
                            {{ Math.ceil((ocrCapabilityTestFile.size || 0) / 1024) }} KB
                          </span>
                          <span v-else>建议用真实扫描件、表格照片或盖章资料做测试。</span>
                        </button>
                        <div class="ocr-capability-form">
                          <label>
                            <span>解析配置</span>
                            <ElSelect v-model="ocrCapabilityTestForm.profileId" size="small">
                              <ElOption label="自动判断" value="auto" />
                              <ElOption
                                label="管道特性表 / 工程表格"
                                value="piping_characteristic_list_v1"
                              />
                              <ElOption label="质量证明书" value="quality_certificate_v1" />
                              <ElOption label="NDT RT 报告" value="ndt_rt_report_v1" />
                              <ElOption label="通用资料" value="all" />
                            </ElSelect>
                          </label>
                          <label>
                            <span>资料类型</span>
                            <ElSelect v-model="ocrCapabilityTestForm.documentType" size="small">
                              <ElOption label="自动判断" value="auto" />
                              <ElOption label="工程表格照片" value="engineering_table_photo" />
                              <ElOption label="质量证明文件" value="quality_certificate" />
                              <ElOption label="NDT 检测报告" value="ndt_report" />
                              <ElOption label="通用工程资料" value="engineering_document" />
                            </ElSelect>
                          </label>
                          <label>
                            <span>快速页数</span>
                            <ElInputNumber
                              v-model="ocrCapabilityTestForm.maxPages"
                              size="small"
                              :min="1"
                              :max="10"
                              controls-position="right"
                            />
                          </label>
                        </div>
                        <div class="ocr-capability-switches">
                          <label>
                            <input v-model="ocrCapabilityTestForm.enableTables" type="checkbox" />
                            表格识别
                          </label>
                          <label>
                            <input v-model="ocrCapabilityTestForm.enableSeals" type="checkbox" />
                            印章识别（稍慢）
                          </label>
                          <label>
                            <input v-model="ocrCapabilityTestForm.enableFallback" type="checkbox" />
                            复杂页兜底
                          </label>
                        </div>
                      </section>
                      <section
                        :class="[
                          'ocr-capability-card',
                          'ocr-capability-card--recent',
                          { 'ocr-capability-card--collapsed': !ocrCapabilityRecentOpen }
                        ]"
                        v-loading="ocrCapabilityRecordsLoading"
                      >
                        <div class="ocr-capability-card__head">
                          <strong>2. 最近测试</strong>
                          <ElSpace>
                            <ElTag effect="plain">{{ ocrCapabilityTestRuns.length }} 条</ElTag>
                            <ElButton
                              size="small"
                              plain
                              @click="ocrCapabilityRecentOpen = !ocrCapabilityRecentOpen"
                            >
                              {{ ocrCapabilityRecentOpen ? '收起' : '展开' }}
                            </ElButton>
                          </ElSpace>
                        </div>
                        <ElTable
                          v-if="ocrCapabilityRecentOpen"
                          :data="ocrCapabilityTestRuns"
                          class="ocr-capability-table"
                          @row-click="
                            (row) => loadOcrCapabilityTestDetail(String(row.runId || row.id))
                          "
                        >
                          <ElTableColumn
                            prop="fileName"
                            label="文件"
                            min-width="180"
                            show-overflow-tooltip
                          />
                          <ElTableColumn prop="status" label="状态" width="115">
                            <template #default="{ row }">
                              <ElTag :type="ocrCapabilityStatusType(row.status)" effect="plain">
                                {{ friendlyStatus(row.status) }}
                              </ElTag>
                            </template>
                          </ElTableColumn>
                          <ElTableColumn label="结果" width="105">
                            <template #default="{ row }">
                              {{
                                Number(row.resultSummary?.fields || 0) +
                                Number(row.resultSummary?.tables || 0) +
                                Number(row.resultSummary?.seals || 0)
                              }}
                            </template>
                          </ElTableColumn>
                        </ElTable>
                      </section>
                    </div>
                    <section class="ocr-capability-result">
                      <div class="ocr-capability-preview" v-loading="ocrCapabilityResultLoading">
                        <div class="ocr-capability-card__head">
                          <strong>3. 文件预览</strong>
                          <ElTag v-if="selectedOcrCapabilityRun" effect="plain">
                            {{ friendlyStatus(selectedOcrCapabilityRun.status) }}
                          </ElTag>
                          <ElTag
                            v-if="selectedOcrCapabilityRois.length"
                            type="success"
                            effect="plain"
                          >
                            ROI {{ selectedOcrCapabilityRois.length }}
                          </ElTag>
                        </div>
                        <div
                          v-if="ocrCapabilityRoiLegend.length"
                          class="ocr-roi-legend"
                          aria-label="ROI 类型图例"
                        >
                          <span
                            v-for="item in ocrCapabilityRoiLegend"
                            :key="item.type"
                            :class="['ocr-roi-legend__item', `ocr-roi-legend__item--${item.tone}`]"
                          >
                            <i aria-hidden="true"></i>
                            <strong>{{ item.label }}</strong>
                            <small>{{ item.count }}</small>
                          </span>
                        </div>
                        <div
                          v-if="selectedOcrCapabilityPreviewSource?.url"
                          class="ocr-preview-stage"
                        >
                          <div
                            v-if="selectedOcrCapabilityPreviewSource.previewType === 'image'"
                            class="ocr-preview-image-frame"
                          >
                            <img
                              :src="selectedOcrCapabilityPreviewSource.url"
                              alt="OCR 测试文件预览"
                            />
                            <div
                              v-if="selectedOcrCapabilityImageRois.length"
                              class="ocr-roi-layer"
                              aria-label="OCR ROI 标注"
                            >
                              <button
                                v-for="roi in selectedOcrCapabilityImageRois"
                                :key="roi.id"
                                type="button"
                                :class="['ocr-roi-box', `ocr-roi-box--${roi.tone}`]"
                                :style="ocrCapabilityRoiStyle(roi)"
                                :title="`${roi.type} · ${roi.label}${roi.text ? ` · ${roi.text}` : ''}`"
                                :aria-label="`${roi.type} 标注：${roi.label}${roi.text ? `，${roi.text}` : ''}`"
                              >
                                <span>{{ roi.text || roi.label || roi.type }}</span>
                              </button>
                            </div>
                          </div>
                          <div
                            v-else-if="
                              selectedOcrCapabilityPreviewSource.previewType === 'pdf' &&
                              selectedOcrCapabilityPdfPagePreviewUrl
                            "
                            class="ocr-preview-image-frame ocr-preview-pdf-page-frame"
                          >
                            <img
                              :src="selectedOcrCapabilityPdfPagePreviewUrl"
                              alt="OCR 测试 PDF 页预览"
                            />
                            <div
                              v-if="selectedOcrCapabilityPdfRois.length"
                              class="ocr-roi-layer"
                              aria-label="OCR PDF ROI 标注"
                            >
                              <button
                                v-for="roi in selectedOcrCapabilityPdfRois"
                                :key="roi.id"
                                type="button"
                                :class="['ocr-roi-box', `ocr-roi-box--${roi.tone}`]"
                                :style="ocrCapabilityRoiStyle(roi)"
                                :title="`${roi.type} · ${roi.label}${roi.text ? ` · ${roi.text}` : ''}`"
                                :aria-label="`${roi.type} 标注：${roi.label}${roi.text ? `，${roi.text}` : ''}`"
                              >
                                <span>{{ roi.text || roi.label || roi.type }}</span>
                              </button>
                            </div>
                          </div>
                          <div
                            v-else-if="selectedOcrCapabilityPreviewSource.previewType === 'pdf'"
                            class="ocr-preview-pdf-fallback"
                            v-loading="ocrCapabilityPdfPagePreviewLoading"
                          >
                            <ElEmpty
                              :description="
                                ocrCapabilityPdfPagePreviewError ||
                                (ocrCapabilityPdfPagePreviewLoading
                                  ? '正在生成 PDF 页面图预览...'
                                  : 'PDF 页面图预览暂未生成，可先查看 OCR 结果。')
                              "
                            />
                          </div>
                          <ElEmpty
                            v-else
                            description="该文件类型暂不支持页面内预览，可查看 OCR 结果。"
                          />
                        </div>
                        <ElEmpty v-else description="选择测试记录后显示文件预览。" />
                      </div>
                      <div class="ocr-capability-summary" v-loading="ocrCapabilityResultLoading">
                        <div class="ocr-capability-card__head">
                          <strong>4. 识别结果</strong>
                          <ElSpace>
                            <ElButton
                              size="small"
                              plain
                              :disabled="!selectedOcrCapabilityCanPersist"
                              :loading="actionLoading"
                              @click="convertOcrCapabilityTestToAnnotation"
                            >
                              转入OCR标注
                            </ElButton>
                            <ElButton
                              size="small"
                              plain
                              :disabled="!selectedOcrCapabilityCanPersist"
                              :loading="actionLoading"
                              @click="convertOcrCapabilityTestToEvaluationCase"
                            >
                              生成评估样本草稿
                            </ElButton>
                          </ElSpace>
                        </div>
                        <div class="ocr-capability-kpis">
                          <div>
                            <span>页数</span>
                            <strong>{{ selectedOcrCapabilitySummary.pages }}</strong>
                          </div>
                          <div>
                            <span>字段</span>
                            <strong>{{ selectedOcrCapabilitySummary.fields }}</strong>
                          </div>
                          <div>
                            <span>表格</span>
                            <strong>{{ selectedOcrCapabilitySummary.tables }}</strong>
                          </div>
                          <div>
                            <span>印章</span>
                            <strong>{{ selectedOcrCapabilitySummary.seals }}</strong>
                          </div>
                          <div>
                            <span>质量状态</span>
                            <strong>{{
                              friendlyStatus(selectedOcrCapabilitySummary.qualityStatus)
                            }}</strong>
                          </div>
                          <div>
                            <span>诊断</span>
                            <strong>{{ selectedOcrCapabilitySummary.diagnostics }}</strong>
                          </div>
                        </div>
                        <ElAlert
                          v-if="selectedOcrCapabilityTerminalNoOutput"
                          class="mt-12px"
                          type="warning"
                          show-icon
                          :closable="false"
                          title="本次测试还没有返回可展示的识别内容，请稍后刷新记录或检查 OCR 服务状态。"
                        />
                        <ElTabs class="ocr-capability-output-tabs">
                          <ElTabPane label="全文">
                            <pre
                              v-if="selectedOcrCapabilityText"
                              class="ocr-capability-text-output"
                              >{{ selectedOcrCapabilityText }}</pre
                            >
                            <ElEmpty v-else description="开始测试后，这里显示 OCR 识别文本。" />
                          </ElTabPane>
                          <ElTabPane
                            :label="`结构化 ${selectedOcrCapabilityStructuredRows.length || ''}`"
                          >
                            <ElTable
                              v-if="selectedOcrCapabilityStructuredRows.length"
                              :data="selectedOcrCapabilityStructuredRows"
                            >
                              <ElTableColumn prop="pageNo" label="页" width="62" />
                              <ElTableColumn prop="type" label="类型" width="82" />
                              <ElTableColumn
                                prop="name"
                                label="名称"
                                min-width="130"
                                show-overflow-tooltip
                              />
                              <ElTableColumn
                                prop="value"
                                label="内容 / 值"
                                min-width="220"
                                show-overflow-tooltip
                              />
                              <ElTableColumn
                                prop="bboxText"
                                label="bbox"
                                min-width="150"
                                show-overflow-tooltip
                              />
                              <ElTableColumn label="置信度" width="96">
                                <template #default="{ row }">
                                  {{
                                    row.confidence === undefined
                                      ? '-'
                                      : scorePercent(row.confidence)
                                  }}
                                </template>
                              </ElTableColumn>
                              <ElTableColumn
                                prop="source"
                                label="来源"
                                min-width="150"
                                show-overflow-tooltip
                              />
                            </ElTable>
                            <ElEmpty v-else description="暂无可结构化的识别内容。" />
                          </ElTabPane>
                          <ElTabPane :label="`ROI ${selectedOcrCapabilityRois.length || ''}`">
                            <ElTable
                              v-if="selectedOcrCapabilityRois.length"
                              :data="selectedOcrCapabilityRois"
                            >
                              <ElTableColumn label="类型" width="96">
                                <template #default="{ row }">
                                  <ElTag :type="ocrCapabilityRoiTagType(row.tone)" effect="plain">
                                    {{ row.type }}
                                  </ElTag>
                                </template>
                              </ElTableColumn>
                              <ElTableColumn
                                prop="label"
                                label="对象"
                                min-width="130"
                                show-overflow-tooltip
                              />
                              <ElTableColumn
                                prop="text"
                                label="文本"
                                min-width="180"
                                show-overflow-tooltip
                              />
                              <ElTableColumn label="bbox" min-width="160" show-overflow-tooltip>
                                <template #default="{ row }">{{ row.bbox.join(', ') }}</template>
                              </ElTableColumn>
                              <ElTableColumn label="置信度" width="96">
                                <template #default="{ row }">
                                  {{
                                    row.confidence === undefined
                                      ? '-'
                                      : scorePercent(row.confidence)
                                  }}
                                </template>
                              </ElTableColumn>
                            </ElTable>
                            <ElEmpty v-else description="OCR 结果暂无可标注 ROI。" />
                          </ElTabPane>
                          <ElTabPane label="字段">
                            <ElTable
                              v-if="selectedOcrCapabilityFields.length"
                              :data="selectedOcrCapabilityFields"
                            >
                              <ElTableColumn
                                prop="fieldCode"
                                label="字段"
                                min-width="150"
                                show-overflow-tooltip
                              >
                                <template #default="{ row }">{{
                                  friendlyFieldLabel(row.fieldCode || row.fieldName)
                                }}</template>
                              </ElTableColumn>
                              <ElTableColumn
                                prop="fieldValue"
                                label="识别值"
                                min-width="180"
                                show-overflow-tooltip
                              />
                              <ElTableColumn prop="confidence" label="置信度" width="95" />
                            </ElTable>
                            <ElEmpty v-else description="暂无结构化字段输出。" />
                          </ElTabPane>
                          <ElTabPane label="表格">
                            <div
                              v-if="selectedOcrCapabilityTablePreviews.length"
                              class="ocr-table-result-list"
                            >
                              <article
                                v-for="table in selectedOcrCapabilityTablePreviews"
                                :key="table.id"
                                class="ocr-table-result-card"
                              >
                                <div class="ocr-table-result-card__head">
                                  <strong>{{ table.title }}</strong>
                                  <dl class="ocr-table-meta">
                                    <div v-for="item in table.meta" :key="item.label">
                                      <dt>{{ item.label }}</dt>
                                      <dd>{{ item.value }}</dd>
                                    </div>
                                  </dl>
                                </div>
                                <table class="ocr-structured-table">
                                  <thead>
                                    <tr>
                                      <th v-for="column in table.columns" :key="column.key">
                                        {{ column.label }}
                                      </th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    <tr v-for="row in table.rows" :key="row.id">
                                      <td v-for="column in table.columns" :key="column.key">
                                        {{ row.cells[column.key] || '-' }}
                                      </td>
                                    </tr>
                                  </tbody>
                                </table>
                              </article>
                            </div>
                            <ElEmpty v-else description="暂无表格输出。" />
                          </ElTabPane>
                          <ElTabPane label="印章">
                            <div
                              v-if="selectedOcrCapabilitySealRows.length"
                              class="ocr-seal-result-list"
                            >
                              <article
                                v-for="seal in selectedOcrCapabilitySealRows"
                                :key="seal.id"
                                class="ocr-seal-result-card"
                              >
                                <div class="ocr-seal-result-card__head">
                                  <div>
                                    <span>{{ seal.colorLabel }} · {{ seal.typeLabel }}</span>
                                    <strong>{{ seal.title }}</strong>
                                  </div>
                                  <ElTag :type="seal.tagType" effect="plain">{{
                                    seal.status
                                  }}</ElTag>
                                </div>
                                <dl class="ocr-seal-meta">
                                  <div v-for="item in seal.meta" :key="item.label">
                                    <dt>{{ item.label }}</dt>
                                    <dd>{{ item.value }}</dd>
                                  </div>
                                </dl>
                                <div class="ocr-seal-content">
                                  <span>格式化内容</span>
                                  <template v-if="seal.contentLines.length">
                                    <p v-for="line in seal.contentLines" :key="line">{{ line }}</p>
                                  </template>
                                  <small v-else
                                    >已定位印章框，但当前 OCR 未读出可格式化文字。</small
                                  >
                                </div>
                              </article>
                            </div>
                            <ElEmpty v-else description="暂无印章输出。" />
                          </ElTabPane>
                          <ElTabPane label="诊断">
                            <ElTable
                              v-if="selectedOcrCapabilityDiagnostics.length"
                              :data="selectedOcrCapabilityDiagnostics"
                            >
                              <ElTableColumn
                                prop="code"
                                label="问题"
                                min-width="180"
                                show-overflow-tooltip
                              >
                                <template #default="{ row }">{{
                                  friendlyIssueLabel(row.code || row)
                                }}</template>
                              </ElTableColumn>
                              <ElTableColumn
                                prop="message"
                                label="说明"
                                min-width="260"
                                show-overflow-tooltip
                              />
                            </ElTable>
                            <ElEmpty v-else description="暂无诊断输出。" />
                          </ElTabPane>
                        </ElTabs>
                      </div>
                    </section>
                  </section>
                </ElDialog>
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
                      <ElTable :data="ocrAnnotationRows" border>
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
                        >
                          <template #default="{ row }">{{
                            friendlyTechLabel(row.scenario)
                          }}</template>
                        </ElTableColumn>
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
                    class="mt-12px"
                    @row-click="(row) => openOcrAuditDrawer(String(row.id || row.jobId))"
                  >
                    <ElTableColumn
                      prop="id"
                      label="任务编号"
                      min-width="150"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="status" label="状态" width="95">
                      <template #default="{ row }">
                        <ElTag :type="statusType(String(row.status))" effect="plain">
                          {{ friendlyStatus(row.status) }}
                        </ElTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="profileId"
                      label="解析配置"
                      min-width="140"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                    </ElTableColumn>
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
                      {{ friendlyTechList(selectedOcrMissingVariants) }}
                    </ElDescriptionsItem>
                  </ElDescriptions>
                  <ElTable
                    v-if="selectedOcrEngineRows.length"
                    :data="selectedOcrEngineRows"
                    border
                    class="mt-12px"
                  >
                    <ElTableColumn prop="engine" label="引擎" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">{{ friendlyTechLabel(row.engine) }}</template>
                    </ElTableColumn>
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
                    class="mt-12px"
                  >
                    <ElTableColumn
                      prop="code"
                      label="字段问题"
                      min-width="150"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">{{ friendlyTechLabel(row.code) }}</template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="fieldName"
                      label="字段"
                      min-width="110"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">{{
                        friendlyFieldLabel(row.fieldName)
                      }}</template>
                    </ElTableColumn>
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
                      label="解析配置"
                      min-width="140"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                    </ElTableColumn>
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
                  class="mt-12px"
                  @row-click="selectIncident"
                >
                  <ElTableColumn prop="id" label="事故" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn prop="status" label="状态" width="110" />
                </ElTable>
                <ElTable v-else :data="acceptanceReports" border class="mt-12px">
                  <ElTableColumn prop="id" label="验收报告" min-width="190" show-overflow-tooltip />
                  <ElTableColumn
                    prop="businessPackId"
                    label="业务类型"
                    min-width="180"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{
                      friendlyTechLabel(row.businessPackId)
                    }}</template>
                  </ElTableColumn>
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
                      <span>解析配置</span>
                      <strong>{{ friendlyTechLabel(latestOcrEvalRun.profileId || 'all') }}</strong>
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
                      <ElTable :data="ocrScenarioRows" border>
                        <ElTableColumn
                          prop="scenario"
                          label="场景"
                          min-width="190"
                          show-overflow-tooltip
                        >
                          <template #default="{ row }">{{
                            friendlyTechLabel(row.scenario)
                          }}</template>
                        </ElTableColumn>
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
                        >
                          <template #default="{ row }">{{ friendlyIssueLabel(row.code) }}</template>
                        </ElTableColumn>
                        <ElTableColumn prop="count" label="次数" width="90" />
                      </ElTable>
                      <ElTable v-else :data="failedOcrCaseRows" border>
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
                        >
                          <template #default="{ row }">{{
                            friendlyTechLabel(row.scenario)
                          }}</template>
                        </ElTableColumn>
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
                <ElTable :data="maskingPolicies" border class="mt-12px">
                  <ElTableColumn
                    prop="fieldPath"
                    label="字段"
                    min-width="190"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="strategy" label="策略" width="90" />
                  <ElTableColumn prop="status" label="状态" width="100" />
                </ElTable>
                <ElTable :data="auditEvents" border class="mt-12px">
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
                <ElTable :data="costChangeRequests" border class="mt-12px">
                  <ElTableColumn prop="id" label="申请" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="130">
                    <template #default="{ row }">{{ friendlyStatus(row.status) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="proposedLimit" label="建议额度" width="110" />
                  <ElTableColumn label="原因" min-width="210" show-overflow-tooltip>
                    <template #default="{ row }">{{ friendlyTechnicalText(row.reason) }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>
      </ElTabs>

      <ElDrawer
        v-model="vectorFileQualityDrawerVisible"
        size="92vw"
        class="fde-audit-drawer"
        destroy-on-close
        title="文件向量质量详情"
      >
        <template v-if="selectedVectorFileQuality">
          <div class="audit-drawer-hero" data-testid="fde-vector-file-drawer">
            <div>
              <span>Document Vector</span>
              <strong>{{ selectedVectorFileQualityRecord.fileName || '-' }}</strong>
              <small>
                {{ selectedVectorFileQualityRecord.requirementName || '资料要求未返回' }} ·
                {{ selectedVectorFileQualityRecord.documentVersionId || '-' }}
              </small>
            </div>
            <ElTag
              :type="
                score100(selectedVectorFileQualityRecord.score, 0) >= 90 ? 'success' : 'warning'
              "
              effect="plain"
            >
              {{ score100(selectedVectorFileQualityRecord.score, 0) }}/100
            </ElTag>
          </div>

          <ElAlert
            class="mb-12px"
            type="info"
            show-icon
            :closable="false"
            title="这里展示单文件从图片/文件、OCR、文本、切片、向量格式化、索引到大模型检索引用的证据链；项目级代理溯源会被明确标记。"
          />
          <ElAlert
            v-if="vectorFileDetailError"
            class="mb-12px"
            type="error"
            show-icon
            :closable="false"
            :title="vectorFileDetailError"
          >
            <template #default>
              <ElButton
                size="small"
                type="primary"
                :loading="vectorFileDetailLoading"
                @click="retryVectorFileDetail"
              >
                重试加载
              </ElButton>
            </template>
          </ElAlert>
          <ElAlert
            v-if="
              selectedVectorFileDetailRecord.llmUsage &&
              toRecord(selectedVectorFileDetailRecord.llmUsage).proxyTrace
            "
            class="mb-12px"
            type="warning"
            show-icon
            :closable="false"
            :title="
              String(
                toRecord(selectedVectorFileDetailRecord.llmUsage).proxyReason ||
                  '当前使用项目级代理溯源，不能等同于文件级真实引用。'
              )
            "
          />

          <div class="artifact-summary-grid mb-12px">
            <div
              v-for="item in selectedVectorFileSummaryCards"
              :key="item.label"
              class="artifact-summary-item"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small>{{ item.hint }}</small>
            </div>
          </div>

          <ElDescriptions :column="1" border class="mb-12px">
            <ElDescriptionsItem label="向量模型">
              {{
                friendlyTechLabel(
                  selectedVectorFileQualityRecord.embeddingModel || 'embedding-default'
                )
              }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="索引版本">
              {{ selectedVectorFileQualityRecord.indexVersion || 'knowledge-index@local' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="向量维度">
              {{ selectedVectorFileQualityRecord.vectorDimensions || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="知识文件编号">
              {{ selectedVectorFileQualityRecord.knowledgeFileId || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="最新任务">
              {{ friendlyStatus(selectedVectorFileQualityRecord.latestTaskStatus, '-') }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="当前问题">
              <span v-if="selectedVectorFileBlockers.length">
                {{ selectedVectorFileBlockers.join('；') }}
              </span>
              <span v-else>无</span>
            </ElDescriptionsItem>
          </ElDescriptions>

          <ElTabs v-loading="vectorFileDetailLoading" class="audit-drawer-tabs">
            <ElTabPane label="加工链路" name="pipeline">
              <div class="vector-pipeline-strip mb-12px">
                <div
                  v-for="stage in selectedVectorFilePipelineSummary"
                  :key="stage.id"
                  class="vector-pipeline-stage"
                >
                  <span>{{ stage.label }}</span>
                  <strong>{{ stage.status }}</strong>
                  <small>{{ stage.metric }}</small>
                </div>
              </div>

              <div class="vector-evidence-workbench">
                <ElCard shadow="never" class="vector-source-preview-card">
                  <template #header>
                    <div class="vector-card-header">
                      <strong>图片/文件源</strong>
                      <ElTag effect="plain">
                        第 {{ selectedVectorActivePage?.pageNo || 1 }} 页
                      </ElTag>
                    </div>
                  </template>
                  <div class="vector-source-canvas">
                    <img
                      v-if="selectedVectorPreviewCanRender && selectedVectorPreviewIsImage"
                      class="vector-source-media"
                      :src="selectedVectorPreviewUrl"
                      :alt="
                        String(
                          selectedVectorFilePipelineSource.fileName ||
                            selectedVectorFileQualityRecord.fileName ||
                            '文件预览'
                        )
                      "
                    />
                    <iframe
                      v-else-if="selectedVectorPreviewCanRender"
                      class="vector-source-media"
                      :src="selectedVectorPreviewUrl"
                      title="文件预览"
                    ></iframe>
                    <div v-else class="vector-source-placeholder">
                      <strong>{{
                        selectedVectorFilePipelineSource.fileName ||
                        selectedVectorFileQualityRecord.fileName ||
                        '-'
                      }}</strong>
                      <span>{{
                        selectedVectorFilePipelineSource.previewUnavailableReason ||
                        '未生成可渲染预览，仍可查看 OCR、文本和向量证据。'
                      }}</span>
                      <small>{{
                        selectedVectorFilePipelineSource.storageKey ||
                        selectedVectorFilePipelineSource.previewUrl ||
                        '-'
                      }}</small>
                    </div>
                    <div
                      v-if="selectedVectorEvidenceBbox"
                      class="vector-evidence-box"
                      :style="selectedVectorEvidenceStyle"
                    >
                      <span>{{ selectedVectorEvidenceType }}</span>
                    </div>
                  </div>
                  <ElDescriptions :column="1" border class="mt-12px">
                    <ElDescriptionsItem label="Storage Key">
                      {{ selectedVectorFilePipelineSource.storageKey || '-' }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="Preview">
                      {{ selectedVectorFilePipelineSource.previewUrl || '-' }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="当前证据">
                      {{
                        selectedVectorEvidenceRecord.evidenceLabel ||
                        selectedVectorEvidenceRecord.fieldName ||
                        selectedVectorEvidenceRecord.sourceLabel ||
                        '点击右侧行查看证据定位'
                      }}
                    </ElDescriptionsItem>
                  </ElDescriptions>
                </ElCard>

                <div class="vector-evidence-panels">
                  <ElCard shadow="never" class="vector-pipeline-card">
                    <template #header>
                      <div class="vector-card-header">
                        <strong>OCR 结构化结果</strong>
                        <span>
                          字段 {{ selectedVectorFilePipelineOcrSummary.fieldCount || 0 }} · 片段
                          {{ selectedVectorFilePipelineOcrSummary.fragmentCount || 0 }} · 表格
                          {{ selectedVectorFilePipelineOcrSummary.tableCount || 0 }} · 印章
                          {{ selectedVectorFilePipelineOcrSummary.sealCount || 0 }}
                        </span>
                      </div>
                    </template>
                    <ElTable
                      :data="selectedVectorFilePipelineFieldRows"
                      border
                      highlight-current-row
                      @row-click="(row) => selectVectorEvidence(row, 'OCR')"
                    >
                      <ElTableColumn
                        prop="fieldName"
                        label="字段"
                        min-width="120"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="fieldValue"
                        label="OCR值"
                        min-width="180"
                        show-overflow-tooltip
                      />
                      <ElTableColumn prop="pageNo" label="页" width="64" />
                      <ElTableColumn prop="confidence" label="置信" width="82" />
                      <ElTableColumn label="bbox" width="72">
                        <template #default="{ row }">
                          <ElTag :type="row.hasBbox ? 'success' : 'warning'" effect="plain">
                            {{ row.hasBbox ? '有' : '缺' }}
                          </ElTag>
                        </template>
                      </ElTableColumn>
                    </ElTable>
                  </ElCard>

                  <ElCard shadow="never" class="vector-pipeline-card">
                    <template #header>
                      <div class="vector-card-header">
                        <strong>文本与切片</strong>
                        <span>{{ selectedVectorFilePipelineTextRows.length }} 条文本记录</span>
                      </div>
                    </template>
                    <ElTable
                      :data="selectedVectorFilePipelineTextRows"
                      border
                      highlight-current-row
                      @row-click="(row) => selectVectorEvidence(row, 'Text')"
                    >
                      <ElTableColumn
                        prop="sourceLabel"
                        label="来源"
                        width="140"
                        show-overflow-tooltip
                      />
                      <ElTableColumn prop="pageNo" label="页" width="64" />
                      <ElTableColumn
                        prop="text"
                        label="文本"
                        min-width="260"
                        show-overflow-tooltip
                      />
                      <ElTableColumn label="bbox" width="72">
                        <template #default="{ row }">
                          <ElTag :type="row.hasBbox ? 'success' : 'warning'" effect="plain">
                            {{ row.hasBbox ? '有' : '缺' }}
                          </ElTag>
                        </template>
                      </ElTableColumn>
                    </ElTable>
                  </ElCard>

                  <ElCard shadow="never" class="vector-pipeline-card">
                    <template #header>
                      <div class="vector-card-header">
                        <strong>向量格式化数据 / 索引</strong>
                        <span>不展示真实高维向量，仅展示 payload hash 与索引记录</span>
                      </div>
                    </template>
                    <ElTable
                      :data="selectedVectorFilePipelineVectorRows"
                      border
                      highlight-current-row
                      @row-click="(row) => selectVectorEvidence(row, 'Vector')"
                    >
                      <ElTableColumn prop="chunkNo" label="#" width="64" />
                      <ElTableColumn
                        prop="model"
                        label="模型"
                        min-width="130"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="indexVersion"
                        label="索引"
                        min-width="140"
                        show-overflow-tooltip
                      />
                      <ElTableColumn prop="dimensions" label="维度" width="82" />
                      <ElTableColumn
                        prop="vectorId"
                        label="向量编号"
                        min-width="150"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="payloadHash"
                        label="载荷校验哈希"
                        min-width="170"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="textPreview"
                        label="输入文本"
                        min-width="240"
                        show-overflow-tooltip
                      />
                    </ElTable>
                  </ElCard>
                </div>

                <ElCard shadow="never" class="vector-evidence-detail-card">
                  <template #header>当前选中证据</template>
                  <ElEmpty
                    v-if="!Object.keys(selectedVectorEvidenceRecord).length"
                    description="点击 OCR、文本、切片或向量行查看细节"
                  />
                  <template v-else>
                    <ElDescriptions :column="1" border>
                      <ElDescriptionsItem label="类型">{{
                        selectedVectorEvidenceType
                      }}</ElDescriptionsItem>
                      <ElDescriptionsItem label="页码">{{
                        selectedVectorEvidenceRecord.pageNo || '-'
                      }}</ElDescriptionsItem>
                      <ElDescriptionsItem label="bbox">{{
                        selectedVectorEvidenceRecord.bbox
                          ? JSON.stringify(selectedVectorEvidenceRecord.bbox)
                          : '缺'
                      }}</ElDescriptionsItem>
                      <ElDescriptionsItem label="摘要">
                        {{
                          selectedVectorEvidenceRecord.fieldValue ||
                          selectedVectorEvidenceRecord.text ||
                          selectedVectorEvidenceRecord.textPreview ||
                          '-'
                        }}
                      </ElDescriptionsItem>
                    </ElDescriptions>
                    <pre class="vector-evidence-json">{{ selectedVectorEvidenceJson }}</pre>
                  </template>
                </ElCard>
              </div>
            </ElTabPane>
            <ElTabPane label="质量维度" name="dimensions">
              <ElTable :data="selectedVectorFileQualityDimensions" border>
                <ElTableColumn prop="name" label="维度" min-width="150" show-overflow-tooltip />
                <ElTableColumn label="评分" width="82">
                  <template #default="{ row }">{{ row.score }}</template>
                </ElTableColumn>
                <ElTableColumn prop="metric" label="指标" width="96" />
                <ElTableColumn prop="status" label="状态" width="96">
                  <template #default="{ row }">
                    <ElTag :type="row.status === 'pass' ? 'success' : 'warning'" effect="plain">
                      {{ row.statusLabel }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="message" label="说明" min-width="260" show-overflow-tooltip />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="切片明细" name="chunks">
              <div class="artifact-summary-grid mb-12px">
                <div
                  v-for="item in selectedVectorFileChunkCards"
                  :key="item.label"
                  class="artifact-summary-item"
                >
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                  <small>{{ item.hint }}</small>
                </div>
              </div>
              <ElAlert
                v-if="selectedVectorFileBlockers.length"
                class="mb-12px"
                type="warning"
                show-icon
                :closable="false"
                :title="selectedVectorFileBlockers.slice(0, 3).join('；')"
              />
              <ElTable
                :data="selectedVectorFileChunkRows"
                border
                highlight-current-row
                @row-click="(row) => selectVectorEvidence(row, 'Chunk')"
              >
                <ElTableColumn prop="chunkNo" label="#" width="70" />
                <ElTableColumn label="状态" width="98">
                  <template #default="{ row }">
                    <ElTag :type="row.materialized ? 'success' : 'warning'" effect="plain">
                      {{ row.materialized ? '真实' : '缺明细' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="pageNo" label="页码" width="82" />
                <ElTableColumn label="bbox" width="82">
                  <template #default="{ row }">
                    <ElTag :type="row.hasBbox ? 'success' : 'warning'" effect="plain">
                      {{ row.hasBbox ? '有' : '缺' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="tokenCount" label="Token 用量" width="100" />
                <ElTableColumn prop="vectorStatus" label="向量" width="116" />
                <ElTableColumn prop="retrievalHitCount" label="溯源" width="82" />
                <ElTableColumn prop="metadataCompleteness" label="元数据" width="112" />
                <ElTableColumn
                  prop="textPreview"
                  label="切片预览"
                  min-width="280"
                  show-overflow-tooltip
                />
                <ElTableColumn label="标记" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">
                    <ElSpace wrap size="small">
                      <ElTag
                        v-for="flag in row.qualityFlags.slice(0, 3)"
                        :key="flag"
                        type="warning"
                        effect="plain"
                      >
                        {{ flag }}
                      </ElTag>
                      <span v-if="!row.qualityFlags.length">-</span>
                    </ElSpace>
                  </template>
                </ElTableColumn>
              </ElTable>
              <ElPagination
                class="vector-file-pagination"
                small
                background
                layout="total"
                :total="
                  Number(
                    toRecord(selectedVectorFileDetailRecord.chunkPage).total ||
                      selectedVectorFileChunkRows.length
                  )
                "
              />
            </ElTabPane>
            <ElTabPane label="质量问题" name="qualityIssues">
              <ElEmpty
                v-if="!selectedVectorQualityIssues.length"
                description="当前文件没有结构化质量问题"
              />
              <div v-else class="vector-file-blocker-list">
                <ElAlert
                  v-for="issue in selectedVectorQualityIssues"
                  :key="String(issue.code || issue.message)"
                  :type="issue.severity === 'blocker' ? 'error' : 'warning'"
                  show-icon
                  :closable="false"
                  :title="String(issue.message || issue.code || '-')"
                />
              </div>
            </ElTabPane>
            <ElTabPane label="切片图表" name="chunkCharts">
              <div class="vector-file-chart-grid">
                <ElCard shadow="never" class="vector-file-chart-card">
                  <template #header>Token 长度分布</template>
                  <Echart :options="selectedVectorFileTokenOption" height="240px" />
                </ElCard>
                <ElCard shadow="never" class="vector-file-chart-card">
                  <template #header>页码覆盖</template>
                  <Echart :options="selectedVectorFilePageOption" height="240px" />
                </ElCard>
                <ElCard shadow="never" class="vector-file-chart-card">
                  <template #header>质量标记</template>
                  <Echart :options="selectedVectorFileFlagOption" height="240px" />
                </ElCard>
              </div>
            </ElTabPane>
            <ElTabPane label="处理阶段" name="stages">
              <ElTable :data="selectedVectorFileLineageStages" border>
                <ElTableColumn prop="label" label="阶段" min-width="120" show-overflow-tooltip />
                <ElTableColumn prop="status" label="状态" width="120">
                  <template #default="{ row }">
                    <ElTag :type="row.done ? 'success' : 'warning'" effect="plain">
                      {{ row.status }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="evidence" label="证据" min-width="260" show-overflow-tooltip />
                <ElTableColumn prop="action" label="建议" min-width="260" show-overflow-tooltip />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="LLM 检索" name="retrieval">
              <ElDescriptions :column="2" border class="mb-12px">
                <ElDescriptionsItem label="溯源范围">
                  {{
                    selectedVectorFileLlmTrace.scope === 'document_explicit'
                      ? '文件级绑定'
                      : '项目级代理'
                  }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="审查任务编号">
                  {{ selectedVectorFileLlmTrace.relatedReviewRunCount || 0 }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="命中率">
                  {{ scorePercent(selectedVectorFileLlmTrace.hitRate as number) }}
                </ElDescriptionsItem>
                <ElDescriptionsItem label="证据命中">
                  {{ scorePercent(selectedVectorFileLlmTrace.evidenceHitRate as number) }}
                </ElDescriptionsItem>
              </ElDescriptions>
              <ElTable :data="selectedVectorFileDetailRetrievalRows" border>
                <ElTableColumn
                  prop="query"
                  label="检索问题"
                  min-width="240"
                  show-overflow-tooltip
                />
                <ElTableColumn prop="selectedRoute" label="路由" min-width="170" />
                <ElTableColumn prop="scope" label="范围" width="90" />
                <ElTableColumn prop="selectedClauseCount" label="条款" width="82" />
                <ElTableColumn prop="selectedChunkCount" label="切片" width="82" />
                <ElTableColumn label="证据" width="82">
                  <template #default="{ row }">
                    <ElTag :type="row.evidenceBacked ? 'success' : 'warning'" effect="plain">
                      {{ row.evidenceBacked ? '有' : '缺' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="过滤" width="82">
                  <template #default="{ row }">
                    <ElTag :type="row.filterScoped ? 'success' : 'danger'" effect="plain">
                      {{ row.filterScoped ? '有' : '缺' }}
                    </ElTag>
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="阻断与建议" name="blockers">
              <ElEmpty
                v-if="!selectedVectorFileBlockers.length"
                description="当前文件没有向量质量阻断"
              />
              <div v-else class="vector-file-blocker-list">
                <ElAlert
                  v-for="blocker in selectedVectorFileBlockers"
                  :key="blocker"
                  type="warning"
                  show-icon
                  :closable="false"
                  :title="blocker"
                />
              </div>
            </ElTabPane>
          </ElTabs>
        </template>
        <ElEmpty v-else description="请选择资料文件" />
      </ElDrawer>

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
              <span>审查任务编号</span>
              <strong>{{ selectedReviewRun.run.reviewRunId || selectedReviewRun.run.id }}</strong>
              <small>
                {{ friendlyTechLabel(selectedReviewRun.run.agentId || 'compliance_review_agent') }}
                · {{ friendlyTechLabel(selectedReviewRun.run.modelAlias) }}
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
            <ElButton plain :loading="actionLoading" @click="createReviewDiagnosticFeedback">
              记录诊断修正
            </ElButton>
          </div>

          <ElDescriptions :column="1" border class="mb-12px">
            <ElDescriptionsItem label="工作流编号">
              {{ selectedReviewTemporal.workflowId || selectedReviewRun.run.workflowId || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="编排执行器">
              {{
                friendlyTechLabel(
                  selectedReviewRun.run.graphRunner || selectedReviewRun.run.graphEngine
                )
              }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="检查点">
              {{
                friendlyTechLabel(
                  selectedReviewRun.run.graphExecution?.checkpointer ||
                    selectedReviewRun.run.graphExecution?.fallbackReason
                )
              }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="输入校验哈希">
              {{ selectedReviewRun.run.inputHash || '-' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="输出校验哈希">
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
              <div
                v-if="normalizedReviewReasoningRows.length"
                class="audit-step-list drawer-step-list"
              >
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
              <ElTable :data="normalizedReviewFindingRows" border>
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
              <ElTable :data="normalizedReviewQualityRows" border>
                <ElTableColumn
                  prop="name"
                  label="门禁/维度"
                  min-width="150"
                  show-overflow-tooltip
                />
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
              <ElTable :data="reviewLineageRows" border>
                <ElTableColumn prop="label" label="字段" width="130" />
                <ElTableColumn label="值" min-width="320" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ friendlyTechnicalText(shortText(row.value)) }}
                  </template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="人工修正" name="human">
              <ElTable :data="normalizedReviewHumanCorrectionRows" border>
                <ElTableColumn prop="targetType" label="对象" min-width="120" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.targetType) }}</template>
                </ElTableColumn>
                <ElTableColumn
                  prop="correctionType"
                  label="类型"
                  min-width="140"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    {{ friendlyIssueLabel(row.correctionType) }}
                  </template>
                </ElTableColumn>
                <ElTableColumn prop="before" label="修正前" min-width="220" show-overflow-tooltip />
                <ElTableColumn label="修正后" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">{{ shortText(row.after) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="rootCause" label="归因" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyIssueLabel(row.rootCause) }}</template>
                </ElTableColumn>
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
              <span>OCR 任务</span>
              <strong>{{ selectedOcrRun.job.jobId || selectedOcrRun.job.id }}</strong>
              <small
                >{{ friendlyTechLabel(selectedOcrRun.job.profileId) }} ·
                {{ friendlyTechLabel(selectedOcrRun.job.documentType) }}</small
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
                · 缺失 {{ friendlyTechList(selectedOcrMissingVariants) }}
              </span>
            </ElDescriptionsItem>
            <ElDescriptionsItem label="人工修正">
              {{ selectedOcrCorrectionRows.length }}
            </ElDescriptionsItem>
          </ElDescriptions>

          <ElTabs class="audit-drawer-tabs">
            <ElTabPane label="引擎" name="engines">
              <ElTable :data="selectedOcrEngineRows" border>
                <ElTableColumn prop="engine" label="引擎" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.engine) }}</template>
                </ElTableColumn>
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
              <ElTable :data="ocrFieldFailureRows" border>
                <ElTableColumn prop="code" label="问题" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.code) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="fieldName" label="字段" min-width="130" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyFieldLabel(row.fieldName) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="fieldValue" label="值" min-width="160" show-overflow-tooltip />
                <ElTableColumn prop="confidence" label="置信度" width="95" />
              </ElTable>
            </ElTabPane>
            <ElTabPane label="证据缺口" name="evidence">
              <ElTable :data="ocrMissingEvidenceRows" border>
                <ElTableColumn prop="targetType" label="类型" width="110">
                  <template #default="{ row }">{{ friendlyTechLabel(row.targetType) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="targetId" label="目标" min-width="160" show-overflow-tooltip />
                <ElTableColumn
                  prop="parseResultId"
                  label="结果"
                  min-width="170"
                  show-overflow-tooltip
                />
                <ElTableColumn
                  prop="profileId"
                  label="解析配置"
                  min-width="160"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ friendlyTechLabel(row.profileId) }}</template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="诊断" name="diagnostics">
              <ElTable :data="selectedOcrDiagnosticRows" border>
                <ElTableColumn prop="code" label="诊断码" min-width="150" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechLabel(row.code) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="level" label="等级" width="100">
                  <template #default="{ row }">{{ friendlyStatus(row.level) }}</template>
                </ElTableColumn>
                <ElTableColumn prop="message" label="说明" min-width="280" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyTechnicalText(row.message) }}</template>
                </ElTableColumn>
              </ElTable>
            </ElTabPane>
            <ElTabPane label="人工修正" name="corrections">
              <ElTable :data="selectedOcrCorrectionRows" border>
                <ElTableColumn prop="fieldCode" label="字段" min-width="130" show-overflow-tooltip>
                  <template #default="{ row }">{{ friendlyFieldLabel(row.fieldCode) }}</template>
                </ElTableColumn>
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
                {{ friendlyTechLabel(selectedAnnotationTask?.scenario) }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="页面尺寸">
                {{ annotationPageSize.width }} × {{ annotationPageSize.height }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="阻断">
                {{ friendlyIssueList(selectedAnnotationTask?.readinessBlockers, '无') }}
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
                  placeholder="字段编码 / 表格结构 / 印章名称"
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
                      item.fieldCode
                        ? friendlyFieldLabel(item.fieldCode as string)
                        : friendlyTechLabel(
                            item.businessSchema || item.nameContains || item.sealType
                          )
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
  max-width: 100%;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.project-audit-workbench > * {
  max-width: 100%;
  min-width: 0;
}

.project-audit-card {
  max-width: 100%;
  min-width: 0;
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
  max-width: 100%;
  min-width: 0;
  min-height: 52px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
  grid-template-columns: minmax(260px, 1fr) minmax(360px, 1.25fr);
  gap: 14px;
  align-items: center;
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
  max-width: 100%;
  min-width: 0;
  margin-bottom: 16px;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
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

.workbench-summary-card--button {
  display: grid;
  width: 100%;
  font: inherit;
  color: inherit;
  text-align: left;
  appearance: none;
  cursor: pointer;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease,
    background-color 180ms ease;
}

.workbench-summary-card--button:hover,
.workbench-summary-card--button:focus-visible,
.workbench-summary-card--button.is-active {
  background: #f8fbff;
  border-color: #8db7f6;
  box-shadow:
    0 0 0 2px rgb(37 99 235 / 10%),
    0 12px 24px rgb(15 23 42 / 8%);
}

.workbench-summary-card--button:hover,
.workbench-summary-card--button:focus-visible {
  transform: translateY(-1px);
}

.workbench-summary-card--button:focus-visible {
  outline: 3px solid rgb(37 99 235 / 20%);
  outline-offset: 2px;
}

.agent-status-tabs {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.agent-status-panel {
  display: grid;
  grid-template-columns: minmax(0, 0.42fr) minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-width: 0;
  min-height: 74px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
}

.agent-status-panel div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.agent-status-panel span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.agent-status-panel strong {
  min-width: 0;
  font-size: 18px;
  font-weight: 900;
  line-height: 26px;
  color: #172033;
}

.agent-status-panel small {
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
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

.project-overview-command-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.project-overview-governance-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(260px, 0.94fr) minmax(260px, 0.94fr);
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.project-overview-chart-panel,
.project-overview-governance-panel {
  min-width: 0;
}

.project-overview-chart-panel--full {
  grid-column: 1 / -1;
}

.project-overview-echart {
  width: 100%;
  min-width: 0;
}

.project-overview-node-status-bars {
  display: grid;
  gap: 10px;
  width: 100%;
  padding: 10px 2px 2px;
}

.project-overview-node-status-row {
  display: grid;
  grid-template-columns: minmax(90px, 148px) minmax(240px, 1fr) minmax(74px, auto);
  gap: 12px;
  align-items: center;
  min-width: 0;
  min-height: 36px;
}

.project-overview-node-status-row > span {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  line-height: 20px;
  color: #52617a;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-overview-node-status-track {
  position: relative;
  height: 24px;
  min-width: 0;
  overflow: hidden;
  background: repeating-linear-gradient(
      90deg,
      transparent 0,
      transparent calc(10% - 1px),
      #e7eef8 calc(10% - 1px),
      #e7eef8 10%
    ),
    #f8fbff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.project-overview-node-status-track i {
  display: block;
  height: 100%;
  min-width: 4px;
  background: #2563eb;
  border-radius: 7px;
  box-shadow: 0 7px 18px rgb(37 99 235 / 18%);
}

.project-overview-node-status-track::after {
  position: absolute;
  pointer-events: none;
  border-radius: inherit;
  content: '';
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 60%);
  inset: 0;
}

.project-overview-node-status-row strong {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
  min-width: 0;
  font-size: 16px;
  font-weight: 900;
  line-height: 22px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.project-overview-node-status-row strong small {
  font-size: 11px;
  font-weight: 800;
  color: #7b8798;
}

.project-overview-node-status-row--green .project-overview-node-status-track i {
  background: #16a34a;
  box-shadow: 0 7px 18px rgb(22 163 74 / 18%);
}

.project-overview-node-status-row--orange .project-overview-node-status-track i {
  background: #f59e0b;
  box-shadow: 0 7px 18px rgb(245 158 11 / 18%);
}

.project-overview-node-status-row--red .project-overview-node-status-track i {
  background: #dc2626;
  box-shadow: 0 7px 18px rgb(220 38 38 / 16%);
}

.project-overview-diagnostics {
  margin-bottom: 16px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.project-overview-diagnostics summary {
  display: flex;
  min-height: 48px;
  padding: 0 14px;
  list-style: none;
  cursor: pointer;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.project-overview-diagnostics summary::-webkit-details-marker {
  display: none;
}

.project-overview-diagnostics summary::after {
  font-size: 13px;
  font-weight: 900;
  color: #2563eb;
  content: '展开';
}

.project-overview-diagnostics[open] summary {
  border-bottom: 1px solid #e6edf7;
}

.project-overview-diagnostics[open] summary::after {
  content: '收起';
}

.project-overview-diagnostics summary span {
  font-size: 14px;
  font-weight: 900;
  color: #172033;
}

.project-overview-diagnostics summary small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 800;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-overview-diagnostics .project-audit-health-grid {
  padding: 14px 14px 0;
}

.project-overview-diagnostics .project-audit-node-grid {
  padding: 0 14px 14px;
}

.project-overview-capability-list,
.project-overview-task-list,
.project-overview-action-list {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.project-overview-capability-item,
.project-overview-task-item,
.project-overview-action-item {
  display: grid;
  width: 100%;
  min-width: 0;
  padding: 12px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  outline: none;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.project-overview-capability-item {
  grid-template-columns: minmax(84px, 0.38fr) minmax(90px, 0.45fr) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.project-overview-task-item,
.project-overview-action-item {
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 6px 10px;
  align-items: start;
}

.project-overview-task-item span,
.project-overview-action-item span {
  grid-row: span 2;
  min-height: 26px;
  padding: 5px 7px;
  font-size: 12px;
  font-weight: 900;
  color: #1d4ed8;
  text-align: center;
  background: #eef5ff;
  border: 1px solid #cfe0ff;
  border-radius: 6px;
}

.project-overview-capability-item span,
.project-overview-task-item strong,
.project-overview-action-item strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-overview-capability-item strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  line-height: 18px;
  color: #23314a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-overview-capability-item small,
.project-overview-task-item small,
.project-overview-action-item small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 17px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-overview-capability-item:hover,
.project-overview-task-item:hover,
.project-overview-action-item:hover,
.project-overview-capability-item:focus-visible,
.project-overview-task-item:focus-visible,
.project-overview-action-item:focus-visible {
  background: #f8fbff;
  border-color: #9dc0f7;
  transform: translateY(-1px);
}

.project-overview-item--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.project-overview-item--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.project-overview-item--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.project-overview-item--red {
  background: #fff3f1;
  border-color: #ffc9c3;
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
  white-space: normal;
  -webkit-box-orient: vertical;
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
  transform: translateY(-1px);
  box-shadow: 0 10px 22px rgb(15 23 42 / 8%);
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

.audit-flow-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 16px;
}

.audit-flow-card {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 9px;
  min-width: 0;
  min-height: 86px;
  padding: 11px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 7px 18px rgb(15 23 42 / 4%);
}

.audit-flow-card > span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  font-size: 11px;
  font-weight: 900;
  color: #1f66d8;
  background: #eff6ff;
  border: 1px solid #c9dcfb;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}

.audit-flow-card div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.audit-flow-card strong,
.audit-flow-card small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.audit-flow-card strong {
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  white-space: nowrap;
}

.audit-flow-card small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.audit-flow-card em {
  grid-column: 2;
  justify-self: start;
  min-height: 22px;
  padding: 2px 7px;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  line-height: 18px;
  color: #475569;
  background: rgb(255 255 255 / 82%);
  border: 1px solid #dbe8f7;
  border-radius: 6px;
  font-variant-numeric: tabular-nums;
}

.audit-flow-card--green {
  background: #f2fbf6;
  border-color: #c9ead8;
}

.audit-flow-card--blue {
  background: #f8fbff;
  border-color: #cbdcf8;
}

.audit-flow-card--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.audit-flow-card--red {
  background: #fff4f3;
  border-color: #ffc8c1;
}

.vector-quality-board {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 16px;
}

.technology-stack-panel :deep(.el-card__body) {
  display: grid;
  gap: 14px;
}

.technology-stack-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}

.technology-stack-card {
  display: grid;
  gap: 5px;
  min-width: 0;
  min-height: 126px;
  padding: 12px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.technology-stack-card span,
.technology-stack-card strong,
.technology-stack-card em,
.technology-stack-card small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.technology-stack-card span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #64748b;
  white-space: nowrap;
}

.technology-stack-card strong {
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  white-space: nowrap;
}

.technology-stack-card em {
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  line-height: 18px;
  color: #2563eb;
  white-space: nowrap;
}

.technology-stack-card small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.technology-stack-card--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.technology-stack-card--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.technology-stack-card--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.technology-stack-card--red {
  background: #fff4f3;
  border-color: #ffc8c1;
}

.technology-model-table {
  width: 100%;
}

.vector-lineage-intro {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  min-width: 0;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: linear-gradient(180deg, #f8fbff, #fff);
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
}

.vector-lineage-intro div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.vector-lineage-intro span,
.vector-lineage-intro strong,
.vector-lineage-intro small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vector-lineage-intro span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.vector-lineage-intro strong {
  font-size: 16px;
  font-weight: 900;
  line-height: 22px;
  color: #172033;
}

.vector-lineage-intro small {
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
}

.vector-quality-card {
  display: grid;
  gap: 7px;
  min-width: 0;
  min-height: 112px;
  padding: 15px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 4%);
}

.vector-quality-card span,
.vector-quality-card strong,
.vector-quality-card small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vector-quality-card span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #64748b;
  white-space: nowrap;
}

.vector-quality-card strong {
  font-size: 24px;
  font-weight: 900;
  line-height: 30px;
  color: #172033;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.vector-quality-card small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.vector-quality-card--green {
  border-color: #c9ead8;
}

.vector-quality-card--blue {
  border-color: #cbdcf8;
}

.vector-quality-card--orange {
  border-color: #f6d6a5;
}

.vector-quality-card--red {
  border-color: #ffc8c1;
}

.vector-quality-panel :deep(.el-card__body) {
  padding: 12px;
}

.vector-quality-echart {
  width: 100%;
  min-width: 0;
}

.chart-panel :deep(.el-card__body) {
  padding: 10px;
}

.ocr-command-center {
  display: grid;
  gap: 16px;
  margin: 0 0 18px;
}

.ocr-online-entry {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 14px 16px;
  background: #f8fbff;
  border: 1px solid #dbe7f7;
  border-radius: 8px;
}

.ocr-online-entry__copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.ocr-online-entry__copy span {
  font-size: 12px;
  font-weight: 850;
  color: #2563eb;
}

.ocr-online-entry__copy strong {
  min-width: 0;
  font-size: 16px;
  font-weight: 900;
  line-height: 22px;
  color: #172033;
}

.ocr-online-entry__copy small {
  min-width: 0;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
}

.ocr-online-entry :deep(.el-button) {
  min-width: 132px;
}

.ocr-step-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.ocr-step-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 6px 10px;
  min-width: 0;
  min-height: 96px;
  padding: 13px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 7px 18px rgb(15 23 42 / 4%);
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease;
}

.ocr-step-card:hover,
.ocr-step-card:focus-visible {
  border-color: #8db7f6;
  box-shadow: 0 10px 22px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.ocr-step-card.is-active {
  border-color: #2563eb;
  box-shadow:
    0 0 0 2px rgb(37 99 235 / 12%),
    0 12px 24px rgb(15 23 42 / 9%);
}

.ocr-step-card:focus-visible {
  outline: 3px solid rgb(37 99 235 / 20%);
  outline-offset: 2px;
}

.ocr-step-card span {
  grid-row: span 2;
  width: 34px;
  height: 34px;
  font-size: 12px;
  font-weight: 900;
  line-height: 34px;
  color: #2563eb;
  text-align: center;
  background: #eff6ff;
  border-radius: 8px;
}

.ocr-step-card strong,
.ocr-step-card small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-step-card strong {
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  white-space: normal;
}

.ocr-step-card small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.ocr-step-card--green {
  border-color: #c9ead8;
}

.ocr-step-card--orange {
  border-color: #f6d6a5;
}

.ocr-step-card--red {
  border-color: #ffc8c1;
}

.ocr-step-card--blue {
  border-color: #cbdcf8;
}

.ocr-command-kpis {
  margin-bottom: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.ocr-command-center > .ocr-command-kpis,
.ocr-command-center > .el-row {
  display: none;
}

.ocr-status-tabs {
  display: grid;
  gap: 12px;
  padding: 14px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
}

.ocr-status-tabs__header {
  display: grid;
  grid-template-columns: minmax(0, 0.46fr) minmax(0, 1fr);
  gap: 12px;
  align-items: end;
}

.ocr-status-tabs__header div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.ocr-status-tabs__header span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.ocr-status-tabs__header strong {
  min-width: 0;
  font-size: 18px;
  font-weight: 900;
  line-height: 26px;
  color: #172033;
}

.ocr-status-tabs__header small {
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
}

.ocr-status-tabs__body {
  min-width: 0;
}

.ocr-status-dialog__body {
  display: grid;
  max-height: min(72vh, 720px);
  overflow: auto;
  padding-right: 2px;
}

.ocr-secondary-menu {
  display: grid;
  gap: 10px;
}

.ocr-secondary-tool {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 12px;
  min-width: 0;
  min-height: 84px;
  padding: 13px 14px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  transition:
    border-color 180ms ease,
    box-shadow 180ms ease,
    transform 180ms ease;
}

.ocr-secondary-tool:hover,
.ocr-secondary-tool:focus-visible {
  border-color: #8db7f6;
  box-shadow: 0 10px 22px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.ocr-secondary-tool:focus-visible {
  outline: 3px solid rgb(37 99 235 / 20%);
  outline-offset: 2px;
}

.ocr-secondary-tool span {
  min-width: 0;
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
}

.ocr-secondary-tool strong {
  font-size: 12px;
  font-weight: 900;
  line-height: 20px;
  color: #2563eb;
}

.ocr-secondary-tool small {
  grid-column: 1 / -1;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  text-overflow: ellipsis;
}

.ocr-secondary-tool--green {
  border-color: #c9ead8;
}

.ocr-secondary-tool--orange {
  border-color: #f6d6a5;
}

.ocr-secondary-tool--red {
  border-color: #ffc8c1;
}

.ocr-secondary-tool--blue {
  border-color: #cbdcf8;
}

.chart-zoom-value {
  min-width: 42px;
  font-size: 12px;
  font-weight: 900;
  line-height: 22px;
  color: #2563eb;
  text-align: center;
  background: #eff6ff;
  border: 1px solid #cfe0fb;
  border-radius: 999px;
}

.ocr-priority-panel :deep(.el-card__body) {
  min-height: 320px;
}

.ocr-blocker-list {
  display: grid;
  gap: 10px;
}

.ocr-blocker-list article {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 11px;
  background: #fff8ed;
  border: 1px solid #f6d6a5;
  border-radius: 8px;
}

.ocr-blocker-list strong,
.ocr-blocker-list small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-blocker-list strong {
  font-size: 13px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  white-space: nowrap;
}

.ocr-blocker-list small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.knowledge-chart-shell {
  position: relative;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  cursor: grab;
  background: linear-gradient(90deg, rgb(37 99 235 / 4%) 1px, transparent 1px),
    linear-gradient(180deg, rgb(37 99 235 / 4%) 1px, transparent 1px),
    linear-gradient(180deg, #f8fbff 0%, #fff 100%);
  background-size:
    34px 34px,
    34px 34px,
    auto;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  user-select: none;
  overscroll-behavior: contain;
  touch-action: none;
  contain: layout paint;
  scrollbar-color: #a9c7ed transparent;
  scrollbar-width: thin;
}

.knowledge-chart-shell:focus-visible,
.langgraph-chart-shell:focus-visible {
  border-color: #8eb8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(37 99 235 / 14%);
}

.knowledge-chart-shell.is-panning,
.langgraph-chart-shell.is-panning {
  cursor: grabbing;
}

.chart-zoom-frame {
  position: relative;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
  flex: 0 0 auto;
  contain: strict;
}

.chart-zoom-content {
  position: absolute;
  inset: 0 auto auto 0;
  transform-origin: 0 0;
  will-change: transform;
  backface-visibility: hidden;
}

.knowledge-chart-shell::-webkit-scrollbar,
.langgraph-chart-shell::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.knowledge-chart-shell::-webkit-scrollbar-thumb,
.langgraph-chart-shell::-webkit-scrollbar-thumb {
  background: #a9c7ed;
  border: 2px solid #f8fbff;
  border-radius: 999px;
}

.knowledge-chart-shell::-webkit-scrollbar-track,
.langgraph-chart-shell::-webkit-scrollbar-track {
  background: transparent;
}

.knowledge-chart-shell--tree {
  height: 380px;
  background-size:
    42px 42px,
    42px 42px,
    auto;
}

.knowledge-echart {
  width: 100%;
  min-width: 760px;
  touch-action: none;
}

.knowledge-chart-shell--sankey .knowledge-echart {
  min-width: 960px;
}

.knowledge-chart-shell--tree .knowledge-echart {
  min-width: 1320px;
}

.knowledge-chart-shell--timeline .knowledge-echart {
  min-width: 920px;
}

.knowledge-chart-shell--heatmap .knowledge-echart {
  min-width: 820px;
}

.sr-only-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.ocr-capability-shell {
  display: grid;
  gap: 14px;
}

.ocr-capability-hero,
.ocr-capability-card,
.ocr-capability-preview,
.ocr-capability-summary {
  background: #fff;
  border: 1px solid #dbeafe;
  border-radius: 12px;
}

.ocr-capability-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
  padding: 18px;
  background: linear-gradient(135deg, rgb(239 246 255 / 94%), rgb(255 255 255 / 98%)), #fff;
}

.ocr-capability-hero div,
.ocr-capability-card__head {
  min-width: 0;
}

.ocr-capability-hero span,
.ocr-capability-hero strong,
.ocr-capability-hero small {
  display: block;
}

.ocr-capability-hero span {
  font-size: 12px;
  font-weight: 800;
  color: #2563eb;
}

.ocr-capability-hero strong {
  margin-top: 6px;
  font-size: 20px;
  line-height: 1.35;
  color: #0f172a;
}

.ocr-capability-hero small {
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}

.ocr-capability-layout,
.ocr-capability-result {
  display: grid;
  grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.15fr);
  gap: 14px;
}

.ocr-capability-card,
.ocr-capability-preview,
.ocr-capability-summary {
  min-width: 0;
  padding: 14px;
}

.ocr-capability-card--collapsed {
  align-self: start;
}

.ocr-capability-card--recent.ocr-capability-card--collapsed {
  padding-bottom: 12px;
}

.ocr-capability-card__head {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.ocr-capability-card__head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 15px;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-capability-upload {
  width: 100%;
  min-height: 118px;
  padding: 18px;
  color: #1e40af;
  text-align: left;
  cursor: pointer;
  background: #f8fbff;
  border: 1px dashed #93c5fd;
  border-radius: 12px;
  transition:
    border-color 0.2s ease,
    background 0.2s ease;
}

.ocr-capability-upload:hover {
  background: #eff6ff;
  border-color: #2563eb;
}

.ocr-capability-upload strong,
.ocr-capability-upload span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-capability-upload strong {
  font-size: 16px;
  color: #0f172a;
  white-space: nowrap;
}

.ocr-capability-upload span {
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}

.ocr-capability-form {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.ocr-capability-form label {
  display: grid;
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  gap: 6px;
}

.ocr-capability-switches {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.ocr-capability-switches label {
  display: inline-flex;
  min-height: 30px;
  padding: 0 10px;
  font-size: 12px;
  color: #334155;
  background: #f8fafc;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  gap: 6px;
  align-items: center;
}

.ocr-capability-table {
  --el-table-border-color: #e2e8f0;
}

.ocr-preview-stage {
  position: relative;
  display: grid;
  place-items: center;
  height: 420px;
  padding: 10px;
  overflow: hidden;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.ocr-preview-pdf-fallback {
  width: 100%;
  height: 100%;
  border: 0;
}

.ocr-preview-pdf-fallback {
  display: grid;
  place-items: center;
}

.ocr-roi-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0 10px;
}

.ocr-roi-legend__item {
  display: inline-flex;
  min-height: 28px;
  padding: 0 9px;
  font-size: 12px;
  line-height: 1;
  color: #1e293b;
  background: #f8fafc;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  gap: 6px;
  align-items: center;
}

.ocr-roi-legend__item i {
  width: 10px;
  height: 10px;
  background: #2563eb;
  border-radius: 999px;
  box-shadow: 0 0 0 3px rgb(37 99 235 / 12%);
}

.ocr-roi-legend__item strong {
  font-weight: 800;
}

.ocr-roi-legend__item small {
  min-width: 18px;
  padding: 2px 5px;
  font-size: 11px;
  font-weight: 800;
  color: #1d4ed8;
  text-align: center;
  background: rgb(37 99 235 / 10%);
  border-radius: 999px;
}

.ocr-roi-legend__item--green {
  border-color: #bbf7d0;
}

.ocr-roi-legend__item--green i {
  background: #16a34a;
  box-shadow: 0 0 0 3px rgb(22 163 74 / 12%);
}

.ocr-roi-legend__item--green small {
  color: #15803d;
  background: rgb(22 163 74 / 10%);
}

.ocr-roi-legend__item--orange {
  border-color: #fed7aa;
}

.ocr-roi-legend__item--orange i {
  background: #ea580c;
  box-shadow: 0 0 0 3px rgb(234 88 12 / 12%);
}

.ocr-roi-legend__item--orange small {
  color: #c2410c;
  background: rgb(234 88 12 / 10%);
}

.ocr-roi-legend__item--red {
  border-color: #fecaca;
}

.ocr-roi-legend__item--red i {
  background: #dc2626;
  box-shadow: 0 0 0 3px rgb(220 38 38 / 12%);
}

.ocr-roi-legend__item--red small {
  color: #b91c1c;
  background: rgb(220 38 38 / 10%);
}

.ocr-roi-legend__item--purple {
  border-color: #ddd6fe;
}

.ocr-roi-legend__item--purple i {
  background: #7c3aed;
  box-shadow: 0 0 0 3px rgb(124 58 237 / 12%);
}

.ocr-roi-legend__item--purple small {
  color: #6d28d9;
  background: rgb(124 58 237 / 10%);
}

.ocr-preview-image-frame {
  position: relative;
  display: inline-block;
  max-width: 100%;
  max-height: 100%;
}

.ocr-preview-image-frame img {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  max-height: 398px;
  object-fit: contain;
}

.ocr-preview-pdf-page-frame {
  max-width: 100%;
  max-height: 100%;
  background: #ffffff;
  box-shadow: 0 8px 24px rgb(15 23 42 / 16%);
}

.ocr-preview-pdf-page-frame img {
  max-height: 398px;
}

.ocr-roi-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.ocr-roi-box {
  position: absolute;
  min-width: 22px;
  min-height: 18px;
  padding: 0;
  overflow: visible;
  background: rgb(37 99 235 / 5%);
  border: 1.5px solid rgb(37 99 235 / 82%);
  border-radius: 2px;
  box-shadow: none;
  pointer-events: auto;
}

.ocr-roi-box span {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 0;
  display: inline-flex;
  max-width: 260px;
  min-height: 24px;
  padding: 4px 8px;
  overflow: hidden;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
  visibility: hidden;
  background: rgb(255 255 255 / 96%);
  border: 1px solid rgb(37 99 235 / 35%);
  border-radius: 4px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 18%);
  opacity: 0;
  transform: translateY(3px);
  transition:
    opacity 0.12s ease,
    transform 0.12s ease,
    visibility 0.12s ease;
}

.ocr-roi-box:hover,
.ocr-roi-box:focus-visible {
  z-index: 3;
  background: rgb(37 99 235 / 12%);
  border-width: 2px;
  border-color: #2563eb;
  outline: none;
}

.ocr-roi-box:hover span,
.ocr-roi-box:focus-visible span {
  visibility: visible;
  opacity: 1;
  transform: translateY(0);
}

.ocr-roi-box--blue {
  background: rgb(37 99 235 / 5%);
  border-color: rgb(37 99 235 / 82%);
}

.ocr-roi-box--blue span {
  border-color: rgb(37 99 235 / 35%);
}

.ocr-roi-box--green {
  background: rgb(22 163 74 / 5%);
  border-color: rgb(22 163 74 / 78%);
}

.ocr-roi-box--green span {
  border-color: rgb(22 163 74 / 35%);
}

.ocr-roi-box--orange {
  background: rgb(234 88 12 / 5%);
  border-color: rgb(234 88 12 / 78%);
}

.ocr-roi-box--orange span {
  border-color: rgb(234 88 12 / 35%);
}

.ocr-roi-box--red {
  background: rgb(220 38 38 / 5%);
  border-color: rgb(220 38 38 / 78%);
}

.ocr-roi-box--red span {
  border-color: rgb(220 38 38 / 35%);
}

.ocr-roi-box--purple {
  background: rgb(124 58 237 / 5%);
  border-color: rgb(124 58 237 / 78%);
}

.ocr-roi-box--purple span {
  border-color: rgb(124 58 237 / 35%);
}

.ocr-roi-box--blue:hover,
.ocr-roi-box--blue:focus-visible {
  background: rgb(37 99 235 / 12%);
  border-color: #2563eb;
}

.ocr-roi-box--green:hover,
.ocr-roi-box--green:focus-visible {
  background: rgb(22 163 74 / 12%);
  border-color: #16a34a;
}

.ocr-roi-box--orange:hover,
.ocr-roi-box--orange:focus-visible {
  background: rgb(234 88 12 / 12%);
  border-color: #ea580c;
}

.ocr-roi-box--red:hover,
.ocr-roi-box--red:focus-visible {
  background: rgb(220 38 38 / 12%);
  border-color: #dc2626;
}

.ocr-roi-box--purple:hover,
.ocr-roi-box--purple:focus-visible {
  background: rgb(124 58 237 / 12%);
  border-color: #7c3aed;
}

.ocr-capability-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.ocr-capability-kpis div {
  min-width: 0;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.ocr-capability-kpis span,
.ocr-capability-kpis strong {
  display: block;
}

.ocr-capability-kpis span {
  font-size: 12px;
  color: #64748b;
}

.ocr-capability-kpis strong {
  margin-top: 4px;
  overflow: hidden;
  font-size: 18px;
  color: #0f172a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-capability-output-tabs {
  margin-top: 12px;
}

.ocr-capability-text-output {
  max-height: 420px;
  min-height: 220px;
  padding: 12px;
  margin: 0;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #172033;
  word-break: break-word;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ocr-table-result-list {
  display: grid;
  gap: 12px;
}

.ocr-table-result-card {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ocr-table-result-card__head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.ocr-table-result-card__head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 950;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-table-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.ocr-table-meta div {
  min-width: 0;
  padding: 8px 9px;
  background: #f8fafc;
  border: 1px solid #e5edf7;
  border-radius: 8px;
}

.ocr-table-meta dt,
.ocr-table-meta dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-table-meta dt {
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #64748b;
}

.ocr-table-meta dd {
  margin-top: 3px;
  font-size: 12px;
  font-weight: 850;
  line-height: 17px;
  color: #172033;
}

.ocr-structured-table {
  width: 100%;
  border: 1px solid #dbe5f2;
  border-collapse: collapse;
  border-radius: 8px;
  table-layout: fixed;
}

.ocr-structured-table th,
.ocr-structured-table td {
  min-width: 0;
  padding: 8px 9px;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
  border: 1px solid #dbe5f2;
}

.ocr-structured-table th {
  font-size: 12px;
  font-weight: 950;
  line-height: 17px;
  color: #172033;
  text-align: left;
  background: #f1f5f9;
}

.ocr-structured-table td {
  font-size: 12px;
  font-weight: 760;
  line-height: 18px;
  color: #334155;
  vertical-align: top;
  background: #fff;
}

.ocr-seal-result-list {
  display: grid;
  gap: 10px;
}

.ocr-seal-result-card {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.ocr-seal-result-card__head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.ocr-seal-result-card__head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.ocr-seal-result-card__head span,
.ocr-seal-content span {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-seal-result-card__head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 950;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-seal-meta {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.ocr-seal-meta div {
  min-width: 0;
  padding: 8px 9px;
  background: #f8fafc;
  border: 1px solid #e5edf7;
  border-radius: 8px;
}

.ocr-seal-meta dt,
.ocr-seal-meta dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-seal-meta dt {
  font-size: 11px;
  font-weight: 900;
  line-height: 16px;
  color: #64748b;
}

.ocr-seal-meta dd {
  margin-top: 3px;
  font-size: 12px;
  font-weight: 850;
  line-height: 17px;
  color: #172033;
}

.ocr-seal-content {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px;
  background: #f8fbff;
  border: 1px solid #dbeafe;
  border-radius: 8px;
}

.ocr-seal-content p,
.ocr-seal-content small {
  min-width: 0;
  margin: 0;
  font-size: 13px;
  line-height: 19px;
  color: #172033;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.ocr-seal-content small {
  color: #64748b;
}

.lineage-document-grid,
.pageindex-friendly-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.85fr) repeat(2, minmax(260px, 1fr));
  gap: 10px;
  margin: 0 0 16px;
}

.lineage-document-intro,
.lineage-document-card,
.pageindex-friendly-intro,
.pageindex-friendly-card {
  display: grid;
  gap: 8px;
  min-width: 0;
  min-height: 154px;
  padding: 13px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 7px 18px rgb(15 23 42 / 4%);
}

.lineage-document-intro,
.pageindex-friendly-intro {
  background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
  border-color: #cfe0f5;
}

.lineage-document-intro span,
.lineage-document-card__head span,
.pageindex-friendly-intro span,
.pageindex-friendly-card__head small {
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lineage-document-intro strong,
.lineage-document-card__head strong,
.pageindex-friendly-intro strong,
.pageindex-friendly-card__head strong {
  overflow: hidden;
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lineage-document-intro small,
.lineage-document-card p,
.lineage-document-card > small,
.pageindex-friendly-intro small,
.pageindex-friendly-card p {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
}

.lineage-document-card__head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  min-width: 0;
}

.lineage-document-card__head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.lineage-stage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-height: 50px;
  align-content: flex-start;
}

.lineage-stage-pill {
  display: inline-flex;
  max-width: 100%;
  min-height: 22px;
  padding: 2px 7px;
  overflow: hidden;
  font-size: 11px;
  font-weight: 800;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid transparent;
  border-radius: 999px;
}

.lineage-stage-pill.is-done {
  color: #167341;
  background: #ecfdf3;
  border-color: #bfe7cf;
}

.lineage-stage-pill.is-waiting {
  color: #b45309;
  background: #fff7ed;
  border-color: #fed7aa;
}

.pageindex-friendly-card__head {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: start;
  min-width: 0;
}

.pageindex-friendly-card__head > span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  font-size: 11px;
  font-weight: 900;
  color: #1f66d8;
  background: #eff6ff;
  border: 1px solid #c9dcfb;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}

.pageindex-friendly-card__head > div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.pageindex-friendly-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.pageindex-friendly-facts span {
  display: grid;
  gap: 2px;
  min-width: 0;
  min-height: 44px;
  padding: 6px 7px;
  background: #f8fbff;
  border: 1px solid #e3edf9;
  border-radius: 8px;
}

.pageindex-friendly-facts em,
.pageindex-friendly-facts strong {
  min-width: 0;
  overflow: hidden;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pageindex-friendly-facts em {
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  color: #64748b;
}

.pageindex-friendly-facts strong {
  font-size: 12px;
  font-weight: 900;
  color: #172033;
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
  background: #2563eb;
  border-radius: 0 4px 4px 0;
  content: '';
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

.langgraph-chart-shell {
  position: relative;
  height: 410px;
  max-width: 100%;
  min-height: 0;
  padding: 6px;
  overflow: hidden;
  cursor: grab;
  background: linear-gradient(90deg, rgb(37 99 235 / 5%) 1px, transparent 1px),
    linear-gradient(180deg, rgb(37 99 235 / 5%) 1px, transparent 1px),
    linear-gradient(180deg, #f8fbff 0%, #fff 100%);
  background-size:
    34px 34px,
    34px 34px,
    auto;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  user-select: none;
  overscroll-behavior: contain;
  touch-action: none;
  contain: layout paint;
  scrollbar-color: #a9c7ed transparent;
  scrollbar-width: thin;
}

.langgraph-echart {
  width: 100%;
  min-width: 900px;
  touch-action: none;
}

.agent-friendly-note {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 11px 12px;
  background: linear-gradient(180deg, #f8fbff, #fff);
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.agent-friendly-note strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 950;
  line-height: 19px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-friendly-note small {
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  color: #64748b;
}

.finding-friendly-list {
  display: grid;
  gap: 10px;
  max-height: 322px;
  padding-right: 4px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: #c7d5e8 transparent;
}

.finding-friendly-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(150px, 0.42fr);
  gap: 12px;
  min-width: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #e0e9f6;
  border-radius: 8px;
}

.finding-friendly-main,
.finding-friendly-side {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.finding-friendly-main span {
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.finding-friendly-main strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 950;
  line-height: 20px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.finding-friendly-main small,
.finding-friendly-side small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
}

.finding-friendly-main small {
  white-space: nowrap;
}

.finding-friendly-side {
  justify-items: end;
  text-align: right;
}

.finding-friendly-side strong {
  font-size: 22px;
  font-weight: 950;
  line-height: 26px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.langgraph-cog-panel {
  display: grid;
  gap: 10px;
  padding: 12px;
  margin-top: 12px;
  background: linear-gradient(180deg, #f8fbff, #fff);
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.langgraph-cog-head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  justify-content: space-between;
  min-width: 0;
}

.langgraph-cog-head div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.langgraph-cog-head span {
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
}

.langgraph-cog-head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.langgraph-cog-list {
  display: grid;
  gap: 8px;
}

.langgraph-cog-list article {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 9px;
  align-items: start;
  min-width: 0;
  padding: 9px 10px;
  background: #fff;
  border: 1px solid #e4ecf7;
  border-radius: 8px;
}

.langgraph-cog-list article > span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 24px;
  font-size: 11px;
  font-weight: 900;
  color: #1f66d8;
  background: #eff6ff;
  border: 1px solid #c9dcfb;
  border-radius: 7px;
  font-variant-numeric: tabular-nums;
}

.langgraph-cog-list div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.langgraph-cog-list strong,
.langgraph-cog-list p {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.langgraph-cog-list strong {
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  white-space: nowrap;
}

.langgraph-cog-list p {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #475569;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.langgraph-cog-list em {
  min-height: 22px;
  padding: 2px 7px;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  line-height: 18px;
  color: #1f66d8;
  white-space: nowrap;
  background: #eff6ff;
  border: 1px solid #c9dcfb;
  border-radius: 6px;
}

.langgraph-lane-list {
  display: grid;
  gap: 8px;
}

.langgraph-lane {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  min-width: 0;
  min-height: 58px;
  padding: 10px 11px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.langgraph-lane--blue {
  background: #f8fbff;
  border-color: #cbdcf8;
}

.langgraph-lane--green {
  background: #f2fbf6;
  border-color: #c9ead8;
}

.langgraph-lane--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.langgraph-lane--red {
  background: #fff4f3;
  border-color: #ffc8c1;
}

.langgraph-lane-main {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 2px 8px;
  min-width: 0;
  align-items: center;
}

.langgraph-lane-main span {
  grid-row: 1 / 3;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
  color: #1f66d8;
  background: #fff;
  border: 1px solid #c9dcfb;
  border-radius: 7px;
  font-variant-numeric: tabular-nums;
}

.langgraph-lane-main strong,
.langgraph-lane-main small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.langgraph-lane-main strong {
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
}

.langgraph-lane-main small {
  font-size: 12px;
  line-height: 17px;
  color: #64748b;
}

.langgraph-lane-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
  justify-content: flex-end;
  min-width: 108px;
}

.langgraph-lane-meta em {
  min-height: 20px;
  padding: 1px 6px;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  line-height: 18px;
  color: #475569;
  background: rgb(255 255 255 / 78%);
  border: 1px solid #dbe8f7;
  border-radius: 5px;
  font-variant-numeric: tabular-nums;
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
  transform: translateY(-1px);
  box-shadow: 0 12px 24px rgb(15 23 42 / 8%);
}

.workflow-card:focus-visible {
  outline: 3px solid rgb(37 99 235 / 20%);
  outline-offset: 2px;
}

.workflow-card.is-active {
  border-color: #2563eb;
  box-shadow:
    0 0 0 2px rgb(37 99 235 / 10%),
    0 12px 24px rgb(15 23 42 / 8%);
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
  background: rgb(37 99 235 / 7%);
  border-radius: 999px;
  content: '';
}

.workflow-card--green::after {
  background: rgb(22 163 74 / 8%);
}

.workflow-card--orange::after {
  background: rgb(217 119 6 / 9%);
}

.workflow-grid--tabs {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 14px;
}

.fde-dashboard-secondary {
  overflow: hidden;
}

.fde-dashboard-secondary .metric-grid {
  padding: 14px;
  margin-bottom: 0;
}

.metric-grid--secondary {
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}

.metric-grid--secondary .metric-card {
  min-height: 78px;
  padding: 12px;
}

.metric-grid--secondary .metric-card span {
  margin-bottom: 7px;
  font-size: 12px;
  line-height: 18px;
}

.metric-grid--secondary .metric-card strong {
  font-size: 22px;
  line-height: 28px;
}

.fde-dashboard-detail {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 14px;
  margin-bottom: 20px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 8px 18px rgb(15 23 42 / 4%);
}

.fde-dashboard-detail__header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.fde-dashboard-detail__header div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.fde-dashboard-detail__header span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.fde-dashboard-detail__header strong {
  min-width: 0;
  font-size: 18px;
  font-weight: 900;
  line-height: 26px;
  color: #172033;
}

.fde-dashboard-detail__header small {
  min-width: 0;
  font-size: 13px;
  line-height: 20px;
  color: #64748b;
}

.fde-tabs--single-route > :deep(.el-tabs__header) {
  display: none;
}

.panel {
  max-width: 100%;
  min-width: 0;
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

.panel-header--compact {
  min-height: 28px;
  margin-bottom: 10px;
}

.ocr-action-board {
  padding: 12px;
  background: #f8fbff;
  border: 1px solid #e3edf9;
  border-radius: 8px;
}

.ocr-action-board .project-subpage-kpis {
  margin-bottom: 10px;
}

.ocr-handoff {
  display: grid;
  gap: 8px;
  padding: 10px;
  margin-bottom: 10px;
  background: rgb(255 255 255 / 78%);
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.ocr-handoff__head,
.ocr-handoff__file {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.ocr-handoff__head strong,
.ocr-handoff__file strong {
  display: block;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-handoff__head span,
.ocr-handoff__head small,
.ocr-handoff__file span,
.ocr-handoff__file small {
  display: block;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-handoff__files {
  display: grid;
  gap: 6px;
}

.ocr-handoff__file {
  min-height: 44px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 6px;
}

.ocr-handoff__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  justify-content: flex-end;
}

.ocr-handoff__actions .el-button {
  min-width: 44px;
  min-height: 28px;
  padding: 0 8px;
}

.ocr-action-list {
  display: grid;
  gap: 8px;
}

.ocr-action-row {
  display: grid;
  grid-template-columns: 68px minmax(190px, 0.9fr) minmax(260px, 1.4fr) auto;
  gap: 10px;
  align-items: center;
  min-height: 42px;
  padding: 8px 10px;
  color: #334155;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.ocr-action-row strong,
.ocr-action-row span {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-action-row strong {
  font-weight: 800;
  color: #172033;
}

.ocr-action-row span {
  color: #64748b;
}

.ocr-action-row .el-button {
  min-width: 58px;
}

.fde-tabs {
  margin-top: 2px;
}

.fde-tabs :deep(.el-row) {
  max-width: 100%;
  min-width: 0;
  row-gap: 18px;
}

.fde-tabs :deep(.el-col) {
  max-width: 100%;
  min-width: 0;
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

.vector-file-chart-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.vector-file-chart-card {
  min-width: 0;
  border-radius: 8px;
}

.vector-file-pagination {
  justify-content: flex-end;
  margin-top: 12px;
}

.vector-file-blocker-list {
  display: grid;
  gap: 10px;
}

.vector-evidence-workbench {
  display: grid;
  grid-template-columns: minmax(320px, 0.85fr) minmax(560px, 1.25fr) minmax(280px, 0.65fr);
  gap: 14px;
  align-items: start;
}

.vector-source-preview-card,
.vector-evidence-detail-card {
  min-width: 0;
  border-radius: 8px;
}

.vector-card-header {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.vector-card-header strong,
.vector-card-header span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vector-card-header span {
  font-size: 12px;
  color: #64748b;
}

.vector-source-canvas {
  position: relative;
  display: grid;
  place-items: center;
  min-height: 520px;
  overflow: hidden;
  background: linear-gradient(90deg, rgb(37 99 235 / 5%) 1px, transparent 1px),
    linear-gradient(rgb(37 99 235 / 5%) 1px, transparent 1px), #f8fafc;
  background-size: 32px 32px;
  border: 1px solid #d7e2f1;
  border-radius: 8px;
}

.vector-source-media {
  width: 100%;
  height: 520px;
  background: #fff;
  border: 0;
  object-fit: contain;
}

.panel-title-alias {
  display: inline-flex;
  align-items: center;
  margin-left: 8px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #eef4ff;
  color: #5b6f91;
  font-size: 12px;
  font-weight: 600;
  vertical-align: middle;
}

.vector-source-placeholder {
  display: grid;
  gap: 8px;
  max-width: 82%;
  padding: 20px;
  text-align: center;
  background: #fff;
  border: 1px dashed #cbd8ea;
  border-radius: 8px;
}

.vector-source-placeholder strong,
.vector-source-placeholder span,
.vector-source-placeholder small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vector-source-placeholder strong {
  color: #172033;
}

.vector-source-placeholder span,
.vector-source-placeholder small {
  color: #64748b;
}

.vector-evidence-box {
  position: absolute;
  min-width: 28px;
  min-height: 22px;
  border: 2px solid #2563eb;
  border-radius: 4px;
  box-shadow: 0 0 0 9999px rgb(15 23 42 / 12%);
}

.vector-evidence-box span {
  position: absolute;
  top: -26px;
  left: -2px;
  padding: 2px 7px;
  font-size: 12px;
  font-weight: 800;
  color: #fff;
  white-space: nowrap;
  background: #2563eb;
  border-radius: 6px;
}

.vector-evidence-panels {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.vector-evidence-detail-card {
  position: sticky;
  top: 8px;
}

.vector-evidence-json {
  max-height: 300px;
  padding: 12px;
  margin: 12px 0 0;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  color: #172033;
  word-break: break-word;
  white-space: pre-wrap;
  background: #f8fafc;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.vector-pipeline-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.vector-pipeline-stage {
  min-width: 0;
  padding: 12px;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.vector-pipeline-stage span,
.vector-pipeline-stage strong,
.vector-pipeline-stage small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vector-pipeline-stage span {
  font-size: 12px;
  font-weight: 800;
  color: #64748b;
}

.vector-pipeline-stage strong {
  margin-top: 4px;
  font-size: 15px;
  color: #172033;
}

.vector-pipeline-stage small {
  margin-top: 3px;
  font-size: 12px;
  color: #64748b;
}

.vector-pipeline-two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.vector-pipeline-card {
  min-width: 0;
  border-radius: 8px;
}

.ocr-labeling-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
  gap: 14px;
  align-items: stretch;
  margin-bottom: 14px;
}

.ocr-labeling-hero--compact {
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
}

.ocr-labeling-hero-copy,
.ocr-labeling-primary-action {
  min-width: 0;
  padding: 16px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 22px rgb(15 23 42 / 4%);
}

.ocr-labeling-hero-copy {
  display: grid;
  gap: 7px;
  background: linear-gradient(180deg, rgb(248 251 255 / 96%), #fff),
    radial-gradient(circle at 20px 14px, rgb(37 99 235 / 10%), transparent 72px);
}

.ocr-labeling-hero-copy span,
.ocr-labeling-hero-copy strong,
.ocr-labeling-hero-copy small,
.ocr-labeling-primary-action span,
.ocr-labeling-primary-action strong,
.ocr-labeling-primary-action small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-labeling-hero-copy span,
.ocr-labeling-primary-action span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.ocr-labeling-hero-copy strong,
.ocr-labeling-primary-action strong {
  font-size: 18px;
  font-weight: 900;
  line-height: 25px;
  color: #172033;
}

.ocr-labeling-hero-copy small,
.ocr-labeling-primary-action small {
  font-size: 13px;
  line-height: 21px;
  color: #64748b;
  white-space: normal;
}

.ocr-labeling-primary-action {
  display: grid;
  gap: 8px;
  align-content: start;
}

.ocr-labeling-primary-action--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.ocr-labeling-primary-action--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.ocr-labeling-primary-action--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.ocr-labeling-primary-action--red {
  background: #fff3f1;
  border-color: #ffc9c3;
}

.ocr-labeling-mini-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.ocr-labeling-mini-flow span {
  display: inline-flex;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 12px;
  font-weight: 800;
  line-height: 18px;
  color: #52617a;
  background: #f8fafc;
  border: 1px solid #dbe8f7;
  border-radius: 999px;
  align-items: center;
}

.ocr-labeling-mini-flow span.done {
  color: #15803d;
  background: #eaf8ef;
  border-color: #bfe8ce;
}

.ocr-labeling-workflow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.ocr-labeling-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 9px;
  min-width: 0;
  min-height: 118px;
  padding: 12px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.ocr-labeling-step.done {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.ocr-labeling-step > span {
  display: inline-grid;
  width: 34px;
  height: 34px;
  font-size: 12px;
  font-weight: 900;
  color: #1d4ed8;
  background: #eef5ff;
  border: 1px solid #cfe0ff;
  border-radius: 8px;
  place-items: center;
}

.ocr-labeling-step.done > span {
  color: #15803d;
  background: #eaf8ef;
  border-color: #bfe8ce;
}

.ocr-labeling-step div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.ocr-labeling-step strong,
.ocr-labeling-step small,
.ocr-labeling-step em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-labeling-step strong {
  font-size: 14px;
  font-weight: 900;
  line-height: 20px;
  color: #172033;
  white-space: nowrap;
}

.ocr-labeling-step small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.ocr-labeling-step em {
  grid-column: 2;
  justify-self: start;
  min-height: 22px;
  padding: 2px 8px;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  line-height: 18px;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #dbe8f7;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

.ocr-labeling-main-grid {
  align-items: start;
}

.ocr-labeling-side-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.ocr-labeling-help-card,
.ocr-labeling-coverage-card,
.ocr-labeling-next-list {
  min-width: 0;
  padding: 14px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 4%);
}

.ocr-labeling-help-card {
  background: linear-gradient(180deg, #f8fbff, #fff);
}

.ocr-labeling-help-card > span {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 900;
  color: #172033;
}

.ocr-labeling-help-card ol {
  display: grid;
  gap: 7px;
  padding: 0 0 0 18px;
  margin: 0;
}

.ocr-labeling-help-card li {
  font-size: 12px;
  font-weight: 700;
  line-height: 19px;
  color: #52617a;
}

.ocr-labeling-coverage-card,
.ocr-labeling-next-list {
  display: grid;
  gap: 10px;
}

.ocr-labeling-coverage-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 48px;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.ocr-labeling-coverage-row span,
.ocr-labeling-coverage-row strong {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  color: #52617a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-labeling-coverage-row div {
  height: 10px;
  min-width: 0;
  overflow: hidden;
  background: #eef4fb;
  border-radius: 999px;
}

.ocr-labeling-coverage-row i {
  display: block;
  height: 100%;
  min-width: 4px;
  background: #2563eb;
  border-radius: inherit;
}

.ocr-labeling-next-list article {
  display: grid;
  gap: 4px;
  padding: 10px;
  background: #fff8ed;
  border: 1px solid #f6d6a5;
  border-radius: 8px;
}

.ocr-labeling-next-list strong,
.ocr-labeling-next-list small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ocr-labeling-next-list strong {
  font-size: 13px;
  font-weight: 900;
  line-height: 18px;
  color: #172033;
  white-space: nowrap;
}

.ocr-labeling-next-list small {
  display: -webkit-box;
  font-size: 12px;
  line-height: 18px;
  color: #64748b;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.ocr-labeling-diagnostics {
  margin-top: 16px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.ocr-labeling-diagnostics summary {
  display: flex;
  min-height: 48px;
  padding: 0 14px;
  list-style: none;
  cursor: pointer;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.ocr-labeling-diagnostics summary::-webkit-details-marker {
  display: none;
}

.ocr-labeling-diagnostics summary::after {
  font-size: 13px;
  font-weight: 900;
  color: #2563eb;
  content: '展开';
}

.ocr-labeling-diagnostics[open] summary {
  border-bottom: 1px solid #e6edf7;
}

.ocr-labeling-diagnostics[open] summary::after {
  content: '收起';
}

.ocr-labeling-diagnostics summary span {
  font-size: 14px;
  font-weight: 900;
  color: #172033;
}

.ocr-labeling-diagnostics summary small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 800;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-labeling-diagnostics :deep(.el-row) {
  padding: 14px;
}

.ocr-labeling-focus {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(250px, 0.72fr) minmax(190px, 0.32fr);
  gap: 12px;
  align-items: stretch;
  margin-bottom: 14px;
}

.ocr-labeling-focus-copy,
.ocr-labeling-focus-steps,
.ocr-labeling-focus-progress {
  min-width: 0;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 22px rgb(15 23 42 / 4%);
}

.ocr-labeling-focus-copy {
  display: grid;
  gap: 5px;
  background: linear-gradient(180deg, #f8fbff, #fff);
}

.ocr-labeling-focus-copy span,
.ocr-labeling-focus-progress span {
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #2563eb;
}

.ocr-labeling-focus-copy strong {
  font-size: 18px;
  font-weight: 900;
  line-height: 25px;
  color: #172033;
}

.ocr-labeling-focus-copy small,
.ocr-labeling-focus-progress small {
  font-size: 13px;
  font-weight: 700;
  line-height: 20px;
  color: #64748b;
}

.ocr-labeling-focus-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-content: center;
  background: #f8fafc;
}

.ocr-labeling-focus-steps span {
  display: inline-flex;
  min-height: 30px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 900;
  color: #475569;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 999px;
  align-items: center;
}

.ocr-labeling-focus-steps span.done {
  color: #15803d;
  background: #eaf8ef;
  border-color: #bfe8ce;
}

.ocr-labeling-focus-progress {
  display: grid;
  gap: 3px;
  align-content: center;
  text-align: right;
}

.ocr-labeling-focus-progress strong {
  font-size: 25px;
  font-weight: 950;
  line-height: 30px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.ocr-labeling-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
  gap: 16px;
  align-items: start;
}

.ocr-labeling-queue-panel {
  min-width: 0;
}

.ocr-labeling-task-list {
  display: grid;
  gap: 10px;
}

.ocr-labeling-task-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
  min-height: 74px;
  padding: 12px;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}

.ocr-labeling-task-card:hover,
.ocr-labeling-task-card.active {
  background: #f8fbff;
  border-color: #9fc5ff;
  box-shadow: 0 10px 24px rgb(37 99 235 / 8%);
}

.ocr-labeling-task-card--orange {
  border-left: 3px solid #f59e0b;
}

.ocr-labeling-task-card--green {
  border-left: 3px solid #16a34a;
}

.ocr-labeling-task-main,
.ocr-labeling-task-meta {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.ocr-labeling-task-main span,
.ocr-labeling-task-meta span {
  overflow: hidden;
  font-size: 12px;
  font-weight: 900;
  line-height: 18px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-labeling-task-main strong {
  overflow: hidden;
  font-size: 15px;
  font-weight: 950;
  line-height: 22px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-labeling-task-main small {
  overflow: hidden;
  font-size: 12px;
  font-weight: 750;
  line-height: 18px;
  color: #52617a;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ocr-labeling-task-meta {
  justify-items: end;
  text-align: right;
}

.ocr-labeling-task-meta strong {
  font-size: 18px;
  font-weight: 950;
  line-height: 24px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.ocr-labeling-action-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.ocr-labeling-action-card,
.ocr-labeling-plain-guide,
.ocr-labeling-mini-stats {
  min-width: 0;
  padding: 14px;
  background: #fff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 4%);
}

.ocr-labeling-action-card {
  display: grid;
  gap: 8px;
}

.ocr-labeling-action-card--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.ocr-labeling-action-card--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.ocr-labeling-action-card--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.ocr-labeling-action-card--red {
  background: #fff3f1;
  border-color: #ffc9c3;
}

.ocr-labeling-action-card span,
.ocr-labeling-plain-guide span,
.ocr-labeling-mini-stats span {
  font-size: 12px;
  font-weight: 900;
  color: #2563eb;
}

.ocr-labeling-action-card strong {
  font-size: 16px;
  font-weight: 950;
  line-height: 23px;
  color: #172033;
}

.ocr-labeling-action-card small {
  font-size: 12px;
  font-weight: 750;
  line-height: 19px;
  color: #64748b;
}

.ocr-labeling-plain-guide {
  display: grid;
  gap: 8px;
}

.ocr-labeling-plain-guide ol {
  display: grid;
  gap: 7px;
  padding-left: 18px;
  margin: 0;
}

.ocr-labeling-plain-guide li {
  font-size: 12px;
  font-weight: 760;
  line-height: 19px;
  color: #52617a;
}

.ocr-labeling-mini-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ocr-labeling-mini-stats article {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 10px;
  text-align: center;
  background: #f8fafc;
  border: 1px solid #e6edf7;
  border-radius: 8px;
}

.ocr-labeling-mini-stats strong {
  font-size: 20px;
  font-weight: 950;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.ocr-labeling-coverage-card--flat {
  padding: 0;
  border: 0;
  box-shadow: none;
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

.gate-summary-item .gate-status-pill {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 2px 8px;
  align-items: center;
  width: 100%;
  min-height: 46px;
  padding: 9px 11px;
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.25;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 65%);
}

.gate-summary-item .gate-status-pill i {
  width: 9px;
  height: 9px;
  border-radius: 999px;
}

.gate-summary-item .gate-status-pill span {
  display: block;
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 850;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gate-summary-item .gate-status-pill small {
  display: block;
  grid-column: 2;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 650;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.78;
}

.gate-summary-item .gate-status-pill--success {
  color: #047857;
  background: #ecfdf3;
  border: 1px solid #a7f3d0;
}

.gate-summary-item .gate-status-pill--success i {
  background: #10b981;
}

.gate-summary-item .gate-status-pill--danger {
  color: #b42318;
  background: #fff1f0;
  border: 1px solid #fecaca;
}

.gate-summary-item .gate-status-pill--danger i {
  background: #ef4444;
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

  .agent-status-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  }

  .audit-flow-strip {
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  }

  .vector-quality-board {
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  }

  .technology-stack-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .ocr-labeling-workflow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ocr-labeling-focus,
  .ocr-labeling-workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-labeling-focus-progress {
    text-align: left;
  }

  .lineage-document-grid,
  .pageindex-friendly-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ocr-step-grid,
  .ocr-command-kpis,
  .workflow-grid--tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lineage-document-intro,
  .pageindex-friendly-intro {
    grid-column: 1 / -1;
  }
}

@media (width <= 1180px) {
  .project-overview-command-grid,
  .project-overview-governance-grid,
  .project-audit-health-grid,
  .project-audit-node-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
  }

  .ocr-capability-layout,
  .ocr-capability-result {
    grid-template-columns: minmax(0, 1fr);
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

  .project-overview-capability-item {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .project-overview-capability-item small {
    grid-column: 1 / -1;
  }

  .project-overview-node-status-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 6px 10px;
  }

  .project-overview-node-status-row > span {
    text-align: left;
  }

  .project-overview-node-status-track {
    grid-column: 1 / -1;
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

  .agent-status-panel,
  .fde-dashboard-detail__header {
    grid-template-columns: minmax(0, 1fr);
  }

  .fde-dashboard-detail__header :deep(.el-button) {
    justify-self: start;
  }

  .ocr-online-entry {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-online-entry :deep(.el-button) {
    justify-self: start;
  }

  .workbench-summary-grid.project-subpage-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ocr-command-kpis,
  .ocr-step-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ocr-capability-hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-capability-hero .el-space {
    justify-content: flex-start;
  }

  .ocr-capability-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .audit-flow-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .vector-quality-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .technology-stack-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .vector-lineage-intro {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-labeling-hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-labeling-task-card {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
  }

  .ocr-labeling-task-meta {
    justify-items: start;
    text-align: left;
  }

  .lineage-document-grid,
  .pageindex-friendly-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .lineage-document-intro,
  .pageindex-friendly-intro {
    grid-column: auto;
  }

  .lineage-document-card__head,
  .pageindex-friendly-card__head {
    grid-template-columns: minmax(0, 1fr);
  }

  .pageindex-friendly-card__head > span {
    display: none;
  }

  .pageindex-friendly-facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .annotation-canvas {
    min-height: 360px;
  }

  .annotation-item {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-action-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-action-row strong,
  .ocr-action-row span {
    white-space: normal;
  }

  .ocr-handoff__head,
  .ocr-handoff__file {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-handoff__head strong,
  .ocr-handoff__head span,
  .ocr-handoff__head small,
  .ocr-handoff__file strong,
  .ocr-handoff__file span,
  .ocr-handoff__file small {
    white-space: normal;
  }

  .ocr-handoff__actions {
    justify-content: flex-start;
  }

  .audit-drawer-hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .vector-file-chart-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .vector-pipeline-strip,
  .vector-pipeline-two-col,
  .vector-evidence-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .vector-evidence-detail-card {
    position: static;
  }

  .vector-source-canvas,
  .vector-source-media {
    height: 360px;
    min-height: 360px;
  }
}

@media (width <= 520px) {
  .metric-grid,
  .gate-summary,
  .artifact-summary-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .audit-flow-strip {
    grid-template-columns: minmax(0, 1fr);
  }

  .vector-quality-board {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-labeling-workflow {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-labeling-focus-steps,
  .ocr-labeling-mini-stats {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-online-entry :deep(.el-button) {
    width: 100%;
  }

  .ocr-command-kpis,
  .ocr-step-grid,
  .agent-status-tabs,
  .workflow-grid--tabs {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-status-tabs__header {
    grid-template-columns: minmax(0, 1fr);
  }

  .ocr-capability-kpis {
    grid-template-columns: minmax(0, 1fr);
  }

  .pageindex-friendly-facts {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
