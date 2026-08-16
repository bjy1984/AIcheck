<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElIcon,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElPagination,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSkeleton,
  ElTable,
  ElTableColumn,
  ElTreeV2
} from 'element-plus'
import {
  ArrowLeft,
  Document,
  DocumentChecked,
  FolderOpened,
  Guide,
  MagicStick,
  View
} from '@element-plus/icons-vue'
import {
  adoptAiSuggestionApi,
  archiveReportApi,
  bindDocumentsToNodeApi,
  bindInspectionDocumentsApi,
  completeTodoApi,
  completeDocumentUploadSessionApi,
  completeNdtReportUploadSessionApi,
  confirmNodeEvidenceLinkApi,
  createNdtFilmApi,
  createDocumentUploadSessionApi,
  createInspectionAttachmentUploadSessionApi,
  createNdtReportUploadSessionApi,
  deleteProjectDocumentApi,
  getArchivePackageApi,
  getArchiveItemDetailApi,
  getDocumentDetailApi,
  getDocumentOriginalBlobApi,
  getEvidencePackageApi,
  getExportTaskApi,
  getInspectionDateCompareApi,
  getInspectionAuditOverviewApi,
  getInspectionSubmittedDocumentsApi,
  getInspectionAuditWorkspaceApi,
  getActiveReviewHumanInputTaskApi,
  getNdtInspectionFeedbackDetailApi,
  getNdtReportDetailApi,
  getReportDetailApi,
  exportReportApi,
  importNdtRecordsApi,
  generateReportReviewApi,
  getNodePackageApi,
  getNodeLiveStatusApi,
  getProjectTreeApi,
  getSubmissionDetailApi,
  getSubmissionDraftDetailApi,
  getWorkbenchContextApi,
  getWorkbenchSummaryApi,
  listNdtFilmsApi,
  listNdtInspectionFeedbackApi,
  listNdtRecordsApi,
  listNdtReportsApi,
  listOwnerReportsApi,
  listProjectArchiveApi,
  listInspectionStandardsApi,
  listSubmissionHistoryApi,
  listWorkbenchProjectsApi,
  listMessagesApi,
  listTodosApi,
  markAllMessagesReadApi,
  markMessageReadApi,
  rejectAiSuggestionApi,
  rejectNodeEvidenceLinkApi,
  retryDocumentUploadApi,
  requestAiRecheckApi,
  returnCorrectionApi,
  saveReviewOpinionApi,
  saveSubmissionDraftApi,
  searchApi,
  replaceNdtAtomicMaterialBindingsApi,
  submitNdtAtomicMaterialApi,
  submitNdtRectificationApi,
  submitInspectionDocumentBindingsApi,
  submitNodePackageApi,
  submitRectificationApi,
  submitReviewHumanInputResponseApi,
  updateReportApi
} from '@/api/aicheck'
import type {
  ArchiveItemDetailPayload,
  DateComparisonItem,
  DocumentDetailPayload,
  DocumentPreviewPayload,
  NdtFeedbackDetailPayload,
  NdtReportDetailPayload,
  NdtReportUploadRequest,
  ProjectTreePayload,
  R12LicenseCandidate,
  R12RegistryVerificationInput,
  R19EvidenceCandidate,
  R19HumanInputAnswer,
  ReportDetailPayload,
  ReportSection,
  StandardReference,
  SubmissionDetailPayload,
  SubmissionDraftDetailPayload,
  SubmissionDraftSummary,
  SubmissionSummary,
  UploadSessionPayload,
  ReviewHumanInputTask
} from '@/api/aicheck'
import type {
  ActionCode,
  ArchiveItem,
  AiReviewRun,
  EvidenceLink,
  ExportTask,
  InspectionAuditItem,
  InspectionAuditItemKey,
  InspectionAuditOverviewPayload,
  InspectionSubmittedDocumentsPayload,
  InspectionAuditWorkspacePayload,
  NdtFeedback,
  NdtFilm,
  NdtSubmissionReadiness,
  NdtRecord,
  NdtReport,
  NodeFileBinding,
  NodePackagePayload,
  Project,
  ProjectTreeNode,
  ReportVersion,
  ReviewOpinion,
  RoleCode,
  SearchResult,
  TodoItem,
  MessageItem,
  WorkbenchContextPayload,
  WorkbenchSummaryPayload
} from '@/types/aicheck'
import { getAicheckErrorMessage, getLatestAicheckBusinessError } from '@/utils/aicheckError'
import { buildDocumentSubmissionPayload, documentBindingSummary } from '@/utils/acceptanceFlows'
import { getAicheckRoleLabel } from '@/utils/roleAccess'

type InspectionNodeSortKey = 'review' | 'nodeId' | 'material'
type SortDirection = 'asc' | 'desc'
type InspectionReviewProgressLabel = '未提交' | '待审查' | '未补正' | '已通过'
type NodeRequirementDisplayRow = {
  id: string
  rowNo: number
  name: string
  requiredType: string
  materialType: string
  responsibleParty: string
  applicability: string
  matchedFileNames: string[]
  status: string
  supportStatus?: string
  matchedLinkCount: number
}
type AiExecutionDisplayStep = {
  title: string
  input: string
  feedback: string
  tools: string[]
  evidenceLinks: EvidenceLink[]
  status: string
}
type ReviewConclusionPoint = {
  order: string
  title: string
  conclusion: string
  description: string
  evidenceLinks: EvidenceLink[]
}
type EvidenceConfirmationRow = {
  id: string
  requirementId: string
  requirementName: string
  materialType: string
  status: string
  fileName: string
  evidenceText: string
  confidenceText: string
  evidence?: EvidenceLink
}
import AuditSummaryGrid, { type AuditSummaryCard } from './components/AuditSummaryGrid.vue'
import AuditStatusTag, { type AuditStatusTone } from './components/AuditStatusTag.vue'
import AiReviewRunAlerts from './components/AiReviewRunAlerts.vue'
import ArchiveDetailDrawer from './components/ArchiveDetailDrawer.vue'
import DocumentBindDialog from './components/DocumentBindDialog.vue'
import EvidenceLocatorDialog from './components/EvidenceLocatorDialog.vue'
import ExportTaskDrawer from './components/ExportTaskDrawer.vue'
import FileTypeIcon from './components/FileTypeIcon.vue'
import FileDetailDialog from './components/FileDetailDialog.vue'
import GlobalQuickAccessDialog from './components/GlobalQuickAccessDialog.vue'
import NdtDetailDrawer from './components/NdtDetailDrawer.vue'
import NdtReportUploadDrawer from './components/NdtReportUploadDrawer.vue'
import NdtWorkflowPanel from './components/NdtWorkflowPanel.vue'
import NodePackagePanel from './components/NodePackagePanel.vue'
import ProjectNodeTree from './components/ProjectNodeTree.vue'
import RectificationDetailDialog from './components/RectificationDetailDialog.vue'
import R12RegistryVerificationDialog from './components/R12RegistryVerificationDialog.vue'
import R19SemanticEvidenceDialog from './components/R19SemanticEvidenceDialog.vue'
import ReportArchivePanel from './components/ReportArchivePanel.vue'
import ReportDetailDrawer from './components/ReportDetailDrawer.vue'
import ReviewDecisionPanel from './components/ReviewDecisionPanel.vue'
import RoleContextPanel from './components/RoleContextPanel.vue'
import SubmissionBatchDialog from './components/SubmissionBatchDialog.vue'
import SubmissionDetailDrawer from './components/SubmissionDetailDrawer.vue'
import SubmissionHistoryDrawer from './components/SubmissionHistoryDrawer.vue'
import UploadSessionDrawer from './components/UploadSessionDrawer.vue'
import { NDT_NODE_IDS, type NdtAtomicMaterial } from '@/utils/ndtAtomicMaterials'
import WorkbenchActionBar from './components/WorkbenchActionBar.vue'
import WorkbenchRoleStaticSections from './components/WorkbenchRoleStaticSections.vue'
import WorkbenchRightStaticDetails from './components/WorkbenchRightStaticDetails.vue'
import WorkbenchSidePanel from './components/WorkbenchSidePanel.vue'
import WorkbenchStateBanner from './components/WorkbenchStateBanner.vue'
import AuditItemDirectory from './components/AuditItemDirectory.vue'
import ConversationalReviewWorkbenchB from '@/views/AIReviewB/ConversationalReviewWorkbenchB.vue'
import { useUserStore } from '@/store/modules/user'
import { formatConfidence } from '@/utils/confidence'
import { parseAiFindings } from '@/utils/aiFindings'
import { removeProjectFileLocally, restoreProjectFileLocally } from './projectFileDeletion'
import { resolveInspectionWorkspaceView } from './inspectionWorkspaceView'
import { aggregateNodeStatus, nodeNeedsAttention } from './nodeAggregateStatus'
import { type InspectionWorkspaceView } from './inspectionWorkspaceView'
import { loadRoleScopedReportArchive } from './workbenchRoleAccess'

type PreviewDrawerTarget = {
  source: 'node' | 'file' | 'standard' | 'report' | 'archive'
  title: string
  url?: string
  meta?: string
  previewType?: DocumentPreviewPayload['previewType']
}

const roleConfig: Record<RoleCode, { title: string; subtitle: string }> = {
  inspection: { title: '监检工作台', subtitle: '资料审查、AI 复核、补正闭环' },
  contractor: { title: '施工方工作台', subtitle: '施工资料上传、项目文件库、补正反馈' },
  ndt: { title: '无损检测工作台', subtitle: '检测资料上传、资料库、补正反馈' },
  owner: { title: '建设方工作台', subtitle: '项目进度、报告与归档资料查看' },
  admin: { title: '管理工作台', subtitle: '系统配置与审计' },
  fde: { title: 'FDE 后台', subtitle: 'AI 交付、效果监控与治理' }
}

type WorkbenchStateIssue = {
  type: 'error' | 'forbidden' | 'readonly' | 'empty'
  title: string
  message?: string
}
type OperationBlocker = {
  title: string
  message?: string
  reasons: string[]
}
type AiReviewMode = 'formal' | 'gap_precheck'
type StandardReferenceItem = {
  reference: string
  file?: string
  fileName?: string
  knowledgeFileId?: string
  sourceRelativePath?: string
  previewAvailable?: boolean
  previewUrl?: string
}
type StandardReferenceTreeNode = {
  id: string
  label: string
  kind: 'root' | 'group' | 'file'
  reference?: string
  fileName?: string
  sourceRelativePath?: string
  knowledgeFileId?: string
  previewAvailable?: boolean
  previewUrl?: string
  children?: StandardReferenceTreeNode[]
}

