<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
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
  ElMessage,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElProgress,
  ElRow,
  ElSelect,
  ElSpace,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTreeSelect
} from 'element-plus'
import {
  batchReindexKnowledgeApi,
  cancelKnowledgeTaskApi,
  createKnowledgeRuleVersionApi,
  createKnowledgeSourceApi,
  deleteKnowledgeFileApi,
  disableKnowledgeSourceApi,
  enableKnowledgeSourceApi,
  forkKnowledgeRuleVersionApi,
  getBusinessPackApi,
  getKnowledgeConfigApi,
  getKnowledgeFileDetailApi,
  getKnowledgeFileVectorApi,
  getKnowledgeRuleVersionDiffApi,
  getLlmCompareRunApi,
  getReasoningLogDetailApi,
  importBusinessRulesApi,
  importKnowledgeFilesApi,
  importRulesStandardsApi,
  listKnowledgeAuditLogsApi,
  listKnowledgeFileChunksApi,
  listKnowledgeFileReasoningReferencesApi,
  listKnowledgePageIndexNodesApi,
  listKnowledgeProjectFilesApi,
  listKnowledgeRuleVersionsApi,
  listKnowledgeSourcesApi,
  listKnowledgeTasksApi,
  listLlmCompareRunsApi,
  listWorkbenchProjectsApi,
  listReasoningLogsApi,
  publishKnowledgeRuleVersionApi,
  reindexKnowledgeFileApi,
  replaceKnowledgeFileVersionApi,
  retryKnowledgeTaskApi,
  rollbackKnowledgeRuleVersionApi,
  runKnowledgeRetrievalTestApi,
  runLlmCompareApi,
  updateKnowledgeRuleVersionApi,
  updateKnowledgeConfigApi,
  updateKnowledgeFileApi,
  updateKnowledgeSourceApi
} from '@/api/aicheck'
import type {
  BusinessPackDetail,
  KnowledgeAuditLog,
  KnowledgeChunk,
  KnowledgeConfig,
  KnowledgeFile,
  KnowledgeFileDetailPayload,
  KnowledgeFileSavePayload,
  KnowledgeOverviewPayload,
  KnowledgePageIndexNode,
  KnowledgeReasoningReference,
  KnowledgeRetrievalTestPayload,
  KnowledgeRuleVersion,
  KnowledgeRuleVersionDiffPayload,
  KnowledgeRuleVersionSavePayload,
  KnowledgeSource,
  KnowledgeSourceSavePayload,
  KnowledgeTask,
  LlmComparePayload,
  LlmCompareRunSummary,
  ReasoningLogDetailPayload
} from '@/api/aicheck'
import { getKnowledgeOverviewApi } from '@/api/aicheck'
import type { AiReviewRun, Project } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import AdminKnowledgeStaticDeepSections from './components/AdminKnowledgeStaticDeepSections.vue'
import AuditSummaryGrid, { type AuditSummaryCard } from './components/AuditSummaryGrid.vue'
import StaticPageShell from './components/StaticPageShell.vue'
import WorkbenchStateBanner from './components/WorkbenchStateBanner.vue'

const emptyOverview = (): KnowledgeOverviewPayload => ({
  metrics: [],
  libraries: []
})

const emptyKnowledgeConfig = (): KnowledgeConfig => ({
  embeddingModel: 'text-embedding-3-large',
  chunkSize: 900,
  chunkOverlap: 120,
  topKDefault: 5,
  rerankEnabled: true,
  evidenceStrictMode: true,
  autoReindex: true,
  retentionDays: 180,
  updatedBy: '',
  updatedAt: ''
})

const emptySourceForm = (): KnowledgeSourceSavePayload => ({
  name: '',
  sourceType: 'standard',
  version: '',
  status: '待复核',
  fileCount: 0,
  chunkCount: 0,
  vectorStatus: '待向量化'
})

const emptyStandardFileForm = (): Required<KnowledgeFileSavePayload> => ({
  fileName: '',
  sourceRelativePath: '',
  contextDescription: '',
  projectId: '',
  projectName: ''
})

const emptyRuleForm = (): KnowledgeRuleVersionSavePayload => ({
  sequence: undefined,
  sourceSequence: undefined,
  sourceRuleId: '',
  sourceDocument: '',
  businessModule: '',
  inspectionCategory: '',
  inspectionItem: '',
  inspectionClass: 'C',
  standardText: '',
  witnessText: '',
  sourceWitness: '',
  agentThinking: '',
  toolchainThinking: '',
  referencedStandards: [],
  materialTypeCodes: [],
  thinkingModeIds: [],
  toolIds: [],
  aiExecution: undefined,
  nodeIds: []
})

const DEFAULT_RULE_BUSINESS_PACK_ID = 'engineering_inspection_v1'
const DEFAULT_STANDARD_SOURCE_ID = 'KS-STANDARD-RULES'
const DEFAULT_STANDARD_SOURCE_NAME = '标准规范库（业务规则引用标准）'
const DEFAULT_STANDARD_SOURCE_VERSION = 'rules-standards-20260703'
const DEFAULT_PROJECT_FILE_SOURCE_ID = 'KS-PROJECT-FILE'
const DEFAULT_PROJECT_FILE_SOURCE_NAME = '项目文件知识库'
const DEFAULT_PROJECT_FILE_SOURCE_VERSION = 'proj-v2026.06.26'

type RuleNodeSelectOption = {
  value: string
  label: string
  disabled?: boolean
  nodeId?: number
  inspectionCategory?: string
  inspectionItem?: string
  children?: RuleNodeSelectOption[]
}

const ruleNodeTreeProps = {
  label: 'label',
  value: 'value',
  children: 'children',
  disabled: 'disabled'
}

const route = useRoute()
const router = useRouter()

const knowledgeShellMenuSectionsBase = [
  {
    title: '知识库管理',
    meta: '10页',
    items: [
      {
        index: '01',
        label: '知识库总览',
        badge: '运行',
        tone: 'blue',
        route: '/knowledge/overview'
      },
      {
        index: '02',
        label: '标准规范库',
        badge: '标准',
        tone: 'green',
        route: '/knowledge/sources'
      },
      {
        index: '03',
        label: '项目文件知识库',
        badge: '项目',
        tone: 'blue',
        route: '/knowledge/files'
      },
      {
        index: '04',
        label: 'OCR/向量任务中心',
        badge: '失败',
        tone: 'orange',
        route: '/knowledge/tasks'
      },
      {
        index: '05',
        label: '监检业务判断规则管理',
        badge: '规则',
        tone: 'blue',
        route: '/knowledge/rules'
      },
      {
        index: '06',
        label: '知识检索测试',
        badge: '测试',
        tone: 'blue',
        route: '/knowledge/retrieval'
      },
      {
        index: '07',
        label: '推理链路历史日志',
        badge: '日志',
        tone: 'green',
        route: '/knowledge/reasoning'
      },
      {
        index: '08',
        label: '多 LLM 反馈对比',
        badge: '评估',
        tone: 'green',
        route: '/knowledge/compare'
      },
      { index: '09', label: '知识库配置', badge: '策略', tone: 'blue', route: '/knowledge/config' },
      {
        index: '10',
        label: '操作审计日志',
        badge: '审计',
        tone: 'blue',
        route: '/knowledge/config'
      }
    ]
  }
] as const

const knowledgePeerNavItems = computed(
  () =>
    [
      {
        index: 'admin-peer-10',
        label: '业务类型管理',
        badge: '复用',
        tone: 'green',
        route: '/admin/business-packs'
      },
      {
        index: 'admin-peer-11',
        label: '审核节点维护',
        hint: '项目审核节点',
        badge: '69项',
        tone: 'blue',
        route: '/admin/permission'
      },
      {
        index: 'admin-peer-12',
        label: '节点角色矩阵',
        hint: '动作级权限',
        badge: '权限',
        tone: 'blue',
        route: '/admin/permission'
      },
      {
        index: 'admin-peer-13',
        label: 'AI 业务规则模板',
        badge: '规则',
        tone: 'orange',
        route: '/admin/rules'
      },
      {
        index: 'admin-peer-14',
        label: 'AI 知识库管理',
        badge: '当前',
        tone: 'green',
        route: '/knowledge/overview',
        active: route.path.startsWith('/knowledge')
      },
      {
        index: 'admin-peer-15',
        label: '外部核验工具源',
        badge: '工具',
        tone: 'blue',
        route: '/admin/fine-config'
      },
      {
        index: 'admin-peer-16',
        label: '证据字段映射',
        badge: '字段',
        tone: 'blue',
        route: '/admin/fine-config'
      },
      {
        index: 'admin-peer-17',
        label: '角色单位人员',
        badge: '基础',
        tone: 'green',
        route: '/admin/org'
      },
      {
        index: 'admin-peer-18',
        label: '联调清单',
        badge: '对账',
        tone: 'orange',
        route: '/admin/integration'
      },
      {
        index: 'admin-peer-19',
        label: '操作日志',
        badge: '审计',
        tone: 'blue',
        route: '/admin/audit'
      }
    ] as const
)

const knowledgeShellBoundaryRows = [
  { label: '不办理', value: '退回补正、审查意见、报告复核' },
  { label: '可管理', value: '知识源、OCR、向量、规则版本、推理日志' },
  { label: '权限', value: '继承项目、单位、角色授权' },
  { label: '审计', value: '所有重跑、发布、回滚均留痕' }
] as const

const knowledgeShellRightCards = [
  {
    title: '处理进度',
    rows: [
      { label: 'OCR', progress: 91, progressTone: 'green' },
      { label: '切片', progress: 88, progressTone: 'green' },
      { label: '向量', progress: 84, progressTone: 'orange' },
      { label: '推理日志', valueBadge: '248 次', valueTone: 'blue' }
    ]
  },
  {
    title: '最近失败任务',
    rows: [
      { label: 'OCR', value: '材料复验报告.pdf 页面旋转异常' },
      { label: '向量', value: 'RT 检测报告切片为空' },
      { label: '索引', value: 'TSG Z6002 索引版本过期' }
    ]
  },
  {
    title: '当前规则快照',
    rows: [
      { label: '规则', value: 'Welder-Qualification-B v2.1' },
      { label: 'Prompt', value: 'prompt-v1.5' },
      { label: '字段映射', value: 'map-v1.3' },
      { label: '工具源', value: 'tool-v2.0' }
    ]
  },
  {
    title: '多模型评估摘要',
    rows: [
      { label: '一致结论', value: '2 / 3 模型判断满足要求' },
      { label: '分歧点', value: '外部查询截图时效性' },
      { label: '建议', value: '加入截图日期核验规则' }
    ]
  },
  {
    title: '后台限制',
    note: '本页面仅管理知识源、规则版本、任务状态和推理日志，不提供采纳 AI 建议、退回补正、保存审查意见或报告复核按钮。'
  }
] as const

type PaginationState = {
  page: number
  pageSize: number
  total: number
}

type SectionKey =
  | 'sources'
  | 'standardFiles'
  | 'files'
  | 'tasks'
  | 'rules'
  | 'config'
  | 'audit'
  | 'reasoning'
  | 'compare'

type SectionIssue = {
  title: string
  message?: string
}

type OperationIssueKey =
  | 'source'
  | 'rule'
  | 'ruleDiff'
  | 'config'
  | 'reindex'
  | 'import'
  | 'file'
  | 'task'
  | 'pageIndex'
  | 'retrieval'
  | 'compare'
  | 'fileDetail'
  | 'reasoningDetail'

type KnowledgeTopStatKey = 'sources' | 'vectorTasks' | 'failedTasks'

type KnowledgeTopStat = {
  key: KnowledgeTopStatKey
  label: string
  value: number
  tone: 'blue' | 'green' | 'red'
  clickable: true
  title: string
}

const createPagination = (pageSize = 10): PaginationState => ({
  page: 1,
  pageSize,
  total: 0
})

const loading = ref(false)
const actionLoading = ref('')

const knowledgeTabRouteMap = {
  overview: '/knowledge/overview',
  'source-manage': '/knowledge/sources',
  files: '/knowledge/files',
  tasks: '/knowledge/tasks',
  rules: '/knowledge/rules',
  retrieval: '/knowledge/retrieval',
  reasoning: '/knowledge/reasoning',
  compare: '/knowledge/compare',
  config: '/knowledge/config'
} as const

type KnowledgeTabKey = keyof typeof knowledgeTabRouteMap

const knowledgeRouteTabMap: Record<string, KnowledgeTabKey> = {
  '/knowledge/overview': 'overview',
  '/knowledge/sources': 'source-manage',
  '/knowledge/files': 'files',
  '/knowledge/tasks': 'tasks',
  '/knowledge/rules': 'rules',
  '/knowledge/retrieval': 'retrieval',
  '/knowledge/reasoning': 'reasoning',
  '/knowledge/compare': 'compare',
  '/knowledge/config': 'config'
}

const getKnowledgeTabFromRoute = (path: string): KnowledgeTabKey =>
  knowledgeRouteTabMap[path] || 'overview'

const activeTab = ref<KnowledgeTabKey>(getKnowledgeTabFromRoute(route.path))

function loadKnowledgeTabData(tab: KnowledgeTabKey) {
  if (tab === 'source-manage') return Promise.all([loadSources(), loadStandardFiles()])
  if (tab === 'files') return loadFiles()
  if (tab === 'tasks') return loadTasks()
  if (tab === 'rules') return loadRuleVersions()
  if (tab === 'config') return Promise.all([loadKnowledgeConfig(), loadKnowledgeAuditLogs()])
  if (tab === 'reasoning') return loadReasoningLogs()
  if (tab === 'compare') return loadCompareRuns()
  if (tab === 'retrieval') return loadPageIndexNodes()
  return loadOverview()
}

const pageIssue = ref<{
  type: 'error' | 'forbidden' | 'readonly' | 'empty'
  title: string
  message?: string
}>()
const overview = ref<KnowledgeOverviewPayload>(emptyOverview())
const projects = ref<Project[]>([])
const sources = ref<KnowledgeSource[]>([])
const files = ref<KnowledgeFile[]>([])
const standardFiles = ref<KnowledgeFile[]>([])
const tasks = ref<KnowledgeTask[]>([])
const reasoningLogs = ref<AiReviewRun[]>([])
const compareRuns = ref<LlmCompareRunSummary[]>([])
const ruleVersions = ref<KnowledgeRuleVersion[]>([])
const auditLogs = ref<KnowledgeAuditLog[]>([])
const knowledgeConfig = reactive<KnowledgeConfig>(emptyKnowledgeConfig())
const sectionIssues = reactive<Record<SectionKey, SectionIssue | undefined>>({
  sources: undefined,
  standardFiles: undefined,
  files: undefined,
  tasks: undefined,
  rules: undefined,
  config: undefined,
  audit: undefined,
  reasoning: undefined,
  compare: undefined
})
const operationIssues = reactive<Record<OperationIssueKey, SectionIssue | undefined>>({
  source: undefined,
  rule: undefined,
  ruleDiff: undefined,
  config: undefined,
  reindex: undefined,
  import: undefined,
  file: undefined,
  task: undefined,
  pageIndex: undefined,
  retrieval: undefined,
  compare: undefined,
  fileDetail: undefined,
  reasoningDetail: undefined
})

const fileDrawerVisible = ref(false)
const fileDetailLoading = ref(false)
const fileDetail = ref<KnowledgeFileDetailPayload | null>(null)
const fileChunks = ref<KnowledgeChunk[]>([])
const fileReferences = ref<KnowledgeReasoningReference[]>([])

const knowledgeShellMenuSections = computed(() => {
  let activeMatched = false
  return knowledgeShellMenuSectionsBase.map((section) => ({
    ...section,
    items: section.items.map((item) => {
      const active = !activeMatched && item.route === route.path
      if (active) activeMatched = true
      return { ...item, active }
    })
  }))
})

