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
  ElMessageBox,
  ElOption,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSpace,
  ElStep,
  ElSteps,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip
} from 'element-plus'
import {
  authorizeProjectMemberApi,
  createAdminConfigExportApi,
  createAdminConfigItemApi,
  createAdminOrgUnitApi,
  createAdminProjectApi,
  createAdminUserApi,
  createPromptTemplateApi,
  createReportTemplateApi,
  deleteAdminOrgUnitApi,
  deleteAdminProjectApi,
  deleteAdminUserApi,
  deleteAdminConfigItemApi,
  deletePromptTemplateApi,
  deleteReportTemplateApi,
  deleteProjectMemberApi,
  getAdminConfigOverviewApi,
  getAdminIntegrationContractApi,
  getAdminProjectDetailApi,
  getKnowledgeRuleVersionDiffApi,
  getAuditLogsApi,
  listAdminProjectsApi,
  listPromptTemplatesApi,
  listReportTemplatesApi,
  listBusinessPacksApi,
  previewAdminConfigDiffApi,
  previewAdminConfigPublishApi,
  publishAdminConfigApi,
  publishPromptTemplateApi,
  publishReportTemplateApi,
  saveAdminConfigItemApi,
  updateAdminOrgUnitApi,
  updateAdminProjectApi,
  updateAdminUserApi,
  updatePromptTemplateApi,
  updateReportTemplateApi,
  updateProjectMemberApi,
  validateAllBusinessPacksApi
} from '@/api/aicheck'
import type {
  AdminConfigChangePayload,
  AdminConfigDiffPayload,
  AdminConfigOverviewPayload,
  AdminPublishConfigPayload,
  AdminConfigTarget,
  AdminMaterialReviewPoint,
  AdminProjectCreatePayload,
  AdminProjectDetailPayload,
  AdminOrgUnit,
  AdminOrgUnitType,
  AdminUser,
  AuditLogPayload,
  BusinessPackValidateAllPayload,
  IntegrationContractField,
  IntegrationContractModule,
  IntegrationContractPayload,
  IntegrationContractStatus,
  KnowledgeRuleVersionDiffPayload,
  ProjectMember,
  PromptTemplate,
  PromptTemplateSavePayload,
  ReportTemplate,
  ReportTemplateSavePayload
} from '@/api/aicheck'
import type { ActionCode, ExportTask, Project, RoleCode } from '@/types/aicheck'
import { useUserStore } from '@/store/modules/user'
import { actionLabel, actionLabelWithCode } from '@/utils/actionLabels'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import { getAicheckRoleLabel } from '@/utils/roleAccess'
import AuditSummaryGrid, { type AuditSummaryCard } from './components/AuditSummaryGrid.vue'
import StaticPageShell from './components/StaticPageShell.vue'
import {
  formatNodeScope,
  formatParticipantType,
  formatProjectRegion
} from './utils/projectDetailPresentation'
import {
  findFirstRoleWithoutCandidates,
  missingWizardMemberMessage,
  userBelongsToOrganization
} from './utils/projectWizardMembers'

const emptyOverview = (): AdminConfigOverviewPayload => ({
  metrics: [],
  orgUnits: [],
  users: [],
  permissionMatrix: [],
  nodeTemplates: [],
  ruleVersions: [],
  workflowStateMachines: [],
  todoRules: [],
  messageTemplates: [],
  toolSources: [],
  fieldMappings: [],
  materialReviewPoints: [],
  businessPacks: []
})