type DocumentUploadTarget = UploadSessionPayload['uploadUrls'][number]
type LoadProjectBundleOptions = {
  silent?: boolean
  preserveSelection?: boolean
}
type LoadNodePackageOptions = {
  silent?: boolean
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const nodeLoading = ref(false)
const actionLoading = ref(false)
const pageIssue = ref<WorkbenchStateIssue>()
const nodeIssue = ref<WorkbenchStateIssue>()
const projectOptions = ref<Project[]>([])
const activeProjectId = ref('')
const activeNodeId = ref(24)
const activeWorkbenchSection = ref<'overview' | 'node'>('overview')
const activeInspectionWorkspaceView = ref<InspectionWorkspaceView>(
  resolveInspectionWorkspaceView(route.query.view)
)
const workbenchMainRef = ref<HTMLElement>()
const workbenchPageTransitionPhase = ref<'idle' | 'leaving' | 'hidden' | 'entering'>('idle')
let workbenchPageTransitionTimer: number | undefined
let workbenchPageTransitionSequence = 0
const activeInspectionAuditItem = ref<InspectionAuditItemKey>('submission')
const inspectionAuditOverview = ref<InspectionAuditOverviewPayload>()
const inspectionSubmittedDocuments = ref<InspectionSubmittedDocumentsPayload>()
const inspectionAuditWorkspace = ref<InspectionAuditWorkspacePayload>()
const inspectionAuditLoading = ref(false)
const inspectionAuditIssue = ref<WorkbenchStateIssue>()
const inspectionAuditItemByNode = ref<Record<number, InspectionAuditItemKey>>({})
const inspectionRouteSyncing = ref(false)
const context = ref<WorkbenchContextPayload>()
const summary = ref<WorkbenchSummaryPayload>()
const treeGroups = ref<ProjectTreePayload['groups']>([])
const nodePackage = ref<NodePackagePayload>()
const reports = ref<ReportVersion[]>([])
const archiveItems = ref<ArchiveItem[]>([])
const ndtFilms = ref<NdtFilm[]>([])
const ndtRecords = ref<NdtRecord[]>([])
const ndtReports = ref<NdtReport[]>([])
const ndtFeedback = ref<NdtFeedback[]>([])
const ndtFilmError = ref('')
const ndtRecordImportError = ref('')
const ndtReportUploadError = ref('')
const ndtSubmitError = ref('')
const ndtRectifyError = ref('')
const ndtReadiness = ref<NdtSubmissionReadiness>()
const actionBlocker = ref<OperationBlocker>()
const activeSideTab = ref('ai')
const previewDrawerVisible = ref(false)
const previewDrawerTarget = ref<PreviewDrawerTarget>({
  source: 'node',
  title: '当前节点资料预览'
})
const previewDrawerObjectUrl = ref('')
const previewDrawerLoadingOriginal = ref(false)
const previewDrawerOriginalError = ref('')
const uploadDrawerVisible = ref(false)
const uploadDrawerError = ref('')
const uploadDrawerMaterialCategory = ref('')
/** 替换目标。有值时这次上传是「给这份资料出新版本」，不是新建一份。 */
const uploadDrawerReplaceTarget = ref<{ documentId: string; fileName: string } | null>(null)
const uploadDrawerAtomicMaterial = ref<NdtAtomicMaterial>()
const uploadDrawerMode = ref<'project' | 'inspection'>('project')
const ndtReportUploadVisible = ref(false)
const bindDialogVisible = ref(false)
const bindDialogError = ref('')
const bindDialogDocumentId = ref('')
const submissionDialogVisible = ref(false)
const submissionDialogError = ref('')
const submissionHistoryVisible = ref(false)
const submissionHistoryLoading = ref(false)
const evidenceDialogVisible = ref(false)
const rectificationDialogVisible = ref(false)
const activeRectificationId = ref('')
const fileDetailVisible = ref(false)
const fileDetailLoading = ref(false)
const submissionDetailVisible = ref(false)
const submissionDetailLoading = ref(false)
const inspectionDetailLoading = ref(false)
const reportDetailVisible = ref(false)
const reportDetailLoading = ref(false)
const reportDetailError = ref('')
const ndtDetailVisible = ref(false)
const ndtDetailLoading = ref(false)
const ndtDetailMode = ref<'report' | 'feedback'>('report')
const archiveDetailVisible = ref(false)
const archiveDetailLoading = ref(false)
const archiveDetailError = ref('')
const exportTaskVisible = ref(false)
const exportTaskLoading = ref(false)
const exportTaskError = ref('')
const quickAccessVisible = ref(false)
const quickAccessTab = ref<'search' | 'todos' | 'messages'>('search')
const quickAccessKeyword = ref('')
const quickAccessLoading = ref(false)
const quickSearchResults = ref<SearchResult[]>([])
const quickTodos = ref<TodoItem[]>([])
const quickMessages = ref<MessageItem[]>([])
const activeEvidence = ref<EvidenceLink>()
const fileDetail = ref<DocumentDetailPayload>()
const submissionDetail = ref<SubmissionDraftDetailPayload | SubmissionDetailPayload>()
const restoredSubmissionDraft = ref<SubmissionDraftDetailPayload>()
const submissionDrafts = ref<SubmissionDraftSummary[]>([])
const submissionSnapshots = ref<SubmissionSummary[]>([])
const standardReferences = ref<StandardReference[]>([])
const dateComparisons = ref<DateComparisonItem[]>([])
const reportDetail = ref<ReportDetailPayload>()
const ndtReportDetail = ref<NdtReportDetailPayload>()
const ndtFeedbackDetail = ref<NdtFeedbackDetailPayload>()
const archiveDetail = ref<ArchiveItemDetailPayload>()
const exportTask = ref<ExportTask>()
const recentReadOnlyExportTasks = ref<ExportTask[]>([])
const activeReportDetailId = ref('')
const activeArchiveItemId = ref('')
const activeExportTaskId = ref('')
const reviewResult = ref<ReviewOpinion['result']>('满足要求')
const reviewOpinion = ref('资料、证据链与规则要求一致，同意通过。')
const correctionReason = ref('')
const selectedReviewEvidenceIds = ref<string[]>([])
const draftRequiresEvidenceSelection = ref(false)
const latestSubmissionIds = ref<Record<number, string>>({})
const pipelinePollTimer = ref<number>()
const pipelinePolling = ref(false)
const reviewPollTimer = ref<number>()
const reviewPolling = ref(false)
// 上传后单次补拉的延迟（不是轮询周期）
const POST_UPLOAD_PIPELINE_RECHECK_DELAY_MS = 10000
// AI 复核触发后单次补拉的延迟（不是轮询周期）
const REVIEW_RECHECK_DELAY_MS = 5000
const overviewFileKeyword = ref('')
const overviewFilePage = ref(1)
const overviewFilePageSize = ref(8)
const inspectionNodePage = ref(1)
const inspectionNodePageSize = ref(6)
const inspectionNodeSortKey = ref<InspectionNodeSortKey>('review')
const inspectionNodeSortDirection = ref<SortDirection>('asc')
const inspectionAuditItemKeys: InspectionAuditItemKey[] = [
  'submission',
  'ocr',
  'evidence',
  'ai_review',
  'human_review',
  'report',
  'archive'
]
const inspectionAuditItemLabels: Record<InspectionAuditItemKey, string> = {
  submission: '资料提交',
  ocr: 'OCR 抽取',
  evidence: '证据确认',
  ai_review: 'AI 复核',
  human_review: '人工结论',
  report: '报告复核',
  archive: '签发归档'
}
const isInspectionAuditItemKey = (value: unknown): value is InspectionAuditItemKey =>
  inspectionAuditItemKeys.includes(String(value || '') as InspectionAuditItemKey)
const emptyInspectionAuditItems = (): InspectionAuditItem[] =>
  inspectionAuditItemKeys.map((key) => ({
    key,
    label: inspectionAuditItemLabels[key],
    status: 'not_started',
    statusLabel: '状态待加载',
    metric: '-',
    summary: '审计项状态正在加载；目录仍可独立切换。',
    issueCount: 0,
    issues: [],
    sourceRefs: [],
    availableActions: []
  }))

const role = computed<RoleCode>(() => {
  const path = route.path
  if (path.includes('/contractor')) return 'contractor'
  if (path.includes('/ndt')) return 'ndt'
  if (path.includes('/owner')) return 'owner'
  return 'inspection'
})

const currentRoleConfig = computed(() => roleConfig[role.value])
const currentProject = computed(() => {
  return (
    context.value?.project ||
    projectOptions.value.find((project) => project.id === activeProjectId.value)
  )
})
const metrics = computed(() => summary.value?.metrics || [])
const todos = computed(() => summary.value?.todos || [])
const messages = computed(() => summary.value?.messages || [])
const selectedNode = computed<ProjectTreeNode | undefined>(() => nodePackage.value?.node)

/** 静态视图（施工方/建设方）的组件实例，待办跳转要调它的定位方法。 */
const staticSectionsRef = ref<{
  focusContractorNode?: (node: { id: number; name: string }) => Promise<boolean>
} | null>(null)

/** 节点显示名。取不到就退回「节点 N」——搜索框里宁可填个编号，也不填空串。 */
const nodeDisplayName = (nodeId: number) => {
  const fromPackage = nodePackage.value?.node
  if (fromPackage && Number(fromPackage.id) === nodeId) {
    return String(fromPackage.name || `节点 ${nodeId}`)
  }
  return `节点 ${nodeId}`
}
const bindings = computed(() => nodePackage.value?.bindings || [])
const nodeScopedFiles = computed(() => {
  const documentIds = new Set(bindings.value.map((binding) => binding.documentId))
  return (nodePackage.value?.projectFiles || []).filter((file) => documentIds.has(file.id))
})
const inspectionAuditItems = computed<InspectionAuditItem[]>(() =>
  inspectionAuditWorkspace.value?.items?.length
    ? inspectionAuditWorkspace.value.items
    : emptyInspectionAuditItems()
)
const activeInspectionAuditItemData = computed(() =>
  inspectionAuditItems.value.find((item) => item.key === activeInspectionAuditItem.value)
)
const inspectionAuditOverviewNodeMap = computed(
  () =>
    new Map((inspectionAuditOverview.value?.items || []).map((item) => [item.node.nodeId, item]))
)
const inspectionAuditStatusSummaryRows = computed(() => {
  const summary = inspectionAuditOverview.value?.summary
  return [
    { key: 'not_started', label: '未开始', value: summary?.not_started || 0 },
    { key: 'in_progress', label: '处理中', value: summary?.in_progress || 0 },
    { key: 'needs_attention', label: '需关注', value: summary?.needs_attention || 0 },
    { key: 'failed', label: '执行失败', value: summary?.failed || 0 },
    { key: 'completed', label: '已完成', value: summary?.completed || 0 }
  ] as const
})
const inspectionNodeReports = computed(() =>
  role.value === 'inspection'
    ? reports.value.filter((report) => report.nodeIds.includes(activeNodeId.value))
    : reports.value
)
const inspectionNodeArchiveItems = computed(() =>
  role.value === 'inspection'
    ? archiveItems.value.filter((item) => Number(item.nodeId || 0) === activeNodeId.value)
    : archiveItems.value
)
const extractedFields = computed(() => nodePackage.value?.extractedFields || [])
const extractedFieldCountByVersion = computed(() => {
  const counts = new Map<string, number>()
  for (const field of extractedFields.value) {
    counts.set(field.documentVersionId, (counts.get(field.documentVersionId) || 0) + 1)
  }
  return counts
})
const rectifications = computed(() => nodePackage.value?.rectifications || [])
const reviewOpinions = computed(() => nodePackage.value?.reviewOpinions || [])
const latestAiRun = computed(() => nodePackage.value?.aiRuns[0])
const aiRecheckOutputVisible = ref(false)
const aiTechnicalPanels = ref<string[]>([])
const mobileTreeOpen = ref(false)
const compactNodeNavigation = ref(false)
const desktopTreeCollapsed = ref(false)

const syncCompactNodeNavigation = () => {
  compactNodeNavigation.value = window.innerWidth <= 900
  if (!compactNodeNavigation.value) mobileTreeOpen.value = false
}
const aiRecheckRunOverride = ref<AiReviewRun>()
const aiRecheckOutputError = ref('')
const selectedAiReviewMode = ref<AiReviewMode>('formal')
const getAiMetadataText = (metadata: Record<string, unknown> | undefined, keys: string[]) => {
  for (const key of keys) {
    const value = metadata?.[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value && typeof value === 'object') return JSON.stringify(value, null, 2)
  }
  return ''
}
const aiRecheckDisplayRun = computed(() => aiRecheckRunOverride.value || latestAiRun.value)
const activeHumanInputTask = ref<ReviewHumanInputTask | null>(null)
const humanInputReviewEtag = ref('')
const humanInputDialogVisible = ref(false)
const humanInputLoading = ref(false)
const humanInputPromptedTaskId = ref('')
const activeHumanInputTaskType = computed(() => activeHumanInputTask.value?.taskType || '')
const isR19HumanInputTask = computed(
  () => activeHumanInputTaskType.value === 'r19_semantic_evidence_confirmation'
)

const syncActiveReviewHumanInputTask = async () => {
  const reviewRunId = aiRecheckDisplayRun.value?.reviewRunId
  if (!reviewRunId || ![12, 19].includes(activeNodeId.value)) {
    activeHumanInputTask.value = null
    humanInputReviewEtag.value = ''
    return
  }
  try {
    const res = await getActiveReviewHumanInputTaskApi(reviewRunId)
    if (!res) return
    activeHumanInputTask.value = res.data.task
    humanInputReviewEtag.value = res.data.reviewRun.etag
    if (res.data.task && humanInputPromptedTaskId.value !== res.data.task.taskId) {
      humanInputPromptedTaskId.value = res.data.task.taskId
      humanInputDialogVisible.value = true
    }
  } catch {
    // Polling will retry; keep the current task card visible if it was already loaded.
  }
}
const aiRecheckIsLocalFallback = computed(() => {
  const metadata = aiRecheckDisplayRun.value?.llmMetadata
  return metadata?.llmCalled === false || metadata?.llmExecution === 'local_disabled_fallback'
})
const aiRecheckReasoningText = computed(() => {
  const run = aiRecheckDisplayRun.value
  const metadata = run?.llmMetadata
  return (
    run?.reasoningProcess?.trim() ||
    getAiMetadataText(metadata, [
      'reasoningProcess',
      'reasoningSummary',
      'reasoning_content',
      'reasoningContent'
    ]) ||
    (actionLoading.value && aiRecheckOutputVisible.value
      ? '正在触发 AI 复核，等待后端返回推理过程。'
      : '暂无 AI 推理过程。')
  )
})
const aiRecheckDeepThinkText = computed(() => {
  if (aiRecheckIsLocalFallback.value) {
    return '当前调度器未启用，未调用外部模型，因此没有真实 DeepThink 内容。上方“推理过程”为系统基于真实节点、证据数量、缺项数量和规则上下文生成的本地降级摘要。'
  }
  const run = aiRecheckDisplayRun.value
  const metadata = run?.llmMetadata
  return (
    getAiMetadataText(metadata, [
      'deepThink',
      'deepthink',
      'deepThinkContent',
      'deepthinkContent',
      'reasoning_content',
      'reasoningContent'
    ]) ||
    run?.reasoningProcess?.trim() ||
    (actionLoading.value && aiRecheckOutputVisible.value
      ? '正在触发 AI 复核，等待后端返回 DeepThink 内容。'
      : '暂无 DeepThink 内容。')
  )
})
const aiRecheckDeepThinkLabel = computed(() =>
  aiRecheckIsLocalFallback.value ? 'DeepThink 内容（未调用模型）' : 'DeepThink 内容'
)
const aiRecheckResultText = computed(() => {
  const run = aiRecheckDisplayRun.value
  const metadata = run?.llmMetadata
  return (
    run?.llmResultText?.trim() ||
    getAiMetadataText(metadata, ['resultText', 'answer', 'content']) ||
    run?.suggestion?.opinionDraft ||
    (actionLoading.value && aiRecheckOutputVisible.value ? '正在等待模型输出。' : '暂无模型输出。')
  )
})
/** 模型输出解析成的结论条目；空数组表示不是 findings JSON，按原文显示。 */
const aiRecheckFindings = computed(() => parseAiFindings(aiRecheckResultText.value))

const aiRecheckOutputMeta = computed(() => {
  const run = aiRecheckDisplayRun.value
  if (!run) return actionLoading.value && aiRecheckOutputVisible.value ? '触发中' : '等待触发'
  const executionLabel = aiRecheckIsLocalFallback.value
    ? '本地降级摘要（未调用模型）'
    : run.model || 'review-chat'
  return [run.status, executionLabel, run.finishedAt || run.id].filter(Boolean).join(' · ')
})
const nodeEvidenceLinks = computed(() => nodePackage.value?.nodeEvidenceLinks || [])
const evidenceLinks = computed(() => {
  const runLinks = latestAiRun.value?.evidenceLinks || []
  return runLinks.length ? runLinks : nodeEvidenceLinks.value
})
const evidenceReadiness = computed(() => nodePackage.value?.evidenceReadiness)
const confirmedEvidenceLinks = computed(() =>
  nodeEvidenceLinks.value.filter((item) => item.manualStatus === 'confirmed')
)
const confirmedEvidenceIds = computed(
  () => new Set(confirmedEvidenceLinks.value.map((item) => item.id))
)
const formatBlockingReason = (reason: {
  message?: string
  code?: string
  requirementName?: string
}) => [reason.requirementName, reason.message || reason.code].filter(Boolean).join('：')
const readinessBlockingReasons = computed(() => {
  const reasons = (evidenceReadiness.value?.blockingReasons || [])
    .map(formatBlockingReason)
    .filter(Boolean)
  if (reasons.length) return reasons
  const fallback: string[] = []
  const pendingCount = Number(evidenceReadiness.value?.pendingCount || 0)
  const missingCount = Number(evidenceReadiness.value?.missingCount || 0)
  if (pendingCount > 0) fallback.push(`仍有 ${pendingCount} 条候选证据待确认或不采用。`)
  if (missingCount > 0) fallback.push(`仍有 ${missingCount} 项必传审查点缺少 confirmed 证据。`)
  if (!evidenceReadiness.value) fallback.push('等待节点资料证据 readiness 加载。')
  return fallback
})
const readyForAiFormal = computed(() => {
  const readiness = evidenceReadiness.value
  if (!readiness) return false
  if (typeof readiness.readyForAiFormal === 'boolean') return readiness.readyForAiFormal
  return Boolean(readiness.readyForAi && !readiness.pendingCount && !readiness.missingCount)
})
const readyForGapPrecheck = computed(() => {
  const readiness = evidenceReadiness.value
  if (!readiness) return false
  if (typeof readiness.readyForGapPrecheck === 'boolean') return readiness.readyForGapPrecheck
  return Boolean(readiness.hasReviewPoints)
})
const availableAiReviewModes = computed<AiReviewMode[]>(() => {
  const declared = evidenceReadiness.value?.availableReviewModes
  if (declared?.length) return declared
  const modes: AiReviewMode[] = []
  if (readyForAiFormal.value) modes.push('formal')
  if (readyForGapPrecheck.value) modes.push('gap_precheck')
  return modes
})
const selectedAiReviewModeLabel = computed(() =>
  selectedAiReviewMode.value === 'formal' ? '正式复核' : '缺项预审'
)
const aiRecheckDisabledReason = computed(() => {
  if (role.value !== 'inspection') return ''
  if (isReadOnly.value) return '当前项目只读，不能发起 AI 复核。'
  if (!availableActions.value.includes('ai:recheck')) return '当前节点未开放 AI 复核动作。'
  if (selectedAiReviewMode.value === 'formal') {
    if (readyForAiFormal.value) return ''
    return readinessBlockingReasons.value.join('；') || '资料证据未满足正式 AI 复核条件。'
  }
  if (readyForGapPrecheck.value) return ''
  return readinessBlockingReasons.value.join('；') || '当前节点没有可执行缺项预审的审查点。'
})
const aiRecheckButtonLabel = computed(() =>
  selectedAiReviewMode.value === 'formal' ? '发起正式复核' : '运行缺项预审'
)
/** 正式复核为什么点不了——说清楚还差什么，而不是只把按钮灰掉。 */
const formalReviewBlockedReason = computed(() => {
  if (availableAiReviewModes.value.includes('formal')) return ''
  const readiness = evidenceReadiness.value
  const missing = Number(readiness?.missingCount || 0)
  const pending = Number(readiness?.pendingCount || 0)
  const parts: string[] = []
  if (missing) parts.push(`${missing} 项必传资料未提交`)
  if (pending) parts.push(`${pending} 条候选证据待确认`)
  if (!parts.length) return '正式复核需要必传资料齐全且所有候选证据已确认。'
  return `正式复核暂不可用：${parts.join('、')}。补齐后即可发起。`
})

const aiReviewModeHint = computed(() => {
  // 原来这句只描述**当前选中**的模式。而正式复核不可用时选中的必然是缺项预审，
  // 于是用户看到的是「缺项预审只生成补充资料建议…」——为什么正式复核是灰的，
  // 一个字都没有。用户实际反馈就是「是流程没推进到这一步还是 bug？」
  const blocked = formalReviewBlockedReason.value
  if (selectedAiReviewMode.value === 'gap_precheck') {
    const base = '缺项预审只生成补充资料建议，不改变节点正式审查状态。'
    return blocked ? `${base} ${blocked}` : base
  }
  if (readyForAiFormal.value) return '正式复核完成后进入待人工确认，AI 不会自动通过节点。'
  return blocked || '正式复核需要必传资料齐全且所有候选证据已确认。'
})
const reviewSaveDisabledReason = computed(() => {
  if (role.value !== 'inspection') return ''
  const selectedInvalid = selectedReviewEvidenceIds.value.filter(
    (id) => !confirmedEvidenceIds.value.has(id)
  )
  if (selectedInvalid.length)
    return `证据引用不属于当前节点 confirmed 范围：${selectedInvalid.join('、')}`
  if (reviewResult.value === '满足要求') {
    if (!readyForAiFormal.value) {
      return readinessBlockingReasons.value.join('；') || '资料证据未满足保存“满足要求”的条件。'
    }
    if (!selectedReviewEvidenceIds.value.length)
      return '请选择至少一条 confirmed 证据后再保存“满足要求”。'
  }
  return ''
})
const latestReviewOpinion = computed(() => reviewOpinions.value[0])
const reportGenerateDisabledReason = computed(() => {
  if (role.value !== 'inspection') return ''
  const opinion = latestReviewOpinion.value
  if (!opinion) return '生成报告前必须先保存人工审查意见。'
  if (!opinion.evidenceLinkIds?.length) return '人工审查意见缺少 confirmed 证据引用。'
  if (opinion.evidenceValidation?.passed !== true) {
    return (
      opinion.evidenceValidation?.message || '人工审查意见的证据引用未通过 confirmed-only 校验。'
    )
  }
  if (opinion.result === '满足要求' && opinion.readinessSnapshot?.readyForAiFormal !== true) {
    return '人工审查意见缺少正式 readiness 快照，需重新校验证据后生成报告。'
  }
  return ''
})
const businessBasis = computed(() => nodePackage.value?.businessBasis)
const isReadOnly = computed(
  () => role.value === 'owner' || currentProject.value?.status === '已归档'
)
const readonlyIssue = computed<WorkbenchStateIssue | undefined>(() => {
  if (!isReadOnly.value || !currentProject.value) return undefined
  return {
    type: 'readonly',
    title: role.value === 'owner' ? '建设方只读视图' : '项目已归档，只读查看',
    message:
      role.value === 'owner'
        ? '当前角色只能查看项目、报告和归档资料，可下载归档包和证据定位包，不能上传、审查或退回补正。'
        : '归档项目已锁定业务写入，只保留查看、预览和下载能力。'
  }
})
const availableActions = computed<ActionCode[]>(() => {
  return Array.from(
    new Set([...(context.value?.actions || []), ...(nodePackage.value?.actions || [])])
  )
})
const unreadMessageCount = computed(() => messages.value.filter((message) => !message.read).length)
const quickAccessNotificationCount = computed(() => todos.value.length + unreadMessageCount.value)
const projectTreeNodes = computed<ProjectTreeNode[]>(() =>
  treeGroups.value.flatMap((group) => group.nodes || [])
)
const feedbackNodeIds = computed(() => {
  const nodeIds = new Set<number>()
  for (const todo of todos.value) {
    if (
      todo.nodeId &&
      todo.status === '待处理' &&
      (todo.targetType === 'rectification' || todo.actions?.includes('rectification:submit'))
    ) {
      nodeIds.add(todo.nodeId)
    }
  }
  for (const node of projectTreeNodes.value) {
    if (['需补正', '补正中'].includes(node.status)) {
      nodeIds.add(node.nodeId)
    }
  }
  for (const feedback of ndtFeedback.value) {
    if (feedback.status !== '已关闭') {
      nodeIds.add(feedback.nodeId)
    }
  }
  return nodeIds
})
const contractorFeedbackTreeGroups = computed<ProjectTreePayload['groups']>(() =>
  treeGroups.value
    .map((group) => ({
      ...group,
      nodes: group.nodes.filter((node) => feedbackNodeIds.value.has(node.nodeId))
    }))
    .filter((group) => group.nodes.length)
)
const visibleTreeGroups = computed<ProjectTreePayload['groups']>(() =>
  role.value === 'contractor' || role.value === 'ndt'
    ? contractorFeedbackTreeGroups.value
    : treeGroups.value
)
const getInspectionReviewProgress = (
  status?: string
): { label: InspectionReviewProgressLabel; rank: number } => {
  if (!status) return { label: '未提交', rank: 3 }
  if (status.includes('通过')) return { label: '已通过', rank: 4 }
  if (status.includes('补正')) return { label: '未补正', rank: 2 }
  if (['待审查', 'AI 预审中', '待人工确认', '复审中', '已提交'].includes(status)) {
    return { label: '待审查', rank: 1 }
  }
  return { label: '未提交', rank: 3 }
}
const getInspectionNodeMissingText = (
  missingCount: number,
  missingNames: string[],
  hasRequirementDetails: boolean
) => {
  if (missingCount <= 0) return '资料已齐'
  if (missingNames.length) {
    const visibleNames = missingNames.slice(0, 2).join('、')
    return `缺：${visibleNames}${missingNames.length > 2 ? `等 ${missingNames.length} 项` : ''}`
  }
  return hasRequirementDetails ? `缺 ${missingCount} 项资料` : '缺失资料项待明细配置'
}
const handleInspectionNodeTableSort = ({
  prop,
  order
}: {
  prop: string
  order: 'ascending' | 'descending' | null
}) => {
  if (!order || !['nodeId', 'material'].includes(prop)) return
  inspectionNodePage.value = 1
  inspectionNodeSortKey.value = prop as InspectionNodeSortKey
  inspectionNodeSortDirection.value = order === 'ascending' ? 'asc' : 'desc'
}
/* 只看需要我处理的。
 *
 * 69 个节点按 6 条/页 = 12 页，而需处理的那几个散在其中——实测首屏 6 行全是
 * 「未开始」。业务口径是「监检最好只需要知道状态，全程不需要人工干预」，
 * 那清单的默认视角就该是「有没有要我管的」，而不是把 69 个节点平铺出来让人翻。
 *
 * 默认开启，但要能关掉：偶尔确实需要看全量（比如核对整体进度）。
 * 计数写在开关上——关着的时候也得知道有几个在等，否则筛选本身就成了新的隐藏。
 */
const inspectionOnlyAttentionNodes = ref(true)

/* 需处理的「审计项」数——与需处理的「节点」数是两个单位。
 * 一个节点可能有两项需要处理，两个数字不相等是正常的；并排显示时必须写清楚
 * 单位，否则会被当成其中一个算错了。 */
const inspectionAttentionItemCount = computed(() => {
  let total = 0
  for (const node of projectTreeNodes.value) {
    const items = inspectionAuditOverviewNodeMap.value.get(node.nodeId)?.items || []
    total += items.filter((item) => nodeNeedsAttention([item])).length
  }
  return total
})

const inspectionAttentionNodeCount = computed(
  () =>
    projectTreeNodes.value.filter((node) =>
      nodeNeedsAttention(inspectionAuditOverviewNodeMap.value.get(node.nodeId)?.items)
    ).length
)

const inspectionProjectNodeRows = computed(() => {
  const rows = projectTreeNodes.value.map((node) => {
    const summary = node.requirementsSummary
    const total = Number(summary?.requiredCount ?? node.requiredProgress?.total ?? 0)
    const done = Number(summary?.satisfiedCount ?? node.requiredProgress?.done ?? 0)
    const progress = Number(
      summary?.progressPercent ?? (total ? Math.round((done / total) * 100) : 0)
    )
    const missingCount = Number(summary?.missingCount ?? Math.max(total - done, 0))
    const missingNames = (summary?.missingRequirements || [])
      .map((requirement) => requirement.name)
      .filter(Boolean)
    const reviewProgress = getInspectionReviewProgress(node.status)
    return {
      node,
      materialDone: done,
      materialTotal: total,
      materialPercent: progress,
      missingCount,
      missingText: total
        ? getInspectionNodeMissingText(
            missingCount,
            missingNames,
            Boolean(summary?.hasRequirementDetails)
          )
        : '无资料要求',
      reviewProgress: reviewProgress.label,
      reviewRank: reviewProgress.rank
    }
  })
  return rows.sort((left, right) => {
    const sortKey = inspectionNodeSortKey.value
    let comparison = 0
    if (sortKey === 'nodeId') {
      comparison = left.node.nodeId - right.node.nodeId
    } else if (sortKey === 'material') {
      comparison =
        left.materialPercent - right.materialPercent ||
        left.missingCount - right.missingCount ||
        left.node.nodeId - right.node.nodeId
    } else {
      comparison = left.reviewRank - right.reviewRank || left.node.nodeId - right.node.nodeId
    }
    return inspectionNodeSortDirection.value === 'asc' ? comparison : -comparison
  })
})

const inspectionVisibleNodeRows = computed(() => {
  if (!inspectionOnlyAttentionNodes.value) return inspectionProjectNodeRows.value
  const filtered = inspectionProjectNodeRows.value.filter((row) =>
    nodeNeedsAttention(inspectionAuditOverviewNodeMap.value.get(row.node.nodeId)?.items)
  )
  // 一个都没有时退回全量：给一张空表会让人以为数据没加载出来。
  // 「没有要处理的」这件事由开关旁边的计数说，不靠一张空表暗示。
  return filtered.length ? filtered : inspectionProjectNodeRows.value
})
const pagedInspectionProjectNodeRows = computed(() => {
  const start = (inspectionNodePage.value - 1) * inspectionNodePageSize.value
  return inspectionVisibleNodeRows.value.slice(start, start + inspectionNodePageSize.value)
})
const canShowWorkspace = computed(() => !pageIssue.value && !!activeProjectId.value)
const roleUserLabel = computed(() => {
  const identity =
    userStore.getUserInfo?.displayName ||
    userStore.getUserInfo?.username ||
    getAicheckRoleLabel(role.value)
  return `${getAicheckRoleLabel(role.value)} · ${identity}`
})
const handleUserCommand = (command: string | number | object) => {
  if (command === 'logout') {
    userStore.logoutConfirm()
  }
}
const topbarStatus = computed(() => {
  return (
    context.value?.topbar.statusText ||
    currentProject.value?.status ||
    currentRoleConfig.value.title
  )
})
const globalSearchPlaceholder = computed(() => {
  const placeholders: Record<RoleCode, string> = {
    inspection: '⌕ 全局搜索（项目 / 文件 / 节点 / 焊工证书 / 标准条款）',
    contractor: '⌕ 全局搜索（文件 / 节点名称 / 资料项 / 反馈意见 / 编号）',
    ndt: '⌕ 全局搜索（项目 / 文件 / 资料类型 / 底片编号 / 检测报告）',
    owner: '⌕ 全局搜索（项目 / 节点 / 资料状态 / 报告 / 归档资料）',
    admin: '⌕ 搜索（项目 / 单位 / 用户 / 角色 / 流程 / 待办 / 节点）',
    fde: '⌕ 搜索（AI Run / Agent / 评估集 / 发布单 / 业务类型）'
  }
  return placeholders[role.value]
})
const pageHeadline = computed(() => {
  const headlines: Record<RoleCode, string> = {
    inspection: 'AI 业务审查链路',
    contractor: '项目文件库与补正反馈',
    ndt: '检测资料库与补正反馈',
    owner: '建设方项目概况',
    admin: '管理工作台',
    fde: 'AI 交付治理后台'
  }
  return headlines[role.value]
})
const pageIntro = computed(() => {
  const intros: Record<RoleCode, string> = {
    inspection: '当前节点资料、AI 业务核验链路、人工审查意见和报告归档动作在同一工作区完成。',
    contractor:
      '施工方以项目文件库为主办理资料上传、资料齐套、提交和补正反馈，审核环节仅作为可选定位字段。',
    ndt: '无损检测单位在资料库中上传、核对并逐份提交检测资料，同时处理监检反馈。',
    owner: '只读查看项目进展、节点资料状态、异常提醒、报告状态和归档资料。',
    admin: '后台只维护配置、权限、流程和审计，不替代工作台业务办理。',
    fde: 'FDE 只管理 AI 能力、评估、发布和治理，不替代业务人员作出正式结论。'
  }
  return intros[role.value]
})
/* X-5：未选节点时原先照常渲染整套骨架——七个步骤、四个字段全是「-」和「状态待加载」，
 * 版式与真实内容完全一致，用户会误以为「这个节点没数据」而不是「我还没选节点」。
 * 两者的应对动作完全不同，必须区分开。 */
const inspectionNodeUnselected = computed(
  () =>
    role.value === 'inspection' && activeWorkbenchSection.value === 'node' && !selectedNode.value
)

const currentNodeLabel = computed(() => {
  if (!selectedNode.value) return '未选择节点'
  return `${selectedNode.value.nodeId}. ${selectedNode.value.name}`
})
const workbenchAuditCards = computed<AuditSummaryCard[]>(() => {
  if (role.value === 'contractor') {
    const projectFileCount = nodePackage.value?.projectFiles.length || bindings.value.length
    const correctionCount = rectifications.value.filter((item) => item.status !== '已关闭').length
    const pendingSubmitCount = (nodePackage.value?.projectFiles || []).filter((file) =>
      ['未关联', '待提交', '需补正'].includes(documentBindingSummary(file))
    ).length
    return [
      {
        label: '办理对象',
        value: '项目文件库',
        hint: currentProject.value?.name || '未选择项目',
        tone: 'blue'
      },
      {
        label: '项目文件',
        value: `${projectFileCount} 份`,
        hint: `${extractedFields.value.length} 个 OCR/字段证据可定位`,
        tone: 'green'
      },
      {
        label: '待提交/补正',
        value: pendingSubmitCount,
        hint: '文件可先入库，审核环节可后续选择',
        tone: 'orange'
      },
      {
        label: '监检反馈',
        value: `${correctionCount} 项`,
        hint: '按反馈逐条上传补正或关联已有文件',
        tone: correctionCount ? 'red' : 'green'
      }
    ]
  }
  if (role.value === 'ndt') {
    const openFeedbackCount = ndtFeedback.value.filter((item) => item.status !== '已关闭').length
    const ndtProjectFiles = (nodePackage.value?.projectFiles || []).filter(
      (file) => file.materialCategory === '无损检测资料'
    )
    const materialTypeCount = new Set(ndtProjectFiles.map((file) => file.materialTypeCode)).size
    const pendingFileCount = ndtProjectFiles.filter((file) =>
      ['未关联', '待提交', '需补正'].includes(documentBindingSummary(file))
    ).length
    return [
      {
        label: '办理对象',
        value: '检测资料库',
        hint: currentProject.value?.name || '未选择项目',
        tone: 'blue'
      },
      {
        label: '已上传文件',
        value: `${ndtProjectFiles.length} 份`,
        hint: `${materialTypeCount} 种资料类型`,
        tone: 'green'
      },
      {
        label: '待提交/补正',
        value: pendingFileCount,
        hint: '每个文件可单独提交审批',
        tone: 'orange',
        // 有数字就要能看到是哪几份。只报数不给入口，等于让人自己去列表里翻。
        ...(pendingFileCount ? { actionKey: 'ndt-pending', actionLabel: '查看待处理文件' } : {})
      },
      {
        label: '监检反馈',
        value: `${openFeedbackCount} 项`,
        hint: '按反馈补充报告、底片、记录或说明',
        tone: openFeedbackCount ? 'red' : 'green'
      }
    ]
  }
  return [
    {
      label: '当前审查对象',
      value: selectedNode.value?.name || currentNodeLabel.value,
      hint: currentProject.value?.name || '未选择项目',
      tone: 'blue'
    },
    {
      label: '资料证据',
      value: `${bindings.value.length} 份挂载资料`,
      hint: `${extractedFields.value.length} 个 OCR/字段证据可定位`,
      tone: 'green'
    },
    {
      label: 'AI 审查',
      value: latestAiRun.value?.suggestion.result || '等待预审',
      hint: 'AI 只生成建议，正式结论由人工确认',
      tone: 'orange'
    },
    {
      label: '人工确认',
      value: `${latestAiRun.value?.suggestion.manualConfirmItems.length || 0} 项`,
      hint: role.value === 'owner' ? '只读查看，不办理审批' : '低置信和阻断项优先处理',
      tone: 'red'
    }
  ]
})
const overviewFileMaterialTypeLabels: Record<string, string> = {
  generic_review_material: '审查资料',
  design_license: '设计单位许可证',
  construction_license: '施工单位安装许可证',
  manufacturing_license: '制造单位许可证',
  ndt_org_certificate: '无损检测机构核准证',
  ndt_person_certificate: '无损检测人员资格证和执业注册证',
  design_document: '设计文件',
  drawing_review_record: '施工图审查手续',
  calculation_report: '强度计算书或应力分析报告',
  design_change_document: '设计变更和书面批准文件',
  construction_organization_design: '施工组织设计',
  construction_schedule: '施工计划工期文件',
  quality_certificate: '产品质量证明书',
  manufacturing_supervision_certificate: '制造监督检验证书',
  type_test_report: '型式试验证书或型式试验报告',
  factory_inspection_report: '出厂检验报告',
  overseas_material_certificate: '境外制造或境外牌号材料证明文件',
  acceptance_witness_record: '到货验收见证资料',
  material_retest_report: '材料复验报告',
  material_mark_transfer_record: '材料标志移植记录',
  material_substitution_approval: '材料代用批准文件',
  technical_review_approval: '技术评审和批准手续',
  valve_test_report: '阀门施工资料和耐压试验报告',
  welder_certificate: '焊工资格证',
  welder_roster: '焊工名册',
  wps_pqr: '焊接工艺评定报告和焊接作业指导书',
  welding_material_certificate: '焊接材料质量证明文件',
  welding_material_management_record: '焊材验收保管发放回收记录',
  welding_record: '焊接记录和焊缝标识资料',
  weld_repair_record: '焊缝返修记录',
  heat_treatment_procedure: '焊后热处理工艺文件',
  heat_treatment_record: '热处理记录、曲线和硬度检测报告',
  instrument_calibration_certificate: '仪表检定或校准证书',
  ndt_plan: '无损检测方案',
  ndt_procedure: '无损检测工艺文件',
  ndt_report: '无损检测报告',
  radiographic_film: '射线检测底片',
  anticorrosion_insulation_material_certificate: '防腐及保温材料质量证明文件',
  anticorrosion_insulation_record: '防腐补口补伤和保温施工记录',
  cathodic_protection_record: '阴极保护和杂散电流排流装置资料',
  grounding_test_record: '静电接地施工和测试记录',
  installation_record: '管道安装和现场制作记录',
  safety_accessory_record: '安全附件安装、校验或性能测试资料',
  pressure_test_plan: '耐压试验方案',
  pressure_test_report: '耐压试验记录或报告',
  leakage_test_report: '泄漏试验记录或报告',
  purge_cleaning_record: '吹扫清洗方案和记录',
  field_photo: '现场照片、底片或实物核验证据',
  quality_system_document: '质量保证体系文件和实施记录',
  external_query_screenshot: '外部查询截图'
}
const getOverviewFileMaterialCategory = (file: {
  materialCategory?: string | null
  materialTypeCode?: string | null
}) => {
  const materialCategory = String(file.materialCategory || '').trim()
  if (materialCategory) return materialCategory
  const materialTypeCode = String(file.materialTypeCode || '').trim()
  if (materialTypeCode) return overviewFileMaterialTypeLabels[materialTypeCode] || materialTypeCode
  return '未分类'
}
const ocrReadinessLabels: Record<string, string> = {
  not_started: 'OCR 待处理',
  queued: 'OCR 排队中',
  processing: 'OCR 处理中',
  ready: 'OCR 证据就绪',
  incomplete: 'OCR 抽取不完整',
  inconsistent: 'OCR 状态异常',
  failed: 'OCR 失败'
}
const ocrReadinessLabel = (status?: string) =>
  ocrReadinessLabels[String(status || '')] || '等待 OCR 产物校验'
const pagedInspectionOverviewFiles = computed(() =>
  (inspectionSubmittedDocuments.value?.items || []).map((file, index) => {
    const sourceOrgName = file.sourceOrgName || ''
    const sourceRole =
      /无损|检测|NDT|华测/i.test(sourceOrgName) || file.materialCategory === '无损检测资料'
        ? '无损检测机构'
        : /施工|安装|承包|工程/i.test(sourceOrgName)
          ? '施工方'
          : '参建单位'
    return {
      ...file,
      id: file.documentId,
      rowNo: (overviewFilePage.value - 1) * overviewFilePageSize.value + index + 1,
      materialCategoryText: getOverviewFileMaterialCategory(file),
      sourceRole
    }
  })
)
const inspectionOverviewFileTotal = computed(() => inspectionSubmittedDocuments.value?.total || 0)
const postUploadProcessingFiles = computed(() =>
  (nodePackage.value?.projectFiles || []).filter((file) => {
    const readinessStatus = file.ocrReadiness?.status
    if (readinessStatus && ['queued', 'processing'].includes(readinessStatus)) return true
    if (readinessStatus && readinessStatus !== 'ready') return false
    if (['排队中', '识别中'].includes(file.currentOcrStatus)) return true
    if (file.currentOcrStatus !== '已识别') return false
    if (['未切片', '待切片'].includes(file.sliceStatus || '')) return true
    if (['未向量化', '待向量化'].includes(file.vectorStatus || '')) return true
    return false
  })
)
const hasPostUploadProcessing = computed(() => postUploadProcessingFiles.value.length > 0)
const firstBinding = computed(() => bindings.value[0])
const previewFileName = computed(() => {
  if (role.value === 'owner') return '项目资料状态摘要'
  if (role.value === 'ndt') return ndtReports.value[0]?.reportNo || 'RT 检测报告 R2.pdf'
  return firstBinding.value?.fileName || '当前节点资料预览'
})
const previewDrawerTitle = computed(() => {
  const title = previewDrawerTarget.value.title || previewFileName.value
  return role.value === 'owner' ? `只读预览 · ${title}` : `文件预览 · ${title}`
})
const previewDrawerToolbarLabel = computed(() => {
  if (previewDrawerTarget.value.source === 'standard') return '规范原文预览'
  if (previewDrawerTarget.value.source === 'report') return '报告预览'
  if (previewDrawerTarget.value.source === 'archive') return '归档资料预览'
  if (previewDrawerTarget.value.source === 'file') return '文件签名预览'
  return role.value === 'owner' ? '项目状态摘要' : '第 1 / 3 页'
})
const previewDrawerMeta = computed(() => {
  if (previewDrawerTarget.value.meta) return previewDrawerTarget.value.meta
  if (previewDrawerTarget.value.url) return previewDrawerTarget.value.url
  return '当前节点内嵌预览'
})
const previewDrawerCanEmbedOriginal = computed(() => {
  const url = String(previewDrawerTarget.value.url || '')
  if (!url || url.startsWith('mock://')) return false
  const previewType = previewDrawerTarget.value.previewType
  // Office 等非浏览器原生类型放入 iframe 会触发自动下载
  return previewType === 'pdf' || previewType === 'image'
})
const previewDrawerRequiresBlob = computed(
  () =>
    previewDrawerCanEmbedOriginal.value &&
    String(previewDrawerTarget.value.url || '').startsWith('/api/')
)
const previewDrawerOriginalUnavailableText = computed(() => {
  const url = String(previewDrawerTarget.value.url || '')
  if (!url) return '当前文件详情没有返回原文地址。'
  if (url.startsWith('mock://'))
    return '当前接口返回的是 mock 占位地址，还没有拿到可预览的真实原文。'
  if (previewDrawerTarget.value.previewType === 'office')
    return 'Word/Excel 等 Office 文件暂不支持在线预览，请下载后查看。'
  if (previewDrawerTarget.value.previewType === 'unsupported')
    return '当前文件类型暂不支持在线预览。'
  return '当前文件没有可预览的真实原文。'
})
const previewDrawerFrameUrl = computed(() => {
  const url = String(previewDrawerTarget.value.url || '')
  if (previewDrawerRequiresBlob.value) return previewDrawerObjectUrl.value
  return previewDrawerObjectUrl.value || url
})
const previewDrawerIsImage = computed(() => previewDrawerTarget.value.previewType === 'image')
const aiConfidence = computed(() => {
  const confidence = latestAiRun.value?.suggestion.confidence
  return formatConfidence(confidence)
})
const compactText = (value?: string, fallback = '暂无配置') => {
  const text = String(value || '').trim()
  return text || fallback
}
const splitBasisParagraphs = (value?: string) =>
  compactText(value)
    .split(/\r?\n\s*\r?\n|\r?\n(?=(?:Agent\s*思考方式|工具集调用思考)[:：])/)
    .map((item) => item.trim())
    .filter(Boolean)
const basisCriteriaParagraphs = computed(() => splitBasisParagraphs(businessBasis.value?.criteria))
const basisCriteriaDecisionNote = computed(
  () =>
    basisCriteriaParagraphs.value.find((item) =>
      /(?:不一致|冲突).*(?:为准|优先)|(?:以后者|以前者)为准/.test(item)
    ) || ''
)
const basisCriteriaReferences = computed(() =>
  basisCriteriaParagraphs.value.filter((item) => item !== basisCriteriaDecisionNote.value)
)
const basisMethodParagraphs = computed(() =>
  splitBasisParagraphs(businessBasis.value?.checkMethod || businessBasis.value?.witnessText)
)
const basisAgentParagraphs = computed(() =>
  basisMethodParagraphs.value.filter((item) =>
    /^(?:Agent\s*思考方式|工具集调用思考)[:：]/.test(item)
  )
)
const basisCheckSteps = computed(() =>
  basisMethodParagraphs.value
    .filter((item) => !basisAgentParagraphs.value.includes(item))
    .map((item, index) => {
      const numbered = item.match(/^(\d+)[、.．]\s*(.+)$/s)
      const validity = item.match(/^有效期[:：]\s*(.+)$/s)
      return {
        label: validity ? '有效期核验' : `核查步骤 ${numbered?.[1] || index + 1}`,
        text: validity?.[1] || numbered?.[2] || item
      }
    })
)
const basisAgentSteps = computed(() =>
  basisAgentParagraphs.value
    .flatMap((item) =>
      item.replace(/^(?:Agent\s*思考方式|工具集调用思考)[:：]\s*/, '').split(/[；;]/)
    )
    .map((item) => item.trim())
    .filter(Boolean)
)
const requirementResponsibleParty = (requirement: {
  responsibleParty?: string
  materialTypeCode?: string
  name?: string
}) => {
  const explicit = String(requirement.responsibleParty || '').trim()
  if (explicit) return getAicheckRoleLabel(explicit)
  const content = `${requirement.materialTypeCode || ''} ${requirement.name || ''}`
  if (/标准|规范|条款|standard/i.test(content)) return '标准规范库引用'
  if (/(无损|检测|底片|射线|(^|_)ndt($|_)|(^|_)rt($|_)|(^|_)ut($|_))/i.test(content)) {
    return '无损检测机构上传'
  }
  if (/现场|照片|见证|监检|检查记录/i.test(content)) return '监检人员现场补充'
  return '施工方上传'
}
const nodeBasisMetaRows = computed(() => {
  const basis = businessBasis.value
  return [
    { label: '规则编号', value: basis?.ruleId || selectedNode.value?.code || '-' },
    {
      label: '来源',
      value: basis?.sourceDocument
        ? `${basis.sourceDocument}${basis.sourceSequence ? ` / 序号${basis.sourceSequence}` : ''}`
        : '-'
    },
    {
      label: '类别',
      value: basis?.inspectionClass || selectedNode.value?.inspectionType || '-'
    },
    {
      label: '业务模块',
      value: basis?.businessModule || selectedNode.value?.groupName || '-'
    }
  ]
})
const nodeRequirementRows = computed<NodeRequirementDisplayRow[]>(() => {
  const summaryRequirements = selectedNode.value?.requirementsSummary?.requirements || []
  const requirements = summaryRequirements.length
    ? summaryRequirements
    : (nodePackage.value?.requirements || []).map((requirement) => ({
        ...requirement,
        matchedLinkCount: 0,
        matchedFileNames: [],
        fulfilled: false
      }))
  return requirements.map((requirement, index) => ({
    id: requirement.id || `${requirement.nodeId}-${index}`,
    rowNo: index + 1,
    name: requirement.name,
    requiredType: requirement.requiredType,
    materialType: requirement.materialTypeCode
      ? overviewFileMaterialTypeLabels[requirement.materialTypeCode] || requirement.materialTypeCode
      : '未配置',
    responsibleParty: requirementResponsibleParty(requirement),
    applicability: requirement.applicability || requirement.note || '按当前节点规则判断',
    matchedFileNames: requirement.matchedFileNames || [],
    status:
      requirement.evidenceReviewStatus ||
      (requirement.fulfilled
        ? '已确认'
        : requirement.matchedLinkCount || requirement.matchedFileNames?.length
          ? '待确认'
          : '未找到'),
    supportStatus: requirement.supportStatus,
    matchedLinkCount: requirement.matchedLinkCount || 0
  }))
})
const evidenceConfirmationRows = computed<EvidenceConfirmationRow[]>(() => {
  const requirements = selectedNode.value?.requirementsSummary?.requirements || []
  const linksByPoint = new Map<string, EvidenceLink[]>()
  for (const link of nodeEvidenceLinks.value) {
    const key = String(link.reviewPointId || '')
    if (!key) continue
    if (!linksByPoint.has(key)) linksByPoint.set(key, [])
    linksByPoint.get(key)?.push(link)
  }
  return requirements.flatMap<EvidenceConfirmationRow>((requirement, index) => {
    const materialType = requirement.materialTypeCode
      ? overviewFileMaterialTypeLabels[requirement.materialTypeCode] || requirement.materialTypeCode
      : '未配置'
    const links = linksByPoint.get(String(requirement.id || '')) || []
    if (!links.length) {
      return [
        {
          id: `${requirement.id || index}-not-found`,
          requirementId: requirement.id || `${requirement.nodeId}-${index}`,
          requirementName: requirement.name,
          materialType,
          status: '未找到',
          fileName: '-',
          evidenceText: '-',
          confidenceText: '-',
          evidence: undefined
        }
      ]
    }
    return links.map((link) => {
      const evidenceItems = Array.from(new Set(link.matchedEvidenceItems || [])).join('、')
      const confidence = formatConfidence(link.confidence)
      return {
        id: link.id,
        requirementId: requirement.id || `${requirement.nodeId}-${index}`,
        requirementName: requirement.name,
        materialType,
        status: link.manualStatusLabel || requirement.evidenceReviewStatus || '待确认',
        fileName: evidenceLabel(link) || '-',
        evidenceText: evidenceItems || compactText(link.quotedText, '-'),
        confidenceText: confidence,
        evidence: link
      }
    })
  })
})
const nodeReferencedStandards = computed<StandardReferenceItem[]>(() => {
  const standards = businessBasis.value?.referencedStandards || []
  if (standards.length) {
    const seen = new Set<string>()
    return standards.reduce<StandardReferenceItem[]>((items, standard) => {
      const key =
        standard.sourceRelativePath || standard.file || standard.fileName || standard.reference
      if (!key || seen.has(key)) return items
      seen.add(key)
      items.push({
        reference: standard.reference || standard.fileName || '标准规范',
        file: standard.file,
        fileName: standard.fileName,
        knowledgeFileId: standard.knowledgeFileId,
        sourceRelativePath: standard.sourceRelativePath,
        previewAvailable: standard.previewAvailable,
        previewUrl: standard.previewUrl
      })
      return items
    }, [])
  }
  return standardReferences.value.map((standard) => ({
    reference: standard.reference || `${standard.standardName} ${standard.clauseNo}`.trim(),
    fileName: standard.fileName || standard.title,
    file: standard.file,
    knowledgeFileId: standard.knowledgeFileId,
    sourceRelativePath: standard.sourceRelativePath,
    previewAvailable: standard.previewAvailable,
    previewUrl: standard.previewUrl
  }))
})
const standardTreeProps = {
  value: 'id',
  label: 'label',
  children: 'children'
}
const standardReferenceGroupLabel = (segment: string) => {
  if (segment === 'NB_T_47013_split') return 'NB/T 47013 承压设备无损检测'
  return segment.replaceAll('_', ' ')
}
const standardReferenceTree = computed<StandardReferenceTreeNode[]>(() => {
  if (!nodeReferencedStandards.value.length) return []
  const root: StandardReferenceTreeNode = {
    id: 'standard-reference-root',
    label: `引用标准文件（${nodeReferencedStandards.value.length}）`,
    kind: 'root',
    children: []
  }
  const groups = new Map<string, StandardReferenceTreeNode>()
  nodeReferencedStandards.value.forEach((standard, index) => {
    const sourcePath = String(standard.sourceRelativePath || standard.file || '').replaceAll(
      '\\',
      '/'
    )
    const relativePath = sourcePath.replace(/^.*?rules\/standards\//, '')
    const segments = relativePath.split('/').filter(Boolean)
    const fileName = standard.fileName || segments.at(-1) || standard.reference
    let parent = root
    let groupPath = ''
    for (const segment of segments.slice(0, -1)) {
      groupPath = groupPath ? `${groupPath}/${segment}` : segment
      let group = groups.get(groupPath)
      if (!group) {
        group = {
          id: `standard-group-${groupPath}`,
          label: standardReferenceGroupLabel(segment),
          kind: 'group',
          children: []
        }
        groups.set(groupPath, group)
        parent.children?.push(group)
      }
      parent = group
    }
    parent.children?.push({
      id: `standard-file-${standard.knowledgeFileId || sourcePath || index}`,
      label: standard.reference || fileName,
      kind: 'file',
      reference: standard.reference,
      fileName,
      sourceRelativePath: sourcePath,
      knowledgeFileId: standard.knowledgeFileId,
      previewAvailable: standard.previewAvailable,
      previewUrl: standard.previewUrl
    })
  })
  const sortNodes = (nodes: StandardReferenceTreeNode[]) => {
    nodes.sort((left, right) => {
      if (left.kind !== right.kind) return left.kind === 'file' ? 1 : -1
      return left.label.localeCompare(right.label, 'zh-CN', { numeric: true })
    })
    nodes.forEach((node) => node.children && sortNodes(node.children))
  }
  sortNodes(root.children || [])
  return [root]
})
const standardTreeDefaultExpandedKeys = computed(() => [
  'standard-reference-root',
  ...Array.from(
    new Set(
      nodeReferencedStandards.value
        .map((standard) =>
          String(standard.sourceRelativePath || standard.file || '').replaceAll('\\', '/')
        )
        .filter((path) => path.includes('rules/standards/'))
        .map((path) =>
          path
            .replace(/^.*?rules\/standards\//, '')
            .split('/')
            .slice(0, -1)
        )
        .flatMap((segments) =>
          segments.map((_, index) => `standard-group-${segments.slice(0, index + 1).join('/')}`)
        )
    )
  )
])
const standardReferenceTreeHeight = computed(() =>
  Math.min(420, Math.max(156, (nodeReferencedStandards.value.length + 2) * 52))
)
const aiExecutionSteps = computed<AiExecutionDisplayStep[]>(() => {
  const basis = businessBasis.value
  const verificationSteps = basis?.aiExecution?.verificationSteps || []
  const manualItems = latestAiRun.value?.suggestion.manualConfirmItems || []
  const missingCount = selectedNode.value?.requirementsSummary?.missingCount || 0
  const statusFor = (index: number, title: string) => {
    const runStatus = latestAiRun.value?.status
    if (!runStatus) return '待执行'
    // 失败时不能按下标硬说前四步「完成」。前端手上只有执行计划、没有分步结果
    // （真实分步在 ai_trace_steps，节点包不带），凭下标编出来的「完成」是假的：
    // 线上那次失败是 Temporal 根本没连上，一步都没跑，界面却显示四步已完成。
    if (runStatus === '失败') return '未执行'
    if (runStatus === '推理中') return index <= 2 ? '完成' : index === 3 ? '执行中' : '待执行'
    if (manualItems.length && /人工|缺项/.test(title)) return '需人工确认'
    return '完成'
  }
  const steps: Omit<AiExecutionDisplayStep, 'status'>[] = [
    {
      title: '读取项目和节点上下文',
      input: currentNodeLabel.value,
      feedback: `${currentProject.value?.name || '当前项目'} / ${selectedNode.value?.groupName || '未分组'}`,
      tools: ['T01'],
      evidenceLinks: []
    },
    {
      title: '定位业务规则与资料要求',
      input: basis?.ruleId || selectedNode.value?.code || '-',
      feedback: `已加载 ${nodeRequirementRows.value.length} 项审查所需资料，规则版本 ${basis?.ruleVersion || latestAiRun.value?.ruleVersion || '-'}`,
      tools: ['T01', 'T02'],
      evidenceLinks: []
    },
    {
      title: '检索项目文件与证据链',
      input: `${bindings.value.length} 份节点挂载资料`,
      feedback: `命中 ${evidenceLinks.value.length} 条 EvidenceLink，项目文件库 ${nodePackage.value?.projectFiles.length || 0} 份文件`,
      tools: ['T02'],
      evidenceLinks: evidenceLinks.value.slice(0, 3)
    },
    {
      title: '抽取 OCR 字段和结构化信息',
      input: `${extractedFields.value.length} 个字段`,
      feedback: extractedFields.value.length
        ? extractedFields.value
            .slice(0, 4)
            .map((field) => `${field.fieldName}:${field.fieldValue}`)
            .join('；')
        : '暂未返回结构化字段，等待 OCR 或人工补录',
      tools: ['T03', 'T04'],
      evidenceLinks: evidenceLinks.value.slice(0, 2)
    },
    {
      title: '执行规则核验',
      input: basis?.inspectionItem || selectedNode.value?.name || '-',
      feedback: verificationSteps.length
        ? verificationSteps.slice(0, 2).join('；')
        : compactText(
            latestAiRun.value?.suggestion.opinionDraft,
            '按当前节点规则执行一致性、完整性和适用性核验'
          ),
      tools: ['T07', 'T08'],
      evidenceLinks: evidenceLinks.value.slice(0, 3)
    },
    {
      title: '生成缺项与人工确认项',
      input: `${missingCount} 项资料缺口 / ${manualItems.length} 项人工确认`,
      feedback: manualItems.length
        ? manualItems.slice(0, 3).join('；')
        : missingCount
          ? '存在资料缺口，需结合责任方补充或人工确认'
          : '未生成阻断性人工确认项',
      tools: ['T11'],
      evidenceLinks: []
    },
    {
      title: '证据链与结论回写',
      input: latestAiRun.value?.id || '等待 AI Run',
      feedback: latestAiRun.value
        ? `${latestAiRun.value.suggestion.result} / 置信度 ${aiConfidence.value}`
        : '尚未形成 AI 审查结果',
      tools: ['T12'],
      evidenceLinks: evidenceLinks.value.slice(0, 3)
    }
  ]
  return steps.map((step, index) => ({ ...step, status: statusFor(index, step.title) }))
})

/* X-3：AI 执行过程默认折叠。
 * 原先 7 个步骤全量平铺，实测占 3.1 屏，而监检最需要的结论与缺项在最底部。
 * 过程性步骤（读上下文、定位规则、检索文件）日常不需要看；需要时一键展开。
 * 折叠交互与 AI 复核 B 版工作台对齐（button + aria-expanded）。 */
const aiExecutionExpanded = ref(false)

/* X-4：界面上原先只显示 T01/T07 这类裸编号，监检人员无从判断它是什么、该不该出现。
 * 业务包的 toolCatalog 是权威来源，这里只做展示层翻译，不在前端另存一份词表。 */
const toolCatalogMap = computed(() => {
  const map = new Map<string, { name: string; capability: string }>()
  for (const tool of businessBasis.value?.toolCatalog || []) {
    if (tool?.id) map.set(String(tool.id), { name: tool.name, capability: tool.capability })
  }
  return map
})

const toolLabel = (toolId: string) => toolCatalogMap.value.get(toolId)?.name || toolId

const toolTooltip = (toolId: string) => {
  const tool = toolCatalogMap.value.get(toolId)
  if (!tool) return `工具编号 ${toolId}`
  return tool.capability ? `${toolId} · ${tool.capability}` : `${toolId} · ${tool.name}`
}

/* 状态词表是 待执行 / 执行中 / 完成 / 异常 / 需人工确认，语义分三类。
 * 「非完成」不等于「需关注」——AI 尚未运行时七步全是「待执行」，那是未开始，
 * 不是出了问题。摘要要是把它报成「7 步需关注」，等于教用户忽略这个提示。 */
const AI_STEP_ATTENTION = new Set(['异常', '需人工确认'])

/* AI 失败归因。
 *
 * 线上失败记录里躺着完整的 Temporal 连接错误，界面却只显示「异常」两个字——
 * 监检既不知道是模型没配、超时、还是资料本身有问题，也不知道该不该重跑，
 * 只能去问人。静默的失败比响亮的失败更贵。
 *
 * 后端已把原始报错翻成人话并给出下一步，这里只负责摆出来，外加一件事：
 * 重跑无用时不给亮着的重跑按钮——那是在诱导用户白点。
 */
/* 证据裁减告知。
 *
 * 节点资料合计超出模型上下文预算时，后端按整份裁减而不是整次失败——但裁过的
 * 结论一律降级为待人工确认。这里必须把「哪几份没送审」摆出来：模型没读到的
 * 资料，监检得自己看。不说，就等于让人对着一份不完整的判定签字。
 */
const aiEvidenceBudget = computed(() => aiRecheckDisplayRun.value?.evidenceBudget)

const aiRunFailure = computed(() => aiRecheckDisplayRun.value?.failure)

const AI_FAILURE_KIND_LABELS: Record<string, string> = {
  orchestration: '编排服务',
  model: '模型服务',
  timeout: '调用超时',
  budget: '内容超限',
  material: '资料依据',
  unknown: '未归类'
}
const aiFailureKindLabel = computed(
  () => AI_FAILURE_KIND_LABELS[String(aiRunFailure.value?.kind)] || '未归类'
)

const aiExecutionSummary = computed(() => {
  const steps = aiExecutionSteps.value
  if (!steps.length) return '暂无执行记录'
  // 失败要直接从 run 状态判，不能等分步标签冒出「异常」——现在失败时每一步都是
  // 「未执行」（因为确实一步没跑），照旧只看步骤标签的话，整次失败反而不再计入
  // 需关注，比原先的假「完成」还糟。
  if (latestAiRun.value?.status === '失败') {
    return `${steps.length} 步 · 本次执行失败，未产出判定`
  }
  const attention = steps.filter((step) => AI_STEP_ATTENTION.has(String(step.status)))
  const done = steps.filter((step) => step.status === '完成')
  const parts = [`${steps.length} 步`]
  if (attention.length) {
    parts.push(`${attention.length} 步需关注：${attention.map((s) => s.title).join('、')}`)
  } else if (!done.length) {
    parts.push('尚未运行')
  } else if (done.length === steps.length) {
    parts.push('全部完成')
  } else {
    parts.push(`进行中 ${done.length}/${steps.length}`)
  }
  return parts.join(' · ')
})

/** 结论与缺项要置顶——这是监检打开这一页真正要看的东西。 */
const aiOutcomeHighlights = computed(() => {
  const suggestion = latestAiRun.value?.suggestion
  if (!suggestion) return null
  // 失败时不显示结论块。suggestion 是 run 创建时就写好的占位（opinionDraft 是
  // 「AI 复核已进入队列，完成后将更新审查建议」），失败后没人回填——照原样显示
  // 就是在失败横幅旁边挂一句「已进入队列」，两句话互相打脸。
  // 没产出判定就说没产出，由横幅承担说明责任。
  if (latestAiRun.value?.status === '失败') return null
  return {
    result: suggestion.result || '待判定',
    confidence: suggestion.confidence,
    manualConfirmItems: suggestion.manualConfirmItems || [],
    // opinionDraft 是 AI 给出的结论说明，比另立 rectificationSuggestion 更贴近类型契约
    rectification: suggestion.opinionDraft || ''
  }
})

const evidenceLabel = (evidence: EvidenceLink) => {
  const title = evidence.fileName || evidence.fieldName || evidence.objectId
  return evidence.pageNo ? `${title} P${evidence.pageNo}` : title
}
const chineseOrder = ['一', '二', '三', '四', '五', '六']
const reviewConclusionOverall = computed(() => {
  // 同上：失败时 opinionDraft 还是那句排队占位，不能当结论用
  if (latestAiRun.value?.status === '失败') {
    return '本次 AI 审查执行失败，未产出结论。失败原因与处理方式见上方提示。'
  }
  if (latestAiRun.value?.suggestion.opinionDraft) return latestAiRun.value.suggestion.opinionDraft
  const summary = selectedNode.value?.requirementsSummary
  if (summary?.missingCount) {
    return `当前节点已有 ${summary.satisfiedCount}/${summary.requiredCount} 项资料匹配，仍有 ${summary.missingCount} 项资料需要补充或人工确认。`
  }
  if (latestAiRun.value) return `当前节点 AI 审查结果为${latestAiRun.value.suggestion.result}。`
  return '当前节点尚未形成 AI 审查结论，需先完成资料匹配、OCR 字段抽取和规则核验。'
})
const reviewConclusionPoints = computed<ReviewConclusionPoint[]>(() => {
  const summary = selectedNode.value?.requirementsSummary
  const manualItems = latestAiRun.value?.suggestion.manualConfirmItems || []
  const points = [
    {
      title: '资料齐全性',
      conclusion: summary?.missingCount ? '需补充' : summary ? '通过' : '待确认',
      description: summary
        ? `审查所需资料已匹配 ${summary.satisfiedCount}/${summary.requiredCount} 项，缺项 ${summary.missingCount} 项。`
        : '当前节点尚未返回资料要求明细。',
      evidenceLinks: evidenceLinks.value.slice(0, 2)
    },
    {
      title: '字段与证据识别',
      conclusion: extractedFields.value.some((field) =>
        ['低置信度', '置信度未知'].includes(field.reviewStatus)
      )
        ? '需人工确认'
        : extractedFields.value.length
          ? '通过'
          : '待识别',
      description: extractedFields.value.length
        ? `已抽取 ${extractedFields.value.length} 个结构化字段，低置信字段需人工复核。`
        : '暂未返回结构化 OCR 字段，不能单独支撑自动结论。',
      evidenceLinks: evidenceLinks.value.slice(0, 3)
    },
    {
      title: '规则核验结论',
      conclusion: latestAiRun.value?.suggestion.result || '待审查',
      description: latestAiRun.value
        ? `依据 ${businessBasis.value?.ruleId || latestAiRun.value.ruleVersion} 执行核验，运行状态为 ${latestAiRun.value.status}。`
        : '尚未获取当前节点 AI Run。',
      evidenceLinks: evidenceLinks.value.slice(0, 3)
    },
    {
      title: '人工确认事项',
      conclusion: manualItems.length ? '需人工确认' : '无阻断项',
      description: manualItems.length ? manualItems.join('；') : '当前 AI Run 未返回人工确认事项。',
      evidenceLinks: []
    }
  ]
  return points.map((point, index) => ({
    ...point,
    order: chineseOrder[index] || String(index + 1)
  }))
})
const reviewChainSteps = computed(() => {
  const fieldNames = extractedFields.value.map((field) => field.fieldName).join('、')
  return [
    {
      title: role.value === 'ndt' ? '底片编号与报告一致性' : '证书真实性核验',
      desc:
        latestAiRun.value?.suggestion.opinionDraft ||
        '系统从过程文件中提取关键字段，并与项目要求、规则模板和证据链进行比对。',
      tags: evidenceLinks.value
        .slice(0, 2)
        .map((evidence) => evidence.fieldName || evidence.fileName || '证据'),
      result: latestAiRun.value?.suggestion.result || '待核验'
    },
    {
      title: role.value === 'contractor' ? '关联环节完整性' : '关键字段一致性',
      desc: fieldNames
        ? `已提取 ${fieldNames} 等字段，低置信度和需人工确认项保留在右侧证据链中。`
        : '当前节点暂未返回结构化字段，需等待 OCR 或人工补录后继续核验。',
      tags: extractedFields.value
        .slice(0, 2)
        .map((field) => `${field.fieldName} ${formatConfidence(field.confidence)}`),
      result: extractedFields.value.some((field) =>
        ['低置信度', '置信度未知'].includes(field.reviewStatus)
      )
        ? '需人工确认'
        : '通过'
    },
    {
      title: role.value === 'owner' ? '只读边界核验' : '业务规则适配',
      desc: latestAiRun.value
        ? `规则版本 ${latestAiRun.value.ruleVersion}，Prompt ${latestAiRun.value.promptVersion}。`
        : '规则版本等待节点包加载后展示。',
      tags: latestAiRun.value
        ? [latestAiRun.value.ruleVersion, latestAiRun.value.promptVersion]
        : ['规则待加载'],
      result: latestAiRun.value?.status || '待处理'
    }
  ]
})
const getPillClass = (value?: string): AuditStatusTone => {
  if (!value) return 'blue'
  if (
    value.includes('通过') ||
    value.includes('满足') ||
    value.includes('归档') ||
    value.includes('只读')
  ) {
    return 'green'
  }
  if (
    value.includes('补正') ||
    value.includes('失败') ||
    value.includes('禁止') ||
    value.includes('风险')
  ) {
    return 'red'
  }
  if (
    value.includes('待') ||
    value.includes('AI') ||
    value.includes('草稿') ||
    value.includes('复核') ||
    value.includes('确认')
  ) {
    return 'orange'
  }
  return 'blue'
}
const hasAction = (action: ActionCode) => availableActions.value.includes(action)

const getErrorMessage = (error: unknown) => {
  return getAicheckErrorMessage(error, '接口返回异常，请稍后重试。')
}

const stringifyBusinessReason = (value: unknown) => {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (typeof value !== 'object') return String(value)
  const record = value as {
    message?: unknown
    code?: unknown
    reportId?: unknown
    requirementName?: unknown
  }
  return [record.reportId, record.requirementName, record.message || record.code]
    .filter(Boolean)
    .join('：')
}

const extractBusinessBlockerReasons = (data?: Record<string, unknown>) => {
  if (!data) return []
  const containers = [
    data.evidenceReadiness,
    data.evidenceValidation,
    data.ndtReadiness,
    data.dispatch
  ] as Array<Record<string, unknown> | undefined>
  const reasons: string[] = []
  for (const container of containers) {
    if (!container) continue
    const blockingReasons = container.blockingReasons
    if (Array.isArray(blockingReasons)) {
      reasons.push(...blockingReasons.map(stringifyBusinessReason).filter(Boolean))
    }
    const message = stringifyBusinessReason(container.message || container.statusReason)
    if (message) reasons.push(message)
  }
  return Array.from(new Set(reasons))
}

const rememberActionBlocker = (title: string, message?: string, reasons: string[] = []) => {
  actionBlocker.value = {
    title,
    message,
    reasons: Array.from(new Set(reasons.filter(Boolean)))
  }
}

const showActionError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  const latest = getLatestAicheckBusinessError()
  const data = latest?.data as Record<string, unknown> | undefined
  rememberActionBlocker('操作被业务规则阻断', message, extractBusinessBlockerReasons(data))
  ElMessage.error(message)
}

const showUploadDrawerError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  uploadDrawerError.value = message
  ElMessage.error(message)
}

const uploadMimeByExtension: Record<string, string> = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  zip: 'application/zip'
}