const scrollKnowledgeContentIntoView = () => {
  nextTick(() => {
    document
      .querySelector('.knowledge-tabs')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const handleKnowledgeMenuSelect = () => {
  scrollKnowledgeContentIntoView()
}

watch(
  () => route.path,
  (path, oldPath) => {
    if (!path.startsWith('/knowledge')) return
    const nextTab = getKnowledgeTabFromRoute(path)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
    if (oldPath) {
      scrollKnowledgeContentIntoView()
      void loadKnowledgeTabData(nextTab)
    }
  },
  { immediate: true }
)

watch(activeTab, (tab) => {
  if (!route.path.startsWith('/knowledge')) return
  if (knowledgeRouteTabMap[route.path] === tab) return
  const targetPath = knowledgeTabRouteMap[tab]
  if (targetPath && route.path !== targetPath) {
    router.push(targetPath)
  }
})

const reasoningDrawerVisible = ref(false)
const reasoningDetailLoading = ref(false)
const reasoningDetail = ref<ReasoningLogDetailPayload | null>(null)

const retrievalLoading = ref(false)
const retrievalResult = ref<KnowledgeRetrievalTestPayload | null>(null)
const pageIndexLoading = ref(false)
const pageIndexNodes = ref<KnowledgePageIndexNode[]>([])
const retrievalTrace = computed(() => retrievalResult.value?.retrievalTrace || null)
const retrievalPageIndexTree = computed(() => retrievalTrace.value?.pageIndexTree || null)
const retrievalPageIndexNodes = computed(() => retrievalPageIndexTree.value?.selectedNodes || [])
const retrievalTreePathRows = computed(() => retrievalPageIndexTree.value?.treeSearchPath || [])
const compareLoading = ref(false)
const compareResult = ref<LlmComparePayload | null>(null)
const compareDisplayResults = computed(() => {
  if (!compareResult.value) return []
  if (compareResult.value.results.length) return compareResult.value.results
  return (compareResult.value.modelCodes || []).map((modelCode) => ({
    modelCode,
    answer:
      compareResult.value?.status === '失败'
        ? '模型对比失败，请查看任务错误并重试。'
        : '模型对比任务已创建，等待 worker 回写结果。',
    confidence: undefined,
    evidenceLinkIds: [] as string[],
    latencyMs: 0
  }))
})
const ruleDiffVisible = ref(false)
const ruleDiffLoading = ref(false)
const ruleDiff = ref<KnowledgeRuleVersionDiffPayload | null>(null)
const selectedRuleDiffVersion = ref<KnowledgeRuleVersion | null>(null)
const ruleEditorVisible = ref(false)
const ruleEditorMode = ref<'create' | 'edit'>('create')
const ruleEditingId = ref('')
const ruleEditingSource = ref<KnowledgeRuleVersion | null>(null)
const ruleForm = reactive<KnowledgeRuleVersionSavePayload>(emptyRuleForm())
const ruleBusinessPack = ref<BusinessPackDetail | null>(null)
const ruleNodeTreeLoading = ref(false)
const ruleNodeSelectValue = ref('')
const ruleNodeSelectOptions = computed<RuleNodeSelectOption[]>(() => {
  const groups: RuleNodeSelectOption[] = []
  const groupMap = new Map<string, RuleNodeSelectOption>()
  for (const template of ruleBusinessPack.value?.nodeTemplates || []) {
    const nodeId = Number(template.nodeId)
    if (!Number.isFinite(nodeId)) continue
    const groupName = template.groupName || '未分组'
    let group = groupMap.get(groupName)
    if (!group) {
      group = {
        value: `group:${groupName}`,
        label: groupName,
        disabled: true,
        children: []
      }
      groupMap.set(groupName, group)
      groups.push(group)
    }
    group.children?.push({
      value: String(nodeId),
      label: `${nodeId}. ${template.name}`,
      nodeId,
      inspectionCategory: groupName,
      inspectionItem: template.name
    })
  }
  return groups
})
const ruleNodeOptionMap = computed(() => {
  const options = new Map<string, RuleNodeSelectOption>()
  const collect = (items: RuleNodeSelectOption[]) => {
    for (const item of items) {
      if (item.nodeId) {
        options.set(item.value, item)
      }
      if (item.children?.length) collect(item.children)
    }
  }
  collect(ruleNodeSelectOptions.value)
  return options
})

const sourceDialogVisible = ref(false)
const sourceDialogMode = ref<'create' | 'edit'>('create')
const sourceDialogContext = ref<'source' | 'standard-file' | 'project-file'>('source')
const sourceEditingId = ref('')
const sourceForm = reactive<KnowledgeSourceSavePayload>(emptySourceForm())
type SourceUploadFileRow = {
  id: string
  file: File
  fileName: string
  relativePath: string
  contextDescription: string
  size: number
  type: string
}
const sourceUploadFileInputRef = ref<HTMLInputElement>()
const sourceUploadDirectoryInputRef = ref<HTMLInputElement>()
const sourceUploadFiles = ref<SourceUploadFileRow[]>([])
const sourceUploadProjectId = ref('')
const standardFileDialogVisible = ref(false)
const standardFileDialogMode = ref<'edit' | 'replace'>('edit')
const standardFileEditing = ref<KnowledgeFile | null>(null)
const standardFileForm = reactive<Required<KnowledgeFileSavePayload>>(emptyStandardFileForm())
const standardFileReplaceInputRef = ref<HTMLInputElement>()
const standardFileReplacement = ref<File | null>(null)
const knowledgeImportVisible = ref(false)
const knowledgeImportFileInputRef = ref<HTMLInputElement>()
const knowledgeImportDirectoryInputRef = ref<HTMLInputElement>()
const knowledgeImportFiles = ref<File[]>([])
const knowledgeImportDialogTitle = ref('从文件导入业务规则草稿')
const businessRuleImportVersion = ref('')

const sourceFilters = reactive({
  keyword: '',
  sourceType: 'standard',
  status: ''
})

const sourcePagination = reactive(createPagination(6))

const standardFileFilters = reactive({
  keyword: '',
  status: ''
})

const standardFilePagination = reactive(createPagination(10))

const fileFilters = reactive({
  keyword: '',
  projectId: '',
  nodeId: undefined as number | undefined,
  status: ''
})

const filePagination = reactive(createPagination(10))

const taskFilters = reactive({
  taskType: '',
  status: ''
})

const taskPagination = reactive(createPagination(10))
const knowledgeTopTaskCounts = reactive({
  vectorTotal: 0,
  failedTotal: 0,
  vectorLoaded: false,
  failedLoaded: false
})

const reasoningFilters = reactive({
  nodeId: undefined as number | undefined,
  status: ''
})

const reasoningPagination = reactive(createPagination(10))

const ruleFilters = reactive({
  keyword: '',
  status: ''
})

const rulePagination = reactive(createPagination(10))

const auditFilters = reactive({
  keyword: '',
  objectType: '',
  result: ''
})

const auditPagination = reactive(createPagination(10))

const retrievalForm = reactive({
  question: '焊工资格证与持证项目是否覆盖本项目焊接方法？',
  scope: ['standard', 'project-file'],
  topK: 5
})

const compareForm = reactive({
  question: '材料质量证明书中的炉批号和标准条款是否一致？',
  modelCodes: ['LLM-A', 'LLM-B'],
  nodeId: 24
})

const libraries = computed(() => overview.value.libraries)
const metrics = computed(() => overview.value.metrics)
const parseMetricNumber = (value: string | number | undefined) => {
  if (typeof value === 'number') return value
  if (!value) return undefined
  const parsed = Number.parseInt(value, 10)
  return Number.isNaN(parsed) ? undefined : parsed
}
const getOverviewMetricNumber = (key: string) =>
  parseMetricNumber(metrics.value.find((metric) => metric.key === key)?.value)
const knowledgeTopStats = computed<KnowledgeTopStat[]>(() => [
  {
    key: 'sources',
    label: '知识源',
    value: getOverviewMetricNumber('source') ?? (sourcePagination.total || sources.value.length),
    tone: 'blue',
    clickable: true,
    title: '查看知识源和标准规范列表'
  },
  {
    key: 'vectorTasks',
    label: '向量任务',
    value: knowledgeTopTaskCounts.vectorLoaded
      ? knowledgeTopTaskCounts.vectorTotal
      : tasks.value.filter((task) => task.taskType === 'vector').length,
    tone: 'green',
    clickable: true,
    title: '查看向量任务'
  },
  {
    key: 'failedTasks',
    label: '失败任务',
    value: knowledgeTopTaskCounts.failedLoaded
      ? knowledgeTopTaskCounts.failedTotal
      : (getOverviewMetricNumber('failed') ??
        tasks.value.filter((task) => task.status === '失败').length),
    tone: 'red',
    clickable: true,
    title: '查看失败任务'
  }
])
const projectFileProjectOptions = computed(() => {
  const optionMap = new Map<string, { id: string; name: string; code?: string }>()
  projects.value.forEach((project) => {
    optionMap.set(project.id, { id: project.id, name: project.name, code: project.code })
  })
  files.value.forEach((file) => {
    if (file.projectId && !optionMap.has(file.projectId)) {
      optionMap.set(file.projectId, {
        id: file.projectId,
        name: file.projectName || file.projectId
      })
    }
  })
  return Array.from(optionMap.values())
})
const selectedSourceUploadProject = computed(() =>
  projects.value.find((project) => project.id === sourceUploadProjectId.value)
)
const selectedKnowledgeFileProjectName = computed(() => {
  const project = projectFileProjectOptions.value.find(
    (item) => item.id === standardFileForm.projectId
  )
  return project?.name || standardFileForm.projectName || ''
})
const isProjectKnowledgeFile = (row?: KnowledgeFile | null) =>
  Boolean(row?.projectId) || row?.sourceId === DEFAULT_PROJECT_FILE_SOURCE_ID
const currentKnowledgeFileKind = computed(() =>
  isProjectKnowledgeFile(standardFileEditing.value) ? '项目文件' : '标准规范'
)
const knowledgeFileDialogTitle = computed(
  () =>
    `${standardFileDialogMode.value === 'edit' ? '编辑' : '替换'}${currentKnowledgeFileKind.value}${
      standardFileDialogMode.value === 'replace' ? '版本' : ''
    }`
)
const knowledgeImportFileRows = computed(() =>
  knowledgeImportFiles.value.map((file) => ({
    id: `${file.name}-${file.size}-${file.lastModified}`,
    name: file.name,
    relativePath: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
    size: file.size,
    type: file.type || file.name.split('.').pop() || '-'
  }))
)
const knowledgeScorecard = computed(() => overview.value.scorecard || null)
const knowledgeScorecardSections = computed(() => knowledgeScorecard.value?.sections || [])
const knowledgeScorecardBlockerRows = computed(() =>
  (knowledgeScorecard.value?.blockers || []).slice(0, 8).map((blocker, index) => ({
    id: index + 1,
    blocker
  }))
)
const knowledgeRetrievalProbeRows = computed(() => knowledgeScorecard.value?.retrievalProbes || [])
const canShowKnowledgeContent = computed(() => !pageIssue.value)
const knowledgeAuditCards = computed<AuditSummaryCard[]>(() => [
  {
    label: '知识源入库',
    value: `${sources.value.length} 个来源`,
    hint: `${files.value.length} 份资料进入 OCR/切片链路`,
    tone: 'blue'
  },
  {
    label: '向量化状态',
    value: `${files.value.filter((file) => file.vectorStatus === '已向量化').length} 份完成`,
    hint: `${tasks.value.filter((task) => task.taskType === 'vector').length} 个向量任务可追踪`,
    tone: 'green'
  },
  {
    label: '章节溯源',
    value: `${pageIndexNodes.value.length} 个节点`,
    hint: '用于长文档章节树、命中路径和条款定位',
    tone: 'orange'
  },
  {
    label: '引用质量',
    value: `${knowledgeScorecard.value?.blockers.length || 0} 个阻断`,
    hint: `${reasoningLogs.value.length} 条推理日志可回放评估`,
    tone: 'red'
  }
])
const hasSectionIssue = computed(() => Object.values(sectionIssues).some(Boolean))
const ruleDiffSummaryItems = computed<
  Array<{
    label: string
    value: number
  }>
>(() => {
  if (!ruleDiff.value) return []
  return [
    { label: '新增', value: ruleDiff.value.summary.added },
    { label: '变更', value: ruleDiff.value.summary.changed },
    { label: '移除', value: ruleDiff.value.summary.removed },
    { label: '需关注', value: ruleDiff.value.summary.warning }
  ]
})

const modelOptions = ['LLM-A', 'LLM-B', 'LLM-C']
const sourceStatusOptions: KnowledgeSource['status'][] = ['启用', '停用', '过期', '待复核']
const vectorStatusOptions: KnowledgeSource['vectorStatus'][] = [
  '未向量化',
  '待向量化',
  '向量化中',
  '已向量化',
  '向量化失败'
]
const ruleStatusOptions: KnowledgeRuleVersion['status'][] = ['草稿', '待发布', '已发布', '已回滚']
const ruleClassOptions = ['A', 'B', 'C', 'C/B']
const auditObjectTypeOptions = [
  'KnowledgeSource',
  'KnowledgeTask',
  'KnowledgeConfig',
  'RuleVersion',
  'LlmCompareRun'
]

const statusType = (status?: string) => {
  if (!status) return 'info'
  if (
    ['健康', '完成', '成功', '启用', '已向量化', '已切片', '已识别', '已人工确认'].some((key) =>
      status.includes(key)
    )
  ) {
    return 'success'
  }
  if (['失败', '需补正', '停用'].some((key) => status.includes(key))) return 'danger'
  if (
    [
      '索引',
      '运行',
      '排队',
      '待复核',
      '待识别',
      '待向量化',
      '未识别',
      '未切片',
      '未向量化',
      '人工修正',
      '识别中',
      '向量化中'
    ].some((key) => status.includes(key))
  ) {
    return 'warning'
  }
  return 'info'
}

const taskTypeLabel = (type: KnowledgeTask['taskType']) => {
  const map: Record<KnowledgeTask['taskType'], string> = {
    ocr: 'OCR',
    slice: '切片',
    vector: '向量',
    reindex: '重建索引'
  }
  return map[type]
}

const sourceTypeLabel = (type: KnowledgeSource['sourceType']) => {
  const map: Record<KnowledgeSource['sourceType'], string> = {
    standard: '标准规范',
    'project-file': '项目文件',
    rule: '业务规则（旧）',
    manual: '人工维护'
  }
  return map[type]
}

const vectorPercent = (row: KnowledgeOverviewPayload['libraries'][number]) => {
  if (!row.chunkCount) return 0
  return Math.min(100, Math.round((row.vectorCount / row.chunkCount) * 100))
}

const confidencePercent = (value?: number) => {
  if (typeof value !== 'number') return '--'
  return `${Math.round(value * 100)}%`
}

const formatPageRange = (row: { startPage?: number; endPage?: number }) => {
  if (!row.startPage && !row.endPage) return '--'
  if (row.startPage && row.endPage) return `${row.startPage}-${row.endPage}`
  return String(row.startPage || row.endPage)
}

const formatTextList = (items?: string[]) => {
  if (!items?.length) return '--'
  return items.join(' / ')
}

const formatRuleReferencedStandards = (standards?: KnowledgeRuleVersion['referencedStandards']) => {
  if (!standards?.length) return '--'
  return standards
    .map((item) => item.fileName || item.file || item.reference)
    .filter(Boolean)
    .join(' / ')
}

const formatRuleExecution = (execution?: KnowledgeRuleVersion['aiExecution']) => {
  if (!execution) return '保存或发布时生成'
  return JSON.stringify(execution, null, 2)
}

const formatAuditValue = (value: unknown, fallback = '-') => {
  if (value === undefined || value === null || value === '') return fallback
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

const fieldText = (record: Record<string, unknown> | undefined, field: string, fallback = '-') =>
  formatAuditValue(record?.[field], fallback)

const reasoningPromptAudit = computed<Record<string, unknown>>(() => {
  const detail = reasoningDetail.value
  return ((detail?.promptAudit || detail?.log.promptAudit || {}) as Record<string, unknown>) || {}
})

const reasoningLlmMetadata = computed<Record<string, unknown>>(() => {
  const detail = reasoningDetail.value
  return ((detail?.llmMetadata || detail?.log.llmMetadata || {}) as Record<string, unknown>) || {}
})

const reasoningTraceSteps = computed<Array<Record<string, unknown>>>(() => {
  return reasoningDetail.value?.traceSteps || []
})

const reasoningPromptText = (field: string) => fieldText(reasoningPromptAudit.value, field, '暂无')

const reasoningMetadataText = (field: string) => fieldText(reasoningLlmMetadata.value, field, '-')

const reasoningPromptTemplateLabel = computed(() => {
  const name = fieldText(reasoningPromptAudit.value, 'promptTemplateName', '')
  const id = fieldText(reasoningPromptAudit.value, 'promptTemplateId', '')
  return [name, id].filter(Boolean).join(' / ') || '-'
})

const reasoningProcessText = computed(() => {
  const fromMetadata = reasoningLlmMetadata.value.reasoningProcess
  return formatAuditValue(
    fromMetadata || reasoningDetail.value?.log.reasoningProcess,
    '暂无推理过程记录'
  )
})

const reasoningResultText = computed(() => {
  const fromMetadata = reasoningLlmMetadata.value.resultText
  return formatAuditValue(
    fromMetadata || reasoningDetail.value?.log.llmResultText,
    '暂无推理结果记录'
  )
})

const formatFileSize = (size: number) => {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

const standardFilePath = (row: KnowledgeFile) =>
  row.sourceRelativePath || row.originalFileName || row.fileName

const allowedKnowledgeImportExtensions = new Set([
  'pdf',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'png',
  'jpg',
  'jpeg',
  'md',
  'txt'
])
const allowedBusinessRuleImportExtensions = new Set([
  'docx',
  'md',
  'markdown',
  'txt',
  'yaml',
  'yml',
  'json'
])

const isAllowedKnowledgeImportFile = (file: File) => {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return allowedKnowledgeImportExtensions.has(extension)
}

const isAllowedBusinessRuleImportFile = (file: File) => {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  return allowedBusinessRuleImportExtensions.has(extension)
}

const createClientKnowledgeSourceId = () => {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `KS-UPLOAD-${random
    .replace(/[^a-zA-Z0-9]/g, '')
    .slice(0, 12)
    .toUpperCase()}`
}

const routeLabel = (route?: string) => {
  const map: Record<string, string> = {
    exact_clause_lookup: '精确条款',
    hybrid_rag: 'Hybrid RAG',
    pageindex_tree_search: 'PageIndex 树检索',
    project_requirement_lookup: '项目特殊要求'
  }
  return route ? map[route] || route : '--'
}

const getErrorMessage = (error: unknown) => {
  return getAicheckErrorMessage(error, '知识库接口返回异常，请检查网络、权限或 mock 状态。')
}

const assertApiResponse = <T,>(response: { data?: T } | undefined, message: string) => {
  if (!response) throw new Error(message)
  return response
}

const setSectionIssue = (key: SectionKey, title: string, error: unknown) => {
  sectionIssues[key] = {
    title,
    message: getErrorMessage(error)
  }
}

const clearSectionIssue = (key: SectionKey) => {
  sectionIssues[key] = undefined
}

const buildOperationFailureMessage = (action: string) =>
  `${action}失败，当前输入和页面数据已保留，请稍后重试或刷新后再操作。`

const setOperationIssue = (key: OperationIssueKey, title: string, error?: unknown) => {
  operationIssues[key] = {
    title,
    message: getErrorMessage(error)
  }
}

const clearOperationIssue = (key: OperationIssueKey) => {
  operationIssues[key] = undefined
}

const loadSection = async (key: SectionKey, title: string, loader: () => Promise<void>) => {
  try {
    await loader()
    clearSectionIssue(key)
  } catch (error) {
    setSectionIssue(key, title, error)
  }
}

const formatDiffValue = (value: unknown) => {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-'
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const diffChangeTypeLabel = (type: 'added' | 'changed' | 'removed') => {
  const map = {
    added: '新增',
    changed: '变更',
    removed: '移除'
  }
  return map[type]
}

const diffChangeTagType = (
  type: 'added' | 'changed' | 'removed'
): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  const map: Record<
    'added' | 'changed' | 'removed',
    'primary' | 'success' | 'warning' | 'danger' | 'info'
  > = {
    added: 'success',
    changed: 'primary',
    removed: 'danger'
  }
  return map[type]
}

const applyPagination = <T,>(
  pagination: PaginationState,
  payload?: { items: T[]; page: number; pageSize: number; total: number }
) => {
  pagination.page = payload?.page || pagination.page
  pagination.pageSize = payload?.pageSize || pagination.pageSize
  pagination.total = payload?.total || 0
  return payload?.items || []
}

const handleFilterChange = async (pagination: PaginationState, loader: () => Promise<void>) => {
  pagination.page = 1
  await loader()
}

const handlePageChange = async (
  pagination: PaginationState,
  loader: () => Promise<void>,
  page: number
) => {
  pagination.page = page
  await loader()
}

const handlePageSizeChange = async (
  pagination: PaginationState,
  loader: () => Promise<void>,
  pageSize: number
) => {
  pagination.page = 1
  pagination.pageSize = pageSize
  await loader()
}

const readKnowledgeTaskTotal = (response?: Awaited<ReturnType<typeof listKnowledgeTasksApi>>) =>
  response?.data?.total || 0

const loadOverview = async () => {
  const res = assertApiResponse(await getKnowledgeOverviewApi(), '知识库总览接口未返回有效数据。')
  overview.value = res.data || emptyOverview()
}

const loadProjectOptions = async () => {
  try {
    const res = assertApiResponse(
      await listWorkbenchProjectsApi('admin'),
      '项目列表接口未返回有效数据。'
    )
    projects.value = res.data || []
  } catch {
    projects.value = []
  }
}

const loadSources = async () => {
  await loadSection('sources', '知识源加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeSourcesApi({
        keyword: sourceFilters.keyword || undefined,
        sourceType: sourceFilters.sourceType as KnowledgeSource['sourceType'] | undefined,
        status: sourceFilters.status as KnowledgeSource['status'] | undefined,
        page: sourcePagination.page,
        pageSize: sourcePagination.pageSize
      }),
      '知识源接口未返回有效数据。'
    )
    sources.value = applyPagination(sourcePagination, res.data)
  })
}

const loadStandardFiles = async () => {
  await loadSection('standardFiles', '标准规范文件加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeProjectFilesApi({
        keyword: standardFileFilters.keyword || undefined,
        status: standardFileFilters.status || undefined,
        sourceType: 'standard',
        page: standardFilePagination.page,
        pageSize: standardFilePagination.pageSize
      }),
      '标准规范文件接口未返回有效数据。'
    )
    standardFiles.value = applyPagination(standardFilePagination, res.data)
  })
}

const loadFiles = async () => {
  await loadSection('files', '项目文件加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeProjectFilesApi({
        keyword: fileFilters.keyword || undefined,
        projectId: fileFilters.projectId || undefined,
        nodeId: fileFilters.nodeId,
        status: fileFilters.status || undefined,
        page: filePagination.page,
        pageSize: filePagination.pageSize
      }),
      '项目文件接口未返回有效数据。'
    )
    files.value = applyPagination(filePagination, res.data)
  })
}

const loadTasks = async () => {
  await loadSection('tasks', '任务中心加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeTasksApi({
        taskType: taskFilters.taskType as KnowledgeTask['taskType'] | undefined,
        status: taskFilters.status as KnowledgeTask['status'] | undefined,
        page: taskPagination.page,
        pageSize: taskPagination.pageSize
      }),
      '任务中心接口未返回有效数据。'
    )
    tasks.value = applyPagination(taskPagination, res.data)
  })
}

const loadKnowledgeTopTaskCounts = async () => {
  const [vectorResult, failedResult] = await Promise.allSettled([
    listKnowledgeTasksApi({ taskType: 'vector', page: 1, pageSize: 1 }),
    listKnowledgeTasksApi({ status: '失败', page: 1, pageSize: 1 })
  ])

  if (vectorResult.status === 'fulfilled') {
    knowledgeTopTaskCounts.vectorTotal = readKnowledgeTaskTotal(vectorResult.value)
    knowledgeTopTaskCounts.vectorLoaded = true
  } else {
    knowledgeTopTaskCounts.vectorLoaded = false
  }

  if (failedResult.status === 'fulfilled') {
    knowledgeTopTaskCounts.failedTotal = readKnowledgeTaskTotal(failedResult.value)
    knowledgeTopTaskCounts.failedLoaded = true
  } else {
    knowledgeTopTaskCounts.failedLoaded = false
  }
}

const loadRuleVersions = async () => {
  await loadSection('rules', '规则版本加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeRuleVersionsApi({
        keyword: ruleFilters.keyword || undefined,
        status: ruleFilters.status as KnowledgeRuleVersion['status'] | undefined,
        page: rulePagination.page,
        pageSize: rulePagination.pageSize
      }),
      '规则版本接口未返回有效数据。'
    )
    ruleVersions.value = applyPagination(rulePagination, res.data)
  })
}

const loadKnowledgeConfig = async () => {
  await loadSection('config', '知识库配置加载失败', async () => {
    const res = assertApiResponse(await getKnowledgeConfigApi(), '知识库配置接口未返回有效数据。')
    if (res.data?.config) {
      Object.assign(knowledgeConfig, res.data.config)
    }
  })
}

const loadKnowledgeAuditLogs = async () => {
  await loadSection('audit', '知识库审计加载失败', async () => {
    const res = assertApiResponse(
      await listKnowledgeAuditLogsApi({
        keyword: auditFilters.keyword || undefined,
        objectType: auditFilters.objectType || undefined,
        result: auditFilters.result || undefined,
        page: auditPagination.page,
        pageSize: auditPagination.pageSize
      }),
      '知识库审计接口未返回有效数据。'
    )
    auditLogs.value = applyPagination(auditPagination, res.data)
  })
}