const emptyIntegrationContract = (): IntegrationContractPayload => ({
  summary: {
    total: 0,
    aligned: 0,
    pending: 0,
    blockers: 0
  },
  modules: [],
  fields: [],
  generatedAt: ''
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const routeQueryText = (key: string) => {
  const value = route.query[key]
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}
const routeQueryNumber = (key: string, fallback: number) => {
  const value = Number(routeQueryText(key))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

const adminShellMenuSectionsBase = [
  {
    title: '基础管理',
    meta: '3页',
    items: [
      { index: '01', label: '项目管理', badge: '多项目', tone: 'blue', route: '/admin/projects' },
      {
        index: '02',
        label: '组织用户',
        route: '/admin/org'
      },
      {
        index: '03',
        label: '权限与节点',
        badge: '动作级',
        tone: 'blue',
        route: '/admin/permission'
      }
    ]
  },
  {
    title: '规则与业务配置',
    meta: '6页',
    items: [
      {
        index: '04',
        label: '业务类型管理',
        badge: '复用',
        tone: 'green',
        route: '/admin/business-packs'
      },
      {
        index: '05',
        label: 'AI业务规则与流程',
        badge: '发布',
        tone: 'blue',
        route: '/admin/rules'
      },
      {
        index: '06',
        label: '业务资料审查点',
        badge: '打靶',
        tone: 'orange',
        route: '/admin/material-review-points'
      },
      {
        index: '07',
        label: 'Prompt 模板管理',
        badge: 'Prompt',
        tone: 'blue',
        route: '/admin/prompt-templates'
      },
      {
        index: '08',
        label: '报告模板管理',
        badge: '报告',
        tone: 'green',
        route: '/admin/report-templates'
      },
      {
        index: '09',
        label: '细项配置',
        badge: '字段',
        tone: 'orange',
        route: '/admin/fine-config'
      }
    ]
  },
  {
    title: '知识与审计',
    meta: '3页',
    items: [
      {
        index: '08',
        label: 'AI 知识库管理',
        badge: 'OCR/向量',
        tone: 'green',
        route: '/knowledge/overview'
      },
      {
        index: '09',
        label: '联调清单',
        badge: '对账',
        tone: 'orange',
        route: '/admin/integration'
      },
      { index: '10', label: '审计日志', badge: '审计', tone: 'blue', route: '/admin/audit' }
    ]
  }
] as const

const adminShellBoundaryRows = [
  { label: '合同1', value: '项目管理、组织用户、权限与节点' },
  { label: '合同2', value: '业务类型、规则流程、Prompt 模板、细项配置' },
  { label: '合同3', value: '知识库、联调清单、审计日志' },
  { label: '边界', value: '后台配置，不办理审查意见或报告确认' }
] as const

type PermissionConfigRow = AdminConfigOverviewPayload['permissionMatrix'][number]
type NodeTemplateConfigRow = AdminConfigOverviewPayload['nodeTemplates'][number]
type WorkflowConfigRow = AdminConfigOverviewPayload['workflowStateMachines'][number]
type RuleVersionConfigRow = AdminConfigOverviewPayload['ruleVersions'][number]
type TodoRuleConfigRow = AdminConfigOverviewPayload['todoRules'][number]
type MessageTemplateConfigRow = AdminConfigOverviewPayload['messageTemplates'][number]
type ToolSourceConfigRow = AdminConfigOverviewPayload['toolSources'][number]
type FieldMappingConfigRow = AdminConfigOverviewPayload['fieldMappings'][number]
type MaterialReviewPointRow = AdminConfigOverviewPayload['materialReviewPoints'][number]
type BusinessPackRow = NonNullable<AdminConfigOverviewPayload['businessPacks']>[number]
type ProjectWizardMemberRole = Extract<RoleCode, 'inspection' | 'contractor' | 'ndt' | 'owner'>
type PaginationState = {
  page: number
  pageSize: number
  total: number
}
type TableSortOrder = 'ascending' | 'descending' | null
type TableSortState = {
  prop: string
  order: TableSortOrder
}
type TableState = PaginationState & TableSortState

const DEFAULT_PIPELINE_BUSINESS_PACK_ID = 'engineering_inspection_v1'
const DEFAULT_INITIAL_PASSWORD = 'anyuekeji.123'
const PIPELINE_TYPE_ORDER = ['GA类', 'GB类', 'GC类']

const createPagination = (pageSize = 10): PaginationState => ({
  page: 1,
  pageSize,
  total: 0
})

const createTableState = (pageSize = 10): TableState => ({
  ...createPagination(pageSize),
  prop: '',
  order: null
})

const loading = ref(false)
const projectsLoading = ref(false)
const auditLoading = ref(false)
const configExporting = ref(false)
const configPublishing = ref(false)

const adminTabRouteMap = {
  projects: '/admin/projects',
  org: '/admin/org',
  'business-pack': '/admin/business-packs',
  permission: '/admin/permission',
  rule: '/admin/rules',
  'material-review-point': '/admin/material-review-points',
  'prompt-template': '/admin/prompt-templates',
  'report-template': '/admin/report-templates',
  'fine-config': '/admin/fine-config',
  integration: '/admin/integration',
  audit: '/admin/audit'
} as const

type AdminTabKey = keyof typeof adminTabRouteMap

const adminRouteTabMap: Record<string, AdminTabKey> = {
  '/admin/overview': 'projects',
  '/admin/projects': 'projects',
  '/admin/org': 'org',
  '/admin/business-packs': 'business-pack',
  '/admin/permission': 'permission',
  '/admin/rules': 'rule',
  '/admin/material-review-points': 'material-review-point',
  '/admin/prompt-templates': 'prompt-template',
  '/admin/report-templates': 'report-template',
  '/admin/fine-config': 'fine-config',
  '/admin/integration': 'integration',
  '/admin/audit': 'audit'
}

const getAdminTabFromRoute = (path: string): AdminTabKey => adminRouteTabMap[path] || 'org'

const activeTab = ref<AdminTabKey>(getAdminTabFromRoute(route.path))
const projects = ref<Project[]>([])
const overview = ref<AdminConfigOverviewPayload>(emptyOverview())
const integrationContract = ref<IntegrationContractPayload>(emptyIntegrationContract())
const auditLogs = ref<AuditLogPayload['items']>([])
const auditIntegrity = ref<AuditLogPayload['integrity']>()
const auditPagination = reactive(createPagination(10))
const tablePageSizes = [5, 10, 20, 50]
const tableStates = reactive({
  projects: createTableState(8),
  orgUnits: createTableState(10),
  users: createTableState(10),
  businessPacks: createTableState(10),
  permissionMatrix: createTableState(8),
  nodeTemplates: createTableState(8),
  ruleVersions: createTableState(8),
  materialReviewPoints: createTableState(10),
  workflowStateMachines: createTableState(8),
  promptTemplates: createTableState(8),
  reportTemplates: createTableState(8),
  todoRules: createTableState(8),
  messageTemplates: createTableState(8),
  toolSources: createTableState(8),
  fieldMappings: createTableState(8),
  integration: createTableState(10),
  projectWizardRoles: createTableState(5),
  configDiff: createTableState(8),
  publishImpact: createTableState(8),
  adminRuleDiff: createTableState(8),
  projectParticipants: createTableState(6),
  projectMembers: createTableState(8),
  projectNodeSummary: createTableState(8),
  projectExports: createTableState(8)
})
if (activeTab.value === 'projects') {
  tableStates.projects.page = routeQueryNumber('page', 1)
  tableStates.projects.pageSize = routeQueryNumber('pageSize', tableStates.projects.pageSize)
  tableStates.projects.prop = routeQueryText('sort')
  tableStates.projects.order = (routeQueryText('order') || null) as TableSortOrder
}
type TableKey = keyof typeof tableStates
const auditSort = reactive<TableSortState>({ prop: '', order: null })
const overviewError = ref('')
const adminActionError = ref('')
const integrationLoading = ref(false)
const integrationError = ref('')
const integrationModuleFilter = ref<IntegrationContractModule | 'all'>('all')
const integrationStatusFilter = ref<IntegrationContractStatus | 'all'>('all')
const adminActionRetry = ref<'export' | 'publish' | null>(null)
const businessPackValidating = ref(false)
const businessPackValidation = ref<BusinessPackValidateAllPayload | null>(null)
const businessPackValidationError = ref('')
const auditError = ref('')
const projectDrawerVisible = ref(false)
const projectDetailLoading = ref(false)
const projectDetail = ref<AdminProjectDetailPayload | null>(null)
const projectDetailProjectId = ref('')
const projectDetailError = ref('')
const memberDialogVisible = ref(false)
const memberDialogMode = ref<'single' | 'batch'>('single')
const memberSaving = ref(false)
const memberOperationError = ref('')
const memberBatchUserIds = ref<string[]>([])
const memberBatchResult = ref<{
  successCount: number
  failed: Array<{ userId: string; name: string; message: string }>
} | null>(null)
const selectedExportTask = ref<ExportTask | null>(null)
const projectWizardVisible = ref(false)
const projectWizardStep = ref(0)
const projectCreating = ref(false)
const projectWizardError = ref('')
const projectEditVisible = ref(false)
const projectSaving = ref(false)
const projectOperationError = ref('')
const orgDialogVisible = ref(false)
const orgDialogMode = ref<'create' | 'edit'>('create')
const orgSaving = ref(false)
const orgOperationError = ref('')
const userDialogVisible = ref(false)
const userDialogMode = ref<'create' | 'edit'>('create')
const userSaving = ref(false)
const userOperationError = ref('')
const configDrawerVisible = ref(false)
const configDiffVisible = ref(false)
const configSaving = ref(false)
const configPreviewing = ref(false)
const configOperationError = ref('')

const adminMenuActiveRoute = computed(() =>
  route.path === '/admin/overview' ? '/admin/projects' : route.path
)

const adminPageTitleMap: Record<AdminTabKey, { title: string; subtitle: string }> = {
  projects: {
    title: '项目管理',
    subtitle: ''
  },
  org: {
    title: '组织用户',
    subtitle: '管理组织单位、用户账号和基础角色'
  },
  permission: {
    title: '权限与节点',
    subtitle: '维护角色权限矩阵和项目审核节点模板'
  },
  'business-pack': {
    title: '业务类型管理',
    subtitle: '管理可复用业务类型、节点、资料和规则配置'
  },
  rule: {
    title: 'AI业务规则与流程',
    subtitle: '管理AI业务规则版本、流程状态机和发布差异'
  },
  'material-review-point': {
    title: '业务资料审查点',
    subtitle: '维护业务节点、资料类型、OCR证据项和审查点的对应关系'
  },
  'prompt-template': {
    title: 'Prompt 模板管理',
    subtitle: '管理 System Prompt、User Prompt、Plan 编排和 Critic 模板版本'
  },
  'report-template': {
    title: '报告模板管理',
    subtitle: '维护报告章节、导出类型和业务包版本，并发布供报告生成使用'
  },
  'fine-config': {
    title: '细项配置',
    subtitle: '管理待办、消息、工具源和证据字段映射'
  },
  integration: {
    title: '联调清单',
    subtitle: '核对前后端字段、接口契约和阻断项'
  },
  audit: {
    title: '审计日志',
    subtitle: '查看后台配置变更、发布和操作审计记录'
  }
}

const adminPageTitle = computed(() => adminPageTitleMap[activeTab.value].title)
const adminPageSubtitle = computed(() => adminPageTitleMap[activeTab.value].subtitle)
const adminPublishScope = computed<'all' | 'permission' | 'workflow' | 'node-template' | 'rule'>(
  () => {
    if (activeTab.value === 'permission') return 'permission'
    if (activeTab.value === 'rule') return 'rule'
    if (activeTab.value === 'material-review-point') return 'node-template'
    if (activeTab.value === 'fine-config') return 'workflow'
    return 'all'
  }
)
const adminPublishAvailable = computed(() =>
  ['permission', 'rule', 'material-review-point', 'prompt-template', 'fine-config'].includes(
    activeTab.value
  )
)

const adminShellMenuSections = computed(() => {
  let activeMatched = false
  return adminShellMenuSectionsBase.map((section) => ({
    ...section,
    items: section.items.map((item) => {
      const active = !activeMatched && item.route === adminMenuActiveRoute.value
      if (active) activeMatched = true
      return { ...item, active }
    })
  }))
})

const scrollAdminContentIntoView = () => {
  nextTick(() => {
    document.querySelector('.admin-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

const handleAdminMenuSelect = () => {
  scrollAdminContentIntoView()
}

watch(
  () => route.path,
  (path, oldPath) => {
    if (!path.startsWith('/admin')) return
    const nextTab = getAdminTabFromRoute(path)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
    if (oldPath) scrollAdminContentIntoView()
  },
  { immediate: true }
)

watch(activeTab, (tab) => {
  if (!route.path.startsWith('/admin')) return
  if (adminRouteTabMap[route.path] === tab && route.path !== '/admin/overview') return
  const targetPath = adminTabRouteMap[tab]
  if (targetPath && route.path !== targetPath) {
    router.push(targetPath)
  }
})

// 切换后台子页要重新取数——loadData 按 activeTab 分派本页要用的那一个请求，
// 而 /admin/* 十二个子页共用同一个组件实例，切页不会重新挂载。
//
// 原先只有 onMounted 里那一次 loadData()：直接整页打开 /admin/audit 能看到
// 2008 条审计记录，从别的管理页点过去就是「共 0 条 / 当前筛选下暂无审计日志」。
// 2026-08-14 实测确认，同样影响项目清单、联调清单、Prompt 与报告模板。
//
// 对监督检验系统来说这条尤其要紧：审计留痕是法定要求，而验证的人多半是
// 从总览点进审计页的——他看到的是「一条记录都没有」。
watch(activeTab, () => {
  loadData()
})
const configOperationRetry = ref<'preview' | 'save' | null>(null)
const configEditTarget = ref<AdminConfigTarget>('permission')
const configEditMode = ref<'create' | 'edit'>('edit')
const latestConfigDiff = ref<AdminConfigDiffPayload | null>(null)
const latestPublishResult = ref<AdminPublishConfigPayload | null>(null)
const publishTraceVisible = ref(false)
const ruleDetailDrawerVisible = ref(false)
const adminRuleDiffVisible = ref(false)
const adminRuleDiffLoading = ref(false)
const selectedRuleVersion = ref<RuleVersionConfigRow | null>(null)
const adminRuleDiff = ref<KnowledgeRuleVersionDiffPayload | null>(null)
const adminRuleDiffError = ref('')
const promptTemplates = ref<PromptTemplate[]>([])
const promptTemplateLoading = ref(false)
const promptTemplateError = ref('')
const promptTemplateSaving = ref(false)
const promptTemplateDialogVisible = ref(false)
const promptTemplateDialogMode = ref<'create' | 'edit'>('create')
const promptTemplateOperationError = ref('')
const reportTemplates = ref<ReportTemplate[]>([])
const reportTemplateLoading = ref(false)
const reportTemplateError = ref('')
const reportTemplateSaving = ref(false)
const reportTemplateDialogVisible = ref(false)
const reportTemplateDialogMode = ref<'create' | 'edit' | 'view'>('create')

// 生产版本的模板不允许改内容——报告已生成的那些引用着当时的快照。
// 但原来的做法是「编辑/发布/删除三个按钮一起禁用，不给任何说明」，
// 管理员看到的就是一排点不动的按钮，也不知道该怎么办（实测被当成 bug 报上来）。
// 规则不变，改成把规则讲出来，并且留一条能走的路：生产版本可以查看。
const REPORT_TEMPLATE_LOCKED_STATUSES = ['production', '已发布']
const reportTemplateLocked = (status?: string) =>
  REPORT_TEMPLATE_LOCKED_STATUSES.includes(String(status || ''))
const reportTemplateLockedHint = '生产版本已被已生成的报告引用，不能改动；请新增一个模板版本。'
const reportTemplateOperationError = ref('')

const auditFilters = reactive({
  keyword: activeTab.value === 'audit' ? routeQueryText('q') : '',
  result: activeTab.value === 'audit' ? routeQueryText('result') : '',
  objectType: activeTab.value === 'audit' ? routeQueryText('objectType') : ''
})

const projectFilters = reactive({
  keyword: activeTab.value === 'projects' ? routeQueryText('q') : '',
  status: (activeTab.value === 'projects' ? routeQueryText('status') : '') as Project['status'] | ''
})
if (activeTab.value === 'audit') {
  auditPagination.page = routeQueryNumber('page', 1)
  auditPagination.pageSize = routeQueryNumber('pageSize', auditPagination.pageSize)
  auditSort.prop = routeQueryText('sort')
  auditSort.order = (routeQueryText('order') || null) as TableSortOrder
}

const syncAdminRouteQuery = () => {
  const query = { ...route.query }
  for (const key of ['q', 'status', 'result', 'objectType', 'page', 'pageSize', 'sort', 'order']) {
    delete query[key]
  }
  if (activeTab.value === 'projects') {
    if (projectFilters.keyword.trim()) query.q = projectFilters.keyword.trim()
    if (projectFilters.status) query.status = projectFilters.status
    if (tableStates.projects.page > 1) query.page = String(tableStates.projects.page)
    if (tableStates.projects.pageSize !== 8) query.pageSize = String(tableStates.projects.pageSize)
    if (tableStates.projects.prop) query.sort = tableStates.projects.prop
    if (tableStates.projects.order) query.order = tableStates.projects.order
  } else if (activeTab.value === 'audit') {
    if (auditFilters.keyword.trim()) query.q = auditFilters.keyword.trim()
    if (auditFilters.result) query.result = auditFilters.result
    if (auditFilters.objectType) query.objectType = auditFilters.objectType
    if (auditPagination.page > 1) query.page = String(auditPagination.page)
    if (auditPagination.pageSize !== 10) query.pageSize = String(auditPagination.pageSize)
    if (auditSort.prop) query.sort = auditSort.prop
    if (auditSort.order) query.order = auditSort.order
  }
  void router.replace({ path: route.path, query })
}

watch(
  () => [
    activeTab.value,
    projectFilters.keyword,
    projectFilters.status,
    tableStates.projects.page,
    tableStates.projects.pageSize,
    tableStates.projects.prop,
    tableStates.projects.order,
    auditFilters.keyword,
    auditFilters.result,
    auditFilters.objectType,
    auditPagination.page,
    auditPagination.pageSize,
    auditSort.prop,
    auditSort.order
  ],
  syncAdminRouteQuery,
  { flush: 'post' }
)

const projectStatusOptions: Project['status'][] = [
  '草稿/立项中',
  '资料提交中',
  'AI 预审中',
  '监检审查中',
  '退回补正中',
  '报告生成/复核中',
  '已归档'
]

const promptTemplateFilters = reactive({
  keyword: '',
  status: ''
})

const reportTemplateFilters = reactive({
  keyword: '',
  status: ''
})

const projectWizardForm = reactive({
  businessPackId: DEFAULT_PIPELINE_BUSINESS_PACK_ID,
  code: '',
  name: '',
  type: '',
  region: '',
  ownerOrgName: '',
  contractorOrgName: '',
  ndtOrgName: '',
  inspectionOrgName: '',
  memberUserIds: {
    inspection: '',
    contractor: '',
    ndt: '',
    owner: ''
  } as Record<ProjectWizardMemberRole, string>
})

const projectEditForm = reactive({
  id: '',
  code: '',
  name: '',
  type: '',
  region: '',
  ownerOrgName: '',
  contractorOrgName: '',
  ndtOrgName: '',
  inspectionOrgName: '',
  status: '草稿/立项中' as Project['status'],
  etag: ''
})

const orgForm = reactive({
  id: '',
  name: '',
  type: 'contractor' as AdminOrgUnitType,
  contactName: '',
  contactPhone: '',
  status: '启用' as AdminOrgUnit['status'],
  etag: ''
})

const userForm = reactive({
  id: '',
  username: '',
  name: '',
  mobile: '',
  role: 'contractor' as RoleCode,
  orgId: '',
  status: '启用' as AdminUser['status'],
  password: '',
  etag: ''
})

const memberForm = reactive({
  userId: '',
  role: 'inspection' as RoleCode,
  orgId: '',
  expiresAt: ''
})

const configForm = reactive({
  id: '',
  role: 'inspection' as RoleCode,
  label: '',
  projectScope: '',
  nodeScope: '',
  actions: [] as ActionCode[],
  readonly: false,
  version: '',
  groupName: '',
  nodeCount: 0,
  requiredCount: 0,
  nodeTemplateStatus: '草稿' as NodeTemplateConfigRow['status'],
  workflowName: '',
  states: 0,
  transitions: 0,
  workflowStatus: '启用' as WorkflowConfigRow['status'],
  todoRuleName: '',
  triggerStatus: '',
  assigneeRole: 'inspection' as RoleCode,
  deadlineHours: 48,
  fineEnabled: true,
  scene: '',
  channel: '站内信' as MessageTemplateConfigRow['channel'],
  titleTemplate: '',
  contentTemplate: '',
  toolName: '',
  toolType: 'external-query' as ToolSourceConfigRow['toolType'],
  endpoint: '',
  authMode: 'none' as ToolSourceConfigRow['authMode'],
  toolStatus: '启用' as ToolSourceConfigRow['status'],
  fieldNodeId: 16,
  fieldName: '',
  sourceField: '',
  targetField: '',
  fieldRequired: true,
  confidenceThreshold: 0.85,
  reviewPointBusinessPackId: DEFAULT_PIPELINE_BUSINESS_PACK_ID,
  reviewPointNodeId: 16,
  reviewPointNodeName: '',
  reviewPointRuleId: '',
  reviewPointBusinessModule: '',
  reviewPointReviewClass: 'C',
  reviewPointReviewContent: '',
  reviewPointMaterialCategory: '',
  reviewPointMaterialTypeCode: '',
  reviewPointMaterialTypeName: '',
  reviewPointFileContent: '',
  reviewPointEvidenceItemText: '',
  reviewPointResponsibleParty: 'contractor' as RoleCode,
  reviewPointRequiredType: '必传' as AdminMaterialReviewPoint['requiredType'],
  reviewPointMappingRelation: '',
  reviewPointMinConfidence: 0.65,
  reason: '按当前业务配置调整。'
})

const promptTemplateForm = reactive({
  id: '',
  name: '',
  promptKey: 'review_prompt',
  version: '2026.06',
  status: 'draft' as PromptTemplate['status'],
  riskLevel: 'high',
  businessPackId: DEFAULT_PIPELINE_BUSINESS_PACK_ID,
  agentId: 'compliance_review_agent',
  promptVersionId: 'PROMPT-review-202606',
  systemPrompt: '',
  userPromptTemplate: '',
  plannerPromptTemplate: '',
  criticPromptTemplate: '',
  outputSchemaText: '',
  etag: ''
})

const reportTemplateForm = reactive({
  id: '',
  name: '',
  version: '2026.06',
  status: 'draft' as ReportTemplate['status'],
  businessPackId: DEFAULT_PIPELINE_BUSINESS_PACK_ID,
  businessPackVersion: '2026.06',
  exportTypes: ['report'] as ReportTemplate['exportTypes'],
  sectionsText: '',
  etag: ''
})

const roleActionOptions: Record<RoleCode, ActionCode[]> = {
  inspection: [
    'project:view',
    'file:upload',
    'file:bind',
    'review:save',
    'review:return-correction',
    'ai:recheck',
    'ai:adopt',
    'ai:reject',
    'report:generate',
    'report:review',
    'report:export',
    'report:view'
  ],
  contractor: [
    'project:view',
    'file:upload',
    'file:bind',
    'submission:draft',
    'submission:submit',
    'rectification:submit'
  ],
  ndt: [
    'project:view',
    'file:upload',
    'file:bind',
    'submission:draft',
    'submission:submit',
    'rectification:submit',
    'ndt:film-create',
    'ndt:record-import',
    'ndt:submit',
    'ndt:report-upload'
  ],
  owner: ['project:view', 'report:view', 'archive:view', 'archive:download'],
  admin: [
    'project:view',
    'project:authorize-member',
    'knowledge:view',
    'knowledge:manage',
    'admin:config',
    'admin:export',
    'audit:view'
  ],
  fde: [
    'fde:dashboard:view',
    'fde:ai-run:view-masked',
    'fde:ai-run:replay',
    'fde:feedback:view',
    'fde:feedback:triage',
    'fde:evaluation:view',
    'fde:evaluation:manage',
    'fde:evaluation:run',
    'fde:business-pack:view',
    'fde:business-pack:validate',
    'fde:capability-bundle:manage',
    'fde:release:view',
    'fde:release:submit',
    'fde:release:rollback',
    'fde:ocr-quality:view',
    'fde:incident:manage'
  ]
}

const statusType = (status?: string) => {
  if (!status) return 'info'
  if (
    status.includes('通过') ||
    status.includes('归档') ||
    status.includes('成功') ||
    status.includes('启用') ||
    status.includes('发布')
  )
    return 'success'
  if (status.includes('补正') || status.includes('失败') || status.includes('停用')) return 'danger'
  if (
    status.includes('AI') ||
    status.includes('待') ||
    status.includes('审查') ||
    status.includes('草稿')
  )
    return 'warning'
  return 'info'
}

const getRequestErrorMessage = (error: unknown, fallback: string) => {
  return getAicheckErrorMessage(error, fallback)
}

const buildOperationFailureMessage = (action: string) =>
  `${action}失败，当前页面数据已保留，请稍后重试或刷新后再操作。`

const roleLabel = (role: RoleCode) => getAicheckRoleLabel(role)

const responsiblePartyLabel = (role?: string) => getAicheckRoleLabel(role)

const tableSortCollator = new Intl.Collator('zh-Hans-CN', {
  numeric: true,
  sensitivity: 'base'
})

const getSortValue = (row: unknown, prop: string): unknown => {
  if (!prop) return ''
  if (prop === '__self') return row ?? ''
  if (prop === '__wizardNodeScope') {
    return row === 'ndt' ? '35, 36, 40, 41, 42' : '1, 16, 24, 40, 68'
  }
  if (!row || typeof row !== 'object') return row ?? ''
  const source = row as Record<string, unknown>
  if (prop === '__businessPackName') return source.pipelineTypeName || source.name || ''
  if (prop === '__businessPackRange') {
    return [source.commonGrades, source.scopeDescription, source.description]
      .filter(Boolean)
      .join('，')
  }
  if (prop === '__endpoint') return [source.method, source.endpoint].filter(Boolean).join(' ')
  return prop.split('.').reduce<unknown>((target, key) => {
    if (!target || typeof target !== 'object') return ''
    return (target as Record<string, unknown>)[key] ?? ''
  }, row)
}

const normalizeSortValue = (value: unknown): string | number => {
  if (value === undefined || value === null) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value === 'boolean') return value ? 1 : 0
  if (value instanceof Date) return value.getTime()
  if (Array.isArray(value)) return value.join(' ')
  const text = String(value)
  const timestamp = Date.parse(text)
  if (/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/.test(text) && !Number.isNaN(timestamp)) {
    return timestamp
  }
  return text
}

const compareSortValues = (left: unknown, right: unknown) => {
  const leftValue = normalizeSortValue(left)
  const rightValue = normalizeSortValue(right)
  if (typeof leftValue === 'number' && typeof rightValue === 'number') return leftValue - rightValue
  return tableSortCollator.compare(String(leftValue), String(rightValue))
}

const sortedRows = <T,>(rows: readonly T[] | undefined, state: TableSortState) => {
  const list = [...(rows || [])]
  if (!state.prop || !state.order) return list
  const direction = state.order === 'ascending' ? 1 : -1
  return list.sort((left, right) => {
    const result = compareSortValues(
      getSortValue(left, state.prop),
      getSortValue(right, state.prop)
    )
    return result * direction
  })
}

const tableRows = <T,>(rows: readonly T[] | undefined, state: TableState) => {
  const list = sortedRows(rows, state)
  const start = (state.page - 1) * state.pageSize
  return list.slice(start, start + state.pageSize)
}

const pageIndex = (state: TableState) => (index: number) => {
  return (state.page - 1) * state.pageSize + index + 1
}

const handleTableSortChange = (key: TableKey, event: { prop?: string; order?: TableSortOrder }) => {
  const state = tableStates[key]
  state.prop = event.prop || ''
  state.order = event.order || null
  state.page = 1
}

const handleAuditSortChange = (event: { prop?: string; order?: TableSortOrder }) => {
  auditSort.prop = event.prop || ''
  auditSort.order = event.order || null
}

const resetTablePage = (key: TableKey) => {
  tableStates[key].page = 1
}

const overviewProjectTotal = computed(() =>
  Number(overview.value.metrics.find((item) => item.key === 'project')?.value || 0)
)
const projectTotal = computed(() =>
  activeTab.value === 'projects' ? tableStates.projects.total : overviewProjectTotal.value
)
const projectTableRows = computed(() => sortedRows(projects.value, tableStates.projects))

const projectStats = computed(() => {
  if (overview.value.metrics.length) return overview.value.metrics
  return [
    { key: 'project', label: '项目总数', value: projectTotal.value, tone: 'blue' as const },
    { key: 'active', label: '在检项目', value: '--', tone: 'green' as const },
    { key: 'correction', label: '补正项目', value: '--', tone: 'red' as const },
    { key: 'todo', label: '全局待办', value: '--', tone: 'orange' as const }
  ]
})

const businessPackRows = computed(() =>
  [...(overview.value.businessPacks || [])].sort((left, right) => {
    const leftIndex = PIPELINE_TYPE_ORDER.indexOf(left.pipelineTypeCode || '')
    const rightIndex = PIPELINE_TYPE_ORDER.indexOf(right.pipelineTypeCode || '')
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex)
    }
    return left.name.localeCompare(right.name, 'zh-Hans-CN')
  })
)
const selectedWizardBusinessPack = computed(
  () =>
    businessPackRows.value.find((pack) => pack.id === projectWizardForm.businessPackId) ||
    businessPackRows.value.find((pack) => pack.id === DEFAULT_PIPELINE_BUSINESS_PACK_ID) ||
    null
)
const packPlatformRoleMap: Record<string, ProjectWizardMemberRole> = {
  reviewer: 'inspection',
  submitter: 'contractor',
  specialist_submitter: 'ndt',
  observer: 'owner'
}
const projectWizardRoles = computed<ProjectWizardMemberRole[]>(() => {
  const pack = selectedWizardBusinessPack.value
  const roles = (pack?.roles || [])
    .map((role) => {
      if (['inspection', 'contractor', 'ndt', 'owner'].includes(role.code)) {
        return role.code as ProjectWizardMemberRole
      }
      return packPlatformRoleMap[role.platformRole]
    })
    .filter((role): role is ProjectWizardMemberRole => Boolean(role))
  if (roles.length) return [...new Set(roles)]
  return pack?.domainType === 'engineering_inspection'
    ? ['inspection', 'contractor', 'ndt', 'owner']
    : ['inspection', 'contractor', 'owner']
})
const wizardUsesRole = (role: ProjectWizardMemberRole) => projectWizardRoles.value.includes(role)
const businessPackTypeLabel = (pack: BusinessPackRow) =>
  [pack.pipelineTypeCode, pack.pipelineTypeName || pack.name].filter(Boolean).join(' ')
const businessPackRangeText = (pack: BusinessPackRow) =>
  [pack.commonGrades, pack.scopeDescription].filter(Boolean).join('，') || pack.description || '-'
const businessPackOptionLabel = (pack: BusinessPackRow) =>
  [businessPackTypeLabel(pack), pack.commonGrades].filter(Boolean).join(' / ')
const projectTypeForPack = (pack?: BusinessPackRow | null) =>
  pack?.projectType || pack?.pipelineTypeName || pack?.name || ''
const businessPackStatusLabel = (status?: string) => {
  const labels: Record<string, string> = {
    published: '已发布',
    draft: '草稿',
    candidate: '候选',
    deprecated: '已停用',
    archived: '已归档'
  }
  return labels[status || ''] || status || '-'
}
const selectedWizardBusinessPackDescription = computed(() => {
  const pack = selectedWizardBusinessPack.value
  if (!pack) return ''
  return `${businessPackTypeLabel(pack)}：${businessPackRangeText(pack)}。节点 ${pack.nodeCount} 个、资料 ${pack.materialTypeCount} 类、规则 ${pack.ruleSetCount} 套。`
})

const pendingRuleCount = computed(
  () => overview.value.ruleVersions.filter((item) => item.status === '待发布').length
)

const adminUserLabel = computed(
  () =>
    userStore.getUserInfo?.displayName ||
    userStore.getUserInfo?.username ||
    userStore.getUserInfo?.roleLabel ||
    '系统管理员'
)
const adminRuntimeStatus = computed(() =>
  overviewError.value ? '数据加载异常' : pendingRuleCount.value ? '存在待发布配置' : '配置已同步'
)
const adminRuntimeStatusTone = computed(() =>
  overviewError.value
    ? ('red' as const)
    : pendingRuleCount.value
      ? ('orange' as const)
      : ('green' as const)
)
const adminShellRightSubtitle = computed(() =>
  overview.value.lastPublishedVersion
    ? `最近发布：${overview.value.lastPublishedVersion}`
    : '尚无已发布配置快照'
)
const adminShellRightCards = computed(() => [
  {
    title: '配置状态',
    rows: [
      { label: '规则模板', value: String(overview.value.ruleVersions.length) },
      { label: '待发布', value: String(pendingRuleCount.value) },
      { label: '权限角色', value: String(overview.value.permissionMatrix.length) },
      { label: '字段映射', value: String(overview.value.fieldMappings.length) },
      { label: '更新时间', value: overview.value.updatedAt || '--' }
    ]
  },
  {
    title: '当前范围',
    rows: [
      { label: '页面', value: adminPageTitle.value },
      { label: '项目总数', value: String(projectTotal.value) },
      { label: '组织单位', value: String(overview.value.orgUnits.length) },
      { label: '用户账号', value: String(overview.value.users.length) }
    ]
  },
  {
    title: '职责边界',
    note: '后台仅维护项目、账号、权限和配置；正式审查结论仍由监检人员在业务工作台完成。'
  }
])

const adminAuditCards = computed<AuditSummaryCard[]>(() => [
  {
    label: '当前治理对象',
    value: '项目、组织、权限与业务类型',
    hint: `${projectTotal.value} 个项目 · ${overview.value.users.length} 个用户`,
    tone: 'blue'
  },
  {
    label: '配置影响范围',
    value: `${overview.value.permissionMatrix.length} 类角色矩阵`,
    hint: `${overview.value.nodeTemplates.length} 组节点模板参与校验`,
    tone: 'green'
  },
  {
    label: '发布门禁',
    value: pendingRuleCount.value ? `${pendingRuleCount.value} 项待发布` : '无待发布项',
    hint: '发布前需完成 Diff、影响范围和审计记录',
    tone: 'orange'
  },
  {
    label: '风险关注',
    value: `${auditPagination.total || 0} 条审计记录`,
    hint: '重点关注权限、规则和业务类型变更',
    tone: 'red'
  }
])

const selectedProjectMembers = computed(() => projectDetail.value?.members || [])
const auditTableRows = computed(() => sortedRows(auditLogs.value, auditSort))
const auditIntegrityAlert = computed(() => {
  const integrity = auditIntegrity.value
  if (!integrity) return null
  if (integrity.status === 'tampered') {
    return {
      type: 'error' as const,
      title: '审计链校验异常',
      description: `发现 ${integrity.failures.length} 个链校验问题，请立即停止签发和归档操作。`
    }
  }
  const legacyCount = integrity.legacyUnverifiedEventCount || 0
  if (legacyCount > 0) {
    const sealed = integrity.coverageStatus === 'legacy_unverified_sealed'
    return {
      type: sealed ? ('warning' as const) : ('error' as const),
      title: sealed ? '后续审计链已验证，历史记录已单独封存' : '存在尚未封存的历史审计记录',
      description: `${integrity.chainedEventCount} 条链上记录已验证；${legacyCount} 条历史记录为 legacy_unverified，不能追溯证明原始真实性。`
    }
  }
  return {
    type: 'success' as const,
    title: '审计链覆盖完整',
    description: `${integrity.verifiedEventCount} 条审计记录已通过连续性和哈希校验。`
  }
})

const memberDialogTitle = computed(() =>
  memberDialogMode.value === 'batch' ? '批量项目成员授权' : '项目成员授权'
)

const selectedProjectMemberUserIds = computed(
  () => new Set(selectedProjectMembers.value.map((member) => member.userId))
)

const businessRoleOrgTypes: Partial<Record<RoleCode, AdminOrgUnitType[]>> = {
  inspection: ['inspection', 'supervision'],
  contractor: ['contractor'],
  ndt: ['ndt'],
  owner: ['owner']
}

const roleOrgOptions = (role: RoleCode) => {
  const allowed = businessRoleOrgTypes[role]
  return overview.value.orgUnits.filter(
    (org) => org.status === '启用' && (!allowed || allowed.includes(org.type))
  )
}

const orgNameById = (orgId?: string) =>
  overview.value.orgUnits.find((org) => org.id === orgId)?.name || ''

const batchMemberCandidateUsers = computed(() => {
  const selectedOrgName = orgNameById(memberForm.orgId)
  return overview.value.users.filter(
    (user) =>
      user.status === '启用' &&
      user.role === memberForm.role &&
      (!memberForm.orgId || user.orgId === memberForm.orgId || user.orgName === selectedOrgName)
  )
})

const allActionOptions = computed(() =>
  Array.from(new Set(Object.values(roleActionOptions).flat())).sort()
)

const configTargetLabel = computed(() => {
  if (configEditTarget.value === 'permission') return '角色权限矩阵'
  if (configEditTarget.value === 'node-template') return '节点模板'
  if (configEditTarget.value === 'workflow') return '流程状态机'
  if (configEditTarget.value === 'todo-rule') return '待办规则'
  if (configEditTarget.value === 'message-template') return '消息模板'
  if (configEditTarget.value === 'tool-source') return '工具源'
  if (configEditTarget.value === 'material-review-point') return '业务资料审查点'
  return '字段映射'
})

const configDiffRows = computed(() => latestConfigDiff.value?.changed || [])
const publishImpactRows = computed(() => latestPublishResult.value?.impacts || [])
const integrationSummaryItems = computed(() => [
  { label: '字段总数', value: integrationContract.value.summary.total, tone: 'blue' },
  { label: '已对齐', value: integrationContract.value.summary.aligned, tone: 'green' },
  { label: '待确认', value: integrationContract.value.summary.pending, tone: 'orange' },
  { label: '阻塞项', value: integrationContract.value.summary.blockers, tone: 'red' }
])
const integrationModuleOptions = computed(() => [
  { label: '全部模块', value: 'all' as const },
  ...integrationContract.value.modules.map((item) => ({
    label: `${item.label}（${item.total}）`,
    value: item.module
  }))
])
const integrationStatusOptions: Array<{ label: string; value: IntegrationContractStatus | 'all' }> =
  [
    { label: '全部状态', value: 'all' },
    { label: '已对齐', value: '已对齐' },
    { label: '待后端确认', value: '待后端确认' },
    { label: '前端缺失', value: '前端缺失' },
    { label: '后端缺失', value: '后端缺失' },
    { label: '命名不一致', value: '命名不一致' }
  ]
const integrationRows = computed(() => integrationContract.value.fields)
const adminRuleDiffRows = computed(() => adminRuleDiff.value?.changes || [])
const adminRuleDiffSummaryItems = computed(() => {
  if (!adminRuleDiff.value) return []
  return [
    { label: '新增', value: adminRuleDiff.value.summary.added },
    { label: '变更', value: adminRuleDiff.value.summary.changed },
    { label: '移除', value: adminRuleDiff.value.summary.removed },
    { label: '需复核', value: adminRuleDiff.value.summary.warning }
  ]
})

const wizardOrgNameByRole = (role: ProjectWizardMemberRole) => {
  const fieldByRole: Record<ProjectWizardMemberRole, keyof typeof projectWizardForm> = {
    inspection: 'inspectionOrgName',
    contractor: 'contractorOrgName',
    ndt: 'ndtOrgName',
    owner: 'ownerOrgName'
  }
  return String(projectWizardForm[fieldByRole[role]] || '')
}
const wizardOrgOptions = (role: ProjectWizardMemberRole) => {
  const allowedTypes: Record<ProjectWizardMemberRole, string[]> = {
    inspection: ['inspection', 'supervision'],
    contractor: ['contractor'],
    ndt: ['ndt'],
    owner: ['owner']
  }
  return overview.value.orgUnits.filter(
    (org) => org.status === '启用' && allowedTypes[role].includes(org.type)
  )
}
const wizardUsersByRole = (role: ProjectWizardMemberRole) => {
  const orgName = wizardOrgNameByRole(role)
  const organization = wizardOrgOptions(role).find((org) => org.name === orgName)
  return overview.value.users.filter(
    (user) =>
      user.role === role && user.status === '启用' && userBelongsToOrganization(user, organization)
  )
}
const handleWizardOrgChange = (role: ProjectWizardMemberRole) => {
  const userId = projectWizardForm.memberUserIds[role]
  const user = overview.value.users.find((item) => item.id === userId)
  const organization = wizardOrgOptions(role).find((org) => org.name === wizardOrgNameByRole(role))
  if (user && !userBelongsToOrganization(user, organization)) {
    projectWizardForm.memberUserIds[role] = ''
  }
}

const formatConfigValue = (value?: unknown) => {
  if (Array.isArray(value)) return value.join(', ')
  if (value === true) return '是'
  if (value === false) return '否'
  if (value === undefined || value === null || value === '') return '-'
  return String(value)
}

const formatRuleDiffValue = (value: unknown) => {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-'
  if (value === true) return '是'
  if (value === false) return '否'
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const promptTemplateStatusLabel = (status?: PromptTemplate['status'] | string) => {
  const labels: Record<string, string> = {
    draft: '草稿',
    production: '生产',
    published: '已发布',
    active: '启用',
    retired: '已停用',
    草稿: '草稿',
    已发布: '已发布',
    已停用: '已停用'
  }
  return labels[status || ''] || status || '-'
}

const promptTemplateStatusType = (
  status?: PromptTemplate['status'] | string
): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  if (!status) return 'info'
  if (['production', 'published', 'active', '已发布', '启用'].includes(status)) return 'success'
  if (['draft', '草稿'].includes(status)) return 'warning'
  if (['retired', '已停用'].includes(status)) return 'info'
  return 'info'
}

const defaultPromptOutputSchema = () =>
  JSON.stringify(
    {
      type: 'ReviewFindingDraftList',
      fields: ['result', 'severity', 'ruleId', 'evidence', 'opinionDraft', 'manualConfirmItems']
    },
    null,
    2
  )

const defaultPromptTemplateText = {
  system:
    '你是 {{agentName}}，负责按 {{businessPackId}}/{{businessPackVersion}} 的监检业务判断规则，对项目节点资料进行证据化审查。只输出基于规则和证据的审查建议，不替代人工最终确认。',
  user: '{{basePromptJson}}\n\n请基于以下审查任务生成结构化预审结果：\n{{reviewTaskJson}}',
  planner:
    '按固定计划执行：1. 读取项目、节点、业务规则上下文；2. 对齐 OCR 字段和资料证据；3. 执行确定性规则；4. 检索标准规范和项目文件知识库；5. 生成可追溯审查建议；6. 标注需人工确认项。',
  critic:
    '复核输出时检查三点：每条结论必须有规则依据；每条证据必须能追溯到文件或字段；缺证据时只能给出补充材料或人工确认建议。'
} as const

const parsePromptSchema = () => {
  const text = promptTemplateForm.outputSchemaText.trim()
  if (!text) return undefined
  try {
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      ElMessage.warning('输出结构必须是 JSON 对象')
      return null
    }
    return parsed as Record<string, unknown>
  } catch {
    ElMessage.warning('输出结构不是有效 JSON')
    return null
  }
}

const resetPromptTemplateForm = (template?: PromptTemplate) => {
  promptTemplateForm.id = template?.id || ''
  promptTemplateForm.name = template?.name || '工程监检审查 Prompt 模板'
  promptTemplateForm.promptKey = template?.promptKey || 'review_prompt'
  promptTemplateForm.version = template?.version || '2026.06'
  promptTemplateForm.status = template?.status || 'draft'
  promptTemplateForm.riskLevel = template?.riskLevel || 'high'
  promptTemplateForm.businessPackId = template?.businessPackId || DEFAULT_PIPELINE_BUSINESS_PACK_ID
  promptTemplateForm.agentId = template?.agentId || 'compliance_review_agent'
  promptTemplateForm.promptVersionId = template?.promptVersionId || 'PROMPT-review-202606'
  promptTemplateForm.systemPrompt = template?.systemPrompt || defaultPromptTemplateText.system
  promptTemplateForm.userPromptTemplate =
    template?.userPromptTemplate || defaultPromptTemplateText.user
  promptTemplateForm.plannerPromptTemplate =
    template?.plannerPromptTemplate || defaultPromptTemplateText.planner
  promptTemplateForm.criticPromptTemplate =
    template?.criticPromptTemplate || defaultPromptTemplateText.critic
  promptTemplateForm.outputSchemaText = template?.outputSchema
    ? JSON.stringify(template.outputSchema, null, 2)
    : defaultPromptOutputSchema()
  promptTemplateForm.etag = template?.etag || ''
  promptTemplateOperationError.value = ''
}

const buildPromptTemplatePayload = (): PromptTemplateSavePayload | null => {
  if (!promptTemplateForm.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return null
  }
  if (!promptTemplateForm.systemPrompt.trim() || !promptTemplateForm.userPromptTemplate.trim()) {
    ElMessage.warning('请填写 System Prompt 和 User Prompt')
    return null
  }
  const outputSchema = parsePromptSchema()
  if (outputSchema === null) return null
  return {
    name: promptTemplateForm.name.trim(),
    promptKey: promptTemplateForm.promptKey.trim() || 'review_prompt',
    version: promptTemplateForm.version.trim() || '2026.06',
    status: promptTemplateForm.status,
    riskLevel: promptTemplateForm.riskLevel.trim() || 'high',
    businessPackId: promptTemplateForm.businessPackId.trim() || DEFAULT_PIPELINE_BUSINESS_PACK_ID,
    agentId: promptTemplateForm.agentId.trim() || 'compliance_review_agent',
    promptVersionId: promptTemplateForm.promptVersionId.trim() || undefined,
    systemPrompt: promptTemplateForm.systemPrompt,
    userPromptTemplate: promptTemplateForm.userPromptTemplate,
    plannerPromptTemplate: promptTemplateForm.plannerPromptTemplate,
    criticPromptTemplate: promptTemplateForm.criticPromptTemplate,
    outputSchema,
    variables: [
      'agentName',
      'businessPackId',
      'businessPackVersion',
      'basePromptJson',
      'reviewTaskJson'
    ]
  }
}

const defaultReportSections = () =>
  JSON.stringify(
    [
      { code: 'project_summary', title: '项目概况', source: 'project' },
      { code: 'review_findings', title: '资料审查情况', source: 'review_findings' },
      { code: 'correction_summary', title: '补正闭环', source: 'corrections' },
      { code: 'evidence_refs', title: '证据引用', source: 'evidence_links' }
    ],
    null,
    2
  )

const resetReportTemplateForm = (template?: ReportTemplate) => {
  reportTemplateForm.id = template?.id || ''
  reportTemplateForm.name = template?.name || '工程监检资料审查报告'
  reportTemplateForm.version = template?.version || '2026.06'
  reportTemplateForm.status = template?.status || 'draft'
  reportTemplateForm.businessPackId = template?.businessPackId || DEFAULT_PIPELINE_BUSINESS_PACK_ID
  reportTemplateForm.businessPackVersion = template?.businessPackVersion || '2026.06'
  reportTemplateForm.exportTypes = template?.exportTypes?.length
    ? [...template.exportTypes]
    : ['report']
  reportTemplateForm.sectionsText = template?.sections
    ? JSON.stringify(template.sections, null, 2)
    : defaultReportSections()
  reportTemplateForm.etag = template?.etag || ''
  reportTemplateOperationError.value = ''
}

const buildReportTemplatePayload = (): ReportTemplateSavePayload | null => {
  if (!reportTemplateForm.name.trim()) {
    ElMessage.warning('请填写报告模板名称')
    return null
  }
  if (!reportTemplateForm.exportTypes.length) {
    ElMessage.warning('请至少选择一种导出类型')
    return null
  }
  try {
    const sections = JSON.parse(reportTemplateForm.sectionsText)
    if (
      !Array.isArray(sections) ||
      !sections.length ||
      sections.some(
        (item) =>
          !item ||
          typeof item !== 'object' ||
          typeof item.code !== 'string' ||
          !item.code.trim() ||
          typeof item.title !== 'string' ||
          !item.title.trim()
      )
    ) {
      ElMessage.warning('章节 JSON 必须是非空数组，每项必须包含 code 和 title')
      return null
    }
    return {
      name: reportTemplateForm.name.trim(),
      version: reportTemplateForm.version.trim() || '2026.06',
      status: reportTemplateForm.status,
      businessPackId: reportTemplateForm.businessPackId.trim() || DEFAULT_PIPELINE_BUSINESS_PACK_ID,
      businessPackVersion: reportTemplateForm.businessPackVersion.trim() || undefined,
      exportTypes: [...reportTemplateForm.exportTypes],
      sections: sections.map((item) => ({
        code: String(item.code).trim(),
        title: String(item.title).trim(),
        source: String(item.source || '').trim()
      }))
    }
  } catch {
    ElMessage.warning('章节配置不是有效 JSON')
    return null
  }
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

const integrationStatusTagType = (
  status: IntegrationContractStatus
): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  if (status === '已对齐') return 'success'
  if (status === '前端缺失' || status === '后端缺失') return 'danger'
  if (status === '待后端确认' || status === '命名不一致') return 'warning'
  return 'info'
}

const integrationSeverityLabel = (severity: IntegrationContractField['severity']) => {
  if (severity === 'danger') return '阻塞'
  if (severity === 'warning') return '需确认'
  return '信息'
}

const integrationSeverityTagType = (
  severity: IntegrationContractField['severity']
): 'primary' | 'success' | 'warning' | 'danger' | 'info' => {
  if (severity === 'danger') return 'danger'
  if (severity === 'warning') return 'warning'
  return 'info'
}

const formatFileSize = (size?: number) => {
  if (!size) return '-'
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
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

const loadAuditLogs = async () => {
  auditLoading.value = true
  auditError.value = ''
  try {
    const res = await getAuditLogsApi({
      keyword: auditFilters.keyword || undefined,
      result: auditFilters.result || undefined,
      objectType: auditFilters.objectType || undefined,
      page: auditPagination.page,
      pageSize: auditPagination.pageSize
    })
    if (!res) {
      auditError.value = getRequestErrorMessage(undefined, '审计日志加载失败，筛选条件已保留。')
      return
    }
    auditIntegrity.value = res.data.integrity
    auditLogs.value = applyPagination(auditPagination, res.data)
  } catch (error) {
    auditError.value = getRequestErrorMessage(error, '审计日志加载失败，筛选条件已保留。')
  } finally {
    auditLoading.value = false
  }
}

const loadPromptTemplates = async () => {
  promptTemplateLoading.value = true
  promptTemplateError.value = ''
  try {
    const res = await listPromptTemplatesApi({
      keyword: promptTemplateFilters.keyword || undefined,
      status: promptTemplateFilters.status || undefined,
      page: tableStates.promptTemplates.page,
      pageSize: tableStates.promptTemplates.pageSize
    })
    if (!res) {
      promptTemplateError.value = getRequestErrorMessage(
        undefined,
        'Prompt 模板列表加载失败，已保留当前筛选条件。'
      )
      return
    }
    promptTemplates.value = applyPagination(tableStates.promptTemplates, res.data)
  } catch (error) {
    promptTemplateError.value = getRequestErrorMessage(
      error,
      'Prompt 模板列表加载失败，已保留当前筛选条件。'
    )
  } finally {
    promptTemplateLoading.value = false
  }
}

const handlePromptTemplateFilter = () => {
  tableStates.promptTemplates.page = 1
  loadPromptTemplates()
}

const handlePromptTemplateSortChange = (event: { prop?: string; order?: TableSortOrder }) => {
  tableStates.promptTemplates.prop = event.prop || ''
  tableStates.promptTemplates.order = event.order || null
}

const openPromptTemplateDialog = (template?: PromptTemplate) => {
  promptTemplateDialogMode.value = template ? 'edit' : 'create'
  resetPromptTemplateForm(template)
  promptTemplateDialogVisible.value = true
}

const handleSavePromptTemplate = async () => {
  const payload = buildPromptTemplatePayload()
  if (!payload) return
  promptTemplateSaving.value = true
  promptTemplateOperationError.value = ''
  try {
    const res =
      promptTemplateDialogMode.value === 'create'
        ? await createPromptTemplateApi(payload)
        : await updatePromptTemplateApi(promptTemplateForm.id, payload, {
            etag: promptTemplateForm.etag
          })
    if (!res) {
      promptTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('Prompt 模板保存')
      )
      return
    }
    ElMessage.success(
      promptTemplateDialogMode.value === 'create' ? 'Prompt 模板已新增' : 'Prompt 模板已保存'
    )
    promptTemplateDialogVisible.value = false
    await Promise.all([loadPromptTemplates(), loadAuditLogs()])
  } catch (error) {
    promptTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('Prompt 模板保存')
    )
  } finally {
    promptTemplateSaving.value = false
  }
}

const handlePublishPromptTemplate = async (template: PromptTemplate) => {
  promptTemplateSaving.value = true
  promptTemplateOperationError.value = ''
  try {
    const res = await publishPromptTemplateApi(
      template.id,
      { reason: '后台发布 Prompt 模板。' },
      { etag: template.etag }
    )
    if (!res) {
      promptTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('Prompt 模板发布')
      )
      return
    }
    ElMessage.success('Prompt 模板已发布')
    await Promise.all([loadPromptTemplates(), loadAuditLogs()])
  } catch (error) {
    promptTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('Prompt 模板发布')
    )
  } finally {
    promptTemplateSaving.value = false
  }
}