const inferUploadFileType = (file: File) => {
  if (file.type) return file.type
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return uploadMimeByExtension[extension] || 'application/octet-stream'
}

const assertRealUploadTarget = (target: DocumentUploadTarget, file: File) => {
  const url = String(target?.url || '')
  if (!url) throw new Error(`${file.name} 未返回上传地址`)
  if (url.startsWith('mock://')) {
    throw new Error('真实上传地址不可用：后端返回 mock:// 地址，请配置对象存储后重试。')
  }
}

/** 这个上传地址是不是我们自己的 API。
 *
 * 只有自家 API 才需要 JWT。发往对象存储的预签名 URL 绝不能带 Authorization：
 * S3/MinIO 一看到这个头就改用它来鉴权、不再认预签名参数，而 JWT 不是合法的
 * AWS 签名，直接回 400。
 *
 * 2026-08-15 实测就是这么卡住的：服务器侧用同一个预签名 URL curl（不带该头）
 * 返回 200，浏览器带着头 PUT 返回 400 Bad Request。
 */
const isOwnApiUploadTarget = (url: string) =>
  url.startsWith('/api/') || url.startsWith(`${window.location.origin}/api/`)

const uploadFileToSignedUrl = async (target: DocumentUploadTarget, file: File) => {
  assertRealUploadTarget(target, file)
  // 登录态由本地会话补，不再依赖服务端在会话响应里回显 Authorization（M-3）——
  // 把调用方自己的 JWT 写进响应体没有增益，却会随响应进入 devtools、前端日志、
  // 错误上报和网关访问日志。target.headers 仍带本次上传专用的短时凭证。
  const response = await fetch(target.url, {
    method: target.method || 'PUT',
    headers: {
      ...(target.headers || {}),
      ...(isOwnApiUploadTarget(target.url)
        ? { [userStore.getTokenKey ?? 'Authorization']: userStore.getToken ?? '' }
        : {})
    },
    body: file
  })
  if (!response.ok) {
    throw new Error(
      `${file.name} 上传失败：${response.status} ${response.statusText || '存储服务拒绝写入'}`
    )
  }
  const contentType = String(response.headers.get('content-type') || '').toLowerCase()
  if (contentType.includes('application/json')) {
    const payload = (await response.json()) as { code?: number; message?: string }
    if (Number(payload.code ?? 0) !== 0) {
      throw new Error(payload.message || `${file.name} 上传被业务规则拒绝`)
    }
  }
}

const showSubmissionDialogError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  submissionDialogError.value = message
  ElMessage.error(message)
}

const showBindDialogError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  bindDialogError.value = message
  ElMessage.error(message)
}

const showNdtFilmError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  ndtFilmError.value = message
  ElMessage.error(message)
}

const showNdtRecordImportError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  ndtRecordImportError.value = message
  ElMessage.error(message)
}

const showNdtReportUploadError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  ndtReportUploadError.value = message
  ElMessage.error(message)
}

const showNdtSubmitError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  const data = getLatestAicheckBusinessError()?.data as
    | { ndtReadiness?: NdtSubmissionReadiness }
    | undefined
  if (data?.ndtReadiness) ndtReadiness.value = data.ndtReadiness
  ndtSubmitError.value = message
  rememberActionBlocker('无损检测资料提交被阻断', message, extractBusinessBlockerReasons(data))
  ElMessage.error(message)
}

const showNdtRectifyError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  ndtRectifyError.value = message
  ElMessage.error(message)
}

const showReportDetailError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  reportDetailError.value = message
  ElMessage.error(message)
}

const showArchiveDetailError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  archiveDetailError.value = message
  ElMessage.error(message)
}

const showExportTaskError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  exportTaskError.value = message
  ElMessage.error(message)
}

const loadInspectionSubmittedDocuments = async () => {
  if (!activeProjectId.value || role.value !== 'inspection') {
    inspectionSubmittedDocuments.value = undefined
    return
  }
  const res = await getInspectionSubmittedDocumentsApi(activeProjectId.value, {
    keyword: overviewFileKeyword.value.trim() || undefined,
    page: overviewFilePage.value,
    pageSize: overviewFilePageSize.value
  })
  inspectionSubmittedDocuments.value = res?.data
}

const loadInspectionAuditOverview = async () => {
  if (!activeProjectId.value || role.value !== 'inspection') {
    inspectionAuditOverview.value = undefined
    return
  }
  inspectionAuditLoading.value = true
  try {
    const res = await getInspectionAuditOverviewApi(activeProjectId.value, { pageSize: 200 })
    if (!res) {
      inspectionAuditOverview.value = undefined
      inspectionAuditIssue.value = {
        type: 'error',
        title: '审计状态矩阵加载失败',
        message: '节点资料仍可查看，但独立审计项状态暂不可用。'
      }
      return
    }
    inspectionAuditOverview.value = res.data
    inspectionAuditIssue.value = undefined
  } catch (error) {
    inspectionAuditOverview.value = undefined
    inspectionAuditIssue.value = {
      type: 'error',
      title: '审计状态矩阵加载失败',
      message: getErrorMessage(error)
    }
  } finally {
    inspectionAuditLoading.value = false
  }
}

const loadInspectionAuditWorkspace = async (nodeId = activeNodeId.value) => {
  if (!activeProjectId.value || role.value !== 'inspection') {
    inspectionAuditWorkspace.value = undefined
    return
  }
  inspectionAuditLoading.value = true
  try {
    const res = await getInspectionAuditWorkspaceApi(activeProjectId.value, nodeId)
    if (!res) {
      inspectionAuditWorkspace.value = undefined
      inspectionAuditIssue.value = {
        type: 'error',
        title: '审计项目录状态加载失败',
        message: '各审计项仍可切换，状态将在重新加载后恢复。'
      }
      return
    }
    inspectionAuditWorkspace.value = res.data
    if (inspectionAuditOverview.value) {
      const nextRows = inspectionAuditOverview.value.items.map((row) =>
        row.node.nodeId === res.data.node.nodeId
          ? {
              node: res.data.node,
              items: res.data.items,
              latestActivityAt:
                res.data.items
                  .map((item) => item.updatedAt || '')
                  .sort()
                  .at(-1) || undefined
            }
          : row
      )
      const nextStatusCounts = {
        not_started: 0,
        in_progress: 0,
        needs_attention: 0,
        failed: 0,
        completed: 0
      }
      for (const row of nextRows) {
        for (const item of row.items) nextStatusCounts[item.status] += 1
      }
      inspectionAuditOverview.value = {
        ...inspectionAuditOverview.value,
        items: nextRows,
        summary: {
          nodeCount: inspectionAuditOverview.value.total,
          ...nextStatusCounts
        },
        dataAsOf: res.data.dataAsOf
      }
    }
    inspectionAuditIssue.value = undefined
  } catch (error) {
    inspectionAuditWorkspace.value = undefined
    inspectionAuditIssue.value = {
      type: 'error',
      title: '审计项目录状态加载失败',
      message: getErrorMessage(error)
    }
  } finally {
    inspectionAuditLoading.value = false
  }
}

// 同一个节点包正在飞的那次请求。多个入口会在同一轮里各叫一次
// （进场加载、路由 watcher、静默刷新……），实测施工方进场时
// nodes/16/package 连发两次，第二次等了 11.4 秒——两个相同请求打在一起，
// 服务端按顺序处理，后一个白等前一个。
//
// 与其在六千行里追每个触发点（追一个漏一个），不如在请求这层去重。
let inFlightNodePackage: { key: string; promise: Promise<unknown> } | undefined

const loadNodePackage = async (
  nodeId = activeNodeId.value,
  options: LoadNodePackageOptions = {}
) => {
  if (!activeProjectId.value) return
  const requestKey = `${activeProjectId.value}#${nodeId}`
  if (inFlightNodePackage?.key === requestKey) {
    // 复用飞行中的那次；loading 态仍按本次调用的意图设置，
    // 免得静默刷新把界面的 loading 关掉。
    if (!options.silent) nodeLoading.value = true
    try {
      await inFlightNodePackage.promise
    } finally {
      if (!options.silent) nodeLoading.value = false
    }
    return
  }
  if (!options.silent) {
    nodeLoading.value = true
    nodeIssue.value = undefined
  }
  try {
    const request = getNodePackageApi(activeProjectId.value, nodeId)
    // 先登记再 await：登记晚一步，同一轮里的第二次调用就看不到它，去重也就不成立。
    inFlightNodePackage = { key: requestKey, promise: request.catch(() => undefined) }
    const res = await request
    if (!res) {
      if (!options.silent) {
        nodePackage.value = undefined
        standardReferences.value = []
        dateComparisons.value = []
        nodeIssue.value = {
          type: 'forbidden',
          title: '节点资料包加载失败',
          message: getAicheckErrorMessage(
            undefined,
            '接口返回失败，可能是权限不足、节点状态冲突或服务暂不可用。'
          )
        }
      }
      return
    }
    nodePackage.value = res.data
    activeNodeId.value = res.data.node.nodeId
    await Promise.all([
      loadInspectionDetails(res.data.node.nodeId),
      loadInspectionAuditWorkspace(res.data.node.nodeId)
    ])
    await syncActiveReviewHumanInputTask()
  } catch (error) {
    if (!options.silent) {
      nodePackage.value = undefined
      standardReferences.value = []
      dateComparisons.value = []
      nodeIssue.value = {
        type: 'error',
        title: '节点资料包加载失败',
        message: getErrorMessage(error)
      }
    }
  } finally {
    if (!options.silent) nodeLoading.value = false
    if (inFlightNodePackage?.key === requestKey) inFlightNodePackage = undefined
  }
}

const loadInspectionDetails = async (nodeId = activeNodeId.value) => {
  if (!activeProjectId.value || role.value !== 'inspection') {
    standardReferences.value = []
    dateComparisons.value = []
    return
  }
  inspectionDetailLoading.value = true
  try {
    const [standardRes, dateRes] = await Promise.all([
      listInspectionStandardsApi(activeProjectId.value, nodeId),
      getInspectionDateCompareApi(activeProjectId.value, nodeId)
    ])
    if (!standardRes || !dateRes) return
    standardReferences.value = standardRes.data
    dateComparisons.value = dateRes.data
  } catch {
    standardReferences.value = []
    dateComparisons.value = []
    ElMessage.warning('标准依据或日期比对加载失败')
  } finally {
    inspectionDetailLoading.value = false
  }
}

const loadReportArchive = async () => {
  if (!activeProjectId.value) return
  const loaded = await loadRoleScopedReportArchive(role.value, {
    reports: async () => {
      const response = await listOwnerReportsApi(activeProjectId.value)
      if (!response) throw new Error('报告资料加载失败。')
      return response.data
    },
    archiveItems: async () => {
      const response = await listProjectArchiveApi(activeProjectId.value)
      if (!response) throw new Error('归档资料加载失败。')
      return response.data.items
    }
  })
  reports.value = loaded.reports
  archiveItems.value = loaded.archiveItems
}

const loadNdtData = async () => {
  if (!activeProjectId.value || role.value !== 'ndt') {
    ndtFilms.value = []
    ndtRecords.value = []
    ndtReports.value = []
    ndtFeedback.value = []
    ndtFilmError.value = ''
    ndtRecordImportError.value = ''
    ndtReportUploadError.value = ''
    ndtSubmitError.value = ''
    ndtRectifyError.value = ''
    return
  }
  const [filmRes, recordRes, reportRes, feedbackRes] = await Promise.all([
    listNdtFilmsApi(activeProjectId.value),
    listNdtRecordsApi(activeProjectId.value),
    listNdtReportsApi(activeProjectId.value),
    listNdtInspectionFeedbackApi(activeProjectId.value)
  ])
  if (!filmRes || !recordRes || !reportRes || !feedbackRes) {
    throw new Error('无损检测数据加载失败。')
  }
  ndtFilms.value = filmRes.data.items
  ndtRecords.value = recordRes.data.items
  ndtReports.value = reportRes.data.items
  ndtFeedback.value = feedbackRes.data.items
}

const loadQuickAccessData = async () => {
  if (!activeProjectId.value) return
  quickAccessLoading.value = true
  try {
    const [todoRes, messageRes] = await Promise.all([
      listTodosApi({ role: role.value, projectId: activeProjectId.value }),
      listMessagesApi({ projectId: activeProjectId.value })
    ])
    if (!todoRes || !messageRes) return
    quickTodos.value = todoRes.data.items
    quickMessages.value = messageRes.data.items
  } finally {
    quickAccessLoading.value = false
  }
}

const handleQuickSearch = async () => {
  if (!quickAccessKeyword.value.trim()) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  quickAccessLoading.value = true
  try {
    const res = await searchApi({
      keyword: quickAccessKeyword.value.trim(),
      projectId: activeProjectId.value
    })
    if (!res) {
      showActionError('全局搜索失败，请检查关键词和当前项目权限。')
      return
    }
    quickSearchResults.value = res.data.items
  } finally {
    quickAccessLoading.value = false
  }
}

const handleOpenQuickAccess = async (tab: 'search' | 'todos' | 'messages') => {
  quickAccessTab.value = tab
  quickAccessVisible.value = true
  if (!quickAccessKeyword.value) {
    quickAccessKeyword.value = selectedNode.value?.name || currentProject.value?.name || ''
  }
  await loadQuickAccessData()
  if (tab === 'search' && quickAccessKeyword.value.trim()) await handleQuickSearch()
}

const handleCompleteQuickTodo = async (todoId: string) => {
  quickAccessLoading.value = true
  try {
    const todo = quickTodos.value.find((item) => item.id === todoId)
    const res = await completeTodoApi(
      todoId,
      { comment: '从全局入口处理完成。' },
      { etag: todo?.etag }
    )
    if (!res) {
      showActionError('待办处理失败，请刷新待办状态后重试。')
      return
    }
    ElMessage.success('待办已完成')
    await Promise.all([loadQuickAccessData(), loadProjectBundle()])
  } finally {
    quickAccessLoading.value = false
  }
}

const handleReadQuickMessage = async (messageId: string) => {
  quickAccessLoading.value = true
  try {
    const message = quickMessages.value.find((item) => item.id === messageId)
    const res = await markMessageReadApi(messageId, { etag: message?.etag })
    if (!res) {
      showActionError('消息标记已读失败，请刷新消息列表后重试。')
      return
    }
    await Promise.all([loadQuickAccessData(), loadProjectBundle()])
  } finally {
    quickAccessLoading.value = false
  }
}

const handleReadAllQuickMessages = async () => {
  quickAccessLoading.value = true
  try {
    const res = await markAllMessagesReadApi({ projectId: activeProjectId.value }, { etag: '*' })
    if (!res) {
      showActionError('全部消息标记已读失败，请刷新消息列表后重试。')
      return
    }
    ElMessage.success(`已标记 ${res.data.affectedCount} 条消息为已读`)
    await Promise.all([loadQuickAccessData(), loadProjectBundle()])
  } finally {
    quickAccessLoading.value = false
  }
}

const handleLocateQuickResult = async (result: SearchResult) => {
  const params = new URLSearchParams(result.route.split('?')[1] || '')
  const targetProjectId = params.get('projectId')
  const targetNodeId = Number(params.get('nodeId') || result.id)
  if (targetProjectId && targetProjectId !== activeProjectId.value) {
    activeProjectId.value = targetProjectId
    await loadProjectBundle()
  }
  if (result.type === 'node' && Number.isFinite(targetNodeId) && targetNodeId > 0) {
    await loadNodePackage(targetNodeId)
  }
  quickAccessVisible.value = false
  ElMessage.success('已定位到相关业务对象')
}

/** 待办点了要能去处理它，而不只是标记完成。
 *
 * 原来待办列表只有一个「完成」按钮：告诉你「项目资料已提交到资料池，待监检处理」，
 * 却不告诉你去哪处理，也点不过去——用户只能自己回到项目树里翻。
 * 待办上本来就带着 projectId / nodeId，定位逻辑也现成（handleLocateQuickResult）。
 */
/** 消息里的内容也要能点过去。走的是和待办同一套定位——
 *  两套定位逻辑迟早会分叉，而分叉的那天没人会发现。 */
/** 摘要卡片上的「查看明细」。
 *
 * 只处理明确登记过的动作：认不出的 key 什么都不做，也不弹提示——
 * 一个凭空冒出来的动作 key 说明是代码写错了，不该让用户来承担。
 */
const handleSummaryCardAction = async (actionKey: string) => {
  if (actionKey === 'ndt-pending') {
    await nextTick()
    document
      .querySelector('#ndt-pending-files')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const handleOpenQuickMessage = async (message: MessageItem) => {
  await handleOpenQuickTodo({
    id: message.id,
    title: message.title,
    projectId: message.projectId,
    targetType: message.targetType,
    targetId: message.targetId,
    nodeId: message.targetType === 'node' ? Number(message.targetId) : undefined
  } as unknown as TodoItem)
  if (!message.read) void handleReadQuickMessage(message.id)
}

const handleOpenQuickTodo = async (todo: TodoItem) => {
  const targetProjectId = String(todo.projectId || '')
  const targetNodeId = Number(todo.nodeId || 0)
  if (!targetProjectId) {
    ElMessage.warning('这条待办没有关联项目，无法定位。')
    return
  }
  if (targetProjectId !== activeProjectId.value) {
    activeProjectId.value = targetProjectId
    await loadProjectBundle()
  }
  let located = false
  if (Number.isFinite(targetNodeId) && targetNodeId > 0) {
    await loadNodePackage(targetNodeId)
    // 取回节点数据 ≠ 用户看见了它。施工方/建设方这个视图是文件库，
    // 不渲染节点包——线上实测点完提示「已定位」，页面首屏一字未变。
    // 这里让静态视图真的把节点名填进筛选并滚过去，滚不动就如实降级措辞。
    const focus = staticSectionsRef.value?.focusContractorNode
    if (typeof focus === 'function') {
      located = (await focus({ id: targetNodeId, name: nodeDisplayName(targetNodeId) })) === true
    } else {
      located = Boolean(selectedNode.value && Number(selectedNode.value.id) === targetNodeId)
    }
  }
  quickAccessVisible.value = false
  if (targetNodeId > 0 && located) {
    ElMessage.success('已定位到待办对应的节点')
  } else if (targetNodeId > 0) {
    // 宁可说清楚「只切了项目」，也不谎称定位成功——用户会以为自己看漏了。
    ElMessage.warning('已切换到待办所属项目；当前视图无法直接定位到该节点，请在列表中查找。')
  } else {
    ElMessage.success('已切换到待办所属项目（该待办未指向具体节点）')
  }
}

const loadProjectBundle = async (options: LoadProjectBundleOptions = {}) => {
  if (!activeProjectId.value) return
  if (!options.silent) loading.value = true
  try {
    if (!options.silent) pageIssue.value = undefined
    const [contextRes, summaryRes, treeRes] = await Promise.all([
      getWorkbenchContextApi(activeProjectId.value, role.value),
      getWorkbenchSummaryApi(activeProjectId.value, role.value),
      getProjectTreeApi(activeProjectId.value)
    ])
    if (!contextRes || !summaryRes || !treeRes) {
      pageIssue.value = {
        type: 'forbidden',
        title: '工作台加载失败',
        message: getAicheckErrorMessage(
          undefined,
          '接口返回失败，可能是当前角色无权访问或服务暂不可用。'
        )
      }
      return
    }
    context.value = contextRes.data
    summary.value = summaryRes.data
    treeGroups.value = treeRes.data.groups
    if (!options.preserveSelection) {
      activeNodeId.value = contextRes.data.currentNodeId
      activeWorkbenchSection.value =
        role.value === 'inspection' && activeInspectionWorkspaceView.value === 'ai'
          ? 'node'
          : 'overview'
    }
    if (role.value === 'ndt') {
      reports.value = []
      archiveItems.value = []
      inspectionAuditOverview.value = undefined
      inspectionSubmittedDocuments.value = undefined
      await loadNdtData()
    } else {
      await Promise.all([
        loadReportArchive(),
        loadNdtData(),
        loadInspectionAuditOverview(),
        loadInspectionSubmittedDocuments()
      ])
    }
    await loadNodePackage(
      options.preserveSelection ? activeNodeId.value : contextRes.data.currentNodeId
    )
    if (!pageIssue.value) {
      pageIssue.value = undefined
    }
  } catch (error) {
    if (!options.silent) {
      pageIssue.value = {
        type: 'error',
        title: '工作台加载失败',
        message: getErrorMessage(error)
      }
    }
  } finally {
    if (!options.silent) loading.value = false
  }
}

const loadProjects = async () => {
  loading.value = true
  try {
    pageIssue.value = undefined
    const res = await listWorkbenchProjectsApi(role.value)
    if (!res) {
      pageIssue.value = {
        type: 'forbidden',
        title: '项目列表加载失败',
        message: getAicheckErrorMessage(
          undefined,
          '接口返回失败，可能是当前角色无授权项目或服务暂不可用。'
        )
      }
      return
    }
    projectOptions.value = res.data
    if (!res.data.length) {
      activeProjectId.value = ''
      pageIssue.value = {
        type: 'empty',
        title: '暂无授权项目',
        message: '当前角色没有可访问项目，请联系管理员完成项目授权。'
      }
      return
    }
    const requestedProjectId = String(route.query.projectId || '')
    activeProjectId.value =
      res.data.find((project) => project.id === requestedProjectId)?.id || res.data[0]?.id || ''
    const requestedNodeId = Number(route.query.nodeId || 0)
    const preserveRouteSelection =
      role.value === 'inspection' && Number.isFinite(requestedNodeId) && requestedNodeId > 0
    activeInspectionWorkspaceView.value = resolveInspectionWorkspaceView(route.query.view)
    if (preserveRouteSelection) {
      activeNodeId.value = requestedNodeId
      activeWorkbenchSection.value = 'node'
      activeInspectionAuditItem.value = isInspectionAuditItemKey(route.query.auditItem)
        ? route.query.auditItem
        : 'submission'
    }
    await loadProjectBundle({ preserveSelection: preserveRouteSelection })
    if (role.value === 'inspection' && route.query.openFileLibrary === '1') {
      handleOpenBindDialog()
      const nextQuery = { ...route.query }
      delete nextQuery.openFileLibrary
      await router.replace({ path: route.path, query: nextQuery })
    }
    if (role.value === 'inspection' && !route.query.projectId) {
      await updateInspectionRoute(
        preserveRouteSelection || activeInspectionWorkspaceView.value === 'ai'
          ? { nodeId: activeNodeId.value, auditItem: activeInspectionAuditItem.value }
          : { overview: true },
        'replace'
      )
    }
  } catch (error) {
    pageIssue.value = {
      type: 'error',
      title: '项目列表加载失败',
      message: getErrorMessage(error)
    }
  } finally {
    loading.value = false
  }
}

const handleRetryLoad = async () => {
  await loadProjects()
}

const handleRetryNodeLoad = async () => {
  await loadNodePackage(activeNodeId.value)
}

const scrollToRoleFeedbackList = async (elementId: string) => {
  await nextTick()
  document.getElementById(elementId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const stopWorkbenchPageTransition = () => {
  if (workbenchPageTransitionTimer !== undefined) {
    window.clearTimeout(workbenchPageTransitionTimer)
    workbenchPageTransitionTimer = undefined
  }
  workbenchPageTransitionPhase.value = 'idle'
}

const scrollWorkbenchContentToTop = () => {
  const main = workbenchMainRef.value
  if (!main) return

  const mainOverflowY = getComputedStyle(main).overflowY
  const mainOwnsScroll = ['auto', 'scroll'].includes(mainOverflowY)
  if (mainOwnsScroll) {
    main.scrollTo({ top: 0, behavior: 'auto' })
    return
  }

  const viewport = main.closest<HTMLElement>('.aicheck-static-viewport')
  if (!viewport) {
    main.scrollIntoView({ block: 'start', behavior: 'auto' })
    return
  }
  const viewportBox = viewport.getBoundingClientRect()
  const mainBox = main.getBoundingClientRect()
  viewport.scrollTo({
    top: Math.max(0, Math.round(viewport.scrollTop + mainBox.top - viewportBox.top)),
    behavior: 'auto'
  })
}

const waitForWorkbenchLayout = () =>
  new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve())
    })
  })

const runWorkbenchPageTransition = async (activateTargetPage: () => void | Promise<void>) => {
  const sequence = ++workbenchPageTransitionSequence
  stopWorkbenchPageTransition()
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  if (reduceMotion) {
    const targetReady = Promise.resolve(activateTargetPage())
    await nextTick()
    if (sequence !== workbenchPageTransitionSequence) return false
    await waitForWorkbenchLayout()
    if (sequence !== workbenchPageTransitionSequence) return false
    scrollWorkbenchContentToTop()
    await targetReady
    if (sequence !== workbenchPageTransitionSequence) return false
    return true
  }

  workbenchPageTransitionPhase.value = 'leaving'
  await new Promise<void>((resolve) => window.setTimeout(resolve, 300))
  if (sequence !== workbenchPageTransitionSequence) return false

  workbenchPageTransitionPhase.value = 'hidden'
  await nextTick()
  if (sequence !== workbenchPageTransitionSequence) return false
  const targetReady = Promise.resolve(activateTargetPage())
  await nextTick()
  if (sequence !== workbenchPageTransitionSequence) return false
  await waitForWorkbenchLayout()
  if (sequence !== workbenchPageTransitionSequence) return false
  scrollWorkbenchContentToTop()
  workbenchPageTransitionPhase.value = 'entering'
  workbenchPageTransitionTimer = window.setTimeout(() => {
    workbenchPageTransitionTimer = undefined
    if (sequence === workbenchPageTransitionSequence) {
      workbenchPageTransitionPhase.value = 'idle'
    }
  }, 500)
  await targetReady
  if (sequence !== workbenchPageTransitionSequence) return false
  return true
}

const scrollInspectionAuditPanelToTop = async (itemKey: InspectionAuditItemKey) => {
  await nextTick()
  const center = document.querySelector<HTMLElement>('.center.has-flush-audit-directory')
  const directory = center?.querySelector<HTMLElement>('.audit-item-directory__scroll')
  const panel = center?.querySelector<HTMLElement>(`#inspection-audit-panel-${itemKey}`)
  if (!center || !directory || !panel) return

  const viewport = document.querySelector<HTMLElement>('.aicheck-static-viewport')
  const scrollContainer =
    center.scrollHeight > center.clientHeight + 1
      ? center
      : viewport && viewport.scrollHeight > viewport.clientHeight + 1
        ? viewport
        : center
  const containerBox = scrollContainer.getBoundingClientRect()
  const panelBox = panel.getBoundingClientRect()
  const directoryBox = directory.getBoundingClientRect()
  const stickyInset = Number.parseFloat(getComputedStyle(directory).top) || 0
  const targetTop =
    scrollContainer.scrollTop +
    panelBox.top -
    containerBox.top -
    stickyInset -
    directoryBox.height -
    8
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  scrollContainer.scrollTo({
    top: Math.max(0, Math.round(targetTop)),
    behavior: reduceMotion ? 'auto' : 'smooth'
  })
}

const updateInspectionRoute = async (
  target: { nodeId?: number; auditItem?: InspectionAuditItemKey; overview?: boolean },
  mode: 'push' | 'replace' = 'push'
) => {
  if (role.value !== 'inspection') return
  const query: Record<string, string> = {
    projectId: activeProjectId.value,
    view: activeInspectionWorkspaceView.value
  }
  if (!target.overview && target.nodeId) {
    query.nodeId = String(target.nodeId)
    query.auditItem = target.auditItem || activeInspectionAuditItem.value
  }
  const navigation = { path: route.path, query }
  if (mode === 'replace') await router.replace(navigation)
  else await router.push(navigation)
}

const handleInspectionAuditSelect = async (item: InspectionAuditItem) => {
  activeInspectionAuditItem.value = item.key
  inspectionAuditItemByNode.value = {
    ...inspectionAuditItemByNode.value,
    [activeNodeId.value]: item.key
  }
  await scrollInspectionAuditPanelToTop(item.key)
  await updateInspectionRoute({ nodeId: activeNodeId.value, auditItem: item.key })
}

const handleProjectChange = async () => {
  submissionDrafts.value = []
  submissionSnapshots.value = []
  restoredSubmissionDraft.value = undefined
  activeWorkbenchSection.value = 'overview'
  inspectionAuditWorkspace.value = undefined
  if (role.value === 'inspection') {
    await updateInspectionRoute({ overview: true }, 'replace')
  }
  await loadProjectBundle()
}

const handleNodeSelect = async (node: ProjectTreeNode) => {
  mobileTreeOpen.value = false
  const routeItem = isInspectionAuditItemKey(route.query.auditItem)
    ? route.query.auditItem
    : undefined
  const nextAuditItem = inspectionAuditItemByNode.value[node.nodeId] || routeItem || 'submission'
  const switched = await runWorkbenchPageTransition(async () => {
    activeWorkbenchSection.value = 'node'
    activeNodeId.value = node.nodeId
    if (role.value === 'inspection') activeInspectionAuditItem.value = nextAuditItem
    await Promise.all([
      role.value === 'inspection'
        ? updateInspectionRoute({
            nodeId: node.nodeId,
            auditItem: activeInspectionAuditItem.value
          })
        : Promise.resolve(),
      loadNodePackage(node.nodeId)
    ])
  })
  if (!switched) return
  if (role.value === 'contractor') {
    await scrollToRoleFeedbackList('contractor-feedback-list')
  }
  if (role.value === 'ndt') {
    await scrollToRoleFeedbackList('ndt-feedback-list')
  }
}