const loadReasoningLogs = async () => {
  await loadSection('reasoning', '推理日志加载失败', async () => {
    const res = assertApiResponse(
      await listReasoningLogsApi({
        nodeId: reasoningFilters.nodeId,
        status: reasoningFilters.status as AiReviewRun['status'] | undefined,
        page: reasoningPagination.page,
        pageSize: reasoningPagination.pageSize
      }),
      '推理日志接口未返回有效数据。'
    )
    reasoningLogs.value = applyPagination(reasoningPagination, res.data)
  })
}

const loadCompareRuns = async () => {
  await loadSection('compare', '多模型历史加载失败', async () => {
    const res = assertApiResponse(
      await listLlmCompareRunsApi({ pageSize: 20 }),
      '多模型历史接口未返回有效数据。'
    )
    compareRuns.value = res.data?.items || []
  })
}

const loadPageIndexNodes = async (keyword = '') => {
  pageIndexLoading.value = true
  clearOperationIssue('pageIndex')
  try {
    const res = assertApiResponse(
      await listKnowledgePageIndexNodesApi({
        keyword: keyword || undefined,
        pageSize: 20
      }),
      'PageIndex 节点接口未返回有效数据。'
    )
    pageIndexNodes.value = res.data?.items || []
  } catch (error) {
    setOperationIssue('pageIndex', buildOperationFailureMessage('PageIndex 节点加载'), error)
  } finally {
    pageIndexLoading.value = false
  }
}

const loadData = async () => {
  loading.value = true
  pageIssue.value = undefined
  try {
    await Promise.all([
      loadOverview(),
      loadProjectOptions(),
      loadSources(),
      loadStandardFiles(),
      loadFiles(),
      loadTasks(),
      loadKnowledgeTopTaskCounts(),
      loadRuleVersions(),
      loadKnowledgeConfig(),
      loadKnowledgeAuditLogs(),
      loadReasoningLogs(),
      loadCompareRuns(),
      loadPageIndexNodes()
    ])
    if (
      !overview.value.metrics.length &&
      !overview.value.libraries.length &&
      !sources.value.length &&
      !files.value.length &&
      !tasks.value.length &&
      !hasSectionIssue.value
    ) {
      pageIssue.value = {
        type: 'empty',
        title: '暂无知识库数据',
        message: '当前环境没有返回标准规范、项目文件或任务数据，可重新加载或先上传标准规范。'
      }
    }
  } catch (error) {
    pageIssue.value = {
      type: 'error',
      title: '知识库数据加载失败',
      message: getErrorMessage(error)
    }
    ElMessage.error('知识库数据加载失败')
  } finally {
    loading.value = false
  }
}

const handleRetryLoad = () => {
  loadData()
}

const navigateKnowledgeTab = async (tab: KnowledgeTabKey) => {
  const targetPath = knowledgeTabRouteMap[tab]
  if (route.path === targetPath) {
    activeTab.value = tab
    await loadKnowledgeTabData(tab)
    scrollKnowledgeContentIntoView()
    return
  }
  await router.push(targetPath)
}

const handleKnowledgeTopStatClick = async (stat: KnowledgeTopStat) => {
  if (stat.key === 'sources') {
    sourceFilters.keyword = ''
    sourceFilters.sourceType = ''
    sourceFilters.status = ''
    standardFileFilters.keyword = ''
    standardFileFilters.status = ''
    sourcePagination.page = 1
    standardFilePagination.page = 1
    await navigateKnowledgeTab('source-manage')
    return
  }

  if (stat.key === 'vectorTasks') {
    taskFilters.taskType = 'vector'
    taskFilters.status = ''
    taskPagination.page = 1
    await navigateKnowledgeTab('tasks')
    return
  }

  if (stat.key === 'failedTasks') {
    taskFilters.taskType = ''
    taskFilters.status = '失败'
    taskPagination.page = 1
    await navigateKnowledgeTab('tasks')
  }
}

const refreshKnowledgeState = async () => {
  await Promise.all([
    loadOverview(),
    loadProjectOptions(),
    loadSources(),
    loadStandardFiles(),
    loadFiles(),
    loadTasks(),
    loadKnowledgeTopTaskCounts(),
    loadKnowledgeAuditLogs()
  ])
}

const openKnowledgeImportDialog = () => {
  clearOperationIssue('import')
  knowledgeImportDialogTitle.value = '从文件导入业务规则草稿'
  const now = new Date()
  const date = now.toISOString().slice(0, 10).replace(/-/g, '')
  const time = `${now.getHours()}`.padStart(2, '0') + `${now.getMinutes()}`.padStart(2, '0')
  businessRuleImportVersion.value = `rule-draft-${date}-${time}`
  knowledgeImportFiles.value = []
  knowledgeImportVisible.value = true
}

const triggerKnowledgeImportFileSelect = () => {
  knowledgeImportFileInputRef.value?.click()
}

const triggerKnowledgeImportDirectorySelect = () => {
  knowledgeImportDirectoryInputRef.value?.click()
}

const addKnowledgeImportFiles = (fileList: FileList | null) => {
  if (!fileList?.length) return
  const nextFiles = [...knowledgeImportFiles.value]
  const existing = new Set(
    nextFiles.map((file) => {
      const relativePath =
        (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
      return `${relativePath}-${file.size}-${file.lastModified}`
    })
  )
  let skippedUnsupported = 0
  Array.from(fileList).forEach((file) => {
    const relativePath =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    const key = `${relativePath}-${file.size}-${file.lastModified}`
    if (!isAllowedBusinessRuleImportFile(file)) {
      skippedUnsupported += 1
      return
    }
    if (!existing.has(key)) {
      existing.add(key)
      nextFiles.push(file)
    }
  })
  knowledgeImportFiles.value = nextFiles
  if (skippedUnsupported) {
    ElMessage.warning(`已跳过 ${skippedUnsupported} 个不支持的文件`)
  }
}

const handleKnowledgeImportInputChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  addKnowledgeImportFiles(input.files)
  input.value = ''
}

const removeKnowledgeImportFile = (rowId: string) => {
  knowledgeImportFiles.value = knowledgeImportFiles.value.filter((file) => {
    const relativePath =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    return `${relativePath}-${file.size}-${file.lastModified}` !== rowId
  })
}

const clearKnowledgeImportFiles = () => {
  knowledgeImportFiles.value = []
}

const handleImportKnowledgeFiles = async () => {
  if (!knowledgeImportFiles.value.length) {
    ElMessage.warning('请选择业务规则文件')
    return
  }
  actionLoading.value = 'knowledge-import'
  clearOperationIssue('import')
  try {
    const res = await importBusinessRulesApi({
      files: knowledgeImportFiles.value,
      importVersion: businessRuleImportVersion.value.trim()
    })
    if (!res) {
      setOperationIssue('import', buildOperationFailureMessage('业务规则导入'))
      return
    }
    const importedCount = res.data?.importedRules?.length || res.data?.rules?.length || 0
    const skippedCount = res.data?.skipped?.length || 0
    ElMessage.success(
      `已导入 ${importedCount} 条业务规则草稿${skippedCount ? `，跳过 ${skippedCount} 个文件` : ''}`
    )
    knowledgeImportVisible.value = false
    knowledgeImportFiles.value = []
    await Promise.all([loadRuleVersions(), loadKnowledgeAuditLogs()])
  } catch (error) {
    setOperationIssue('import', buildOperationFailureMessage('业务规则导入'), error)
  } finally {
    actionLoading.value = ''
  }
}

const syncSourceUploadFileCount = () => {
  if (sourceDialogMode.value === 'create') {
    sourceForm.fileCount = sourceUploadFiles.value.length
    if (sourceUploadFiles.value.length) {
      sourceForm.vectorStatus = '待向量化'
    }
  }
}

const triggerSourceUploadFileSelect = () => {
  sourceUploadFileInputRef.value?.click()
}

const triggerSourceUploadDirectorySelect = () => {
  sourceUploadDirectoryInputRef.value?.click()
}

const addSourceUploadFiles = (fileList: FileList | null) => {
  if (!fileList?.length) return
  const nextRows = [...sourceUploadFiles.value]
  const existing = new Set(
    nextRows.map((row) => `${row.relativePath}-${row.size}-${row.file.lastModified}`)
  )
  let skippedUnsupported = 0
  Array.from(fileList).forEach((file) => {
    const relativePath =
      (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    const key = `${relativePath}-${file.size}-${file.lastModified}`
    if (!isAllowedKnowledgeImportFile(file)) {
      skippedUnsupported += 1
      return
    }
    if (existing.has(key)) return
    existing.add(key)
    nextRows.push({
      id: `${key}-${nextRows.length}`,
      file,
      fileName: file.name,
      relativePath,
      contextDescription: '',
      size: file.size,
      type: file.type || file.name.split('.').pop() || '-'
    })
  })
  sourceUploadFiles.value = nextRows
  syncSourceUploadFileCount()
  if (skippedUnsupported) {
    ElMessage.warning(`已跳过 ${skippedUnsupported} 个不支持的文件`)
  }
}

const handleSourceUploadInputChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  addSourceUploadFiles(input.files)
  input.value = ''
}

const removeSourceUploadFile = (rowId: string) => {
  sourceUploadFiles.value = sourceUploadFiles.value.filter((row) => row.id !== rowId)
  syncSourceUploadFileCount()
}

const clearSourceUploadFiles = () => {
  sourceUploadFiles.value = []
  syncSourceUploadFileCount()
}

const getDefaultProjectFileUploadProjectId = () =>
  fileFilters.projectId || projects.value[0]?.id || ''

const openCreateSourceDialog = (
  context: 'source' | 'standard-file' | 'project-file' = 'source'
) => {
  clearOperationIssue('source')
  sourceDialogContext.value = context
  sourceDialogMode.value = 'create'
  sourceEditingId.value = ''
  const isProjectFileUpload = context === 'project-file'
  Object.assign(sourceForm, {
    ...emptySourceForm(),
    name: isProjectFileUpload ? DEFAULT_PROJECT_FILE_SOURCE_NAME : DEFAULT_STANDARD_SOURCE_NAME,
    sourceType: isProjectFileUpload ? 'project-file' : 'standard',
    version: isProjectFileUpload
      ? DEFAULT_PROJECT_FILE_SOURCE_VERSION
      : DEFAULT_STANDARD_SOURCE_VERSION,
    status: '启用',
    vectorStatus: '待向量化'
  })
  sourceUploadProjectId.value = isProjectFileUpload ? getDefaultProjectFileUploadProjectId() : ''
  sourceUploadFiles.value = []
  sourceDialogVisible.value = true
}

const handleImportRulesStandards = async () => {
  actionLoading.value = 'rules-standards-import'
  clearOperationIssue('source')
  try {
    const res = await importRulesStandardsApi({
      sourceId: DEFAULT_STANDARD_SOURCE_ID,
      sourceName: DEFAULT_STANDARD_SOURCE_NAME,
      sourceVersion: DEFAULT_STANDARD_SOURCE_VERSION,
      sourceStatus: '启用',
      reset: true
    })
    if (!res) {
      setOperationIssue('source', buildOperationFailureMessage('标准规范上传'))
      return
    }
    const importedCount = res.data?.files?.length || res.data?.summary?.imported || 0
    const skippedCount = res.data?.skipped?.length || res.data?.summary?.skipped || 0
    const removedCount = res.data?.summary?.removed || 0
    ElMessage.success(
      `标准规范库已重新初始化，移除 ${removedCount} 个旧文件，导入 ${importedCount} 个文件${
        skippedCount ? `，跳过 ${skippedCount} 个` : ''
      }`
    )
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('source', buildOperationFailureMessage('标准规范上传'), error)
  } finally {
    actionLoading.value = ''
  }
}

const openEditSourceDialog = (row: KnowledgeSource) => {
  clearOperationIssue('source')
  sourceDialogContext.value = 'source'
  sourceDialogMode.value = 'edit'
  sourceEditingId.value = row.id
  sourceUploadFiles.value = []
  Object.assign(sourceForm, {
    name: row.name,
    sourceType: row.sourceType,
    version: row.version || '',
    status: row.status,
    fileCount: row.fileCount,
    chunkCount: row.chunkCount,
    vectorStatus: row.vectorStatus
  })
  sourceDialogVisible.value = true
}

const handleSaveSource = async () => {
  const sourceUploadRows = sourceUploadFiles.value
  const isStandardFileUpload = sourceDialogContext.value === 'standard-file'
  const isProjectFileUpload = sourceDialogContext.value === 'project-file'
  const sourceName =
    (isStandardFileUpload
      ? DEFAULT_STANDARD_SOURCE_NAME
      : isProjectFileUpload
        ? DEFAULT_PROJECT_FILE_SOURCE_NAME
        : sourceForm.name.trim()) ||
    sourceUploadRows[0]?.fileName.trim() ||
    ''
  if ((isStandardFileUpload || isProjectFileUpload) && !sourceUploadRows.length) {
    ElMessage.warning(isProjectFileUpload ? '请选择要上传的项目文件' : '请选择要上传的标准规范文件')
    return
  }
  if (isProjectFileUpload && !sourceUploadProjectId.value) {
    ElMessage.warning('请选择项目')
    return
  }
  if (!sourceName) {
    ElMessage.warning('请输入类别名称或选择上传文件')
    return
  }
  if (sourceDialogMode.value === 'create' && sourceUploadRows.some((row) => !row.fileName.trim())) {
    ElMessage.warning('请输入上传文件名称')
    return
  }
  actionLoading.value = 'source-save'
  clearOperationIssue('source')
  try {
    if (sourceDialogMode.value === 'create') {
      if (sourceUploadRows.length) {
        const res = await importKnowledgeFilesApi({
          files: sourceUploadRows.map((row) => row.file),
          sourceId: isProjectFileUpload
            ? DEFAULT_PROJECT_FILE_SOURCE_ID
            : isStandardFileUpload || sourceForm.sourceType === 'standard'
              ? DEFAULT_STANDARD_SOURCE_ID
              : createClientKnowledgeSourceId(),
          sourceName,
          sourceType: isProjectFileUpload
            ? 'project-file'
            : isStandardFileUpload
              ? 'standard'
              : sourceForm.sourceType,
          sourceVersion: isProjectFileUpload
            ? DEFAULT_PROJECT_FILE_SOURCE_VERSION
            : isStandardFileUpload
              ? DEFAULT_STANDARD_SOURCE_VERSION
              : sourceForm.version,
          sourceStatus: isStandardFileUpload || isProjectFileUpload ? '启用' : sourceForm.status,
          vectorStatus: '待向量化',
          projectId: isProjectFileUpload ? sourceUploadProjectId.value : undefined,
          projectName: isProjectFileUpload
            ? selectedSourceUploadProject.value?.name || sourceUploadProjectId.value
            : undefined,
          fileMetas: sourceUploadRows.map((row) => ({
            fileName: row.fileName.trim(),
            relativePath: row.relativePath,
            contextDescription: row.contextDescription.trim()
          }))
        })
        if (!res) {
          setOperationIssue('source', buildOperationFailureMessage('知识源文件上传'))
          return
        }
        const importedCount = res.data?.files?.length || 0
        const skippedCount = res.data?.skipped?.length || 0
        if (!importedCount && skippedCount) {
          const skippedMessage =
            res.data?.skipped?.map((item) => `${item.fileName}：${item.reason}`).join('；') ||
            '文件未写入知识库。'
          setOperationIssue('source', '知识源文件上传失败', new Error(skippedMessage))
          return
        }
        ElMessage.success(
          `${
            isProjectFileUpload
              ? '项目文件已上传'
              : isStandardFileUpload
                ? '标准规范文件已上传'
                : '知识源已新增'
          }，已上传 ${importedCount} 个文件${skippedCount ? `，跳过 ${skippedCount} 个` : ''}`
        )
      } else {
        const res = await createKnowledgeSourceApi({ ...sourceForm, name: sourceName })
        if (!res) {
          setOperationIssue('source', buildOperationFailureMessage('知识源新增'))
          return
        }
        ElMessage.success('知识源已新增')
      }
    } else {
      const currentSource = sources.value.find((item) => item.id === sourceEditingId.value)
      const res = await updateKnowledgeSourceApi(sourceEditingId.value, sourceForm, {
        etag: currentSource?.etag
      })
      if (!res) {
        setOperationIssue('source', buildOperationFailureMessage('知识源更新'))
        return
      }
      ElMessage.success('知识源已更新')
    }
    sourceDialogVisible.value = false
    sourceUploadFiles.value = []
    sourceUploadProjectId.value = ''
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue(
      'source',
      buildOperationFailureMessage(
        sourceDialogMode.value === 'create' ? '知识源新增' : '知识源更新'
      ),
      error
    )
  } finally {
    actionLoading.value = ''
  }
}

const handleToggleSourceStatus = async (row: KnowledgeSource) => {
  actionLoading.value = `source-status-${row.id}`
  clearOperationIssue('source')
  try {
    if (row.status === '启用') {
      const res = await disableKnowledgeSourceApi(
        row.id,
        { reason: '知识库管理页面停用' },
        { etag: row.etag }
      )
      if (!res) {
        setOperationIssue('source', buildOperationFailureMessage('知识源停用'))
        return
      }
      ElMessage.success(`${row.name} 已停用`)
    } else {
      const res = await enableKnowledgeSourceApi(
        row.id,
        { reason: '知识库管理页面启用' },
        { etag: row.etag }
      )
      if (!res) {
        setOperationIssue('source', buildOperationFailureMessage('知识源启用'))
        return
      }
      ElMessage.success(`${row.name} 已启用`)
    }
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue(
      'source',
      buildOperationFailureMessage(row.status === '启用' ? '知识源停用' : '知识源启用'),
      error
    )
  } finally {
    actionLoading.value = ''
  }
}

const getRollbackTargetVersion = (row: KnowledgeRuleVersion) =>
  ruleVersions.value.find((item) => item.ruleKey === row.ruleKey && item.id !== row.id)?.version

const ruleDisplayName = (row: KnowledgeRuleVersion) => row.inspectionItem || row.name

const normalizeRuleNodeSelectValue = (value?: string | number | null) =>
  value === undefined || value === null || value === '' ? '' : String(value)

const clearRuleNodeFields = () => {
  ruleForm.sequence = undefined
  ruleForm.sourceSequence = undefined
  ruleForm.inspectionCategory = ''
  ruleForm.inspectionItem = ''
  ruleForm.nodeIds = []
}

const syncRuleFieldsFromNodeOption = (option: RuleNodeSelectOption) => {
  if (!option.nodeId) return
  ruleNodeSelectValue.value = option.value
  ruleForm.sequence = option.nodeId
  ruleForm.sourceSequence = option.nodeId
  ruleForm.nodeIds = [option.nodeId]
  ruleForm.inspectionCategory = option.inspectionCategory || ''
  ruleForm.inspectionItem = option.inspectionItem || ''
}

const syncRuleFieldsFromSelectedNode = (
  value: string | number | null | undefined = ruleNodeSelectValue.value,
  clearWhenEmpty = false
) => {
  const normalizedValue = normalizeRuleNodeSelectValue(value)
  if (!normalizedValue) {
    if (clearWhenEmpty) clearRuleNodeFields()
    ruleNodeSelectValue.value = ''
    return
  }
  const option = ruleNodeOptionMap.value.get(normalizedValue)
  if (!option) return
  syncRuleFieldsFromNodeOption(option)
}

const loadRuleNodeTree = async () => {
  if (ruleBusinessPack.value?.nodeTemplates?.length) return
  ruleNodeTreeLoading.value = true
  try {
    const res = await getBusinessPackApi(DEFAULT_RULE_BUSINESS_PACK_ID)
    if (!res?.data?.nodeTemplates?.length) {
      setOperationIssue('rule', buildOperationFailureMessage('监检项目节点加载'))
      return
    }
    ruleBusinessPack.value = res.data
    syncRuleFieldsFromSelectedNode()
  } catch (error) {
    setOperationIssue('rule', buildOperationFailureMessage('监检项目节点加载'), error)
  } finally {
    ruleNodeTreeLoading.value = false
  }
}

const handleRuleNodeSelectChange = (value?: string | number | null) => {
  syncRuleFieldsFromSelectedNode(value, true)
}