const handleDeletePromptTemplate = async (template: PromptTemplate) => {
  try {
    await ElMessageBox.confirm(
      `确认删除 Prompt 模板「${template.name}」？生产状态模板不能删除。`,
      '删除 Prompt 模板',
      { type: 'warning' }
    )
  } catch {
    return
  }
  promptTemplateSaving.value = true
  promptTemplateOperationError.value = ''
  try {
    const res = await deletePromptTemplateApi(template.id, { etag: template.etag })
    if (!res) {
      promptTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('Prompt 模板删除')
      )
      return
    }
    ElMessage.success('Prompt 模板已删除')
    await Promise.all([loadPromptTemplates(), loadAuditLogs()])
  } catch (error) {
    promptTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('Prompt 模板删除')
    )
  } finally {
    promptTemplateSaving.value = false
  }
}

const loadReportTemplates = async () => {
  reportTemplateLoading.value = true
  reportTemplateError.value = ''
  try {
    const res = await listReportTemplatesApi({
      keyword: reportTemplateFilters.keyword || undefined,
      status: reportTemplateFilters.status || undefined,
      page: tableStates.reportTemplates.page,
      pageSize: tableStates.reportTemplates.pageSize
    })
    if (!res) {
      reportTemplateError.value = getRequestErrorMessage(
        undefined,
        '报告模板列表加载失败，已保留当前筛选条件。'
      )
      return
    }
    reportTemplates.value = applyPagination(tableStates.reportTemplates, res.data)
  } catch (error) {
    reportTemplateError.value = getRequestErrorMessage(
      error,
      '报告模板列表加载失败，已保留当前筛选条件。'
    )
  } finally {
    reportTemplateLoading.value = false
  }
}

const handleReportTemplateFilter = () => {
  tableStates.reportTemplates.page = 1
  loadReportTemplates()
}

const handleReportTemplateSortChange = (event: { prop?: string; order?: TableSortOrder }) => {
  tableStates.reportTemplates.prop = event.prop || ''
  tableStates.reportTemplates.order = event.order || null
}

const openReportTemplateDialog = (template?: ReportTemplate) => {
  reportTemplateDialogMode.value = template
    ? reportTemplateLocked(template.status)
      ? 'view'
      : 'edit'
    : 'create'
  resetReportTemplateForm(template)
  reportTemplateDialogVisible.value = true
}

const handleSaveReportTemplate = async () => {
  const payload = buildReportTemplatePayload()
  if (!payload) return
  reportTemplateSaving.value = true
  reportTemplateOperationError.value = ''
  try {
    const res =
      reportTemplateDialogMode.value === 'create'
        ? await createReportTemplateApi(payload)
        : await updateReportTemplateApi(reportTemplateForm.id, payload, {
            etag: reportTemplateForm.etag
          })
    if (!res) {
      reportTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('报告模板保存')
      )
      return
    }
    ElMessage.success(
      reportTemplateDialogMode.value === 'create' ? '报告模板已新增' : '报告模板已保存'
    )
    reportTemplateDialogVisible.value = false
    await Promise.all([loadReportTemplates(), loadAuditLogs()])
  } catch (error) {
    reportTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('报告模板保存')
    )
  } finally {
    reportTemplateSaving.value = false
  }
}

const handlePublishReportTemplate = async (template: ReportTemplate) => {
  reportTemplateSaving.value = true
  reportTemplateOperationError.value = ''
  try {
    const res = await publishReportTemplateApi(
      template.id,
      { reason: '后台发布报告模板。' },
      { etag: template.etag }
    )
    if (!res) {
      reportTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('报告模板发布')
      )
      return
    }
    ElMessage.success('报告模板已发布并用于后续报告生成')
    await Promise.all([loadReportTemplates(), loadAuditLogs()])
  } catch (error) {
    reportTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('报告模板发布')
    )
  } finally {
    reportTemplateSaving.value = false
  }
}

const handleDeleteReportTemplate = async (template: ReportTemplate) => {
  try {
    await ElMessageBox.confirm(
      `确认删除报告模板「${template.name}」？生产状态模板不能删除。`,
      '删除报告模板',
      { type: 'warning' }
    )
  } catch {
    return
  }
  reportTemplateSaving.value = true
  reportTemplateOperationError.value = ''
  try {
    const res = await deleteReportTemplateApi(template.id, { etag: template.etag })
    if (!res) {
      reportTemplateOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('报告模板删除')
      )
      return
    }
    ElMessage.success('报告模板已删除')
    await Promise.all([loadReportTemplates(), loadAuditLogs()])
  } catch (error) {
    reportTemplateOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('报告模板删除')
    )
  } finally {
    reportTemplateSaving.value = false
  }
}

const loadProjectDetail = async (projectId: string) => {
  projectDetailLoading.value = true
  projectDetailError.value = ''
  try {
    const res = await getAdminProjectDetailApi(projectId)
    if (!res) {
      projectDetailError.value = getRequestErrorMessage(
        undefined,
        '项目详情加载失败，已保留当前项目列表。'
      )
      return
    }
    projectDetail.value = res.data
  } catch (error) {
    projectDetailError.value = getRequestErrorMessage(
      error,
      '项目详情加载失败，已保留当前项目列表。'
    )
  } finally {
    projectDetailLoading.value = false
  }
}

const handleOpenProjectDetail = async (row: Project) => {
  projectDrawerVisible.value = true
  projectDetailProjectId.value = row.id
  projectDetail.value = null
  selectedExportTask.value = null
  await loadProjectDetail(row.id)
}

const loadProjects = async () => {
  projectsLoading.value = true
  projectOperationError.value = ''
  try {
    const res = await listAdminProjectsApi({
      page: tableStates.projects.page,
      pageSize: tableStates.projects.pageSize,
      keyword: projectFilters.keyword.trim() || undefined,
      status: projectFilters.status || undefined
    })
    if (!res) {
      projectOperationError.value = getRequestErrorMessage(
        undefined,
        '项目列表加载失败，已保留当前筛选条件。'
      )
      return false
    }
    projects.value = applyPagination(tableStates.projects, res.data)
    return true
  } catch (error) {
    projectOperationError.value = getRequestErrorMessage(
      error,
      '项目列表加载失败，已保留当前筛选条件。'
    )
    return false
  } finally {
    projectsLoading.value = false
  }
}

const loadIntegrationContract = async () => {
  integrationLoading.value = true
  integrationError.value = ''
  try {
    const res = await getAdminIntegrationContractApi({
      module: integrationModuleFilter.value,
      status: integrationStatusFilter.value
    })
    if (!res) {
      integrationError.value = getRequestErrorMessage(
        undefined,
        '联调字段差异清单加载失败，配置管理数据已保留。'
      )
      return
    }
    integrationContract.value = res.data
  } catch (error) {
    integrationError.value = getRequestErrorMessage(
      error,
      '联调字段差异清单加载失败，配置管理数据已保留。'
    )
  } finally {
    integrationLoading.value = false
  }
}

const loadData = async () => {
  loading.value = true
  overviewError.value = ''
  try {
    const tabRequest =
      activeTab.value === 'projects'
        ? loadProjects()
        : activeTab.value === 'audit'
          ? loadAuditLogs()
          : activeTab.value === 'integration'
            ? loadIntegrationContract()
            : activeTab.value === 'prompt-template'
              ? loadPromptTemplates()
              : activeTab.value === 'report-template'
                ? loadReportTemplates()
                : Promise.resolve(true)
    const [tabResult, configRes] = await Promise.all([tabRequest, getAdminConfigOverviewApi()])
    if (configRes) {
      const nextOverview = { ...configRes.data }
      nextOverview.materialReviewPoints = nextOverview.materialReviewPoints || []
      if (!nextOverview.businessPacks?.length) {
        const businessPackRes = await listBusinessPacksApi().catch(() => undefined)
        if (businessPackRes) nextOverview.businessPacks = businessPackRes.data
      }
      overview.value = nextOverview
    }
    if (tabResult === false || !configRes) {
      overviewError.value = getRequestErrorMessage(
        undefined,
        '管理后台基础数据加载失败，已保留上一次可用数据。'
      )
      return
    }
  } catch (error) {
    overviewError.value = getRequestErrorMessage(
      error,
      '管理后台基础数据加载失败，已保留上一次可用数据。'
    )
  } finally {
    loading.value = false
  }
}

const handleIntegrationFilterChange = () => {
  resetTablePage('integration')
  loadIntegrationContract()
}

const handleProjectFilter = () => {
  tableStates.projects.page = 1
  loadProjects()
}

const handleProjectReset = () => {
  projectFilters.keyword = ''
  projectFilters.status = ''
  tableStates.projects.page = 1
  loadProjects()
}

const handleProjectPageChange = (page: number) => {
  tableStates.projects.page = page
  loadProjects()
}

const handleProjectPageSizeChange = (pageSize: number) => {
  tableStates.projects.page = 1
  tableStates.projects.pageSize = pageSize
  loadProjects()
}

const handleValidateBusinessPacks = async () => {
  businessPackValidating.value = true
  businessPackValidationError.value = ''
  try {
    const res = await validateAllBusinessPacksApi()
    if (!res) {
      businessPackValidationError.value = getRequestErrorMessage(
        undefined,
        '业务类型校验失败，已保留当前配置列表。'
      )
      return
    }
    businessPackValidation.value = res.data
    ElMessage.success(res.data.ok ? '业务类型校验通过' : '业务类型存在校验错误')
  } catch (error) {
    businessPackValidationError.value = getRequestErrorMessage(
      error,
      '业务类型校验失败，已保留当前配置列表。'
    )
  } finally {
    businessPackValidating.value = false
  }
}

const resetProjectWizardForm = () => {
  projectWizardForm.businessPackId =
    businessPackRows.value.find((pack) => pack.id === DEFAULT_PIPELINE_BUSINESS_PACK_ID)?.id ||
    businessPackRows.value[0]?.id ||
    DEFAULT_PIPELINE_BUSINESS_PACK_ID
  projectWizardForm.code = ''
  projectWizardForm.name = ''
  projectWizardForm.region = ''
  applyBusinessPackDefaultsToWizard()
  ;(['inspection', 'contractor', 'ndt', 'owner'] as ProjectWizardMemberRole[]).forEach((role) => {
    projectWizardForm.memberUserIds[role] = ''
  })
}

const applyBusinessPackDefaultsToWizard = () => {
  const pack = selectedWizardBusinessPack.value
  projectWizardForm.type = projectTypeForPack(pack)
  projectWizardForm.ownerOrgName = ''
  projectWizardForm.contractorOrgName = ''
  projectWizardForm.ndtOrgName = ''
  projectWizardForm.inspectionOrgName = ''
  ;(['inspection', 'contractor', 'ndt', 'owner'] as ProjectWizardMemberRole[]).forEach((role) => {
    projectWizardForm.memberUserIds[role] = ''
  })
}

const handleWizardBusinessPackChange = () => {
  applyBusinessPackDefaultsToWizard()
}

const openProjectWizard = () => {
  resetProjectWizardForm()
  projectWizardStep.value = 0
  projectWizardError.value = ''
  projectWizardVisible.value = true
}

const validateProjectWizardStep = () => {
  if (projectWizardStep.value === 0) {
    if (!projectWizardForm.businessPackId) {
      ElMessage.warning('请选择压力管道类别')
      return false
    }
    if (!projectWizardForm.type.trim()) {
      projectWizardForm.type = projectTypeForPack(selectedWizardBusinessPack.value)
    }
    if (!projectWizardForm.name.trim()) {
      ElMessage.warning('请填写项目名称')
      return false
    }
    if (!projectWizardForm.type.trim()) {
      ElMessage.warning('项目类型生成失败，请重新选择压力管道类别')
      return false
    }
  }
  if (projectWizardStep.value === 1) {
    const orgNames = projectWizardRoles.value.map(wizardOrgNameByRole)
    if (orgNames.some((name) => !name.trim())) {
      ElMessage.warning('请补齐参建单位')
      return false
    }
    const unavailableRole = findFirstRoleWithoutCandidates(
      projectWizardRoles.value,
      wizardUsersByRole
    )
    if (unavailableRole) {
      ElMessage.warning(
        missingWizardMemberMessage(roleLabel(unavailableRole), wizardOrgNameByRole(unavailableRole))
      )
      return false
    }
  }
  if (projectWizardStep.value === 2) {
    if (projectWizardRoles.value.some((role) => !projectWizardForm.memberUserIds[role])) {
      ElMessage.warning('请为业务类型要求的角色选择初始成员')
      return false
    }
  }
  return true
}

const handleProjectWizardNext = () => {
  if (!validateProjectWizardStep()) return
  projectWizardStep.value = Math.min(projectWizardStep.value + 1, 2)
}

const handleCreateProject = async () => {
  if (!validateProjectWizardStep()) return
  const payload: AdminProjectCreatePayload = {
    code: projectWizardForm.code || undefined,
    businessPackId: projectWizardForm.businessPackId,
    name: projectWizardForm.name,
    type: projectWizardForm.type,
    region: projectWizardForm.region,
    ownerOrgName: projectWizardForm.ownerOrgName,
    contractorOrgName: projectWizardForm.contractorOrgName,
    ndtOrgName: projectWizardForm.ndtOrgName,
    inspectionOrgName: projectWizardForm.inspectionOrgName,
    memberUserIds: Object.fromEntries(
      projectWizardRoles.value.map((role) => [role, projectWizardForm.memberUserIds[role]])
    )
  }
  projectCreating.value = true
  projectWizardError.value = ''
  try {
    const res = await createAdminProjectApi(payload)
    if (!res) {
      projectWizardError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目立项')
      )
      return
    }
    ElMessage.success(`项目已立项：${res.data.project.name}`)
    projectWizardVisible.value = false
    projectDrawerVisible.value = true
    selectedExportTask.value = null
    projectDetailProjectId.value = res.data.project.id
    projectDetail.value = res.data.detail
    await Promise.all([loadProjects(), loadAuditLogs()])
  } catch (error) {
    projectWizardError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目立项')
    )
  } finally {
    projectCreating.value = false
  }
}

const openProjectEditDialog = (row: Project) => {
  projectEditForm.id = row.id
  projectEditForm.code = row.code
  projectEditForm.name = row.name
  projectEditForm.type = row.type
  projectEditForm.region = row.region
  projectEditForm.ownerOrgName = row.ownerOrgName
  projectEditForm.contractorOrgName = row.contractorOrgName
  projectEditForm.ndtOrgName = row.ndtOrgName
  projectEditForm.inspectionOrgName = row.inspectionOrgName
  projectEditForm.status = row.status
  projectEditForm.etag = row.etag || ''
  projectOperationError.value = ''
  projectEditVisible.value = true
}

const handleSaveProjectEdit = async () => {
  if (!projectEditForm.name.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  projectSaving.value = true
  projectOperationError.value = ''
  try {
    const res = await updateAdminProjectApi(
      projectEditForm.id,
      {
        name: projectEditForm.name,
        type: projectEditForm.type,
        region: projectEditForm.region,
        ownerOrgName: projectEditForm.ownerOrgName,
        contractorOrgName: projectEditForm.contractorOrgName,
        ndtOrgName: projectEditForm.ndtOrgName,
        inspectionOrgName: projectEditForm.inspectionOrgName,
        status: projectEditForm.status
      },
      { etag: projectEditForm.etag }
    )
    if (!res) {
      projectOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目保存')
      )
      return
    }
    ElMessage.success('项目已保存')
    projectEditVisible.value = false
    await Promise.all([
      loadProjects(),
      loadAuditLogs(),
      projectDetailProjectId.value === projectEditForm.id
        ? loadProjectDetail(projectEditForm.id)
        : undefined
    ])
  } catch (error) {
    projectOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目保存')
    )
  } finally {
    projectSaving.value = false
  }
}

const handleDeleteProject = async (row: Project) => {
  try {
    await ElMessageBox.confirm(
      `确认删除或归档项目「${row.name}」？有业务数据的项目将自动归档。`,
      '项目删除/归档',
      { type: 'warning' }
    )
  } catch {
    return
  }
  projectSaving.value = true
  projectOperationError.value = ''
  try {
    const res = await deleteAdminProjectApi(row.id, { etag: row.etag })
    if (!res) {
      projectOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目删除/归档')
      )
      return
    }
    ElMessage.success(res.data.archived ? '项目已归档' : '项目已删除')
    if (projectDetailProjectId.value === row.id) {
      projectDrawerVisible.value = false
      projectDetailProjectId.value = ''
      projectDetail.value = null
    }
    await Promise.all([loadProjects(), loadAuditLogs()])
  } catch (error) {
    projectOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目删除/归档')
    )
  } finally {
    projectSaving.value = false
  }
}