const handleProjectOverviewSelect = async () => {
  mobileTreeOpen.value = false
  const switched = await runWorkbenchPageTransition(async () => {
    activeInspectionWorkspaceView.value = 'list'
    activeWorkbenchSection.value = 'overview'
    if (role.value === 'inspection') {
      await updateInspectionRoute({ overview: true })
    }
  })
  if (!switched) return
}

/* 节点的七项审计汇成一个状态。缓存按 nodeId——表格渲染每行会取三次
 * （状态词、卡点、进度），不缓存就是每行算三遍。 */
const nodeAggregate = (nodeId: number) =>
  aggregateNodeStatus(inspectionAuditOverviewNodeMap.value.get(nodeId)?.items)

const handleInspectionMatrixSelect = async (
  node: ProjectTreeNode,
  auditItem: InspectionAuditItemKey
) => {
  mobileTreeOpen.value = false
  const switched = await runWorkbenchPageTransition(async () => {
    activeInspectionAuditItem.value = auditItem
    inspectionAuditItemByNode.value = {
      ...inspectionAuditItemByNode.value,
      [node.nodeId]: auditItem
    }
    activeWorkbenchSection.value = 'node'
    activeNodeId.value = node.nodeId
    await Promise.all([
      updateInspectionRoute({ nodeId: node.nodeId, auditItem }),
      loadNodePackage(node.nodeId)
    ])
  })
  if (!switched) return
}

/**
 * 不可逆业务动作的二次确认。
 *
 * 提交、打回、采纳 AI 建议都会推进监检流程且不能简单撤销，需要和删除文件同等的确认。
 * 返回 false 表示用户取消。
 */
const confirmIrreversibleAction = async (options: {
  title: string
  message: string
  confirmText: string
}): Promise<boolean> => {
  try {
    await ElMessageBox.confirm(options.message, options.title, {
      type: 'warning',
      confirmButtonText: options.confirmText,
      cancelButtonText: '再看看'
    })
    return true
  } catch {
    return false
  }
}

const ensureWritableNode = () => {
  if (isReadOnly.value) {
    ElMessage.warning(readonlyIssue.value?.message || '当前项目只读，只能查看、预览或下载。')
    return false
  }
  if (!activeProjectId.value || !selectedNode.value) {
    ElMessage.warning('请先选择项目和节点')
    return false
  }
  return true
}

const ensureWritableProject = () => {
  if (isReadOnly.value) {
    ElMessage.warning(readonlyIssue.value?.message || '当前项目只读，只能查看、预览或下载。')
    return false
  }
  if (!activeProjectId.value) {
    ElMessage.warning('请先选择项目')
    return false
  }
  return true
}

const bindingIds = () => bindings.value.map((item) => item.id)