const assignRuleForm = (row?: KnowledgeRuleVersion) => {
  Object.assign(ruleForm, emptyRuleForm())
  ruleNodeSelectValue.value = ''
  if (!row) return
  const sequence = row.sourceSequence || row.nodeIds?.[0]
  Object.assign(ruleForm, {
    sequence,
    sourceSequence: sequence,
    sourceRuleId: row.sourceRuleId || '',
    sourceDocument: row.sourceDocument || '',
    businessModule: row.businessModule || row.inspectionCategory || '',
    inspectionCategory: row.inspectionCategory || '',
    inspectionItem: row.inspectionItem || row.name || '',
    inspectionClass: row.inspectionClass || row.reviewClass || 'C',
    standardText: row.standardText || row.criteria || '',
    witnessText: row.witnessText || row.checkMethod || '',
    sourceWitness: row.sourceWitness || '',
    agentThinking: row.agentThinking || '',
    toolchainThinking: row.toolchainThinking || '',
    referencedStandards: row.referencedStandards ? [...row.referencedStandards] : [],
    materialTypeCodes: row.materialTypeCodes ? [...row.materialTypeCodes] : [],
    thinkingModeIds: row.thinkingModeIds ? [...row.thinkingModeIds] : [],
    toolIds: row.toolIds ? [...row.toolIds] : [],
    aiExecution: row.aiExecution,
    nodeIds: row.nodeIds?.length ? [...row.nodeIds] : sequence ? [sequence] : []
  })
  if (sequence) {
    ruleNodeSelectValue.value = String(sequence)
    syncRuleFieldsFromSelectedNode(ruleNodeSelectValue.value)
  }
}

const openCreateRuleEditor = async () => {
  clearOperationIssue('rule')
  ruleEditorMode.value = 'create'
  ruleEditingId.value = ''
  ruleEditingSource.value = null
  assignRuleForm()
  ruleEditorVisible.value = true
  await loadRuleNodeTree()
}

const openEditRuleEditor = async (row: KnowledgeRuleVersion) => {
  clearOperationIssue('rule')
  await loadRuleNodeTree()
  if (row.status === '已发布' || row.status === '已回滚') {
    actionLoading.value = `rule-fork-${row.id}`
    try {
      const res = await forkKnowledgeRuleVersionApi(row.id, {}, { etag: row.etag })
      if (!res?.data?.rule) {
        setOperationIssue('rule', buildOperationFailureMessage('创建规则草稿'))
        return
      }
      ruleEditorMode.value = 'edit'
      ruleEditingId.value = res.data.rule.id
      ruleEditingSource.value = res.data.rule
      assignRuleForm(res.data.rule)
      ruleEditorVisible.value = true
      ElMessage.success('已基于正式规则创建草稿')
      await Promise.all([loadRuleVersions(), loadKnowledgeAuditLogs()])
    } catch (error) {
      setOperationIssue('rule', buildOperationFailureMessage('创建规则草稿'), error)
    } finally {
      actionLoading.value = ''
    }
    return
  }
  ruleEditorMode.value = 'edit'
  ruleEditingId.value = row.id
  ruleEditingSource.value = row
  assignRuleForm(row)
  ruleEditorVisible.value = true
}

const buildRuleSavePayload = (): KnowledgeRuleVersionSavePayload => {
  syncRuleFieldsFromSelectedNode()
  const selectedNode = ruleNodeOptionMap.value.get(ruleNodeSelectValue.value)
  const sequence = selectedNode?.nodeId || ruleForm.sequence || ruleForm.sourceSequence
  return {
    sequence,
    sourceSequence: sequence,
    sourceRuleId: ruleForm.sourceRuleId?.trim(),
    sourceDocument: ruleForm.sourceDocument?.trim(),
    businessModule: ruleForm.businessModule?.trim() || ruleForm.inspectionCategory?.trim(),
    inspectionCategory: selectedNode?.inspectionCategory || ruleForm.inspectionCategory?.trim(),
    inspectionItem: selectedNode?.inspectionItem || ruleForm.inspectionItem.trim(),
    inspectionClass: ruleForm.inspectionClass || 'C',
    standardText: ruleForm.standardText?.trim(),
    witnessText: ruleForm.witnessText?.trim(),
    sourceWitness: ruleForm.sourceWitness?.trim(),
    agentThinking: ruleForm.agentThinking?.trim(),
    toolchainThinking: ruleForm.toolchainThinking?.trim(),
    referencedStandards: ruleForm.referencedStandards,
    materialTypeCodes: ruleForm.materialTypeCodes,
    thinkingModeIds: ruleForm.thinkingModeIds,
    toolIds: ruleForm.toolIds,
    aiExecution: ruleForm.aiExecution,
    nodeIds: sequence ? [sequence] : ruleForm.nodeIds
  }
}

const handleSaveRule = async () => {
  const selectedNode = ruleNodeOptionMap.value.get(ruleNodeSelectValue.value)
  if (!selectedNode?.nodeId) {
    ElMessage.warning('请选择监检项目节点')
    return
  }
  syncRuleFieldsFromNodeOption(selectedNode)
  if (!ruleForm.inspectionItem.trim()) {
    ElMessage.warning('请选择监检项目节点')
    return
  }
  if (!ruleForm.standardText?.trim() && !ruleForm.witnessText?.trim()) {
    ElMessage.warning('请填写判断准则 / 标准规范或方法及内容 / 工作见证')
    return
  }
  actionLoading.value = 'rule-save'
  clearOperationIssue('rule')
  try {
    const payload = buildRuleSavePayload()
    const res =
      ruleEditorMode.value === 'create'
        ? await createKnowledgeRuleVersionApi(payload)
        : await updateKnowledgeRuleVersionApi(ruleEditingId.value, payload, {
            etag: ruleEditingSource.value?.etag
          })
    if (!res) {
      setOperationIssue('rule', buildOperationFailureMessage('业务规则保存'))
      return
    }
    ElMessage.success(
      ruleEditorMode.value === 'create' ? '业务规则草稿已新增' : '业务规则草稿已保存'
    )
    ruleEditorVisible.value = false
    await Promise.all([loadRuleVersions(), loadKnowledgeAuditLogs()])
  } catch (error) {
    setOperationIssue('rule', buildOperationFailureMessage('业务规则保存'), error)
  } finally {
    actionLoading.value = ''
  }
}

const getRuleDiffTarget = (row: KnowledgeRuleVersion) =>
  ruleVersions.value.find(
    (item) => item.ruleKey === row.ruleKey && item.id !== row.id && item.status === '已发布'
  ) || ruleVersions.value.find((item) => item.ruleKey === row.ruleKey && item.id !== row.id)

const handleOpenRuleDiff = async (row: KnowledgeRuleVersion) => {
  selectedRuleDiffVersion.value = row
  ruleDiffVisible.value = true
  ruleDiffLoading.value = true
  ruleDiff.value = null
  clearOperationIssue('ruleDiff')
  const target = getRuleDiffTarget(row)
  try {
    const res = await getKnowledgeRuleVersionDiffApi(row.id, {
      targetVersionId: target?.id,
      targetVersion: target?.version
    })
    if (!res) {
      setOperationIssue('ruleDiff', buildOperationFailureMessage('规则版本差异加载'))
      return
    }
    ruleDiff.value = res.data
  } catch (error) {
    setOperationIssue('ruleDiff', buildOperationFailureMessage('规则版本差异加载'), error)
  } finally {
    ruleDiffLoading.value = false
  }
}

const retryRuleDiff = () => {
  if (selectedRuleDiffVersion.value) {
    handleOpenRuleDiff(selectedRuleDiffVersion.value)
  }
}

