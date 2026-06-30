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
  importFdeOcrAnnotationPackApi,
  getFdeReleaseImpactApi,
  getFdeReviewRunApi,
  installFdeBusinessPackApi,
  listFdeAcceptanceReportsApi,
  listFdeAccessGrantsApi,
  listFdeAiRunsApi,
  listFdeFeedbackApi,
  listFdeIncidentsApi,
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

const routeTabMap: Record<string, string> = {
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
  dashboard: '/fde/dashboard',
  runs: '/fde/ai-runs',
  orchestration: '/fde/review-runs',
  feedback: '/fde/feedback',
  release: '/fde/capability-bundles',
  delivery: '/fde/ocr-quality'
}

const fdeShellMenuSectionsBase = [
  {
    title: '运行监控',
    meta: '3页',
    items: [
      { index: '01', label: 'AI 驾驶舱', badge: '总览', tone: 'blue', route: '/fde/dashboard' },
      { index: '02', label: 'AI Run 追踪', badge: 'Trace', tone: 'blue', route: '/fde/ai-runs' },
      {
        index: '03',
        label: '任务编排',
        badge: '链路',
        tone: 'green',
        route: '/fde/review-runs'
      }
    ]
  },
  {
    title: '评估与发布',
    meta: '4页',
    items: [
      { index: '04', label: '反馈与标注', badge: '样本', tone: 'orange', route: '/fde/feedback' },
      { index: '05', label: '评估实验室', badge: '门禁', tone: 'green', route: '/fde/evaluation' },
      {
        index: '06',
        label: '能力组合',
        badge: 'Bundle',
        tone: 'blue',
        route: '/fde/capability-bundles'
      },
      { index: '07', label: '发布治理', badge: '灰度', tone: 'orange', route: '/fde/releases' }
    ]
  },
  {
    title: '交付治理',
    meta: '6页',
    items: [
      { index: '08', label: 'OCR 质量', badge: '识别', tone: 'green', route: '/fde/ocr-quality' },
      {
        index: '09',
        label: '业务包工厂',
        badge: '复用',
        tone: 'blue',
        route: '/fde/business-packs'
      },
      { index: '10', label: '数据安全', badge: '脱敏', tone: 'red', route: '/fde/security' },
      { index: '11', label: '事故 RCA', badge: '处置', tone: 'orange', route: '/fde/incidents' },
      { index: '12', label: '成本预算', badge: '预算', tone: 'blue', route: '/fde/costs' },
      { index: '13', label: '交付验收', badge: '客户', tone: 'green', route: '/fde/acceptance' }
    ]
  }
] as const

const fdeShellBoundaryRows = [
  { label: '职责', value: 'AI 交付、监控、评估与发布治理' },
  { label: '数据', value: '默认脱敏查看，原文访问需授权留痕' },
  { label: '发布', value: '可发起评估、Shadow、灰度和回滚申请' },
  { label: '边界', value: '不审批资料、不发补正、不改项目最终状态' }
] as const

const syncTabFromRoute = () => {
  const segment = String(route.path.split('/').filter(Boolean).pop() || 'dashboard')
  activeFdeTab.value = routeTabMap[segment] || 'dashboard'
}

const fdeShellMenuSections = computed(() =>
  fdeShellMenuSectionsBase.map((section) => ({
    ...section,
    items: section.items.map((item) => ({
      ...item,
      active: item.route === route.path
    }))
  }))
)
const currentFdeRouteContext = computed(() => {
  for (const section of fdeShellMenuSectionsBase) {
    const item = section.items.find((candidate) => candidate.route === route.path)
    if (item) {
      return {
        group: section.title,
        label: item.label,
        badge: item.badge,
        tone: item.tone
      }
    }
  }
  return {
    group: '运行监控',
    label: 'AI 驾驶舱',
    badge: '总览',
    tone: 'blue'
  }
})
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

const statusType = (status?: string) => {
  if (!status) return 'info'
  if (
    [
      '完成',
      'completed',
      'production',
      'production_approved',
      'accepted',
      'active',
      'passed'
    ].includes(status)
  ) {
    return 'success'
  }
  if (['失败', 'failed', 'blocked_by_gate', 'rejected'].includes(status)) return 'danger'
  if (['queued', 'submitted', 'monitoring', '排队中'].includes(status)) return 'warning'
  return 'info'
}

const recordNumber = (record: Record<string, unknown> | undefined, key: string) => {
  const value = Number(record?.[key] || 0)
  return Number.isNaN(value) ? 0 : value
}

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
const reviewFindingDraftRows = computed(() => reviewGraphArtifacts.value.findingDrafts || [])
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