const openBusinessUrl = (label: string, url?: string) => {
  if (!url) {
    ElMessage.warning(`${label}暂不可用`)
    return
  }
  if (/^https?:\/\//.test(url)) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  ElMessage.success(`${label}已生成：${url}`)
}

const openPreviewDrawer = (target?: Partial<PreviewDrawerTarget>) => {
  previewDrawerTarget.value = {
    source: target?.source || 'node',
    title: target?.title || previewFileName.value,
    url: target?.url,
    meta: target?.meta,
    previewType: target?.previewType
  }
  previewDrawerVisible.value = true
}

const previewTypeForStandard = (fileName?: string): DocumentPreviewPayload['previewType'] => {
  const extension = String(fileName || '')
    .split('.')
    .pop()
    ?.toLowerCase()
  if (extension === 'pdf') return 'pdf'
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(extension || '')) return 'image'
  if (['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(extension || '')) return 'office'
  return 'unsupported'
}

const handleStandardTreeNodeClick = (data: StandardReferenceTreeNode) => {
  if (data.kind !== 'file') return
  if (!data.previewAvailable || !data.previewUrl) {
    ElMessage.warning('该引用尚未关联规范库原文件，请联系知识库管理员补齐文件映射。')
    return
  }
  openPreviewDrawer({
    source: 'standard',
    title: data.fileName || data.reference || data.label,
    url: data.previewUrl,
    previewType: previewTypeForStandard(data.fileName),
    meta: `${data.reference || data.label} · ${data.sourceRelativePath || data.knowledgeFileId || '规范库'}`
  })
}

const handleOpenFileDetail = async (documentId: string) => {
  if (!activeProjectId.value || !documentId) return
  fileDetailVisible.value = true
  fileDetailLoading.value = true
  try {
    const res = await getDocumentDetailApi(activeProjectId.value, documentId)
    if (!res) {
      showActionError('文件详情加载失败，请刷新资料列表后重试。')
      return
    }
    fileDetail.value = res.data
  } finally {
    fileDetailLoading.value = false
  }
}

const handlePreviewFile = (url: string) => {
  openPreviewDrawer({
    source: 'file',
    title: fileDetail.value?.document.fileName || previewFileName.value,
    url,
    previewType: fileDetail.value?.preview?.previewType,
    meta: fileDetail.value?.preview
      ? `${fileDetail.value.preview.contentType || fileDetail.value.document.fileType} · 有效期至 ${
          fileDetail.value.preview.expiresAt
        }`
      : url
  })
}

const revokePreviewDrawerObjectUrl = () => {
  if (!previewDrawerObjectUrl.value) return
  URL.revokeObjectURL(previewDrawerObjectUrl.value)
  previewDrawerObjectUrl.value = ''
}

const loadPreviewDrawerOriginal = async () => {
  revokePreviewDrawerObjectUrl()
  previewDrawerOriginalError.value = ''
  const url = String(previewDrawerTarget.value.url || '')
  if (!previewDrawerRequiresBlob.value) return
  previewDrawerLoadingOriginal.value = true
  try {
    const res = await getDocumentOriginalBlobApi(url)
    previewDrawerObjectUrl.value = URL.createObjectURL(res.data)
  } catch (error) {
    previewDrawerOriginalError.value = getAicheckErrorMessage(
      error,
      '原文预览加载失败，请尝试下载后查看。'
    )
  } finally {
    previewDrawerLoadingOriginal.value = false
  }
}

const handlePreviewDrawerImageError = () => {
  previewDrawerOriginalError.value = '图片预览加载失败，请尝试下载后查看。'
}

const handleDownloadFile = (url: string) => {
  openBusinessUrl('文件下载地址', url)
}

const rememberReadOnlyExportTask = (task?: ExportTask) => {
  if (!task) return
  recentReadOnlyExportTasks.value = [
    task,
    ...recentReadOnlyExportTasks.value.filter((item) => item.id !== task.id)
  ].slice(0, 5)
}

const openLocalArchiveDownloadTask = (item: ArchiveItem) => {
  if (!item.downloadUrl) {
    ElMessage.warning('归档资料下载地址暂不可用')
    return
  }
  const task: ExportTask = {
    id: `DIRECT-${item.id}`,
    projectId: activeProjectId.value,
    exportType: 'document',
    status: '可下载',
    progress: 100,
    fileName: item.name,
    downloadUrl: item.downloadUrl,
    createdAt: item.updatedAt,
    finishedAt: item.updatedAt,
    expiresAt: '签名地址有效期内'
  }
  activeExportTaskId.value = task.id
  exportTaskError.value = ''
  exportTaskLoading.value = false
  exportTask.value = task
  rememberReadOnlyExportTask(task)
  exportTaskVisible.value = true
}

const handleOpenUploadDrawer = (target?: string | NdtAtomicMaterial) => {
  if (!ensureWritableProject()) return
  // 普通上传必须清掉替换目标——不清的话，上一次替换会让这次新传的文件
  // 悄悄覆盖掉那份旧资料，而用户以为自己在新增。
  uploadDrawerReplaceTarget.value = null
  uploadDrawerMode.value = 'project'
  uploadDrawerError.value = ''
  uploadDrawerAtomicMaterial.value = typeof target === 'object' ? target : undefined
  uploadDrawerMaterialCategory.value = uploadDrawerAtomicMaterial.value
    ? '无损检测资料'
    : typeof target === 'string'
      ? target
      : ''
  uploadDrawerVisible.value = true
}

/** 替换某份资料：打开同一个上传抽屉，但这次带着替换目标。 */
const handleReplaceProjectFile = (payload: {
  documentId: string
  fileName: string
  materialCategory: string
}) => {
  if (!ensureWritableProject()) return
  uploadDrawerMode.value = 'project'
  uploadDrawerError.value = ''
  uploadDrawerAtomicMaterial.value = undefined
  uploadDrawerMaterialCategory.value = payload.materialCategory || ''
  uploadDrawerReplaceTarget.value = { documentId: payload.documentId, fileName: payload.fileName }
  uploadDrawerVisible.value = true
}

const handleOpenInspectionUploadDrawer = () => {
  if (!ensureWritableNode()) return
  uploadDrawerMode.value = 'inspection'
  uploadDrawerError.value = ''
  uploadDrawerMaterialCategory.value = '监检现场补充证据'
  uploadDrawerAtomicMaterial.value = undefined
  uploadDrawerVisible.value = true
}

const handleCreateUploadSession = async (files: File[], metadata?: { nodeIds: number[] }) => {
  if (!ensureWritableProject()) return
  if (!files.length) {
    ElMessage.warning('请选择至少一个本地文件')
    return
  }
  actionLoading.value = true
  uploadDrawerError.value = ''
  try {
    if (uploadDrawerReplaceTarget.value && files.length !== 1) {
      // 替换是一对一的：选多个文件却只替换一份，剩下的会被静默丢弃。
      showUploadDrawerError('替换资料时只能选择一个文件。')
      return
    }
    const uploadFiles = files.map((file) => ({
      fileName: file.name,
      fileSize: file.size,
      fileType: inferUploadFileType(file),
      ...(uploadDrawerReplaceTarget.value
        ? { replaceDocumentId: uploadDrawerReplaceTarget.value.documentId }
        : {}),
      ...(uploadDrawerMaterialCategory.value
        ? { materialCategory: uploadDrawerMaterialCategory.value }
        : {}),
      ...(uploadDrawerAtomicMaterial.value
        ? {
            materialTypeCode: uploadDrawerAtomicMaterial.value.code,
            materialTypeName: uploadDrawerAtomicMaterial.value.name,
            nodeIds: metadata?.nodeIds || uploadDrawerAtomicMaterial.value.defaultNodeIds
          }
        : {})
    }))
    const res =
      uploadDrawerMode.value === 'inspection'
        ? await createInspectionAttachmentUploadSessionApi(
            activeProjectId.value,
            activeNodeId.value,
            uploadFiles,
            { etag: currentProject.value?.etag }
          )
        : await createDocumentUploadSessionApi(activeProjectId.value, uploadFiles, {
            etag: currentProject.value?.etag
          })
    if (!res) {
      showUploadDrawerError('上传会话创建失败，请检查文件类型、大小和当前项目权限。')
      return
    }
    if (res.data.uploadUrls.length !== files.length) {
      throw new Error('上传会话返回的文件数量与本地选择不一致，请重新选择文件。')
    }
    await Promise.all(
      files.map((file, index) => uploadFileToSignedUrl(res.data.uploadUrls[index], file))
    )
    const completeRes = await completeDocumentUploadSessionApi(
      activeProjectId.value,
      res.data.uploadSessionId,
      res.data.uploadUrls.map((target, index) => ({
        documentVersionId: target.documentVersionId,
        fileSize: files[index]?.size
      })),
      {
        etag: currentProject.value?.etag,
        idempotencyKey: `document-upload-complete-${res.data.uploadSessionId}`
      }
    )
    if (!completeRes) {
      throw new Error('上传完成确认失败，请刷新项目文件库后重试。')
    }
    if (uploadDrawerMode.value === 'inspection') {
      const bindRes = await bindInspectionDocumentsApi(
        activeProjectId.value,
        activeNodeId.value,
        res.data.uploadUrls.map((target) => ({
          documentId: target.documentId,
          documentVersionId: target.documentVersionId,
          usage: '监检资料'
        })),
        {
          etag: currentProject.value?.etag,
          idempotencyKey: `inspection-upload-bind-${res.data.uploadSessionId}`
        }
      )
      const bindingIds = bindRes?.data.affectedIds || []
      if (bindingIds.length !== files.length) {
        throw new Error('监检文件已上传，但未生成完整的节点挂载关系。')
      }
      const submitRes = await submitInspectionDocumentBindingsApi(
        activeProjectId.value,
        activeNodeId.value,
        {
          bindingIds,
          batchName: `R${String(activeNodeId.value).padStart(2, '0')} 监检资料`,
          submitterComment: '监检人员上传并提交现场或评价证据。'
        },
        {
          etag: currentProject.value?.etag,
          idempotencyKey: `inspection-upload-submit-${res.data.uploadSessionId}`
        }
      )
      if (!submitRes || submitRes.data.bindingIds?.length !== bindingIds.length) {
        throw new Error('监检文件已挂载，但提交快照未包含全部文件。')
      }
      uploadDrawerError.value = ''
      uploadDrawerVisible.value = false
      ElMessage.success(`已上传并提交 ${files.length} 份监检资料`)
      await Promise.all([
        loadProjectBundle(),
        loadInspectionAuditWorkspace(activeNodeId.value),
        loadSubmissionHistory()
      ])
      return
    }
    uploadDrawerError.value = ''
    ElMessage.success(
      uploadDrawerAtomicMaterial.value
        ? `已上传 ${files.length} 个文件并分别保存为草稿，OCR 已异步排队`
        : `已上传 ${files.length} 个文件，OCR 和索引处理已进入队列`
    )
    uploadDrawerVisible.value = false
    await loadProjectBundle()
  } catch (error) {
    showUploadDrawerError('文件上传失败，请检查对象存储、网络连接和当前项目权限。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleReplaceNdtAtomicBindings = async (payload: {
  documentId: string
  nodeIds: number[]
}) => {
  if (!ensureWritableProject()) return
  actionLoading.value = true
  ndtSubmitError.value = ''
  try {
    await replaceNdtAtomicMaterialBindingsApi(
      activeProjectId.value,
      payload.documentId,
      payload.nodeIds,
      { etag: currentProject.value?.etag }
    )
    ElMessage.success('适用业务规则已更新')
    await loadProjectBundle()
  } catch (error) {
    showNdtSubmitError('适用业务规则调整失败，请确认文件仍处于草稿或需补正状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleSubmitNdtAtomicMaterial = async (payload: {
  documentId: string
  bindingIds: string[]
}) => {
  if (!ensureWritableProject()) return
  actionLoading.value = true
  ndtSubmitError.value = ''
  try {
    await submitNdtAtomicMaterialApi(activeProjectId.value, payload, {
      etag: currentProject.value?.etag
    })
    ElMessage.success('该文件已单独提交审批')
    await Promise.all([loadProjectBundle(), loadSubmissionHistory()])
  } catch (error) {
    showNdtSubmitError('单文件提交审批失败，请确认文件仍处于草稿或需补正状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleOpenNdtReportUpload = () => {
  if (!ensureWritableProject()) return
  ndtReportUploadError.value = ''
  ndtReportUploadVisible.value = true
}

const handleCreateNdtReportUpload = async (
  payload: Omit<NdtReportUploadRequest, 'nodeId' | 'files'> & { files: File[] }
) => {
  if (!ensureWritableProject()) return
  if (!payload.files.length) {
    ElMessage.warning('请选择一份检测报告文件')
    return
  }
  actionLoading.value = true
  ndtReportUploadError.value = ''
  try {
    const files = payload.files.map((file) => ({
      fileName: file.name,
      fileSize: file.size,
      fileType: inferUploadFileType(file)
    }))
    const res = await createNdtReportUploadSessionApi(
      activeProjectId.value,
      {
        ...payload,
        nodeId: activeNodeId.value,
        files
      },
      { etag: currentProject.value?.etag }
    )
    if (!res || res.data.uploadUrls.length !== payload.files.length) {
      throw new Error('专用上传会话返回的文件数量与本地选择不一致。')
    }
    await Promise.all(
      payload.files.map((file, index) => uploadFileToSignedUrl(res.data.uploadUrls[index], file))
    )
    const completeRes = await completeNdtReportUploadSessionApi(
      activeProjectId.value,
      res.data.uploadSessionId,
      res.data.uploadUrls.map((target, index) => ({
        documentVersionId: target.documentVersionId,
        fileSize: payload.files[index]?.size
      })),
      {
        etag: currentProject.value?.etag,
        idempotencyKey: `ndt-report-upload-complete-${res.data.uploadSessionId}`
      }
    )
    const createdReports = completeRes?.data.reports || []
    if (createdReports.length !== payload.files.length) {
      throw new Error('报告文件已上传，但后端未生成对应的无损检测报告记录。')
    }
    ndtReportUploadVisible.value = false
    ndtReportUploadError.value = ''
    ElMessage.success(`检测报告 ${createdReports[0]?.reportNo || ''} 已上传并进入 OCR 队列`)
    await Promise.all([loadProjectBundle(), loadNdtData()])
  } catch (error) {
    showNdtReportUploadError('检测报告上传失败，请检查报告字段、关联底片和文件状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleCreateNdtFilm = async (
  payload: {
    filmNo: string
    weldNo: string
    method: NdtFilm['method']
  } & Partial<NdtFilm>
) => {
  if (!activeProjectId.value) return
  if (!payload.filmNo || !payload.weldNo) {
    ElMessage.warning('请填写底片编号和焊口编号')
    return
  }
  actionLoading.value = true
  ndtFilmError.value = ''
  try {
    const res = await createNdtFilmApi(activeProjectId.value, payload, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showNdtFilmError('底片编号新增失败，请检查底片编号、焊口编号和当前节点状态。')
      return
    }
    ndtFilmError.value = ''
    ElMessage.success('底片编号已新增')
    await loadNdtData()
  } catch (error) {
    showNdtFilmError('底片编号新增失败，请检查底片编号、焊口编号和当前节点状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleOpenBindDialog = (documentId?: string) => {
  if (!ensureWritableNode()) return
  bindDialogDocumentId.value = documentId || ''
  bindDialogError.value = ''
  bindDialogVisible.value = true
}

const handleInspectionWorkspaceViewChange = async (view: InspectionWorkspaceView) => {
  activeInspectionWorkspaceView.value = view
  activeWorkbenchSection.value = view === 'ai' ? 'node' : 'overview'
  await updateInspectionRoute(
    activeWorkbenchSection.value === 'overview'
      ? { overview: true }
      : { nodeId: activeNodeId.value, auditItem: activeInspectionAuditItem.value },
    'replace'
  )
}

const handleSubmitProjectFile = async (documentId: string) => {
  if (!ensureWritableProject()) return
  if (!documentId) {
    ElMessage.warning('请选择需要提交的项目文件')
    return
  }
  const file = nodePackage.value?.projectFiles.find((item) => item.id === documentId)
  if (!file) {
    ElMessage.warning('项目文件库中未找到该文件，请刷新后重试')
    return
  }
  const submissionPayload = buildDocumentSubmissionPayload(file)
  if (!submissionPayload) {
    if (file.poolSubmissionStatus === '已提交' && !(file.bindings || []).length) {
      ElMessage.warning('该文件已提交到项目资料池')
    } else if (!file.bindings?.length) {
      ElMessage.warning('当前文件状态不允许提交')
    } else {
      ElMessage.warning('该文件没有待提交或待补正的挂载')
    }
    return
  }
  const isProjectSubmit = submissionPayload.mode === 'project'
  // 与批量提交同一口径：提交是不可逆动作，撤回须另行申请，必须先确认。
  const confirmed = await confirmIrreversibleAction({
    title: '提交资料给监检',
    message: isProjectSubmit
      ? `将把《${file.fileName}》提交到项目资料池，提交后进入监检处理流程，需要撤回时须另行申请。确认提交？`
      : `将把《${file.fileName}》提交到 ${submissionPayload.nodeIds.length} 个审核节点，提交后进入监检审查流程，需要撤回时须另行申请。确认提交？`,
    confirmText: '确认提交'
  })
  if (!confirmed) return
  actionLoading.value = true
  try {
    const res = await submitNodePackageApi(
      activeProjectId.value,
      isProjectSubmit
        ? {
            submissionType: 'project',
            documentIds: submissionPayload.documentIds,
            bindingIds: [],
            nodeIds: [],
            batchName: `${file.fileName} 项目资料池提交`,
            submitterComment: '从项目文件库提交到监检资料池，不关联审核环节。'
          }
        : {
            nodeIds: submissionPayload.nodeIds,
            bindingIds: submissionPayload.bindingIds,
            batchName: `${file.fileName} 多节点文件提交`,
            submitterComment: '从项目文件库提交该文件的全部待提交挂载。'
          },
      {
        etag: currentProject.value?.etag,
        idempotencyKey: isProjectSubmit
          ? `project-pool-submit-${activeProjectId.value}-${documentId}`
          : `project-file-submit-${activeProjectId.value}-${documentId}-${submissionPayload.bindingIds.join('-')}`
      }
    )
    if (!res) {
      showActionError('项目文件提交失败，请检查文件状态、节点范围和当前项目权限。')
      return
    }
    ElMessage.success(
      isProjectSubmit
        ? '项目文件已提交到资料池，等待监检处理'
        : `项目文件已提交至 ${submissionPayload.nodeIds.length} 个审核节点`
    )
    await loadProjectBundle()
    await loadSubmissionHistory()
  } catch (error) {
    showActionError('项目文件提交失败，请检查文件状态、节点范围和当前项目权限。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleRetryProjectFileUpload = async (documentId: string) => {
  if (!ensureWritableProject()) return
  if (!documentId) {
    ElMessage.warning('请选择需要重新上传的项目文件')
    return
  }
  actionLoading.value = true
  try {
    const res = await retryDocumentUploadApi(activeProjectId.value, documentId, {
      etag: currentProject.value?.etag,
      idempotencyKey: `retry-document-upload-${activeProjectId.value}-${documentId}-${Date.now()}`
    })
    if (!res) {
      showActionError('文件重新上传失败，请刷新项目文件库后重试。')
      return
    }
    ElMessage.success('已重新上传，正在处理')
    await loadProjectBundle()
  } catch (error) {
    showActionError('文件重新上传失败，请确认原文件仍然存在。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleDeleteProjectFile = async (documentId: string) => {
  if (!ensureWritableProject()) return
  if (!documentId) {
    ElMessage.warning('请选择需要删除的项目文件')
    return
  }
  try {
    await ElMessageBox.confirm(
      '删除后该文件将从项目文件库移除。仅未提交审核的文件允许删除。',
      '删除未提交文件',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消'
      }
    )
  } catch {
    return
  }
  const removal = removeProjectFileLocally(nodePackage.value, documentId)
  nodePackage.value = removal.packageData
  actionLoading.value = true
  try {
    const res = await deleteProjectDocumentApi(activeProjectId.value, documentId, {
      etag: currentProject.value?.etag,
      idempotencyKey: `project-file-delete-${activeProjectId.value}-${documentId}`
    })
    if (!res) {
      nodePackage.value = restoreProjectFileLocally(nodePackage.value, removal)
      showActionError('项目文件删除失败，请刷新项目文件库后重试。')
      return
    }
    ElMessage.success('未提交文件已删除')
    void loadNodePackage(activeNodeId.value, { silent: true })
  } catch (error) {
    nodePackage.value = restoreProjectFileLocally(nodePackage.value, removal)
    showActionError('项目文件删除失败，仅未提交文件允许删除。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleBindDocuments = async (payload: {
  nodeId?: number
  nodeIds: number[]
  bindings: Array<Pick<NodeFileBinding, 'documentId' | 'documentVersionId' | 'usage'>>
}) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  bindDialogError.value = ''
  try {
    const res = await bindDocumentsToNodeApi(activeProjectId.value, payload, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showBindDialogError('资料挂载失败，请检查资料选择、节点范围和当前项目状态。')
      return
    }
    ElMessage.success(
      role.value === 'contractor'
        ? payload.nodeIds.length > 1
          ? `文件已关联 ${payload.nodeIds.length} 个审核环节`
          : '文件已关联当前审核环节'
        : payload.nodeIds.length > 1
          ? `资料已挂载到 ${payload.nodeIds.length} 个节点`
          : '资料已挂载到当前节点'
    )
    bindDialogVisible.value = false
    bindDialogError.value = ''
    const currentNodeId = activeNodeId.value
    await loadProjectBundle()
    await loadNodePackage(currentNodeId)
  } catch (error) {
    showBindDialogError('资料挂载失败，请检查资料选择、节点范围和当前项目状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleSaveDraft = async () => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  try {
    const res = await saveSubmissionDraftApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        nodeIds: [activeNodeId.value],
        bindingIds: bindingIds(),
        batchName: selectedNode.value
          ? `节点 ${selectedNode.value.nodeId} ${selectedNode.value.name} 提交草稿`
          : undefined,
        remark: '由工作台保存的节点资料提交草稿。'
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('提交草稿保存失败，请检查节点资料和当前项目状态。')
      return
    }
    ElMessage.success('提交草稿已保存')
    await loadSubmissionHistory()
    await openDraftDetail(res.data.draftId)
  } finally {
    actionLoading.value = false
  }
}

const openDraftDetail = async (draftId: string) => {
  if (!activeProjectId.value || !draftId) return
  submissionDetailVisible.value = true
  submissionDetailLoading.value = true
  submissionDetail.value = undefined
  try {
    const res = await getSubmissionDraftDetailApi(activeProjectId.value, draftId)
    if (!res) {
      showActionError('提交草稿详情加载失败，请刷新后重试。')
      return
    }
    submissionDetail.value = res.data
  } finally {
    submissionDetailLoading.value = false
  }
}

const openSubmissionDetail = async (submissionId: string) => {
  if (!activeProjectId.value || !submissionId) return
  submissionDetailVisible.value = true
  submissionDetailLoading.value = true
  submissionDetail.value = undefined
  try {
    const res = await getSubmissionDetailApi(activeProjectId.value, submissionId)
    if (!res) {
      showActionError('提交批次详情加载失败，请刷新后重试。')
      return
    }
    submissionDetail.value = res.data
  } finally {
    submissionDetailLoading.value = false
  }
}

const loadSubmissionHistory = async () => {
  if (!activeProjectId.value) return
  submissionHistoryLoading.value = true
  try {
    const res = await listSubmissionHistoryApi(activeProjectId.value)
    if (!res) {
      showActionError('提交历史加载失败，请刷新项目后重试。')
      return
    }
    submissionDrafts.value = res.data.drafts
    submissionSnapshots.value = res.data.submissions
  } finally {
    submissionHistoryLoading.value = false
  }
}

const handleOpenSubmissionHistory = async () => {
  if (!activeProjectId.value) return
  submissionHistoryVisible.value = true
  await loadSubmissionHistory()
}

const handleRestoreSubmissionDraft = async (draftId: string) => {
  if (!activeProjectId.value || !draftId) return
  submissionHistoryLoading.value = true
  try {
    const res = await getSubmissionDraftDetailApi(activeProjectId.value, draftId)
    if (!res) {
      showActionError('提交草稿恢复失败，请确认草稿是否仍存在。')
      return
    }
    restoredSubmissionDraft.value = res.data
    submissionDialogError.value = ''
    const targetNodeId = res.data.nodeIds[0]
    if (targetNodeId && targetNodeId !== activeNodeId.value) {
      await loadNodePackage(targetNodeId)
    }
    submissionHistoryVisible.value = false
    submissionDialogVisible.value = true
    ElMessage.success('提交草稿已恢复到提交批次弹窗')
  } finally {
    submissionHistoryLoading.value = false
  }
}

const handleOpenSubmissionDialog = () => {
  if (!ensureWritableNode()) return
  restoredSubmissionDraft.value = undefined
  submissionDialogError.value = ''
  submissionDialogVisible.value = true
}

const handleSaveDraftFromDialog = async (payload: {
  nodeIds: number[]
  bindingIds: string[]
  batchName: string
  remark: string
}) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  submissionDialogError.value = ''
  try {
    const res = await saveSubmissionDraftApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        nodeIds: payload.nodeIds,
        bindingIds: payload.bindingIds,
        batchName: payload.batchName,
        remark: payload.remark
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showSubmissionDialogError('提交草稿保存失败，请检查节点范围、资料绑定和当前项目状态。')
      return
    }
    ElMessage.success('提交草稿已保存')
    submissionDialogVisible.value = false
    restoredSubmissionDraft.value = undefined
    submissionDialogError.value = ''
    await loadSubmissionHistory()
    await openDraftDetail(res.data.draftId)
  } catch (error) {
    showSubmissionDialogError('提交草稿保存失败，请检查节点范围、资料绑定和当前项目状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleSubmitBatch = async (payload: {
  nodeIds: number[]
  bindingIds: string[]
  batchName: string
  submitterComment: string
}) => {
  if (!ensureWritableNode()) return
  // 提交后资料进入监检审查流程，撤回需另走接口——比删除未提交文件更不可逆，
  // 理应有同等的二次确认。
  const confirmed = await confirmIrreversibleAction({
    title: '提交资料给监检',
    message: `将提交 ${payload.bindingIds.length} 份资料到 ${payload.nodeIds.length} 个节点，提交后进入监检审查流程，需要撤回时须另行申请。确认提交？`,
    confirmText: '确认提交'
  })
  if (!confirmed) return
  actionLoading.value = true
  submissionDialogError.value = ''
  try {
    const res = await submitNodePackageApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        nodeIds: payload.nodeIds,
        bindingIds: payload.bindingIds,
        batchName: payload.batchName,
        submitterComment: payload.submitterComment
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showSubmissionDialogError('节点资料提交失败，请检查资料绑定、节点状态和当前权限。')
      return
    }
    payload.nodeIds.forEach((nodeId) => {
      latestSubmissionIds.value[nodeId] = res.data.submissionId
    })
    ElMessage.success('节点资料已提交，等待监检核验')
    submissionDialogVisible.value = false
    restoredSubmissionDraft.value = undefined
    submissionDialogError.value = ''
    await loadProjectBundle()
    await loadSubmissionHistory()
    await openSubmissionDetail(res.data.submissionId)
  } catch (error) {
    showSubmissionDialogError('节点资料提交失败，请检查资料绑定、节点状态和当前权限。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleOpenRectificationDialog = (rectificationId?: string) => {
  if (!ensureWritableNode()) return
  activeRectificationId.value = rectificationId || ''
  rectificationDialogVisible.value = true
}

const handleImportNdtRecords = async (payload: { rows: Array<Partial<NdtRecord>> }) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  ndtRecordImportError.value = ''
  try {
    const res = await importNdtRecordsApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        rows: payload.rows
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showNdtRecordImportError('无损检测记录导入失败，请检查记录编号、焊口编号和导入数据。')
      return
    }
    ndtRecordImportError.value = ''
    ElMessage.success(`已导入 ${res.data.imported} 条检测记录`)
    await loadNdtData()
  } catch (error) {
    showNdtRecordImportError('无损检测记录导入失败，请检查记录编号、焊口编号和导入数据。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleRectifyNdt = async (payload: {
  rectificationId: string
  description: string
  reportIds: string[]
  filmIds: string[]
}) => {
  if (!activeProjectId.value) return
  if (!payload.rectificationId || !payload.description) {
    ElMessage.warning('请选择反馈事项并填写补正说明')
    return
  }
  actionLoading.value = true
  ndtRectifyError.value = ''
  try {
    const res = await submitNdtRectificationApi(activeProjectId.value, payload, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showNdtRectifyError('无损检测补正反馈提交失败，请检查反馈事项和补正说明。')
      return
    }
    ndtRectifyError.value = ''
    ElMessage.success('无损检测补正反馈已提交')
    await Promise.all([loadProjectBundle(), loadNdtData()])
  } catch (error) {
    showNdtRectifyError('无损检测补正反馈提交失败，请检查反馈事项和补正说明。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleOpenNdtReportDetail = async (reportId: string) => {
  if (!activeProjectId.value) return
  ndtDetailMode.value = 'report'
  ndtDetailVisible.value = true
  ndtDetailLoading.value = true
  ndtReportDetail.value = undefined
  try {
    const res = await getNdtReportDetailApi(activeProjectId.value, reportId)
    if (!res) {
      showActionError('无损检测报告详情加载失败，请刷新后重试。')
      return
    }
    ndtReportDetail.value = res.data
  } finally {
    ndtDetailLoading.value = false
  }
}

const handleOpenNdtFeedbackDetail = async (feedbackId: string) => {
  if (!activeProjectId.value) return
  ndtDetailMode.value = 'feedback'
  ndtDetailVisible.value = true
  ndtDetailLoading.value = true
  ndtFeedbackDetail.value = undefined
  try {
    const res = await getNdtInspectionFeedbackDetailApi(activeProjectId.value, feedbackId)
    if (!res) {
      showActionError('无损检测反馈详情加载失败，请刷新后重试。')
      return
    }
    ndtFeedbackDetail.value = res.data
  } finally {
    ndtDetailLoading.value = false
  }
}

const handleSubmitRectification = async (payload: {
  comment: string
  bindingIds: string[]
  rectificationId?: string
}) => {
  if (!ensureWritableNode()) return
  if (!payload.comment) {
    ElMessage.warning('请填写补正反馈说明')
    return
  }
  actionLoading.value = true
  try {
    const res = await submitRectificationApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        bindingIds: payload.bindingIds.length ? payload.bindingIds : bindingIds(),
        comment: payload.comment,
        rectificationId: payload.rectificationId || activeRectificationId.value || undefined
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('补正反馈提交失败，请检查补正说明和资料选择。')
      return
    }
    ElMessage.success('补正反馈已提交')
    rectificationDialogVisible.value = false
    activeRectificationId.value = ''
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleAiRecheck = async () => {
  if (!ensureWritableNode()) return
  if (aiRecheckDisabledReason.value) {
    rememberActionBlocker(
      `${selectedAiReviewModeLabel.value}条件不足`,
      aiRecheckDisabledReason.value,
      readinessBlockingReasons.value
    )
    ElMessage.warning(aiRecheckDisabledReason.value)
    return
  }
  aiRecheckOutputVisible.value = true
  aiRecheckOutputError.value = ''
  aiRecheckRunOverride.value = undefined
  actionLoading.value = true
  try {
    const res = await requestAiRecheckApi(
      activeProjectId.value,
      activeNodeId.value,
      { reviewMode: selectedAiReviewMode.value, auditInputMode: 'ocr_llm' },
      {
        etag: currentProject.value?.etag,
        silentBusinessError: true,
        silentHttpError: true
      }
    )
    if (!res) {
      aiRecheckOutputError.value = getAicheckErrorMessage(
        undefined,
        'AI 复核触发失败，请检查是否已有任务运行或当前节点是否允许复核。'
      )
      return
    }
    actionBlocker.value = undefined
    aiRecheckRunOverride.value = res.data.latestRun
    startAiReviewPolling()
    const statusReason = String(res.data.dispatch?.statusReason || '')
    ElMessage.success(
      statusReason
        ? `${selectedAiReviewModeLabel.value}任务已创建：${statusReason}`
        : `${selectedAiReviewModeLabel.value}任务已创建`
    )
    await loadNodePackage(activeNodeId.value)
  } catch (error) {
    aiRecheckOutputError.value = getAicheckErrorMessage(
      error,
      'AI 复核触发失败，请检查是否已有任务运行或当前节点是否允许复核。'
    )
  } finally {
    actionLoading.value = false
  }
}

const handleSaveReviewOpinion = async () => {
  if (!ensureWritableNode()) return
  if (reviewSaveDisabledReason.value) {
    rememberActionBlocker(
      '人工审查意见暂不能保存',
      reviewSaveDisabledReason.value,
      readinessBlockingReasons.value
    )
    ElMessage.warning(reviewSaveDisabledReason.value)
    return
  }
  if (!reviewOpinion.value.trim()) {
    ElMessage.warning('请填写人工审查意见')
    return
  }
  actionLoading.value = true
  try {
    const res = await saveReviewOpinionApi(
      activeProjectId.value,
      activeNodeId.value,
      {
        result: reviewResult.value,
        opinion: reviewOpinion.value.trim(),
        evidenceLinkIds: selectedReviewEvidenceIds.value
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('审查意见保存失败，请检查审查意见和当前节点状态。')
      return
    }
    actionBlocker.value = undefined
    draftRequiresEvidenceSelection.value = false
    ElMessage.success('审查意见已保存')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleAdoptAiSuggestion = async (suggestionId: string) => {
  if (!ensureWritableNode() || !latestAiRun.value) return
  const confirmed = await confirmIrreversibleAction({
    title: '采纳 AI 建议',
    message: `将以 AI 建议「${latestAiRun.value.suggestion.result}」生成人工结论草稿。AI 建议不能替代人工判断，请确认已核对证据与条款依据。`,
    confirmText: '确认采纳'
  })
  if (!confirmed) return
  actionLoading.value = true
  try {
    const aiResult = latestAiRun.value.suggestion.result
    // AI 建议结论 → 人工结论预填，与后端 AI_SUGGESTION_TO_OPINION_RESULT 保持同一口径。
    // 映射不到的建议（需专业判断 / 执行故障待重试）不预填任何值：后端会置
    // requiresResultSelection，由监检人员自己选。切勿兜底成某个具体结论——
    //「需专业判断」意为证据充分但需专业人员定夺，兜底成「证据不足」语义正好相反。
    const AI_RESULT_TO_OPINION: Record<string, ReviewOpinion['result']> = {
      建议满足要求: '满足要求',
      满足要求: '满足要求',
      建议不符合: '需补正',
      需补正: '需补正',
      建议不适用: '不适用',
      不适用: '不适用',
      证据不足: '证据不足'
    }
    const normalizedResult = AI_RESULT_TO_OPINION[aiResult]
    const res = await adoptAiSuggestionApi(
      activeProjectId.value,
      activeNodeId.value,
      suggestionId,
      {
        result: normalizedResult,
        opinion: latestAiRun.value.suggestion.opinionDraft,
        evidenceLinkIds: selectedReviewEvidenceIds.value,
        reason: '采纳 AI 建议作为人工审查草稿。'
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('AI 建议采纳失败，请刷新 AI 建议后重试。')
      return
    }
    reviewResult.value = res.data.draftOpinion.result
    reviewOpinion.value = res.data.draftOpinion.opinion
    selectedReviewEvidenceIds.value = res.data.draftOpinion.evidenceLinkIds || []
    draftRequiresEvidenceSelection.value = Boolean(res.data.draftOpinion.requiresEvidenceSelection)
    activeSideTab.value = 'opinion'
    if (res.data.draftOpinion.requiresEvidenceSelection) {
      rememberActionBlocker(
        'AI 建议已转为草稿，但仍需选择证据',
        '请选择当前节点 confirmed 证据后再保存正式审查意见。'
      )
      activeSideTab.value = 'evidence'
      ElMessage.warning('AI 建议已采纳为草稿，但仍需人工选择 confirmed 证据')
    } else {
      actionBlocker.value = undefined
      ElMessage.success('AI 建议已采纳为审查草稿')
    }
    await loadNodePackage(activeNodeId.value)
  } finally {
    actionLoading.value = false
  }
}

const handleRejectAiSuggestion = async (suggestionId: string) => {
  if (!ensureWritableNode()) return
  let rejectionReason = ''
  try {
    const prompt = await ElMessageBox.prompt(
      '请说明 AI 建议与人工判断不一致的具体原因。该说明会进入审计日志。',
      '驳回 AI 建议',
      {
        confirmButtonText: '确认驳回',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '填写证据、规则或结论方面的差异',
        inputValidator: (value) =>
          value.trim().length >= 4 ? true : '请至少填写 4 个字符的具体原因'
      }
    )
    rejectionReason = prompt.value.trim()
  } catch {
    return
  }
  actionLoading.value = true
  try {
    const res = await rejectAiSuggestionApi(
      activeProjectId.value,
      activeNodeId.value,
      suggestionId,
      {
        reason: rejectionReason,
        manualOpinion: reviewOpinion.value
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('AI 建议驳回失败，请刷新 AI 建议后重试。')
      return
    }
    ElMessage.success('AI 建议已驳回')
    await loadNodePackage(activeNodeId.value)
  } finally {
    actionLoading.value = false
  }
}

const handleLocateEvidence = (evidence: EvidenceLink) => {
  activeEvidence.value = evidence
  evidenceDialogVisible.value = true
}

const handleLocateR12Candidate = (candidate: R12LicenseCandidate) => {
  const linkedEvidence = evidenceLinks.value.find(
    (item) =>
      item.documentVersionId === candidate.documentVersionId &&
      Number(item.pageNo || 1) === Number(candidate.pageNo || 1)
  )
  handleLocateEvidence(
    linkedEvidence || {
      id: `r12-${candidate.candidateId}`,
      projectId: activeProjectId.value,
      nodeId: 12,
      objectType: 'documentVersion',
      objectId: candidate.documentVersionId,
      documentVersionId: candidate.documentVersionId,
      fileName: candidate.fileName,
      pageNo: candidate.pageNo,
      quotedText: candidate.evidence?.quotedText,
      confidence: candidate.evidence?.confidence
    }
  )
}

const handleLocateR19Evidence = (evidence: R19EvidenceCandidate) => {
  if (!evidence.documentVersionId) return
  const linkedEvidence = evidenceLinks.value.find(
    (item) =>
      item.documentVersionId === evidence.documentVersionId &&
      Number(item.pageNo || 1) === Number(evidence.pageNo || 1)
  )
  handleLocateEvidence(
    linkedEvidence || {
      id: evidence.evidenceRefId,
      projectId: activeProjectId.value,
      nodeId: 19,
      objectType: 'documentVersion',
      objectId: evidence.documentVersionId,
      documentVersionId: evidence.documentVersionId,
      fileName: evidence.fileName,
      pageNo: evidence.pageNo || 1,
      quotedText: evidence.quotedText,
      confidence: evidence.confidence
    }
  )
}

const handleSubmitR12HumanInput = async (payload: {
  verifications: R12RegistryVerificationInput[]
  comment?: string
}) => {
  const reviewRunId = aiRecheckDisplayRun.value?.reviewRunId
  const task = activeHumanInputTask.value
  if (!reviewRunId || !task || !humanInputReviewEtag.value) {
    ElMessage.warning('人工核验任务已变化，请刷新后重试')
    return
  }
  humanInputLoading.value = true
  try {
    const res = await submitReviewHumanInputResponseApi(reviewRunId, task.taskId, payload, {
      etag: humanInputReviewEtag.value,
      idempotencyKey: `r12-human-input-${task.taskId}-${task.inputHash}`,
      silentBusinessError: true,
      silentHttpError: true
    })
    if (!res) {
      ElMessage.error('官网核验结果提交失败，请检查必填项或刷新任务')
      return
    }
    activeHumanInputTask.value = null
    humanInputDialogVisible.value = false
    aiRecheckRunOverride.value = undefined
    ElMessage.success('官网核验结果已保存，AI 复核将从暂停位置继续')
    startAiReviewPolling()
    await loadNodePackage(activeNodeId.value, { silent: true })
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, '官网核验结果提交失败，请刷新后重试。'))
  } finally {
    humanInputLoading.value = false
  }
}

const handleSubmitR19HumanInput = async (payload: {
  answers: R19HumanInputAnswer[]
  comment?: string
}) => {
  const reviewRunId = aiRecheckDisplayRun.value?.reviewRunId
  const task = activeHumanInputTask.value
  if (!reviewRunId || !task || !humanInputReviewEtag.value) {
    ElMessage.warning('人工确认任务已变化，请刷新后重试')
    return
  }
  humanInputLoading.value = true
  try {
    const res = await submitReviewHumanInputResponseApi(reviewRunId, task.taskId, payload, {
      etag: humanInputReviewEtag.value,
      idempotencyKey: `r19-human-input-${task.taskId}-${task.inputHash}`,
      silentBusinessError: true,
      silentHttpError: true
    })
    if (!res) {
      ElMessage.error('R19 人工确认提交失败，请检查必填项或刷新任务')
      return
    }
    activeHumanInputTask.value = null
    humanInputDialogVisible.value = false
    aiRecheckRunOverride.value = undefined
    ElMessage.success('R19 人工确认已保存，AI 将从暂停位置恢复语义审核')
    startAiReviewPolling()
    await loadNodePackage(activeNodeId.value, { silent: true })
  } catch (error) {
    ElMessage.error(getAicheckErrorMessage(error, 'R19 人工确认提交失败，请刷新后重试。'))
  } finally {
    humanInputLoading.value = false
  }
}

const handleConfirmEvidence = async (evidence: EvidenceLink) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  try {
    const res = await confirmNodeEvidenceLinkApi(
      activeProjectId.value,
      activeNodeId.value,
      evidence.id,
      { comment: '监检人员确认采用该证据。' },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('证据确认失败，请刷新后重试。')
      return
    }
    ElMessage.success('证据已确认')
    await loadNodePackage(activeNodeId.value, { silent: true })
  } finally {
    actionLoading.value = false
  }
}

const handleRejectEvidence = async (evidence: EvidenceLink) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  try {
    const res = await rejectNodeEvidenceLinkApi(
      activeProjectId.value,
      activeNodeId.value,
      evidence.id,
      { comment: '监检人员不采用该候选证据。' },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('证据不采用失败，请刷新后重试。')
      return
    }
    ElMessage.success('已标记为不采用')
    await loadNodePackage(activeNodeId.value, { silent: true })
  } finally {
    actionLoading.value = false
  }
}

const handleReturnCorrection = async () => {
  if (!ensureWritableNode()) return
  if (!correctionReason.value.trim()) {
    ElMessage.warning('请填写退回补正原因')
    return
  }
  const submittedBindingIds = bindings.value
    .filter((binding) => binding.bindingStatus === '已提交')
    .map((binding) => binding.id)
  if (!submittedBindingIds.length) {
    ElMessage.warning('当前节点没有可退回的已提交资料')
    return
  }
  const confirmed = await confirmIrreversibleAction({
    title: '退回补正',
    message: `将退回 ${submittedBindingIds.length} 份已提交资料并通知施工方整改，节点状态转为「需补正」。确认退回？`,
    confirmText: '确认退回'
  })
  if (!confirmed) return
  actionLoading.value = true
  try {
    const res = await returnCorrectionApi(
      activeProjectId.value,
      activeNodeId.value,
      {
        reason: correctionReason.value.trim(),
        bindingIds: submittedBindingIds,
        evidenceLinkIds: evidenceLinks.value.map((item) => item.id)
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('退回补正失败，请检查补正原因和节点权限。')
      return
    }
    ElMessage.success('已退回施工方补正')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleGenerateReport = async (payload: {
  includeEvidence: boolean
  reportScope: ReportVersion['scope']
}) => {
  if (!ensureWritableNode()) return
  if (reportGenerateDisabledReason.value) {
    rememberActionBlocker('报告草稿暂不能生成', reportGenerateDisabledReason.value)
    ElMessage.warning(reportGenerateDisabledReason.value)
    return
  }
  actionLoading.value = true
  try {
    const res = await generateReportReviewApi(
      activeProjectId.value,
      activeNodeId.value,
      {
        includeEvidence: payload.includeEvidence,
        reportScope: payload.reportScope,
        reviewerNote: '由工作台发起报告草稿生成。'
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('报告草稿生成失败，请检查节点审查状态和报告范围。')
      return
    }
    actionBlocker.value = undefined
    ElMessage.success('报告草稿已生成，进入复核')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleExportReport = async (reportId: string) => {
  if (!activeProjectId.value) return
  actionLoading.value = true
  try {
    const res = await exportReportApi(
      activeProjectId.value,
      reportId,
      { format: 'pdf' },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('报告导出任务创建失败，请检查报告状态和导出权限。')
      return
    }
    ElMessage.success('报告导出任务已创建')
    await loadReportArchive()
    await handleOpenExportTask(res.data.exportId)
  } finally {
    actionLoading.value = false
  }
}

const handlePreviewReport = (reportId: string) => {
  const report = reports.value.find((item) => item.id === reportId)
  if (!report?.previewUrl) {
    ElMessage.warning('报告预览地址暂不可用')
    return
  }
  openPreviewDrawer({
    source: 'report',
    title: report.title || report.reportNo,
    url: report.previewUrl,
    meta: `${report.reportNo} · ${report.versionNo} · ${report.status}`
  })
}

const handleOpenReportDetail = async (reportId: string) => {
  if (!activeProjectId.value) return
  activeReportDetailId.value = reportId
  reportDetailVisible.value = true
  reportDetailLoading.value = true
  reportDetailError.value = ''
  reportDetail.value = undefined
  try {
    const res = await getReportDetailApi(activeProjectId.value, reportId)
    if (!res) {
      showReportDetailError('报告详情加载失败，请刷新报告列表后重试。')
      return
    }
    reportDetailError.value = ''
    reportDetail.value = res.data
  } catch (error) {
    showReportDetailError('报告详情加载失败，请刷新报告列表后重试。', error)
  } finally {
    reportDetailLoading.value = false
  }
}

const handleOpenArchiveItemDetail = async (archiveItemId: string) => {
  if (!activeProjectId.value) return
  activeArchiveItemId.value = archiveItemId
  archiveDetailVisible.value = true
  archiveDetailLoading.value = true
  archiveDetailError.value = ''
  archiveDetail.value = undefined
  try {
    const res = await getArchiveItemDetailApi(activeProjectId.value, archiveItemId)
    if (!res) {
      showArchiveDetailError('归档资料详情加载失败，请刷新归档列表后重试。')
      return
    }
    archiveDetailError.value = ''
    archiveDetail.value = res.data
  } catch (error) {
    showArchiveDetailError('归档资料详情加载失败，请刷新归档列表后重试。', error)
  } finally {
    archiveDetailLoading.value = false
  }
}

const handleOpenExportTask = async (exportId: string) => {
  if (!activeProjectId.value || !exportId) return
  const cachedTask = recentReadOnlyExportTasks.value.find((task) => task.id === exportId)
  if (cachedTask?.id.startsWith('DIRECT-')) {
    activeExportTaskId.value = exportId
    exportTaskVisible.value = true
    exportTaskLoading.value = false
    exportTaskError.value = ''
    exportTask.value = cachedTask
    return
  }
  activeExportTaskId.value = exportId
  exportTaskVisible.value = true
  exportTaskLoading.value = true
  exportTaskError.value = ''
  exportTask.value = undefined
  try {
    const res = await getExportTaskApi(activeProjectId.value, exportId)
    if (!res) {
      showExportTaskError('导出任务详情加载失败，请刷新后重试。')
      return
    }
    exportTaskError.value = ''
    exportTask.value = res.data.task
    rememberReadOnlyExportTask(res.data.task)
  } catch (error) {
    showExportTaskError('导出任务详情加载失败，请刷新后重试。', error)
  } finally {
    exportTaskLoading.value = false
  }
}

const handleRetryReportDetail = () => {
  if (activeReportDetailId.value) handleOpenReportDetail(activeReportDetailId.value)
}

const handleSaveReportDetail = async (payload: { sections: ReportSection[]; remark?: string }) => {
  if (!activeProjectId.value || !reportDetail.value?.report) return
  actionLoading.value = true
  const reportId = reportDetail.value.report.id
  try {
    const res = await updateReportApi(activeProjectId.value, reportId, payload, {
      etag: reportDetail.value.report.etag
    })
    if (!res) {
      showReportDetailError('报告保存失败，请检查章节内容和证据引用。')
      return
    }
    ElMessage.success('报告内容已保存')
    await handleOpenReportDetail(reportId)
    await loadReportArchive()
  } catch (error) {
    showReportDetailError('报告保存失败，请检查章节内容和证据引用。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleTransitionReport = async (status: '复核完成' | '已签发') => {
  if (!activeProjectId.value || !reportDetail.value?.report) return
  const report = reportDetail.value.report
  let reason = ''
  try {
    const prompt = await ElMessageBox.prompt(
      `确认将报告“${report.reportNo}”变更为“${status}”吗？请填写处理说明。`,
      status === '已签发' ? '签发报告' : '完成报告复核',
      {
        type: status === '已签发' ? 'warning' : 'info',
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        inputPlaceholder: '填写复核结论、签发依据或工单号',
        inputValidator: (value) => Boolean(value.trim()) || '必须填写处理说明'
      }
    )
    reason = prompt.value.trim()
  } catch {
    return
  }
  actionLoading.value = true
  try {
    const response = await updateReportApi(
      activeProjectId.value,
      report.id,
      { status, remark: reason },
      { etag: report.etag }
    )
    if (!response) {
      showReportDetailError('报告状态更新失败，请刷新后重试。')
      return
    }
    ElMessage.success(status === '已签发' ? '报告已签发' : '报告复核已完成')
    await handleOpenReportDetail(report.id)
    await loadReportArchive()
  } catch (error) {
    showReportDetailError('报告状态更新失败，请检查证据校验和当前状态。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleRetryArchiveDetail = () => {
  if (activeArchiveItemId.value) handleOpenArchiveItemDetail(activeArchiveItemId.value)
}

const handleRetryExportTask = () => {
  if (activeExportTaskId.value) handleOpenExportTask(activeExportTaskId.value)
}

const handleDownloadArchiveItem = (item: ArchiveItem) => {
  openLocalArchiveDownloadTask(item)
}

const handlePreviewArchiveUrl = (url: string) => {
  openPreviewDrawer({
    source: 'archive',
    title: archiveDetail.value?.item.name || '归档资料预览',
    url,
    meta: archiveDetail.value?.preview
      ? `${archiveDetail.value.preview.contentType || '归档资料'} · 有效期至 ${
          archiveDetail.value.preview.expiresAt
        }`
      : url
  })
}

const handleDownloadUrl = (url: string) => {
  openBusinessUrl('下载地址', url)
}

const exportManifestHint = (hash?: string) => (hash ? ` · ${hash.slice(0, 18)}` : '')

const handleDownloadArchivePackage = async () => {
  if (!activeProjectId.value) return
  actionLoading.value = true
  try {
    const res = await getArchivePackageApi(activeProjectId.value)
    if (!res) {
      showActionError('归档包生成失败，请检查项目归档状态和下载权限。')
      return
    }
    ElMessage.success(
      `归档包导出任务已创建（${res.data.itemCount} 项${exportManifestHint(res.data.manifestHash)}）`
    )
    await handleOpenExportTask(res.data.exportId)
  } finally {
    actionLoading.value = false
  }
}

const handleDownloadEvidencePackage = async (payload?: { reportId?: string }) => {
  if (!activeProjectId.value) return
  const params = payload?.reportId ? { reportId: payload.reportId } : { nodeId: activeNodeId.value }
  if (!params.reportId && !params.nodeId) {
    ElMessage.warning('请先选择节点或报告后再生成证据定位包')
    return
  }
  actionLoading.value = true
  try {
    const res = await getEvidencePackageApi(activeProjectId.value, params)
    if (!res) {
      showActionError('证据定位包生成失败，请检查节点证据和下载权限。')
      return
    }
    ElMessage.success(
      `证据包导出任务已创建（${res.data.itemCount} 项${exportManifestHint(res.data.manifestHash)}）`
    )
    await handleOpenExportTask(res.data.exportId)
  } finally {
    actionLoading.value = false
  }
}

const handleArchiveReport = async (reportId: string) => {
  if (!activeProjectId.value) return
  actionLoading.value = true
  try {
    const currentReport =
      reportDetail.value?.report?.id === reportId
        ? reportDetail.value.report
        : reports.value.find((item) => item.id === reportId)
    const res = await archiveReportApi(
      activeProjectId.value,
      reportId,
      {
        archiveNote: '由监检工作台确认归档。'
      },
      { etag: currentReport?.etag }
    )
    if (!res) {
      showActionError('报告归档失败，请检查报告状态和项目权限。')
      return
    }
    actionBlocker.value = undefined
    ElMessage.success('报告已归档，项目进入只读状态')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const aiReviewTerminalStatuses = new Set([
  '完成',
  '失败',
  '已人工确认',
  '已驳回',
  '已取消',
  'cancelled',
  'waiting_human_review',
  'accepted_by_human',
  'edited_by_human',
  'rejected_by_human',
  'failed',
  'failed_to_start'
])

const refreshAiReviewStatus = async () => {
  if (!activeProjectId.value || reviewPolling.value) return
  const run = aiRecheckDisplayRun.value
  if (!run || aiReviewTerminalStatuses.has(String(run.status || ''))) {
    stopAiReviewPolling()
    return
  }
  reviewPolling.value = true
  try {
    // 先用轻量状态接口探活（约为完整节点包的 0.4%）。只有 AI 运行状态真的变了，
    // 才去重拉完整数据——否则每次轮询都整体替换数据会让页面反复重绘。
    const live = await getNodeLiveStatusApi(activeProjectId.value, activeNodeId.value)
    const liveStatus = String(live?.data?.latestAiRun?.status || '')
    if (!liveStatus) {
      stopAiReviewPolling()
      return
    }
    if (liveStatus === String(run.status || '')) return
    await loadNodePackage(activeNodeId.value, { silent: true })
    aiRecheckRunOverride.value = undefined
    const refreshed = latestAiRun.value
    if (!refreshed || aiReviewTerminalStatuses.has(String(refreshed.status || ''))) {
      stopAiReviewPolling()
    }
  } catch (error) {
    aiRecheckOutputError.value = getAicheckErrorMessage(error, 'AI 复核状态刷新失败，将继续重试。')
  } finally {
    reviewPolling.value = false
  }
}

/* 不做定时轮询：稳态下没有东西在变，隔几秒刷一次只是在制造「页面自己在动」的
 * 观感，也让每次刷新都要重新拉节点包。改为「用户发起动作后单次补一刀」——
 * AI 复核是异步的，触发后延迟一次拉取即可看到结果；还没出结果时用户可以
 * 切走再切回来，那本身就会重新加载。 */
const startAiReviewPolling = () => {
  if (reviewPollTimer.value) return
  reviewPollTimer.value = window.setTimeout(() => {
    reviewPollTimer.value = undefined
    if (document.visibilityState === 'hidden') return
    void refreshAiReviewStatus()
  }, REVIEW_RECHECK_DELAY_MS)
}

const stopAiReviewPolling = () => {
  if (!reviewPollTimer.value) return
  window.clearTimeout(reviewPollTimer.value)
  reviewPollTimer.value = undefined
}

const lastProcessingCount = ref<number | undefined>(undefined)

const refreshPostUploadPipelineStatus = async () => {
  if (!activeProjectId.value || pipelinePolling.value) return
  if (!hasPostUploadProcessing.value) {
    stopPostUploadPolling()
    return
  }
  pipelinePolling.value = true
  try {
    // 同 refreshAiReviewStatus：先轻量探活，处理中的文件数没变就不重拉全量数据。
    const live = await getNodeLiveStatusApi(activeProjectId.value, activeNodeId.value)
    const count = live?.data?.processingDocumentCount
    if (typeof count === 'number' && count === lastProcessingCount.value) return
    lastProcessingCount.value = count
    await loadNodePackage(activeNodeId.value, { silent: true })
    if (count === 0) stopPostUploadPolling()
  } finally {
    pipelinePolling.value = false
  }
}

const startPostUploadPolling = () => {
  if (pipelinePollTimer.value) return
  pipelinePollTimer.value = window.setTimeout(() => {
    pipelinePollTimer.value = undefined
    void refreshPostUploadPipelineStatus()
  }, POST_UPLOAD_PIPELINE_RECHECK_DELAY_MS)
}

const stopPostUploadPolling = () => {
  if (!pipelinePollTimer.value) return
  window.clearTimeout(pipelinePollTimer.value)
  pipelinePollTimer.value = undefined
}

watch(
  () => role.value,
  () => {
    loadProjects()
  }
)

watch(
  () =>
    [route.query.projectId, route.query.nodeId, route.query.auditItem, route.query.view] as const,
  async ([projectIdQuery, nodeIdQuery, auditItemQuery, viewQuery]) => {
    if (
      role.value !== 'inspection' ||
      inspectionRouteSyncing.value ||
      !projectOptions.value.length
    ) {
      return
    }
    const targetProjectId = String(projectIdQuery || activeProjectId.value)
    if (!projectOptions.value.some((project) => project.id === targetProjectId)) return
    const parsedNodeId = Number(nodeIdQuery || 0)
    const targetNodeId = Number.isFinite(parsedNodeId) && parsedNodeId > 0 ? parsedNodeId : 0
    const targetItem = isInspectionAuditItemKey(auditItemQuery) ? auditItemQuery : 'submission'
    activeInspectionWorkspaceView.value = resolveInspectionWorkspaceView(viewQuery)

    inspectionRouteSyncing.value = true
    try {
      if (targetProjectId !== activeProjectId.value) {
        activeProjectId.value = targetProjectId
        activeNodeId.value = targetNodeId || activeNodeId.value
        activeWorkbenchSection.value = targetNodeId ? 'node' : 'overview'
        activeInspectionAuditItem.value = targetItem
        await loadProjectBundle({ preserveSelection: Boolean(targetNodeId) })
        return
      }
      if (!targetNodeId) {
        activeWorkbenchSection.value =
          activeInspectionWorkspaceView.value === 'ai' ? 'node' : 'overview'
        return
      }
      activeWorkbenchSection.value = 'node'
      activeInspectionAuditItem.value = targetItem
      inspectionAuditItemByNode.value = {
        ...inspectionAuditItemByNode.value,
        [targetNodeId]: targetItem
      }
      if (targetNodeId !== activeNodeId.value) {
        activeNodeId.value = targetNodeId
        await loadNodePackage(targetNodeId)
      }
    } finally {
      inspectionRouteSyncing.value = false
    }
  }
)

watch(
  () => activeNodeId.value,
  () => {
    stopAiReviewPolling()
    aiRecheckOutputVisible.value = false
    aiRecheckRunOverride.value = undefined
    aiRecheckOutputError.value = ''
  }
)

watch(
  () => String(aiRecheckDisplayRun.value?.status || ''),
  (status) => {
    if (status && !aiReviewTerminalStatuses.has(status)) {
      startAiReviewPolling()
    } else {
      stopAiReviewPolling()
    }
  },
  { immediate: true }
)

watch(
  () => availableAiReviewModes.value.join('|'),
  () => {
    if (availableAiReviewModes.value.includes(selectedAiReviewMode.value)) return
    selectedAiReviewMode.value = availableAiReviewModes.value.includes('formal')
      ? 'formal'
      : 'gap_precheck'
  },
  { immediate: true }
)

watch(
  () => overviewFileKeyword.value,
  () => {
    if (overviewFilePage.value !== 1) {
      overviewFilePage.value = 1
      return
    }
    void loadInspectionSubmittedDocuments()
  }
)

watch(
  () => [overviewFilePage.value, overviewFilePageSize.value] as const,
  () => {
    void loadInspectionSubmittedDocuments()
  }
)

watch(
  () => activeNodeId.value,
  () => {
    actionBlocker.value = undefined
    ndtReadiness.value = undefined
    selectedReviewEvidenceIds.value = []
    draftRequiresEvidenceSelection.value = false
  }
)

watch(
  () => confirmedEvidenceLinks.value.map((item) => item.id).join('|'),
  () => {
    const allowed = confirmedEvidenceIds.value
    selectedReviewEvidenceIds.value = selectedReviewEvidenceIds.value.filter((id) =>
      allowed.has(id)
    )
    if (!selectedReviewEvidenceIds.value.length && confirmedEvidenceLinks.value.length) {
      selectedReviewEvidenceIds.value = confirmedEvidenceLinks.value.map((item) => item.id)
    }
  },
  { immediate: true }
)

watch(
  () => [inspectionVisibleNodeRows.value.length, inspectionNodePageSize.value] as const,
  ([total, pageSize]) => {
    const maxPage = Math.max(1, Math.ceil(total / pageSize))
    if (inspectionNodePage.value > maxPage) inspectionNodePage.value = maxPage
  }
)

watch(
  () => bindDialogVisible.value,
  (open) => {
    if (!open) {
      bindDialogError.value = ''
      bindDialogDocumentId.value = ''
    }
  }
)

watch(
  () => rectificationDialogVisible.value,
  (open) => {
    if (!open) activeRectificationId.value = ''
  }
)

watch(
  () => uploadDrawerVisible.value,
  (open) => {
    if (!open) {
      uploadDrawerError.value = ''
      uploadDrawerMaterialCategory.value = ''
      uploadDrawerAtomicMaterial.value = undefined
    }
  }
)

watch(
  () => ndtReportUploadVisible.value,
  (open) => {
    if (!open) ndtReportUploadError.value = ''
  }
)

watch(
  () => submissionDialogVisible.value,
  (open) => {
    if (!open) {
      restoredSubmissionDraft.value = undefined
      submissionDialogError.value = ''
    }
  }
)

watch(
  () =>
    [
      previewDrawerVisible.value,
      previewDrawerTarget.value.url,
      previewDrawerTarget.value.previewType
    ] as const,
  ([open]) => {
    if (open) {
      void loadPreviewDrawerOriginal()
    } else {
      revokePreviewDrawerObjectUrl()
      previewDrawerOriginalError.value = ''
    }
  }
)

watch(
  () => hasPostUploadProcessing.value,
  (processing) => {
    if (processing) {
      startPostUploadPolling()
    } else {
      stopPostUploadPolling()
    }
  },
  { immediate: true }
)

onMounted(() => {
  syncCompactNodeNavigation()
  window.addEventListener('resize', syncCompactNodeNavigation)
  loadProjects()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncCompactNodeNavigation)
  workbenchPageTransitionSequence += 1
  stopWorkbenchPageTransition()
  stopPostUploadPolling()
  stopAiReviewPolling()
  revokePreviewDrawerObjectUrl()
})
</script>

<template>
  <div class="aicheck-static-viewport" v-loading="loading">
    <div
      :class="[
        'aicheck-page',
        'app-shell',
        {
          'is-inspection-ai-page':
            role === 'inspection' &&
            activeInspectionWorkspaceView === 'ai' &&
            activeWorkbenchSection === 'node'
        }
      ]"
    >
      <a class="skip-main" href="#aicheck-workbench-main">跳到主内容</a>
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">盾</div>
          <ElSelect
            v-model="activeProjectId"
            class="project-select project-title-select"
            filterable
            aria-label="当前项目"
            :disabled="!projectOptions.length"
            @change="handleProjectChange"
          >
            <ElOption
              v-for="project in projectOptions"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </ElSelect>
          <div :class="['top-status', `pill-${getPillClass(topbarStatus)}`]">
            {{ topbarStatus }}
          </div>
        </div>
        <ElButton class="global-search" @click="handleOpenQuickAccess('search')">
          {{ globalSearchPlaceholder }}
        </ElButton>
        <div class="top-actions">
          <ElButton class="top-action" text @click="handleOpenQuickAccess('todos')">
            待办消息<span v-if="quickAccessNotificationCount" class="notice-dot">
              {{ quickAccessNotificationCount }}
            </span>
          </ElButton>
          <!-- 视图切换做成分段控件，而不是两个并排的文字按钮。
               原先它们长得像动作按钮（还带魔法棒图标），而 AI 视图又是监检的
               默认视图——用户进来就在 AI 视图里，再点「AI审查」是合法的无操作，
               界面却零反馈，看上去就是「点了没用」。实测反馈过这个问题。
               分段控件在视觉上直接表达「二选一」，选中态一望即知。

               另一侧原先叫「文件列表」，而它其实是完整的传统工作台（审计项状态
               总览 + 节点处理清单 + 已提交资料）。名不副实，导致进了 AI 视图的人
               找不到回去的路——实测就有人问「怎么切换回传统视图」。改叫「完整工作台」。 -->
          <div
            v-if="role === 'inspection'"
            class="view-segmented"
            role="tablist"
            aria-label="监检工作台视图"
          >
            <button
              type="button"
              role="tab"
              :aria-selected="activeInspectionWorkspaceView === 'ai'"
              :class="['view-segment', { 'is-active': activeInspectionWorkspaceView === 'ai' }]"
              @click="handleInspectionWorkspaceViewChange('ai')"
            >
              <ElIcon><MagicStick /></ElIcon>
              AI审查
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="activeInspectionWorkspaceView === 'list'"
              :class="['view-segment', { 'is-active': activeInspectionWorkspaceView === 'list' }]"
              @click="handleInspectionWorkspaceViewChange('list')"
            >
              完整工作台
            </button>
          </div>
          <ElDropdown trigger="click" class="user-menu" @command="handleUserCommand">
            <button class="user" type="button" aria-label="打开用户菜单">
              <span class="avatar"></span>
              <span>{{ roleUserLabel }}</span>
              <span class="user-caret">⌄</span>
            </button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem disabled>{{ roleUserLabel }}</ElDropdownItem>
                <ElDropdownItem command="logout" divided>退出登录</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </header>

      <div v-if="pageIssue" class="static-issue">
        <WorkbenchStateBanner
          :type="pageIssue.type"
          :title="pageIssue.title"
          :message="pageIssue.message"
          action-label="重新加载"
          @action="handleRetryLoad"
        />
      </div>

      <div
        v-else-if="canShowWorkspace"
        :class="[
          'workspace',
          {
            'no-left-nav': role === 'contractor' || role === 'ndt',
            'is-left-collapsed': desktopTreeCollapsed && role !== 'contractor' && role !== 'ndt'
          }
        ]"
      >
        <aside
          v-if="role !== 'contractor' && role !== 'ndt' && !compactNodeNavigation"
          id="audit-node-navigation"
          :class="['left', { 'is-collapsed': desktopTreeCollapsed }]"
        >
          <section
            id="audit-node-navigation-content"
            class="tree-wrap"
            :aria-hidden="desktopTreeCollapsed"
            :inert="desktopTreeCollapsed"
          >
            <div class="section-title">
              <span>项目审核节点</span>
              <span v-if="role === 'owner'" class="section-tools">只读</span>
            </div>
            <ProjectNodeTree
              :groups="visibleTreeGroups"
              :active-node-id="activeWorkbenchSection === 'overview' ? 0 : activeNodeId"
              :show-overview="true"
              empty-description="暂无项目审核节点"
              @select="handleNodeSelect"
              @select-overview="handleProjectOverviewSelect"
            />
          </section>
          <ElButton
            class="sidebar-collapse-toggle"
            circle
            :aria-label="desktopTreeCollapsed ? '展开节点导航' : '收起节点导航'"
            aria-controls="audit-node-navigation-content"
            :aria-expanded="!desktopTreeCollapsed"
            :title="desktopTreeCollapsed ? '展开节点导航' : '收起节点导航'"
            @click="desktopTreeCollapsed = !desktopTreeCollapsed"
          >
            <ElIcon>
              <ArrowLeft />
            </ElIcon>
          </ElButton>
        </aside>

        <main
          ref="workbenchMainRef"
          id="aicheck-workbench-main"
          v-loading="nodeLoading && activeWorkbenchSection === 'node'"
          tabindex="-1"
          :aria-busy="nodeLoading && activeWorkbenchSection === 'node'"
          :data-node-transition="workbenchPageTransitionPhase"
          element-loading-text="正在加载节点内容…"
          element-loading-background="rgb(248 251 255 / 82%)"
          :class="[
            'center',
            {
              'has-flush-audit-directory':
                role === 'inspection' && activeWorkbenchSection === 'node',
              'is-inspection-ai-workspace':
                role === 'inspection' &&
                activeInspectionWorkspaceView === 'ai' &&
                activeWorkbenchSection === 'node',
              'is-workbench-page-leaving': workbenchPageTransitionPhase === 'leaving',
              'is-workbench-page-hidden': workbenchPageTransitionPhase === 'hidden',
              'is-workbench-page-entering': workbenchPageTransitionPhase === 'entering'
            }
          ]"
        >
          <section
            v-if="
              role === 'inspection' &&
              activeInspectionWorkspaceView === 'ai' &&
              activeWorkbenchSection === 'node'
            "
            class="inspection-ai-review-region"
            aria-label="AI 审查"
          >
            <ConversationalReviewWorkbenchB
              embedded
              :project-id="activeProjectId"
              :node-id="activeNodeId"
            />
          </section>

          <div
            v-show="role !== 'inspection' || activeInspectionWorkspaceView === 'list'"
            class="inspection-review-list-region"
          >
            <WorkbenchStateBanner
              v-if="readonlyIssue"
              class="readonly-banner"
              :type="readonlyIssue.type"
              :title="readonlyIssue.title"
              :message="readonlyIssue.message"
            />

            <div class="page-head">
              <div>
                <ElBreadcrumb class="crumbs" separator="/">
                  <ElBreadcrumbItem>当前位置：{{ currentRoleConfig.title }}</ElBreadcrumbItem>
                  <ElBreadcrumbItem>
                    {{
                      role === 'contractor'
                        ? '项目文件库'
                        : role === 'ndt'
                          ? '无损检测资料库'
                          : role === 'inspection' && activeWorkbenchSection === 'overview'
                            ? '项目总览'
                            : currentNodeLabel
                    }}
                  </ElBreadcrumbItem>
                  <ElBreadcrumbItem
                    v-if="
                      role !== 'contractor' &&
                      role !== 'ndt' &&
                      !(role === 'inspection' && activeWorkbenchSection === 'overview')
                    "
                  >
                    <AuditStatusTag :tone="getPillClass(selectedNode?.inspectionType)" round>
                      {{ selectedNode?.inspectionType || '-' }}类节点
                    </AuditStatusTag>
                  </ElBreadcrumbItem>
                </ElBreadcrumb>
                <h1 class="page-title">
                  {{
                    role === 'inspection' && activeWorkbenchSection === 'node'
                      ? currentNodeLabel
                      : `${currentRoleConfig.title} · ${pageHeadline}`
                  }}
                </h1>
                <div class="sub">
                  {{
                    role === 'inspection' && activeWorkbenchSection === 'node'
                      ? `${businessBasis?.ruleName || '监检审计节点'} · 当前查看 ${activeInspectionAuditItemData?.label || '资料提交'}`
                      : pageIntro
                  }}
                </div>
              </div>
              <div class="actions">
                <ElButton
                  v-if="role !== 'contractor' && role !== 'ndt'"
                  class="btn mobile-tree-trigger"
                  aria-controls="audit-node-navigation"
                  :aria-expanded="mobileTreeOpen"
                  @click="mobileTreeOpen = true"
                >
                  审核节点
                </ElButton>
                <ElButton
                  v-if="role === 'contractor' && hasAction('file:upload')"
                  class="btn primary"
                  type="primary"
                  :disabled="actionLoading || isReadOnly"
                  @click="handleOpenUploadDrawer()"
                >
                  批量上传文件
                </ElButton>
                <ElButton
                  v-if="
                    role === 'inspection' &&
                    activeWorkbenchSection === 'node' &&
                    !inspectionNodeUnselected &&
                    hasAction('file:upload')
                  "
                  class="btn primary"
                  type="primary"
                  :disabled="actionLoading || isReadOnly"
                  @click="handleOpenInspectionUploadDrawer"
                >
                  上传监检资料
                </ElButton>
                <ElButton
                  v-if="
                    role !== 'owner' &&
                    role !== 'contractor' &&
                    role !== 'ndt' &&
                    !(role === 'inspection' && activeWorkbenchSection === 'overview')
                  "
                  class="btn"
                  :disabled="actionLoading || isReadOnly"
                  @click="() => handleOpenBindDialog()"
                >
                  文件库
                </ElButton>
                <!-- 这里原来有一个「导出状态摘要」按钮，绑的却是
                     handleDownloadArchivePackage——点下去导出的是归档包。
                     而建设方的归档区里本来就有「归档包」按钮，两个入口做同一件事，
                     其中一个还挂着错名字：用户点「状态摘要」拿到的是（0 项的）归档包。
                     前后端都没有「状态摘要导出」这个能力，这个名字从来只是个误会。
                     与其保留一个骗人的入口，不如去掉——真要做状态摘要，是另一个功能。 -->
              </div>
            </div>

            <div v-if="inspectionNodeUnselected" class="node-unselected">
              <ElEmpty :image-size="110" description="">
                <template #description>
                  <p class="node-unselected-title">请从左侧选择一个审查节点</p>
                  <p class="node-unselected-hint">
                    选中节点后，这里会显示该节点的审计项状态、监检依据、资料与 AI 审查结果。
                  </p>
                </template>
              </ElEmpty>
            </div>

            <AuditItemDirectory
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected
              "
              v-model="activeInspectionAuditItem"
              :items="inspectionAuditItems"
              :loading="inspectionAuditLoading"
              @select="handleInspectionAuditSelect"
            />

            <WorkbenchStateBanner
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                inspectionAuditIssue
              "
              class="inspection-audit-state-banner"
              :type="inspectionAuditIssue.type"
              :title="inspectionAuditIssue.title"
              :message="inspectionAuditIssue.message"
              action-label="重新加载目录状态"
              @action="loadInspectionAuditWorkspace(activeNodeId)"
            />

            <AuditSummaryGrid
              v-if="
                role !== 'contractor' &&
                !(
                  role === 'inspection' &&
                  (activeWorkbenchSection === 'overview' || activeWorkbenchSection === 'node')
                )
              "
              :cards="workbenchAuditCards"
              aria-label="业务工作台审计摘要"
              @card-action="handleSummaryCardAction"
            />

            <section
              v-if="role === 'inspection' && activeWorkbenchSection === 'overview'"
              class="inspection-project-overview"
              aria-label="项目总览"
            >
              <div class="inspection-overview-main-grid">
                <article
                  id="inspection-overview-status"
                  class="inspection-overview-panel inspection-overview-panel--status"
                >
                  <!-- 原先这里是四张数字卡片：471 未开始 / 1 处理中 / 9 需关注 / 2 已完成。
                       471 是 69 节点 × 7 审计项里还没动过的——监检不会去「消灭 471」，
                       这个数不驱动任何行动，却占着首屏最贵的位置。

                       业务口径是「监检最好只需要知道状态，全程不需要人工干预」，
                       那这块要回答的就一句话：现在有没有要我管的、在哪儿。
                       全量数字降为次要信息，仍然保留——需要核对整体进度时还得看。 -->
                  <div
                    class="inspection-headline"
                    :class="{ 'is-clear': !inspectionAttentionItemCount }"
                  >
                    <div class="inspection-headline-main">
                      <strong v-if="inspectionAttentionItemCount">
                        {{ inspectionAttentionItemCount }} 项需要你处理
                      </strong>
                      <strong v-else>暂无需要你处理的事项</strong>
                      <small v-if="inspectionAttentionItemCount">
                        分布在 {{ inspectionAttentionNodeCount }} 个节点，已列在下方清单
                      </small>
                      <small v-else>系统在跑的部分完成后会自动出现在这里</small>
                    </div>
                    <!-- 单位不同要写清楚：上面数的是「审计项」，清单里数的是「节点」。
                         两个数字并排而不说明单位，会让人以为其中一个算错了。 -->
                    <dl class="inspection-headline-rest" aria-label="全部审计项统计">
                      <div v-for="row in inspectionAuditStatusSummaryRows" :key="row.key">
                        <dt>{{ row.label }}</dt>
                        <dd>{{ row.value }}</dd>
                      </div>
                    </dl>
                  </div>
                </article>

                <article id="inspection-overview-nodes" class="inspection-overview-panel">
                  <div class="inspection-chart-head">
                    <div>
                      <strong>节点处理清单</strong>
                      <!-- 计数写在开关上：关着的时候也得知道有几个在等，
                           否则筛选本身就成了新的隐藏 -->
                      <ElCheckbox v-model="inspectionOnlyAttentionNodes" class="node-filter-toggle">
                        只看需处理（{{ inspectionAttentionNodeCount }}）
                      </ElCheckbox>
                      <small>与左侧项目树一致，按节点查看资料、要求和审查进度。</small>
                    </div>
                    <AuditStatusTag tone="green" round>
                      {{ inspectionVisibleNodeRows.length }} 个节点
                    </AuditStatusTag>
                  </div>
                  <ElTable
                    class="inspection-node-table"
                    :data="pagedInspectionProjectNodeRows"
                    row-key="node.id"
                    :row-class-name="
                      ({ row }) => (row.node.nodeId === activeNodeId ? 'active' : '')
                    "
                    :default-sort="
                      inspectionNodeSortKey === 'review'
                        ? undefined
                        : {
                            prop: inspectionNodeSortKey,
                            order:
                              inspectionNodeSortDirection === 'asc' ? 'ascending' : 'descending'
                          }
                    "
                    empty-text="暂无节点"
                    @sort-change="handleInspectionNodeTableSort"
                  >
                    <ElTableColumn prop="nodeId" label="序号" width="84" sortable="custom">
                      <template #default="{ row }">{{ row.node.nodeId }}</template>
                    </ElTableColumn>
                    <ElTableColumn label="节点名称" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">
                        <ElButton
                          class="inspection-node-name-button"
                          link
                          type="primary"
                          @click="handleNodeSelect(row.node)"
                        >
                          <span class="file-name-with-icon inspection-node-name-content">
                            <FileTypeIcon
                              :file-name="row.node.name"
                              :category="row.node.groupName"
                            />
                            <span>{{ row.node.name }}</span>
                          </span>
                        </ElButton>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="类别" width="108" align="center">
                      <template #default="{ row }">
                        <AuditStatusTag :tone="getPillClass(row.node.inspectionType)" round>
                          {{ row.node.inspectionType }}
                        </AuditStatusTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn prop="material" label="资料齐全度" width="250" sortable="custom">
                      <template #default="{ row }">
                        <div class="inspection-node-material">
                          <strong>{{ row.materialDone }}/{{ row.materialTotal }}</strong>
                          <span>{{ row.materialPercent }}%</span>
                        </div>
                        <ElProgress
                          class="inspection-node-material-progress"
                          :percentage="row.materialPercent"
                          :show-text="false"
                          :stroke-width="7"
                        />
                        <small class="inspection-node-missing" :title="row.missingText">
                          {{ row.missingText }}
                        </small>
                      </template>
                    </ElTableColumn>
                    <!-- 原先这里平铺七个状态标签，一页 14 行 = 98 个标签、56 个可点元素，
                         而实测 483 个审计项里 471 个是同一个值（未开始）——监检要在一屏
                         几乎一样的标签里找出不一样的那几个。

                         业务口径是「监检最好只需要知道状态，全程不需要人工干预」，
                         所以列表只回答一个问题：这个节点要不要我管。七项明细点开详情再看。 -->
                    <ElTableColumn label="状态" min-width="240">
                      <template #default="{ row }">
                        <button
                          v-if="inspectionAuditOverviewNodeMap.get(row.node.nodeId)"
                          type="button"
                          class="node-status-cell"
                          :title="`点击查看 ${row.node.name} 的七项审计明细`"
                          @click="handleInspectionMatrixSelect(row.node, 'submission')"
                        >
                          <span
                            :class="[
                              'node-status-pill',
                              `is-${nodeAggregate(row.node.nodeId).tone}`
                            ]"
                          >
                            {{ nodeAggregate(row.node.nodeId).label }}
                          </span>
                          <!-- 卡在哪一步必须说出来。只说「需要处理」等于把问题原样
                               丢回给人，他还得点进去逐项翻才知道是 OCR 没跑完还是等他签字。 -->
                          <small
                            v-if="nodeAggregate(row.node.nodeId).blockedAt"
                            class="node-status-where"
                          >
                            {{ nodeAggregate(row.node.nodeId).blockedAt }}
                          </small>
                          <small class="node-status-progress">
                            {{ nodeAggregate(row.node.nodeId).progress }}
                          </small>
                        </button>
                        <ElSkeleton
                          v-else
                          class="inspection-audit-matrix-loading"
                          :rows="1"
                          animated
                          aria-label="正在加载审计项状态"
                        />
                      </template>
                    </ElTableColumn>
                  </ElTable>
                  <ElPagination
                    v-model:current-page="inspectionNodePage"
                    v-model:page-size="inspectionNodePageSize"
                    class="inspection-node-pagination"
                    :page-sizes="[6, 10, 20, 50]"
                    :total="inspectionVisibleNodeRows.length"
                    layout="total, sizes, prev, pager, next"
                    small
                  />
                </article>

                <article
                  id="inspection-overview-files"
                  class="inspection-overview-panel inspection-overview-panel--files"
                >
                  <div class="inspection-chart-head">
                    <div>
                      <strong>已提交审查资料</strong>
                      <small>仅展示施工方和无损检测机构已正式提交监检审查的资料。</small>
                    </div>
                    <AuditStatusTag tone="blue" round>
                      {{ inspectionOverviewFileTotal }} 份文件
                    </AuditStatusTag>
                  </div>

                  <div class="overview-file-toolbar">
                    <ElInput
                      v-model="overviewFileKeyword"
                      clearable
                      placeholder="查找文件名、提交单位、提交人、资料类别或审查状态"
                      aria-label="查找已提交审查资料"
                    />
                  </div>

                  <ElTable
                    class="overview-file-table"
                    :data="pagedInspectionOverviewFiles"
                    row-key="id"
                    empty-text="暂无已提交审查资料"
                  >
                    <ElTableColumn prop="rowNo" label="序号" width="72" align="center" />
                    <ElTableColumn
                      prop="fileName"
                      label="文件名"
                      min-width="220"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">
                        <span class="file-name-with-icon">
                          <FileTypeIcon
                            :file-name="row.fileName"
                            :file-type="row.fileType"
                            :category="row.materialCategoryText"
                          />
                          <span>{{ row.fileName }}</span>
                        </span>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="来源" min-width="150">
                      <template #default="{ row }">
                        <span>{{ row.sourceRole }}</span>
                        <small class="overview-file-source">{{ row.sourceOrgName }}</small>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn prop="submitterName" label="提交人" width="112">
                      <template #default="{ row }">{{ row.submitterName || '-' }}</template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="materialCategoryText"
                      label="资料类别"
                      min-width="150"
                      show-overflow-tooltip
                    />
                    <ElTableColumn label="审查/OCR 状态" min-width="176">
                      <template #default="{ row }">
                        <AuditStatusTag :tone="getPillClass(row.reviewStatus)" round>
                          {{ row.reviewStatus }}
                        </AuditStatusTag>
                        <small
                          :class="[
                            'overview-ocr-status',
                            `is-${row.ocrReadiness?.status || 'unknown'}`
                          ]"
                        >
                          {{ ocrReadinessLabel(row.ocrReadiness?.status) }}
                          <template v-if="row.ocrReadiness?.status === 'ready'">
                            · bbox {{ Math.round((row.ocrReadiness?.bboxCoverage || 0) * 100) }}%
                          </template>
                        </small>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="提交审查时间" width="170">
                      <template #default="{ row }">
                        {{ row.submittedAt || '提交时间缺失' }}
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="操作" width="96" fixed="right">
                      <template #default="{ row }">
                        <ElButton text type="primary" @click="handleOpenFileDetail(row.documentId)">
                          查看原文
                        </ElButton>
                      </template>
                    </ElTableColumn>
                  </ElTable>

                  <ElPagination
                    v-model:current-page="overviewFilePage"
                    v-model:page-size="overviewFilePageSize"
                    class="overview-file-pagination"
                    :page-sizes="[5, 8, 10, 20]"
                    :total="inspectionOverviewFileTotal"
                    layout="total, sizes, prev, pager, next"
                    small
                  />
                </article>
              </div>
            </section>

            <WorkbenchRoleStaticSections
              v-if="role === 'contractor' || role === 'owner'"
              ref="staticSectionsRef"
              :role="role"
              :project="currentProject"
              :node="selectedNode"
              :package-data="nodePackage"
              :read-only="isReadOnly"
              :metrics="metrics"
              :review-steps="reviewChainSteps"
              :ai-confidence="aiConfidence"
              :reports="reports"
              :archive-items="archiveItems"
              :ndt-films="ndtFilms"
              :ndt-records="ndtRecords"
              :ndt-reports="ndtReports"
              :ndt-feedback="ndtFeedback"
              @upload="handleOpenUploadDrawer"
              @bind="handleOpenBindDialog"
              @rectify="handleOpenRectificationDialog"
              @file-view="handleOpenFileDetail"
              @file-replace="handleReplaceProjectFile"
              @file-bind="handleOpenBindDialog"
              @file-submit="handleSubmitProjectFile"
              @file-retry-upload="handleRetryProjectFileUpload"
              @file-delete="handleDeleteProjectFile"
            />

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                activeInspectionAuditItem === 'ai_review' &&
                hasAction('ai:recheck')
              "
              id="inspection-audit-panel-ai_review"
              role="tabpanel"
              aria-label="AI 复核"
              class="node-ai-recheck-top"
            >
              <div class="node-ai-recheck-actions">
                <div class="ai-review-mode-control">
                  <ElRadioGroup v-model="selectedAiReviewMode" aria-label="AI 复核模式">
                    <ElRadioButton
                      value="formal"
                      :disabled="!availableAiReviewModes.includes('formal')"
                      :title="formalReviewBlockedReason || '按当前文件版本发起正式 AI 复核'"
                    >
                      正式复核
                    </ElRadioButton>
                    <ElRadioButton
                      value="gap_precheck"
                      :disabled="!availableAiReviewModes.includes('gap_precheck')"
                    >
                      缺项预审
                    </ElRadioButton>
                  </ElRadioGroup>
                  <small>{{ aiReviewModeHint }}</small>
                </div>
                <ElButton
                  class="node-ai-recheck-button"
                  type="primary"
                  :loading="actionLoading"
                  :disabled="isReadOnly || Boolean(aiRecheckDisabledReason)"
                  :title="aiRecheckDisabledReason || aiReviewModeHint"
                  @click="handleAiRecheck"
                >
                  {{ aiRecheckButtonLabel }}
                </ElButton>
              </div>
              <div v-if="aiRecheckOutputVisible" class="ai-recheck-output" aria-live="polite">
                <div class="ai-recheck-output-head">
                  <strong>AI 复核输出</strong>
                  <small>{{ aiRecheckOutputMeta }}</small>
                </div>
                <ElAlert
                  v-if="aiRecheckOutputError"
                  class="ai-recheck-output-alert"
                  type="error"
                  :title="aiRecheckOutputError"
                  :closable="false"
                  show-icon
                />
                <ElAlert
                  v-if="aiRecheckIsLocalFallback"
                  class="ai-recheck-output-alert"
                  type="warning"
                  title="当前调度器未启用，未调用外部模型；以下为基于真实证据状态生成的本地降级摘要，不是模型 DeepThink。"
                  :closable="false"
                  show-icon
                />
                <div v-if="activeHumanInputTask" class="ai-human-input-card">
                  <div>
                    <strong>
                      {{
                        isR19HumanInputTask
                          ? 'AI 已暂停，等待 R19 关键事实确认'
                          : 'AI 已暂停，等待官网人工核验'
                      }}
                    </strong>
                    <span v-if="isR19HumanInputTask">
                      需要确认
                      {{
                        activeHumanInputTask.questionCount ||
                        activeHumanInputTask.questions?.length ||
                        0
                      }}
                      个语义事实；提交后将作为新证据恢复 R19 Agent，并继续完成八个原子项判断。
                    </span>
                    <span v-else>
                      已识别 {{ activeHumanInputTask.candidateCount || 0 }}
                      张制造许可证；完成核验后，AI 将继续调用固定 Tool 比对工程元件覆盖范围。
                    </span>
                  </div>
                  <ElButton type="warning" @click="humanInputDialogVisible = true">
                    {{ isR19HumanInputTask ? '处理人工确认' : '处理人工核验' }}
                  </ElButton>
                </div>
                <div class="ai-recheck-output-section">
                  <label>AI 建议（待人工确认）</label>
                  <!-- 模型输出是 findings JSON 时按条渲染。原先直接 <pre> 打出
                       原始 JSON，监检要在花括号和转义引号里找结论——
                       **那不是不好看，是让人读不到判定**。
                       解析不出来仍原样显示文本：模型偶尔回纯文字，硬套结构会吃掉内容。 -->
                  <ul v-if="aiRecheckFindings.length" class="ai-finding-list">
                    <li v-for="(finding, index) in aiRecheckFindings" :key="index">
                      <div class="ai-finding-head">
                        <ElTag size="small" effect="plain">{{ finding.typeLabel }}</ElTag>
                        <ElTag
                          v-if="finding.severityLabel"
                          size="small"
                          :type="
                            finding.severity === 'high'
                              ? 'danger'
                              : finding.severity === 'medium'
                                ? 'warning'
                                : 'info'
                          "
                        >
                          严重度 {{ finding.severityLabel }}
                        </ElTag>
                        <span v-if="finding.evidenceCount" class="ai-finding-meta">
                          证据 {{ finding.evidenceCount }} 条
                        </span>
                        <span v-if="finding.ruleCount" class="ai-finding-meta">
                          条款 {{ finding.ruleCount }} 条
                        </span>
                      </div>
                      <div v-if="finding.title" class="ai-finding-title">{{ finding.title }}</div>
                      <div v-if="finding.description" class="ai-finding-desc">
                        {{ finding.description }}
                      </div>
                    </li>
                  </ul>
                  <pre v-else>{{ aiRecheckResultText }}</pre>
                </div>
                <ElCollapse
                  v-model="aiTechnicalPanels"
                  class="ai-recheck-technical-details"
                  aria-label="模型执行详情"
                >
                  <ElCollapseItem name="execution-details" title="查看模型执行详情">
                    <div class="ai-recheck-output-section">
                      <label>推理过程</label>
                      <pre>{{ aiRecheckReasoningText }}</pre>
                    </div>
                    <div class="ai-recheck-output-section">
                      <label>{{ aiRecheckDeepThinkLabel }}</label>
                      <pre>{{ aiRecheckDeepThinkText }}</pre>
                    </div>
                  </ElCollapseItem>
                </ElCollapse>
              </div>
            </section>

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                activeInspectionAuditItem === 'ocr'
              "
              id="inspection-audit-panel-ocr"
              role="tabpanel"
              aria-label="OCR 抽取"
              class="card inspection-ocr-panel"
            >
              <div class="card-head">
                <h2>OCR 抽取与定位质量</h2>
                <div class="sub">仅展示当前节点挂载文档的当前版本</div>
              </div>
              <div class="card-body">
                <ElTable :data="nodeScopedFiles" border class="inspection-ocr-table">
                  <ElTableColumn prop="fileName" label="文件" min-width="230" show-overflow-tooltip>
                    <template #default="{ row }">
                      <span class="file-name-with-icon">
                        <FileTypeIcon
                          :file-name="row.fileName"
                          :file-type="row.fileType"
                          :category="row.materialCategory"
                        />
                        <span>{{ row.fileName }}</span>
                      </span>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="执行状态" width="126">
                    <template #default="{ row }">
                      <AuditStatusTag
                        :tone="getPillClass(ocrReadinessLabel(row.ocrReadiness?.status))"
                        round
                      >
                        {{ ocrReadinessLabel(row.ocrReadiness?.status) }}
                      </AuditStatusTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="字段" width="88">
                    <template #default="{ row }">
                      {{ extractedFieldCountByVersion.get(row.currentVersionId) || 0 }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="定位覆盖" width="116">
                    <template #default="{ row }">
                      {{ Math.round((row.ocrReadiness?.bboxCoverage || 0) * 100) }}%
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="当前说明" min-width="250">
                    <template #default="{ row }">
                      {{
                        row.ocrReadiness?.blockingReasons?.[0]?.message ||
                        (row.ocrReadiness?.status === 'ready'
                          ? '抽取产物及证据定位已就绪。'
                          : '等待 OCR 任务产物。')
                      }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="96" fixed="right">
                    <template #default="{ row }">
                      <ElButton text type="primary" @click="handleOpenFileDetail(row.id)">
                        查看
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElEmpty
                  v-if="!nodeScopedFiles.length"
                  class="inspection-audit-empty"
                  :image-size="72"
                  description="当前节点暂无挂载文档；这不会阻止查看或办理其他审计项。"
                />
              </div>
            </section>

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                ['submission', 'evidence'].includes(activeInspectionAuditItem)
              "
              :id="`inspection-audit-panel-${activeInspectionAuditItem}`"
              role="tabpanel"
              :aria-label="activeInspectionAuditItemData?.label"
              class="card"
            >
              <div class="card-head">
                <h2>监检依据 · {{ activeInspectionAuditItemData?.label }}</h2>
                <div class="sub">{{ businessBasis?.ruleName || selectedNode?.name }}</div>
              </div>
              <div class="card-body">
                <div class="basis-meta-grid">
                  <div v-for="item in nodeBasisMetaRows" :key="item.label" class="basis-meta-item">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </div>
                </div>

                <div class="basis-block-grid">
                  <article class="basis-block basis-block--criteria">
                    <div class="basis-block-heading">
                      <ElIcon class="basis-block-icon"><DocumentChecked /></ElIcon>
                      <div>
                        <span class="basis-block-kicker">判定依据</span>
                        <h3>监检判断准则</h3>
                      </div>
                    </div>
                    <ol class="basis-reference-list">
                      <li v-for="(item, index) in basisCriteriaReferences" :key="item">
                        <span class="basis-reference-index">
                          {{ String(index + 1).padStart(2, '0') }}
                        </span>
                        <p>{{ item }}</p>
                      </li>
                    </ol>
                    <div v-if="basisCriteriaDecisionNote" class="basis-decision-note">
                      <ElIcon><Guide /></ElIcon>
                      <div>
                        <strong>冲突适用规则</strong>
                        <span>{{ basisCriteriaDecisionNote }}</span>
                      </div>
                    </div>
                  </article>
                  <article class="basis-block basis-block--method">
                    <div class="basis-block-heading">
                      <ElIcon class="basis-block-icon"><Guide /></ElIcon>
                      <div>
                        <span class="basis-block-kicker">执行路径</span>
                        <h3>核查方法与工作见证</h3>
                      </div>
                    </div>
                    <div class="basis-method-list">
                      <div
                        v-for="(item, index) in basisCheckSteps"
                        :key="item.text"
                        class="basis-method-item"
                      >
                        <span class="basis-method-step">{{ index + 1 }}</span>
                        <div>
                          <small>{{ item.label }}</small>
                          <p>{{ item.text }}</p>
                        </div>
                      </div>
                    </div>
                    <div v-if="basisAgentSteps.length" class="basis-agent-note">
                      <div class="basis-agent-note__head">
                        <ElIcon><MagicStick /></ElIcon>
                        <strong>Agent 核查思路</strong>
                        <span>辅助说明</span>
                      </div>
                      <ul>
                        <li v-for="item in basisAgentSteps" :key="item">{{ item }}</li>
                      </ul>
                    </div>
                  </article>
                </div>

                <article
                  v-if="activeInspectionAuditItem === 'submission'"
                  id="inspection-node-requirements"
                  class="basis-table-block"
                >
                  <div class="block-title-row">
                    <h3>审查所需资料</h3>
                    <AuditStatusTag tone="blue" round>
                      {{ nodeRequirementRows.length }} 项
                    </AuditStatusTag>
                  </div>
                  <div class="basis-table-wrap">
                    <ElTable
                      class="basis-table"
                      :data="nodeRequirementRows"
                      row-key="id"
                      empty-text="暂无资料要求明细"
                    >
                      <ElTableColumn prop="rowNo" label="序号" width="72" align="center" />
                      <ElTableColumn label="资料名称" min-width="220">
                        <template #default="{ row }">
                          <strong>{{ row.name }}</strong>
                          <small class="basis-table-secondary">{{ row.applicability }}</small>
                        </template>
                      </ElTableColumn>
                      <ElTableColumn
                        prop="materialType"
                        label="资料类别"
                        min-width="140"
                        show-overflow-tooltip
                      />
                      <ElTableColumn prop="responsibleParty" label="责任方" width="112" />
                      <ElTableColumn prop="requiredType" label="要求" width="112" />
                      <ElTableColumn label="当前匹配" min-width="190">
                        <template #default="{ row }">
                          <AuditStatusTag :tone="getPillClass(row.status)" round>
                            {{ row.status }}
                          </AuditStatusTag>
                          <small v-if="row.matchedFileNames.length" class="basis-table-secondary">
                            {{ row.matchedFileNames.slice(0, 2).join('、') }}
                          </small>
                        </template>
                      </ElTableColumn>
                    </ElTable>
                  </div>

                  <div class="block-title-row inspection-bound-files-title">
                    <h3>当前节点已挂载资料</h3>
                    <AuditStatusTag tone="blue" round>
                      {{ nodeScopedFiles.length }} 份
                    </AuditStatusTag>
                  </div>
                  <ElTable :data="nodeScopedFiles" border class="inspection-bound-files-table">
                    <ElTableColumn
                      prop="fileName"
                      label="文件"
                      min-width="220"
                      show-overflow-tooltip
                    >
                      <template #default="{ row }">
                        <span class="file-name-with-icon">
                          <FileTypeIcon
                            :file-name="row.fileName"
                            :file-type="row.fileType"
                            :category="row.materialCategory"
                          />
                          <span>{{ row.fileName }}</span>
                        </span>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="sourceOrgName"
                      label="来源"
                      min-width="150"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="currentOcrStatus" label="OCR" width="110" />
                    <ElTableColumn label="状态" width="110">
                      <template #default="{ row }">
                        <AuditStatusTag
                          :tone="getPillClass(row.primaryBinding?.bindingStatus || row.fileStatus)"
                          round
                        >
                          {{ row.primaryBinding?.bindingStatus || row.fileStatus }}
                        </AuditStatusTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn label="操作" width="96" fixed="right">
                      <template #default="{ row }">
                        <ElButton text type="primary" @click="handleOpenFileDetail(row.id)">
                          查看
                        </ElButton>
                      </template>
                    </ElTableColumn>
                  </ElTable>
                </article>

                <article
                  v-if="activeInspectionAuditItem === 'evidence'"
                  id="inspection-node-evidence"
                  class="basis-table-block evidence-confirmation-block"
                >
                  <div class="block-title-row">
                    <h3>证据确认</h3>
                    <AuditStatusTag tone="blue" round>
                      {{ evidenceConfirmationRows.length }} 条
                    </AuditStatusTag>
                  </div>
                  <ElTable
                    class="evidence-confirmation-table"
                    :data="evidenceConfirmationRows"
                    border
                  >
                    <ElTableColumn prop="materialType" label="资料类别" min-width="150" />
                    <ElTableColumn label="状态" width="118">
                      <template #default="{ row }">
                        <AuditStatusTag :tone="getPillClass(row.status)" round>
                          {{ row.status }}
                        </AuditStatusTag>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn prop="fileName" label="候选文件" min-width="190">
                      <template #default="{ row }">
                        <span class="file-name-with-icon">
                          <FileTypeIcon :file-name="row.fileName" :category="row.materialType" />
                          <span>{{ row.fileName }}</span>
                        </span>
                      </template>
                    </ElTableColumn>
                    <ElTableColumn
                      prop="evidenceText"
                      label="命中证据"
                      min-width="220"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="confidenceText" label="置信度" width="90" />
                    <ElTableColumn label="操作" width="230" fixed="right">
                      <template #default="{ row }">
                        <div v-if="row.evidence" class="evidence-confirmation-actions">
                          <ElButton text type="primary" @click="handleLocateEvidence(row.evidence)">
                            查看原文
                          </ElButton>
                          <ElButton
                            text
                            type="success"
                            :disabled="row.evidence.manualStatus === 'confirmed' || actionLoading"
                            @click="handleConfirmEvidence(row.evidence)"
                          >
                            确认
                          </ElButton>
                          <ElButton
                            text
                            type="warning"
                            :disabled="row.evidence.manualStatus === 'rejected' || actionLoading"
                            @click="handleRejectEvidence(row.evidence)"
                          >
                            不采用
                          </ElButton>
                        </div>
                        <span v-else class="empty-inline">-</span>
                      </template>
                    </ElTableColumn>
                  </ElTable>
                </article>

                <article
                  v-if="activeInspectionAuditItem === 'evidence'"
                  class="standard-reference-block"
                >
                  <div class="block-title-row">
                    <h3>引用标准文件</h3>
                    <AuditStatusTag tone="blue" round>
                      {{ nodeReferencedStandards.length }} 项
                    </AuditStatusTag>
                  </div>
                  <div v-if="standardReferenceTree.length" class="standard-reference-tree-shell">
                    <ElTreeV2
                      class="standard-reference-tree"
                      :data="standardReferenceTree"
                      :props="standardTreeProps"
                      :height="standardReferenceTreeHeight"
                      :item-size="52"
                      :default-expanded-keys="standardTreeDefaultExpandedKeys"
                      node-key="id"
                      highlight-current
                      scrollbar-always-on
                      aria-label="引用标准文件树"
                      @node-click="handleStandardTreeNodeClick"
                    >
                      <template #default="{ data }">
                        <div
                          class="standard-tree-node"
                          :class="`is-${data.kind}`"
                          :title="data.sourceRelativePath || data.fileName || data.label"
                        >
                          <component
                            :is="data.kind === 'file' ? Document : FolderOpened"
                            class="standard-tree-icon"
                            aria-hidden="true"
                          />
                          <div class="standard-tree-copy">
                            <strong>{{ data.label }}</strong>
                            <small v-if="data.kind === 'file'">{{ data.fileName }}</small>
                          </div>
                          <span
                            v-if="data.kind === 'file'"
                            class="standard-tree-preview-state"
                            :class="{ 'is-unavailable': !data.previewAvailable }"
                          >
                            <View aria-hidden="true" />
                            {{ data.previewAvailable ? '预览' : '未关联' }}
                          </span>
                        </div>
                      </template>
                    </ElTreeV2>
                  </div>
                  <span v-else class="empty-inline">暂无引用标准文件</span>
                </article>
              </div>
            </section>

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                activeInspectionAuditItem === 'ai_review'
              "
              id="inspection-node-execution"
              class="card node-package-card"
            >
              <div class="card-head">
                <h2>二、AI 审查执行过程</h2>
                <div class="sub">LangGraph 编排执行步骤与操作反馈</div>
              </div>
              <div class="card-body">
                <!-- 结论与缺项置顶：这是监检打开这一页真正要看的东西 -->
                <div v-if="aiOutcomeHighlights" class="ai-outcome">
                  <div class="ai-outcome-head">
                    <span class="ai-outcome-label">AI 建议结论</span>
                    <strong class="ai-outcome-result">{{ aiOutcomeHighlights.result }}</strong>
                    <span
                      v-if="aiOutcomeHighlights.confidence !== undefined"
                      class="ai-outcome-conf"
                    >
                      置信度 {{ Math.round((aiOutcomeHighlights.confidence || 0) * 100) }}%
                    </span>
                  </div>
                  <div
                    v-if="aiOutcomeHighlights.manualConfirmItems.length"
                    class="ai-outcome-block"
                  >
                    <span class="ai-outcome-block-label">需人工确认</span>
                    <div class="ai-outcome-chips">
                      <span
                        v-for="item in aiOutcomeHighlights.manualConfirmItems"
                        :key="item"
                        class="ai-outcome-chip"
                      >
                        {{ item }}
                      </span>
                    </div>
                  </div>
                  <div v-if="aiOutcomeHighlights.rectification" class="ai-outcome-block">
                    <span class="ai-outcome-block-label">结论说明</span>
                    <p class="ai-outcome-text">{{ aiOutcomeHighlights.rectification }}</p>
                  </div>
                </div>

                <AiReviewRunAlerts
                  :evidence-budget="aiEvidenceBudget"
                  :failure="aiRunFailure"
                  :failure-kind-label="aiFailureKindLabel"
                  @retry="handleAiRecheck"
                />

                <!-- 过程默认折叠，与 AI 复核 B 版工作台的交互对齐 -->
                <button
                  type="button"
                  class="execution-toggle"
                  :aria-expanded="aiExecutionExpanded"
                  aria-controls="ai-execution-timeline"
                  @click="aiExecutionExpanded = !aiExecutionExpanded"
                >
                  <span class="execution-toggle-copy">
                    <strong>执行过程</strong>
                    <small>{{ aiExecutionSummary }}</small>
                  </span>
                  <span :class="['execution-toggle-chevron', { 'is-open': aiExecutionExpanded }]"
                    >⌄</span
                  >
                </button>

                <div
                  v-show="aiExecutionExpanded"
                  id="ai-execution-timeline"
                  class="execution-timeline"
                >
                  <article
                    v-for="(step, index) in aiExecutionSteps"
                    :key="step.title"
                    class="execution-step"
                  >
                    <div class="step-no">{{ index + 1 }}</div>
                    <div class="execution-step-main">
                      <div class="execution-step-head">
                        <h3>{{ step.title }}</h3>
                        <AuditStatusTag :tone="getPillClass(step.status)" round>
                          {{ step.status }}
                        </AuditStatusTag>
                      </div>
                      <dl class="execution-step-detail">
                        <div>
                          <dt>输入</dt>
                          <dd>{{ step.input }}</dd>
                        </div>
                        <div>
                          <dt>反馈</dt>
                          <dd>{{ step.feedback }}</dd>
                        </div>
                      </dl>
                      <div class="evidence-row">
                        <ElTooltip
                          v-for="tool in step.tools"
                          :key="tool"
                          :content="toolTooltip(tool)"
                          placement="top"
                        >
                          <span class="execution-tool-tag">{{ toolLabel(tool) }}</span>
                        </ElTooltip>
                        <button
                          v-for="evidence in step.evidenceLinks"
                          :key="evidence.id"
                          class="evidence-link-button"
                          type="button"
                          @click="handleLocateEvidence(evidence)"
                        >
                          {{ evidenceLabel(evidence) }}
                        </button>
                      </div>
                    </div>
                  </article>
                </div>
              </div>
            </section>

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                activeInspectionAuditItem === 'human_review'
              "
              id="inspection-audit-panel-human_review"
              role="tabpanel"
              aria-label="人工结论"
              class="card conclusion-card"
            >
              <div class="card-head">
                <h2>三、审查结论</h2>
                <div class="sub">{{
                  latestAiRun?.finishedAt || latestAiRun?.status || '等待审查'
                }}</div>
              </div>
              <div class="card-body">
                <div class="overall-conclusion">
                  <span>总体意见</span>
                  <p>{{ reviewConclusionOverall }}</p>
                </div>
                <div class="conclusion-points">
                  <article
                    v-for="point in reviewConclusionPoints"
                    :key="point.title"
                    class="conclusion-point"
                  >
                    <div class="conclusion-point-order">{{ point.order }}</div>
                    <div>
                      <div class="conclusion-point-head">
                        <h3>{{ point.title }}</h3>
                        <AuditStatusTag :tone="getPillClass(point.conclusion)" round>
                          {{ point.conclusion }}
                        </AuditStatusTag>
                      </div>
                      <p>{{ point.description }}</p>
                      <div v-if="point.evidenceLinks.length" class="evidence-row">
                        <button
                          v-for="evidence in point.evidenceLinks"
                          :key="evidence.id"
                          class="evidence-link-button"
                          type="button"
                          @click="handleLocateEvidence(evidence)"
                        >
                          {{ evidenceLabel(evidence) }}
                        </button>
                      </div>
                    </div>
                  </article>
                </div>
              </div>
            </section>

            <section
              v-if="
                role === 'inspection' &&
                activeWorkbenchSection === 'node' &&
                !inspectionNodeUnselected &&
                activeInspectionAuditItem === 'human_review'
              "
              id="inspection-node-manual-review"
              class="manual-review-section"
            >
              <div class="card-head manual-review-head">
                <h2>四、人工审查操作区</h2>
                <div class="sub">人工结论、补正要求和审查意见提交</div>
              </div>
              <div class="manual-review-grid">
                <section class="right-card action-card">
                  <h3>办理操作</h3>
                  <div class="body">
                    <WorkbenchActionBar
                      :role="role"
                      :actions="availableActions"
                      :loading="actionLoading"
                      :read-only="isReadOnly"
                      @upload="handleOpenUploadDrawer"
                      @bind="handleOpenBindDialog"
                      @save-draft="handleSaveDraft"
                      @submit="handleOpenSubmissionDialog"
                      @history="handleOpenSubmissionHistory"
                      @rectify="handleOpenRectificationDialog"
                    />
                  </div>
                </section>
                <ElAlert
                  v-if="actionBlocker"
                  class="operation-blocker-alert"
                  type="warning"
                  :title="actionBlocker.title"
                  :description="actionBlocker.message"
                  :closable="true"
                  show-icon
                  @close="actionBlocker = undefined"
                >
                  <ul v-if="actionBlocker.reasons.length" class="operation-blocker-list">
                    <li v-for="reason in actionBlocker.reasons" :key="reason">{{ reason }}</li>
                  </ul>
                </ElAlert>
                <ReviewDecisionPanel
                  v-model:review-result="reviewResult"
                  v-model:review-opinion="reviewOpinion"
                  v-model:correction-reason="correctionReason"
                  v-model:selected-evidence-ids="selectedReviewEvidenceIds"
                  :role="role"
                  :actions="availableActions"
                  :latest-ai-run="latestAiRun"
                  :evidence-count="evidenceLinks.length"
                  :confirmed-evidence-links="confirmedEvidenceLinks"
                  :save-disabled-reason="reviewSaveDisabledReason"
                  :blocking-reasons="readinessBlockingReasons"
                  :requires-evidence-selection="draftRequiresEvidenceSelection"
                  :loading="actionLoading"
                  @save-review="handleSaveReviewOpinion"
                  @return-correction="handleReturnCorrection"
                  @adopt-ai="handleAdoptAiSuggestion"
                  @reject-ai="handleRejectAiSuggestion"
                />
              </div>
            </section>

            <section v-if="role === 'owner'" class="card node-package-card">
              <div class="card-head">
                <h2>只读节点资料联动区</h2>
                <div class="sub">集中展示当前节点文件、审核反馈和错误恢复能力</div>
              </div>
              <div class="card-body">
                <NodePackagePanel
                  :package-data="nodePackage"
                  :loading="nodeLoading"
                  :issue="nodeIssue"
                  :retry-loading="nodeLoading"
                  @open-file="handleOpenFileDetail"
                  @retry="handleRetryNodeLoad"
                />
              </div>
            </section>

            <NdtWorkflowPanel
              v-if="role === 'ndt'"
              :node="selectedNode"
              :films="ndtFilms"
              :records="ndtRecords"
              :reports="ndtReports"
              :feedback="ndtFeedback"
              :project-files="nodePackage?.projectFiles || []"
              :loading="actionLoading"
              :film-error="ndtFilmError"
              :record-import-error="ndtRecordImportError"
              :report-upload-error="ndtReportUploadError"
              :submit-error="ndtSubmitError"
              :rectify-error="ndtRectifyError"
              @create-film="handleCreateNdtFilm"
              @import-records="handleImportNdtRecords"
              @upload-material="handleOpenUploadDrawer"
              @view-material-file="handleOpenFileDetail"
              @upload-report="handleOpenNdtReportUpload"
              @replace-material-bindings="handleReplaceNdtAtomicBindings"
              @submit-material="handleSubmitNdtAtomicMaterial"
              @retry-upload="handleRetryProjectFileUpload"
              @rectify-ndt="handleRectifyNdt"
              @open-report-detail="handleOpenNdtReportDetail"
              @open-feedback-detail="handleOpenNdtFeedbackDetail"
            />

            <ReportArchivePanel
              v-if="
                role !== 'ndt' &&
                role !== 'contractor' &&
                (role !== 'inspection' ||
                  (activeWorkbenchSection === 'node' &&
                    ['report', 'archive'].includes(activeInspectionAuditItem)))
              "
              :id="
                role === 'inspection'
                  ? `inspection-audit-panel-${activeInspectionAuditItem}`
                  : 'inspection-node-report-archive'
              "
              :aria-label="role === 'inspection' ? activeInspectionAuditItemData?.label : undefined"
              :role="role"
              :aria-role="role === 'inspection' ? 'tabpanel' : undefined"
              :actions="availableActions"
              :package-data="nodePackage"
              :reports="inspectionNodeReports"
              :archive-items="inspectionNodeArchiveItems"
              :recent-export-tasks="recentReadOnlyExportTasks"
              :generate-disabled-reason="reportGenerateDisabledReason"
              :loading="actionLoading"
              :mode="
                role === 'inspection'
                  ? activeInspectionAuditItem === 'report'
                    ? 'report'
                    : 'archive'
                  : 'combined'
              "
              @generate-report="handleGenerateReport"
              @export-report="handleExportReport"
              @archive-report="handleArchiveReport"
              @preview-report="handlePreviewReport"
              @open-report-detail="handleOpenReportDetail"
              @open-archive-item-detail="handleOpenArchiveItemDetail"
              @download-archive-item="handleDownloadArchiveItem"
              @download-archive-package="handleDownloadArchivePackage"
              @download-evidence-package="handleDownloadEvidencePackage"
              @open-export-task="handleOpenExportTask"
            />

            <section
              v-if="role !== 'inspection' && role !== 'contractor' && role !== 'ndt'"
              class="center-support-grid"
            >
              <WorkbenchRightStaticDetails
                :role="role"
                :project="currentProject"
                :node="selectedNode"
                :package-data="nodePackage"
                :metrics="metrics"
                :review-steps="reviewChainSteps"
                :ai-confidence="aiConfidence"
                :reports="reports"
                :archive-items="archiveItems"
                :ndt-films="ndtFilms"
                :ndt-records="ndtRecords"
                :ndt-reports="ndtReports"
                :ndt-feedback="ndtFeedback"
              />

              <section class="right-card action-card">
                <h3>{{ role === 'owner' ? '强制限制' : '办理操作' }}</h3>
                <div class="body">
                  <div v-if="role === 'owner'" class="readonly-mask">
                    建设方页面不出现上传、退回、审查、复核、报告确认或归档操作按钮；这里只展示预览、浏览和摘要查看。
                  </div>
                  <WorkbenchActionBar
                    v-else
                    :role="role"
                    :actions="availableActions"
                    :loading="actionLoading"
                    :read-only="isReadOnly"
                    @upload="handleOpenUploadDrawer"
                    @bind="handleOpenBindDialog"
                    @save-draft="handleSaveDraft"
                    @submit="handleOpenSubmissionDialog"
                    @history="handleOpenSubmissionHistory"
                    @rectify="handleOpenRectificationDialog"
                  />
                </div>
              </section>

              <RoleContextPanel
                :role="role"
                :project="currentProject"
                :package-data="nodePackage"
                :todos="todos"
              />
              <ReviewDecisionPanel
                v-model:review-result="reviewResult"
                v-model:review-opinion="reviewOpinion"
                v-model:correction-reason="correctionReason"
                v-model:selected-evidence-ids="selectedReviewEvidenceIds"
                :role="role"
                :actions="availableActions"
                :latest-ai-run="latestAiRun"
                :evidence-count="evidenceLinks.length"
                :confirmed-evidence-links="confirmedEvidenceLinks"
                :save-disabled-reason="reviewSaveDisabledReason"
                :blocking-reasons="readinessBlockingReasons"
                :requires-evidence-selection="draftRequiresEvidenceSelection"
                :loading="actionLoading"
                @save-review="handleSaveReviewOpinion"
                @return-correction="handleReturnCorrection"
                @adopt-ai="handleAdoptAiSuggestion"
                @reject-ai="handleRejectAiSuggestion"
              />
              <WorkbenchSidePanel
                v-model="activeSideTab"
                :latest-ai-run="latestAiRun"
                :extracted-fields="extractedFields"
                :evidence-links="evidenceLinks"
                :standards="standardReferences"
                :date-comparisons="dateComparisons"
                :inspection-loading="inspectionDetailLoading"
                :todos="todos"
                :messages="messages"
                :review-opinions="reviewOpinions"
                @locate-evidence="handleLocateEvidence"
              />
            </section>
          </div>
        </main>
      </div>

      <ElDrawer
        v-if="role !== 'contractor' && role !== 'ndt' && compactNodeNavigation"
        v-model="mobileTreeOpen"
        class="mobile-tree-drawer"
        title="项目审核节点"
        direction="ltr"
        size="min(380px, 88vw)"
        append-to-body
        destroy-on-close
      >
        <div id="audit-node-navigation" class="mobile-tree-navigation">
          <ProjectNodeTree
            :groups="visibleTreeGroups"
            :active-node-id="activeWorkbenchSection === 'overview' ? 0 : activeNodeId"
            :show-overview="true"
            empty-description="暂无项目审核节点"
            @select="handleNodeSelect"
            @select-overview="handleProjectOverviewSelect"
          />
        </div>
      </ElDrawer>

      <ElDrawer
        v-model="previewDrawerVisible"
        :title="previewDrawerTitle"
        class="aicheck-preview-drawer"
        direction="rtl"
        size="min(760px, 92vw)"
        append-to-body
      >
        <div class="preview-drawer-panel">
          <div class="preview-name"
            >当前预览：{{ previewDrawerTarget.title || previewFileName }}</div
          >
          <div class="preview-source">{{ previewDrawerMeta }}</div>
          <div class="preview-actions">
            <ElButton class="btn" @click="activeSideTab = 'evidence'">定位证据</ElButton>
            <ElButton
              class="btn"
              :disabled="previewDrawerTarget.source === 'standard' || !firstBinding"
              @click="firstBinding && handleOpenFileDetail(firstBinding.documentId)"
            >
              详情
            </ElButton>
          </div>
          <div class="doc-preview">
            <div class="doc-toolbar">
              <span>{{ previewDrawerToolbarLabel }}</span>
            </div>
            <div class="doc-canvas">
              <div
                v-if="previewDrawerCanEmbedOriginal"
                class="doc-original-host"
                v-loading="previewDrawerLoadingOriginal"
              >
                <ElAlert
                  v-if="previewDrawerOriginalError"
                  :title="previewDrawerOriginalError"
                  type="warning"
                  :closable="false"
                  show-icon
                />
                <div v-else-if="!previewDrawerFrameUrl" class="doc-original-placeholder">
                  原文预览加载中
                </div>
                <img
                  v-else-if="previewDrawerIsImage"
                  class="doc-original-image"
                  :src="previewDrawerFrameUrl"
                  :alt="previewDrawerTarget.title"
                  @error="handlePreviewDrawerImageError"
                />
                <iframe
                  v-else
                  class="doc-original-frame"
                  :src="previewDrawerFrameUrl"
                  :title="previewDrawerTarget.title"
                ></iframe>
              </div>
              <div
                v-else-if="['file', 'standard'].includes(previewDrawerTarget.source)"
                class="doc-original-unavailable"
              >
                <ElAlert
                  :title="
                    previewDrawerTarget.previewType === 'office'
                      ? 'Office 文件不支持在线预览'
                      : '当前文件没有可预览的真实原文'
                  "
                  :description="previewDrawerOriginalUnavailableText"
                  type="warning"
                  :closable="false"
                  show-icon
                />
                <code v-if="previewDrawerTarget.url" class="doc-source-url">
                  {{ previewDrawerTarget.url }}
                </code>
              </div>
              <div v-else class="doc-paper">
                <div class="paper-title">
                  {{ role === 'owner' ? '监督检验项目状态摘要' : previewDrawerTarget.title }}
                </div>
                <table class="mini-doc-table">
                  <tbody>
                    <tr>
                      <td>项目名称</td>
                      <td colspan="3">{{ currentProject?.name || '-' }}</td>
                    </tr>
                    <tr>
                      <td>当前节点</td>
                      <td>{{ currentNodeLabel }}</td>
                      <td>节点状态</td>
                      <td>{{ selectedNode?.status || '-' }}</td>
                    </tr>
                    <tr v-for="field in extractedFields.slice(0, 3)" :key="field.id">
                      <td>{{ field.fieldName }}</td>
                      <td>{{ field.fieldValue }}</td>
                      <td>置信度</td>
                      <td>{{ formatConfidence(field.confidence) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </ElDrawer>

      <UploadSessionDrawer
        v-model="uploadDrawerVisible"
        :title="
          uploadDrawerReplaceTarget
            ? `替换资料：${uploadDrawerReplaceTarget.fileName}`
            : uploadDrawerMode === 'inspection'
              ? '上传监检资料'
              : uploadDrawerAtomicMaterial
                ? '上传无损检测资料'
                : '上传项目文件'
        "
        :node-name="selectedNode?.name"
        :material-category="uploadDrawerMaterialCategory"
        :material-type-code="uploadDrawerAtomicMaterial?.code"
        :material-type-name="uploadDrawerAtomicMaterial?.name"
        :default-node-ids="uploadDrawerAtomicMaterial?.defaultNodeIds"
        :allowed-node-ids="[...NDT_NODE_IDS]"
        :loading="actionLoading"
        :operation-error="uploadDrawerError"
        @submit="handleCreateUploadSession"
      />

      <NdtReportUploadDrawer
        v-model="ndtReportUploadVisible"
        :node-name="selectedNode?.name"
        :films="ndtFilms"
        :loading="actionLoading"
        :operation-error="ndtReportUploadError"
        @submit="handleCreateNdtReportUpload"
      />

      <DocumentBindDialog
        v-model="bindDialogVisible"
        :package-data="nodePackage"
        :tree-groups="treeGroups"
        :role="role"
        :loading="actionLoading"
        :operation-error="bindDialogError"
        :initial-document-id="bindDialogDocumentId"
        @submit="handleBindDocuments"
      />

      <SubmissionBatchDialog
        v-model="submissionDialogVisible"
        :package-data="nodePackage"
        :tree-groups="treeGroups"
        :draft-detail="restoredSubmissionDraft"
        :loading="actionLoading"
        :operation-error="submissionDialogError"
        @save-draft="handleSaveDraftFromDialog"
        @submit="handleSubmitBatch"
      />

      <EvidenceLocatorDialog
        v-model="evidenceDialogVisible"
        :project-id="activeProjectId"
        :evidence="activeEvidence"
        :extracted-fields="extractedFields"
      />

      <R12RegistryVerificationDialog
        v-if="!isR19HumanInputTask"
        v-model="humanInputDialogVisible"
        :task="activeHumanInputTask"
        :loading="humanInputLoading"
        @submit="handleSubmitR12HumanInput"
        @locate="handleLocateR12Candidate"
      />

      <R19SemanticEvidenceDialog
        v-else
        v-model="humanInputDialogVisible"
        :task="activeHumanInputTask"
        :loading="humanInputLoading"
        @submit="handleSubmitR19HumanInput"
        @locate="handleLocateR19Evidence"
      />

      <FileDetailDialog
        v-model="fileDetailVisible"
        :detail="fileDetail"
        :loading="fileDetailLoading"
        @preview="handlePreviewFile"
        @download="handleDownloadFile"
      />

      <SubmissionDetailDrawer
        v-model="submissionDetailVisible"
        :detail="submissionDetail"
        :loading="submissionDetailLoading"
      />

      <SubmissionHistoryDrawer
        v-model="submissionHistoryVisible"
        :drafts="submissionDrafts"
        :submissions="submissionSnapshots"
        :loading="submissionHistoryLoading"
        @refresh="loadSubmissionHistory"
        @open-draft="openDraftDetail"
        @restore-draft="handleRestoreSubmissionDraft"
        @open-submission="openSubmissionDetail"
      />

      <ReportDetailDrawer
        v-model="reportDetailVisible"
        :detail="reportDetail"
        :loading="reportDetailLoading"
        :saving="actionLoading"
        :issue="reportDetailError"
        @locate-evidence="handleLocateEvidence"
        @retry="handleRetryReportDetail"
        @save="handleSaveReportDetail"
        @transition="handleTransitionReport"
      />

      <NdtDetailDrawer
        v-model="ndtDetailVisible"
        :mode="ndtDetailMode"
        :report-detail="ndtReportDetail"
        :feedback-detail="ndtFeedbackDetail"
        :loading="ndtDetailLoading"
      />

      <ArchiveDetailDrawer
        v-model="archiveDetailVisible"
        :detail="archiveDetail"
        :loading="archiveDetailLoading"
        :issue="archiveDetailError"
        @preview="handlePreviewArchiveUrl"
        @download="handleDownloadUrl"
        @open-export-task="handleOpenExportTask"
        @retry="handleRetryArchiveDetail"
      />

      <ExportTaskDrawer
        v-model="exportTaskVisible"
        :task="exportTask"
        :loading="exportTaskLoading"
        :issue="exportTaskError"
        @download="handleDownloadUrl"
        @retry="handleRetryExportTask"
      />

      <RectificationDetailDialog
        v-model="rectificationDialogVisible"
        :node="selectedNode"
        :bindings="bindings"
        :todos="todos"
        :rectification-id="activeRectificationId"
        :loading="actionLoading"
        @submit="handleSubmitRectification"
      />

      <GlobalQuickAccessDialog
        v-model="quickAccessVisible"
        v-model:active-tab="quickAccessTab"
        v-model:keyword="quickAccessKeyword"
        :search-results="quickSearchResults"
        :todos="quickTodos"
        :messages="quickMessages"
        :loading="quickAccessLoading"
        @search="handleQuickSearch"
        @complete-todo="handleCompleteQuickTodo"
        @open-todo="handleOpenQuickTodo"
        @open-message="handleOpenQuickMessage"
        @read-message="handleReadQuickMessage"
        @read-all-messages="handleReadAllQuickMessages"
        @locate-result="handleLocateQuickResult"
      />
    </div>
  </div>
</template>

<style scoped>
.aicheck-static-viewport {
  --bg: var(--aicheck-bg, #f4f7fb);
  --panel: var(--aicheck-surface, #fff);
  --panel-soft: var(--aicheck-surface-soft, #f8fbff);
  --panel-muted: var(--aicheck-surface-muted, #f2f6fb);
  --line: var(--aicheck-border, #d4deeb);
  --line-soft: var(--aicheck-border-soft, #e5ecf6);
  --line-strong: var(--aicheck-border-strong, #c2d1e3);
  --head: var(--aicheck-surface-muted, #f2f6fb);
  --ink: var(--aicheck-text-strong, #172033);
  --muted: var(--aicheck-text-muted, #52647d);
  --blue: var(--aicheck-primary, #1f66d8);
  --blue-2: var(--aicheck-primary-strong, #174fa8);
  --blue-soft: #eaf3ff;
  --green: var(--aicheck-success, #087443);
  --green-soft: var(--aicheck-success-bg, #ecfdf3);
  --orange: var(--aicheck-warning, #8a4b00);
  --orange-soft: var(--aicheck-warning-bg, #fff7e6);
  --red: var(--aicheck-danger, #b42318);
  --red-soft: var(--aicheck-danger-bg, #fef3f2);
  --shadow: var(--aicheck-shadow-xs, 0 1px 2px rgb(20 34 56 / 5%));
  --shadow-sm: var(--aicheck-shadow-sm, 0 6px 16px rgb(15 23 42 / 6%));
  --shadow-md: var(--aicheck-shadow-md, 0 14px 32px rgb(15 23 42 / 9%));

  width: 100%;
  height: 100vh;
  max-width: 100vw;
  overflow: hidden;
  font-family: var(--aicheck-font-family);
  color: var(--ink);
  background: var(--bg);
}

.aicheck-static-viewport *,
.aicheck-static-viewport *::before,
.aicheck-static-viewport *::after {
  box-sizing: border-box;
}

.aicheck-page.app-shell {
  display: grid;
  width: 100%;
  height: 100vh;
  max-width: 100vw;
  min-width: 0;
  min-height: 0;
  padding: 0;
  overflow-x: hidden;
  background: var(--bg);
  grid-template-rows: auto minmax(0, 1fr);
}

.topbar {
  position: relative;
  z-index: 2;
  display: grid;
  min-width: 0;
  min-height: 68px;
  padding: 0 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  box-shadow: 0 8px 22px rgb(15 23 42 / 5%);
  grid-template-columns: minmax(280px, 404px) minmax(260px, 1fr) minmax(260px, 520px);
  gap: 18px;
  align-items: center;
}

.skip-main {
  position: fixed;
  top: 8px;
  left: 8px;
  z-index: 1000;
  padding: 9px 12px;
  color: #fff;
  text-decoration: none;
  background: var(--blue-2);
  border-radius: 8px;
  transform: translateY(-160%);
  box-shadow: 0 8px 24px rgb(15 23 42 / 18%);
  transition: transform 0.18s ease;
}

.skip-main:focus-visible {
  outline: 3px solid rgb(255 255 255 / 80%);
  outline-offset: 2px;
  transform: translateY(0);
}

.brand {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(180deg, #4b86ff, #1761d2);
  border-radius: 8px;
  place-items: center;
}

.project-title-select {
  width: 100%;
  min-width: 0;
}

.project-title-select :deep(.el-select__wrapper) {
  min-height: 34px;
  padding: 0 18px 0 0;
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
  font-weight: 760;
  line-height: 1.16;
  letter-spacing: 0;
  color: var(--ink);
  text-rendering: geometricprecision;
  background: transparent;
  box-shadow: none;
  align-items: center;
}

.project-title-select :deep(.el-select__selection),
.project-title-select :deep(.el-select__input-wrapper) {
  width: 100%;
  min-width: 0;
}

.project-title-select :deep(.el-select__selected-item) {
  min-width: 0;
  overflow: visible;
  line-height: 1.16;
  overflow-wrap: anywhere;
  text-overflow: clip;
  white-space: normal;
}

.project-title-select :deep(.el-select__placeholder) {
  display: block;
  max-width: 100%;
  overflow: visible;
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
  font-weight: 760;
  line-height: 1.16;
  color: #24344d;
  text-overflow: clip;
  text-rendering: geometricprecision;
  white-space: normal;
  overflow-wrap: anywhere;
}

.project-title-select :deep(.el-select__placeholder span) {
  display: block;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.project-title-select :deep(.el-select__input) {
  width: 100% !important;
  height: auto;
  min-width: 100% !important;
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
  font-weight: 760;
  line-height: 1.16;
  letter-spacing: 0;
  color: #24344d;
  text-rendering: geometricprecision;
}

.project-title-select :deep(.el-select__caret) {
  font-size: 15px;
  font-weight: 760;
  color: var(--blue-2);
}

.top-status {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  height: 36px;
  padding: 0 14px;
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid #bcd6ff;
  border-radius: 5px;
}

.pill-blue,
.top-status.pill-blue {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #bcd4ff;
}

.pill-green,
.top-status.pill-green {
  color: var(--green);
  background: var(--green-soft);
  border-color: #bdebd1;
}

.pill-orange,
.top-status.pill-orange {
  color: var(--orange);
  background: var(--orange-soft);
  border-color: #ffd399;
}

.pill-red,
.top-status.pill-red {
  color: var(--red);
  background: var(--red-soft);
  border-color: #ffc5bd;
}

.global-search {
  --el-button-bg-color: #fff;
  --el-button-border-color: #cbd8ea;
  --el-button-hover-bg-color: #f8fbff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: #52647d;
  --el-button-active-bg-color: #eef5ff;
  --el-button-active-border-color: #8fb0df;
  --el-button-active-text-color: #52647d;

  display: flex;
  width: min(720px, 100%);
  height: 40px;
  padding: 0 16px;
  margin: 0;
  font-weight: 600;
  color: var(--muted);
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 6px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  align-items: center;
  justify-content: flex-start;
  justify-self: center;
}

.global-search :deep(span) {
  justify-content: flex-start;
  width: 100%;
}

.global-search:hover,
.global-search:focus-visible {
  color: #52647d;
  background: #f8fbff;
  border-color: #9db8df;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.top-actions {
  display: flex;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
  font-size: 15px;
  color: #27364d;
  white-space: nowrap;
  scrollbar-width: none;
  flex-wrap: nowrap;
  gap: 14px;
  align-items: center;
  justify-content: flex-end;
}

/* 首屏第一句话：现在有没有要我管的、在哪儿。
   原先这里是四张数字卡片，最大的那个 471 不驱动任何行动。 */
.inspection-headline {
  display: flex;
  padding: 14px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
}

/* 没有待办时不该继续用告警色——那会让人一直处在「有事没办」的错觉里 */
.inspection-headline.is-clear {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.inspection-headline-main {
  display: flex;
  min-width: 220px;
  flex-direction: column;
  flex: 1;
  gap: 4px;
}

.inspection-headline-main strong {
  font-size: 20px;
  color: #7f1d1d;
}

.inspection-headline.is-clear .inspection-headline-main strong {
  color: #14532d;
}

.inspection-headline-main small {
  font-size: 13px;
  color: #64748b;
}

.inspection-headline-rest {
  display: flex;
  margin: 0;
  gap: 18px;
  flex-wrap: wrap;
}

.inspection-headline-rest div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.inspection-headline-rest dt {
  font-size: 12px;
  color: #94a3b8;
}

.inspection-headline-rest dd {
  margin: 0;
  font-size: 15px;
  color: #475569;
}

.node-filter-toggle {
  margin-left: 12px;
  font-weight: 400;
}

/* 节点状态：一个词说清「要不要我管」，卡点与进度做次要信息 */
.node-status-cell {
  display: flex;
  width: 100%;
  padding: 2px 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: none;
  gap: 8px;
  align-items: center;
}

.node-status-pill {
  padding: 3px 10px;
  font-size: 13px;
  border-radius: 999px;
  flex: none;
}

/* 只有这一种需要人动，配色上要能一眼从整列里跳出来 */
.node-status-pill.is-attention {
  color: #b91c1c;
  background: #fee2e2;
}

.node-status-pill.is-running {
  color: #1d4ed8;
  background: #dbeafe;
}

.node-status-pill.is-done {
  color: #15803d;
  background: #dcfce7;
}

.node-status-pill.is-idle {
  color: #64748b;
  background: #f1f5f9;
}

.node-status-where {
  font-size: 12px;
  color: #92400e;
}

.node-status-progress {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
}

/* 视图分段控件：一眼看出是「二选一」，不是两个可点的动作 */
.view-segmented {
  display: inline-flex;
  padding: 2px;
  background: #eef1f6;
  border-radius: 999px;
  gap: 2px;
  flex: none;
}

.view-segment {
  display: inline-flex;
  padding: 5px 14px;
  font: inherit;
  font-size: 14px;
  color: #5b6b85;
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: none;
  border-radius: 999px;
  gap: 5px;
  align-items: center;
  transition:
    background 0.15s,
    color 0.15s;
}

.view-segment:hover:not(.is-active) {
  color: #27364d;
  background: rgb(255 255 255 / 60%);
}

.view-segment.is-active {
  color: #1d4ed8;
  background: #fff;
  box-shadow: 0 1px 3px rgb(15 23 42 / 10%);
}

.top-actions::-webkit-scrollbar {
  display: none;
}

.top-actions .top-action.el-button {
  --el-button-bg-color: transparent;
  --el-button-border-color: transparent;
  --el-button-hover-bg-color: #f4f8ff;
  --el-button-hover-border-color: transparent;
  --el-button-hover-text-color: var(--blue-2);
  --el-button-active-bg-color: #eef5ff;
  --el-button-active-border-color: transparent;
  --el-button-active-text-color: var(--blue-2);

  display: inline-flex;
  min-height: 32px;
  padding: 0 4px;
  margin: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 5px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
  align-items: center;
}

.top-actions .top-action.el-button:hover,
.top-actions .top-action.el-button:focus-visible,
.top-actions .top-action.el-button.is-active {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.notice-dot {
  display: inline-flex;
  height: 22px;
  min-width: 22px;
  padding: 0 6px;
  margin-left: 2px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #ef3f3b;
  border-radius: 999px;
  align-items: center;
  justify-content: center;
}

.avatar {
  width: 32px;
  height: 32px;
  background: linear-gradient(180deg, #4b83f7, #1e5ec8);
  border-radius: 50%;
}

.user-menu {
  flex: 0 0 auto;
}

.user {
  display: inline-flex;
  min-height: 40px;
  padding: 0 8px 0 4px;
  font-weight: 600;
  color: inherit;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 999px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease;
  gap: 8px;
  align-items: center;
}

.user:hover,
.user:focus-visible {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.user-caret {
  font-size: 12px;
  line-height: 1;
  color: #6a7890;
}

.static-issue {
  padding: 20px;
}

.workspace {
  display: grid;
  width: 100%;
  height: 100%;
  max-width: 100vw;
  min-height: 0;
  overflow: hidden;
  grid-template-columns: minmax(300px, 404px) minmax(0, 1fr);
  transition: grid-template-columns 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.workspace.no-left-nav {
  grid-template-columns: minmax(0, 1fr);
}

.workspace.is-left-collapsed {
  grid-template-columns: minmax(28px, 28px) minmax(0, 1fr);
}

.left,
.center {
  min-height: 0;
}

.inspection-ai-review-region,
.inspection-review-list-region {
  min-width: 0;
}

.center.is-inspection-ai-workspace {
  min-height: 0;
  overflow: hidden;
}

.center.is-inspection-ai-workspace > .inspection-ai-review-region {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.left {
  position: relative;
  display: grid;
  height: 100%;
  overflow: visible;
  background: #fff;
  border-right: 1px solid var(--line);
  transition: background-color 180ms ease-out;
  grid-template-rows: minmax(0, 1fr);
}

.left.is-collapsed {
  background: #f8fbff;
}

.sidebar-collapse-toggle.el-button {
  position: absolute;
  right: -18px;
  bottom: 18px;
  z-index: 50;
  width: 36px;
  height: 36px;
  min-width: 36px;
  padding: 0;
  margin: 0;
  color: #52647d;
  background: #fff;
  border-color: #cbd8ea;
  box-shadow: 0 4px 12px rgb(15 23 42 / 12%);
}

.sidebar-collapse-toggle.el-button:hover,
.sidebar-collapse-toggle.el-button:focus-visible {
  color: var(--blue-2);
  background: #f4f8ff;
  border-color: #9db8df;
  outline: 0;
  box-shadow:
    0 4px 12px rgb(15 23 42 / 12%),
    0 0 0 3px rgb(31 102 216 / 12%);
}

.sidebar-collapse-toggle .el-icon {
  font-size: 16px;
  transition: transform 200ms cubic-bezier(0.22, 1, 0.36, 1);
}

.left.is-collapsed .sidebar-collapse-toggle .el-icon {
  transform: rotate(180deg);
}

.tree-wrap {
  min-height: 0;
  overflow: hidden auto;
  opacity: 1;
  visibility: visible;
  transform: translateX(0);
  transition:
    opacity 180ms ease-out 40ms,
    transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
    visibility 0s;
}

.left.is-collapsed .tree-wrap {
  pointer-events: none;
  opacity: 0;
  visibility: hidden;
  transform: translateX(-8px);
  transition:
    opacity 120ms ease-in,
    transform 160ms ease-in,
    visibility 0s 160ms;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 18px;
  font-size: 18px;
  font-weight: 600;
}

.section-tools {
  display: inline-flex;
  font-size: 16px;
  color: #6e7d92;
  gap: 8px;
}

.tree-wrap :deep(.tree-panel) {
  height: calc(100% - 44px);
  border: 0;
  border-radius: 0;
}

.tree-wrap :deep(.el-card__header) {
  display: none;
}

.tree-wrap :deep(.el-card__body) {
  height: 100%;
  padding: 8px 18px 16px;
  overflow: auto;
  border-bottom: 1px solid var(--line);
}

.tree-wrap :deep(.tree-scroll) {
  --el-tree-node-hover-bg-color: transparent;

  max-height: none;
  background: transparent;
}

.tree-wrap :deep(.node-tree .el-tree-node__content) {
  height: auto;
  min-height: 44px;
  padding-left: 0 !important;
  line-height: 1.2;
  color: #26364e;
  background: transparent;
}

.tree-wrap :deep(.node-tree .el-tree-node__content:hover),
.tree-wrap :deep(.node-tree .el-tree-node.is-current > .el-tree-node__content) {
  background: transparent;
}

.tree-wrap :deep(.node-tree .el-tree-node__expand-icon) {
  width: 28px;
  height: 28px;
  margin-right: 2px;
  font-size: 18px;
  color: #6e7d92;
  flex: 0 0 28px;
}

.tree-wrap :deep(.node-tree .el-tree-node__expand-icon svg) {
  width: 18px;
  height: 18px;
}

.tree-wrap :deep(.node-tree .el-tree-node__children .el-tree-node__content) {
  padding-left: 0 !important;
}

.tree-wrap :deep(.node-tree .el-tree-node__expand-icon.is-leaf) {
  flex: 0 0 0;
  width: 0;
  height: 0;
  margin-right: 0;
  visibility: hidden;
}

.tree-wrap :deep(.node-group-title) {
  position: static;
  display: block;
  width: 100%;
  padding: 8px 0;
  font-size: 14px;
  font-weight: 600;
  color: #26364e;
  background: #fff;
}

.tree-wrap :deep(.node-overview-button),
.tree-wrap :deep(.node-button) {
  display: grid;
  min-height: 40px;
  padding: 6px 8px;
  margin: 0 0 4px 8px;
  font-weight: 600;
  color: #26364e;
  white-space: normal;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.tree-wrap :deep(.node-overview-button) {
  margin: 0 0 8px;
  background: #f8fbff;
  border-color: #dbe8f7;
}

.tree-wrap :deep(.node-button:hover),
.tree-wrap :deep(.node-button.is-active),
.tree-wrap :deep(.node-overview-button:hover),
.tree-wrap :deep(.node-overview-button.is-active) {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #9dc0f7;
}

.tree-wrap :deep(.node-button:focus-visible),
.tree-wrap :deep(.node-overview-button:focus-visible) {
  color: var(--blue-2);
  background: #f4f8ff;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 14%);
}

.tree-wrap :deep(.node-button.is-active),
.tree-wrap :deep(.node-overview-button.is-active) {
  box-shadow: none;
}

.tree-wrap :deep(.node-index) {
  width: auto;
  height: auto;
  font-size: 13px;
  font-weight: 600;
  color: inherit;
  background: transparent;
}

.tree-wrap :deep(.node-name) {
  display: block;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  color: inherit;
  white-space: normal;
  overflow-wrap: anywhere;
}

.tree-wrap :deep(.node-meta) {
  font-size: 12px;
  color: var(--muted);
}

.center {
  --center-top-gutter: 18px;

  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
  overflow-anchor: none;
  opacity: 1;
  transform: translateY(0);
  transition:
    opacity 300ms ease-in,
    transform 300ms ease-in;
}

/* X-5 未选节点空状态 */
.node-unselected {
  display: flex;
  padding: 48px 16px;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.node-unselected-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}

.node-unselected-hint {
  margin: 0;
  max-width: 420px;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

/* X-3 执行过程折叠开关 —— 与 AI 复核 B 版工作台同一交互 */
.execution-toggle {
  display: flex;
  width: 100%;
  margin-bottom: 12px;
  padding: 10px 14px;
  font: inherit;
  text-align: left;
  color: inherit;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s;
}

.execution-toggle:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.execution-toggle-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.execution-toggle-copy strong {
  font-size: 14px;
  color: #1f2937;
}

.execution-toggle-copy small {
  font-size: 12px;
  color: #64748b;
}

.execution-toggle-chevron {
  font-size: 18px;
  color: #94a3b8;
  transition: transform 0.2s;
}

.execution-toggle-chevron.is-open {
  transform: rotate(180deg);
}

/* X-4 工具标签：显示业务名，悬浮看能力说明 */
.execution-tool-tag {
  display: inline-block;
  padding: 2px 8px;
  font-size: 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  cursor: help;
}

/* AI 结论置顶卡片 */
.ai-outcome {
  margin-bottom: 14px;
  padding: 14px 16px;
  background: linear-gradient(180deg, #f8fafc, #fff);
  border: 1px solid #dbe3ee;
  border-radius: 10px;
}

.ai-outcome-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}

.ai-outcome-label {
  font-size: 13px;
  color: #64748b;
}

.ai-outcome-result {
  font-size: 18px;
  color: #1f2937;
}

.ai-outcome-conf {
  font-size: 12px;
  color: #64748b;
}

.ai-outcome-block {
  margin-top: 10px;
}

.ai-outcome-block-label {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #64748b;
}

.ai-outcome-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.ai-outcome-chip {
  padding: 2px 10px;
  font-size: 13px;
  color: #b45309;
  background: #fef3c7;
  border-radius: 10px;
}

.ai-outcome-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
}

.center.has-flush-audit-directory {
  padding-top: 0;
}

.center.has-flush-audit-directory > :first-child:not(.inspection-review-list-region) {
  margin-top: var(--center-top-gutter);
}

.center.has-flush-audit-directory > .inspection-review-list-region {
  padding-top: var(--center-top-gutter);
}

.center.is-workbench-page-leaving {
  will-change: opacity, transform;
  opacity: 0;
  transform: translateY(-12px);
}

.center.is-workbench-page-hidden {
  opacity: 0;
  transform: translateY(12px);
  transition: none;
}

.center.is-workbench-page-entering {
  will-change: opacity, transform;
  animation: workbench-page-enter 500ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes workbench-page-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.center-support-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: start;
  margin-top: 12px;
}

.center-support-grid :deep(.workbench-right-static-details),
.center-support-grid :deep(.side-panel) {
  grid-column: 1 / -1;
}

.page-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  margin-bottom: 12px;
}

.crumbs {
  margin-bottom: 5px;
  font-size: 14px;
  font-weight: 600;
  color: var(--muted);
}

.crumbs :deep(.el-breadcrumb__inner),
.crumbs :deep(.el-breadcrumb__separator) {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.page-title,
h1 {
  margin: 0;
  font-size: var(--aicheck-font-size-page);
  font-weight: 600;
  line-height: var(--aicheck-line-height-page);
}

h2 {
  margin: 0;
  font-size: var(--aicheck-font-size-section);
  line-height: var(--aicheck-line-height-section);
}

h3 {
  margin: 0;
  font-size: var(--aicheck-font-size-card);
  line-height: var(--aicheck-line-height-card);
}

.sub {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 400;
  line-height: 22px;
  color: var(--muted);
}

.inspection-overview-jump-menu {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.inspection-overview-jump-button {
  min-height: 36px;
  padding: 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: #1f66d8;
  cursor: pointer;
  background: #f8fbff;
  border: 1px solid #b9d2fb;
  border-radius: 6px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.inspection-overview-jump-button:hover,
.inspection-overview-jump-button:focus-visible {
  color: #0f4fb9;
  background: #eef5ff;
  border-color: #85acec;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

#inspection-node-basis,
#inspection-node-requirements,
#inspection-node-evidence,
#inspection-node-execution,
#inspection-node-conclusion,
#inspection-node-manual-review {
  scroll-margin-top: 88px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.workbench-action-tooltip {
  display: inline-flex;
}

:global(.audit-action-tooltip-popper) {
  max-width: min(420px, calc(100vw - 24px));
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.global-search,
.top-actions .top-action.el-button,
.user {
  min-height: 44px;
}

.btn {
  --el-button-text-color: #26364e;
  --el-button-bg-color: #fff;
  --el-button-border-color: #cbd8ea;
  --el-button-hover-bg-color: #f8fbff;
  --el-button-hover-border-color: #9db8df;
  --el-button-hover-text-color: var(--blue-2);
  --el-button-active-bg-color: #eef5ff;
  --el-button-active-border-color: #8fb0df;
  --el-button-active-text-color: var(--blue-2);

  display: inline-flex;
  min-height: 44px;
  padding: 0 17px;
  margin: 0;
  font-weight: 600;
  color: #26364e;
  text-decoration: none;
  cursor: pointer;
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 5px;
  transition:
    color 0.18s ease,
    background-color 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
  align-items: center;
  justify-content: center;
}

.btn.el-button + .btn.el-button {
  margin-left: 0;
}

.btn:hover:not(:disabled),
.btn:focus-visible:not(:disabled) {
  color: var(--blue-2);
  background: #f8fbff;
  border-color: #9db8df;
  outline: 0;
  box-shadow: 0 0 0 3px rgb(31 102 216 / 12%);
}

.btn:disabled,
.btn.is-disabled {
  cursor: not-allowed;
  opacity: 0.56;
}

.btn.primary {
  --el-button-text-color: #fff;
  --el-button-bg-color: var(--blue);
  --el-button-border-color: var(--blue);
  --el-button-hover-bg-color: var(--blue-2);
  --el-button-hover-border-color: var(--blue-2);
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: var(--blue-2);
  --el-button-active-border-color: var(--blue-2);
  --el-button-active-text-color: #fff;

  color: #fff;
  background: var(--blue);
  border-color: var(--blue);
}

.btn.primary:hover:not(:disabled),
.btn.primary:focus-visible:not(:disabled) {
  color: #fff;
  background: var(--blue-2);
  border-color: var(--blue-2);
}

.btn.orange {
  --el-button-text-color: #fff;
  --el-button-bg-color: #ff5a27;
  --el-button-border-color: #ff5a27;
  --el-button-hover-bg-color: #e84d1e;
  --el-button-hover-border-color: #e84d1e;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #d84419;
  --el-button-active-border-color: #d84419;
  --el-button-active-text-color: #fff;

  color: #fff;
  background: #ff5a27;
  border-color: #ff5a27;
}

.btn.orange:hover:not(:disabled),
.btn.orange:focus-visible:not(:disabled) {
  color: #fff;
  background: #e84d1e;
  border-color: #e84d1e;
}

.card {
  margin-bottom: 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.card:hover,
.card:focus-within {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-sm);
}

.card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 13px 16px;
  background: var(--panel-soft);
  border-bottom: 1px solid var(--line-soft);
}

.card-body {
  padding: 14px 16px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.metric {
  min-height: 72px;
  padding: 14px;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.metric-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.metric-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1;
  color: var(--blue);
}

.metric-value.green {
  color: var(--green);
}

.metric-value.orange {
  color: var(--orange);
}

.metric-value.red {
  color: var(--red);
}

.metric-value.gray {
  color: #64748b;
}

.inspection-project-overview {
  display: grid;
  gap: 12px;
  padding: 14px;
  margin-bottom: 16px;
  background: linear-gradient(180deg, var(--panel), var(--panel-soft));
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
}

.inspection-project-overview-head {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  justify-content: space-between;
  min-width: 0;
}

.inspection-project-overview-head div,
.inspection-project-overview-head span,
.inspection-project-overview-head strong,
.inspection-project-overview-head small {
  min-width: 0;
}

.inspection-project-overview-head div > span {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #2563eb;
}

.inspection-project-overview-head strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 600;
  line-height: 24px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-project-overview-head small {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
}

.inspection-overview-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.inspection-overview-card {
  min-width: 0;
  min-height: 92px;
  padding: 12px;
  background: #fff;
  border: 1px solid #dbe6f5;
  border-radius: 8px;
}

.inspection-overview-card span,
.inspection-overview-card strong,
.inspection-overview-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-overview-card span {
  font-size: 12px;
  font-weight: 600;
  color: #667085;
}

.inspection-overview-card strong {
  margin-top: 8px;
  font-size: 20px;
  font-weight: 600;
  line-height: 26px;
  color: #172033;
}

.inspection-overview-card small {
  margin-top: 6px;
  font-size: 12px;
  line-height: 17px;
  color: #667085;
}

.inspection-overview-card--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.inspection-overview-card--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.inspection-overview-card--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.inspection-overview-card--red {
  background: #fff3f1;
  border-color: #ffc9c3;
}

.inspection-overview-main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.inspection-overview-panel {
  min-width: 0;
  min-height: 280px;
  padding: 14px 16px 12px;
  background: #fff;
  border: 1px solid #e1eaf7;
  border-radius: 8px;
  scroll-margin-top: 16px;
}

.inspection-overview-panel--status {
  grid-column: 1 / -1;
  min-height: auto;
}

.inspection-overview-panel--files {
  min-height: 0;
}

.inspection-node-status-bars {
  display: grid;
  gap: 10px;
  width: 100%;
  padding: 12px 2px 4px;
}

.inspection-node-status-row {
  display: grid;
  grid-template-columns: minmax(82px, 136px) minmax(220px, 1fr) minmax(72px, auto);
  gap: 12px;
  align-items: center;
  min-width: 0;
  min-height: 38px;
  padding: 4px 0;
}

.inspection-node-status-row span {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;
  color: #52617a;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-node-status-track {
  position: relative;
  height: 26px;
  min-width: 0;
  overflow: hidden;
  background: repeating-linear-gradient(
      90deg,
      transparent 0,
      transparent calc(20% - 1px),
      #e5edf8 calc(20% - 1px),
      #e5edf8 20%
    ),
    #f7faff;
  border: 1px solid #dbe8f7;
  border-radius: 8px;
}

.inspection-node-status-track i {
  display: block;
  height: 100%;
  min-width: 3px;
  background: #2563eb;
  border-radius: 7px;
  box-shadow: 0 7px 18px rgb(37 99 235 / 20%);
}

.inspection-node-status-track::after {
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  content: '';
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 55%);
}

.inspection-node-status-row strong {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
  font-size: 16px;
  font-weight: 600;
  line-height: 22px;
  color: #172033;
  text-align: left;
  font-variant-numeric: tabular-nums;
}

.inspection-node-status-row strong small {
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  color: var(--muted);
}

.inspection-node-status-row--green .inspection-node-status-track i {
  background: #16a34a;
  box-shadow: 0 7px 18px rgb(22 163 74 / 20%);
}

.inspection-node-status-row--orange .inspection-node-status-track i {
  background: #f59e0b;
  box-shadow: 0 7px 18px rgb(245 158 11 / 20%);
}

.inspection-node-status-row--red .inspection-node-status-track i {
  background: #dc2626;
  box-shadow: 0 7px 18px rgb(220 38 38 / 18%);
}

.inspection-audit-status-summary {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  padding-top: 12px;
}

.inspection-audit-status-card {
  --inspection-status-color: #667085;
  --inspection-status-surface: #f5f7fa;

  min-width: 0;
  overflow: hidden;
  background: var(--inspection-status-surface);
  border: 0;
  border-radius: 10px;
  box-shadow: 0 6px 18px rgb(15 23 42 / 5%);
}

.inspection-audit-status-card :deep(.el-card__body) {
  display: flex;
  min-height: 84px;
  padding: 12px 14px;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
}

.inspection-audit-status-card.is-in_progress {
  --inspection-status-color: #2563eb;
  --inspection-status-surface: #f1f6ff;
}

.inspection-audit-status-card.is-needs_attention {
  --inspection-status-color: #b45309;
  --inspection-status-surface: #fff7e8;
}

.inspection-audit-status-card.is-failed {
  --inspection-status-color: #c4322a;
  --inspection-status-surface: #fff3f1;
}

.inspection-audit-status-card.is-completed {
  --inspection-status-color: #16804a;
  --inspection-status-surface: #effaf4;
}

.inspection-audit-status-card__label,
.inspection-audit-status-card__metric {
  display: flex;
  align-items: center;
}

.inspection-audit-status-card__label {
  gap: 7px;
}

.inspection-audit-status-card__label i {
  width: 7px;
  height: 7px;
  background: var(--inspection-status-color);
  border-radius: 50%;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--inspection-status-color) 12%, transparent);
  flex: 0 0 auto;
}

.inspection-audit-status-card__label span {
  font-size: 12px;
  font-weight: 650;
  line-height: 18px;
  color: var(--inspection-status-color);
}

.inspection-audit-status-card__metric {
  align-items: baseline;
  gap: 6px;
}

.inspection-audit-status-card__metric strong {
  font-size: 25px;
  line-height: 30px;
  letter-spacing: -0.02em;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.inspection-audit-status-card__metric small {
  font-size: 12px;
  font-weight: 500;
  line-height: 17px;
  color: #536176;
}

.inspection-node-table {
  width: 100%;
  margin-top: 10px;
}

.inspection-node-table :deep(.el-table__row.active > td.el-table__cell) {
  background: #f8fbff;
}

.inspection-audit-matrix {
  display: grid;
  grid-template-columns: repeat(7, minmax(64px, 1fr));
  gap: 6px;
}

.inspection-audit-matrix-item {
  --inspection-status-color: #667085;

  display: grid;
  min-width: 64px;
  min-height: 52px;
  padding: 5px 4px;
  color: #344054;
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--inspection-status-color);
  border-radius: 6px;
  place-items: center;
  grid-template-columns: auto 6px;
  column-gap: 4px;
  transition:
    background-color 180ms ease-out,
    box-shadow 180ms ease-out;
}

.inspection-audit-matrix-item.is-in_progress {
  --inspection-status-color: #2563eb;
}

.inspection-audit-matrix-item.is-needs_attention {
  --inspection-status-color: #b45309;
}

.inspection-audit-matrix-item.is-failed {
  --inspection-status-color: #dc2626;
}

.inspection-audit-matrix-item.is-completed {
  --inspection-status-color: #16803c;
}

.inspection-audit-matrix-item:hover,
.inspection-audit-matrix-item:focus-visible {
  background: color-mix(in srgb, var(--inspection-status-color) 8%, #fff);
  outline: 0;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--inspection-status-color) 30%, transparent);
}

.inspection-audit-matrix-item span {
  font-size: 12px;
  font-weight: 700;
  line-height: 16px;
  white-space: nowrap;
}

.inspection-audit-matrix-item i {
  width: 6px;
  height: 6px;
  background: var(--inspection-status-color);
  border-radius: 50%;
}

.inspection-audit-matrix-item small {
  grid-column: 1 / -1;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  color: var(--inspection-status-color);
  white-space: nowrap;
}

.inspection-audit-matrix-loading {
  width: 100%;
  min-width: 280px;
  padding: 4px 0;
}

.inspection-audit-matrix-loading :deep(.el-skeleton__paragraph) {
  margin-top: 0;
}

.inspection-audit-matrix-loading :deep(.el-skeleton__item) {
  height: 12px;
}

.inspection-node-material {
  display: flex;
  gap: 8px;
  align-items: baseline;
  justify-content: space-between;
  font-variant-numeric: tabular-nums;
}

.inspection-node-material strong {
  font-size: 14px;
  font-weight: 600;
  color: #172033;
}

.inspection-node-material span {
  font-size: 12px;
  font-weight: 600;
  color: #1f66d8;
}

.inspection-node-material-progress {
  margin-top: 6px;
}

.inspection-node-missing {
  display: block;
  max-width: 280px;
  margin-top: 5px;
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  line-height: 16px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-node-pagination {
  justify-content: flex-end;
  margin-top: 12px;
}

.inspection-node-progress-list,
.inspection-next-action-list {
  display: grid;
  gap: 8px;
}

.inspection-node-progress-list {
  max-height: 360px;
  padding-right: 4px;
  overflow: auto;
}

.inspection-node-progress-item,
.inspection-next-action-item {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  min-width: 0;
  padding: 10px;
  font: inherit;
  text-align: left;
  background: #f8fbff;
  border: 1px solid #e1eaf7;
  border-radius: 8px;
}

.inspection-node-progress-item {
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.inspection-node-progress-item:hover,
.inspection-node-progress-item:focus-visible,
.inspection-node-progress-item.active {
  background: #eef5ff;
  border-color: #9dc0f7;
  outline: none;
  transform: translateY(-1px);
}

.inspection-node-progress-item span,
.inspection-next-action-item span {
  grid-row: span 2;
  min-height: 28px;
  padding: 6px 7px;
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
  text-align: center;
  background: #eef5ff;
  border: 1px solid #cfe0ff;
  border-radius: 6px;
}

.inspection-node-progress-item strong,
.inspection-next-action-item strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  line-height: 18px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-node-progress-item small,
.inspection-next-action-item small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  line-height: 17px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-node-progress-item em {
  grid-row: span 2;
  font-size: 13px;
  font-style: normal;
  font-weight: 600;
  color: #2563eb;
  font-variant-numeric: tabular-nums;
}

.inspection-next-action-item {
  grid-template-columns: 62px minmax(0, 1fr);
}

.inspection-next-action-item--green {
  background: #f3fbf7;
  border-color: #c9ead8;
}

.inspection-next-action-item--blue {
  background: #f4f8ff;
  border-color: #cfe0ff;
}

.inspection-next-action-item--orange {
  background: #fff8ed;
  border-color: #f6d6a5;
}

.inspection-next-action-item--red {
  background: #fff3f1;
  border-color: #ffc9c3;
}

.overview-file-toolbar {
  display: flex;
  align-items: center;
  max-width: 560px;
  margin: 10px 0 12px;
}

.overview-file-table {
  width: 100%;
}

.file-name-with-icon {
  display: inline-flex;
  max-width: 100%;
  min-width: 0;
  gap: 8px;
  align-items: center;
  vertical-align: middle;
}

.file-name-with-icon > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspection-node-name-button {
  max-width: 100%;
  justify-content: flex-start;
}

.inspection-node-name-content {
  text-align: left;
}

.overview-file-source {
  display: block;
  margin-top: 2px;
  color: var(--muted);
}

.overview-file-action {
  padding: 0;
  font-weight: 600;
}

.overview-ocr-status {
  display: block;
  margin-top: 5px;
  font-size: 12px;
  font-weight: 600;
  color: #52677f;
}

.overview-ocr-status.is-ready {
  color: #157347;
}

.overview-ocr-status.is-incomplete,
.overview-ocr-status.is-inconsistent,
.overview-ocr-status.is-failed {
  color: #a53b00;
}

.overview-file-pagination {
  justify-content: flex-end;
  margin-top: 12px;
}

.inspection-chart-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 8px;
}

.inspection-chart-head strong,
.inspection-chart-head small {
  display: block;
}

.inspection-chart-head strong {
  font-size: 15px;
  font-weight: 600;
  color: #172033;
}

.inspection-chart-head small {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #667085;
}

.pill {
  display: inline-flex;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  color: var(--blue-2);
  white-space: nowrap;
  background: var(--blue-soft);
  border: 1px solid #bcd4ff;
  border-radius: 5px;
  align-items: center;
  justify-content: center;
}

.pill.blue {
  color: var(--blue-2);
  background: var(--blue-soft);
  border-color: #bcd4ff;
}

.pill.green {
  color: var(--green);
  background: var(--green-soft);
  border-color: #bdebd1;
}

.pill.orange {
  color: var(--orange);
  background: var(--orange-soft);
  border-color: #ffd399;
}

.pill.red {
  color: var(--red);
  background: var(--red-soft);
  border-color: #ffc5bd;
}

.table {
  width: 100%;
  font-size: 14px;
  border-collapse: collapse;
  table-layout: fixed;
}

.table th,
.table td,
.mini-doc-table td {
  padding: 10px 11px;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  vertical-align: middle;
  border: 1px solid var(--line-soft);
  transition: background-color 0.18s ease;
}

.table th {
  font-weight: 600;
  color: #485a73;
  background: var(--head);
}

.table.compact th,
.table.compact td {
  padding: 8px 9px;
  font-size: 13px;
}

.table tbody tr:hover th,
.table tbody tr:hover td {
  background: #f4f8ff;
}

.table tr.selected th,
.table tr.selected td {
  background: var(--blue-soft);
}

.review-chain {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.basis-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.basis-meta-item {
  min-height: 72px;
  padding: 12px;
  background: #f8fbff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.basis-meta-item span,
.overall-conclusion span {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.basis-meta-item strong {
  display: block;
  font-size: 16px;
  line-height: 1.45;
  color: var(--ink);
}

.basis-block-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.basis-block,
.basis-table-block,
.standard-reference-block,
.overall-conclusion,
.conclusion-point,
.execution-step {
  padding: 14px;
  background: #fff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.basis-block {
  min-width: 0;
  padding: 20px;
  overflow: hidden;
  border-color: #e2e9f4;
  border-radius: 12px;
  box-shadow: 0 8px 28px rgb(43 74 123 / 6%);
}

.basis-block--criteria {
  background: linear-gradient(155deg, #fff 0%, #fbfcff 100%);
}

.basis-block--method {
  background: linear-gradient(155deg, #fff 0%, #f9fbff 100%);
}

.basis-block-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  padding-bottom: 15px;
  border-bottom: 1px solid #e8edf5;
}

.basis-block-icon {
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  font-size: 19px;
  color: #376fc7;
  background: #edf4ff;
  border-radius: 11px;
}

.basis-block--method .basis-block-icon {
  color: #6c5fc7;
  background: #f1efff;
}

.basis-block-kicker {
  display: block;
  margin-bottom: 3px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0.08em;
  color: #5f6d84;
}

.basis-block h3,
.basis-table-block h3,
.standard-reference-block h3,
.execution-step h3,
.conclusion-point h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--ink);
}

.overall-conclusion p,
.conclusion-point p {
  margin: 8px 0 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.7;
  color: #344054;
  white-space: pre-wrap;
}

.basis-reference-list {
  padding: 0;
  margin: 6px 0 0;
  list-style: none;
}

.basis-reference-list li {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid #edf1f6;
}

.basis-reference-list li:last-child {
  border-bottom: 0;
}

.basis-reference-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 700;
  color: #2f63b5;
  font-variant-numeric: tabular-nums;
  background: #edf4ff;
  border-radius: 9px;
}

.basis-reference-list p,
.basis-method-item p {
  max-width: 72ch;
  margin: 2px 0 0;
  font-size: 14px;
  font-weight: 400;
  line-height: 1.72;
  color: #344054;
}

.basis-decision-note {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  margin-top: 10px;
  color: #79520a;
  background: #fff8e8;
  border-radius: 10px;
}

.basis-decision-note > .el-icon {
  flex: 0 0 auto;
  margin-top: 3px;
  font-size: 16px;
}

.basis-decision-note strong,
.basis-decision-note span {
  display: block;
}

.basis-decision-note strong {
  margin-bottom: 3px;
  font-size: 12px;
  font-weight: 700;
}

.basis-decision-note span {
  font-size: 13px;
  line-height: 1.6;
}

.basis-method-list {
  position: relative;
  display: grid;
  gap: 0;
  margin-top: 8px;
}

.basis-method-item {
  position: relative;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 10px;
  padding: 11px 0;
}

.basis-method-item:not(:last-child)::after {
  position: absolute;
  top: 39px;
  bottom: -5px;
  left: 13px;
  width: 2px;
  background: #e1e7f3;
  border-radius: 2px;
  content: '';
}

.basis-method-step {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-size: 12px;
  font-weight: 700;
  color: #6154b5;
  background: #f0eeff;
  border-radius: 50%;
}

.basis-method-item small {
  display: block;
  margin-bottom: 3px;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.4;
  color: #626d83;
}

.basis-agent-note {
  padding: 14px 16px;
  margin-top: 10px;
  color: #37405f;
  background: linear-gradient(135deg, #f4f1ff 0%, #f2f7ff 100%);
  border-radius: 11px;
}

.basis-agent-note__head {
  display: flex;
  gap: 7px;
  align-items: center;
  margin-bottom: 9px;
}

.basis-agent-note__head .el-icon {
  font-size: 16px;
  color: #6658bc;
}

.basis-agent-note__head strong {
  font-size: 13px;
  font-weight: 700;
  color: #3d356e;
}

.basis-agent-note__head span {
  padding: 2px 7px;
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: #7066a8;
  background: rgb(255 255 255 / 72%);
  border-radius: 999px;
}

.basis-agent-note ul {
  display: grid;
  gap: 6px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.basis-agent-note li {
  position: relative;
  padding-left: 14px;
  font-size: 13px;
  font-weight: 400;
  line-height: 1.65;
}

.basis-agent-note li::before {
  position: absolute;
  top: 0.72em;
  left: 1px;
  width: 5px;
  height: 5px;
  background: #8a7cd8;
  border-radius: 50%;
  content: '';
}

.block-title-row,
.execution-step-head,
.conclusion-point-head,
.manual-review-head {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.basis-table-block {
  margin-bottom: 14px;
}

.basis-table-wrap {
  margin-top: 12px;
  overflow-x: auto;
  border-radius: 6px;
}

.basis-table {
  width: 100%;
  min-width: 980px;
}

.basis-table :deep(.el-table__cell) {
  padding: 10px 0;
}

.basis-table-secondary,
.standard-reference-chip small {
  display: block;
  margin-top: 4px;
  line-height: 1.45;
  color: var(--muted);
}

.inspection-bound-files-title {
  margin-top: 18px;
}

.inspection-bound-files-table,
.inspection-ocr-table {
  margin-top: 10px;
}

.inspection-audit-state-banner {
  margin: 10px 0 12px;
}

.inspection-ocr-panel {
  min-height: 300px;
}

.inspection-audit-empty {
  padding: 28px 16px;
  margin-top: 12px;
  font-size: 14px;
  line-height: 22px;
  color: var(--muted);
  text-align: center;
  background: var(--panel-soft);
  border: 1px dashed var(--line);
  border-radius: 6px;
}

.node-ai-recheck-top {
  padding: 14px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.node-ai-recheck-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.mobile-tree-trigger {
  display: none;
}

:global(.mobile-tree-drawer .el-drawer__body) {
  padding: 0 12px 16px;
}

:global(.mobile-tree-drawer .tree-panel) {
  height: calc(100dvh - 84px);
  max-height: none;
}

.ai-review-mode-control {
  display: grid;
  gap: 6px;
  min-width: min(100%, 360px);
}

.ai-review-mode-control small {
  font-size: 12px;
  line-height: 1.5;
  color: #52677f;
}

.ai-review-mode-control :deep(.el-radio-button__inner) {
  min-height: 44px;
  padding: 12px 18px;
  font-weight: 600;
  letter-spacing: 0;
}

.node-ai-recheck-button {
  min-width: 180px;
  min-height: 44px;
  font-weight: 600;
  border-radius: 5px;
}

.evidence-confirmation-block {
  overflow: hidden;
}

.evidence-confirmation-table {
  margin-top: 12px;
}

.evidence-confirmation-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.evidence-confirmation-actions :deep(.el-button) {
  margin-left: 0;
  font-weight: 600;
}

.standard-reference-tree-shell {
  margin-top: 12px;
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.standard-reference-tree {
  --el-tree-node-hover-bg-color: #f2f7ff;
  --el-fill-color-light: #f2f7ff;

  padding: 6px 0;
}

.standard-reference-tree :deep(.el-tree-node__content) {
  height: 52px;
  padding-right: 10px;
  border-bottom: 1px solid #edf2f8;
}

.standard-reference-tree :deep(.el-tree-node__content:focus-visible) {
  outline: 2px solid var(--blue);
  outline-offset: -2px;
}

.standard-reference-tree :deep(.el-tree-node:last-child > .el-tree-node__content) {
  border-bottom: 0;
}

.standard-tree-node {
  display: flex;
  min-width: 0;
  flex: 1;
  gap: 10px;
  align-items: center;
}

.standard-tree-node.is-file {
  cursor: pointer;
}

.standard-tree-icon {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  color: #54749a;
}

.standard-tree-node.is-file .standard-tree-icon {
  color: var(--blue);
}

.standard-tree-copy {
  min-width: 0;
  flex: 1;
}

.standard-tree-copy strong,
.standard-tree-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.standard-tree-copy strong {
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  color: var(--ink);
}

.standard-tree-copy small {
  font-size: 13px;
  font-weight: 400;
  line-height: 18px;
  color: var(--muted);
}

.standard-tree-node.is-root .standard-tree-copy strong {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.standard-tree-node.is-group .standard-tree-copy strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.standard-tree-preview-state {
  display: inline-flex;
  min-width: 58px;
  flex: 0 0 auto;
  gap: 4px;
  align-items: center;
  justify-content: flex-end;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  transition: color 0.18s ease;
}

.standard-reference-tree :deep(.el-tree-node__content:hover) .standard-tree-preview-state,
.standard-reference-tree
  :deep(.el-tree-node.is-current > .el-tree-node__content)
  .standard-tree-preview-state {
  color: var(--blue);
}

.standard-tree-preview-state svg {
  width: 15px;
  height: 15px;
}

.standard-tree-preview-state.is-unavailable {
  color: var(--muted);
}

.empty-inline {
  font-weight: 600;
  color: var(--muted);
}

.execution-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.execution-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.step-no {
  display: grid;
  width: 28px;
  height: 28px;
  font-weight: 600;
  color: #fff;
  background: var(--blue);
  border-radius: 50%;
  place-items: center;
}

.step-title {
  font-weight: 600;
}

.execution-step-detail {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 10px 0 0;
}

.execution-step-detail div {
  padding: 10px;
  background: #f8fbff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.execution-step-detail dt {
  margin-bottom: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
}

.execution-step-detail dd {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.55;
  color: var(--ink);
}

.step-desc {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.6;
  color: #344054;
}

.evidence-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.evidence-link-button {
  padding: 0;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--blue);
  text-decoration: underline;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.conclusion-points {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.conclusion-point {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
}

.conclusion-point-order {
  display: grid;
  width: 28px;
  height: 28px;
  font-weight: 600;
  color: var(--blue);
  background: #eef5ff;
  border: 1px solid #bcd4ff;
  border-radius: 6px;
  place-items: center;
}

.manual-review-section {
  margin-bottom: 12px;
}

.manual-review-head {
  padding: 16px;
  margin-bottom: 10px;
  background: #fff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  box-shadow: var(--shadow);
}

.manual-review-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(420px, 1.2fr);
  gap: 12px;
  align-items: start;
}

.operation-blocker-alert {
  grid-column: 1 / -1;
}

.operation-blocker-list {
  padding-left: 18px;
  margin: 4px 0 0;
  line-height: 1.6;
}

.preview-name {
  font-weight: 600;
  color: #26364e;
}

.preview-source {
  margin-top: 6px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: #68788f;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}

.preview-drawer-panel {
  min-height: 100%;
  padding: 18px 20px 24px;
  overflow-x: hidden;
  background: #fff;
}

:global(.aicheck-preview-drawer .el-drawer__header) {
  padding: 16px 20px;
  margin-bottom: 0;
  font-weight: 600;
  color: #26364e;
  border-bottom: 1px solid var(--line, #cbd8ea);
}

:global(.aicheck-preview-drawer) {
  --line: #cbd8ea;
  --line-soft: #dde6f2;
  --head: #f3f7fc;
  --blue-soft: #eff6ff;
  --blue-2: #1f66d8;
}

:global(.aicheck-preview-drawer .el-drawer__body) {
  padding: 0;
  overflow: auto;
  background: #fff;
}

.doc-preview {
  overflow: hidden;
  background: #f4f7fb;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.doc-toolbar {
  display: flex;
  height: 38px;
  padding: 0 12px;
  font-weight: 600;
  color: #40516b;
  background: #fff;
  border-bottom: 1px solid var(--line);
  align-items: center;
  justify-content: space-between;
}

.doc-canvas {
  min-height: 340px;
  padding: 18px;
}

.doc-original-host {
  min-height: 520px;
}

.doc-original-placeholder {
  display: flex;
  min-height: 520px;
  align-items: center;
  justify-content: center;
  color: #667085;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.doc-original-image {
  display: block;
  width: 100%;
  max-height: 680px;
  object-fit: contain;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.doc-original-unavailable {
  display: flex;
  min-height: 300px;
  flex-direction: column;
  gap: 12px;
  justify-content: center;
  padding: 18px;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.doc-source-url {
  display: block;
  max-width: 100%;
  padding: 10px;
  color: #475467;
  background: #f3f4f6;
  border-radius: 6px;
  overflow-wrap: anywhere;
}

.doc-original-frame {
  width: 100%;
  min-height: 520px;
  background: #fff;
  border: 1px solid #d5deea;
  border-radius: 4px;
}

.doc-paper {
  min-height: 300px;
  padding: 24px;
  background: #fff;
  border: 1px solid #d5deea;
  box-shadow: 0 10px 24px rgb(23 32 51 / 8%);
}

.paper-title {
  margin-bottom: 18px;
  font-size: 20px;
  font-weight: 600;
  text-align: center;
}

.mini-doc-table {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
  table-layout: fixed;
}

.mini-doc-table td:nth-child(odd) {
  font-weight: 600;
  color: #485a73;
  background: var(--head);
}

.right-card {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.right-card:hover,
.right-card:focus-within {
  border-color: #c4d5ee;
  box-shadow: 0 2px 8px rgb(20 34 56 / 8%);
}

.right-card h3 {
  padding: 13px 16px;
  border-bottom: 1px solid var(--line-soft);
}

.right-card .body {
  padding: 14px 16px;
}

.readonly-mask {
  padding: 12px;
  font-weight: 600;
  line-height: 1.6;
  color: #6b2b24;
  background: var(--red-soft);
  border: 1px solid #ffc5bd;
  border-radius: 6px;
}

.readonly-banner {
  margin-bottom: 12px;
}

.node-package-card :deep(.el-card.panel),
.center-support-grid :deep(.el-card.panel),
.center :deep(.report-panel),
.center :deep(.ndt-panel) {
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.node-package-card :deep(.el-card__header) {
  padding-top: 0;
}

.center-support-grid :deep(.panel),
.center :deep(.report-panel),
.center :deep(.ndt-panel) {
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.right-card :deep(.action-bar) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  justify-content: stretch;
  margin-top: 0;
}

.right-card :deep(.action-bar .el-button) {
  width: 100%;
  margin-left: 0;
  font-weight: 600;
  border-radius: 5px;
}

.ai-recheck-output {
  margin-top: 12px;
  overflow: hidden;
  color: #26364e;
  background: #f8fbff;
  border: 1px solid #c8d8ee;
  border-radius: 6px;
}

.ai-recheck-output-head {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: #eef5ff;
  border-bottom: 1px solid #c8d8ee;
}

.ai-recheck-output-head strong {
  font-size: 14px;
  font-weight: 600;
}

.ai-recheck-output-head small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ai-recheck-output-alert {
  margin: 10px 12px 0;
}

.ai-finding-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ai-finding-list li {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e6ebf2;
  border-radius: 8px;
}

.ai-finding-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ai-finding-meta {
  color: #667085;
  font-size: 12px;
}

.ai-finding-title {
  margin-top: 6px;
  font-weight: 600;
  color: #1f2d3d;
}

.ai-finding-desc {
  margin-top: 4px;
  color: #47536b;
  line-height: 1.6;
  white-space: pre-wrap;
}

.ai-recheck-output-section {
  padding: 10px 12px 12px;
}

.ai-recheck-output-section + .ai-recheck-output-section {
  border-top: 1px solid #dde6f2;
}

.ai-recheck-technical-details {
  --el-collapse-border-color: transparent;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;

  border-top: 1px solid #dde6f2;
}

.ai-recheck-technical-details :deep(.el-collapse-item__header) {
  min-height: 44px;
  padding: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #35516f;
  border: 0;
}

.ai-recheck-technical-details :deep(.el-collapse-item__wrap) {
  border: 0;
}

.ai-recheck-technical-details :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.ai-recheck-output-section label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #485a73;
}

.ai-recheck-output-section pre {
  max-height: 180px;
  padding: 10px;
  margin: 0;
  overflow: auto;
  font:
    12px/1.6 ui-monospace,
    SFMono-Regular,
    Menlo,
    Monaco,
    Consolas,
    'Liberation Mono',
    'Courier New',
    monospace;
  word-break: break-word;
  white-space: pre-wrap;
  background: #fff;
  border: 1px solid #dde6f2;
  border-radius: 5px;
}

@media (width <= 1360px) {
  .topbar {
    grid-template-columns: minmax(260px, 360px) minmax(220px, 1fr);
  }

  .top-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .workspace {
    grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
    overflow-y: auto;
  }

  .inspection-overview-main-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .inspection-overview-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 900px) {
  .aicheck-static-viewport {
    height: 100vh;
    overflow-y: auto;
  }

  .aicheck-page.app-shell {
    grid-template-rows: auto 1fr;
    height: auto;
    min-height: 100vh;
  }

  .aicheck-page.app-shell.is-inspection-ai-page {
    height: 100vh;
    min-height: 0;
    overflow: hidden;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .aicheck-page.app-shell.is-inspection-ai-page .workspace {
    display: grid;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    grid-template-columns: minmax(0, 1fr);
  }

  .aicheck-page.app-shell.is-inspection-ai-page .center {
    height: 100%;
    min-height: 0;
  }

  .topbar,
  .workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .inspection-project-overview-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .inspection-overview-card-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .basis-meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .basis-block-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .inspection-audit-status-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .inspection-audit-status-card:last-child {
    grid-column: 1 / -1;
  }

  .workspace {
    display: block;
    height: auto;
    overflow: visible;
  }

  .topbar {
    gap: 10px;
    min-height: 68px;
    padding: 10px 12px;
  }

  .brand {
    grid-template-columns: 34px minmax(0, 1fr);
  }

  .top-status {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .left,
  .center {
    min-height: auto;
  }

  .left {
    display: none;
  }

  .mobile-tree-trigger {
    display: inline-flex;
  }

  .center {
    --center-top-gutter: 14px;

    height: auto;
    padding: 14px 12px 18px;
  }

  .center.has-flush-audit-directory {
    padding-top: 0;
  }

  .center-support-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-audit-board,
  .metrics,
  .result-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 560px) {
  .basis-meta-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .basis-block {
    padding: 16px;
  }

  .basis-reference-list p,
  .basis-method-item p {
    font-size: 15px;
  }

  .basis-agent-note li {
    font-size: 14px;
  }

  .workbench-audit-board,
  .metrics,
  .result-grid {
    grid-template-columns: 1fr;
  }

  .inspection-node-status-row {
    grid-template-columns: minmax(76px, 92px) minmax(120px, 1fr) minmax(62px, auto);
    gap: 8px;
  }

  .inspection-node-status-row span {
    font-size: 13px;
    text-align: left;
  }
}

.ai-human-input-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  margin: 12px 0;
  background: #fff8e8;
  border: 1px solid #f3c66c;
  border-radius: 10px;
}

.ai-human-input-card > div {
  display: grid;
  gap: 4px;
}

.ai-human-input-card span {
  font-size: 13px;
  color: #765827;
}

@media (prefers-reduced-motion: reduce) {
  .center.is-workbench-page-entering {
    animation: none;
  }

  .center,
  .workspace,
  .tree-wrap,
  .sidebar-collapse-toggle .el-icon {
    transition: none;
  }

  .global-search,
  .top-actions .top-action.el-button,
  .tree-wrap :deep(.node-button),
  .btn,
  .card,
  .right-card,
  .table th,
  .table td,
  .mini-doc-table td {
    transition: none;
  }

  .left {
    transition: none;
  }
}
</style>