const handleProjectCardCommand = async (command: string, row: Project) => {
  if (command === 'edit') {
    openProjectEditDialog(row)
    return
  }
  if (command === 'archive') {
    await handleDeleteProject(row)
  }
}

const resetOrgForm = () => {
  orgForm.id = ''
  orgForm.name = ''
  orgForm.type = 'contractor'
  orgForm.contactName = ''
  orgForm.contactPhone = ''
  orgForm.status = '启用'
  orgForm.etag = ''
  orgOperationError.value = ''
}

const openOrgDialog = (row?: AdminOrgUnit) => {
  resetOrgForm()
  orgDialogMode.value = row ? 'edit' : 'create'
  if (row) {
    orgForm.id = row.id
    orgForm.name = row.name
    orgForm.type = row.type
    orgForm.contactName = row.contactName
    orgForm.contactPhone = row.contactPhone
    orgForm.status = row.status
    orgForm.etag = row.etag || ''
  }
  orgDialogVisible.value = true
}

const handleSaveOrg = async () => {
  if (!orgForm.name.trim()) {
    ElMessage.warning('请填写组织名称')
    return
  }
  orgSaving.value = true
  orgOperationError.value = ''
  try {
    const payload = {
      name: orgForm.name,
      type: orgForm.type,
      contactName: orgForm.contactName,
      contactPhone: orgForm.contactPhone,
      status: orgForm.status
    }
    const res =
      orgDialogMode.value === 'create'
        ? await createAdminOrgUnitApi(payload, { etag: overview.value.etag })
        : await updateAdminOrgUnitApi(orgForm.id, payload, { etag: orgForm.etag })
    if (!res) {
      orgOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('组织保存')
      )
      return
    }
    ElMessage.success(orgDialogMode.value === 'create' ? '组织已新增' : '组织已保存')
    orgDialogVisible.value = false
    await Promise.all([loadData(), loadAuditLogs()])
  } catch (error) {
    orgOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('组织保存')
    )
  } finally {
    orgSaving.value = false
  }
}

const handleDeleteOrg = async (row: AdminOrgUnit) => {
  try {
    await ElMessageBox.confirm(
      `确认删除组织「${row.name}」？仍被引用时后端会拒绝删除。`,
      '删除组织',
      {
        type: 'warning'
      }
    )
  } catch {
    return
  }
  orgSaving.value = true
  orgOperationError.value = ''
  try {
    const res = await deleteAdminOrgUnitApi(row.id, { etag: row.etag })
    if (!res) {
      orgOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('组织删除')
      )
      return
    }
    ElMessage.success('组织已删除')
    await Promise.all([loadData(), loadAuditLogs()])
  } catch (error) {
    orgOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('组织删除')
    )
  } finally {
    orgSaving.value = false
  }
}

const resetUserForm = () => {
  userForm.id = ''
  userForm.username = ''
  userForm.name = ''
  userForm.mobile = ''
  userForm.role = 'contractor'
  userForm.orgId = ''
  userForm.status = '启用'
  userForm.password = ''
  userForm.etag = ''
  userOperationError.value = ''
}

const openUserDialog = (row?: AdminUser) => {
  resetUserForm()
  userDialogMode.value = row ? 'edit' : 'create'
  if (row) {
    userForm.id = row.id
    userForm.username = row.username
    userForm.name = row.name
    userForm.mobile = row.mobile
    userForm.role = row.role
    userForm.orgId =
      row.orgId || overview.value.orgUnits.find((org) => org.name === row.orgName)?.id || ''
    userForm.status = row.status
    userForm.etag = row.etag || ''
  } else {
    userForm.password = DEFAULT_INITIAL_PASSWORD
  }
  userDialogVisible.value = true
}

const handleUserRoleChange = () => {
  if (!roleOrgOptions(userForm.role).some((org) => org.id === userForm.orgId)) {
    userForm.orgId = ''
  }
}

const handleSaveUser = async () => {
  if (!userForm.username.trim() || !userForm.name.trim()) {
    ElMessage.warning('请填写用户名和姓名')
    return
  }
  const org = overview.value.orgUnits.find((item) => item.id === userForm.orgId)
  if (businessRoleOrgTypes[userForm.role] && !org) {
    ElMessage.warning('该角色必须绑定组织')
    return
  }
  const initialPassword =
    userDialogMode.value === 'create'
      ? userForm.password.trim() || DEFAULT_INITIAL_PASSWORD
      : userForm.password.trim()
  if (initialPassword) {
    const classes = [
      /[a-z]/.test(initialPassword),
      /[A-Z]/.test(initialPassword),
      /\d/.test(initialPassword),
      /[^A-Za-z0-9]/.test(initialPassword)
    ]
    if (
      initialPassword.length < 12 ||
      classes.filter(Boolean).length < 3 ||
      initialPassword.toLowerCase().includes(userForm.username.toLowerCase())
    ) {
      ElMessage.warning('密码至少 12 位、包含三类字符且不得包含用户名')
      return
    }
  }
  userSaving.value = true
  userOperationError.value = ''
  try {
    const payload = {
      username: userForm.username,
      name: userForm.name,
      mobile: userForm.mobile,
      role: userForm.role,
      orgId: userForm.orgId || undefined,
      orgName: org?.name,
      status: userForm.status,
      password: userDialogMode.value === 'create' ? initialPassword : initialPassword || undefined
    }
    const res =
      userDialogMode.value === 'create'
        ? await createAdminUserApi(payload, { etag: overview.value.etag })
        : await updateAdminUserApi(userForm.id, payload, { etag: userForm.etag })
    if (!res) {
      userOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('用户保存')
      )
      return
    }
    ElMessage.success(userDialogMode.value === 'create' ? '用户已新增' : '用户已保存')
    userDialogVisible.value = false
    await Promise.all([loadData(), loadAuditLogs()])
  } catch (error) {
    userOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('用户保存')
    )
  } finally {
    userSaving.value = false
  }
}