const fdeTopStats = computed(() => [
  { label: '告警', value: dashboard.value?.alerts?.length || 0, tone: 'orange' as const },
  { label: '事故', value: incidents.value.length || 0, tone: 'red' as const }
])

const fdeShellRightCards = computed(() => [
  {
    title: '治理快照',
    rows: [
      {
        label: '服务状态',
        value: loading.value ? '加载中' : '在线',
        valueBadge: error.value ? '异常' : '正常',
        valueTone: error.value ? ('red' as const) : ('green' as const)
      },
      { label: 'AI Run', value: String(aiRuns.value.length) },
      { label: 'Review Run', value: String(reviewRuns.value.length) },
      { label: '人工反馈', value: String(feedback.value.length) }
    ]
  },
  {
    title: '发布与评估',
    rows: [
      { label: '能力组合', value: String(bundles.value?.bundles?.length || 0) },
      { label: '发布计划', value: String(releases.value?.plans?.length || 0) },
      { label: '评估集', value: String(evaluation.value?.sets?.length || 0) },
      { label: '验收报告', value: String(acceptanceReports.value.length) }
    ]
  },
  {
    title: 'OCR 质量',
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
    title: '权限边界',
    note: 'FDE 管理 AI 能力、交付质量和发布治理；正式业务结论仍由业务角色确认。'
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
      maskingRes
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
      getFdeMaskingPoliciesApi()
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
    if (firstEvaluationRunId.value) {
      await loadEvaluationReportDetail(firstEvaluationRunId.value)
    } else {
      selectedEvaluationReport.value = null
    }
    if (firstOcrJobId.value) {
      await loadOcrRunDetail(firstOcrJobId.value)
    }
    if (activeBundleId.value) {
      await loadCapabilityBundleDiff(activeBundleId.value)
    }
    if (activeReleaseId.value) {
      await loadReleaseImpact(activeReleaseId.value)
    }
    if (activeBusinessPackId.value) {
      await loadBusinessPackDiff(activeBusinessPackId.value)
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
  const res = await getFdeReviewRunApi(reviewRunId)
  selectedReviewRun.value = res.data
}

const loadOcrRunDetail = async (jobId: string) => {
  const res = await getFdeOcrRunApi(jobId)
  selectedOcrRun.value = res.data
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

watch(
  () => route.path,
  () => syncTabFromRoute(),
  { immediate: true }
)

watch(activeFdeTab, (tab) => {
  const segment = String(route.path.split('/').filter(Boolean).pop() || 'dashboard')
  if (routeTabMap[segment] === tab) return
  const target = fdeTabRouteMap[tab]
  if (target && route.path !== target) {
    router.push(target)
  }
})

onMounted(loadData)
</script>

<template>
  <StaticPageShell
    brand-mark="F"
    title="FDE 后台"
    status="AI 治理"
    status-tone="blue"
    search-placeholder="⌕ 搜索（AI Run / Agent / 评估集 / 发布单 / 业务包）"
    user-label="FDE 工程师"
    :top-stats="fdeTopStats"
    menu-title="FDE 菜单"
    menu-root="AI Delivery & Governance"
    :menu-sections="fdeShellMenuSections"
    boundary-title="职责边界"
    boundary-badge="不办业务审批"
    boundary-tone="green"
    :boundary-rows="fdeShellBoundaryRows"
    right-title="治理摘要"
    right-subtitle="Capability Bundle / OCR / Release"
    :right-cards="fdeShellRightCards"
    workspace-mode="wide"
  >
    <div class="fde-console" v-loading="loading">
      <div class="page-toolbar">
        <div>
          <div class="page-title">AI 交付治理后台</div>
          <div class="page-subtitle">AI Run、Agent 绩效、OCR 质量、评估发布与交付验收</div>
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
        </div>
        <ElSpace wrap>
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

      <div class="metric-grid">
        <div
          v-for="metric in dashboardMetricCards"
          :key="metric.label"
          :class="`metric-card metric-card--${metric.tone}`"
        >
          <span>{{ metric.label }}</span>
          <strong>{{ metric.suffix === '%' ? percent(metric.value) : metric.value }}</strong>
        </div>
      </div>

      <ElTabs v-model="activeFdeTab" class="fde-tabs">
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
                    {{ dashboard?.cost.budgetStatus || '-' }}
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
                      <ElTag :type="statusType(row.status)" effect="plain">{{ row.status }}</ElTag>
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
              <ElCard shadow="never" class="panel">
                <template #header>评估报告门禁</template>
                <ElDescriptions v-if="latestEvaluationReport" :column="1" border>
                  <ElDescriptionsItem label="状态">
                    <ElTag :type="statusType(latestEvaluationReport.status)" effect="plain">
                      {{ latestEvaluationReport.status }}
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
          <ElRow :gutter="16">
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
                  :data="reviewRuns"
                  border
                  height="360"
                  @row-click="(row) => loadReviewRunDetail(String(row.reviewRunId || row.id))"
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
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="currentStep"
                    label="当前步骤"
                    min-width="150"
                    show-overflow-tooltip
                  />
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
                          {{ row.status }}
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
                  <ElTableColumn prop="status" label="节点状态" />
                  <ElTableColumn prop="count" label="数量" width="90" />
                </ElTable>
                <ElEmpty v-if="!selectedReviewRun" description="请选择 ReviewRun" />
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
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
                        {{ row.status }}
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
                        {{ row.status }}
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
                        {{ row.result }}
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
                <ElTable :data="reviewFindingDraftRows" border height="260">
                  <ElTableColumn prop="id" label="Draft" min-width="145" show-overflow-tooltip />
                  <ElTableColumn
                    prop="findingType"
                    label="类型"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="severity" label="等级" width="90" />
                  <ElTableColumn label="置信度" width="90">
                    <template #default="{ row }">{{ scorePercent(row.confidence) }}</template>
                  </ElTableColumn>
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Capability Bundle</template>
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>Capability Bundle 差异</template>
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>OCR 质量</span>
                    <ElSpace>
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
                    · {{ percent(ocrQuality.cacheMetrics?.engineCacheHitRate) }}</ElDescriptionsItem
                  >
                  <ElDescriptionsItem label="候选缓存"
                    >{{ ocrQuality.cacheMetrics?.variantCacheHits || 0 }}/{{
                      ocrQuality.cacheMetrics?.engineRunCount || 0
                    }}
                    ·
                    {{ percent(ocrQuality.cacheMetrics?.variantCacheHitRate) }}</ElDescriptionsItem
                  >
                  <ElDescriptionsItem label="引擎耗时"
                    >{{ ocrQuality.cacheMetrics?.totalDurationMs || 0 }} ms</ElDescriptionsItem
                  >
                  <ElDescriptionsItem label="运行时">
                    <ElTag :type="ocrRuntimeDoctor?.ok ? 'success' : 'warning'" effect="plain">
                      {{ ocrRuntimeDoctor?.status || 'unknown' }}
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
                      <strong>{{ ocr100Scorecard.score }}/{{ ocr100Scorecard.targetScore }}</strong>
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
                          <template #default="{ row }">{{ row.score }}/{{ row.maxScore }}</template>
                        </ElTableColumn>
                        <ElTableColumn prop="status" label="状态" width="95">
                          <template #default="{ row }">
                            <ElTag
                              :type="row.status === 'pass' ? 'success' : 'danger'"
                              effect="plain"
                            >
                              {{ row.status }}
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
                <div class="sub-section mt-12px">
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
                            <ElTag :type="statusType(String(row.collectionStatus))" effect="plain">
                              {{ row.collectionStatus || '-' }}
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
                <ElTable
                  :data="ocrRuns"
                  border
                  height="220"
                  class="mt-12px"
                  @row-click="(row) => loadOcrRunDetail(String(row.id || row.jobId))"
                >
                  <ElTableColumn prop="id" label="Job" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="95">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">{{
                        row.status
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="profileId"
                    label="Profile"
                    min-width="140"
                    show-overflow-tooltip
                  />
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
                  <ElTableColumn prop="engine" label="引擎" min-width="180" show-overflow-tooltip />
                  <ElTableColumn prop="status" label="状态" width="90">
                    <template #default="{ row }">
                      <ElTag :type="statusType(String(row.status))" effect="plain">{{
                        row.status
                      }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="durationMs" label="耗时" width="95" />
                  <ElTableColumn label="缓存" width="120">
                    <template #default="{ row }">
                      <ElSpace size="small">
                        <ElTag v-if="row.engineCacheHit" size="small" type="success" effect="plain">
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
              </ElCard>
            </ElCol>
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>事故与验收</span>
                    <ElSpace>
                      <ElButton size="small" plain :loading="actionLoading" @click="updateFirstRca">
                        更新 RCA
                      </ElButton>
                      <ElButton
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
              </ElCard>
            </ElCol>
          </ElRow>
          <ElRow :gutter="16" class="mt-16px">
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
          <ElRow :gutter="16" class="mt-16px">
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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
            <ElCol :xl="24" :lg="24" :md="24" :sm="24" :xs="24">
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

.panel {
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
  row-gap: 18px;
}

.fde-tabs :deep(.el-tabs__header) {
  padding: 4px;
  margin: 0 0 20px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
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

@media (width <= 768px) {
  .page-toolbar {
    grid-template-columns: minmax(0, 1fr);
  }

  .metric-grid,
  .gate-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .annotation-canvas {
    min-height: 360px;
  }

  .annotation-item {
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