const handlePublishRule = async (row: KnowledgeRuleVersion) => {
  actionLoading.value = `rule-publish-${row.id}`
  clearOperationIssue('rule')
  try {
    const res = await publishKnowledgeRuleVersionApi(
      row.id,
      { reason: '知识库规则管理发布' },
      { etag: row.etag }
    )
    if (!res) {
      setOperationIssue('rule', buildOperationFailureMessage('规则版本发布'))
      return
    }
    ElMessage.success(`${row.name} 已发布`)
    await Promise.all([loadRuleVersions(), loadKnowledgeAuditLogs()])
  } catch (error) {
    setOperationIssue('rule', buildOperationFailureMessage('规则版本发布'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleRollbackRule = async (row: KnowledgeRuleVersion) => {
  const targetVersion = getRollbackTargetVersion(row)
  if (!targetVersion) {
    ElMessage.warning('没有可回滚的目标版本')
    return
  }
  actionLoading.value = `rule-rollback-${row.id}`
  clearOperationIssue('rule')
  try {
    const res = await rollbackKnowledgeRuleVersionApi(
      row.id,
      {
        targetVersion,
        reason: '知识库规则管理回滚'
      },
      { etag: row.etag }
    )
    if (!res) {
      setOperationIssue('rule', buildOperationFailureMessage('规则版本回滚'))
      return
    }
    ElMessage.success(`${row.name} 已回滚到 ${targetVersion}`)
    await Promise.all([loadRuleVersions(), loadKnowledgeAuditLogs()])
  } catch (error) {
    setOperationIssue('rule', buildOperationFailureMessage('规则版本回滚'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleSaveKnowledgeConfig = async () => {
  if (knowledgeConfig.chunkOverlap >= knowledgeConfig.chunkSize) {
    ElMessage.warning('切片重叠必须小于切片长度')
    return
  }
  actionLoading.value = 'config-save'
  clearOperationIssue('config')
  try {
    const payload: Partial<KnowledgeConfig> = { ...knowledgeConfig }
    delete payload.etag
    delete payload.revision
    delete payload.updatedAt
    const res = await updateKnowledgeConfigApi(payload, { etag: knowledgeConfig.etag })
    if (!res) {
      setOperationIssue('config', buildOperationFailureMessage('知识库配置保存'))
      return
    }
    if (res.data?.config) Object.assign(knowledgeConfig, res.data.config)
    ElMessage.success('知识库配置已保存')
    await loadKnowledgeAuditLogs()
  } catch (error) {
    setOperationIssue('config', buildOperationFailureMessage('知识库配置保存'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleReindexAll = async () => {
  actionLoading.value = 'reindex-all'
  clearOperationIssue('reindex')
  try {
    const res = await batchReindexKnowledgeApi({ scope: 'all' })
    if (!res) {
      setOperationIssue('reindex', buildOperationFailureMessage('批量重建索引'))
      return
    }
    ElMessage.success(`已创建 ${res.data?.taskIds?.length || 0} 个索引任务`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('reindex', buildOperationFailureMessage('批量重建索引'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleReindexSource = async (row: KnowledgeOverviewPayload['libraries'][number]) => {
  actionLoading.value = `source-${row.key}`
  clearOperationIssue('reindex')
  try {
    const res = await batchReindexKnowledgeApi({ scope: 'source', sourceId: row.key })
    if (!res) {
      setOperationIssue('reindex', buildOperationFailureMessage('知识源重建索引'))
      return
    }
    ElMessage.success(`${row.name} 已加入索引任务队列`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('reindex', buildOperationFailureMessage('知识源重建索引'), error)
  } finally {
    actionLoading.value = ''
  }
}

const loadKnowledgeFileDetailBundle = async (row: KnowledgeFile) => {
  const [detailRes, chunksRes, vectorRes, refRes] = await Promise.all([
    getKnowledgeFileDetailApi(row.id, { silentBusinessError: true }),
    listKnowledgeFileChunksApi(row.id, { pageSize: 12 }, { silentBusinessError: true }),
    getKnowledgeFileVectorApi(row.id, { silentBusinessError: true }),
    listKnowledgeFileReasoningReferencesApi(row.id, { pageSize: 10 }, { silentBusinessError: true })
  ])
  if (!detailRes || !chunksRes || !vectorRes || !refRes) {
    throw new Error('文件知识详情接口未返回有效数据。')
  }
  return { detailRes, chunksRes, vectorRes, refRes }
}

const findFreshStandardFile = async (row: KnowledgeFile) => {
  const keyword = row.sourceRelativePath || row.originalFileName || row.fileName
  if (!keyword) return undefined
  const res = assertApiResponse(
    await listKnowledgeProjectFilesApi({
      keyword,
      sourceType: 'standard',
      page: 1,
      pageSize: 200
    }),
    '标准规范文件接口未返回有效数据。'
  )
  const items = res.data?.items || []
  const fresh =
    items.find(
      (item) => row.sourceRelativePath && item.sourceRelativePath === row.sourceRelativePath
    ) ||
    items.find((item) => row.originalFileName && item.originalFileName === row.originalFileName) ||
    items.find((item) => item.fileName === row.fileName)
  if (fresh) {
    const index = standardFiles.value.findIndex(
      (item) =>
        item.id === row.id ||
        Boolean(row.sourceRelativePath && item.sourceRelativePath === row.sourceRelativePath)
    )
    if (index >= 0) {
      standardFiles.value.splice(index, 1, fresh)
    }
  }
  return fresh
}

const handleOpenFile = async (row: KnowledgeFile) => {
  fileDrawerVisible.value = true
  fileDetailLoading.value = true
  fileDetail.value = null
  fileChunks.value = []
  fileReferences.value = []
  clearOperationIssue('fileDetail')
  try {
    let target = row
    let bundle
    try {
      bundle = await loadKnowledgeFileDetailBundle(target)
    } catch (error) {
      const fresh = await findFreshStandardFile(row)
      if (!fresh || fresh.id === row.id) throw error
      target = fresh
      bundle = await loadKnowledgeFileDetailBundle(target)
      ElMessage.info('列表数据已刷新，已打开最新标准规范详情')
    }
    const { detailRes, chunksRes, vectorRes, refRes } = bundle
    fileDetail.value = {
      ...detailRes.data,
      vectorSummary: vectorRes.data
    }
    fileChunks.value = chunksRes.data?.items || []
    fileReferences.value = refRes.data?.items || []
  } catch (error) {
    setOperationIssue('fileDetail', buildOperationFailureMessage('文件知识详情加载'), error)
  } finally {
    fileDetailLoading.value = false
  }
}

const openKnowledgeFileOriginal = (mode: 'preview' | 'download') => {
  const target = mode === 'preview' ? fileDetail.value?.preview : fileDetail.value?.download
  if (!target?.url) {
    ElMessage.warning('原文地址尚未生成')
    return
  }
  window.open(target.url, '_blank', 'noopener,noreferrer')
}

const handleReindexFile = async (row: KnowledgeFile) => {
  actionLoading.value = `file-${row.id}`
  clearOperationIssue('file')
  try {
    const res = await reindexKnowledgeFileApi(row.id, { force: true })
    if (!res) {
      setOperationIssue('file', buildOperationFailureMessage('文件重建索引'))
      return
    }
    ElMessage.success(`${row.fileName} 已加入索引任务队列`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('file', buildOperationFailureMessage('文件重建索引'), error)
  } finally {
    actionLoading.value = ''
  }
}

const openEditStandardFileDialog = (row: KnowledgeFile) => {
  clearOperationIssue('file')
  standardFileDialogMode.value = 'edit'
  standardFileEditing.value = row
  standardFileReplacement.value = null
  Object.assign(standardFileForm, {
    fileName: row.fileName || '',
    sourceRelativePath: row.sourceRelativePath || row.originalFileName || row.fileName || '',
    contextDescription: row.contextDescription || '',
    projectId: row.projectId || '',
    projectName: row.projectName || ''
  })
  standardFileDialogVisible.value = true
}

const openReplaceStandardFileDialog = (row: KnowledgeFile) => {
  clearOperationIssue('file')
  standardFileDialogMode.value = 'replace'
  standardFileEditing.value = row
  standardFileReplacement.value = null
  Object.assign(standardFileForm, {
    fileName: row.fileName || '',
    sourceRelativePath: row.sourceRelativePath || row.originalFileName || row.fileName || '',
    contextDescription: row.contextDescription || '',
    projectId: row.projectId || '',
    projectName: row.projectName || ''
  })
  standardFileDialogVisible.value = true
}

const triggerStandardFileReplaceSelect = () => {
  standardFileReplaceInputRef.value?.click()
}

const handleStandardFileReplaceInputChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!isAllowedKnowledgeImportFile(file)) {
    ElMessage.warning('文件类型不支持')
    input.value = ''
    return
  }
  standardFileReplacement.value = file
  if (!standardFileForm.fileName.trim()) {
    standardFileForm.fileName = file.name
  }
  const relativePath =
    (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
  if (!standardFileForm.sourceRelativePath.trim()) {
    standardFileForm.sourceRelativePath = relativePath
  }
  input.value = ''
}

const handleSaveStandardFile = async () => {
  const current = standardFileEditing.value
  if (!current) return
  if (!standardFileForm.fileName.trim()) {
    ElMessage.warning('请输入文件名称')
    return
  }
  if (isProjectKnowledgeFile(current) && !standardFileForm.projectId) {
    ElMessage.warning('请选择项目')
    return
  }
  if (standardFileDialogMode.value === 'replace' && !standardFileReplacement.value) {
    ElMessage.warning('请选择替换版本文件')
    return
  }
  actionLoading.value = 'standard-file-save'
  clearOperationIssue('file')
  try {
    if (standardFileDialogMode.value === 'edit') {
      const res = await updateKnowledgeFileApi(
        current.id,
        {
          fileName: standardFileForm.fileName.trim(),
          sourceRelativePath: standardFileForm.sourceRelativePath.trim(),
          contextDescription: standardFileForm.contextDescription.trim(),
          projectId: isProjectKnowledgeFile(current) ? standardFileForm.projectId : undefined,
          projectName: isProjectKnowledgeFile(current)
            ? selectedKnowledgeFileProjectName.value
            : undefined
        },
        { etag: current.etag }
      )
      if (!res) {
        setOperationIssue(
          'file',
          buildOperationFailureMessage(`${currentKnowledgeFileKind.value}更新`)
        )
        return
      }
      ElMessage.success(`${currentKnowledgeFileKind.value}已更新`)
    } else if (standardFileReplacement.value) {
      const res = await replaceKnowledgeFileVersionApi(
        current.id,
        {
          file: standardFileReplacement.value,
          fileName: standardFileForm.fileName.trim(),
          relativePath: standardFileForm.sourceRelativePath.trim(),
          contextDescription: standardFileForm.contextDescription.trim()
        },
        { etag: current.etag }
      )
      if (!res) {
        setOperationIssue(
          'file',
          buildOperationFailureMessage(`${currentKnowledgeFileKind.value}版本替换`)
        )
        return
      }
      ElMessage.success(`${currentKnowledgeFileKind.value}版本已替换，已重新进入识别队列`)
    }
    standardFileDialogVisible.value = false
    standardFileReplacement.value = null
    standardFileEditing.value = null
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue(
      'file',
      buildOperationFailureMessage(
        standardFileDialogMode.value === 'edit'
          ? `${currentKnowledgeFileKind.value}更新`
          : `${currentKnowledgeFileKind.value}版本替换`
      ),
      error
    )
  } finally {
    actionLoading.value = ''
  }
}

const handleDeleteStandardFile = async (row: KnowledgeFile) => {
  actionLoading.value = `file-delete-${row.id}`
  clearOperationIssue('file')
  const fileKind = isProjectKnowledgeFile(row) ? '项目文件' : '标准规范'
  try {
    const res = await deleteKnowledgeFileApi(
      row.id,
      { reason: `${fileKind}页面删除` },
      { etag: row.etag }
    )
    if (!res) {
      setOperationIssue('file', buildOperationFailureMessage(`${fileKind}删除`))
      return
    }
    ElMessage.success(`${row.fileName} 已删除`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('file', buildOperationFailureMessage(`${fileKind}删除`), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleRetryTask = async (row: KnowledgeTask) => {
  actionLoading.value = `retry-${row.id}`
  clearOperationIssue('task')
  try {
    const res = await retryKnowledgeTaskApi(
      row.id,
      { reason: '前端任务中心手动重试' },
      { etag: row.etag }
    )
    if (!res) {
      setOperationIssue('task', buildOperationFailureMessage('知识库任务重试'))
      return
    }
    ElMessage.success(`${row.targetName} 已重新排队`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('task', buildOperationFailureMessage('知识库任务重试'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleCancelTask = async (row: KnowledgeTask) => {
  actionLoading.value = `cancel-${row.id}`
  clearOperationIssue('task')
  try {
    const res = await cancelKnowledgeTaskApi(
      row.id,
      { reason: '前端任务中心取消排队任务' },
      { etag: row.etag }
    )
    if (!res) {
      setOperationIssue('task', buildOperationFailureMessage('知识库任务取消'))
      return
    }
    ElMessage.success(`${row.targetName} 已取消`)
    await refreshKnowledgeState()
  } catch (error) {
    setOperationIssue('task', buildOperationFailureMessage('知识库任务取消'), error)
  } finally {
    actionLoading.value = ''
  }
}

const handleRunRetrieval = async () => {
  if (!retrievalForm.question.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  retrievalLoading.value = true
  clearOperationIssue('retrieval')
  try {
    const res = await runKnowledgeRetrievalTestApi({
      question: retrievalForm.question,
      scope: retrievalForm.scope,
      topK: retrievalForm.topK
    })
    if (!res) {
      setOperationIssue('retrieval', buildOperationFailureMessage('知识检索测试'))
      return
    }
    retrievalResult.value = res.data
    if (res.data.retrievalTrace?.selectedRoute === 'pageindex_tree_search') {
      await loadPageIndexNodes(retrievalForm.question)
    }
  } catch (error) {
    setOperationIssue('retrieval', buildOperationFailureMessage('知识检索测试'), error)
  } finally {
    retrievalLoading.value = false
  }
}

const handleOpenReasoningLog = async (row: AiReviewRun) => {
  reasoningDrawerVisible.value = true
  reasoningDetailLoading.value = true
  reasoningDetail.value = null
  clearOperationIssue('reasoningDetail')
  try {
    const res = await getReasoningLogDetailApi(row.id)
    if (!res) {
      setOperationIssue('reasoningDetail', buildOperationFailureMessage('推理链路详情加载'))
      return
    }
    reasoningDetail.value = res.data
  } catch (error) {
    setOperationIssue('reasoningDetail', buildOperationFailureMessage('推理链路详情加载'), error)
  } finally {
    reasoningDetailLoading.value = false
  }
}

const handleRunCompare = async () => {
  if (!compareForm.question.trim()) {
    ElMessage.warning('请输入对比问题')
    return
  }
  if (compareForm.modelCodes.length < 2) {
    ElMessage.warning('至少选择两个模型')
    return
  }
  compareLoading.value = true
  clearOperationIssue('compare')
  try {
    const res = await runLlmCompareApi({
      question: compareForm.question,
      modelCodes: compareForm.modelCodes,
      nodeId: compareForm.nodeId
    })
    if (!res) {
      setOperationIssue('compare', buildOperationFailureMessage('多模型对比运行'))
      return
    }
    compareResult.value = res.data
    await loadCompareRuns()
  } catch (error) {
    setOperationIssue('compare', buildOperationFailureMessage('多模型对比运行'), error)
  } finally {
    compareLoading.value = false
  }
}

const handleOpenCompareRun = async (row: LlmCompareRunSummary) => {
  compareLoading.value = true
  clearOperationIssue('compare')
  try {
    const res = await getLlmCompareRunApi(row.runId)
    if (!res) {
      setOperationIssue('compare', buildOperationFailureMessage('多模型历史加载'))
      return
    }
    compareResult.value = res.data
  } catch (error) {
    setOperationIssue('compare', buildOperationFailureMessage('多模型历史加载'), error)
  } finally {
    compareLoading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="knowledge-page" v-loading="loading">
    <StaticPageShell
      brand-mark="知"
      title="AI 知识库管理"
      status="索引运行中"
      status-tone="orange"
      search-placeholder="搜索条款、资料、PageIndex、检索 Trace"
      user-label="系统管理员 周工"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="运行摘要"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="knowledgeTopStats"
      menu-title="知识库菜单"
      menu-root="AI 知识库管理"
      peer-nav-title="后台同级功能"
      :peer-nav-items="knowledgePeerNavItems"
      :menu-sections="knowledgeShellMenuSections"
      boundary-title="后台边界"
      boundary-badge="只管理"
      boundary-tone="green"
      :boundary-rows="knowledgeShellBoundaryRows"
      right-title="运行状态"
      right-subtitle="索引版本：proj-v2026.06.26"
      :right-cards="knowledgeShellRightCards"
      @menu-select="handleKnowledgeMenuSelect"
      @top-stat-click="handleKnowledgeTopStatClick"
    >
      <div class="page-toolbar">
        <div>
          <div class="page-title">AI 知识库管理</div>
          <div class="page-subtitle"
            >知识工程审计台 · 追踪资料入库、OCR 切片、向量化、PageIndex 与引用质量</div
          >
        </div>
        <ElButton
          type="primary"
          :disabled="!!pageIssue"
          :loading="actionLoading === 'reindex-all'"
          @click="handleReindexAll"
        >
          重建索引
        </ElButton>
      </div>

      <AuditSummaryGrid
        v-if="canShowKnowledgeContent"
        :cards="knowledgeAuditCards"
        aria-label="知识工程审计摘要"
      />

      <WorkbenchStateBanner
        v-if="pageIssue"
        :type="pageIssue.type"
        :title="pageIssue.title"
        :message="pageIssue.message"
        action-label="重新加载"
        :action-loading="loading"
        @action="handleRetryLoad"
      />

      <div v-if="operationIssues.reindex && canShowKnowledgeContent" class="section-error">
        <div>
          <strong>{{ operationIssues.reindex.title }}</strong>
          <span>{{ operationIssues.reindex.message }}</span>
        </div>
        <ElButton
          size="small"
          type="primary"
          plain
          :loading="actionLoading === 'reindex-all'"
          @click="handleReindexAll"
        >
          重试重建索引
        </ElButton>
      </div>

      <details v-if="canShowKnowledgeContent" class="secondary-summary-collapse">
        <summary>
          <span>索引统计明细</span>
          <small>摘要卡已展示核心状态，展开查看任务与索引计数</small>
        </summary>
        <div class="metric-grid">
          <div
            v-for="metric in metrics"
            :key="metric.key"
            :class="`metric-card metric-card--${metric.tone}`"
          >
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </div>
        </div>
      </details>

      <ElCard v-if="canShowKnowledgeContent && knowledgeScorecard" shadow="never" class="panel">
        <template #header>
          <div class="panel-header">
            <span>知识依据链 100</span>
            <ElTag :type="knowledgeScorecard.ok ? 'success' : 'danger'" effect="plain">
              {{ knowledgeScorecard.ok ? '生产就绪' : '存在阻断' }}
            </ElTag>
          </div>
        </template>
        <div class="scorecard-grid">
          <div class="scorecard-item">
            <span>总分</span>
            <strong>{{ knowledgeScorecard.score }}/{{ knowledgeScorecard.targetScore }}</strong>
          </div>
          <div class="scorecard-item">
            <span>评分域</span>
            <strong>{{ knowledgeScorecardSections.length }}</strong>
          </div>
          <div class="scorecard-item">
            <span>阻断项</span>
            <strong>{{ knowledgeScorecard.blockers.length }}</strong>
          </div>
          <div class="scorecard-item">
            <span>检索探针</span>
            <strong>{{ knowledgeRetrievalProbeRows.length }}</strong>
          </div>
        </div>
        <ElRow :gutter="12" class="mt-12">
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElTable
              :data="knowledgeScorecardSections"
              border
              height="190"
              empty-text="暂无知识质量评分项"
            >
              <ElTableColumn prop="name" label="评分域" min-width="140" show-overflow-tooltip />
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
          </ElCol>
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElTable
              :data="knowledgeRetrievalProbeRows"
              border
              height="190"
              empty-text="暂无检索探针"
            >
              <ElTableColumn
                prop="expectedRoute"
                label="期望路由"
                min-width="155"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="selectedRoute"
                label="实际路由"
                min-width="155"
                show-overflow-tooltip
              />
              <ElTableColumn prop="selectedClauseCount" label="条款" width="80" />
              <ElTableColumn prop="passed" label="结果" width="90">
                <template #default="{ row }">
                  <ElTag :type="row.passed ? 'success' : 'danger'" effect="plain">
                    {{ row.passed ? '通过' : '失败' }}
                  </ElTag>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCol>
          <ElCol :xl="8" :lg="8" :md="24" :sm="24" :xs="24">
            <ElTable
              v-if="knowledgeScorecardBlockerRows.length"
              :data="knowledgeScorecardBlockerRows"
              border
              height="190"
            >
              <ElTableColumn prop="id" label="#" width="64" />
              <ElTableColumn prop="blocker" label="阻断项" min-width="250" show-overflow-tooltip />
            </ElTable>
            <ElAlert
              v-else
              type="success"
              show-icon
              :closable="false"
              title="知识依据链未发现生产阻断项。"
            />
          </ElCol>
        </ElRow>
      </ElCard>

      <AdminKnowledgeStaticDeepSections
        v-if="canShowKnowledgeContent"
        mode="knowledge"
        :knowledge-overview="overview"
        :knowledge-sources="sources"
        :knowledge-files="files"
        :knowledge-tasks="tasks"
        :knowledge-rules="ruleVersions"
        :knowledge-reasoning-logs="reasoningLogs"
        :knowledge-compare-runs="compareRuns"
        :knowledge-config="knowledgeConfig"
        :knowledge-audit-logs="auditLogs"
      />

      <ElTabs v-if="canShowKnowledgeContent" v-model="activeTab" class="knowledge-tabs">
        <ElTabPane label="总览" name="overview">
          <ElRow :gutter="16">
            <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>知识库索引</span>
                    <ElTag type="info" effect="plain">{{ libraries.length }} 个库</ElTag>
                  </div>
                </template>
                <ElTable :data="libraries" border height="360" empty-text="暂无知识库索引">
                  <ElTableColumn prop="name" label="知识库" min-width="220" />
                  <ElTableColumn prop="fileCount" label="文件" width="88" />
                  <ElTableColumn prop="chunkCount" label="切片" width="100" />
                  <ElTableColumn prop="vectorCount" label="向量" width="100" />
                  <ElTableColumn label="向量化" min-width="160">
                    <template #default="{ row }">
                      <ElProgress :percentage="vectorPercent(row)" :stroke-width="8" />
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="indexVersion" label="索引版本" width="150" />
                  <ElTableColumn label="状态" width="100">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
                  <ElTableColumn label="操作" width="110" fixed="right">
                    <template #default="{ row }">
                      <ElButton
                        link
                        type="primary"
                        :loading="actionLoading === `source-${row.key}`"
                        @click="handleReindexSource(row)"
                      >
                        重建索引
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>

            <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>知识源</span>
                    <ElSpace>
                      <ElTag type="success" effect="plain">{{ sources.length }} 个来源</ElTag>
                      <ElButton size="small" type="primary" @click="openCreateSourceDialog()">
                        新增
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <div class="filter-bar compact">
                  <ElInput
                    v-model="sourceFilters.keyword"
                    clearable
                    placeholder="搜索知识源"
                    @change="handleFilterChange(sourcePagination, loadSources)"
                  />
                  <ElSelect
                    v-model="sourceFilters.sourceType"
                    clearable
                    placeholder="类型"
                    @change="handleFilterChange(sourcePagination, loadSources)"
                  >
                    <ElOption label="标准规范" value="standard" />
                    <ElOption label="项目文件" value="project-file" />
                    <ElOption label="人工维护" value="manual" />
                  </ElSelect>
                  <ElSelect
                    v-model="sourceFilters.status"
                    clearable
                    placeholder="状态"
                    @change="handleFilterChange(sourcePagination, loadSources)"
                  >
                    <ElOption
                      v-for="status in sourceStatusOptions"
                      :key="status"
                      :label="status"
                      :value="status"
                    />
                  </ElSelect>
                </div>
                <div v-if="sectionIssues.sources" class="section-error">
                  <div>
                    <strong>{{ sectionIssues.sources.title }}</strong>
                    <span>{{ sectionIssues.sources.message }}</span>
                  </div>
                  <ElButton size="small" type="primary" plain @click="loadSources">
                    重新加载
                  </ElButton>
                </div>
                <div v-if="operationIssues.source" class="section-error">
                  <div>
                    <strong>{{ operationIssues.source.title }}</strong>
                    <span>{{ operationIssues.source.message }}</span>
                  </div>
                  <ElButton size="small" type="primary" plain @click="loadSources"
                    >刷新列表</ElButton
                  >
                </div>
                <div class="source-list">
                  <div v-for="source in sources" :key="source.id" class="source-item">
                    <div>
                      <strong>{{ source.name }}</strong>
                      <span
                        >{{ sourceTypeLabel(source.sourceType) }} ·
                        {{ source.version || '未发布' }}</span
                      >
                    </div>
                    <div class="source-actions">
                      <ElTag :type="statusType(source.status)" effect="light">
                        {{ source.status }}
                      </ElTag>
                      <ElTag :type="statusType(source.vectorStatus)" effect="plain">
                        {{ source.vectorStatus }}
                      </ElTag>
                      <ElButton link type="primary" @click="openEditSourceDialog(source)">
                        编辑
                      </ElButton>
                      <ElButton
                        link
                        :type="source.status === '启用' ? 'danger' : 'success'"
                        :loading="actionLoading === `source-status-${source.id}`"
                        @click="handleToggleSourceStatus(source)"
                      >
                        {{ source.status === '启用' ? '停用' : '启用' }}
                      </ElButton>
                    </div>
                  </div>
                </div>
                <ElPagination
                  v-if="sourcePagination.total > sourcePagination.pageSize"
                  v-model:current-page="sourcePagination.page"
                  v-model:page-size="sourcePagination.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="[6, 10, 20, 50]"
                  layout="total, sizes, prev, pager, next"
                  :total="sourcePagination.total"
                  @size-change="(size) => handlePageSizeChange(sourcePagination, loadSources, size)"
                  @current-change="(page) => handlePageChange(sourcePagination, loadSources, page)"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="标准规范库" name="source-manage">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>标准规范库</span>
                <ElSpace>
                  <ElTag effect="plain">{{ standardFilePagination.total }} 个标准规范</ElTag>
                  <ElButton
                    type="success"
                    plain
                    :loading="actionLoading === 'rules-standards-import'"
                    @click="handleImportRulesStandards"
                  >
                    重新初始化标准库
                  </ElButton>
                  <ElButton type="primary" @click="openCreateSourceDialog('standard-file')">
                    上传标准文件
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <div v-if="sectionIssues.standardFiles" class="section-error">
              <div>
                <strong>{{ sectionIssues.standardFiles.title }}</strong>
                <span>{{ sectionIssues.standardFiles.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadStandardFiles">
                重新加载
              </ElButton>
            </div>
            <div v-if="operationIssues.source" class="section-error">
              <div>
                <strong>{{ operationIssues.source.title }}</strong>
                <span>{{ operationIssues.source.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadStandardFiles">
                刷新列表
              </ElButton>
            </div>
            <div v-if="operationIssues.file" class="section-error">
              <div>
                <strong>{{ operationIssues.file.title }}</strong>
                <span>{{ operationIssues.file.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadStandardFiles">
                刷新列表
              </ElButton>
            </div>
            <div class="filter-bar">
              <ElInput
                v-model="standardFileFilters.keyword"
                clearable
                placeholder="搜索标准规范名称或路径"
                @change="handleFilterChange(standardFilePagination, loadStandardFiles)"
              />
              <ElSelect
                v-model="standardFileFilters.status"
                clearable
                placeholder="处理状态"
                @change="handleFilterChange(standardFilePagination, loadStandardFiles)"
              >
                <ElOption label="待识别" value="待识别" />
                <ElOption label="未识别" value="未识别" />
                <ElOption label="识别中" value="识别中" />
                <ElOption label="已识别" value="已识别" />
                <ElOption label="未切片" value="未切片" />
                <ElOption label="已切片" value="已切片" />
                <ElOption label="待向量化" value="待向量化" />
                <ElOption label="已向量化" value="已向量化" />
              </ElSelect>
              <ElButton @click="loadStandardFiles">刷新</ElButton>
            </div>
            <ElTable :data="standardFiles" border height="430" empty-text="暂无标准规范文件">
              <ElTableColumn
                prop="fileName"
                label="标准规范"
                min-width="280"
                show-overflow-tooltip
              />
              <ElTableColumn label="来源路径" min-width="320" show-overflow-tooltip>
                <template #default="{ row }">{{ standardFilePath(row) }}</template>
              </ElTableColumn>
              <ElTableColumn label="OCR" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.ocrStatus)" effect="light">{{
                    row.ocrStatus
                  }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="切片" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.sliceStatus)" effect="light">{{
                    row.sliceStatus
                  }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="向量" width="120">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.vectorStatus)" effect="plain">
                    {{ row.vectorStatus }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="切片/向量" width="120">
                <template #default="{ row }">{{ row.chunkCount }} / {{ row.vectorCount }}</template>
              </ElTableColumn>
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
              <ElTableColumn label="操作" width="320" fixed="right">
                <template #default="{ row }">
                  <div class="standard-file-actions">
                    <ElButton link type="primary" @click="handleOpenFile(row)">详情</ElButton>
                    <ElButton link type="primary" @click="openEditStandardFileDialog(row)">
                      编辑
                    </ElButton>
                    <ElButton link type="primary" @click="openReplaceStandardFileDialog(row)">
                      替换版本
                    </ElButton>
                    <ElButton
                      link
                      type="primary"
                      :loading="actionLoading === `file-${row.id}`"
                      @click="handleReindexFile(row)"
                    >
                      重建索引
                    </ElButton>
                    <ElPopconfirm
                      title="确认删除这个标准规范？"
                      confirm-button-text="删除"
                      cancel-button-text="取消"
                      @confirm="handleDeleteStandardFile(row)"
                    >
                      <template #reference>
                        <ElButton
                          link
                          type="danger"
                          :loading="actionLoading === `file-delete-${row.id}`"
                        >
                          删除
                        </ElButton>
                      </template>
                    </ElPopconfirm>
                  </div>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-if="standardFilePagination.total > standardFilePagination.pageSize"
              v-model:current-page="standardFilePagination.page"
              v-model:page-size="standardFilePagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="standardFilePagination.total"
              @size-change="
                (size) => handlePageSizeChange(standardFilePagination, loadStandardFiles, size)
              "
              @current-change="
                (page) => handlePageChange(standardFilePagination, loadStandardFiles, page)
              "
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="规则配置" name="rules">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>业务判断规则管理</span>
                <ElSpace>
                  <ElTag effect="plain">{{ rulePagination.total }} 条规则</ElTag>
                  <ElButton type="primary" @click="openCreateRuleEditor">新增规则</ElButton>
                  <ElButton
                    type="success"
                    plain
                    :loading="actionLoading === 'knowledge-import'"
                    @click="openKnowledgeImportDialog"
                  >
                    从文件导入草稿
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <div class="filter-bar">
              <ElInput
                v-model="ruleFilters.keyword"
                clearable
                placeholder="搜索大类、监检项目、标准或方法"
                @change="handleFilterChange(rulePagination, loadRuleVersions)"
              />
              <ElSelect
                v-model="ruleFilters.status"
                clearable
                placeholder="状态"
                @change="handleFilterChange(rulePagination, loadRuleVersions)"
              >
                <ElOption
                  v-for="status in ruleStatusOptions"
                  :key="status"
                  :label="status"
                  :value="status"
                />
              </ElSelect>
              <ElButton @click="loadRuleVersions">刷新</ElButton>
            </div>
            <div v-if="sectionIssues.rules" class="section-error">
              <div>
                <strong>{{ sectionIssues.rules.title }}</strong>
                <span>{{ sectionIssues.rules.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadRuleVersions">
                重新加载
              </ElButton>
            </div>
            <div v-if="operationIssues.rule" class="section-error">
              <div>
                <strong>{{ operationIssues.rule.title }}</strong>
                <span>{{ operationIssues.rule.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadRuleVersions">
                刷新规则
              </ElButton>
            </div>
            <div v-if="operationIssues.import" class="section-error">
              <div>
                <strong>{{ operationIssues.import.title }}</strong>
                <span>{{ operationIssues.import.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="openKnowledgeImportDialog">
                重新导入
              </ElButton>
            </div>
            <ElTable :data="ruleVersions" border height="430" empty-text="暂无业务规则">
              <ElTableColumn label="序号" width="78">
                <template #default="{ row }">{{
                  row.sourceSequence || row.nodeIds?.[0] || '-'
                }}</template>
              </ElTableColumn>
              <ElTableColumn
                prop="inspectionCategory"
                label="监检项目（大类）"
                min-width="150"
                show-overflow-tooltip
              />
              <ElTableColumn label="监检项目（内容）" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ ruleDisplayName(row) }}</template>
              </ElTableColumn>
              <ElTableColumn label="类别" width="82">
                <template #default="{ row }">{{
                  row.inspectionClass || row.reviewClass || '-'
                }}</template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="100">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="standardText"
                label="判断准则 / 标准规范"
                min-width="260"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="witnessText"
                label="方法及内容 / 工作见证"
                min-width="280"
                show-overflow-tooltip
              />
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
              <ElTableColumn label="操作" width="230" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    link
                    type="primary"
                    :loading="actionLoading === `rule-fork-${row.id}`"
                    @click="openEditRuleEditor(row)"
                  >
                    {{ row.status === '草稿' || row.status === '待发布' ? '编辑' : '基于此编辑' }}
                  </ElButton>
                  <ElButton
                    v-if="row.status === '草稿' || row.status === '待发布'"
                    link
                    type="primary"
                    :loading="actionLoading === `rule-publish-${row.id}`"
                    @click="handlePublishRule(row)"
                  >
                    发布
                  </ElButton>
                  <ElButton
                    v-if="row.status === '已发布'"
                    link
                    type="warning"
                    :loading="actionLoading === `rule-rollback-${row.id}`"
                    @click="handleRollbackRule(row)"
                  >
                    回滚
                  </ElButton>
                  <ElButton link type="info" @click="handleOpenRuleDiff(row)">变更</ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-if="rulePagination.total > rulePagination.pageSize"
              v-model:current-page="rulePagination.page"
              v-model:page-size="rulePagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="rulePagination.total"
              @size-change="(size) => handlePageSizeChange(rulePagination, loadRuleVersions, size)"
              @current-change="(page) => handlePageChange(rulePagination, loadRuleVersions, page)"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="配置审计" name="config">
          <ElRow :gutter="16">
            <ElCol :xl="9" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>知识库配置</span>
                    <ElTag effect="plain">{{ knowledgeConfig.updatedAt || '未保存' }}</ElTag>
                  </div>
                </template>
                <div v-if="sectionIssues.config" class="section-error">
                  <div>
                    <strong>{{ sectionIssues.config.title }}</strong>
                    <span>{{ sectionIssues.config.message }}</span>
                  </div>
                  <ElButton size="small" type="primary" plain @click="loadKnowledgeConfig">
                    重新加载
                  </ElButton>
                </div>
                <div v-if="operationIssues.config" class="section-error">
                  <div>
                    <strong>{{ operationIssues.config.title }}</strong>
                    <span>{{ operationIssues.config.message }}</span>
                  </div>
                  <ElButton
                    size="small"
                    type="primary"
                    plain
                    :loading="actionLoading === 'config-save'"
                    @click="handleSaveKnowledgeConfig"
                  >
                    重试保存
                  </ElButton>
                </div>
                <ElForm label-position="top" class="config-form">
                  <ElFormItem label="Embedding 模型">
                    <ElInput v-model="knowledgeConfig.embeddingModel" />
                  </ElFormItem>
                  <ElFormItem label="切片长度">
                    <ElInputNumber v-model="knowledgeConfig.chunkSize" :min="200" :max="2000" />
                  </ElFormItem>
                  <ElFormItem label="切片重叠">
                    <ElInputNumber
                      v-model="knowledgeConfig.chunkOverlap"
                      :min="0"
                      :max="knowledgeConfig.chunkSize - 1"
                    />
                  </ElFormItem>
                  <ElFormItem label="默认 Top K">
                    <ElInputNumber v-model="knowledgeConfig.topKDefault" :min="1" :max="20" />
                  </ElFormItem>
                  <div class="config-switch-list">
                    <div>
                      <span>重排序</span>
                      <ElSwitch v-model="knowledgeConfig.rerankEnabled" />
                    </div>
                    <div>
                      <span>证据严格模式</span>
                      <ElSwitch v-model="knowledgeConfig.evidenceStrictMode" />
                    </div>
                    <div>
                      <span>自动重建索引</span>
                      <ElSwitch v-model="knowledgeConfig.autoReindex" />
                    </div>
                  </div>
                  <ElFormItem label="审计留存天数">
                    <ElInputNumber v-model="knowledgeConfig.retentionDays" :min="30" :max="3650" />
                  </ElFormItem>
                  <ElButton
                    type="primary"
                    :loading="actionLoading === 'config-save'"
                    @click="handleSaveKnowledgeConfig"
                  >
                    保存配置
                  </ElButton>
                </ElForm>
              </ElCard>
            </ElCol>
            <ElCol :xl="15" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>知识库审计</span>
                    <ElTag effect="plain">{{ auditPagination.total }} 条</ElTag>
                  </div>
                </template>
                <div class="filter-bar">
                  <ElInput
                    v-model="auditFilters.keyword"
                    clearable
                    placeholder="搜索操作、人或对象"
                    @change="handleFilterChange(auditPagination, loadKnowledgeAuditLogs)"
                  />
                  <ElSelect
                    v-model="auditFilters.objectType"
                    clearable
                    placeholder="对象"
                    @change="handleFilterChange(auditPagination, loadKnowledgeAuditLogs)"
                  >
                    <ElOption
                      v-for="item in auditObjectTypeOptions"
                      :key="item"
                      :label="item"
                      :value="item"
                    />
                  </ElSelect>
                  <ElSelect
                    v-model="auditFilters.result"
                    clearable
                    placeholder="结果"
                    @change="handleFilterChange(auditPagination, loadKnowledgeAuditLogs)"
                  >
                    <ElOption label="成功" value="成功" />
                    <ElOption label="失败" value="失败" />
                  </ElSelect>
                  <ElButton @click="loadKnowledgeAuditLogs">刷新</ElButton>
                </div>
                <div v-if="sectionIssues.audit" class="section-error">
                  <div>
                    <strong>{{ sectionIssues.audit.title }}</strong>
                    <span>{{ sectionIssues.audit.message }}</span>
                  </div>
                  <ElButton size="small" type="primary" plain @click="loadKnowledgeAuditLogs">
                    重新加载
                  </ElButton>
                </div>
                <ElTable :data="auditLogs" border height="392" empty-text="当前筛选下暂无审计日志">
                  <ElTableColumn prop="createdAt" label="时间" width="170" />
                  <ElTableColumn prop="actorName" label="人员" width="110" />
                  <ElTableColumn prop="action" label="操作" min-width="160" show-overflow-tooltip />
                  <ElTableColumn prop="objectType" label="对象" width="150" />
                  <ElTableColumn
                    prop="objectId"
                    label="对象 ID"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="结果" width="90">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.result)" effect="light">{{ row.result }}</ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-if="auditPagination.total > auditPagination.pageSize"
                  v-model:current-page="auditPagination.page"
                  v-model:page-size="auditPagination.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="[10, 20, 50]"
                  layout="total, sizes, prev, pager, next"
                  :total="auditPagination.total"
                  @size-change="
                    (size) => handlePageSizeChange(auditPagination, loadKnowledgeAuditLogs, size)
                  "
                  @current-change="
                    (page) => handlePageChange(auditPagination, loadKnowledgeAuditLogs, page)
                  "
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="项目文件知识库" name="files">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>项目文件知识库</span>
                <ElSpace>
                  <ElTag effect="plain">{{ filePagination.total }} 个文件</ElTag>
                  <ElButton type="primary" @click="openCreateSourceDialog('project-file')">
                    上传项目文件
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <div class="filter-bar">
              <ElInput
                v-model="fileFilters.keyword"
                clearable
                placeholder="搜索文件、节点或项目"
                @change="handleFilterChange(filePagination, loadFiles)"
              />
              <ElSelect
                v-model="fileFilters.projectId"
                clearable
                filterable
                placeholder="按项目筛选"
                @change="handleFilterChange(filePagination, loadFiles)"
              >
                <ElOption
                  v-for="project in projectFileProjectOptions"
                  :key="project.id"
                  :label="project.name"
                  :value="project.id"
                >
                  <span>{{ project.name }}</span>
                  <span v-if="project.code" class="select-option-meta">{{ project.code }}</span>
                </ElOption>
              </ElSelect>
              <ElInputNumber
                v-model="fileFilters.nodeId"
                :min="1"
                :max="69"
                controls-position="right"
                placeholder="节点号"
                @change="handleFilterChange(filePagination, loadFiles)"
              />
              <ElSelect
                v-model="fileFilters.status"
                clearable
                placeholder="状态"
                @change="handleFilterChange(filePagination, loadFiles)"
              >
                <ElOption label="待识别" value="待识别" />
                <ElOption label="未识别" value="未识别" />
                <ElOption label="已识别" value="已识别" />
                <ElOption label="识别中" value="识别中" />
                <ElOption label="人工修正" value="人工修正" />
                <ElOption label="已切片" value="已切片" />
                <ElOption label="向量化中" value="向量化中" />
                <ElOption label="已向量化" value="已向量化" />
              </ElSelect>
              <ElButton @click="loadFiles">筛选</ElButton>
            </div>
            <div v-if="sectionIssues.files" class="section-error">
              <div>
                <strong>{{ sectionIssues.files.title }}</strong>
                <span>{{ sectionIssues.files.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadFiles">重新加载</ElButton>
            </div>
            <div v-if="operationIssues.file" class="section-error">
              <div>
                <strong>{{ operationIssues.file.title }}</strong>
                <span>{{ operationIssues.file.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadFiles">刷新文件</ElButton>
            </div>
            <ElTable :data="files" border height="430" empty-text="暂无项目知识文件">
              <ElTableColumn label="项目" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.projectName || '未绑定项目' }}</template>
              </ElTableColumn>
              <ElTableColumn prop="nodeId" label="节点" width="76" />
              <ElTableColumn
                prop="nodeName"
                label="节点名称"
                min-width="220"
                show-overflow-tooltip
              />
              <ElTableColumn prop="fileName" label="文件" min-width="240" show-overflow-tooltip />
              <ElTableColumn label="OCR" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.ocrStatus)" effect="light">{{
                    row.ocrStatus
                  }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="切片" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.sliceStatus)" effect="light">{{
                    row.sliceStatus
                  }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="向量" width="120">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.vectorStatus)" effect="light">{{
                    row.vectorStatus
                  }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="切片/向量" width="120">
                <template #default="{ row }">{{ row.chunkCount }} / {{ row.vectorCount }}</template>
              </ElTableColumn>
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
              <ElTableColumn label="操作" width="320" fixed="right">
                <template #default="{ row }">
                  <div class="standard-file-actions">
                    <ElButton link type="primary" @click="handleOpenFile(row)">详情</ElButton>
                    <ElButton link type="primary" @click="openEditStandardFileDialog(row)">
                      编辑
                    </ElButton>
                    <ElButton link type="primary" @click="openReplaceStandardFileDialog(row)">
                      替换版本
                    </ElButton>
                    <ElButton
                      link
                      type="primary"
                      :loading="actionLoading === `file-${row.id}`"
                      @click="handleReindexFile(row)"
                    >
                      重建索引
                    </ElButton>
                    <ElPopconfirm
                      title="确认删除这个项目文件？"
                      confirm-button-text="删除"
                      cancel-button-text="取消"
                      @confirm="handleDeleteStandardFile(row)"
                    >
                      <template #reference>
                        <ElButton
                          link
                          type="danger"
                          :loading="actionLoading === `file-delete-${row.id}`"
                        >
                          删除
                        </ElButton>
                      </template>
                    </ElPopconfirm>
                  </div>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-if="filePagination.total > filePagination.pageSize"
              v-model:current-page="filePagination.page"
              v-model:page-size="filePagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="filePagination.total"
              @size-change="(size) => handlePageSizeChange(filePagination, loadFiles, size)"
              @current-change="(page) => handlePageChange(filePagination, loadFiles, page)"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="任务中心" name="tasks">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>OCR / 切片 / 向量任务</span>
                <ElTag effect="plain">{{ taskPagination.total }} 条</ElTag>
              </div>
            </template>
            <div class="filter-bar">
              <ElSelect
                v-model="taskFilters.taskType"
                clearable
                placeholder="任务类型"
                @change="handleFilterChange(taskPagination, loadTasks)"
              >
                <ElOption label="OCR" value="ocr" />
                <ElOption label="切片" value="slice" />
                <ElOption label="向量" value="vector" />
                <ElOption label="重建索引" value="reindex" />
              </ElSelect>
              <ElSelect
                v-model="taskFilters.status"
                clearable
                placeholder="状态"
                @change="handleFilterChange(taskPagination, loadTasks)"
              >
                <ElOption label="排队中" value="排队中" />
                <ElOption label="运行中" value="运行中" />
                <ElOption label="成功" value="成功" />
                <ElOption label="失败" value="失败" />
                <ElOption label="已取消" value="已取消" />
              </ElSelect>
              <ElButton @click="loadTasks">刷新</ElButton>
            </div>
            <div v-if="sectionIssues.tasks" class="section-error">
              <div>
                <strong>{{ sectionIssues.tasks.title }}</strong>
                <span>{{ sectionIssues.tasks.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadTasks">重新加载</ElButton>
            </div>
            <div v-if="operationIssues.task" class="section-error">
              <div>
                <strong>{{ operationIssues.task.title }}</strong>
                <span>{{ operationIssues.task.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadTasks">刷新任务</ElButton>
            </div>
            <ElTable :data="tasks" border height="430" empty-text="暂无 OCR 或向量任务">
              <ElTableColumn prop="id" label="任务号" width="170" />
              <ElTableColumn label="类型" width="110">
                <template #default="{ row }">{{ taskTypeLabel(row.taskType) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="targetName" label="目标" min-width="240" show-overflow-tooltip />
              <ElTableColumn label="状态" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="进度" min-width="150">
                <template #default="{ row }">
                  <ElProgress :percentage="row.progress" :stroke-width="8" />
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="errorMessage"
                label="错误"
                min-width="260"
                show-overflow-tooltip
              />
              <ElTableColumn prop="createdAt" label="创建时间" width="170" />
              <ElTableColumn prop="finishedAt" label="结束时间" width="170" />
              <ElTableColumn label="操作" width="140" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    v-if="['失败', '已取消'].includes(row.status)"
                    link
                    type="primary"
                    :loading="actionLoading === `retry-${row.id}`"
                    @click="handleRetryTask(row)"
                  >
                    重试
                  </ElButton>
                  <ElButton
                    v-if="row.status === '排队中'"
                    link
                    type="danger"
                    :loading="actionLoading === `cancel-${row.id}`"
                    @click="handleCancelTask(row)"
                  >
                    取消
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-if="taskPagination.total > taskPagination.pageSize"
              v-model:current-page="taskPagination.page"
              v-model:page-size="taskPagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="taskPagination.total"
              @size-change="(size) => handlePageSizeChange(taskPagination, loadTasks, size)"
              @current-change="(page) => handlePageChange(taskPagination, loadTasks, page)"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="检索测试" name="retrieval">
          <ElRow :gutter="16">
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>知识检索测试</span>
                    <ElTag type="warning" effect="plain">不写入审查结论</ElTag>
                  </div>
                </template>
                <ElForm label-position="top">
                  <ElFormItem label="问题">
                    <ElInput
                      v-model="retrievalForm.question"
                      type="textarea"
                      :rows="4"
                      maxlength="300"
                      show-word-limit
                    />
                  </ElFormItem>
                  <ElFormItem label="范围">
                    <ElCheckboxGroup v-model="retrievalForm.scope">
                      <ElCheckbox label="standard">标准规范</ElCheckbox>
                      <ElCheckbox label="project-file">项目文件</ElCheckbox>
                    </ElCheckboxGroup>
                  </ElFormItem>
                  <ElFormItem label="Top K">
                    <ElInputNumber v-model="retrievalForm.topK" :min="1" :max="10" />
                  </ElFormItem>
                  <ElButton type="primary" :loading="retrievalLoading" @click="handleRunRetrieval">
                    运行检索
                  </ElButton>
                </ElForm>
                <div v-if="operationIssues.retrieval" class="section-error local-operation-error">
                  <div>
                    <strong>{{ operationIssues.retrieval.title }}</strong>
                    <span>{{ operationIssues.retrieval.message }}</span>
                  </div>
                  <ElButton
                    size="small"
                    type="primary"
                    plain
                    :loading="retrievalLoading"
                    @click="handleRunRetrieval"
                  >
                    重试检索
                  </ElButton>
                </div>
                <ElDivider />
                <div class="panel-header compact">
                  <span>PageIndex 树节点</span>
                  <ElTag effect="plain">{{ pageIndexNodes.length }} 个</ElTag>
                </div>
                <div v-if="operationIssues.pageIndex" class="section-error local-operation-error">
                  <div>
                    <strong>{{ operationIssues.pageIndex.title }}</strong>
                    <span>{{ operationIssues.pageIndex.message }}</span>
                  </div>
                  <ElButton
                    size="small"
                    type="primary"
                    plain
                    :loading="pageIndexLoading"
                    @click="loadPageIndexNodes()"
                  >
                    重试
                  </ElButton>
                </div>
                <ElTable
                  v-else
                  v-loading="pageIndexLoading"
                  :data="pageIndexNodes"
                  border
                  height="220"
                  class="page-index-table"
                >
                  <ElTableColumn prop="title" label="节点" min-width="180" show-overflow-tooltip />
                  <ElTableColumn label="页码" width="86">
                    <template #default="{ row }">{{ formatPageRange(row) }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="条款" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">{{
                      formatTextList(row.linkedClauseIds)
                    }}</template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel retrieval-result">
                <template #header>
                  <div class="panel-header">
                    <span>检索结果</span>
                    <ElTag v-if="retrievalResult" type="info" effect="plain">
                      {{ retrievalResult.latencyMs }} ms
                    </ElTag>
                  </div>
                </template>
                <ElEmpty v-if="!retrievalResult" description="运行检索后显示答案草稿和证据命中" />
                <template v-else>
                  <ElAlert
                    title="答案草稿"
                    type="success"
                    :description="retrievalResult.answerDraft"
                    :closable="false"
                    show-icon
                  />
                  <ElDivider />
                  <ElDescriptions v-if="retrievalTrace" :column="3" border size="small">
                    <ElDescriptionsItem label="路由">
                      {{ routeLabel(retrievalTrace.selectedRoute) }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="Router">
                      {{ retrievalTrace.routerVersion || '--' }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="PageIndex 候选">
                      {{ retrievalPageIndexTree?.candidateNodeCount || 0 }}
                    </ElDescriptionsItem>
                    <ElDescriptionsItem label="关联条款" :span="3">
                      {{ formatTextList(retrievalPageIndexTree?.linkedClauseIds) }}
                    </ElDescriptionsItem>
                  </ElDescriptions>
                  <template v-if="retrievalPageIndexNodes.length">
                    <ElDivider />
                    <div class="subsection-title">PageIndex 命中节点</div>
                    <ElTable :data="retrievalPageIndexNodes" border height="180">
                      <ElTableColumn
                        prop="title"
                        label="节点"
                        min-width="180"
                        show-overflow-tooltip
                      />
                      <ElTableColumn label="页码" width="86">
                        <template #default="{ row }">{{ formatPageRange(row) }}</template>
                      </ElTableColumn>
                      <ElTableColumn label="分数" width="90">
                        <template #default="{ row }">
                          {{ typeof row.score === 'number' ? row.score.toFixed(2) : '--' }}
                        </template>
                      </ElTableColumn>
                      <ElTableColumn label="条款" min-width="180" show-overflow-tooltip>
                        <template #default="{ row }">{{
                          formatTextList(row.linkedClauseIds)
                        }}</template>
                      </ElTableColumn>
                    </ElTable>
                  </template>
                  <template v-if="retrievalTreePathRows.length">
                    <ElDivider />
                    <div class="subsection-title">树检索路径</div>
                    <ElTable :data="retrievalTreePathRows" border height="160">
                      <ElTableColumn
                        prop="pageIndexNodeId"
                        label="节点ID"
                        width="180"
                        show-overflow-tooltip
                      />
                      <ElTableColumn
                        prop="title"
                        label="路径节点"
                        min-width="220"
                        show-overflow-tooltip
                      />
                    </ElTable>
                  </template>
                  <ElDivider />
                  <ElTable :data="retrievalResult.hits" border height="250">
                    <ElTableColumn prop="objectType" label="对象" width="140" />
                    <ElTableColumn
                      prop="fileName"
                      label="文件"
                      min-width="180"
                      show-overflow-tooltip
                    />
                    <ElTableColumn prop="pageNo" label="页码" width="80" />
                    <ElTableColumn prop="fieldName" label="字段" width="120" />
                    <ElTableColumn
                      prop="quotedText"
                      label="命中文本"
                      min-width="260"
                      show-overflow-tooltip
                    />
                    <ElTableColumn label="置信度" width="100">
                      <template #default="{ row }">{{
                        confidencePercent(row.confidence)
                      }}</template>
                    </ElTableColumn>
                  </ElTable>
                  <div class="index-version-list">
                    <ElTag
                      v-for="version in retrievalResult.usedIndexVersions"
                      :key="version"
                      effect="plain"
                    >
                      {{ version }}
                    </ElTag>
                  </div>
                </template>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="推理日志" name="reasoning">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>推理链路历史</span>
                <ElTag effect="plain">{{ reasoningPagination.total }} 条</ElTag>
              </div>
            </template>
            <div class="filter-bar">
              <ElInputNumber
                v-model="reasoningFilters.nodeId"
                :min="1"
                :max="69"
                controls-position="right"
                placeholder="节点号"
                @change="handleFilterChange(reasoningPagination, loadReasoningLogs)"
              />
              <ElSelect
                v-model="reasoningFilters.status"
                clearable
                placeholder="状态"
                @change="handleFilterChange(reasoningPagination, loadReasoningLogs)"
              >
                <ElOption label="推理中" value="推理中" />
                <ElOption label="完成" value="完成" />
                <ElOption label="失败" value="失败" />
                <ElOption label="已人工确认" value="已人工确认" />
              </ElSelect>
              <ElButton @click="loadReasoningLogs">刷新</ElButton>
            </div>
            <div v-if="sectionIssues.reasoning" class="section-error">
              <div>
                <strong>{{ sectionIssues.reasoning.title }}</strong>
                <span>{{ sectionIssues.reasoning.message }}</span>
              </div>
              <ElButton size="small" type="primary" plain @click="loadReasoningLogs">
                重新加载
              </ElButton>
            </div>
            <ElTable :data="reasoningLogs" border height="430" empty-text="暂无推理日志">
              <ElTableColumn prop="id" label="Run ID" width="190" />
              <ElTableColumn prop="nodeId" label="节点" width="76" />
              <ElTableColumn prop="subject" label="主题" min-width="220" show-overflow-tooltip />
              <ElTableColumn prop="model" label="模型" width="110" />
              <ElTableColumn
                prop="promptVersion"
                label="Prompt"
                min-width="170"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="ruleVersion"
                label="规则版本"
                min-width="190"
                show-overflow-tooltip
              />
              <ElTableColumn label="状态" width="110">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="建议" min-width="260" show-overflow-tooltip>
                <template #default="{ row }">{{ row.suggestion?.opinionDraft }}</template>
              </ElTableColumn>
              <ElTableColumn prop="finishedAt" label="完成时间" width="170" />
              <ElTableColumn label="操作" width="90" fixed="right">
                <template #default="{ row }">
                  <ElButton link type="primary" @click="handleOpenReasoningLog(row)">详情</ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-if="reasoningPagination.total > reasoningPagination.pageSize"
              v-model:current-page="reasoningPagination.page"
              v-model:page-size="reasoningPagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="reasoningPagination.total"
              @size-change="
                (size) => handlePageSizeChange(reasoningPagination, loadReasoningLogs, size)
              "
              @current-change="
                (page) => handlePageChange(reasoningPagination, loadReasoningLogs, page)
              "
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="多模型对比" name="compare">
          <ElRow :gutter="16">
            <ElCol :xl="10" :lg="10" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>对比输入</span>
                    <ElTag type="info" effect="plain">实验区</ElTag>
                  </div>
                </template>
                <ElForm label-position="top">
                  <ElFormItem label="问题">
                    <ElInput
                      v-model="compareForm.question"
                      type="textarea"
                      :rows="4"
                      maxlength="300"
                      show-word-limit
                    />
                  </ElFormItem>
                  <ElFormItem label="节点">
                    <ElInputNumber v-model="compareForm.nodeId" :min="1" :max="69" />
                  </ElFormItem>
                  <ElFormItem label="模型">
                    <ElCheckboxGroup v-model="compareForm.modelCodes">
                      <ElCheckbox v-for="model in modelOptions" :key="model" :label="model">
                        {{ model }}
                      </ElCheckbox>
                    </ElCheckboxGroup>
                  </ElFormItem>
                  <ElButton type="primary" :loading="compareLoading" @click="handleRunCompare">
                    开始对比
                  </ElButton>
                </ElForm>
                <div v-if="operationIssues.compare" class="section-error local-operation-error">
                  <div>
                    <strong>{{ operationIssues.compare.title }}</strong>
                    <span>{{ operationIssues.compare.message }}</span>
                  </div>
                  <ElButton
                    size="small"
                    type="primary"
                    plain
                    :loading="compareLoading"
                    @click="handleRunCompare"
                  >
                    重试对比
                  </ElButton>
                </div>

                <ElDivider />
                <div v-if="sectionIssues.compare" class="section-error">
                  <div>
                    <strong>{{ sectionIssues.compare.title }}</strong>
                    <span>{{ sectionIssues.compare.message }}</span>
                  </div>
                  <ElButton size="small" type="primary" plain @click="loadCompareRuns">
                    重新加载
                  </ElButton>
                </div>
                <div class="compare-history">
                  <div
                    v-for="run in compareRuns"
                    :key="run.runId"
                    class="compare-history-item"
                    @click="handleOpenCompareRun(run)"
                  >
                    <strong>{{ run.question }}</strong>
                    <span>{{ run.modelCodes.join(' / ') }} · {{ run.createdAt }}</span>
                  </div>
                </div>
              </ElCard>
            </ElCol>
            <ElCol :xl="14" :lg="14" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel compare-result" v-loading="compareLoading">
                <template #header>
                  <div class="panel-header">
                    <span>对比结果</span>
                    <ElSpace v-if="compareResult">
                      <ElTag effect="plain">{{ compareResult.runId }}</ElTag>
                      <ElTag
                        :type="
                          compareResult.status === '失败'
                            ? 'danger'
                            : compareResult.status === '完成'
                              ? 'success'
                              : 'warning'
                        "
                        effect="light"
                      >
                        {{ compareResult.status || '完成' }}
                      </ElTag>
                    </ElSpace>
                  </div>
                </template>
                <ElEmpty v-if="!compareResult" description="运行或选择历史对比后显示结果" />
                <div v-else class="model-result-list">
                  <div
                    v-for="item in compareDisplayResults"
                    :key="item.modelCode"
                    class="model-result-item"
                  >
                    <div class="model-result-head">
                      <strong>{{ item.modelCode }}</strong>
                      <ElTag
                        :type="
                          typeof item.confidence === 'number' && item.confidence >= 0.85
                            ? 'success'
                            : 'warning'
                        "
                        effect="light"
                      >
                        {{ confidencePercent(item.confidence) }}
                      </ElTag>
                    </div>
                    <p>{{ item.answer }}</p>
                    <span
                      >{{ item.latencyMs }} ms · 证据 {{ item.evidenceLinkIds.join(', ') }}</span
                    >
                  </div>
                </div>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>
      </ElTabs>

      <ElDialog
        v-model="sourceDialogVisible"
        :title="
          sourceDialogMode === 'create'
            ? sourceDialogContext === 'standard-file'
              ? '上传标准规范文件'
              : sourceDialogContext === 'project-file'
                ? '上传项目文件'
                : '新增知识源'
            : '编辑标准源'
        "
        width="min(780px, 94vw)"
      >
        <ElForm label-position="top" class="source-form">
          <div v-if="operationIssues.source" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.source.title }}</strong>
              <span>{{ operationIssues.source.message }}</span>
            </div>
            <ElButton
              size="small"
              type="primary"
              plain
              :loading="actionLoading === 'source-save'"
              @click="handleSaveSource"
            >
              重试保存
            </ElButton>
          </div>
          <template v-if="sourceDialogContext === 'source'">
            <ElFormItem label="类别名称">
              <ElInput
                v-model="sourceForm.name"
                maxlength="80"
                show-word-limit
                placeholder="默认为标准规范库"
              />
            </ElFormItem>
            <ElFormItem label="类型">
              <ElSelect v-model="sourceForm.sourceType">
                <ElOption label="标准规范" value="standard" />
                <ElOption label="项目文件" value="project-file" />
                <ElOption label="人工维护" value="manual" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="版本">
              <ElInput v-model="sourceForm.version" placeholder="例如 rules-standards-20260703" />
            </ElFormItem>
          </template>
          <template v-if="sourceDialogMode === 'create'">
            <ElFormItem v-if="sourceDialogContext === 'project-file'" label="所属项目">
              <ElSelect
                v-model="sourceUploadProjectId"
                filterable
                placeholder="选择项目"
                class="full-width-control"
              >
                <ElOption
                  v-for="project in projectFileProjectOptions"
                  :key="project.id"
                  :label="project.name"
                  :value="project.id"
                >
                  <span>{{ project.name }}</span>
                  <span v-if="project.code" class="select-option-meta">{{ project.code }}</span>
                </ElOption>
              </ElSelect>
            </ElFormItem>
            <ElFormItem
              :label="
                sourceDialogContext === 'standard-file'
                  ? '标准规范文件'
                  : sourceDialogContext === 'project-file'
                    ? '项目文件'
                    : '上传文件'
              "
            >
              <div class="source-upload-panel">
                <div class="knowledge-import-toolbar source-upload-toolbar">
                  <ElButton type="primary" plain @click="triggerSourceUploadFileSelect">
                    选择文件
                  </ElButton>
                  <ElButton type="primary" plain @click="triggerSourceUploadDirectorySelect">
                    选择文件夹
                  </ElButton>
                  <ElButton :disabled="!sourceUploadFiles.length" @click="clearSourceUploadFiles">
                    清空
                  </ElButton>
                  <ElTag effect="plain">{{ sourceUploadFiles.length }} 个待上传</ElTag>
                </div>
                <input
                  ref="sourceUploadFileInputRef"
                  class="hidden-file-input"
                  type="file"
                  multiple
                  accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.md,.txt"
                  @change="handleSourceUploadInputChange"
                />
                <input
                  ref="sourceUploadDirectoryInputRef"
                  class="hidden-file-input"
                  type="file"
                  multiple
                  webkitdirectory
                  directory
                  @change="handleSourceUploadInputChange"
                />
                <div v-if="!sourceUploadFiles.length" class="source-upload-empty">
                  尚未选择文件
                </div>
                <div v-for="row in sourceUploadFiles" :key="row.id" class="source-upload-row">
                  <div class="source-upload-row-head">
                    <span>{{ row.relativePath }}</span>
                    <ElButton link type="danger" @click="removeSourceUploadFile(row.id)">
                      移除
                    </ElButton>
                  </div>
                  <div class="source-upload-grid">
                    <label class="source-upload-field">
                      <span>文件名称</span>
                      <ElInput v-model="row.fileName" maxlength="180" show-word-limit />
                    </label>
                    <label class="source-upload-field">
                      <span>上下文描述</span>
                      <ElInput
                        v-model="row.contextDescription"
                        type="textarea"
                        :rows="2"
                        maxlength="500"
                        show-word-limit
                        placeholder="例如适用标准、业务节点、资料来源或检索上下文"
                      />
                    </label>
                  </div>
                  <div class="source-upload-meta">
                    <span>{{ formatFileSize(row.size) }}</span>
                    <span>{{ row.type }}</span>
                  </div>
                </div>
              </div>
            </ElFormItem>
          </template>
          <template v-if="sourceDialogContext === 'source'">
            <ElRow :gutter="12">
              <ElCol :span="12">
                <ElFormItem label="状态">
                  <ElSelect v-model="sourceForm.status">
                    <ElOption
                      v-for="status in sourceStatusOptions"
                      :key="status"
                      :label="status"
                      :value="status"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :span="12">
                <ElFormItem label="向量状态">
                  <ElSelect v-model="sourceForm.vectorStatus">
                    <ElOption
                      v-for="status in vectorStatusOptions"
                      :key="status"
                      :label="status"
                      :value="status"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElRow :gutter="12">
              <ElCol :span="12">
                <ElFormItem label="文件数">
                  <ElInputNumber v-model="sourceForm.fileCount" :min="0" />
                </ElFormItem>
              </ElCol>
              <ElCol :span="12">
                <ElFormItem label="切片数">
                  <ElInputNumber v-model="sourceForm.chunkCount" :min="0" />
                </ElFormItem>
              </ElCol>
            </ElRow>
          </template>
        </ElForm>
        <template #footer>
          <ElButton @click="sourceDialogVisible = false">取消</ElButton>
          <ElButton
            type="primary"
            :loading="actionLoading === 'source-save'"
            @click="handleSaveSource"
          >
            保存
          </ElButton>
        </template>
      </ElDialog>

      <ElDialog
        v-model="standardFileDialogVisible"
        :title="knowledgeFileDialogTitle"
        width="min(680px, 94vw)"
      >
        <ElForm label-position="top" class="source-form">
          <div v-if="operationIssues.file" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.file.title }}</strong>
              <span>{{ operationIssues.file.message }}</span>
            </div>
          </div>
          <ElFormItem :label="`${currentKnowledgeFileKind}名称`">
            <ElInput v-model="standardFileForm.fileName" maxlength="180" show-word-limit />
          </ElFormItem>
          <ElFormItem v-if="isProjectKnowledgeFile(standardFileEditing)" label="所属项目">
            <ElSelect
              v-model="standardFileForm.projectId"
              filterable
              placeholder="选择项目"
              class="full-width-control"
            >
              <ElOption
                v-for="project in projectFileProjectOptions"
                :key="project.id"
                :label="project.name"
                :value="project.id"
              >
                <span>{{ project.name }}</span>
                <span v-if="project.code" class="select-option-meta">{{ project.code }}</span>
              </ElOption>
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="来源路径">
            <ElInput
              v-model="standardFileForm.sourceRelativePath"
              maxlength="240"
              show-word-limit
            />
          </ElFormItem>
          <ElFormItem label="上下文描述">
            <ElInput
              v-model="standardFileForm.contextDescription"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
            />
          </ElFormItem>
          <ElFormItem v-if="standardFileDialogMode === 'replace'" label="新版本文件">
            <div class="standard-file-replace-panel">
              <input
                ref="standardFileReplaceInputRef"
                class="hidden-file-input"
                type="file"
                accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.md,.txt"
                @change="handleStandardFileReplaceInputChange"
              />
              <ElButton type="primary" plain @click="triggerStandardFileReplaceSelect">
                选择文件
              </ElButton>
              <span v-if="standardFileReplacement">
                {{ standardFileReplacement.name }} ·
                {{ formatFileSize(standardFileReplacement.size) }}
              </span>
              <span v-else>尚未选择文件</span>
            </div>
          </ElFormItem>
        </ElForm>
        <template #footer>
          <ElButton @click="standardFileDialogVisible = false">取消</ElButton>
          <ElButton
            type="primary"
            :loading="actionLoading === 'standard-file-save'"
            @click="handleSaveStandardFile"
          >
            保存
          </ElButton>
        </template>
      </ElDialog>

      <ElDialog
        v-model="knowledgeImportVisible"
        :title="knowledgeImportDialogTitle"
        width="min(760px, 94vw)"
      >
        <ElForm label-position="top" class="source-form">
          <div v-if="operationIssues.import" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.import.title }}</strong>
              <span>{{ operationIssues.import.message }}</span>
            </div>
            <ElButton
              size="small"
              type="primary"
              plain
              :loading="actionLoading === 'knowledge-import'"
              @click="handleImportKnowledgeFiles"
            >
              重试导入
            </ElButton>
          </div>
          <ElFormItem label="草稿版本号">
            <ElInput
              v-model="businessRuleImportVersion"
              maxlength="80"
              show-word-limit
              placeholder="例如 rule-draft-20260702-0930"
            />
          </ElFormItem>
          <div class="knowledge-import-toolbar">
            <ElButton type="primary" plain @click="triggerKnowledgeImportFileSelect">
              选择文件
            </ElButton>
            <ElButton type="primary" plain @click="triggerKnowledgeImportDirectorySelect">
              选择文件夹
            </ElButton>
            <ElButton :disabled="!knowledgeImportFiles.length" @click="clearKnowledgeImportFiles">
              清空
            </ElButton>
            <ElTag effect="plain">{{ knowledgeImportFiles.length }} 个待导入</ElTag>
          </div>
          <input
            ref="knowledgeImportFileInputRef"
            class="hidden-file-input"
            type="file"
            multiple
            accept=".docx,.md,.markdown,.txt,.yaml,.yml,.json"
            @change="handleKnowledgeImportInputChange"
          />
          <input
            ref="knowledgeImportDirectoryInputRef"
            class="hidden-file-input"
            type="file"
            multiple
            webkitdirectory
            directory
            @change="handleKnowledgeImportInputChange"
          />
          <ElTable
            :data="knowledgeImportFileRows"
            border
            height="280"
            empty-text="请选择 Word、Markdown、YAML、JSON 或 TXT 格式业务规则文件"
          >
            <ElTableColumn prop="name" label="文件名" min-width="220" show-overflow-tooltip />
            <ElTableColumn
              prop="relativePath"
              label="相对路径"
              min-width="260"
              show-overflow-tooltip
            />
            <ElTableColumn label="大小" width="110">
              <template #default="{ row }">{{ formatFileSize(row.size) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="type" label="类型" width="110" show-overflow-tooltip />
            <ElTableColumn label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <ElButton link type="danger" @click="removeKnowledgeImportFile(row.id)">
                  移除
                </ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </ElForm>
        <template #footer>
          <ElButton @click="knowledgeImportVisible = false">取消</ElButton>
          <ElButton
            type="primary"
            :disabled="!knowledgeImportFiles.length"
            :loading="actionLoading === 'knowledge-import'"
            @click="handleImportKnowledgeFiles"
          >
            开始导入
          </ElButton>
        </template>
      </ElDialog>

      <ElDrawer
        v-model="ruleEditorVisible"
        :title="ruleEditorMode === 'create' ? '新增业务规则' : '编辑业务规则草稿'"
        size="min(860px, 96vw)"
      >
        <div class="drawer-content rule-editor-drawer">
          <div v-if="operationIssues.rule" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.rule.title }}</strong>
              <span>{{ operationIssues.rule.message }}</span>
            </div>
          </div>
          <ElForm label-position="top" class="rule-editor-form">
            <ElRow :gutter="16">
              <ElCol :xl="16" :lg="16" :md="24" :sm="24" :xs="24">
                <ElFormItem label="监检项目节点">
                  <ElTreeSelect
                    v-model="ruleNodeSelectValue"
                    :data="ruleNodeSelectOptions"
                    :props="ruleNodeTreeProps"
                    node-key="value"
                    filterable
                    clearable
                    default-expand-all
                    :render-after-expand="false"
                    :loading="ruleNodeTreeLoading"
                    :empty-text="ruleNodeTreeLoading ? '加载中' : '暂无节点'"
                    placeholder="请选择监检项目节点"
                    @change="handleRuleNodeSelectChange"
                  />
                </ElFormItem>
              </ElCol>
              <ElCol :xl="8" :lg="8" :md="12" :sm="24" :xs="24">
                <ElFormItem label="类别">
                  <ElSelect v-model="ruleForm.inspectionClass" placeholder="类别">
                    <ElOption
                      v-for="item in ruleClassOptions"
                      :key="item"
                      :label="item"
                      :value="item"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :xl="6" :lg="6" :md="8" :sm="24" :xs="24">
                <ElFormItem label="序号">
                  <ElInput
                    :model-value="ruleForm.sourceSequence || ''"
                    disabled
                    placeholder="选择节点后自动带出"
                  />
                </ElFormItem>
              </ElCol>
              <ElCol :xl="9" :lg="9" :md="8" :sm="24" :xs="24">
                <ElFormItem label="监检项目（大类）">
                  <ElInput
                    :model-value="ruleForm.inspectionCategory || ''"
                    disabled
                    placeholder="选择节点后自动带出"
                  />
                </ElFormItem>
              </ElCol>
              <ElCol :xl="9" :lg="9" :md="8" :sm="24" :xs="24">
                <ElFormItem label="监检项目（内容）">
                  <ElInput
                    :model-value="ruleForm.inspectionItem || ''"
                    disabled
                    placeholder="选择节点后自动带出"
                  />
                </ElFormItem>
              </ElCol>
              <ElCol :xl="6" :lg="6" :md="8" :sm="24" :xs="24">
                <ElFormItem label="来源规则">
                  <ElInput :model-value="ruleForm.sourceRuleId || ''" disabled />
                </ElFormItem>
              </ElCol>
              <ElCol :xl="18" :lg="18" :md="16" :sm="24" :xs="24">
                <ElFormItem label="来源文档">
                  <ElInput :model-value="ruleForm.sourceDocument || ''" disabled />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="判断准则 / 标准规范">
              <ElInput
                v-model="ruleForm.standardText"
                type="textarea"
                :rows="6"
                maxlength="3000"
                show-word-limit
              />
            </ElFormItem>
            <ElFormItem label="方法及内容 / 工作见证">
              <ElInput
                v-model="ruleForm.witnessText"
                type="textarea"
                :rows="8"
                maxlength="3000"
                show-word-limit
              />
            </ElFormItem>
            <ElFormItem label="Agent 思考方式">
              <ElInput
                v-model="ruleForm.agentThinking"
                type="textarea"
                :rows="5"
                maxlength="3000"
                show-word-limit
              />
            </ElFormItem>
            <ElFormItem label="工具集调用思考">
              <ElInput
                v-model="ruleForm.toolchainThinking"
                type="textarea"
                :rows="5"
                maxlength="3000"
                show-word-limit
              />
            </ElFormItem>
            <ElFormItem label="引用标准文件">
              <ElInput
                :model-value="formatRuleReferencedStandards(ruleForm.referencedStandards)"
                type="textarea"
                :rows="3"
                readonly
              />
            </ElFormItem>
            <ElFormItem label="AI 解析版结构化规则">
              <ElInput
                :model-value="formatRuleExecution(ruleForm.aiExecution)"
                type="textarea"
                :rows="8"
                readonly
              />
            </ElFormItem>
          </ElForm>
          <ElDivider />
          <ElDescriptions :column="2" border size="small">
            <ElDescriptionsItem label="草稿 ID">
              {{ ruleEditingId || '保存后生成' }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="适用节点">
              {{ formatTextList((ruleForm.nodeIds || []).map(String)) }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="AI 执行结构" :span="2">
              {{
                ruleEditingSource?.aiExecution?.compiledAt
                  ? `已生成：${ruleEditingSource.aiExecution.compiledAt}`
                  : '保存或发布时生成'
              }}
            </ElDescriptionsItem>
          </ElDescriptions>
        </div>
        <template #footer>
          <ElButton @click="ruleEditorVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="actionLoading === 'rule-save'" @click="handleSaveRule">
            保存草稿
          </ElButton>
        </template>
      </ElDrawer>

      <ElDrawer v-model="ruleDiffVisible" title="规则版本差异" size="min(760px, 94vw)">
        <div v-loading="ruleDiffLoading" class="drawer-content rule-diff-drawer">
          <div v-if="operationIssues.ruleDiff" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.ruleDiff.title }}</strong>
              <span>{{ operationIssues.ruleDiff.message }}</span>
            </div>
            <ElButton
              size="small"
              type="primary"
              plain
              :loading="ruleDiffLoading"
              @click="retryRuleDiff"
            >
              重新加载
            </ElButton>
          </div>
          <ElEmpty v-if="!ruleDiff && !operationIssues.ruleDiff" description="暂无规则差异" />
          <template v-if="ruleDiff">
            <ElDescriptions :column="1" border>
              <ElDescriptionsItem label="当前版本">{{ ruleDiff.base.version }}</ElDescriptionsItem>
              <ElDescriptionsItem label="对比版本">{{
                ruleDiff.target.version
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="规则">{{ ruleDiff.base.name }}</ElDescriptionsItem>
              <ElDescriptionsItem label="对比时间">{{ ruleDiff.comparedAt }}</ElDescriptionsItem>
            </ElDescriptions>

            <div class="rule-diff-summary">
              <div v-for="item in ruleDiffSummaryItems" :key="item.label" class="rule-diff-metric">
                <span>{{ item.label }}</span>
                <strong>
                  {{ item.value }}
                  <small>项</small>
                </strong>
              </div>
            </div>

            <ElTable
              :data="ruleDiff.changes"
              border
              height="360"
              empty-text="当前对比未发现字段差异"
            >
              <ElTableColumn prop="label" label="字段" width="130" />
              <ElTableColumn label="类型" width="96">
                <template #default="{ row }">
                  <ElTag :type="diffChangeTagType(row.changeType)" effect="light">
                    {{ diffChangeTypeLabel(row.changeType) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="基线值" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="diff-value">{{ formatDiffValue(row.before) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="当前值" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="diff-value">{{ formatDiffValue(row.after) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="关注" width="90">
                <template #default="{ row }">
                  <ElTag :type="row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                    {{ row.severity === 'warning' ? '需关注' : '信息' }}
                  </ElTag>
                </template>
              </ElTableColumn>
            </ElTable>
          </template>
        </div>
      </ElDrawer>

      <ElDrawer v-model="fileDrawerVisible" title="文件知识详情" size="58%">
        <div v-loading="fileDetailLoading" class="drawer-content">
          <div v-if="operationIssues.fileDetail" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.fileDetail.title }}</strong>
              <span>{{ operationIssues.fileDetail.message }}</span>
            </div>
          </div>
          <ElEmpty v-if="!fileDetail && !operationIssues.fileDetail" description="暂无文件详情" />
          <template v-if="fileDetail">
            <ElDescriptions :column="2" border>
              <ElDescriptionsItem label="文件">{{ fileDetail.file.fileName }}</ElDescriptionsItem>
              <ElDescriptionsItem label="项目">{{
                fileDetail.file.projectName || '-'
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="节点">
                {{ fileDetail.file.nodeId || '-' }} {{ fileDetail.file.nodeName || '' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="版本">
                {{ fileDetail.currentVersion?.versionNo || '-' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="OCR">
                <ElTag :type="statusType(fileDetail.file.ocrStatus)" effect="light">
                  {{ fileDetail.file.ocrStatus }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="向量">
                <ElTag :type="statusType(fileDetail.vectorSummary.vectorStatus)" effect="light">
                  {{ fileDetail.vectorSummary.vectorStatus }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="索引版本">
                {{ fileDetail.vectorSummary.indexVersion }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="维度">
                {{ fileDetail.vectorSummary.dimensions }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="来源路径">
                {{
                  fileDetail.file.sourceRelativePath || fileDetail.file.contextDescription || '-'
                }}
              </ElDescriptionsItem>
            </ElDescriptions>

            <div class="file-original-panel">
              <div>
                <strong>文档原文</strong>
                <span>
                  {{
                    fileDetail.preview?.contentType || fileDetail.document?.fileType || '原始文件'
                  }}
                  <template v-if="fileDetail.download?.expiresAt">
                    · 有效期至 {{ fileDetail.download.expiresAt }}
                  </template>
                </span>
              </div>
              <ElSpace>
                <ElButton
                  type="primary"
                  plain
                  :disabled="!fileDetail.preview?.url"
                  @click="openKnowledgeFileOriginal('preview')"
                >
                  查看原文
                </ElButton>
                <ElButton
                  :disabled="!fileDetail.download?.url"
                  @click="openKnowledgeFileOriginal('download')"
                >
                  下载原文
                </ElButton>
              </ElSpace>
            </div>

            <ElDivider content-position="left">切片</ElDivider>
            <ElAlert
              v-if="!fileChunks.length"
              class="chunk-empty-alert"
              title="尚未生成真实切片"
              description="当前文件没有可审计的切片明细，系统不会展示示例切片。请先完成 OCR/切片任务或重建索引。"
              type="warning"
              show-icon
              :closable="false"
            />
            <ElTable :data="fileChunks" border height="260" empty-text="暂无真实切片">
              <ElTableColumn prop="chunkNo" label="#" width="70" />
              <ElTableColumn prop="pageNo" label="页码" width="80" />
              <ElTableColumn prop="text" label="文本" min-width="360" show-overflow-tooltip />
              <ElTableColumn prop="tokenCount" label="Token" width="90" />
              <ElTableColumn prop="evidenceLinkId" label="证据" width="130" />
            </ElTable>

            <ElDivider content-position="left">推理引用</ElDivider>
            <ElTable :data="fileReferences" border height="220" empty-text="暂无真实推理引用">
              <ElTableColumn prop="runId" label="Run ID" width="180" />
              <ElTableColumn prop="nodeId" label="节点" width="70" />
              <ElTableColumn prop="subject" label="主题" min-width="180" show-overflow-tooltip />
              <ElTableColumn prop="model" label="模型" width="100" />
              <ElTableColumn
                prop="quotedText"
                label="引用文本"
                min-width="260"
                show-overflow-tooltip
              />
              <ElTableColumn prop="createdAt" label="时间" width="170" />
            </ElTable>
          </template>
        </div>
      </ElDrawer>

      <ElDrawer v-model="reasoningDrawerVisible" title="推理链路详情" size="52%">
        <div v-loading="reasoningDetailLoading" class="drawer-content">
          <div v-if="operationIssues.reasoningDetail" class="section-error local-operation-error">
            <div>
              <strong>{{ operationIssues.reasoningDetail.title }}</strong>
              <span>{{ operationIssues.reasoningDetail.message }}</span>
            </div>
          </div>
          <ElEmpty
            v-if="!reasoningDetail && !operationIssues.reasoningDetail"
            description="暂无推理详情"
          />
          <template v-if="reasoningDetail">
            <ElDescriptions :column="2" border>
              <ElDescriptionsItem label="Run ID">{{ reasoningDetail.log.id }}</ElDescriptionsItem>
              <ElDescriptionsItem label="节点">{{ reasoningDetail.log.nodeId }}</ElDescriptionsItem>
              <ElDescriptionsItem label="模型">{{ reasoningDetail.log.model }}</ElDescriptionsItem>
              <ElDescriptionsItem label="状态">
                <ElTag :type="statusType(reasoningDetail.log.status)" effect="light">
                  {{ reasoningDetail.log.status }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="规则版本">
                {{ reasoningDetail.log.ruleVersion }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="Prompt">
                {{ reasoningDetail.log.promptVersion }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="LLM 对话 ID">
                {{
                  reasoningDetail.log.llmConversationId || reasoningMetadataText('conversationId')
                }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="Prompt 模板">
                {{ reasoningPromptTemplateLabel }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="Prompt Hash">
                {{ reasoningMetadataText('promptHash') }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="Response Hash">
                {{ reasoningMetadataText('responseHash') }}
              </ElDescriptionsItem>
            </ElDescriptions>
            <ElDivider content-position="left">Prompt 正文</ElDivider>
            <div class="reasoning-audit-grid">
              <div class="reasoning-audit-block">
                <strong>System Prompt</strong>
                <ElInput
                  :model-value="reasoningPromptText('systemPrompt')"
                  type="textarea"
                  :rows="5"
                  readonly
                />
              </div>
              <div class="reasoning-audit-block">
                <strong>User Prompt</strong>
                <ElInput
                  :model-value="reasoningPromptText('userPrompt')"
                  type="textarea"
                  :rows="8"
                  readonly
                />
              </div>
              <div class="reasoning-audit-block">
                <strong>Plan 编排 Prompt</strong>
                <ElInput
                  :model-value="reasoningPromptText('plannerPrompt')"
                  type="textarea"
                  :rows="4"
                  readonly
                />
              </div>
              <div class="reasoning-audit-block">
                <strong>Critic 复核 Prompt</strong>
                <ElInput
                  :model-value="reasoningPromptText('criticPrompt')"
                  type="textarea"
                  :rows="4"
                  readonly
                />
              </div>
            </div>
            <ElDivider content-position="left">推理过程与结果</ElDivider>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <div class="reasoning-audit-block">
                  <strong>推理过程</strong>
                  <ElInput :model-value="reasoningProcessText" type="textarea" :rows="6" readonly />
                </div>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <div class="reasoning-audit-block">
                  <strong>推理结果</strong>
                  <ElInput :model-value="reasoningResultText" type="textarea" :rows="6" readonly />
                </div>
              </ElCol>
            </ElRow>
            <ElDivider content-position="left">推理链路 Trace</ElDivider>
            <ElTable :data="reasoningTraceSteps" border height="220" empty-text="暂无 Trace 记录">
              <ElTableColumn prop="sequence" label="序号" width="76" />
              <ElTableColumn prop="stepName" label="步骤" min-width="150" show-overflow-tooltip />
              <ElTableColumn prop="stepType" label="类型" width="130" show-overflow-tooltip />
              <ElTableColumn
                prop="conversationId"
                label="对话 ID"
                min-width="180"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="promptHash"
                label="Prompt Hash"
                min-width="150"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="responseHash"
                label="Response Hash"
                min-width="150"
                show-overflow-tooltip
              />
            </ElTable>
            <ElDivider content-position="left">模型建议</ElDivider>
            <div class="reasoning-suggestion">
              <ElTag :type="statusType(reasoningDetail.log.suggestion.result)" effect="light">
                {{ reasoningDetail.log.suggestion.result }}
              </ElTag>
              <p>{{ reasoningDetail.log.suggestion.opinionDraft }}</p>
              <ElSpace wrap>
                <ElTag
                  v-for="item in reasoningDetail.log.suggestion.manualConfirmItems"
                  :key="item"
                  type="warning"
                  effect="plain"
                >
                  {{ item }}
                </ElTag>
              </ElSpace>
            </div>
            <ElDivider content-position="left">证据</ElDivider>
            <ElTable :data="reasoningDetail.evidenceLinks" border height="280">
              <ElTableColumn prop="objectType" label="对象" width="140" />
              <ElTableColumn prop="fileName" label="文件" min-width="180" show-overflow-tooltip />
              <ElTableColumn prop="pageNo" label="页码" width="80" />
              <ElTableColumn prop="fieldName" label="字段" width="120" />
              <ElTableColumn prop="quotedText" label="文本" min-width="260" show-overflow-tooltip />
              <ElTableColumn label="置信度" width="100">
                <template #default="{ row }">{{ confidencePercent(row.confidence) }}</template>
              </ElTableColumn>
            </ElTable>
          </template>
        </div>
      </ElDrawer>
    </StaticPageShell>
  </div>
</template>

<style scoped>
.knowledge-page {
  min-height: 100vh;
  padding: 0;
  color: #1f2937;
  background: #f5f7fb;
}

.page-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  justify-content: space-between;
  margin-bottom: 12px;
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
  color: #667085;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.secondary-summary-collapse {
  padding: 0;
  margin: 0 0 16px;
  background: #fff;
  border: 1px solid #dfe8f5;
  border-radius: 8px;
  box-shadow: 0 6px 18px rgb(15 23 42 / 4%);
}

.secondary-summary-collapse summary {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 900;
  color: #172033;
  list-style: none;
  cursor: pointer;
}

.secondary-summary-collapse summary::-webkit-details-marker {
  display: none;
}

.secondary-summary-collapse summary::after {
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 900;
  color: #2563eb;
  content: '展开';
}

.secondary-summary-collapse[open] summary::after {
  content: '收起';
}

.secondary-summary-collapse summary small {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.secondary-summary-collapse .metric-grid {
  padding: 0 14px 14px;
  margin-bottom: 0;
}

.metric-card {
  min-height: 78px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.metric-card span {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #667085;
}

.metric-card strong {
  font-size: 26px;
  line-height: 32px;
}

.metric-card--blue {
  background: #f8fbff;
  border-color: #cbdcf8;
}

.metric-card--green {
  background: #f8fdf9;
  border-color: #cfe8d7;
}

.metric-card--orange {
  background: #fffaf0;
  border-color: #f0dfb8;
}

.metric-card--red {
  background: #fff7f7;
  border-color: #efc8c8;
}

.metric-card--gray {
  background: #f8fafc;
  border-color: #d7dde8;
}

.scorecard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.scorecard-item {
  min-height: 72px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.scorecard-item span {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #667085;
}

.scorecard-item strong {
  font-size: 20px;
  line-height: 28px;
}

.mt-12 {
  margin-top: 12px;
}

.knowledge-tabs {
  padding: 0 2px;
}

.panel {
  margin-bottom: 16px;
  border-radius: 8px;
}

.panel-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  font-weight: 700;
}

.panel-header.compact {
  margin-bottom: 10px;
  font-size: 13px;
}

.subsection-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #344054;
}

.page-index-table {
  margin-top: 8px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.filter-bar :deep(.el-input),
.filter-bar :deep(.el-select),
.filter-bar :deep(.el-input-number) {
  width: 220px;
}

.filter-bar.compact :deep(.el-input),
.filter-bar.compact :deep(.el-select),
.filter-bar.compact :deep(.el-input-number) {
  width: 180px;
}

.full-width-control {
  width: 100%;
}

.select-option-meta {
  float: right;
  margin-left: 16px;
  font-size: 12px;
  color: #98a2b3;
}

.table-pagination {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-top: 12px;
  row-gap: 8px;
}

.section-error {
  display: flex;
  padding: 10px 12px;
  margin-bottom: 12px;
  color: #991b1b;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.section-error strong,
.section-error span {
  display: block;
}

.section-error strong {
  line-height: 20px;
}

.section-error span {
  margin-top: 3px;
  font-size: 12px;
  line-height: 18px;
  color: #b42318;
}

.section-error :deep(.el-button) {
  flex: 0 0 auto;
}

.local-operation-error {
  margin-top: 12px;
}

.source-list,
.compare-history,
.model-result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-item,
.compare-history-item,
.model-result-item {
  padding: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.source-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.source-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-end;
  min-width: 150px;
}

.standard-source-summary {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}

.standard-source-row {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  min-height: 76px;
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.standard-source-main {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  gap: 4px;
}

.standard-source-main strong,
.standard-source-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.standard-source-main span {
  font-size: 12px;
  color: #667085;
}

.standard-source-controls {
  display: flex;
  flex: 0 0 auto;
  gap: 16px;
  align-items: center;
  justify-content: flex-end;
  min-width: 380px;
}

.standard-source-status,
.standard-source-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.standard-source-status {
  min-width: 150px;
}

.standard-source-actions {
  min-width: 170px;
}

.standard-source-actions :deep(.el-button) {
  min-height: 28px;
  margin-left: 0;
  padding: 0 2px;
}

.standard-source-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.standard-file-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: center;
}

.standard-file-actions :deep(.el-button) {
  margin-left: 0;
  padding: 0;
}

.standard-file-replace-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  min-height: 32px;
  color: #667085;
}

.source-item strong,
.compare-history-item strong {
  display: block;
  line-height: 20px;
}

.source-item span,
.compare-history-item span,
.model-result-item span {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #667085;
}

.compare-history-item {
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    background 0.2s ease;
}

.compare-history-item:hover {
  background: #f8fbff;
  border-color: #409eff;
}

.retrieval-result,
.compare-result {
  min-height: 430px;
}

.index-version-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.model-result-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.model-result-item p {
  margin: 10px 0 0;
  line-height: 22px;
  color: #344054;
}

.source-form :deep(.el-select),
.source-form :deep(.el-input-number),
.config-form :deep(.el-input),
.config-form :deep(.el-input-number) {
  width: 100%;
}

.knowledge-import-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.source-upload-panel {
  display: grid;
  width: 100%;
  min-width: 0;
  gap: 10px;
}

.source-upload-toolbar {
  margin-bottom: 0;
}

.source-upload-empty {
  display: grid;
  min-height: 54px;
  font-size: 13px;
  font-weight: 700;
  color: #667085;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  place-items: center;
}

.source-upload-row {
  display: grid;
  min-width: 0;
  padding: 10px;
  background: #fff;
  border: 1px solid #e4ebf5;
  border-radius: 8px;
  gap: 8px;
}

.source-upload-row-head,
.source-upload-meta {
  display: flex;
  min-width: 0;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.source-upload-row-head > span {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 800;
  color: #344054;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-upload-grid {
  display: grid;
  grid-template-columns: minmax(180px, 0.42fr) minmax(260px, 0.58fr);
  gap: 10px;
}

.source-upload-field {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.source-upload-field > span,
.source-upload-meta {
  font-size: 12px;
  font-weight: 800;
  color: #667085;
}

.source-upload-meta {
  justify-content: flex-start;
}

.hidden-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.config-switch-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin-bottom: 18px;
}

.config-switch-list > div {
  display: flex;
  min-height: 44px;
  padding: 8px 10px;
  color: #344054;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  align-items: center;
  justify-content: space-between;
}

.drawer-content {
  min-height: 320px;
}

.file-original-panel {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  margin-top: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.file-original-panel > div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.file-original-panel strong {
  line-height: 20px;
  color: #1f2937;
}

.file-original-panel span {
  overflow: hidden;
  font-size: 12px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-empty-alert {
  margin-bottom: 10px;
}

.rule-diff-drawer :deep(.el-descriptions) {
  margin-bottom: 16px;
}

.rule-diff-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.rule-diff-metric {
  min-height: 76px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.rule-diff-metric span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.rule-diff-metric strong {
  display: block;
  font-size: 24px;
  line-height: 28px;
  color: #1f2937;
}

.rule-diff-metric small {
  margin-left: 4px;
  font-size: 12px;
  font-weight: 500;
  color: #667085;
}

.diff-value {
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: #344054;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reasoning-suggestion {
  padding: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.reasoning-suggestion p {
  margin: 10px 0;
  line-height: 22px;
  color: #344054;
}

.reasoning-audit-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.reasoning-audit-block {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.reasoning-audit-block strong {
  font-size: 13px;
  line-height: 18px;
  color: #344054;
}

.reasoning-audit-block :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
  line-height: 18px;
}

@media (width <= 768px) {
  .knowledge-page {
    padding: 0;
  }

  .page-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .knowledge-flow-board,
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-bar :deep(.el-input),
  .filter-bar :deep(.el-select),
  .filter-bar :deep(.el-input-number),
  .filter-bar.compact :deep(.el-input),
  .filter-bar.compact :deep(.el-select),
  .filter-bar.compact :deep(.el-input-number) {
    width: 100%;
  }

  .table-pagination {
    padding-bottom: 4px;
    overflow-x: auto;
    justify-content: flex-start;
  }

  .section-error {
    align-items: stretch;
    flex-direction: column;
  }

  .section-error :deep(.el-button) {
    align-self: flex-start;
  }

  .source-item {
    flex-direction: column;
  }

  .source-actions {
    justify-content: flex-start;
    width: 100%;
  }

  .standard-source-row {
    align-items: stretch;
    flex-direction: column;
  }

  .standard-source-controls {
    align-items: flex-start;
    flex-direction: column;
    min-width: 0;
    width: 100%;
  }

  .standard-source-status,
  .standard-source-actions {
    justify-content: flex-start;
    min-width: 0;
    width: 100%;
  }

  .file-original-panel {
    align-items: stretch;
    flex-direction: column;
  }

  .source-upload-grid {
    grid-template-columns: 1fr;
  }

  .rule-diff-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scorecard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 480px) {
  .knowledge-flow-board,
  .metric-grid {
    grid-template-columns: 1fr;
  }

  .metric-card strong {
    font-size: 22px;
  }

  .rule-diff-summary {
    grid-template-columns: 1fr;
  }

  .scorecard-grid {
    grid-template-columns: 1fr;
  }
}
</style>