const handleDeleteUser = async (row: AdminUser) => {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.name}」？如用户已有项目授权，后端会转为停用。`,
      '删除用户',
      { type: 'warning' }
    )
  } catch {
    return
  }
  userSaving.value = true
  userOperationError.value = ''
  try {
    const res = await deleteAdminUserApi(row.id, { etag: row.etag })
    if (!res) {
      userOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('用户删除')
      )
      return
    }
    ElMessage.success(res.data.deleted ? '用户已删除' : '用户已停用')
    await Promise.all([loadData(), loadAuditLogs()])
  } catch (error) {
    userOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('用户删除')
    )
  } finally {
    userSaving.value = false
  }
}

const handleExportConfig = async () => {
  configExporting.value = true
  adminActionError.value = ''
  adminActionRetry.value = null
  try {
    const res = await createAdminConfigExportApi({
      scope: 'all',
      includeAudit: true,
      reason: '管理后台导出配置包。'
    })
    if (!res) {
      adminActionError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('配置包导出')
      )
      adminActionRetry.value = 'export'
      return
    }
    selectedExportTask.value = res.data.task
    ElMessage.success(`配置包已生成：${res.data.task.fileName}`)
    await loadAuditLogs()
  } catch (error) {
    adminActionError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('配置包导出')
    )
    adminActionRetry.value = 'export'
  } finally {
    configExporting.value = false
  }
}

const handlePublishConfig = async () => {
  let reason = ''
  try {
    const promptResult = await ElMessageBox.prompt(
      `将发布“${adminPageTitle.value}”相关配置。请填写发布原因，系统会先计算影响范围。`,
      '发布配置',
      {
        confirmButtonText: '生成影响预览',
        cancelButtonText: '取消',
        inputPlaceholder: '例如：完成权限矩阵复核，申请发布',
        inputValidator: (value) => Boolean(value.trim()) || '必须填写发布原因'
      }
    )
    reason = promptResult.value.trim()
  } catch {
    return
  }

  configPublishing.value = true
  adminActionError.value = ''
  adminActionRetry.value = null
  try {
    const previewResponse = await previewAdminConfigPublishApi({
      scope: adminPublishScope.value,
      reason
    })
    const preview = previewResponse?.data
    if (!preview) {
      throw new Error('影响预览未返回有效数据。')
    }
    const impact = preview.impact
    const warningText = impact.warnings.length ? `\n警告：${impact.warnings.join('；')}` : ''
    try {
      await ElMessageBox.confirm(
        `将发布 ${impact.totalAffected} 项配置，关联 ${impact.linkedProjects} 个未归档项目。${warningText}\n预览有效期至 ${preview.expiresAt}。`,
        '确认发布影响',
        {
          type: impact.warnings.length ? 'warning' : 'info',
          confirmButtonText: '确认发布',
          cancelButtonText: '返回检查'
        }
      )
    } catch {
      return
    }
    const res = await publishAdminConfigApi(
      {
        scope: adminPublishScope.value,
        reason,
        previewId: preview.previewId
      },
      { etag: overview.value.etag }
    )
    if (!res) {
      adminActionError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('配置发布')
      )
      adminActionRetry.value = 'publish'
      return
    }
    latestPublishResult.value = res.data
    ElMessage.success(`配置已发布：${res.data.version}`)
    await Promise.all([loadAuditLogs(), loadData()])
  } catch (error) {
    adminActionError.value = getRequestErrorMessage(error, buildOperationFailureMessage('配置发布'))
    adminActionRetry.value = 'publish'
  } finally {
    configPublishing.value = false
  }
}

const retryAdminAction = () => {
  if (adminActionRetry.value === 'export') {
    handleExportConfig()
    return
  }
  if (adminActionRetry.value === 'publish') {
    handlePublishConfig()
  }
}

const openPermissionConfig = (row: PermissionConfigRow) => {
  configEditTarget.value = 'permission'
  configEditMode.value = 'edit'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row.role
  configForm.role = row.role
  configForm.label = row.label
  configForm.projectScope = row.projectScope
  configForm.nodeScope = row.nodeScope
  configForm.actions = [...row.actions]
  configForm.readonly = row.readonly
  configForm.reason = '调整角色权限矩阵。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const openNodeTemplateConfig = (row: NodeTemplateConfigRow) => {
  configEditTarget.value = 'node-template'
  configEditMode.value = 'edit'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row.id
  configForm.version = row.version
  configForm.groupName = row.groupName
  configForm.nodeCount = row.nodeCount
  configForm.requiredCount = row.requiredCount
  configForm.nodeTemplateStatus = row.status
  configForm.reason = '调整节点模板配置。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const openWorkflowConfig = (row: WorkflowConfigRow) => {
  configEditTarget.value = 'workflow'
  configEditMode.value = 'edit'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row.id
  configForm.workflowName = row.name
  configForm.version = row.version
  configForm.states = row.states
  configForm.transitions = row.transitions
  configForm.workflowStatus = row.status
  configForm.reason = '调整流程状态机配置。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const getRuleDiffTarget = (row: RuleVersionConfigRow) =>
  overview.value.ruleVersions.find(
    (item) => item.ruleKey === row.ruleKey && item.id !== row.id && item.status === '已发布'
  ) ||
  overview.value.ruleVersions.find((item) => item.ruleKey === row.ruleKey && item.id !== row.id)

const openRuleVersionDetail = (row: RuleVersionConfigRow) => {
  selectedRuleVersion.value = row
  ruleDetailDrawerVisible.value = true
}

const openRuleVersionDiff = async (row: RuleVersionConfigRow) => {
  selectedRuleVersion.value = row
  adminRuleDiff.value = null
  adminRuleDiffError.value = ''
  adminRuleDiffVisible.value = true
  adminRuleDiffLoading.value = true
  const target = getRuleDiffTarget(row)
  try {
    const res = await getKnowledgeRuleVersionDiffApi(row.id, {
      targetVersionId: target?.id,
      targetVersion: target?.version
    })
    if (!res) {
      adminRuleDiffError.value = getRequestErrorMessage(
        undefined,
        'AI业务规则版本差异加载失败，已保留AI业务规则版本列表。'
      )
      return
    }
    adminRuleDiff.value = res.data
  } catch (error) {
    adminRuleDiffError.value = getRequestErrorMessage(
      error,
      'AI业务规则版本差异加载失败，已保留AI业务规则版本列表。'
    )
  } finally {
    adminRuleDiffLoading.value = false
  }
}

const retryRuleVersionDiff = () => {
  if (selectedRuleVersion.value) {
    openRuleVersionDiff(selectedRuleVersion.value)
  }
}

const openTodoRuleConfig = (row?: TodoRuleConfigRow) => {
  configEditTarget.value = 'todo-rule'
  configEditMode.value = row ? 'edit' : 'create'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row?.id || ''
  configForm.todoRuleName = row?.name || ''
  configForm.triggerStatus = row?.triggerStatus || 'AI 预审中'
  configForm.assigneeRole = row?.assigneeRole || 'inspection'
  configForm.deadlineHours = row?.deadlineHours || 48
  configForm.fineEnabled = row?.enabled ?? true
  configForm.reason = row ? '调整待办规则。' : '新增待办规则。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const openMessageTemplateConfig = (row?: MessageTemplateConfigRow) => {
  configEditTarget.value = 'message-template'
  configEditMode.value = row ? 'edit' : 'create'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row?.id || ''
  configForm.scene = row?.scene || 'custom-scene'
  configForm.channel = row?.channel || '站内信'
  configForm.titleTemplate = row?.titleTemplate || ''
  configForm.contentTemplate = row?.contentTemplate || ''
  configForm.fineEnabled = row?.enabled ?? true
  configForm.reason = row ? '调整消息模板。' : '新增消息模板。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const openToolSourceConfig = (row?: ToolSourceConfigRow) => {
  configEditTarget.value = 'tool-source'
  configEditMode.value = row ? 'edit' : 'create'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row?.id || ''
  configForm.toolName = row?.name || ''
  configForm.toolType = row?.toolType || 'external-query'
  configForm.endpoint = row?.endpoint || ''
  configForm.authMode = row?.authMode || 'none'
  configForm.toolStatus = row?.status || '启用'
  configForm.reason = row ? '调整工具源。' : '新增工具源。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const openFieldMappingConfig = (row?: FieldMappingConfigRow) => {
  configEditTarget.value = 'field-mapping'
  configEditMode.value = row ? 'edit' : 'create'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row?.id || ''
  configForm.fieldNodeId = row?.nodeId || 16
  configForm.fieldName = row?.fieldName || ''
  configForm.sourceField = row?.sourceField || ''
  configForm.targetField = row?.targetField || ''
  configForm.fieldRequired = row?.required ?? true
  configForm.confidenceThreshold = row?.confidenceThreshold || 0.85
  configForm.reason = row ? '调整字段映射。' : '新增字段映射。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const splitReviewPointEvidenceItems = (text: string) =>
  text
    .split(/[、，,；;]/)
    .map((item) => item.trim())
    .filter(Boolean)

const materialReviewPointAuditContent = (row: MaterialReviewPointRow) =>
  row.fileContent || row.mappingRelation || '-'

const openMaterialReviewPointConfig = (row?: MaterialReviewPointRow) => {
  configEditTarget.value = 'material-review-point'
  configEditMode.value = row ? 'edit' : 'create'
  configOperationError.value = ''
  configOperationRetry.value = null
  configForm.id = row?.id || ''
  configForm.reviewPointBusinessPackId = row?.businessPackId || DEFAULT_PIPELINE_BUSINESS_PACK_ID
  configForm.reviewPointNodeId = row?.nodeId || 16
  configForm.reviewPointNodeName = row?.nodeName || ''
  configForm.reviewPointRuleId = row?.ruleId || ''
  configForm.reviewPointBusinessModule = row?.businessModule || ''
  configForm.reviewPointReviewClass = row?.reviewClass || 'C'
  configForm.reviewPointReviewContent = row?.reviewContent || ''
  configForm.reviewPointMaterialCategory = row?.materialCategory || ''
  configForm.reviewPointMaterialTypeCode = row?.materialTypeCode || ''
  configForm.reviewPointMaterialTypeName = row?.materialTypeName || ''
  configForm.reviewPointFileContent = row?.fileContent || ''
  configForm.reviewPointEvidenceItemText =
    row?.evidenceItemText || (row?.evidenceItems || []).join('、')
  configForm.reviewPointResponsibleParty = (row?.responsibleParty as RoleCode) || 'contractor'
  configForm.reviewPointRequiredType = row?.requiredType || '必传'
  configForm.reviewPointMappingRelation = row?.mappingRelation || 'OCR证据支撑'
  configForm.reviewPointMinConfidence = row?.minConfidence || 0.65
  configForm.fineEnabled = row?.enabled ?? true
  configForm.reason = row ? '调整业务资料审查点。' : '新增业务资料审查点。'
  latestConfigDiff.value = null
  configDrawerVisible.value = true
}

const buildAdminConfigChangePayload = (): AdminConfigChangePayload => {
  const reason = configForm.reason.trim()
  if (configEditTarget.value === 'permission') {
    return {
      target: 'permission',
      id: configForm.role,
      reason,
      values: {
        label: configForm.label,
        projectScope: configForm.projectScope,
        nodeScope: configForm.nodeScope,
        actions: [...configForm.actions],
        readonly: configForm.readonly
      }
    }
  }
  if (configEditTarget.value === 'node-template') {
    return {
      target: 'node-template',
      id: configForm.id,
      reason,
      values: {
        version: configForm.version,
        groupName: configForm.groupName,
        nodeCount: Number(configForm.nodeCount) || 0,
        requiredCount: Number(configForm.requiredCount) || 0,
        status: configForm.nodeTemplateStatus
      }
    }
  }
  if (configEditTarget.value === 'workflow') {
    return {
      target: 'workflow',
      id: configForm.id,
      reason,
      values: {
        name: configForm.workflowName,
        version: configForm.version,
        states: Number(configForm.states) || 0,
        transitions: Number(configForm.transitions) || 0,
        status: configForm.workflowStatus
      }
    }
  }
  if (configEditTarget.value === 'todo-rule') {
    return {
      target: 'todo-rule',
      id: configForm.id,
      reason,
      values: {
        name: configForm.todoRuleName,
        triggerStatus: configForm.triggerStatus,
        assigneeRole: configForm.assigneeRole,
        deadlineHours: Number(configForm.deadlineHours) || 0,
        enabled: configForm.fineEnabled
      }
    }
  }
  if (configEditTarget.value === 'message-template') {
    return {
      target: 'message-template',
      id: configForm.id,
      reason,
      values: {
        scene: configForm.scene,
        channel: configForm.channel,
        titleTemplate: configForm.titleTemplate,
        contentTemplate: configForm.contentTemplate,
        enabled: configForm.fineEnabled
      }
    }
  }
  if (configEditTarget.value === 'tool-source') {
    return {
      target: 'tool-source',
      id: configForm.id,
      reason,
      values: {
        name: configForm.toolName,
        toolType: configForm.toolType,
        endpoint: configForm.endpoint,
        authMode: configForm.authMode,
        status: configForm.toolStatus
      }
    }
  }
  if (configEditTarget.value === 'material-review-point') {
    const evidenceItems = splitReviewPointEvidenceItems(configForm.reviewPointEvidenceItemText)
    return {
      target: 'material-review-point',
      id: configForm.id,
      reason,
      values: {
        businessPackId: configForm.reviewPointBusinessPackId,
        nodeId: Number(configForm.reviewPointNodeId) || 1,
        nodeName: configForm.reviewPointNodeName,
        ruleId: configForm.reviewPointRuleId,
        businessModule: configForm.reviewPointBusinessModule,
        reviewClass: configForm.reviewPointReviewClass,
        reviewContent: configForm.reviewPointReviewContent,
        materialCategory: configForm.reviewPointMaterialCategory,
        materialTypeCode: configForm.reviewPointMaterialTypeCode,
        materialTypeName: configForm.reviewPointMaterialTypeName,
        fileContent: configForm.reviewPointFileContent,
        evidenceItemText: configForm.reviewPointEvidenceItemText,
        evidenceItems,
        responsibleParty: configForm.reviewPointResponsibleParty,
        responsiblePartyLabel: roleLabel(configForm.reviewPointResponsibleParty),
        requiredType: configForm.reviewPointRequiredType,
        mappingRelation: configForm.reviewPointMappingRelation,
        minConfidence: Number(configForm.reviewPointMinConfidence) || 0.65,
        enabled: configForm.fineEnabled
      }
    }
  }
  return {
    target: 'field-mapping',
    id: configForm.id,
    reason,
    values: {
      nodeId: Number(configForm.fieldNodeId) || 1,
      fieldName: configForm.fieldName,
      sourceField: configForm.sourceField,
      targetField: configForm.targetField,
      required: configForm.fieldRequired,
      confidenceThreshold: Number(configForm.confidenceThreshold) || 0.85
    }
  }
}

const buildAdminConfigCreatePayload = () => {
  const { id: _id, ...payload } = buildAdminConfigChangePayload()
  if (
    payload.target === 'permission' ||
    payload.target === 'node-template' ||
    payload.target === 'workflow'
  ) {
    return undefined
  }
  return payload
}

const canPreviewConfigDiff = computed(() => configEditMode.value === 'edit')

const handleSaveCreatedConfigItem = async () => {
  const payload = buildAdminConfigCreatePayload()
  if (!payload) {
    ElMessage.warning('该配置类型不支持新增')
    return false
  }
  const res = await createAdminConfigItemApi(payload, { etag: overview.value.etag })
  if (!res) {
    configOperationError.value = getRequestErrorMessage(
      undefined,
      buildOperationFailureMessage(`${configTargetLabel.value}新增`)
    )
    configOperationRetry.value = 'save'
    return false
  }
  overview.value = res.data.overview
  latestConfigDiff.value = res.data.diff
  configDiffVisible.value = true
  configDrawerVisible.value = false
  ElMessage.success(`${configTargetLabel.value}已新增`)
  await loadAuditLogs()
  return true
}

const ensureConfigReason = () => {
  if (configForm.reason.trim()) return true
  ElMessage.warning('请填写配置变更原因')
  return false
}

const handlePreviewConfigDiff = async () => {
  if (!ensureConfigReason()) return
  configPreviewing.value = true
  configOperationError.value = ''
  configOperationRetry.value = null
  try {
    const res = await previewAdminConfigDiffApi(buildAdminConfigChangePayload())
    if (!res) {
      configOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('配置差异预览')
      )
      configOperationRetry.value = 'preview'
      return
    }
    latestConfigDiff.value = res.data
    configDiffVisible.value = true
  } catch (error) {
    configOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('配置差异预览')
    )
    configOperationRetry.value = 'preview'
  } finally {
    configPreviewing.value = false
  }
}

const handleSaveConfigItem = async () => {
  if (!ensureConfigReason()) return
  configSaving.value = true
  configOperationError.value = ''
  configOperationRetry.value = null
  try {
    if (configEditMode.value === 'create') {
      await handleSaveCreatedConfigItem()
      return
    }
    const res = await saveAdminConfigItemApi(buildAdminConfigChangePayload(), {
      etag: overview.value.etag
    })
    if (!res) {
      configOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage(`${configTargetLabel.value}保存`)
      )
      configOperationRetry.value = 'save'
      return
    }
    overview.value = res.data.overview
    latestConfigDiff.value = res.data.diff
    configDiffVisible.value = true
    configDrawerVisible.value = false
    ElMessage.success(`${configTargetLabel.value}已保存`)
    await loadAuditLogs()
  } catch (error) {
    configOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage(`${configTargetLabel.value}保存`)
    )
    configOperationRetry.value = 'save'
  } finally {
    configSaving.value = false
  }
}

const handleDeleteMaterialReviewPoint = async (row: MaterialReviewPointRow) => {
  try {
    await ElMessageBox.confirm(
      `确认删除审查点「${row.reviewContent || row.materialTypeName}」？`,
      '删除业务资料审查点',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  configSaving.value = true
  configOperationError.value = ''
  try {
    const res = await deleteAdminConfigItemApi(
      { target: 'material-review-point', id: row.id },
      { etag: overview.value.etag }
    )
    if (!res) {
      configOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('业务资料审查点删除')
      )
      return
    }
    overview.value = res.data.overview
    ElMessage.success('业务资料审查点已删除')
    await loadAuditLogs()
  } catch (error) {
    configOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('业务资料审查点删除')
    )
  } finally {
    configSaving.value = false
  }
}

const retryConfigOperation = () => {
  if (configOperationRetry.value === 'preview') {
    handlePreviewConfigDiff()
    return
  }
  if (configOperationRetry.value === 'save') {
    handleSaveConfigItem()
  }
}

const getDefaultMemberUser = (role: RoleCode) =>
  batchMemberCandidateUsers.value.find((user) => user.role === role) ||
  overview.value.users.find((user) => user.role === role && user.status === '启用') ||
  overview.value.users[0]

const getDefaultBatchMemberUserIds = () => {
  const users = batchMemberCandidateUsers.value
  const notAuthorized = users
    .filter((user) => !selectedProjectMemberUserIds.value.has(user.id))
    .map((user) => user.id)
  return (notAuthorized.length ? notAuthorized : users.map((user) => user.id)).slice(0, 4)
}

const resetMemberForm = (role: RoleCode = 'inspection') => {
  memberForm.role = role
  memberForm.orgId = ''
  memberForm.expiresAt = ''
  memberOperationError.value = ''
  memberBatchResult.value = null
}

const openMemberDialog = () => {
  if (!projectDetail.value) return
  memberDialogMode.value = 'single'
  resetMemberForm()
  const firstUser = getDefaultMemberUser(memberForm.role)
  memberForm.userId = firstUser?.id || ''
  memberBatchUserIds.value = []
  memberDialogVisible.value = true
}

const openMemberBatchDialog = () => {
  if (!projectDetail.value) return
  memberDialogMode.value = 'batch'
  resetMemberForm()
  memberForm.userId = ''
  memberBatchUserIds.value = getDefaultBatchMemberUserIds()
  memberDialogVisible.value = true
}

const handleMemberRoleChange = () => {
  if (!roleOrgOptions(memberForm.role).some((org) => org.id === memberForm.orgId)) {
    memberForm.orgId = ''
  }
  if (memberDialogMode.value === 'single') {
    memberForm.userId = getDefaultMemberUser(memberForm.role)?.id || ''
    return
  }
  memberBatchUserIds.value = getDefaultBatchMemberUserIds()
}

const handleMemberOrgChange = () => {
  if (memberDialogMode.value === 'single') {
    memberForm.userId = getDefaultMemberUser(memberForm.role)?.id || ''
    return
  }
  memberBatchUserIds.value = getDefaultBatchMemberUserIds()
}

const handleSaveMember = async () => {
  if (!projectDetail.value) return
  if (memberDialogMode.value === 'single' && !memberForm.userId) {
    ElMessage.warning('请选择授权用户')
    return
  }
  if (memberDialogMode.value === 'batch' && !memberBatchUserIds.value.length) {
    ElMessage.warning('请选择批量授权用户')
    return
  }
  memberSaving.value = true
  memberOperationError.value = ''
  memberBatchResult.value = null
  try {
    const userIds =
      memberDialogMode.value === 'batch' ? memberBatchUserIds.value : [memberForm.userId]
    const res = await authorizeProjectMemberApi(projectDetail.value.project.id, {
      userIds,
      expiresAt: memberForm.expiresAt || undefined
    })
    if (!res) {
      memberOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目成员授权')
      )
      return
    }
    const failed = res.data.failed || []
    const successCount = res.data.successCount || res.data.members?.length || 0
    if (failed.length) {
      memberBatchResult.value = { successCount, failed }
      memberOperationError.value = buildOperationFailureMessage('项目成员授权')
      if (successCount) {
        await Promise.all([loadProjectDetail(projectDetail.value.project.id), loadAuditLogs()])
      }
      return
    }
    ElMessage.success(`项目成员授权已保存：${successCount} 人`)
    memberDialogVisible.value = false
    await Promise.all([loadProjectDetail(projectDetail.value.project.id), loadAuditLogs()])
  } catch (error) {
    memberOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目成员授权保存')
    )
  } finally {
    memberSaving.value = false
  }
}

const handleToggleMemberStatus = async (row: ProjectMember) => {
  if (!projectDetail.value) return
  const nextStatus = row.status === '启用' ? '停用' : '启用'
  memberSaving.value = true
  memberOperationError.value = ''
  try {
    const res = await updateProjectMemberApi(
      projectDetail.value.project.id,
      row.id,
      {
        status: nextStatus
      },
      { etag: row.etag }
    )
    if (!res) {
      memberOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目成员状态更新')
      )
      return
    }
    ElMessage.success(`${row.name} 已${nextStatus}`)
    await Promise.all([loadProjectDetail(projectDetail.value.project.id), loadAuditLogs()])
  } catch (error) {
    memberOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目成员状态更新')
    )
  } finally {
    memberSaving.value = false
  }
}

const handleDeleteMember = async (row: ProjectMember) => {
  if (!projectDetail.value) return
  try {
    await ElMessageBox.confirm(`确认移除「${row.name}」的项目授权？`, '移除授权', {
      type: 'warning'
    })
  } catch {
    return
  }
  memberSaving.value = true
  memberOperationError.value = ''
  try {
    const res = await deleteProjectMemberApi(projectDetail.value.project.id, row.id, {
      etag: row.etag
    })
    if (!res) {
      memberOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目成员移除')
      )
      return
    }
    ElMessage.success('项目成员授权已移除')
    await Promise.all([loadProjectDetail(projectDetail.value.project.id), loadAuditLogs()])
  } catch (error) {
    memberOperationError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目成员移除')
    )
  } finally {
    memberSaving.value = false
  }
}

const handleFilterAudit = () => {
  auditPagination.page = 1
  loadAuditLogs()
}

const handleResetAudit = () => {
  auditFilters.keyword = ''
  auditFilters.result = ''
  auditFilters.objectType = ''
  auditPagination.page = 1
  loadAuditLogs()
}

const handleAuditPageChange = (page: number) => {
  auditPagination.page = page
  loadAuditLogs()
}

const handleAuditPageSizeChange = (pageSize: number) => {
  auditPagination.page = 1
  auditPagination.pageSize = pageSize
  loadAuditLogs()
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div
    class="admin-page"
    :class="{ 'admin-page--expanded': activeTab === 'org' || activeTab === 'permission' }"
    v-loading="loading"
  >
    <StaticPageShell
      brand-mark="管"
      title="项目与权限配置"
      :status="adminRuntimeStatus"
      :status-tone="adminRuntimeStatusTone"
      search-placeholder="搜索项目、用户、权限、规则"
      search-scope="admin"
      task-area="admin"
      :user-label="adminUserLabel"
      workspace-mode="wide"
      right-panel-mode="drawer"
      right-toggle-label="配置摘要"
      right-collapsed-default
      boundary-collapsed-default
      :top-stats="[
        { label: '项目', value: projectTotal, tone: 'blue' },
        { label: '配置待办', value: pendingRuleCount, tone: 'orange' },
        { label: '审计', value: auditPagination.total, tone: 'red' }
      ]"
      menu-title="后台菜单"
      menu-root="后台管理功能"
      :menu-sections="adminShellMenuSections"
      boundary-title="后台边界"
      boundary-badge="无业务办理"
      boundary-tone="green"
      :boundary-rows="adminShellBoundaryRows"
      right-title="运行摘要"
      :right-subtitle="adminShellRightSubtitle"
      :right-cards="adminShellRightCards"
      @menu-select="handleAdminMenuSelect"
    >
      <div class="page-toolbar">
        <div>
          <h1 class="page-title">{{ adminPageTitle }}</h1>
          <div v-if="adminPageSubtitle" class="page-subtitle">{{ adminPageSubtitle }}</div>
        </div>
        <ElSpace wrap>
          <ElButton v-if="activeTab === 'projects'" type="primary" @click="openProjectWizard">
            新建项目
          </ElButton>
          <ElButton
            v-if="activeTab === 'audit'"
            :loading="configExporting"
            @click="handleExportConfig"
          >
            导出配置包
          </ElButton>
          <ElButton
            v-if="adminPublishAvailable"
            type="primary"
            :loading="configPublishing"
            @click="handlePublishConfig"
          >
            发布配置
          </ElButton>
        </ElSpace>
      </div>

      <div v-if="latestPublishResult" class="config-panel publish-result-panel">
        <div>
          <strong>最近发布：{{ latestPublishResult.version }}</strong>
          <span>
            在检项目 {{ latestPublishResult.impactSummary.linkedProjects }} 个 · 推送
            {{ latestPublishResult.impactSummary.pushedMessages }} 条消息 · 复核待办
            {{ latestPublishResult.impactSummary.reviewTodos }} 条
          </span>
        </div>
        <ElButton type="primary" plain @click="publishTraceVisible = true">查看联动</ElButton>
      </div>

      <AuditSummaryGrid :cards="adminAuditCards" aria-label="管理后台治理摘要" />

      <div
        v-if="
          overviewError ||
          adminActionError ||
          projectOperationError ||
          orgOperationError ||
          userOperationError
        "
        class="error-stack"
      >
        <div v-if="overviewError" class="local-error">
          <ElAlert type="error" show-icon :closable="false" :title="overviewError" />
          <ElButton type="primary" plain :loading="loading" @click="loadData">重新加载</ElButton>
        </div>
        <div v-if="adminActionError" class="local-error">
          <ElAlert type="error" show-icon :closable="false" :title="adminActionError" />
          <ElButton
            v-if="adminActionRetry"
            type="primary"
            plain
            :loading="configExporting || configPublishing"
            @click="retryAdminAction"
          >
            重试操作
          </ElButton>
        </div>
        <ElAlert
          v-if="projectOperationError"
          type="error"
          show-icon
          :closable="false"
          :title="projectOperationError"
        />
        <ElAlert
          v-if="orgOperationError"
          type="error"
          show-icon
          :closable="false"
          :title="orgOperationError"
        />
        <ElAlert
          v-if="userOperationError"
          type="error"
          show-icon
          :closable="false"
          :title="userOperationError"
        />
      </div>

      <details class="secondary-summary-collapse">
        <summary>
          <span>配置统计明细</span>
          <small>摘要卡已展示核心指标，展开查看完整配置计数</small>
        </summary>
        <div class="metric-grid">
          <div
            v-for="stat in projectStats"
            :key="stat.key"
            :class="`metric-card metric-card--${stat.tone}`"
          >
            <span>{{ stat.label }}</span>
            <strong>{{ stat.value }}</strong>
          </div>
        </div>
      </details>

      <ElTabs v-model="activeTab" class="admin-tabs">
        <ElTabPane label="项目管理" name="projects">
          <ElRow :gutter="16">
            <ElCol :span="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>项目清单</span>
                    <ElSpace wrap>
                      <ElTag type="info" effect="plain">{{ projectTotal }} 个</ElTag>
                    </ElSpace>
                  </div>
                </template>
                <div class="project-filter-bar">
                  <ElInput
                    v-model="projectFilters.keyword"
                    clearable
                    placeholder="搜索项目名称、编号或区域"
                    aria-label="搜索项目名称、编号或区域"
                    @keyup.enter="handleProjectFilter"
                    @clear="handleProjectFilter"
                  />
                  <ElSelect
                    v-model="projectFilters.status"
                    clearable
                    placeholder="全部状态"
                    aria-label="按项目状态筛选"
                    @change="handleProjectFilter"
                    @clear="handleProjectFilter"
                  >
                    <ElOption
                      v-for="status in projectStatusOptions"
                      :key="status"
                      :label="status"
                      :value="status"
                    />
                  </ElSelect>
                  <ElSpace wrap>
                    <ElButton
                      type="primary"
                      plain
                      :loading="projectsLoading"
                      @click="handleProjectFilter"
                    >
                      查询
                    </ElButton>
                    <ElButton :disabled="projectsLoading" @click="handleProjectReset"
                      >重置</ElButton
                    >
                    <ElButton :loading="projectsLoading" @click="loadProjects">刷新</ElButton>
                  </ElSpace>
                </div>
                <ElTable
                  v-loading="projectsLoading"
                  class="desktop-project-table"
                  :data="projectTableRows"
                  border
                  height="360"
                  empty-text="暂无项目配置"
                  @sort-change="handleTableSortChange('projects', $event)"
                >
                  <ElTableColumn
                    type="index"
                    label="序号"
                    width="76"
                    align="center"
                    :index="pageIndex(tableStates.projects)"
                  />
                  <ElTableColumn
                    prop="name"
                    label="项目名称"
                    min-width="220"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="contractorOrgName"
                    label="施工单位"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="inspectionOrgName"
                    label="监检机构"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="status" label="状态" width="130" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="todoCount" label="待办" width="76" sortable="custom" />
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
                  <ElTableColumn label="操作" width="180" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="handleOpenProjectDetail(row)"
                        >详情</ElButton
                      >
                      <ElButton link type="primary" @click="openProjectEditDialog(row)"
                        >编辑</ElButton
                      >
                      <ElButton
                        link
                        type="danger"
                        :loading="projectSaving"
                        @click="handleDeleteProject(row)"
                      >
                        归档/删除
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <div v-loading="projectsLoading" class="mobile-project-list" aria-live="polite">
                  <article
                    v-for="row in projectTableRows"
                    :key="row.id"
                    class="mobile-project-card"
                  >
                    <header>
                      <div>
                        <small>{{ row.code || '未设置项目编号' }}</small>
                        <strong>{{ row.name }}</strong>
                      </div>
                      <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                    </header>
                    <dl>
                      <div>
                        <dt>施工单位</dt>
                        <dd>{{ row.contractorOrgName || '--' }}</dd>
                      </div>
                      <div>
                        <dt>监检机构</dt>
                        <dd>{{ row.inspectionOrgName || '--' }}</dd>
                      </div>
                      <div>
                        <dt>待办</dt>
                        <dd>{{ row.todoCount ?? 0 }}</dd>
                      </div>
                      <div>
                        <dt>更新时间</dt>
                        <dd>{{ row.updatedAt || '--' }}</dd>
                      </div>
                    </dl>
                    <footer>
                      <ElButton link type="primary" @click="handleOpenProjectDetail(row)">
                        查看详情
                      </ElButton>
                      <ElDropdown
                        trigger="click"
                        @command="(command) => handleProjectCardCommand(String(command), row)"
                      >
                        <ElButton link type="primary" aria-label="打开项目更多操作">
                          更多操作
                        </ElButton>
                        <template #dropdown>
                          <ElDropdownMenu>
                            <ElDropdownItem command="edit">编辑项目</ElDropdownItem>
                            <ElDropdownItem command="archive" divided>归档/删除</ElDropdownItem>
                          </ElDropdownMenu>
                        </template>
                      </ElDropdown>
                    </footer>
                  </article>
                  <ElEmpty v-if="!projectTableRows.length" description="暂无项目配置" />
                </div>
                <ElPagination
                  v-model:current-page="tableStates.projects.page"
                  v-model:page-size="tableStates.projects.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="tableStates.projects.total"
                  @size-change="handleProjectPageSizeChange"
                  @current-change="handleProjectPageChange"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="组织用户" name="org">
          <ElRow :gutter="16" class="admin-stack-row">
            <ElCol :span="24" class="admin-stack-col">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>组织单位</span>
                    <ElSpace>
                      <ElTag type="info" effect="plain">{{ overview.orgUnits.length }} 个</ElTag>
                      <ElButton size="small" type="primary" plain @click="openOrgDialog()">
                        新增组织
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.orgUnits, tableStates.orgUnits)"
                  border
                  height="420"
                  empty-text="暂无组织单位"
                  @sort-change="handleTableSortChange('orgUnits', $event)"
                >
                  <ElTableColumn
                    prop="name"
                    label="组织名称"
                    min-width="170"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="type" label="类型" width="96" sortable="custom" />
                  <ElTableColumn prop="contactName" label="联系人" width="92" sortable="custom" />
                  <ElTableColumn prop="projectCount" label="项目" width="72" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="88" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="116" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openOrgDialog(row)">编辑</ElButton>
                      <ElButton
                        link
                        type="danger"
                        :loading="orgSaving"
                        @click="handleDeleteOrg(row)"
                      >
                        删除
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.orgUnits.page"
                  v-model:page-size="tableStates.orgUnits.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.orgUnits.length"
                  @size-change="resetTablePage('orgUnits')"
                />
              </ElCard>
            </ElCol>

            <ElCol :span="24" class="admin-stack-col">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>用户与角色</span>
                    <ElSpace>
                      <ElTag type="info" effect="plain">{{ overview.users.length }} 人</ElTag>
                      <ElButton size="small" type="primary" plain @click="openUserDialog()">
                        新增用户
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.users, tableStates.users)"
                  border
                  height="460"
                  empty-text="暂无用户账号"
                  @sort-change="handleTableSortChange('users', $event)"
                >
                  <ElTableColumn prop="username" label="用户名" width="110" sortable="custom" />
                  <ElTableColumn prop="name" label="姓名" width="96" sortable="custom" />
                  <ElTableColumn
                    prop="orgName"
                    label="所属组织"
                    min-width="170"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="role" label="角色" width="100" sortable="custom">
                    <template #default="{ row }">
                      <ElTag size="small" effect="plain">{{ roleLabel(row.role) }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="mobile" label="手机号" width="130" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="88" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="lastLoginAt"
                    label="最近登录"
                    width="170"
                    sortable="custom"
                  />
                  <ElTableColumn label="操作" width="116" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openUserDialog(row)">编辑</ElButton>
                      <ElButton
                        link
                        type="danger"
                        :loading="userSaving"
                        @click="handleDeleteUser(row)"
                      >
                        删除
                      </ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.users.page"
                  v-model:page-size="tableStates.users.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.users.length"
                  @size-change="resetTablePage('users')"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="业务类型管理" name="business-pack">
          <ElRow :gutter="16">
            <ElCol :span="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>业务类型列表</span>
                    <ElSpace>
                      <ElTag
                        :type="businessPackValidation?.ok === false ? 'danger' : 'success'"
                        effect="plain"
                      >
                        {{ businessPackValidation?.ok === false ? '存在错误' : '可用' }}
                      </ElTag>
                      <ElButton
                        type="primary"
                        size="small"
                        plain
                        :loading="businessPackValidating"
                        @click="handleValidateBusinessPacks"
                      >
                        重新校验
                      </ElButton>
                    </ElSpace>
                  </div>
                </template>
                <ElAlert
                  v-if="businessPackValidationError"
                  type="error"
                  show-icon
                  :closable="false"
                  :title="businessPackValidationError"
                  class="mb-12px"
                />
                <ElTable
                  :data="tableRows(businessPackRows, tableStates.businessPacks)"
                  border
                  height="380"
                  empty-text="暂无压力管道业务类型"
                  @sort-change="handleTableSortChange('businessPacks', $event)"
                >
                  <ElTableColumn
                    prop="pipelineTypeCode"
                    label="类型代号"
                    width="120"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="__businessPackName"
                    label="名称"
                    min-width="160"
                    show-overflow-tooltip
                    sortable="custom"
                  >
                    <template #default="{ row }">
                      {{ row.pipelineTypeName || row.name }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="__businessPackRange"
                    label="常见分级/范围"
                    min-width="360"
                    show-overflow-tooltip
                    sortable="custom"
                  >
                    <template #default="{ row }">
                      {{ businessPackRangeText(row) }}
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="projectType"
                    label="项目属性"
                    min-width="150"
                    sortable="custom"
                  />
                  <ElTableColumn prop="version" label="版本" width="120" sortable="custom" />
                  <ElTableColumn prop="nodeCount" label="节点" width="72" sortable="custom" />
                  <ElTableColumn
                    prop="materialTypeCount"
                    label="资料"
                    width="72"
                    sortable="custom"
                  />
                  <ElTableColumn prop="ruleSetCount" label="规则" width="72" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="96" sortable="custom">
                    <template #default="{ row }">
                      <ElTag
                        :type="statusType(businessPackStatusLabel(row.status))"
                        size="small"
                        effect="plain"
                      >
                        {{ businessPackStatusLabel(row.status) }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.businessPacks.page"
                  v-model:page-size="tableStates.businessPacks.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="businessPackRows.length"
                  @size-change="resetTablePage('businessPacks')"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="权限与节点" name="permission">
          <ElRow :gutter="16" class="admin-stack-row">
            <ElCol :span="24" class="admin-stack-col">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>角色权限矩阵</span>
                    <ElTag type="info" effect="plain"
                      >{{ overview.permissionMatrix.length }} 类</ElTag
                    >
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.permissionMatrix, tableStates.permissionMatrix)"
                  border
                  height="460"
                  empty-text="暂无权限矩阵"
                  @sort-change="handleTableSortChange('permissionMatrix', $event)"
                >
                  <ElTableColumn prop="label" label="角色" width="100" sortable="custom" />
                  <ElTableColumn
                    prop="projectScope"
                    label="项目范围"
                    min-width="130"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="nodeScope"
                    label="节点范围"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="actions" label="动作权限" min-width="220" sortable="custom">
                    <template #default="{ row }">
                      <div class="tag-list">
                        <!-- 原来直接摊 project:view 这类码。那是给中间件比对用的，
                             不是给人读的：配一个角色要先在心里翻译一遍，
                             ai:adopt 和 ai:recheck 还容易看混。
                             悬浮时给出原始码，配权限的人有时确实需要它。 -->
                        <ElTag
                          v-for="action in row.actions.slice(0, 5)"
                          :key="action"
                          size="small"
                          effect="plain"
                          :title="actionLabelWithCode(action)"
                        >
                          {{ actionLabel(action) }}
                        </ElTag>
                        <ElTag
                          v-if="row.actions.length > 5"
                          size="small"
                          type="info"
                          effect="plain"
                        >
                          +{{ row.actions.length - 5 }}
                        </ElTag>
                      </div>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="readonly" label="只读" width="76" sortable="custom">
                    <template #default="{ row }">
                      <ElTag
                        :type="row.readonly ? 'warning' : 'success'"
                        size="small"
                        effect="plain"
                      >
                        {{ row.readonly ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openPermissionConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.permissionMatrix.page"
                  v-model:page-size="tableStates.permissionMatrix.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.permissionMatrix.length"
                  @size-change="resetTablePage('permissionMatrix')"
                />
              </ElCard>
            </ElCol>

            <ElCol :span="24" class="admin-stack-col">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>节点模板</span>
                    <ElTag type="info" effect="plain">{{ overview.nodeTemplates.length }} 组</ElTag>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.nodeTemplates, tableStates.nodeTemplates)"
                  border
                  height="460"
                  empty-text="暂无节点模板"
                  @sort-change="handleTableSortChange('nodeTemplates', $event)"
                >
                  <ElTableColumn
                    prop="groupName"
                    label="业务分组"
                    min-width="170"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="version" label="版本" width="130" sortable="custom" />
                  <ElTableColumn prop="nodeCount" label="节点" width="70" sortable="custom" />
                  <ElTableColumn prop="requiredCount" label="资料项" width="84" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="96" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openNodeTemplateConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.nodeTemplates.page"
                  v-model:page-size="tableStates.nodeTemplates.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.nodeTemplates.length"
                  @size-change="resetTablePage('nodeTemplates')"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="AI业务规则与流程" name="rule">
          <ElRow :gutter="16">
            <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>AI业务规则版本</span>
                    <ElTag :type="pendingRuleCount ? 'warning' : 'success'" effect="plain">
                      {{ pendingRuleCount ? `${pendingRuleCount} 待发布` : '全部发布' }}
                    </ElTag>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.ruleVersions, tableStates.ruleVersions)"
                  border
                  height="320"
                  empty-text="暂无AI业务规则版本"
                  @sort-change="handleTableSortChange('ruleVersions', $event)"
                >
                  <ElTableColumn
                    prop="name"
                    label="规则名称"
                    min-width="180"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="version"
                    label="版本"
                    min-width="160"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="promptVersion"
                    label="Prompt"
                    min-width="170"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="outputSchemaVersion"
                    label="输出结构"
                    min-width="130"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="nodeIds" label="节点" min-width="130" sortable="custom">
                    <template #default="{ row }">{{ row.nodeIds.join('、') }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="status" label="状态" width="96" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
                  <ElTableColumn label="操作" width="112" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openRuleVersionDetail(row)">
                        详情
                      </ElButton>
                      <ElButton link type="primary" @click="openRuleVersionDiff(row)"
                        >差异</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.ruleVersions.page"
                  v-model:page-size="tableStates.ruleVersions.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.ruleVersions.length"
                  @size-change="resetTablePage('ruleVersions')"
                />
              </ElCard>
            </ElCol>

            <ElCol :xl="11" :lg="11" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>流程状态机</span>
                    <ElTag type="success" effect="plain">启用</ElTag>
                  </div>
                </template>
                <ElTable
                  :data="
                    tableRows(overview.workflowStateMachines, tableStates.workflowStateMachines)
                  "
                  border
                  height="320"
                  @sort-change="handleTableSortChange('workflowStateMachines', $event)"
                >
                  <ElTableColumn
                    prop="name"
                    label="流程"
                    min-width="170"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="version" label="版本" width="140" sortable="custom" />
                  <ElTableColumn prop="states" label="状态数" width="84" sortable="custom" />
                  <ElTableColumn prop="transitions" label="流转" width="70" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="86" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openWorkflowConfig(row)">编辑</ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.workflowStateMachines.page"
                  v-model:page-size="tableStates.workflowStateMachines.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.workflowStateMachines.length"
                  @size-change="resetTablePage('workflowStateMachines')"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="业务资料审查点" name="material-review-point">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>资料与审查点对应关系</span>
                <ElSpace>
                  <ElTag type="info" effect="plain">
                    {{ overview.materialReviewPoints.length }} 项
                  </ElTag>
                  <ElButton
                    type="primary"
                    size="small"
                    plain
                    @click="openMaterialReviewPointConfig()"
                  >
                    新增
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <ElTable
              :data="tableRows(overview.materialReviewPoints, tableStates.materialReviewPoints)"
              border
              height="520"
              empty-text="暂无业务资料审查点"
              @sort-change="handleTableSortChange('materialReviewPoints', $event)"
            >
              <ElTableColumn prop="nodeId" label="节点" width="78" sortable="custom" />
              <ElTableColumn
                prop="reviewContent"
                label="审查点"
                min-width="190"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="fileContent"
                label="审查内容"
                min-width="260"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">
                  {{ materialReviewPointAuditContent(row) }}
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="materialTypeName"
                label="资料类型"
                min-width="190"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">
                  <div class="stacked-cell">
                    <span>{{ row.materialTypeName || '-' }}</span>
                    <small>{{ row.materialTypeCode || '-' }}</small>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="evidenceItemText"
                label="OCR证据项"
                min-width="260"
                show-overflow-tooltip
              />
              <ElTableColumn prop="responsibleParty" label="责任方" width="110" sortable="custom">
                <template #default="{ row }">{{
                  responsiblePartyLabel(row.responsibleParty)
                }}</template>
              </ElTableColumn>
              <ElTableColumn prop="requiredType" label="口径" width="98" sortable="custom">
                <template #default="{ row }">
                  <ElTag
                    :type="row.requiredType === '可选' ? 'info' : 'warning'"
                    size="small"
                    effect="plain"
                  >
                    {{ row.requiredType }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="minConfidence" label="阈值" width="86" sortable="custom" />
              <ElTableColumn prop="enabled" label="状态" width="84" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
                    {{ row.enabled ? '启用' : '停用' }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="132" fixed="right">
                <template #default="{ row }">
                  <ElButton link type="primary" @click="openMaterialReviewPointConfig(row)">
                    编辑
                  </ElButton>
                  <ElButton link type="danger" @click="handleDeleteMaterialReviewPoint(row)">
                    删除
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.materialReviewPoints.page"
              v-model:page-size="tableStates.materialReviewPoints.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="overview.materialReviewPoints.length"
              @size-change="resetTablePage('materialReviewPoints')"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="Prompt 模板管理" name="prompt-template">
          <ElCard shadow="never" class="panel" v-loading="promptTemplateLoading">
            <template #header>
              <div class="panel-header">
                <span>Prompt 模板管理</span>
                <ElSpace>
                  <ElTag type="info" effect="plain"
                    >{{ tableStates.promptTemplates.total }} 个</ElTag
                  >
                  <ElButton type="primary" plain size="small" @click="openPromptTemplateDialog()">
                    新增模板
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <div v-if="promptTemplateOperationError" class="local-error local-error--compact">
              <ElAlert
                type="error"
                show-icon
                :closable="false"
                :title="promptTemplateOperationError"
              />
            </div>
            <div v-if="promptTemplateError" class="local-error local-error--compact">
              <ElAlert type="error" show-icon :closable="false" :title="promptTemplateError" />
              <ElButton
                type="primary"
                plain
                :loading="promptTemplateLoading"
                @click="loadPromptTemplates"
              >
                重新加载
              </ElButton>
            </div>
            <div class="prompt-template-filter-bar">
              <ElInput
                v-model="promptTemplateFilters.keyword"
                clearable
                placeholder="搜索模板名称、Prompt Key、业务类型或 Agent"
                @keyup.enter="handlePromptTemplateFilter"
              />
              <ElSelect
                v-model="promptTemplateFilters.status"
                clearable
                placeholder="状态"
                @change="handlePromptTemplateFilter"
              >
                <ElOption label="草稿" value="draft" />
                <ElOption label="生产" value="production" />
                <ElOption label="已停用" value="retired" />
              </ElSelect>
              <ElButton
                type="primary"
                :loading="promptTemplateLoading"
                @click="handlePromptTemplateFilter"
              >
                筛选
              </ElButton>
              <ElButton :loading="promptTemplateLoading" @click="loadPromptTemplates"
                >刷新</ElButton
              >
            </div>
            <ElTable
              :data="sortedRows(promptTemplates, tableStates.promptTemplates)"
              border
              height="430"
              empty-text="暂无 Prompt 模板"
              @sort-change="handlePromptTemplateSortChange"
            >
              <ElTableColumn
                prop="name"
                label="模板名称"
                min-width="220"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="promptKey"
                label="Prompt Key"
                min-width="150"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="version" label="版本" width="110" sortable="custom" />
              <ElTableColumn prop="status" label="状态" width="100" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="promptTemplateStatusType(row.status)" size="small" effect="plain">
                    {{ promptTemplateStatusLabel(row.status) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="businessPackId"
                label="业务包"
                min-width="190"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="agentId"
                label="Agent"
                min-width="170"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="promptVersionId"
                label="Prompt 版本"
                min-width="170"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
              <ElTableColumn label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <ElButton link type="primary" @click="openPromptTemplateDialog(row)">
                    编辑
                  </ElButton>
                  <ElButton
                    link
                    type="success"
                    :disabled="['production', '已发布'].includes(row.status)"
                    :loading="promptTemplateSaving"
                    @click="handlePublishPromptTemplate(row)"
                  >
                    发布
                  </ElButton>
                  <ElButton
                    link
                    type="danger"
                    :disabled="['production', '已发布'].includes(row.status)"
                    :loading="promptTemplateSaving"
                    @click="handleDeletePromptTemplate(row)"
                  >
                    删除
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.promptTemplates.page"
              v-model:page-size="tableStates.promptTemplates.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="tableStates.promptTemplates.total"
              @size-change="handlePromptTemplateFilter"
              @current-change="loadPromptTemplates"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="报告模板管理" name="report-template">
          <ElCard shadow="never" class="panel" v-loading="reportTemplateLoading">
            <template #header>
              <div class="panel-header">
                <span>报告模板管理</span>
                <ElSpace>
                  <ElTag type="info" effect="plain"
                    >{{ tableStates.reportTemplates.total }} 个</ElTag
                  >
                  <ElButton type="primary" plain size="small" @click="openReportTemplateDialog()">
                    新增模板
                  </ElButton>
                </ElSpace>
              </div>
            </template>
            <div v-if="reportTemplateOperationError" class="local-error local-error--compact">
              <ElAlert
                type="error"
                show-icon
                :closable="false"
                :title="reportTemplateOperationError"
              />
            </div>
            <div v-if="reportTemplateError" class="local-error local-error--compact">
              <ElAlert type="error" show-icon :closable="false" :title="reportTemplateError" />
              <ElButton
                type="primary"
                plain
                :loading="reportTemplateLoading"
                @click="loadReportTemplates"
              >
                重新加载
              </ElButton>
            </div>
            <div class="prompt-template-filter-bar">
              <ElInput
                v-model="reportTemplateFilters.keyword"
                clearable
                placeholder="搜索模板名称、版本或业务包"
                @keyup.enter="handleReportTemplateFilter"
              />
              <ElSelect
                v-model="reportTemplateFilters.status"
                clearable
                placeholder="状态"
                @change="handleReportTemplateFilter"
              >
                <ElOption label="草稿" value="draft" />
                <ElOption label="生产" value="production" />
                <ElOption label="已停用" value="retired" />
              </ElSelect>
              <ElButton
                type="primary"
                :loading="reportTemplateLoading"
                @click="handleReportTemplateFilter"
              >
                筛选
              </ElButton>
              <ElButton :loading="reportTemplateLoading" @click="loadReportTemplates">
                刷新
              </ElButton>
            </div>
            <ElTable
              :data="sortedRows(reportTemplates, tableStates.reportTemplates)"
              border
              height="430"
              empty-text="暂无报告模板"
              @sort-change="handleReportTemplateSortChange"
            >
              <ElTableColumn
                prop="name"
                label="模板名称"
                min-width="230"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="version" label="版本" width="110" sortable="custom" />
              <ElTableColumn prop="status" label="状态" width="100" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="promptTemplateStatusType(row.status)" size="small" effect="plain">
                    {{ promptTemplateStatusLabel(row.status) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="businessPackId"
                label="业务包"
                min-width="210"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn label="章节" width="90">
                <template #default="{ row }">{{ row.sections?.length || 0 }} 项</template>
              </ElTableColumn>
              <ElTableColumn label="导出类型" min-width="230" show-overflow-tooltip>
                <template #default="{ row }">{{ row.exportTypes?.join('、') || '-' }}</template>
              </ElTableColumn>
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
              <ElTableColumn label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <!-- 生产版本不可改，但得让人看得到内容、且知道为什么点不动。
                       原来三个按钮一起灰掉、不给任何说明，管理员只能当它坏了。 -->
                  <ElButton link type="primary" @click="openReportTemplateDialog(row)">
                    {{ reportTemplateLocked(row.status) ? '查看' : '编辑' }}
                  </ElButton>
                  <ElTooltip
                    :disabled="!reportTemplateLocked(row.status)"
                    :content="reportTemplateLockedHint"
                    placement="top"
                  >
                    <span>
                      <ElButton
                        link
                        type="success"
                        :disabled="reportTemplateLocked(row.status)"
                        :loading="reportTemplateSaving"
                        @click="handlePublishReportTemplate(row)"
                      >
                        发布
                      </ElButton>
                    </span>
                  </ElTooltip>
                  <ElTooltip
                    :disabled="!reportTemplateLocked(row.status)"
                    :content="reportTemplateLockedHint"
                    placement="top"
                  >
                    <span>
                      <ElButton
                        link
                        type="danger"
                        :disabled="reportTemplateLocked(row.status)"
                        :loading="reportTemplateSaving"
                        @click="handleDeleteReportTemplate(row)"
                      >
                        删除
                      </ElButton>
                    </span>
                  </ElTooltip>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.reportTemplates.page"
              v-model:page-size="tableStates.reportTemplates.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="tableStates.reportTemplates.total"
              @size-change="handleReportTemplateFilter"
              @current-change="loadReportTemplates"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="细项配置" name="fine-config">
          <ElRow :gutter="16">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>待办规则</span>
                    <ElButton type="primary" size="small" plain @click="openTodoRuleConfig()">
                      新增
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.todoRules, tableStates.todoRules)"
                  border
                  height="300"
                  @sort-change="handleTableSortChange('todoRules', $event)"
                >
                  <ElTableColumn
                    prop="name"
                    label="规则名称"
                    min-width="160"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="triggerStatus"
                    label="触发状态"
                    min-width="130"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="assigneeRole" label="处理角色" width="110" sortable="custom">
                    <template #default="{ row }">{{ roleLabel(row.assigneeRole) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="deadlineHours" label="时限/h" width="82" sortable="custom" />
                  <ElTableColumn prop="enabled" label="状态" width="84" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
                        {{ row.enabled ? '启用' : '停用' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openTodoRuleConfig(row)">编辑</ElButton>
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.todoRules.page"
                  v-model:page-size="tableStates.todoRules.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.todoRules.length"
                  @size-change="resetTablePage('todoRules')"
                />
              </ElCard>
            </ElCol>

            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>消息模板</span>
                    <ElButton
                      type="primary"
                      size="small"
                      plain
                      @click="openMessageTemplateConfig()"
                    >
                      新增
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.messageTemplates, tableStates.messageTemplates)"
                  border
                  height="300"
                  @sort-change="handleTableSortChange('messageTemplates', $event)"
                >
                  <ElTableColumn
                    prop="scene"
                    label="场景"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="channel" label="渠道" width="86" sortable="custom" />
                  <ElTableColumn
                    prop="titleTemplate"
                    label="标题模板"
                    min-width="210"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="enabled" label="状态" width="84" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
                        {{ row.enabled ? '启用' : '停用' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" sortable="custom" />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openMessageTemplateConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.messageTemplates.page"
                  v-model:page-size="tableStates.messageTemplates.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.messageTemplates.length"
                  @size-change="resetTablePage('messageTemplates')"
                />
              </ElCard>
            </ElCol>

            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>工具源</span>
                    <ElButton type="primary" size="small" plain @click="openToolSourceConfig()">
                      新增
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.toolSources, tableStates.toolSources)"
                  border
                  height="300"
                  @sort-change="handleTableSortChange('toolSources', $event)"
                >
                  <ElTableColumn
                    prop="name"
                    label="工具名称"
                    min-width="160"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="toolType" label="类型" width="120" sortable="custom" />
                  <ElTableColumn
                    prop="endpoint"
                    label="地址"
                    min-width="220"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="authMode" label="鉴权" width="88" sortable="custom" />
                  <ElTableColumn prop="status" label="状态" width="84" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openToolSourceConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.toolSources.page"
                  v-model:page-size="tableStates.toolSources.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.toolSources.length"
                  @size-change="resetTablePage('toolSources')"
                />
              </ElCard>
            </ElCol>

            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>字段映射</span>
                    <ElButton type="primary" size="small" plain @click="openFieldMappingConfig()">
                      新增
                    </ElButton>
                  </div>
                </template>
                <ElTable
                  :data="tableRows(overview.fieldMappings, tableStates.fieldMappings)"
                  border
                  height="300"
                  @sort-change="handleTableSortChange('fieldMappings', $event)"
                >
                  <ElTableColumn prop="nodeId" label="节点" width="72" sortable="custom" />
                  <ElTableColumn
                    prop="fieldName"
                    label="字段"
                    min-width="140"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="sourceField"
                    label="来源字段"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn
                    prop="targetField"
                    label="目标字段"
                    min-width="150"
                    show-overflow-tooltip
                    sortable="custom"
                  />
                  <ElTableColumn prop="required" label="必填" width="76" sortable="custom">
                    <template #default="{ row }">
                      <ElTag :type="row.required ? 'warning' : 'info'" size="small" effect="plain">
                        {{ row.required ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn
                    prop="confidenceThreshold"
                    label="阈值"
                    width="76"
                    sortable="custom"
                  />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openFieldMappingConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
                <ElPagination
                  v-model:current-page="tableStates.fieldMappings.page"
                  v-model:page-size="tableStates.fieldMappings.pageSize"
                  class="table-pagination"
                  background
                  :page-sizes="tablePageSizes"
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="overview.fieldMappings.length"
                  @size-change="resetTablePage('fieldMappings')"
                />
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="联调清单" name="integration">
          <ElCard shadow="never" class="panel integration-panel" v-loading="integrationLoading">
            <template #header>
              <div class="panel-header">
                <span>真实联调字段差异清单</span>
                <ElTag
                  :type="integrationContract.summary.blockers ? 'danger' : 'success'"
                  effect="plain"
                >
                  {{
                    integrationContract.summary.blockers
                      ? `${integrationContract.summary.blockers} 阻塞`
                      : '可推进'
                  }}
                </ElTag>
              </div>
            </template>

            <div v-if="integrationError" class="local-error local-error--compact">
              <ElAlert type="error" show-icon :closable="false" :title="integrationError" />
              <ElButton
                type="primary"
                plain
                :loading="integrationLoading"
                @click="loadIntegrationContract"
              >
                重新加载
              </ElButton>
            </div>

            <div class="integration-summary-grid">
              <div
                v-for="item in integrationSummaryItems"
                :key="item.label"
                :class="`integration-summary-card integration-summary-card--${item.tone}`"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>

            <div class="integration-filter-bar">
              <ElSelect
                v-model="integrationModuleFilter"
                placeholder="模块"
                @change="handleIntegrationFilterChange"
              >
                <ElOption
                  v-for="item in integrationModuleOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </ElSelect>
              <ElSelect
                v-model="integrationStatusFilter"
                placeholder="状态"
                @change="handleIntegrationFilterChange"
              >
                <ElOption
                  v-for="item in integrationStatusOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </ElSelect>
              <ElButton :loading="integrationLoading" @click="loadIntegrationContract"
                >刷新</ElButton
              >
              <span class="integration-generated-at">
                生成时间：{{ integrationContract.generatedAt || '-' }}
              </span>
            </div>

            <ElRow :gutter="16" class="integration-module-grid">
              <ElCol
                v-for="module in integrationContract.modules"
                :key="module.module"
                :xl="8"
                :lg="8"
                :md="12"
                :sm="24"
                :xs="24"
              >
                <div class="integration-module-card">
                  <div>
                    <strong>{{ module.label }}</strong>
                    <span>{{ module.total }} 字段 · {{ module.aligned }} 已对齐</span>
                  </div>
                  <ElTag
                    :type="module.blockers ? 'danger' : module.pending ? 'warning' : 'success'"
                    effect="plain"
                  >
                    {{ module.blockers ? `${module.blockers} 阻塞` : `${module.pending} 待确认` }}
                  </ElTag>
                </div>
              </ElCol>
            </ElRow>

            <ElTable
              :data="tableRows(integrationRows, tableStates.integration)"
              border
              height="430"
              class="integration-contract-table"
              empty-text="当前筛选下没有字段差异"
              @sort-change="handleTableSortChange('integration', $event)"
            >
              <ElTableColumn prop="moduleLabel" label="模块" width="130" sortable="custom" />
              <ElTableColumn
                prop="__endpoint"
                label="接口"
                min-width="260"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">
                  <span class="method-pill">{{ row.method }}</span>
                  <span>{{ row.endpoint }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="frontendField"
                label="前端字段"
                min-width="180"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="backendField"
                label="后端字段"
                min-width="180"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">{{ row.backendField || '-' }}</template>
              </ElTableColumn>
              <ElTableColumn prop="required" label="必填" width="74" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="row.required ? 'warning' : 'info'" size="small" effect="plain">
                    {{ row.required ? '是' : '否' }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="status" label="状态" width="118" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="integrationStatusTagType(row.status)" size="small" effect="plain">
                    {{ row.status }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="severity" label="级别" width="88" sortable="custom">
                <template #default="{ row }">
                  <ElTag
                    :type="integrationSeverityTagType(row.severity)"
                    size="small"
                    effect="plain"
                  >
                    {{ integrationSeverityLabel(row.severity) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="owner" label="负责人" width="116" sortable="custom" />
              <ElTableColumn
                prop="note"
                label="说明"
                min-width="260"
                show-overflow-tooltip
                sortable="custom"
              />
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.integration.page"
              v-model:page-size="tableStates.integration.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="integrationRows.length"
              @size-change="resetTablePage('integration')"
            />
          </ElCard>
        </ElTabPane>

        <ElTabPane label="审计日志" name="audit">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>审计日志</span>
                <ElTag type="info" effect="plain">{{ auditPagination.total }} 条</ElTag>
              </div>
            </template>
            <ElAlert
              v-if="auditIntegrityAlert"
              class="audit-integrity-alert"
              show-icon
              :closable="false"
              :type="auditIntegrityAlert.type"
              :title="auditIntegrityAlert.title"
              :description="auditIntegrityAlert.description"
            />
            <div class="filter-bar">
              <ElInput
                v-model="auditFilters.keyword"
                clearable
                placeholder="搜索操作人、动作、对象"
              />
              <ElSelect v-model="auditFilters.result" clearable placeholder="结果">
                <ElOption label="成功" value="成功" />
                <ElOption label="失败" value="失败" />
              </ElSelect>
              <ElSelect v-model="auditFilters.objectType" clearable placeholder="对象类型">
                <ElOption label="AdminConfig" value="AdminConfig" />
                <ElOption label="AdminConfigExport" value="AdminConfigExport" />
                <ElOption label="PromptTemplate" value="PromptTemplate" />
                <ElOption label="ProjectMember" value="ProjectMember" />
                <ElOption label="RuleTemplate" value="RuleTemplate" />
                <ElOption label="ReportVersion" value="ReportVersion" />
                <ElOption label="MessageItem" value="MessageItem" />
              </ElSelect>
              <ElButton type="primary" :loading="auditLoading" @click="handleFilterAudit"
                >筛选</ElButton
              >
              <ElButton @click="handleResetAudit">重置</ElButton>
            </div>
            <div v-if="auditError" class="local-error local-error--compact">
              <ElAlert type="error" show-icon :closable="false" :title="auditError" />
              <ElButton type="primary" plain :loading="auditLoading" @click="loadAuditLogs">
                重新加载
              </ElButton>
            </div>
            <ElTable
              :data="auditTableRows"
              border
              height="360"
              v-loading="auditLoading"
              empty-text="当前筛选下暂无审计日志"
              @sort-change="handleAuditSortChange"
            >
              <ElTableColumn prop="actorName" label="操作人" width="110" sortable="custom" />
              <ElTableColumn
                prop="action"
                label="动作"
                min-width="180"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="objectType" label="对象类型" width="130" sortable="custom" />
              <ElTableColumn
                prop="objectId"
                label="对象 ID"
                min-width="160"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="result" label="结果" width="88" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.result)" size="small" effect="plain">
                    {{ row.result }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="createdAt" label="时间" width="170" sortable="custom" />
            </ElTable>
            <ElPagination
              v-model:current-page="auditPagination.page"
              v-model:page-size="auditPagination.pageSize"
              class="table-pagination"
              background
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next"
              :total="auditPagination.total"
              @size-change="handleAuditPageSizeChange"
              @current-change="handleAuditPageChange"
            />
          </ElCard>
        </ElTabPane>
      </ElTabs>

      <ElDialog v-model="projectWizardVisible" title="项目立项向导" width="min(780px, 94vw)">
        <ElSteps :active="projectWizardStep" finish-status="success" align-center>
          <ElStep title="基本信息" />
          <ElStep title="参建单位" />
          <ElStep title="初始授权" />
        </ElSteps>

        <ElForm label-position="top" class="wizard-form">
          <div v-if="projectWizardError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="projectWizardError" />
            <ElButton type="primary" plain :loading="projectCreating" @click="handleCreateProject">
              重试创建
            </ElButton>
          </div>

          <div v-show="projectWizardStep === 0">
            <ElFormItem label="压力管道类别">
              <ElSelect
                v-model="projectWizardForm.businessPackId"
                filterable
                placeholder="请选择压力管道类别"
                @change="handleWizardBusinessPackChange"
              >
                <ElOption
                  v-for="pack in businessPackRows"
                  :key="pack.id"
                  :label="businessPackOptionLabel(pack)"
                  :value="pack.id"
                >
                  <div class="business-pack-option">
                    <span>{{ businessPackTypeLabel(pack) }}</span>
                    <small>{{ businessPackRangeText(pack) }}</small>
                  </div>
                </ElOption>
              </ElSelect>
            </ElFormItem>
            <ElAlert
              v-if="selectedWizardBusinessPack"
              type="info"
              show-icon
              :closable="false"
              :title="selectedWizardBusinessPackDescription"
              class="mb-12px"
            />
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="项目编号">
                  <ElInput v-model="projectWizardForm.code" placeholder="留空自动生成" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="项目名称">
                  <ElInput v-model="projectWizardForm.name" placeholder="请输入项目名称" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="压力管道属性">
                  <ElInput v-model="projectWizardForm.type" disabled />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="区域（选填）">
                  <ElInput v-model="projectWizardForm.region" placeholder="例如：广东省广州市" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElAlert
              type="info"
              show-icon
              :closable="false"
              title="起始节点和节点范围由所选业务类型版本自动确定，立项后不可手工改写。"
            />
          </div>

          <div v-show="projectWizardStep === 1">
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="建设单位">
                  <ElSelect
                    v-model="projectWizardForm.ownerOrgName"
                    filterable
                    placeholder="请选择已启用建设单位"
                    @change="handleWizardOrgChange('owner')"
                  >
                    <ElOption
                      v-for="org in wizardOrgOptions('owner')"
                      :key="org.id"
                      :label="org.name"
                      :value="org.name"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="施工单位">
                  <ElSelect
                    v-model="projectWizardForm.contractorOrgName"
                    filterable
                    placeholder="请选择已启用施工单位"
                    @change="handleWizardOrgChange('contractor')"
                  >
                    <ElOption
                      v-for="org in wizardOrgOptions('contractor')"
                      :key="org.id"
                      :label="org.name"
                      :value="org.name"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElRow :gutter="12">
              <ElCol v-if="wizardUsesRole('ndt')" :xs="24" :sm="12">
                <ElFormItem label="无损检测单位">
                  <ElSelect
                    v-model="projectWizardForm.ndtOrgName"
                    filterable
                    placeholder="请选择已启用无损检测单位"
                    @change="handleWizardOrgChange('ndt')"
                  >
                    <ElOption
                      v-for="org in wizardOrgOptions('ndt')"
                      :key="org.id"
                      :label="org.name"
                      :value="org.name"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="监检机构">
                  <ElSelect
                    v-model="projectWizardForm.inspectionOrgName"
                    filterable
                    placeholder="请选择已启用监检机构"
                    @change="handleWizardOrgChange('inspection')"
                  >
                    <ElOption
                      v-for="org in wizardOrgOptions('inspection')"
                      :key="org.id"
                      :label="org.name"
                      :value="org.name"
                    />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
            </ElRow>
          </div>

          <div v-show="projectWizardStep === 2">
            <ElAlert
              type="info"
              show-icon
              :closable="false"
              :title="`立项后将按 ${selectedWizardBusinessPack?.pipelineTypeCode || '当前'} 业务类型生成节点，并只写入本次明确选择的成员授权。`"
            />
            <ElTable
              :data="tableRows(projectWizardRoles, tableStates.projectWizardRoles)"
              border
              class="wizard-member-table"
              @sort-change="handleTableSortChange('projectWizardRoles', $event)"
            >
              <ElTableColumn prop="__self" label="角色" width="120" sortable="custom">
                <template #default="{ row }">{{ roleLabel(row) }}</template>
              </ElTableColumn>
              <ElTableColumn label="初始成员" min-width="260">
                <template #default="{ row }">
                  <ElSelect
                    v-model="projectWizardForm.memberUserIds[row]"
                    filterable
                    placeholder="请选择所属单位的启用用户"
                    no-data-text="该单位暂无可用用户"
                  >
                    <ElOption
                      v-for="user in wizardUsersByRole(row)"
                      :key="user.id"
                      :label="`${user.name} / ${user.orgName}`"
                      :value="user.id"
                    />
                  </ElSelect>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="__wizardNodeScope"
                label="节点范围"
                min-width="180"
                sortable="custom"
              >
                <template #default>
                  按业务类型授权 {{ selectedWizardBusinessPack?.nodeCount || 0 }} 个节点
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.projectWizardRoles.page"
              v-model:page-size="tableStates.projectWizardRoles.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="projectWizardRoles.length"
              @size-change="resetTablePage('projectWizardRoles')"
            />
          </div>
        </ElForm>

        <template #footer>
          <ElButton @click="projectWizardVisible = false">取消</ElButton>
          <ElButton v-if="projectWizardStep > 0" @click="projectWizardStep -= 1">上一步</ElButton>
          <ElButton v-if="projectWizardStep < 2" type="primary" @click="handleProjectWizardNext">
            下一步
          </ElButton>
          <ElButton v-else type="primary" :loading="projectCreating" @click="handleCreateProject">
            创建项目
          </ElButton>
        </template>
      </ElDialog>

      <ElDialog v-model="projectEditVisible" title="编辑项目" width="min(720px, 94vw)">
        <ElForm label-position="top" class="wizard-form">
          <div v-if="projectOperationError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="projectOperationError" />
          </div>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="项目编号">
                <ElInput v-model="projectEditForm.code" disabled />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="项目名称">
                <ElInput v-model="projectEditForm.name" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="项目类型">
                <ElInput v-model="projectEditForm.type" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="区域">
                <ElInput v-model="projectEditForm.region" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="建设单位快照">
                <ElInput v-model="projectEditForm.ownerOrgName" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="施工单位快照">
                <ElInput v-model="projectEditForm.contractorOrgName" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="无损检测单位快照">
                <ElInput v-model="projectEditForm.ndtOrgName" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="监检机构快照">
                <ElInput v-model="projectEditForm.inspectionOrgName" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem label="状态">
            <ElSelect v-model="projectEditForm.status">
              <ElOption label="草稿/立项中" value="草稿/立项中" />
              <ElOption label="资料提交中" value="资料提交中" />
              <ElOption label="AI 预审中" value="AI 预审中" />
              <ElOption label="监检审查中" value="监检审查中" />
              <ElOption label="退回补正中" value="退回补正中" />
              <ElOption label="报告生成/复核中" value="报告生成/复核中" />
              <ElOption label="已归档" value="已归档" />
            </ElSelect>
          </ElFormItem>
        </ElForm>
        <template #footer>
          <ElButton @click="projectEditVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="projectSaving" @click="handleSaveProjectEdit">
            保存
          </ElButton>
        </template>
      </ElDialog>

      <ElDialog
        v-model="orgDialogVisible"
        :title="orgDialogMode === 'create' ? '新增组织' : '编辑组织'"
        width="min(560px, 92vw)"
      >
        <ElForm label-position="top" class="wizard-form">
          <div v-if="orgOperationError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="orgOperationError" />
          </div>
          <ElFormItem label="组织名称">
            <ElInput v-model="orgForm.name" />
          </ElFormItem>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="组织类型">
                <ElSelect v-model="orgForm.type">
                  <ElOption label="监检机构" value="inspection" />
                  <ElOption label="施工方" value="contractor" />
                  <ElOption label="无损检测" value="ndt" />
                  <ElOption label="建设方" value="owner" />
                  <ElOption label="平台管理" value="admin" />
                  <ElOption label="FDE" value="fde" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="状态">
                <ElSelect v-model="orgForm.status">
                  <ElOption label="启用" value="启用" />
                  <ElOption label="停用" value="停用" />
                  <ElOption label="待授权" value="待授权" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="联系人">
                <ElInput v-model="orgForm.contactName" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="联系电话">
                <ElInput v-model="orgForm.contactPhone" />
              </ElFormItem>
            </ElCol>
          </ElRow>
        </ElForm>
        <template #footer>
          <ElButton @click="orgDialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="orgSaving" @click="handleSaveOrg">保存</ElButton>
        </template>
      </ElDialog>

      <ElDialog
        v-model="userDialogVisible"
        :title="userDialogMode === 'create' ? '新增用户' : '编辑用户'"
        width="min(640px, 92vw)"
      >
        <ElForm label-position="top" class="wizard-form">
          <div v-if="userOperationError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="userOperationError" />
          </div>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="用户名">
                <ElInput v-model="userForm.username" :disabled="userDialogMode === 'edit'" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="姓名">
                <ElInput v-model="userForm.name" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="角色">
                <ElSelect v-model="userForm.role" @change="handleUserRoleChange">
                  <ElOption label="监检人员" value="inspection" />
                  <ElOption label="施工方" value="contractor" />
                  <ElOption label="无损检测" value="ndt" />
                  <ElOption label="建设方" value="owner" />
                  <ElOption label="系统管理员" value="admin" />
                  <ElOption label="FDE" value="fde" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="所属组织">
                <ElSelect v-model="userForm.orgId" clearable filterable>
                  <ElOption
                    v-for="org in roleOrgOptions(userForm.role)"
                    :key="org.id"
                    :label="org.name"
                    :value="org.id"
                  />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="手机号">
                <ElInput v-model="userForm.mobile" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="状态">
                <ElSelect v-model="userForm.status">
                  <ElOption label="启用" value="启用" />
                  <ElOption label="停用" value="停用" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem :label="userDialogMode === 'create' ? '初始密码' : '重置密码'">
            <ElInput
              v-model="userForm.password"
              show-password
              autocomplete="new-password"
              :placeholder="
                userDialogMode === 'create'
                  ? `默认 ${DEFAULT_INITIAL_PASSWORD}；可修改`
                  : '留空则不修改；填写后用户须首次改密'
              "
            />
          </ElFormItem>
        </ElForm>
        <template #footer>
          <ElButton @click="userDialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="userSaving" @click="handleSaveUser">保存</ElButton>
        </template>
      </ElDialog>

      <ElDrawer
        v-model="configDrawerVisible"
        :title="`${configEditMode === 'create' ? '新增' : '编辑'}${configTargetLabel}`"
        size="min(560px, 92vw)"
      >
        <ElForm label-position="top" class="config-edit-form">
          <ElAlert
            type="warning"
            show-icon
            :closable="false"
            title="配置变更会写入审计日志；业务审查意见仍需在对应工作台办理。"
          />
          <div v-if="configOperationError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="configOperationError" />
            <ElButton
              v-if="configOperationRetry"
              type="primary"
              plain
              :loading="configSaving || configPreviewing"
              @click="retryConfigOperation"
            >
              重试操作
            </ElButton>
          </div>

          <template v-if="configEditTarget === 'permission'">
            <ElFormItem label="角色名称">
              <ElInput v-model="configForm.label" />
            </ElFormItem>
            <ElFormItem label="项目范围">
              <ElInput v-model="configForm.projectScope" />
            </ElFormItem>
            <ElFormItem label="节点范围">
              <ElInput v-model="configForm.nodeScope" />
            </ElFormItem>
            <ElFormItem label="只读">
              <ElSwitch v-model="configForm.readonly" />
            </ElFormItem>
            <ElFormItem label="动作权限">
              <ElCheckboxGroup v-model="configForm.actions" class="action-checkbox-grid">
                <ElCheckbox
                  v-for="action in allActionOptions"
                  :key="action"
                  :label="action"
                  :title="actionLabelWithCode(action)"
                >
                  {{ actionLabel(action) }}
                </ElCheckbox>
              </ElCheckboxGroup>
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'node-template'">
            <ElFormItem label="业务分组">
              <ElInput v-model="configForm.groupName" />
            </ElFormItem>
            <ElFormItem label="版本">
              <ElInput v-model="configForm.version" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="节点数">
                  <ElInputNumber v-model="configForm.nodeCount" :min="0" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="资料项">
                  <ElInputNumber v-model="configForm.requiredCount" :min="0" :max="200" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="状态">
              <ElRadioGroup v-model="configForm.nodeTemplateStatus">
                <ElRadioButton label="草稿" />
                <ElRadioButton label="已发布" />
                <ElRadioButton label="已停用" />
              </ElRadioGroup>
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'workflow'">
            <ElFormItem label="流程名称">
              <ElInput v-model="configForm.workflowName" />
            </ElFormItem>
            <ElFormItem label="版本">
              <ElInput v-model="configForm.version" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="状态数">
                  <ElInputNumber v-model="configForm.states" :min="1" :max="60" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="流转数">
                  <ElInputNumber v-model="configForm.transitions" :min="1" :max="120" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="状态">
              <ElRadioGroup v-model="configForm.workflowStatus">
                <ElRadioButton label="启用" />
                <ElRadioButton label="停用" />
              </ElRadioGroup>
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'todo-rule'">
            <ElFormItem label="规则名称">
              <ElInput v-model="configForm.todoRuleName" />
            </ElFormItem>
            <ElFormItem label="触发状态">
              <ElInput v-model="configForm.triggerStatus" placeholder="例如 AI 预审中" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="处理角色">
                  <ElSelect v-model="configForm.assigneeRole">
                    <ElOption label="监检" value="inspection" />
                    <ElOption label="施工" value="contractor" />
                    <ElOption label="无损检测" value="ndt" />
                    <ElOption label="建设方" value="owner" />
                    <ElOption label="管理" value="admin" />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="办理时限">
                  <ElInputNumber v-model="configForm.deadlineHours" :min="1" :max="720" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="启用状态">
              <ElSwitch v-model="configForm.fineEnabled" active-text="启用" inactive-text="停用" />
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'message-template'">
            <ElFormItem label="场景">
              <ElInput v-model="configForm.scene" placeholder="例如 review-return-correction" />
            </ElFormItem>
            <ElFormItem label="发送渠道">
              <ElRadioGroup v-model="configForm.channel">
                <ElRadioButton label="站内信" />
                <ElRadioButton label="短信" />
                <ElRadioButton label="邮件" />
              </ElRadioGroup>
            </ElFormItem>
            <ElFormItem label="标题模板">
              <ElInput v-model="configForm.titleTemplate" />
            </ElFormItem>
            <ElFormItem label="内容模板">
              <ElInput v-model="configForm.contentTemplate" type="textarea" :rows="4" />
            </ElFormItem>
            <ElFormItem label="启用状态">
              <ElSwitch v-model="configForm.fineEnabled" active-text="启用" inactive-text="停用" />
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'tool-source'">
            <ElFormItem label="工具名称">
              <ElInput v-model="configForm.toolName" />
            </ElFormItem>
            <ElFormItem label="工具类型">
              <ElSelect v-model="configForm.toolType">
                <ElOption label="外部查询" value="external-query" />
                <ElOption label="OCR" value="ocr" />
                <ElOption label="电子签章" value="signature" />
                <ElOption label="归档服务" value="archive" />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="接口地址">
              <ElInput v-model="configForm.endpoint" />
            </ElFormItem>
            <ElFormItem label="鉴权方式">
              <ElRadioGroup v-model="configForm.authMode">
                <ElRadioButton label="none">无</ElRadioButton>
                <ElRadioButton label="token">Token</ElRadioButton>
                <ElRadioButton label="signature">签名</ElRadioButton>
              </ElRadioGroup>
            </ElFormItem>
            <ElFormItem label="运行状态">
              <ElRadioGroup v-model="configForm.toolStatus">
                <ElRadioButton label="启用" />
                <ElRadioButton label="停用" />
                <ElRadioButton label="异常" />
              </ElRadioGroup>
            </ElFormItem>
          </template>

          <template v-else-if="configEditTarget === 'material-review-point'">
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="业务包">
                  <ElInput v-model="configForm.reviewPointBusinessPackId" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="节点编号">
                  <ElInputNumber v-model="configForm.reviewPointNodeId" :min="1" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="节点名称">
              <ElInput v-model="configForm.reviewPointNodeName" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="规则">
                  <ElInput v-model="configForm.reviewPointRuleId" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="类别">
                  <ElInput v-model="configForm.reviewPointReviewClass" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="业务模块">
              <ElInput v-model="configForm.reviewPointBusinessModule" />
            </ElFormItem>
            <ElFormItem label="审查点">
              <ElInput v-model="configForm.reviewPointReviewContent" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="资料大类">
                  <ElInput v-model="configForm.reviewPointMaterialCategory" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="资料类型编码">
                  <ElInput v-model="configForm.reviewPointMaterialTypeCode" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="资料类型名称">
              <ElInput v-model="configForm.reviewPointMaterialTypeName" />
            </ElFormItem>
            <ElFormItem label="审查内容">
              <ElInput v-model="configForm.reviewPointFileContent" type="textarea" :rows="2" />
            </ElFormItem>
            <ElFormItem label="OCR证据项">
              <ElInput v-model="configForm.reviewPointEvidenceItemText" type="textarea" :rows="3" />
            </ElFormItem>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="责任方">
                  <ElSelect v-model="configForm.reviewPointResponsibleParty">
                    <ElOption label="施工" value="contractor" />
                    <ElOption label="无损检测" value="ndt" />
                    <ElOption label="监检" value="inspection" />
                    <ElOption label="建设方" value="owner" />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="必传口径">
                  <ElSelect v-model="configForm.reviewPointRequiredType">
                    <ElOption label="必传" value="必传" />
                    <ElOption label="条件必传" value="条件必传" />
                    <ElOption label="可选" value="可选" />
                  </ElSelect>
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="命中阈值">
                  <ElInputNumber
                    v-model="configForm.reviewPointMinConfidence"
                    :min="0"
                    :max="1"
                    :step="0.01"
                    :precision="2"
                  />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="启用状态">
                  <ElSwitch
                    v-model="configForm.fineEnabled"
                    active-text="启用"
                    inactive-text="停用"
                  />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="映射关系">
              <ElInput v-model="configForm.reviewPointMappingRelation" />
            </ElFormItem>
          </template>

          <template v-else>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="节点编号">
                  <ElInputNumber v-model="configForm.fieldNodeId" :min="1" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="置信阈值">
                  <ElInputNumber
                    v-model="configForm.confidenceThreshold"
                    :min="0"
                    :max="1"
                    :step="0.01"
                    :precision="2"
                  />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="字段名称">
              <ElInput v-model="configForm.fieldName" />
            </ElFormItem>
            <ElFormItem label="来源字段">
              <ElInput v-model="configForm.sourceField" />
            </ElFormItem>
            <ElFormItem label="目标字段">
              <ElInput v-model="configForm.targetField" />
            </ElFormItem>
            <ElFormItem label="必填">
              <ElSwitch v-model="configForm.fieldRequired" active-text="是" inactive-text="否" />
            </ElFormItem>
          </template>

          <ElFormItem label="变更原因">
            <ElInput
              v-model="configForm.reason"
              type="textarea"
              :rows="3"
              placeholder="请输入可审计的配置变更原因"
            />
          </ElFormItem>
        </ElForm>
        <div class="drawer-footer">
          <ElButton
            v-if="canPreviewConfigDiff"
            :loading="configPreviewing"
            @click="handlePreviewConfigDiff"
            >预览差异</ElButton
          >
          <ElButton type="primary" :loading="configSaving" @click="handleSaveConfigItem">
            {{ configEditMode === 'create' ? '新增配置' : '保存配置' }}
          </ElButton>
        </div>
      </ElDrawer>

      <ElDrawer
        v-model="promptTemplateDialogVisible"
        :title="promptTemplateDialogMode === 'create' ? '新增 Prompt 模板' : '编辑 Prompt 模板'"
        size="min(900px, 94vw)"
      >
        <ElForm label-position="top" class="prompt-template-form">
          <ElAlert
            type="info"
            show-icon
            :closable="false"
            title="模板正文会在 AI Check 推理链路中完整留痕，用于审计、复盘和版本对比。"
          />
          <div v-if="promptTemplateOperationError" class="local-error local-error--compact">
            <ElAlert
              type="error"
              show-icon
              :closable="false"
              :title="promptTemplateOperationError"
            />
          </div>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="模板名称">
                <ElInput v-model="promptTemplateForm.name" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="Prompt Key">
                <ElInput v-model="promptTemplateForm.promptKey" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="版本">
                <ElInput v-model="promptTemplateForm.version" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="状态">
                <ElSelect v-model="promptTemplateForm.status">
                  <ElOption label="草稿" value="draft" />
                  <ElOption label="生产" value="production" />
                  <ElOption label="已停用" value="retired" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="风险等级">
                <ElSelect v-model="promptTemplateForm.riskLevel">
                  <ElOption label="高" value="high" />
                  <ElOption label="中" value="medium" />
                  <ElOption label="低" value="low" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="业务包 ID">
                <ElInput v-model="promptTemplateForm.businessPackId" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="Agent ID">
                <ElInput v-model="promptTemplateForm.agentId" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="关联 Prompt 版本">
                <ElInput v-model="promptTemplateForm.promptVersionId" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem label="System Prompt">
            <ElInput
              v-model="promptTemplateForm.systemPrompt"
              type="textarea"
              :rows="5"
              resize="vertical"
            />
          </ElFormItem>
          <ElFormItem label="User Prompt 模板">
            <ElInput
              v-model="promptTemplateForm.userPromptTemplate"
              type="textarea"
              :rows="8"
              resize="vertical"
            />
          </ElFormItem>
          <ElFormItem label="Plan 编排 Prompt">
            <ElInput
              v-model="promptTemplateForm.plannerPromptTemplate"
              type="textarea"
              :rows="4"
              resize="vertical"
            />
          </ElFormItem>
          <ElFormItem label="Critic 复核 Prompt">
            <ElInput
              v-model="promptTemplateForm.criticPromptTemplate"
              type="textarea"
              :rows="4"
              resize="vertical"
            />
          </ElFormItem>
          <ElFormItem label="输出结构 JSON">
            <ElInput
              v-model="promptTemplateForm.outputSchemaText"
              type="textarea"
              :rows="7"
              resize="vertical"
            />
          </ElFormItem>
        </ElForm>
        <div class="drawer-footer">
          <ElButton @click="promptTemplateDialogVisible = false">取消</ElButton>
          <ElButton
            type="primary"
            :loading="promptTemplateSaving"
            @click="handleSavePromptTemplate"
          >
            保存模板
          </ElButton>
        </div>
      </ElDrawer>

      <ElDrawer
        v-model="reportTemplateDialogVisible"
        :title="
          reportTemplateDialogMode === 'create'
            ? '新增报告模板'
            : reportTemplateDialogMode === 'view'
              ? '查看报告模板（生产版本，不可改）'
              : '编辑报告模板'
        "
        size="min(820px, 94vw)"
      >
        <!-- disabled 加在 ElForm 上，整张表单一起只读；逐个控件加会漏，
             漏掉的那个就是「看起来能改、保存却没有按钮」。 -->
        <ElForm
          label-position="top"
          class="prompt-template-form"
          :disabled="reportTemplateDialogMode === 'view'"
        >
          <ElAlert
            v-if="reportTemplateDialogMode === 'view'"
            type="warning"
            show-icon
            :closable="false"
            :title="reportTemplateLockedHint"
          />
          <ElAlert
            v-else
            type="info"
            show-icon
            :closable="false"
            title="发布后将替换同一业务包的生产模板；已生成报告保留当时的模板快照。"
          />
          <div v-if="reportTemplateOperationError" class="local-error local-error--compact">
            <ElAlert
              type="error"
              show-icon
              :closable="false"
              :title="reportTemplateOperationError"
            />
          </div>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="模板名称">
                <ElInput v-model="reportTemplateForm.name" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="6">
              <ElFormItem label="版本">
                <ElInput v-model="reportTemplateForm.version" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="6">
              <ElFormItem label="状态">
                <ElSelect v-model="reportTemplateForm.status">
                  <ElOption label="草稿" value="draft" />
                  <ElOption label="已停用" value="retired" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="16">
              <ElFormItem label="业务包 ID">
                <ElInput v-model="reportTemplateForm.businessPackId" />
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="8">
              <ElFormItem label="业务包版本">
                <ElInput v-model="reportTemplateForm.businessPackVersion" />
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem label="允许的导出类型">
            <ElCheckboxGroup v-model="reportTemplateForm.exportTypes">
              <ElCheckbox value="report">报告</ElCheckbox>
              <ElCheckbox value="archive-package">归档包</ElCheckbox>
              <ElCheckbox value="evidence-package">证据包</ElCheckbox>
            </ElCheckboxGroup>
          </ElFormItem>
          <ElFormItem label="章节配置 JSON">
            <ElInput
              v-model="reportTemplateForm.sectionsText"
              type="textarea"
              :rows="16"
              resize="vertical"
              placeholder='[{"code":"project_summary","title":"项目概况","source":"project"}]'
            />
          </ElFormItem>
        </ElForm>
        <div class="drawer-footer">
          <ElButton @click="reportTemplateDialogVisible = false">
            {{ reportTemplateDialogMode === 'view' ? '关闭' : '取消' }}
          </ElButton>
          <!-- 查看模式不留保存按钮：留着就是一个能改却存不进去的假编辑，
               比直接说明不可改更糟。 -->
          <ElButton
            v-if="reportTemplateDialogMode !== 'view'"
            type="primary"
            :loading="reportTemplateSaving"
            @click="handleSaveReportTemplate"
          >
            保存模板
          </ElButton>
        </div>
      </ElDrawer>

      <ElDialog v-model="configDiffVisible" title="配置差异" width="min(720px, 94vw)">
        <ElEmpty v-if="!latestConfigDiff" description="暂无配置差异" />
        <template v-else>
          <ElDescriptions :column="2" border>
            <ElDescriptionsItem label="配置项">{{
              latestConfigDiff.objectName
            }}</ElDescriptionsItem>
            <ElDescriptionsItem label="对象 ID">{{ latestConfigDiff.objectId }}</ElDescriptionsItem>
            <ElDescriptionsItem label="类型">{{ latestConfigDiff.target }}</ElDescriptionsItem>
            <ElDescriptionsItem label="时间">{{ latestConfigDiff.previewedAt }}</ElDescriptionsItem>
          </ElDescriptions>
          <ElTable
            :data="tableRows(configDiffRows, tableStates.configDiff)"
            border
            class="diff-table"
            @sort-change="handleTableSortChange('configDiff', $event)"
          >
            <ElTableColumn prop="label" label="字段" width="120" sortable="custom" />
            <ElTableColumn
              prop="before"
              label="变更前"
              min-width="210"
              show-overflow-tooltip
              sortable="custom"
            >
              <template #default="{ row }">{{ formatConfigValue(row.before) }}</template>
            </ElTableColumn>
            <ElTableColumn
              prop="after"
              label="变更后"
              min-width="210"
              show-overflow-tooltip
              sortable="custom"
            >
              <template #default="{ row }">{{ formatConfigValue(row.after) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="severity" label="等级" width="90" sortable="custom">
              <template #default="{ row }">
                <ElTag :type="row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                  {{ row.severity === 'warning' ? '需复核' : '信息' }}
                </ElTag>
              </template>
            </ElTableColumn>
          </ElTable>
          <ElPagination
            v-model:current-page="tableStates.configDiff.page"
            v-model:page-size="tableStates.configDiff.pageSize"
            class="table-pagination"
            background
            :page-sizes="tablePageSizes"
            layout="total, sizes, prev, pager, next, jumper"
            :total="configDiffRows.length"
            @size-change="resetTablePage('configDiff')"
          />
          <ElEmpty v-if="!configDiffRows.length" description="当前表单与已保存配置一致" />
        </template>
      </ElDialog>

      <ElDialog v-model="publishTraceVisible" title="发布联动追溯" width="min(760px, 94vw)">
        <ElEmpty v-if="!latestPublishResult" description="暂无发布结果" />
        <template v-else>
          <ElDescriptions :column="2" border>
            <ElDescriptionsItem label="发布版本">
              {{ latestPublishResult.version }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="发布状态">
              {{ latestPublishResult.status }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="审计编号">
              {{ latestPublishResult.auditLogId }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="发布时间">
              {{ latestPublishResult.publishedAt }}
            </ElDescriptionsItem>
            <ElDescriptionsItem label="影响配置">
              {{ latestPublishResult.impactSummary.totalAffected }} 项
            </ElDescriptionsItem>
            <ElDescriptionsItem label="在检项目">
              {{ latestPublishResult.impactSummary.linkedProjects }} 个
            </ElDescriptionsItem>
            <ElDescriptionsItem label="工作台消息">
              {{ latestPublishResult.impactSummary.pushedMessages }} 条
            </ElDescriptionsItem>
            <ElDescriptionsItem label="复核待办">
              {{ latestPublishResult.impactSummary.reviewTodos }} 条
            </ElDescriptionsItem>
          </ElDescriptions>
          <ElTable
            :data="tableRows(publishImpactRows, tableStates.publishImpact)"
            border
            class="publish-impact-table"
            @sort-change="handleTableSortChange('publishImpact', $event)"
          >
            <ElTableColumn prop="label" label="配置域" width="118" sortable="custom" />
            <ElTableColumn prop="affectedCount" label="影响项" width="86" sortable="custom" />
            <ElTableColumn prop="status" label="状态" width="96" sortable="custom">
              <template #default="{ row }">
                <ElTag :type="row.status === '需复核' ? 'warning' : 'success'" effect="plain">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn
              prop="trace"
              label="联动追溯"
              min-width="320"
              show-overflow-tooltip
              sortable="custom"
            />
          </ElTable>
          <ElPagination
            v-model:current-page="tableStates.publishImpact.page"
            v-model:page-size="tableStates.publishImpact.pageSize"
            class="table-pagination"
            background
            :page-sizes="tablePageSizes"
            layout="total, sizes, prev, pager, next, jumper"
            :total="publishImpactRows.length"
            @size-change="resetTablePage('publishImpact')"
          />
        </template>
      </ElDialog>

      <ElDrawer
        v-model="ruleDetailDrawerVisible"
        title="规则与 Prompt 版本详情"
        size="min(720px, 94vw)"
      >
        <div class="drawer-content">
          <ElEmpty v-if="!selectedRuleVersion" description="暂无AI业务规则版本详情" />
          <template v-else>
            <ElDescriptions :column="2" border>
              <ElDescriptionsItem label="规则名称">{{
                selectedRuleVersion.name
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="规则 Key">{{
                selectedRuleVersion.ruleKey
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="AI业务规则版本">{{
                selectedRuleVersion.version
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="状态">
                <ElTag :type="statusType(selectedRuleVersion.status)" effect="light">
                  {{ selectedRuleVersion.status }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="Prompt 版本">
                {{ selectedRuleVersion.promptVersion }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="输出结构">
                {{ selectedRuleVersion.outputSchemaVersion }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="发布时间">
                {{ selectedRuleVersion.publishedAt || '-' }}
              </ElDescriptionsItem>
              <ElDescriptionsItem label="更新时间">
                {{ selectedRuleVersion.updatedAt }}
              </ElDescriptionsItem>
            </ElDescriptions>

            <ElDivider content-position="left">影响节点</ElDivider>
            <div class="rule-node-list">
              <ElTag
                v-for="nodeId in selectedRuleVersion.nodeIds"
                :key="nodeId"
                type="info"
                effect="plain"
              >
                节点 {{ nodeId }}
              </ElTag>
            </div>

            <ElDivider content-position="left">动作权限</ElDivider>
            <div class="tag-list">
              <ElTag
                v-for="action in selectedRuleVersion.actions"
                :key="action"
                type="success"
                effect="plain"
              >
                {{ action }}
              </ElTag>
            </div>

            <ElDivider content-position="left">说明</ElDivider>
            <div class="rule-description">
              {{ selectedRuleVersion.description || '暂无规则说明' }}
            </div>
          </template>
        </div>
      </ElDrawer>

      <ElDrawer v-model="adminRuleDiffVisible" title="AI业务规则版本差异" size="min(760px, 94vw)">
        <div v-loading="adminRuleDiffLoading" class="drawer-content rule-diff-drawer">
          <div v-if="adminRuleDiffError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="adminRuleDiffError" />
            <ElButton
              type="primary"
              plain
              :loading="adminRuleDiffLoading"
              @click="retryRuleVersionDiff"
            >
              重新加载
            </ElButton>
          </div>
          <ElEmpty v-if="!adminRuleDiff && !adminRuleDiffError" description="暂无规则差异" />
          <template v-if="adminRuleDiff">
            <ElDescriptions :column="1" border>
              <ElDescriptionsItem label="当前版本">{{
                adminRuleDiff.base.version
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="对比版本">{{
                adminRuleDiff.target.version
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="规则">{{ adminRuleDiff.base.name }}</ElDescriptionsItem>
              <ElDescriptionsItem label="对比时间">{{
                adminRuleDiff.comparedAt
              }}</ElDescriptionsItem>
            </ElDescriptions>

            <div class="rule-diff-summary">
              <div
                v-for="item in adminRuleDiffSummaryItems"
                :key="item.label"
                class="rule-diff-metric"
              >
                <span>{{ item.label }}</span>
                <strong>
                  {{ item.value }}
                  <small>项</small>
                </strong>
              </div>
            </div>

            <ElTable
              :data="tableRows(adminRuleDiffRows, tableStates.adminRuleDiff)"
              border
              height="360"
              empty-text="当前对比未发现字段差异"
              @sort-change="handleTableSortChange('adminRuleDiff', $event)"
            >
              <ElTableColumn prop="label" label="字段" width="130" sortable="custom" />
              <ElTableColumn prop="changeType" label="类型" width="96" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="diffChangeTagType(row.changeType)" effect="light">
                    {{ diffChangeTypeLabel(row.changeType) }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="before"
                label="基线值"
                min-width="220"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">
                  <span class="diff-value">{{ formatRuleDiffValue(row.before) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn
                prop="after"
                label="当前值"
                min-width="220"
                show-overflow-tooltip
                sortable="custom"
              >
                <template #default="{ row }">
                  <span class="diff-value">{{ formatRuleDiffValue(row.after) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="severity" label="关注" width="90" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                    {{ row.severity === 'warning' ? '需复核' : '信息' }}
                  </ElTag>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.adminRuleDiff.page"
              v-model:page-size="tableStates.adminRuleDiff.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="adminRuleDiffRows.length"
              @size-change="resetTablePage('adminRuleDiff')"
            />
          </template>
        </div>
      </ElDrawer>

      <ElDrawer v-model="projectDrawerVisible" title="项目详情与成员授权" size="min(920px, 94vw)">
        <div v-loading="projectDetailLoading" class="drawer-content">
          <div v-if="projectDetailError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="projectDetailError" />
            <ElButton
              v-if="projectDetailProjectId"
              type="primary"
              plain
              :loading="projectDetailLoading"
              @click="loadProjectDetail(projectDetailProjectId)"
            >
              重新加载
            </ElButton>
          </div>
          <ElEmpty v-if="!projectDetail && !projectDetailError" description="暂无项目详情" />
          <template v-if="projectDetail">
            <ElDescriptions :column="2" border>
              <ElDescriptionsItem label="项目编号">{{
                projectDetail.project.code
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="项目名称">{{
                projectDetail.project.name
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="区域">{{
                formatProjectRegion(projectDetail.project.region)
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="状态">
                <ElTag :type="statusType(projectDetail.project.status)" effect="light">
                  {{ projectDetail.project.status }}
                </ElTag>
              </ElDescriptionsItem>
              <ElDescriptionsItem label="当前节点">{{
                projectDetail.project.currentNodeId
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="更新时间">{{
                projectDetail.project.updatedAt
              }}</ElDescriptionsItem>
            </ElDescriptions>

            <ElDivider content-position="left">参建单位</ElDivider>
            <ElTable
              :data="tableRows(projectDetail.participantUnits, tableStates.projectParticipants)"
              border
              height="210"
              @sort-change="handleTableSortChange('projectParticipants', $event)"
            >
              <ElTableColumn
                prop="unitName"
                label="单位"
                min-width="220"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="unitType" label="类型" width="140" sortable="custom">
                <template #default="{ row }">{{ formatParticipantType(row.unitType) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="contactName" label="联系人" width="100" sortable="custom" />
              <ElTableColumn prop="contactPhone" label="电话" width="140" sortable="custom" />
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.projectParticipants.page"
              v-model:page-size="tableStates.projectParticipants.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="projectDetail.participantUnits.length"
              @size-change="resetTablePage('projectParticipants')"
            />

            <ElDivider content-position="left">成员授权</ElDivider>
            <div v-if="memberOperationError" class="local-error local-error--compact">
              <ElAlert type="error" show-icon :closable="false" :title="memberOperationError" />
            </div>
            <div class="drawer-action-row">
              <ElTag effect="plain">{{ selectedProjectMembers.length }} 名成员</ElTag>
              <ElSpace wrap>
                <ElButton @click="openMemberBatchDialog">批量授权</ElButton>
                <ElButton type="primary" @click="openMemberDialog">新增授权</ElButton>
              </ElSpace>
            </div>
            <ElTable
              :data="tableRows(selectedProjectMembers, tableStates.projectMembers)"
              border
              height="280"
              @sort-change="handleTableSortChange('projectMembers', $event)"
            >
              <ElTableColumn prop="name" label="姓名" width="96" sortable="custom" />
              <ElTableColumn
                prop="orgName"
                label="组织"
                min-width="190"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="role" label="角色" width="100" sortable="custom">
                <template #default="{ row }">
                  <ElTag effect="plain">{{ roleLabel(row.role) }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="nodeScope" label="节点范围" min-width="160" sortable="custom">
                <template #default="{ row }">{{ formatNodeScope(row.nodeScope) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="actions" label="动作" min-width="220" sortable="custom">
                <template #default="{ row }">
                  <div class="tag-list">
                    <ElTag
                      v-for="action in row.actions.slice(0, 4)"
                      :key="action"
                      size="small"
                      effect="plain"
                    >
                      {{ action }}
                    </ElTag>
                    <ElTag v-if="row.actions.length > 4" size="small" type="info" effect="plain">
                      +{{ row.actions.length - 4 }}
                    </ElTag>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="status" label="状态" width="96" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" size="small" effect="plain">
                    {{ row.status }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="124" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    link
                    :type="row.status === '启用' ? 'danger' : 'success'"
                    :loading="memberSaving"
                    @click="handleToggleMemberStatus(row)"
                  >
                    {{ row.status === '启用' ? '停用' : '启用' }}
                  </ElButton>
                  <ElButton
                    link
                    type="danger"
                    :loading="memberSaving"
                    @click="handleDeleteMember(row)"
                  >
                    移除
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.projectMembers.page"
              v-model:page-size="tableStates.projectMembers.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="selectedProjectMembers.length"
              @size-change="resetTablePage('projectMembers')"
            />

            <ElDivider content-position="left">节点概况</ElDivider>
            <ElTable
              :data="tableRows(projectDetail.nodeSummary, tableStates.projectNodeSummary)"
              border
              height="260"
              @sort-change="handleTableSortChange('projectNodeSummary', $event)"
            >
              <ElTableColumn
                prop="groupName"
                label="业务分组"
                min-width="190"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="total" label="节点" width="76" sortable="custom" />
              <ElTableColumn prop="passed" label="已通过" width="86" sortable="custom" />
              <ElTableColumn prop="correction" label="补正" width="76" sortable="custom" />
              <ElTableColumn prop="pending" label="待处理" width="86" sortable="custom" />
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.projectNodeSummary.page"
              v-model:page-size="tableStates.projectNodeSummary.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="projectDetail.nodeSummary.length"
              @size-change="resetTablePage('projectNodeSummary')"
            />

            <ElDivider content-position="left">近期导出</ElDivider>
            <ElTable
              :data="tableRows(projectDetail.recentExportTasks, tableStates.projectExports)"
              border
              height="220"
              @sort-change="handleTableSortChange('projectExports', $event)"
            >
              <ElTableColumn
                prop="id"
                label="任务号"
                min-width="170"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn
                prop="fileName"
                label="文件"
                min-width="220"
                show-overflow-tooltip
                sortable="custom"
              />
              <ElTableColumn prop="status" label="状态" width="100" sortable="custom">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="fileSize" label="大小" width="100" sortable="custom">
                <template #default="{ row }">{{ formatFileSize(row.fileSize) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="createdAt" label="创建时间" width="170" sortable="custom" />
            </ElTable>
            <ElPagination
              v-model:current-page="tableStates.projectExports.page"
              v-model:page-size="tableStates.projectExports.pageSize"
              class="table-pagination"
              background
              :page-sizes="tablePageSizes"
              layout="total, sizes, prev, pager, next, jumper"
              :total="projectDetail.recentExportTasks.length"
              @size-change="resetTablePage('projectExports')"
            />
          </template>
        </div>
      </ElDrawer>

      <ElDialog v-model="memberDialogVisible" :title="memberDialogTitle" width="min(680px, 92vw)">
        <ElForm label-position="top" class="member-form">
          <div v-if="memberOperationError" class="local-error local-error--compact">
            <ElAlert type="error" show-icon :closable="false" :title="memberOperationError" />
            <ElButton type="primary" plain :loading="memberSaving" @click="handleSaveMember">
              重试保存
            </ElButton>
          </div>
          <div v-if="memberBatchResult" class="batch-result">
            <ElTag type="success" effect="plain"
              >成功 {{ memberBatchResult.successCount }} 人</ElTag
            >
            <ElTag v-if="memberBatchResult.failed.length" type="danger" effect="plain">
              失败 {{ memberBatchResult.failed.length }} 人
            </ElTag>
            <div v-if="memberBatchResult.failed.length" class="batch-result-list">
              <span v-for="item in memberBatchResult.failed" :key="item.userId">
                {{ item.name }}：{{ item.message }}
              </span>
            </div>
          </div>

          <ElRow :gutter="12">
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="角色筛选">
                <ElSelect v-model="memberForm.role" @change="handleMemberRoleChange">
                  <ElOption label="监检" value="inspection" />
                  <ElOption label="施工" value="contractor" />
                  <ElOption label="无损检测" value="ndt" />
                  <ElOption label="建设方" value="owner" />
                  <ElOption label="管理" value="admin" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="组织筛选">
                <ElSelect
                  v-model="memberForm.orgId"
                  clearable
                  filterable
                  @change="handleMemberOrgChange"
                >
                  <ElOption
                    v-for="org in roleOrgOptions(memberForm.role)"
                    :key="org.id"
                    :label="org.name"
                    :value="org.id"
                  />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem v-if="memberDialogMode === 'single'" label="用户">
            <ElSelect v-model="memberForm.userId" filterable>
              <ElOption
                v-for="user in batchMemberCandidateUsers"
                :key="user.id"
                :label="`${user.name} / ${user.orgName}`"
                :value="user.id"
              />
            </ElSelect>
          </ElFormItem>
          <ElFormItem v-else label="批量用户">
            <ElSelect
              v-model="memberBatchUserIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择要授权到项目的用户"
            >
              <ElOption
                v-for="user in batchMemberCandidateUsers"
                :key="user.id"
                :label="`${user.name} / ${user.orgName}`"
                :value="user.id"
              >
                <span>{{ user.name }} / {{ user.orgName }}</span>
                <ElTag
                  v-if="selectedProjectMemberUserIds.has(user.id)"
                  class="member-option-tag"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  将更新
                </ElTag>
              </ElOption>
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="到期时间">
            <ElInput v-model="memberForm.expiresAt" placeholder="例如 2026-12-31 18:00:00" />
          </ElFormItem>
        </ElForm>
        <template #footer>
          <ElButton @click="memberDialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="memberSaving" @click="handleSaveMember">保存</ElButton>
        </template>
      </ElDialog>
    </StaticPageShell>
  </div>
</template>

<style scoped>
.admin-page {
  min-height: 100vh;
  padding: 0;
  color: #1f2937;
  background: var(--aicheck-bg, #eef3f8);
}

.page-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.page-toolbar :deep(.el-button),
.admin-page :deep(.el-input__wrapper),
.admin-page :deep(.el-select__wrapper) {
  min-height: 44px;
}

.page-title {
  margin: 0;
  font-size: 27px;
  font-weight: 600;
  line-height: 1.2;
  color: #172033;
}

.page-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #667085;
}

.publish-result-panel {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  margin-bottom: 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
}

.publish-result-panel strong {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
  color: #1d4ed8;
}

.publish-result-panel span {
  font-size: 12px;
  color: #475569;
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
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 8px;
  box-shadow: var(--aicheck-shadow-sm, 0 6px 16px rgb(15 23 42 / 6%));
}

.secondary-summary-collapse summary {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 600;
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
  font-weight: 600;
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
  font-weight: 600;
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
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 8px;
  box-shadow: var(--aicheck-shadow-xs, 0 1px 2px rgb(20 34 56 / 5%));
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
  background: var(--aicheck-surface-soft, #f8fbff);
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
  background: var(--aicheck-surface-muted, #f2f6fb);
  border-color: #d7dde8;
}

.panel {
  margin-bottom: 16px;
  border-radius: 8px;
}

.admin-page--expanded :deep(.el-tabs__content) {
  min-height: 980px;
}

.admin-stack-row {
  row-gap: 16px;
}

.admin-stack-col .panel {
  margin-bottom: 0;
}

.panel-header {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.admin-tabs {
  margin-top: 2px;
}

:deep(.admin-tabs > .el-tabs__header) {
  display: none;
}

.error-stack {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
}

.local-error {
  display: grid;
  padding: 10px;
  background: #fff7f7;
  border: 1px solid #fecaca;
  border-radius: 8px;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
}

.local-error--compact {
  margin-bottom: 12px;
}

.local-error :deep(.el-alert) {
  padding: 0;
  background: transparent;
}

.local-error :deep(.el-alert__title) {
  line-height: 20px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.export-task-card {
  display: flex;
  padding: 12px;
  margin-top: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.export-task-card strong {
  display: block;
  line-height: 20px;
}

.export-task-card span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #667085;
}

.publish-trace-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.publish-impact-table {
  margin-top: 12px;
}

.drawer-content {
  min-height: 360px;
}

.drawer-action-row {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.stacked-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.stacked-cell small {
  font-size: 12px;
  line-height: 1.2;
  color: var(--el-text-color-secondary);
}

.member-form :deep(.el-select),
.member-form :deep(.el-input),
.wizard-form :deep(.el-select),
.wizard-form :deep(.el-input),
.wizard-form :deep(.el-input-number),
.config-edit-form :deep(.el-select),
.config-edit-form :deep(.el-input),
.config-edit-form :deep(.el-input-number),
.prompt-template-form :deep(.el-select),
.prompt-template-form :deep(.el-input),
.project-filter-bar :deep(.el-input),
.project-filter-bar :deep(.el-select),
.integration-filter-bar :deep(.el-select) {
  width: 100%;
}

.wizard-form,
.config-edit-form,
.prompt-template-form {
  margin-top: 18px;
}

.wizard-member-table,
.diff-table {
  margin-top: 12px;
}

.rule-node-list,
.rule-diff-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.rule-description {
  padding: 12px;
  line-height: 22px;
  color: #344054;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.rule-diff-drawer :deep(.el-descriptions) {
  margin-bottom: 16px;
}

.rule-diff-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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

.integration-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.integration-summary-card,
.integration-module-card {
  min-height: 76px;
  padding: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.integration-summary-card {
  background: #f8fafc;
  border-color: #d7dde8;
}

.integration-summary-card--blue {
  background: #f8fbff;
  border-color: #cbdcf8;
}

.integration-summary-card--green {
  background: #f8fdf9;
  border-color: #cfe8d7;
}

.integration-summary-card--orange {
  background: #fffaf0;
  border-color: #f0dfb8;
}

.integration-summary-card--red {
  background: #fff7f7;
  border-color: #efc8c8;
}

.integration-summary-card span,
.integration-module-card span,
.integration-generated-at {
  display: block;
  font-size: 12px;
  color: #667085;
}

.integration-summary-card strong {
  display: block;
  margin-top: 6px;
  font-size: 24px;
  line-height: 28px;
  color: #1f2937;
}

.integration-filter-bar {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(160px, 220px) auto minmax(180px, 1fr);
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.integration-module-grid {
  margin-bottom: 14px;
}

.integration-module-card {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  min-height: 68px;
  margin-bottom: 12px;
}

.integration-module-card strong {
  display: block;
  margin-bottom: 5px;
  color: #1f2937;
}

.method-pill {
  display: inline-flex;
  height: 22px;
  min-width: 52px;
  padding: 0 8px;
  margin-right: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
  background: #eff6ff;
  border-radius: 6px;
  align-items: center;
  justify-content: center;
}

.diff-value {
  display: block;
  max-width: 100%;
  overflow: hidden;
  color: #344054;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-footer {
  position: sticky;
  bottom: 0;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  padding: 12px 0 4px;
  background: #fff;
}

.action-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  width: 100%;
}

.batch-result {
  display: flex;
  padding: 10px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
}

.batch-result-list {
  display: grid;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  flex-basis: 100%;
  gap: 4px;
}

.member-option-tag {
  float: right;
  margin-left: 8px;
}

.business-pack-option {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.business-pack-option span {
  font-weight: 600;
  line-height: 18px;
}

.business-pack-option small {
  overflow: hidden;
  font-size: 12px;
  line-height: 16px;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filter-bar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 140px 150px auto auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.audit-integrity-alert {
  margin-bottom: 12px;
}

.project-filter-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(140px, 180px) auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.mobile-project-list {
  display: none;
}

.mobile-project-card {
  padding: 14px;
  background: #fff;
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 12px;
  box-shadow: var(--aicheck-shadow-xs, 0 1px 2px rgb(20 34 56 / 5%));
}

.mobile-project-card header,
.mobile-project-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.mobile-project-card header > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.mobile-project-card header small {
  font-size: 12px;
  color: #596a80;
}

.mobile-project-card header strong {
  overflow: hidden;
  font-size: 15px;
  line-height: 1.4;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-project-card dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  padding: 12px 0;
  margin: 12px 0 8px;
  border-top: 1px solid #edf1f6;
  border-bottom: 1px solid #edf1f6;
}

.mobile-project-card dt,
.mobile-project-card dd {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.mobile-project-card dt {
  margin-bottom: 2px;
  color: #596a80;
}

.mobile-project-card dd {
  color: #26364e;
}

.prompt-template-filter-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(140px, 180px) auto auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

@media (width <= 768px) {
  .admin-page {
    padding: 0;
  }

  .page-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .audit-object-board,
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-bar {
    grid-template-columns: 1fr;
  }

  .prompt-template-filter-bar {
    grid-template-columns: 1fr;
  }

  .project-filter-bar {
    grid-template-columns: 1fr;
  }

  .desktop-project-table {
    display: none;
  }

  .mobile-project-list {
    display: grid;
    gap: 10px;
  }

  .integration-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .integration-filter-bar {
    grid-template-columns: 1fr;
  }

  .drawer-action-row,
  .export-task-card,
  .publish-trace-actions,
  .local-error,
  .drawer-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .local-error {
    grid-template-columns: 1fr;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }

  .action-checkbox-grid {
    grid-template-columns: 1fr;
  }

  .rule-diff-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 480px) {
  .audit-object-board,
  .metric-grid,
  .integration-summary-grid,
  .rule-diff-summary {
    grid-template-columns: 1fr;
  }
}
</style>
