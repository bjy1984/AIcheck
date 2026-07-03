<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ElButton,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElMessage,
  ElOption,
  ElSelect
} from 'element-plus'
import {
  adoptAiSuggestionApi,
  archiveReportApi,
  bindDocumentsToNodeApi,
  completeTodoApi,
  createNdtFilmApi,
  createNdtReportUploadSessionApi,
  createDocumentUploadSessionApi,
  getArchivePackageApi,
  getArchiveItemDetailApi,
  getDocumentDetailApi,
  getEvidencePackageApi,
  getExportTaskApi,
  getInspectionDateCompareApi,
  getNdtInspectionFeedbackDetailApi,
  getNdtReportDetailApi,
  getReportDetailApi,
  exportReportApi,
  importNdtRecordsApi,
  generateReportReviewApi,
  getNodePackageApi,
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
  requestAiRecheckApi,
  returnCorrectionApi,
  saveReviewOpinionApi,
  saveSubmissionDraftApi,
  searchApi,
  submitNdtRectificationApi,
  submitNdtSubmissionApi,
  submitNodePackageApi,
  submitRectificationApi,
  withdrawSubmissionItemsApi
} from '@/api/aicheck'
import type {
  ArchiveItemDetailPayload,
  DateComparisonItem,
  DocumentDetailPayload,
  NdtFeedbackDetailPayload,
  NdtReportDetailPayload,
  ProjectTreePayload,
  ReportDetailPayload,
  StandardReference,
  SubmissionDetailPayload,
  SubmissionDraftDetailPayload,
  SubmissionDraftSummary,
  SubmissionSummary
} from '@/api/aicheck'
import type {
  ActionCode,
  ArchiveItem,
  EvidenceLink,
  ExportTask,
  NdtFeedback,
  NdtFilm,
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
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { Echart } from '@/components/Echart'
import AuditSummaryGrid, { type AuditSummaryCard } from './components/AuditSummaryGrid.vue'
import ArchiveDetailDrawer from './components/ArchiveDetailDrawer.vue'
import DocumentBindDialog from './components/DocumentBindDialog.vue'
import EvidenceLocatorDialog from './components/EvidenceLocatorDialog.vue'
import ExportTaskDrawer from './components/ExportTaskDrawer.vue'
import FileDetailDialog from './components/FileDetailDialog.vue'
import GlobalQuickAccessDialog from './components/GlobalQuickAccessDialog.vue'
import NdtDetailDrawer from './components/NdtDetailDrawer.vue'
import NdtWorkflowPanel from './components/NdtWorkflowPanel.vue'
import NodePackagePanel from './components/NodePackagePanel.vue'
import ProjectNodeTree from './components/ProjectNodeTree.vue'
import RectificationDetailDialog from './components/RectificationDetailDialog.vue'
import ReportArchivePanel from './components/ReportArchivePanel.vue'
import ReportDetailDrawer from './components/ReportDetailDrawer.vue'
import ReviewDecisionPanel from './components/ReviewDecisionPanel.vue'
import RoleContextPanel from './components/RoleContextPanel.vue'
import SubmissionBatchDialog from './components/SubmissionBatchDialog.vue'
import SubmissionDetailDrawer from './components/SubmissionDetailDrawer.vue'
import SubmissionHistoryDrawer from './components/SubmissionHistoryDrawer.vue'
import UploadSessionDrawer from './components/UploadSessionDrawer.vue'
import WorkbenchActionBar from './components/WorkbenchActionBar.vue'
import WorkbenchRoleStaticSections from './components/WorkbenchRoleStaticSections.vue'
import WorkbenchRightStaticDetails from './components/WorkbenchRightStaticDetails.vue'
import WorkbenchSidePanel from './components/WorkbenchSidePanel.vue'
import WorkbenchStateBanner from './components/WorkbenchStateBanner.vue'
import { useUserStore } from '@/store/modules/user'

type PreviewDrawerTarget = {
  source: 'node' | 'file' | 'report' | 'archive'
  title: string
  url?: string
  meta?: string
}

const roleConfig: Record<RoleCode, { title: string; subtitle: string }> = {
  inspection: { title: '监检工作台', subtitle: '资料审查、AI 复核、补正闭环' },
  contractor: { title: '施工方工作台', subtitle: '资料上传、节点提交、补正反馈' },
  ndt: { title: '无损检测工作台', subtitle: '检测报告提交、证据链维护' },
  owner: { title: '建设方工作台', subtitle: '项目进度、报告与归档资料查看' },
  admin: { title: '管理工作台', subtitle: '系统配置与审计' },
  fde: { title: 'FDE 后台', subtitle: 'AI 交付、效果监控与治理' }
}

type WorkbenchStateIssue = {
  type: 'error' | 'forbidden' | 'readonly' | 'empty'
  title: string
  message?: string
}

const route = useRoute()
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
const activeSideTab = ref('ai')
const previewDrawerVisible = ref(false)
const previewDrawerTarget = ref<PreviewDrawerTarget>({
  source: 'node',
  title: '当前节点资料预览'
})
const uploadDrawerVisible = ref(false)
const uploadDrawerError = ref('')
const bindDialogVisible = ref(false)
const bindDialogError = ref('')
const submissionDialogVisible = ref(false)
const submissionDialogError = ref('')
const submissionHistoryVisible = ref(false)
const submissionHistoryLoading = ref(false)
const withdrawSuccessMessage = ref('')
const evidenceDialogVisible = ref(false)
const rectificationDialogVisible = ref(false)
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
const correctionReason = ref('证据链或资料内容与规则要求不一致，需补充说明。')
const latestSubmissionIds = ref<Record<number, string>>({})

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
const bindings = computed(() => nodePackage.value?.bindings || [])
const extractedFields = computed(() => nodePackage.value?.extractedFields || [])
const reviewOpinions = computed(() => nodePackage.value?.reviewOpinions || [])
const latestAiRun = computed(() => nodePackage.value?.aiRuns[0])
const evidenceLinks = computed(() => latestAiRun.value?.evidenceLinks || [])
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
const getMetricValue = (key: string, label: string) => {
  const metric = metrics.value.find((item) => item.key === key || item.label.includes(label))
  if (!metric) return 0
  if (typeof metric.value === 'number') return metric.value
  const parsed = Number.parseFloat(String(metric.value).replace(/[^\d.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : 0
}
const inspectionAuditMetricItems = computed(() => [
  {
    key: 'todo',
    label: '待办',
    value: getMetricValue('todo', '待办'),
    color: '#f59e0b',
    hint: '需要监检员处理'
  },
  {
    key: 'correction',
    label: '补正项',
    value: getMetricValue('correction', '补正'),
    color: '#dc2626',
    hint: '影响当前节点通过'
  },
  {
    key: 'evidence',
    label: '证据引用',
    value: getMetricValue('evidence', '证据'),
    color: '#2563eb',
    hint: '可回溯 OCR/字段证据'
  },
  {
    key: 'passed',
    label: '已通过节点',
    value: getMetricValue('passed', '通过'),
    color: '#16a34a',
    hint: '已形成确认结论'
  }
])
const inspectionClosureItems = computed(() => {
  const todo = getMetricValue('todo', '待办')
  const correction = getMetricValue('correction', '补正')
  const passed = getMetricValue('passed', '通过')
  const data = [
    { name: '待办', value: todo, itemStyle: { color: '#f59e0b' } },
    { name: '补正项', value: correction, itemStyle: { color: '#dc2626' } },
    { name: '已通过节点', value: passed, itemStyle: { color: '#16a34a' } }
  ]
  return data.some((item) => item.value > 0)
    ? data
    : [{ name: '暂无处理项', value: 1, itemStyle: { color: '#d7dde8' } }]
})
const inspectionOpenIssueCount = computed(
  () => getMetricValue('todo', '待办') + getMetricValue('correction', '补正')
)
const inspectionAuditBarOption = computed<EChartsOption>(() => ({
  aria: {
    enabled: true,
    description: '当前审查对象的待办、补正项、证据引用和已通过节点数量柱状图。'
  },
  color: inspectionAuditMetricItems.value.map((item) => item.color),
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    formatter: (params) => {
      const item = Array.isArray(params) ? params[0] : params
      const name = String(item?.name || '')
      const found = inspectionAuditMetricItems.value.find((metric) => metric.label === name)
      return `${name}<br/>数量：${Number(item?.value || 0)}<br/>${found?.hint || ''}`
    }
  },
  grid: { top: 26, right: 18, bottom: 34, left: 36, containLabel: true },
  xAxis: {
    type: 'category',
    data: inspectionAuditMetricItems.value.map((item) => item.label),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#d8e5f5' } },
    axisLabel: { color: '#667085', fontWeight: 700 }
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#edf2f7' } },
    axisLabel: { color: '#8a94a6' }
  },
  series: [
    {
      name: '审查态势',
      type: 'bar',
      barMaxWidth: 30,
      data: inspectionAuditMetricItems.value.map((item) => ({
        value: item.value,
        itemStyle: {
          color: item.color,
          borderRadius: [6, 6, 0, 0]
        }
      })),
      label: {
        show: true,
        position: 'top',
        color: '#172033',
        fontWeight: 900
      }
    }
  ]
}))
const inspectionClosurePieOption = computed<EChartsOption>(() => ({
  aria: {
    enabled: true,
    description: '当前审查对象的人工处理闭环环形图。'
  },
  tooltip: {
    trigger: 'item',
    formatter: '{b}<br/>数量：{c}（{d}%）'
  },
  legend: {
    bottom: 0,
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: '#667085', fontWeight: 700 }
  },
  graphic: [
    {
      type: 'text',
      left: 'center',
      top: '39%',
      silent: true,
      style: {
        text: inspectionOpenIssueCount.value
          ? `${inspectionOpenIssueCount.value}\n待处理`
          : '0\n阻断',
        textAlign: 'center',
        fill: '#172033',
        font: '900 18px sans-serif',
        lineHeight: 22
      }
    }
  ],
  series: [
    {
      name: '人工处理闭环',
      type: 'pie',
      radius: ['56%', '74%'],
      center: ['50%', '40%'],
      avoidLabelOverlap: true,
      label: { show: false },
      labelLine: { show: false },
      data: inspectionClosureItems.value
    }
  ]
}))
const projectTreeNodes = computed<ProjectTreeNode[]>(() =>
  treeGroups.value.flatMap((group) => group.nodes || [])
)
const inspectionProjectNodeStatusRows = computed(() => {
  const counts: Record<string, number> = {}
  for (const node of projectTreeNodes.value) {
    counts[node.status] = (counts[node.status] || 0) + 1
  }
  const rows = Object.entries(counts).map(([status, count]) => ({ status, count }))
  return rows.length ? rows : [{ status: '暂无节点', count: 0 }]
})
const inspectionProjectPassedNodes = computed(
  () => projectTreeNodes.value.filter((node) => node.status === '已通过').length
)
const inspectionProjectBlockedNodes = computed(
  () =>
    projectTreeNodes.value.filter((node) =>
      ['需补正', '补正中', '待人工确认'].includes(node.status)
    ).length
)
const inspectionLowConfidenceFieldCount = computed(
  () =>
    extractedFields.value.filter((field) => {
      const confidence = Number(field.confidence || 0)
      return confidence > 0 && confidence < 0.82
    }).length
)
const inspectionProjectOverviewCards = computed(() => {
  const totalNodes = projectTreeNodes.value.length
  const totalFiles = projectTreeNodes.value.reduce(
    (sum, node) => sum + Number(node.fileCount || 0),
    0
  )
  const totalRequired = projectTreeNodes.value.reduce(
    (sum, node) => sum + Number(node.requiredProgress?.total || 0),
    0
  )
  const totalDone = projectTreeNodes.value.reduce(
    (sum, node) => sum + Number(node.requiredProgress?.done || 0),
    0
  )
  return [
    {
      label: '项目进度',
      value: `${inspectionProjectPassedNodes.value}/${totalNodes || 0} 节点`,
      hint: `资料要求完成 ${totalDone}/${totalRequired || 0}`,
      tone: 'blue'
    },
    {
      label: '当前卡点',
      value: `${inspectionProjectBlockedNodes.value} 个节点`,
      hint: `${inspectionOpenIssueCount.value} 项待办/补正`,
      tone: inspectionProjectBlockedNodes.value ? 'red' : 'green'
    },
    {
      label: '资料证据',
      value: `${totalFiles} 份文件`,
      hint: `当前节点 ${bindings.value.length} 份，证据 ${evidenceLinks.value.length}`,
      tone: 'green'
    },
    {
      label: 'AI 复核',
      value: latestAiRun.value?.suggestion.result || '等待预审',
      hint: `${inspectionLowConfidenceFieldCount.value} 个低置信 OCR 字段需关注`,
      tone: latestAiRun.value ? 'orange' : 'blue'
    }
  ]
})
const inspectionProjectNodeRows = computed(() =>
  projectTreeNodes.value.slice(0, 8).map((node) => {
    const total = Number(node.requiredProgress?.total || 0)
    const done = Number(node.requiredProgress?.done || 0)
    return {
      node,
      progress: total ? Math.round((done / total) * 100) : 0,
      evidence: `资料 ${node.fileCount} · 要求 ${done}/${total || 0}`
    }
  })
)
const inspectionNodeStatusBarRows = computed(() => {
  const totalCount = inspectionProjectNodeStatusRows.value.reduce(
    (sum, row) => sum + Number(row.count || 0),
    0
  )
  const maxCount = Math.max(...inspectionProjectNodeStatusRows.value.map((row) => row.count), 0)
  return inspectionProjectNodeStatusRows.value.map((row) => {
    const tone =
      row.status === '已通过'
        ? 'green'
        : row.status.includes('补正') || row.status.includes('人工')
          ? 'red'
          : row.status.includes('预审') || row.status.includes('待审')
            ? 'orange'
            : 'blue'
    return {
      ...row,
      tone,
      percent: totalCount ? Math.round((row.count / totalCount) * 100) : 0,
      barPercent: maxCount ? Math.max(3, Math.round((row.count / maxCount) * 100)) : 0,
      ratioText: totalCount ? `${Math.round((row.count / totalCount) * 100)}%` : '0%'
    }
  })
})
const inspectionProjectNextActions = computed(() => {
  const rows: Array<{ title: string; description: string; tag: string; tone: string }> = []
  if (inspectionOpenIssueCount.value) {
    rows.push({
      title: '优先处理待办和补正',
      description: `当前有 ${inspectionOpenIssueCount.value} 项未闭环，影响节点通过。`,
      tag: '人工确认',
      tone: 'red'
    })
  }
  if (inspectionLowConfidenceFieldCount.value) {
    rows.push({
      title: '复核低置信 OCR 字段',
      description: `${inspectionLowConfidenceFieldCount.value} 个字段置信度偏低，建议打开证据定位确认。`,
      tag: 'OCR',
      tone: 'orange'
    })
  }
  if (hasAction('ai:recheck')) {
    rows.push({
      title: '重新触发 AI 预审',
      description: '资料或补正更新后，可重新生成 AI 建议，正式结论仍由人工确认。',
      tag: 'AI',
      tone: 'blue'
    })
  }
  if (hasAction('review:save')) {
    rows.push({
      title: '保存人工审查意见',
      description: '确认 AI 建议、修正结论并沉淀为可追溯审查记录。',
      tag: '审查',
      tone: 'green'
    })
  }
  if (!rows.length) {
    rows.push({
      title: '继续巡检项目节点',
      description: '当前节点没有显著阻断，可按左侧项目树切换其他节点复核。',
      tag: '项目',
      tone: 'green'
    })
  }
  return rows.slice(0, 4)
})
const canShowWorkspace = computed(() => !pageIssue.value && !!activeProjectId.value)
const roleUserLabel = computed(() => {
  const labels: Record<RoleCode, string> = {
    inspection: '监检员 张工',
    contractor: '施工方 李工',
    ndt: '无损检测 王工',
    owner: '建设方 陈经理',
    admin: '系统管理员',
    fde: 'FDE 工程师'
  }
  return labels[role.value]
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
    ndt: '⌕ 全局搜索（项目 / 底片编号 / 焊口编号 / 检测报告 / 节点）',
    owner: '⌕ 全局搜索（项目 / 节点 / 资料状态 / 报告 / 归档资料）',
    admin: '⌕ 搜索（项目 / 单位 / 用户 / 角色 / 流程 / 待办 / 节点）',
    fde: '⌕ 搜索（AI Run / Agent / 评估集 / 发布单 / 业务类型）'
  }
  return placeholders[role.value]
})
const pageHeadline = computed(() => {
  const headlines: Record<RoleCode, string> = {
    inspection: 'AI 业务审查链路',
    contractor: '项目文件上传与挂载',
    ndt: '无损检测资料维护',
    owner: '建设方项目概况',
    admin: '管理工作台',
    fde: 'AI 交付治理后台'
  }
  return headlines[role.value]
})
const pageIntro = computed(() => {
  const intros: Record<RoleCode, string> = {
    inspection: '当前节点资料、AI 业务核验链路、人工审查意见和报告归档动作在同一工作区完成。',
    contractor: '施工方以文件上传和项目文件库为主，可选择一个或多个授权检测节点并提交挂载关系。',
    ndt: '底片编号、检测记录、检测报告和图像资料直接挂载到明确的无损检测节点。',
    owner: '只读查看项目进展、节点资料状态、异常提醒、报告状态和归档资料。',
    admin: '后台只维护配置、权限、流程和审计，不替代工作台业务办理。',
    fde: 'FDE 只管理 AI 能力、评估、发布和治理，不替代业务人员作出正式结论。'
  }
  return intros[role.value]
})
const currentNodeLabel = computed(() => {
  if (!selectedNode.value) return '未选择节点'
  return `${selectedNode.value.nodeId}. ${selectedNode.value.name}`
})
const workbenchAuditCards = computed<AuditSummaryCard[]>(() => [
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
])
const nodeBindingsPreview = computed(() => bindings.value.slice(0, 5))
const projectFilesPreview = computed(() => (nodePackage.value?.projectFiles || []).slice(0, 5))
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
const aiConfidence = computed(() => {
  const confidence = latestAiRun.value?.suggestion.confidence
  if (confidence === undefined) return '-'
  return `${confidence <= 1 ? Math.round(confidence * 100) : Math.round(confidence)}%`
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
      title: role.value === 'contractor' ? '挂载关系完整性' : '关键字段一致性',
      desc: fieldNames
        ? `已提取 ${fieldNames} 等字段，低置信度和需人工确认项保留在右侧证据链中。`
        : '当前节点暂未返回结构化字段，需等待 OCR 或人工补录后继续核验。',
      tags: extractedFields.value
        .slice(0, 2)
        .map((field) => `${field.fieldName} ${field.confidence}%`),
      result: extractedFields.value.some((field) => field.reviewStatus === '低置信度')
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
const getPillClass = (value?: string) => {
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

const showActionError = (fallback: string, error?: unknown) => {
  ElMessage.error(getAicheckErrorMessage(error, fallback))
}

const showUploadDrawerError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  uploadDrawerError.value = message
  ElMessage.error(message)
}

const showSubmissionDialogError = (fallback: string, error?: unknown) => {
  const message = getAicheckErrorMessage(error, fallback)
  submissionDialogError.value = message
  ElMessage.error(message)
}

let withdrawSuccessTimer: ReturnType<typeof setTimeout> | undefined

const showWithdrawSuccess = () => {
  const message = '提交项已撤回为草稿挂载，可在提交历史中追溯'
  withdrawSuccessMessage.value = message
  if (withdrawSuccessTimer) clearTimeout(withdrawSuccessTimer)
  withdrawSuccessTimer = setTimeout(() => {
    withdrawSuccessMessage.value = ''
  }, 20000)
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
  ndtSubmitError.value = message
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

const loadNodePackage = async (nodeId = activeNodeId.value) => {
  if (!activeProjectId.value) return
  nodeLoading.value = true
  nodeIssue.value = undefined
  try {
    const res = await getNodePackageApi(activeProjectId.value, nodeId)
    if (!res) {
      nodePackage.value = undefined
      standardReferences.value = []
      dateComparisons.value = []
      nodeIssue.value = {
        type: 'forbidden',
        title: '节点资料包加载失败',
        message: getAicheckErrorMessage(
          undefined,
          '接口返回失败，可能是权限不足、节点状态冲突或 mock 异常。'
        )
      }
      return
    }
    nodePackage.value = res.data
    activeNodeId.value = res.data.node.nodeId
    await loadInspectionDetails(res.data.node.nodeId)
  } catch (error) {
    nodePackage.value = undefined
    standardReferences.value = []
    dateComparisons.value = []
    nodeIssue.value = {
      type: 'error',
      title: '节点资料包加载失败',
      message: getErrorMessage(error)
    }
  } finally {
    nodeLoading.value = false
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
  const [reportRes, archiveRes] = await Promise.all([
    listOwnerReportsApi(activeProjectId.value),
    listProjectArchiveApi(activeProjectId.value)
  ])
  if (!reportRes || !archiveRes) {
    throw new Error('报告或归档资料加载失败。')
  }
  reports.value = reportRes.data
  archiveItems.value = archiveRes.data.items
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

const loadProjectBundle = async () => {
  if (!activeProjectId.value) return
  loading.value = true
  try {
    pageIssue.value = undefined
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
          '接口返回失败，可能是当前角色无权访问或 mock 正在模拟异常。'
        )
      }
      return
    }
    context.value = contextRes.data
    summary.value = summaryRes.data
    treeGroups.value = treeRes.data.groups
    activeNodeId.value = contextRes.data.currentNodeId
    activeWorkbenchSection.value = 'overview'
    if (role.value === 'ndt') {
      reports.value = []
      archiveItems.value = []
      await loadNdtData()
    } else {
      await loadReportArchive()
      await loadNdtData()
    }
    await loadNodePackage(activeNodeId.value)
    if (!pageIssue.value) {
      pageIssue.value = undefined
    }
  } catch (error) {
    pageIssue.value = {
      type: 'error',
      title: '工作台加载失败',
      message: getErrorMessage(error)
    }
  } finally {
    loading.value = false
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
          '接口返回失败，可能是当前角色无授权项目或 mock 正在模拟权限异常。'
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
    activeProjectId.value = res.data[0]?.id || ''
    await loadProjectBundle()
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

const handleProjectChange = async () => {
  submissionDrafts.value = []
  submissionSnapshots.value = []
  restoredSubmissionDraft.value = undefined
  activeWorkbenchSection.value = 'overview'
  await loadProjectBundle()
}

const handleNodeSelect = async (node: ProjectTreeNode) => {
  activeWorkbenchSection.value = 'node'
  activeNodeId.value = node.nodeId
  await loadNodePackage(node.nodeId)
}

const handleProjectOverviewSelect = () => {
  activeWorkbenchSection.value = 'overview'
}

const ensureWritableNode = () => {
  if (!activeProjectId.value || !selectedNode.value) {
    ElMessage.warning('请先选择项目和节点')
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
    meta: target?.meta
  }
  previewDrawerVisible.value = true
}

const handleOpenCurrentPreview = () => {
  openPreviewDrawer({
    source: 'node',
    title: previewFileName.value
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
    meta: fileDetail.value?.preview
      ? `${fileDetail.value.preview.contentType || fileDetail.value.document.fileType} · 有效期至 ${
          fileDetail.value.preview.expiresAt
        }`
      : url
  })
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
    expiresAt: 'mock 签名地址有效期内'
  }
  activeExportTaskId.value = task.id
  exportTaskError.value = ''
  exportTaskLoading.value = false
  exportTask.value = task
  rememberReadOnlyExportTask(task)
  exportTaskVisible.value = true
}

const handleOpenUploadDrawer = () => {
  if (!ensureWritableNode()) return
  uploadDrawerError.value = ''
  uploadDrawerVisible.value = true
}

const handleCreateUploadSession = async (
  files: Array<{ fileName: string; fileType: string; fileSize: number }>
) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  uploadDrawerError.value = ''
  try {
    const res = await createDocumentUploadSessionApi(activeProjectId.value, files, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showUploadDrawerError('上传会话创建失败，请检查文件类型、大小和当前节点权限。')
      return
    }
    uploadDrawerError.value = ''
    ElMessage.success(`上传会话已创建：${res.data.uploadSessionId}`)
    uploadDrawerVisible.value = false
    await loadNodePackage(activeNodeId.value)
  } catch (error) {
    showUploadDrawerError('上传会话创建失败，请检查文件类型、大小和当前节点权限。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleCreateNdtFilm = async (payload: {
  filmNo: string
  weldNo: string
  method: NdtFilm['method']
  pipelineNo?: string
  testDate?: string
}) => {
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

const handleUploadNdtReport = async (payload: {
  files: Array<{ fileName: string; fileType: string; fileSize: number }>
  relatedFilmIds: string[]
}) => {
  if (!activeProjectId.value) return
  if (!payload.files[0]?.fileName) {
    ElMessage.warning('请填写检测报告文件名')
    return
  }
  actionLoading.value = true
  ndtReportUploadError.value = ''
  try {
    const res = await createNdtReportUploadSessionApi(activeProjectId.value, payload, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showNdtReportUploadError('检测报告上传会话创建失败，请检查文件类型、大小和检测资料权限。')
      return
    }
    ndtReportUploadError.value = ''
    ElMessage.success(`检测报告上传会话已创建：${res.data.uploadSessionId}`)
    await Promise.all([loadNdtData(), loadNodePackage(activeNodeId.value)])
  } catch (error) {
    showNdtReportUploadError(
      '检测报告上传会话创建失败，请检查文件类型、大小和检测资料权限。',
      error
    )
  } finally {
    actionLoading.value = false
  }
}

const handleOpenBindDialog = () => {
  if (!ensureWritableNode()) return
  bindDialogError.value = ''
  bindDialogVisible.value = true
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
      payload.nodeIds.length > 1
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
    ElMessage.success('节点资料已提交，进入 AI 预审')
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

const handleWithdrawSubmission = async (payload: { bindingIds: string[]; reason: string }) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  submissionDialogError.value = ''
  try {
    const submissionId =
      latestSubmissionIds.value[activeNodeId.value] || `SUB-${activeNodeId.value}-CURRENT`
    const res = await withdrawSubmissionItemsApi(
      activeProjectId.value,
      submissionId,
      {
        bindingIds: payload.bindingIds,
        reason: payload.reason
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showSubmissionDialogError('提交项撤回失败，请检查资料是否已锁定或当前状态是否允许撤回。')
      return
    }
    showWithdrawSuccess()
    submissionDialogVisible.value = false
    submissionDialogError.value = ''
    await loadProjectBundle()
    await loadSubmissionHistory()
    submissionHistoryVisible.value = true
  } catch (error) {
    showSubmissionDialogError('提交项撤回失败，请检查资料是否已锁定或当前状态是否允许撤回。', error)
  } finally {
    actionLoading.value = false
  }
}

const handleOpenRectificationDialog = () => {
  if (!ensureWritableNode()) return
  rectificationDialogVisible.value = true
}

const handleSubmitNdt = async (payload: { reportIds: string[]; filmIds: string[] }) => {
  if (!ensureWritableNode()) return
  if (!payload.reportIds.length) {
    ElMessage.warning('请选择或上传至少一份检测报告')
    return
  }
  actionLoading.value = true
  ndtSubmitError.value = ''
  try {
    const res = await submitNdtSubmissionApi(
      activeProjectId.value,
      {
        nodeId: activeNodeId.value,
        reportIds: payload.reportIds,
        filmIds: payload.filmIds
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showNdtSubmitError('无损检测资料提交失败，请检查报告、底片和当前节点状态。')
      return
    }
    ndtSubmitError.value = ''
    ElMessage.success('无损检测资料已提交监检')
    await Promise.all([loadProjectBundle(), loadNdtData()])
  } catch (error) {
    showNdtSubmitError('无损检测资料提交失败，请检查报告、底片和当前节点状态。', error)
  } finally {
    actionLoading.value = false
  }
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

const handleSubmitRectification = async (payload: { comment: string; bindingIds: string[] }) => {
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
        comment: payload.comment
      },
      { etag: currentProject.value?.etag }
    )
    if (!res) {
      showActionError('补正反馈提交失败，请检查补正说明和资料选择。')
      return
    }
    ElMessage.success('补正反馈已提交')
    rectificationDialogVisible.value = false
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleAiRecheck = async () => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  try {
    const res = await requestAiRecheckApi(activeProjectId.value, activeNodeId.value, {
      etag: currentProject.value?.etag
    })
    if (!res) {
      showActionError('AI 复核触发失败，请检查是否已有任务运行或当前节点是否允许复核。')
      return
    }
    ElMessage.success('AI 复核已完成')
    await loadNodePackage(activeNodeId.value)
  } finally {
    actionLoading.value = false
  }
}

const handleSaveReviewOpinion = async () => {
  if (!ensureWritableNode()) return
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
        evidenceLinkIds: evidenceLinks.value.map((item) => item.id)
      },
      {
        etag: currentProject.value?.etag
      }
    )
    if (!res) {
      showActionError('审查意见保存失败，请检查审查意见和当前节点状态。')
      return
    }
    ElMessage.success('审查意见已保存')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

const handleAdoptAiSuggestion = async (suggestionId: string) => {
  if (!ensureWritableNode() || !latestAiRun.value) return
  actionLoading.value = true
  try {
    const aiResult = latestAiRun.value.suggestion.result
    const normalizedResult: ReviewOpinion['result'] =
      aiResult === '需补正' || aiResult === '不适用' ? aiResult : '满足要求'
    const res = await adoptAiSuggestionApi(
      activeProjectId.value,
      activeNodeId.value,
      suggestionId,
      {
        result: normalizedResult,
        opinion: latestAiRun.value.suggestion.opinionDraft,
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
    activeSideTab.value = 'opinion'
    ElMessage.success('AI 建议已采纳为审查草稿')
    await loadNodePackage(activeNodeId.value)
  } finally {
    actionLoading.value = false
  }
}

const handleRejectAiSuggestion = async (suggestionId: string) => {
  if (!ensureWritableNode()) return
  actionLoading.value = true
  try {
    const res = await rejectAiSuggestionApi(
      activeProjectId.value,
      activeNodeId.value,
      suggestionId,
      {
        reason: 'AI 建议与人工复核判断不一致。',
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

const handleReturnCorrection = async () => {
  if (!ensureWritableNode()) return
  if (!correctionReason.value.trim()) {
    ElMessage.warning('请填写退回补正原因')
    return
  }
  actionLoading.value = true
  try {
    const res = await returnCorrectionApi(
      activeProjectId.value,
      activeNodeId.value,
      {
        reason: correctionReason.value.trim(),
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

const handleDownloadArchivePackage = async () => {
  if (!activeProjectId.value) return
  actionLoading.value = true
  try {
    const res = await getArchivePackageApi(activeProjectId.value)
    if (!res) {
      showActionError('归档包生成失败，请检查项目归档状态和下载权限。')
      return
    }
    ElMessage.success(`归档包导出任务已创建（${res.data.itemCount} 项）`)
    await handleOpenExportTask(res.data.exportId)
  } finally {
    actionLoading.value = false
  }
}

const handleDownloadEvidencePackage = async () => {
  if (!activeProjectId.value) return
  actionLoading.value = true
  try {
    const res = await getEvidencePackageApi(activeProjectId.value, { nodeId: activeNodeId.value })
    if (!res) {
      showActionError('证据定位包生成失败，请检查节点证据和下载权限。')
      return
    }
    ElMessage.success(`证据包导出任务已创建（${res.data.itemCount} 项）`)
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
    ElMessage.success('报告已归档，项目进入只读状态')
    await loadProjectBundle()
  } finally {
    actionLoading.value = false
  }
}

watch(
  () => role.value,
  () => {
    loadProjects()
  }
)

watch(
  () => bindDialogVisible.value,
  (open) => {
    if (!open) bindDialogError.value = ''
  }
)

watch(
  () => uploadDrawerVisible.value,
  (open) => {
    if (!open) uploadDrawerError.value = ''
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

onMounted(() => {
  loadProjects()
})
</script>

<template>
  <div class="aicheck-static-viewport" v-loading="loading">
    <div
      v-if="withdrawSuccessMessage"
      class="el-message el-message--success withdraw-success-message"
      role="alert"
    >
      {{ withdrawSuccessMessage }}
    </div>
    <div class="aicheck-page app-shell">
      <header class="topbar">
        <div class="brand">
          <div class="hamburger">≡</div>
          <div class="brand-mark">盾</div>
          <ElSelect
            v-model="activeProjectId"
            class="project-select project-title-select"
            filterable
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
            待办<span v-if="todos.length" class="notice-dot">{{ todos.length }}</span>
          </ElButton>
          <ElButton class="top-action" text @click="handleOpenQuickAccess('messages')">
            消息<span v-if="unreadMessageCount" class="notice-dot">{{ unreadMessageCount }}</span>
          </ElButton>
          <ElButton class="top-action" text @click="handleOpenCurrentPreview"> 文件预览 </ElButton>
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

      <div v-else-if="canShowWorkspace" class="workspace">
        <aside :class="['left', { 'with-project-package': role === 'inspection' }]">
          <section class="tree-wrap">
            <div class="section-title">
              <span>项目审核节点</span>
              <span class="section-tools">{{ role === 'owner' ? '只读 ⓘ' : '↻ ⚙' }}</span>
            </div>
            <ProjectNodeTree
              :groups="treeGroups"
              :active-node-id="activeWorkbenchSection === 'overview' ? 0 : activeNodeId"
              @select="handleNodeSelect"
              @select-overview="handleProjectOverviewSelect"
            />
          </section>

          <section class="node-files">
            <div class="node-file-head">
              <span>
                {{
                  role === 'ndt' ? '检测资料包' : role === 'owner' ? '只读资料摘要' : '节点文件包'
                }}
                <small>{{ currentNodeLabel }}</small>
              </span>
              <span :class="['pill', getPillClass(selectedNode?.status)]">
                {{ selectedNode?.status || '-' }}
              </span>
            </div>
            <table class="table compact">
              <thead>
                <tr>
                  <th>{{ role === 'ndt' ? '资料/记录' : '文件名' }}</th>
                  <th>来源</th>
                  <th>版本</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="binding in nodeBindingsPreview" :key="binding.id">
                  <td>{{ binding.fileName }}</td>
                  <td>{{ binding.sourceOrgName }}</td>
                  <td>{{ binding.versionNo }}</td>
                  <td>
                    <span :class="['pill', getPillClass(binding.bindingStatus)]">
                      {{ binding.bindingStatus }}
                    </span>
                  </td>
                </tr>
                <tr v-if="!nodeBindingsPreview.length">
                  <td colspan="4">当前节点暂无文件</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section v-if="role === 'inspection'" class="project-files">
            <div class="node-file-head">
              <span>项目文件包 <small>项目级文件库</small></span>
              <span class="pill blue">{{ nodePackage?.projectFiles.length || 0 }}文件</span>
            </div>
            <table class="table compact">
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>来源</th>
                  <th>OCR</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in projectFilesPreview" :key="file.id">
                  <td>{{ file.fileName }}</td>
                  <td>{{ file.sourceOrgName }}</td>
                  <td>{{ file.currentOcrStatus }}</td>
                  <td>
                    <span :class="['pill', getPillClass(file.fileStatus)]">
                      {{ file.fileStatus }}
                    </span>
                  </td>
                </tr>
                <tr v-if="!projectFilesPreview.length">
                  <td colspan="4">项目文件包等待加载</td>
                </tr>
              </tbody>
            </table>
          </section>
        </aside>

        <main class="center">
          <WorkbenchStateBanner
            v-if="readonlyIssue"
            class="readonly-banner"
            :type="readonlyIssue.type"
            :title="readonlyIssue.title"
            :message="readonlyIssue.message"
          />

          <div class="page-head">
            <div>
              <div class="crumbs">
                当前位置：{{ currentRoleConfig.title }} / {{ currentNodeLabel }}
                <span :class="['pill', getPillClass(selectedNode?.inspectionType)]">
                  {{ selectedNode?.inspectionType || '-' }}类节点
                </span>
              </div>
              <h1 class="page-title">{{ currentRoleConfig.title }} · {{ pageHeadline }}</h1>
              <div class="sub">{{ pageIntro }}</div>
            </div>
            <div class="actions">
              <ElButton
                v-if="role === 'inspection' && hasAction('ai:recheck')"
                class="btn"
                :disabled="actionLoading || isReadOnly"
                @click="handleAiRecheck"
              >
                重新核验
              </ElButton>
              <ElButton
                v-if="role === 'contractor' && hasAction('file:upload')"
                class="btn primary"
                type="primary"
                :disabled="actionLoading || isReadOnly"
                @click="handleOpenUploadDrawer"
              >
                批量上传文件
              </ElButton>
              <ElButton
                v-if="role === 'ndt' && hasAction('ndt:submit')"
                class="btn primary"
                type="primary"
                :disabled="actionLoading || isReadOnly"
                @click="
                  handleSubmitNdt({
                    reportIds: ndtReports.map((item) => item.id),
                    filmIds: ndtFilms.map((item) => item.id)
                  })
                "
              >
                提交检测资料
              </ElButton>
              <ElButton
                v-if="role !== 'owner'"
                class="btn"
                :disabled="actionLoading || isReadOnly"
                @click="handleOpenBindDialog"
              >
                选择挂载节点
              </ElButton>
              <ElButton v-if="role === 'owner'" class="btn" @click="handleDownloadArchivePackage">
                导出状态摘要
              </ElButton>
            </div>
          </div>

          <AuditSummaryGrid :cards="workbenchAuditCards" aria-label="业务工作台审计摘要" />

          <section
            v-if="role === 'inspection' && activeWorkbenchSection === 'overview'"
            class="inspection-project-overview"
            aria-label="项目总览"
          >
            <div class="inspection-project-overview-head">
              <div>
                <span>项目总览</span>
                <strong>{{ currentProject?.name || '未选择项目' }}</strong>
                <small>先判断项目级卡点，再进入当前节点办理审查。</small>
              </div>
              <span :class="['pill', inspectionOpenIssueCount ? 'red' : 'green']">
                {{
                  inspectionOpenIssueCount ? `${inspectionOpenIssueCount} 项待处理` : '无待处理阻断'
                }}
              </span>
            </div>

            <div class="inspection-overview-card-grid">
              <article
                v-for="card in inspectionProjectOverviewCards"
                :key="card.label"
                :class="['inspection-overview-card', `inspection-overview-card--${card.tone}`]"
              >
                <span>{{ card.label }}</span>
                <strong>{{ card.value }}</strong>
                <small>{{ card.hint }}</small>
              </article>
            </div>

            <div class="inspection-overview-main-grid">
              <article class="inspection-overview-panel inspection-overview-panel--status">
                <div class="inspection-chart-head">
                  <div>
                    <strong>节点状态分布</strong>
                    <small>按项目树聚合节点状态，定位补正、预审和通过节点。</small>
                  </div>
                  <span class="pill blue">{{ projectTreeNodes.length }} 个节点</span>
                </div>
                <div class="inspection-node-status-bars" aria-label="项目节点状态分布图">
                  <article
                    v-for="row in inspectionNodeStatusBarRows"
                    :key="row.status"
                    :class="[
                      'inspection-node-status-row',
                      `inspection-node-status-row--${row.tone}`
                    ]"
                    :aria-label="`${row.status}：${row.count} 个节点，占比 ${row.percent}%`"
                  >
                    <span>{{ row.status }}</span>
                    <div class="inspection-node-status-track">
                      <i :style="{ width: `${row.barPercent}%` }"></i>
                    </div>
                    <strong>
                      {{ row.count }}
                      <small>{{ row.ratioText }}</small>
                    </strong>
                  </article>
                </div>
              </article>

              <article class="inspection-overview-panel">
                <div class="inspection-chart-head">
                  <div>
                    <strong>节点处理清单</strong>
                    <small>与左侧项目树一致，按节点查看资料、要求和审查进度。</small>
                  </div>
                  <span class="pill green">可下钻</span>
                </div>
                <div class="inspection-node-progress-list">
                  <button
                    v-for="row in inspectionProjectNodeRows"
                    :key="row.node.id"
                    type="button"
                    :class="[
                      'inspection-node-progress-item',
                      { active: row.node.nodeId === activeNodeId }
                    ]"
                    @click="handleNodeSelect(row.node)"
                  >
                    <span>{{ row.node.nodeId }}</span>
                    <strong>{{ row.node.name }}</strong>
                    <small>{{ row.evidence }}</small>
                    <em>{{ row.progress }}%</em>
                  </button>
                </div>
              </article>

              <article class="inspection-overview-panel">
                <div class="inspection-chart-head">
                  <div>
                    <strong>下一步建议</strong>
                    <small>只提示处理顺序，不替代监检员形成正式结论。</small>
                  </div>
                  <span class="pill orange">人工确认</span>
                </div>
                <div class="inspection-next-action-list">
                  <article
                    v-for="row in inspectionProjectNextActions"
                    :key="`${row.tag}-${row.title}`"
                    :class="[
                      'inspection-next-action-item',
                      `inspection-next-action-item--${row.tone}`
                    ]"
                  >
                    <span>{{ row.tag }}</span>
                    <strong>{{ row.title }}</strong>
                    <small>{{ row.description }}</small>
                  </article>
                </div>
              </article>
            </div>
          </section>

          <section
            v-if="role === 'inspection' && activeWorkbenchSection === 'node'"
            class="inspection-audit-visual"
            aria-label="审查态势图"
          >
            <article class="inspection-chart-panel inspection-chart-panel--wide">
              <div class="inspection-chart-head">
                <div>
                  <strong>任务与证据分布</strong>
                  <small>按当前项目节点聚合待办、补正、证据引用和已通过节点</small>
                </div>
                <span class="pill blue">当前节点</span>
              </div>
              <Echart
                :options="inspectionAuditBarOption"
                height="220px"
                class="inspection-audit-echart"
              />
              <div class="inspection-metric-strip">
                <span
                  v-for="item in inspectionAuditMetricItems"
                  :key="item.key"
                  :style="{ '--metric-color': item.color }"
                >
                  <b>{{ item.value }}</b>
                  {{ item.label }}
                </span>
              </div>
            </article>

            <article class="inspection-chart-panel">
              <div class="inspection-chart-head">
                <div>
                  <strong>人工处理闭环</strong>
                  <small>突出待办和补正压力，辅助监检员确定处理优先级</small>
                </div>
                <span :class="['pill', inspectionOpenIssueCount ? 'red' : 'green']">
                  {{ inspectionOpenIssueCount ? `${inspectionOpenIssueCount} 项待处理` : '无阻断' }}
                </span>
              </div>
              <Echart
                :options="inspectionClosurePieOption"
                height="220px"
                class="inspection-audit-echart"
              />
            </article>
          </section>

          <section v-else-if="role !== 'inspection'" class="card">
            <div class="card-body">
              <div class="metrics">
                <div v-for="metric in metrics.slice(0, 5)" :key="metric.key" class="metric">
                  <div class="metric-label">{{ metric.label }}</div>
                  <div :class="['metric-value', metric.tone || 'blue']">{{ metric.value }}</div>
                </div>
              </div>
            </div>
          </section>

          <WorkbenchRoleStaticSections
            v-if="role !== 'inspection'"
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

          <section v-if="role === 'inspection' && activeWorkbenchSection === 'node'" class="card">
            <div class="card-head">
              <h2>一、业务核验链路</h2>
              <div class="sub">每一步都关联过程文件和 EvidenceLink</div>
            </div>
            <div class="card-body">
              <div class="review-chain">
                <div
                  v-for="(step, index) in reviewChainSteps"
                  :key="step.title"
                  class="review-step"
                >
                  <div class="step-no">{{ index + 1 }}</div>
                  <div>
                    <div class="step-title">{{ step.title }}</div>
                    <div class="step-desc">{{ step.desc }}</div>
                    <div class="evidence-row">
                      <span v-for="tag in step.tags" :key="tag" class="pill blue">
                        {{ tag }}
                      </span>
                    </div>
                  </div>
                  <span :class="['pill', getPillClass(step.result)]">{{ step.result }}</span>
                </div>
              </div>
            </div>
          </section>

          <section
            v-if="role !== 'inspection' || activeWorkbenchSection === 'node'"
            class="card node-package-card"
          >
            <div class="card-head">
              <h2>
                {{
                  role === 'inspection'
                    ? '二、监检工作区'
                    : role === 'ndt'
                      ? '检测资料联动区'
                      : role === 'owner'
                        ? '只读节点资料联动区'
                        : '项目文件与挂载联动区'
                }}
              </h2>
              <div class="sub">保留原有 mock 写回、抽屉和错误恢复能力</div>
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

          <section
            v-if="role === 'inspection' && activeWorkbenchSection === 'node'"
            class="result-band"
          >
            <h2>三、AI 业务建议结果 <span class="sub">仅为建议，需监检人员确认</span></h2>
            <div class="result-grid">
              <div>
                建议结论
                <b>{{ latestAiRun?.suggestion.result || '-' }}</b>
              </div>
              <div>
                风险等级
                <b>{{ latestAiRun?.suggestion.result === '需补正' ? '中' : '低' }}</b>
              </div>
              <div>
                置信度
                <b class="blue">{{ aiConfidence }}</b>
              </div>
              <div>
                人工确认
                <b>{{ latestAiRun?.suggestion.manualConfirmItems.length || 0 }}项</b>
              </div>
            </div>
            <div class="ai-suggestion-editor">
              <div class="ai-suggestion-head">
                <strong>建议意见</strong>
                <span class="pill blue">可编辑草稿</span>
              </div>
              <textarea
                v-model="reviewOpinion"
                class="ai-suggestion-textarea"
                rows="4"
                aria-label="AI 建议意见"
              ></textarea>
            </div>
          </section>

          <WorkbenchRoleStaticSections
            v-if="role === 'inspection'"
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

          <NdtWorkflowPanel
            v-if="role === 'ndt'"
            :node="selectedNode"
            :films="ndtFilms"
            :records="ndtRecords"
            :reports="ndtReports"
            :feedback="ndtFeedback"
            :loading="actionLoading"
            :film-error="ndtFilmError"
            :record-import-error="ndtRecordImportError"
            :report-upload-error="ndtReportUploadError"
            :submit-error="ndtSubmitError"
            :rectify-error="ndtRectifyError"
            @create-film="handleCreateNdtFilm"
            @import-records="handleImportNdtRecords"
            @upload-report="handleUploadNdtReport"
            @submit-ndt="handleSubmitNdt"
            @rectify-ndt="handleRectifyNdt"
            @open-report-detail="handleOpenNdtReportDetail"
            @open-feedback-detail="handleOpenNdtFeedbackDetail"
          />

          <ReportArchivePanel
            v-if="role !== 'ndt'"
            :role="role"
            :actions="availableActions"
            :package-data="nodePackage"
            :reports="reports"
            :archive-items="archiveItems"
            :recent-export-tasks="recentReadOnlyExportTasks"
            :loading="actionLoading"
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

          <section class="center-support-grid">
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
                  @withdraw="handleOpenSubmissionDialog"
                  @history="handleOpenSubmissionHistory"
                  @rectify="handleOpenRectificationDialog"
                  @ai-recheck="handleAiRecheck"
                />
              </div>
            </section>

            <RoleContextPanel
              v-if="role !== 'ndt'"
              :role="role"
              :project="currentProject"
              :package-data="nodePackage"
              :todos="todos"
            />
            <ReviewDecisionPanel
              v-model:review-result="reviewResult"
              v-model:review-opinion="reviewOpinion"
              v-model:correction-reason="correctionReason"
              :role="role"
              :actions="availableActions"
              :latest-ai-run="latestAiRun"
              :evidence-count="evidenceLinks.length"
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
        </main>
      </div>

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
            <ElButton class="btn">放大</ElButton>
            <ElButton class="btn">缩小</ElButton>
            <ElButton class="btn" @click="activeSideTab = 'evidence'">定位证据</ElButton>
            <ElButton
              class="btn"
              :disabled="!firstBinding"
              @click="firstBinding && handleOpenFileDetail(firstBinding.documentId)"
            >
              详情
            </ElButton>
          </div>
          <div class="doc-preview">
            <div class="doc-toolbar">
              <span>{{ previewDrawerToolbarLabel }}</span>
              <span>⛶</span>
            </div>
            <div class="doc-canvas">
              <div class="doc-paper">
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
                      <td>{{ field.confidence }}%</td>
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
        :node-name="selectedNode?.name"
        :loading="actionLoading"
        :operation-error="uploadDrawerError"
        @submit="handleCreateUploadSession"
      />

      <DocumentBindDialog
        v-model="bindDialogVisible"
        :package-data="nodePackage"
        :tree-groups="treeGroups"
        :role="role"
        :loading="actionLoading"
        :operation-error="bindDialogError"
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
        @withdraw="handleWithdrawSubmission"
      />

      <EvidenceLocatorDialog
        v-model="evidenceDialogVisible"
        :evidence="activeEvidence"
        :extracted-fields="extractedFields"
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
        :issue="reportDetailError"
        @locate-evidence="handleLocateEvidence"
        @retry="handleRetryReportDetail"
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
        @read-message="handleReadQuickMessage"
        @read-all-messages="handleReadAllQuickMessages"
        @locate-result="handleLocateQuickResult"
      />
    </div>
  </div>
</template>

<style scoped>
.aicheck-static-viewport {
  --bg: #f4f7fb;
  --panel: #fff;
  --line: #d9e2ef;
  --line-soft: #e9eef6;
  --head: #f3f6fa;
  --ink: #172033;
  --muted: #6a7890;
  --blue: #1f66d8;
  --blue-2: #0c56c2;
  --blue-soft: #eaf3ff;
  --green: #14a36b;
  --green-soft: #eaf8f1;
  --orange: #ff8a00;
  --orange-soft: #fff4e3;
  --red: #ff4d3d;
  --red-soft: #fff0ee;
  --shadow: 0 1px 2px rgb(20 34 56 / 4%);

  width: 100%;
  height: 100vh;
  max-width: 100vw;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei',
    'Noto Sans CJK SC', Arial, sans-serif;
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
  display: grid;
  min-width: 0;
  min-height: 68px;
  padding: 0 20px;
  background: #fff;
  border-bottom: 1px solid var(--line);
  grid-template-columns: minmax(280px, 404px) minmax(260px, 1fr) minmax(260px, 520px);
  gap: 18px;
  align-items: center;
}

.brand {
  display: grid;
  grid-template-columns: 24px 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.hamburger {
  font-size: 22px;
  line-height: 1;
  color: #304158;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  font-weight: 800;
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
  font-weight: 800;
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
  color: #8b98aa;
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
  font-size: 15px;
  color: #27364d;
  white-space: nowrap;
  flex-wrap: wrap;
  gap: 18px;
  row-gap: 6px;
  align-items: center;
  justify-content: flex-end;
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
.top-actions .top-action.el-button:focus-visible {
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
  font-weight: 800;
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
  font-weight: 700;
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
}

.left,
.center {
  min-height: 0;
}

.left {
  display: grid;
  height: 100%;
  overflow: hidden auto;
  background: #fff;
  border-right: 1px solid var(--line);
  grid-template-rows: minmax(560px, 1fr) 394px;
}

.left.with-project-package {
  grid-template-rows: minmax(430px, 1fr) 286px 300px;
}

.tree-wrap,
.node-files,
.project-files {
  min-height: 0;
  overflow: hidden auto;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 18px;
  font-size: 18px;
  font-weight: 800;
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
  min-height: 34px;
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
  font-weight: 800;
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
  font-weight: 800;
  color: inherit;
  background: transparent;
}

.tree-wrap :deep(.node-name) {
  display: block;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.35;
  color: inherit;
  white-space: normal;
  overflow-wrap: anywhere;
}

.tree-wrap :deep(.node-meta) {
  font-size: 12px;
  color: var(--muted);
}

.node-files {
  background: #fff;
  border-top: 1px solid var(--line);
}

.project-files {
  background: #fbfdff;
  border-top: 1px solid var(--line);
}

.node-file-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 18px;
  font-weight: 800;
}

.node-file-head small {
  font-weight: 700;
  color: var(--muted);
}

.center {
  height: 100%;
  min-width: 0;
  padding: 18px 20px 24px;
  overflow: hidden auto;
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
  font-weight: 700;
  color: var(--muted);
}

.page-title,
h1 {
  margin: 0;
  font-size: 27px;
  font-weight: 900;
  line-height: 1.2;
}

h2 {
  margin: 0;
  font-size: 21px;
  line-height: 1.2;
}

h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.2;
}

.sub {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
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
  min-height: 38px;
  padding: 0 17px;
  margin: 0;
  font-weight: 800;
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
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 6px;
  box-shadow: var(--shadow);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.card:hover,
.card:focus-within {
  border-color: #c4d5ee;
  box-shadow: 0 2px 8px rgb(20 34 56 / 8%);
}

.card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 13px 16px;
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
  background: #fbfdff;
  border: 1px solid var(--line);
  border-radius: 6px;
}

.metric-label {
  font-size: 13px;
  font-weight: 800;
  color: var(--muted);
}

.metric-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 900;
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
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgb(20 34 56 / 4%);
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
  font-weight: 900;
  color: #2563eb;
}

.inspection-project-overview-head strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 900;
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
  font-weight: 900;
  color: #667085;
}

.inspection-overview-card strong {
  margin-top: 8px;
  font-size: 20px;
  font-weight: 900;
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
  grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
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
}

.inspection-overview-panel--status {
  grid-column: 1 / -1;
  min-height: auto;
}

.inspection-overview-panel--status .inspection-audit-echart {
  display: block;
  width: 100% !important;
  min-width: 0;
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
  font-weight: 900;
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
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 55%);
  content: '';
}

.inspection-node-status-row strong {
  display: inline-flex;
  gap: 6px;
  align-items: baseline;
  font-size: 16px;
  font-weight: 900;
  line-height: 22px;
  color: #172033;
  text-align: left;
  font-variant-numeric: tabular-nums;
}

.inspection-node-status-row strong small {
  font-size: 11px;
  font-weight: 800;
  line-height: 16px;
  color: #7b8798;
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

.inspection-node-progress-list,
.inspection-next-action-list {
  display: grid;
  gap: 8px;
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
  font-weight: 900;
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
  font-weight: 900;
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
  font-weight: 900;
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

.inspection-audit-visual {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.95fr);
  gap: 12px;
  margin-bottom: 16px;
}

.inspection-chart-panel {
  min-height: 304px;
  padding: 14px 16px 12px;
  overflow: hidden;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 1px solid #dbe6f5;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgb(20 34 56 / 4%);
}

.inspection-chart-panel--wide {
  min-width: 0;
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
  font-weight: 900;
  color: #172033;
}

.inspection-chart-head small {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #667085;
}

.inspection-audit-echart {
  width: 100%;
}

.inspection-metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 6px;
}

.inspection-metric-strip span {
  min-width: 0;
  padding: 8px 10px;
  overflow: hidden;
  font-size: 12px;
  font-weight: 800;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #fff;
  border: 1px solid #e6edf7;
  border-radius: 6px;
}

.inspection-metric-strip span::before {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 7px;
  vertical-align: 1px;
  background: var(--metric-color, #2563eb);
  border-radius: 999px;
  content: '';
}

.inspection-metric-strip b {
  margin-right: 4px;
  font-size: 15px;
  color: #172033;
  font-variant-numeric: tabular-nums;
}

.pill {
  display: inline-flex;
  min-height: 24px;
  padding: 3px 8px;
  font-size: 13px;
  font-weight: 800;
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
  font-weight: 900;
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

.review-step {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 12px;
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.step-no {
  display: grid;
  width: 28px;
  height: 28px;
  font-weight: 900;
  color: #fff;
  background: var(--blue);
  border-radius: 50%;
  place-items: center;
}

.step-title {
  font-weight: 900;
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

.result-band {
  padding: 16px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid #bcd4ff;
  border-radius: 6px;
  box-shadow: var(--shadow);
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.result-grid div {
  min-height: 62px;
  padding: 12px;
  font-weight: 800;
  color: var(--muted);
  background: #fbfdff;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}

.result-grid b {
  display: block;
  margin-top: 8px;
  font-size: 20px;
  color: var(--ink);
}

.result-grid b.blue {
  color: var(--blue);
}

.ai-suggestion-editor {
  margin-top: 12px;
}

.ai-suggestion-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.ai-suggestion-textarea {
  width: 100%;
  min-height: 92px;
  padding: 9px 10px;
  font-weight: 700;
  line-height: 1.55;
  color: var(--ink);
  background: #fff;
  border: 1px solid #cbd8ea;
  border-radius: 5px;
  resize: vertical;
}

.preview-name {
  font-weight: 800;
  color: #26364e;
}

.preview-source {
  margin-top: 6px;
  overflow: hidden;
  font-size: 13px;
  font-weight: 700;
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
  font-weight: 900;
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
  font-weight: 800;
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
  font-weight: 900;
  text-align: center;
}

.mini-doc-table {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
  table-layout: fixed;
}

.mini-doc-table td:nth-child(odd) {
  font-weight: 900;
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
  font-weight: 800;
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
  font-weight: 800;
  border-radius: 5px;
}

.withdraw-success-message {
  position: fixed;
  top: 22px;
  left: 50%;
  z-index: 5000;
  display: flex;
  max-width: min(620px, calc(100vw - 32px));
  min-width: 320px;
  pointer-events: none;
  transform: translateX(-50%);
  justify-content: center;
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

  .inspection-audit-visual {
    grid-template-columns: minmax(0, 1fr);
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

  .workspace {
    height: auto;
    overflow: visible;
  }

  .topbar {
    gap: 10px;
    min-height: 68px;
    padding: 10px 12px;
  }

  .brand {
    grid-template-columns: 24px 34px minmax(0, 1fr);
  }

  .top-status {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .left,
  .center {
    min-height: auto;
  }

  .left,
  .left.with-project-package {
    grid-template-rows: auto auto auto;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .tree-wrap :deep(.tree-panel) {
    max-height: 520px;
  }

  .center {
    height: auto;
    padding: 14px 12px 18px;
  }

  .center-support-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-audit-board,
  .metrics,
  .result-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .inspection-metric-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 560px) {
  .workbench-audit-board,
  .metrics,
  .result-grid {
    grid-template-columns: 1fr;
  }

  .inspection-chart-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .inspection-node-status-row {
    grid-template-columns: minmax(76px, 92px) minmax(120px, 1fr) minmax(62px, auto);
    gap: 8px;
  }

  .inspection-node-status-row span {
    font-size: 13px;
    text-align: left;
  }

  .inspection-metric-strip {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
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
}
</style>
