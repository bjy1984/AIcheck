<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
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
  ElTag
} from 'element-plus'
import {
  authorizeProjectMemberApi,
  createAdminConfigExportApi,
  createAdminConfigItemApi,
  createAdminProjectApi,
  getAdminConfigOverviewApi,
  getAdminIntegrationContractApi,
  getAdminProjectDetailApi,
  getKnowledgeRuleVersionDiffApi,
  getAuditLogsApi,
  listWorkbenchProjectsApi,
  previewAdminConfigDiffApi,
  publishAdminConfigApi,
  saveAdminConfigItemApi,
  updateProjectMemberApi
} from '@/api/aicheck'
import type {
  AdminConfigChangePayload,
  AdminConfigDiffPayload,
  AdminConfigOverviewPayload,
  AdminPublishConfigPayload,
  AdminConfigTarget,
  AdminProjectCreatePayload,
  AdminProjectDetailPayload,
  AuditLogPayload,
  IntegrationContractField,
  IntegrationContractModule,
  IntegrationContractPayload,
  IntegrationContractStatus,
  KnowledgeRuleVersionDiffPayload,
  ProjectMember
} from '@/api/aicheck'
import type { ActionCode, ExportTask, Project, RoleCode } from '@/types/aicheck'
import { getAicheckErrorMessage } from '@/utils/aicheckError'
import AdminKnowledgeStaticDeepSections from './components/AdminKnowledgeStaticDeepSections.vue'
import StaticPageShell from './components/StaticPageShell.vue'

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
  fieldMappings: []
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

const adminShellMenuSectionsBase = [
  {
    title: '项目管理与基础配置',
    meta: '3页',
    items: [
      { index: '01', label: '项目列表', badge: '多项目', tone: 'blue', route: '/admin/projects' },
      {
        index: '02',
        label: '项目详情',
        badge: '基础信息',
        tone: 'green',
        route: '/admin/projects'
      },
      {
        index: '03',
        label: '项目立项向导',
        badge: '新建',
        tone: 'orange',
        route: '/admin/projects'
      }
    ]
  },
  {
    title: '用户中心与组织权限',
    meta: '3页',
    items: [
      { index: '04', label: '组织用户', badge: '68人', tone: 'blue', route: '/admin/org' },
      {
        index: '05',
        label: '角色权限配置',
        badge: '动作级',
        tone: 'blue',
        route: '/admin/permission'
      },
      {
        index: '06',
        label: '项目成员授权',
        badge: '按项目',
        tone: 'green',
        route: '/admin/permission'
      }
    ]
  },
  {
    title: '流程管理与待办任务',
    meta: '3页',
    items: [
      { index: '07', label: '流程状态机', badge: '状态', tone: 'blue', route: '/admin/rules' },
      {
        index: '08',
        label: '待办规则配置',
        badge: '规则',
        tone: 'orange',
        route: '/admin/fine-config'
      },
      { index: '09', label: '流程实例详情', badge: '流转', tone: 'green', route: '/admin/rules' }
    ]
  },
  {
    title: '规则、知识与审计配置',
    meta: '9页',
    items: [
      {
        index: '10',
        label: '项目审核节点维护',
        badge: '69项',
        tone: 'blue',
        route: '/admin/permission'
      },
      {
        index: '11',
        label: '节点与角色权限矩阵',
        badge: '动作级',
        tone: 'blue',
        route: '/admin/permission'
      },
      {
        index: '12',
        label: 'AI 业务审查规则模板',
        badge: '新增',
        tone: 'orange',
        route: '/admin/rules'
      },
      {
        index: '13',
        label: 'AI 知识库管理',
        badge: 'OCR/向量',
        tone: 'green',
        route: '/knowledge/overview'
      },
      {
        index: '14',
        label: '外部核验工具源配置',
        badge: '4源',
        tone: 'blue',
        route: '/admin/fine-config'
      },
      {
        index: '15',
        label: '证据字段映射配置',
        badge: '字段',
        tone: 'blue',
        route: '/admin/fine-config'
      },
      { index: '16', label: '角色单位人员维护', badge: '基础', tone: 'green', route: '/admin/org' },
      {
        index: '17',
        label: '联调清单',
        badge: '对账',
        tone: 'orange',
        route: '/admin/integration'
      },
      { index: '18', label: '操作日志', badge: '审计', tone: 'blue', route: '/admin/audit' }
    ]
  }
] as const

const adminShellBoundaryRows = [
  { label: '合同1', value: '项目列表、详情、立项向导' },
  { label: '合同2', value: '组织用户、角色权限、成员授权' },
  { label: '合同3', value: '流程状态机、待办规则、实例详情' },
  { label: '边界', value: '后台配置，不办理审查意见或报告确认' }
] as const

const adminShellRightCards = [
  {
    title: '基础信息',
    rows: [
      { label: '模板名称', value: 'Welder-Qualification-B' },
      { label: '适用节点', value: '24. 焊工资格证及持证合格项目' },
      { label: '审查对象', value: '人员证书' },
      { label: '当前版本', value: 'v2.1', valueBadge: '启用', valueTone: 'green' },
      { label: '输出格式', value: '审查对象、过程文件、核验步骤、证据、建议结论' }
    ]
  },
  {
    title: '字段映射',
    rows: [
      { label: '证书编号', value: '焊工资格证第 1 页 OCR 字段' },
      { label: '有效期', value: '资格证有效期字段' },
      { label: '作业范围', value: '资格证持证项目页' },
      { label: '项目要求', value: '焊接工艺卡字段' },
      { label: '外部结果', value: '资格网站查询截图字段' }
    ]
  },
  {
    title: '版本记录',
    timeline: [
      {
        title: 'v2.1 当前使用',
        description: '新增外部查询截图字段。',
        tone: 'blue'
      },
      {
        title: 'v2.0',
        description: '拆分真实性和有效期核验。',
        tone: 'blue'
      },
      {
        title: 'v1.8',
        description: '增加跨文件一致性核验。',
        tone: 'orange'
      }
    ]
  },
  {
    title: '后台限制',
    note: '后台只维护规则模板、工具源、字段映射和权限；不显示 AI 建议采纳、审查意见、退回补正、报告生成/复核或报告确认按钮。'
  }
] as const

type PermissionConfigRow = AdminConfigOverviewPayload['permissionMatrix'][number]
type NodeTemplateConfigRow = AdminConfigOverviewPayload['nodeTemplates'][number]
type WorkflowConfigRow = AdminConfigOverviewPayload['workflowStateMachines'][number]
type RuleVersionConfigRow = AdminConfigOverviewPayload['ruleVersions'][number]
type TodoRuleConfigRow = AdminConfigOverviewPayload['todoRules'][number]
type MessageTemplateConfigRow = AdminConfigOverviewPayload['messageTemplates'][number]
type ToolSourceConfigRow = AdminConfigOverviewPayload['toolSources'][number]
type FieldMappingConfigRow = AdminConfigOverviewPayload['fieldMappings'][number]
type ProjectWizardMemberRole = Extract<RoleCode, 'inspection' | 'contractor' | 'ndt' | 'owner'>
type PaginationState = {
  page: number
  pageSize: number
  total: number
}

const createPagination = (pageSize = 10): PaginationState => ({
  page: 1,
  pageSize,
  total: 0
})

const loading = ref(false)
const auditLoading = ref(false)
const configExporting = ref(false)
const configPublishing = ref(false)

const adminTabRouteMap = {
  org: '/admin/org',
  permission: '/admin/permission',
  rule: '/admin/rules',
  'fine-config': '/admin/fine-config',
  integration: '/admin/integration',
  audit: '/admin/audit'
} as const

type AdminTabKey = keyof typeof adminTabRouteMap

const adminRouteTabMap: Record<string, AdminTabKey> = {
  '/admin/overview': 'org',
  '/admin/projects': 'org',
  '/admin/org': 'org',
  '/admin/permission': 'permission',
  '/admin/rules': 'rule',
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
const auditPagination = reactive(createPagination(10))
const overviewError = ref('')
const adminActionError = ref('')
const integrationLoading = ref(false)
const integrationError = ref('')
const integrationModuleFilter = ref<IntegrationContractModule | 'all'>('all')
const integrationStatusFilter = ref<IntegrationContractStatus | 'all'>('all')
const adminActionRetry = ref<'export' | 'publish' | null>(null)
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
const configDrawerVisible = ref(false)
const configDiffVisible = ref(false)
const configSaving = ref(false)
const configPreviewing = ref(false)
const configOperationError = ref('')

const adminMenuActiveRoute = computed(() =>
  route.path === '/admin/overview' ? '/admin/projects' : route.path
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

watch(
  () => route.path,
  (path) => {
    if (!path.startsWith('/admin')) return
    const nextTab = getAdminTabFromRoute(path)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
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

const auditFilters = reactive({
  keyword: '',
  result: '',
  objectType: ''
})

const projectWizardRoles: ProjectWizardMemberRole[] = ['inspection', 'contractor', 'ndt', 'owner']

const projectWizardForm = reactive({
  code: '',
  name: '',
  type: '工业管道新建',
  region: '华东',
  ownerOrgName: '华东管网建设公司',
  contractorOrgName: '中石化安装有限公司',
  ndtOrgName: '华测检测有限公司',
  inspectionOrgName: '省特检院一部',
  currentNodeId: 1,
  memberUserIds: {
    inspection: 'USR-INS-001',
    contractor: 'USR-CON-001',
    ndt: 'USR-NDT-001',
    owner: 'USR-OWN-001'
  } as Record<ProjectWizardMemberRole, string>
})

const memberForm = reactive({
  userId: '',
  role: 'inspection' as RoleCode,
  nodeScopeText: '16,24,40',
  actions: [] as ActionCode[],
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
  reason: '按当前业务配置调整。'
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
    'submission:withdraw',
    'rectification:submit'
  ],
  ndt: [
    'project:view',
    'file:upload',
    'file:bind',
    'submission:draft',
    'submission:submit',
    'submission:withdraw',
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

const roleLabel = (role: RoleCode) => {
  const labels: Record<RoleCode, string> = {
    inspection: '监检',
    contractor: '施工',
    ndt: '无损检测',
    owner: '建设方',
    admin: '管理'
  }
  return labels[role]
}

const projectStats = computed(() => {
  if (overview.value.metrics.length) return overview.value.metrics
  const active = projects.value.filter((project) => project.status !== '已归档').length
  const correction = projects.value.filter((project) => project.status.includes('补正')).length
  const todos = projects.value.reduce((sum, project) => sum + project.todoCount, 0)
  return [
    { key: 'project', label: '项目总数', value: projects.value.length, tone: 'blue' as const },
    { key: 'active', label: '在检项目', value: active, tone: 'green' as const },
    { key: 'correction', label: '补正项目', value: correction, tone: 'red' as const },
    { key: 'todo', label: '全局待办', value: todos, tone: 'orange' as const }
  ]
})

const configSummary = computed(() => [
  {
    label: '组织用户',
    value: `${overview.value.orgUnits.length} 个组织 / ${overview.value.users.length} 个用户`
  },
  { label: '权限模型', value: `${overview.value.permissionMatrix.length} 类角色矩阵` },
  { label: '节点模板', value: `${overview.value.nodeTemplates.length} 组模板 / 69 个节点` },
  { label: '规则版本', value: `${overview.value.ruleVersions.length} 个规则包` },
  { label: '状态机', value: `${overview.value.workflowStateMachines.length} 个流程版本` },
  {
    label: '细项配置',
    value: `${overview.value.todoRules.length + overview.value.messageTemplates.length + overview.value.toolSources.length + overview.value.fieldMappings.length} 项`
  }
])

const pendingRuleCount = computed(
  () => overview.value.ruleVersions.filter((item) => item.status === '待发布').length
)

const currentRoleActions = computed(() => roleActionOptions[memberForm.role] || [])

const selectedProjectMembers = computed(() => projectDetail.value?.members || [])

const memberDialogTitle = computed(() =>
  memberDialogMode.value === 'batch' ? '批量项目成员授权' : '项目成员授权'
)

const selectedProjectMemberUserIds = computed(
  () => new Set(selectedProjectMembers.value.map((member) => member.userId))
)

const batchMemberCandidateUsers = computed(() => {
  const matched = overview.value.users.filter((user) => user.role === memberForm.role)
  return matched.length ? matched : overview.value.users
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

const wizardUsersByRole = (role: RoleCode) =>
  overview.value.users.filter((user) => user.role === role || !overview.value.users.length)

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

const parseNodeScope = () =>
  memberForm.nodeScopeText
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0 && item <= 69)

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
    auditLogs.value = applyPagination(auditPagination, res.data)
  } catch (error) {
    auditError.value = getRequestErrorMessage(error, '审计日志加载失败，筛选条件已保留。')
  } finally {
    auditLoading.value = false
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
    const [projectRes, configRes] = await Promise.all([
      listWorkbenchProjectsApi('admin'),
      getAdminConfigOverviewApi()
    ])
    if (projectRes) projects.value = projectRes.data
    if (configRes) overview.value = configRes.data
    if (!projectRes || !configRes) {
      overviewError.value = getRequestErrorMessage(
        undefined,
        '管理后台基础数据加载失败，已保留上一次可用数据。'
      )
      return
    }
    await Promise.all([loadAuditLogs(), loadIntegrationContract()])
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
  loadIntegrationContract()
}

const getDefaultWizardUserId = (role: ProjectWizardMemberRole) =>
  overview.value.users.find((user) => user.role === role)?.id ||
  projectWizardForm.memberUserIds[role]

const resetProjectWizardForm = () => {
  projectWizardForm.code = `P-2026-MOCK-${String(projects.value.length + 1).padStart(3, '0')}`
  projectWizardForm.name = ''
  projectWizardForm.type = '工业管道新建'
  projectWizardForm.region = '华东'
  projectWizardForm.ownerOrgName = '华东管网建设公司'
  projectWizardForm.contractorOrgName = '中石化安装有限公司'
  projectWizardForm.ndtOrgName = '华测检测有限公司'
  projectWizardForm.inspectionOrgName = '省特检院一部'
  projectWizardForm.currentNodeId = 1
  projectWizardRoles.forEach((role) => {
    projectWizardForm.memberUserIds[role] = getDefaultWizardUserId(role)
  })
}

const openProjectWizard = () => {
  resetProjectWizardForm()
  projectWizardStep.value = 0
  projectWizardError.value = ''
  projectWizardVisible.value = true
}

const validateProjectWizardStep = () => {
  if (projectWizardStep.value === 0) {
    if (!projectWizardForm.name.trim()) {
      ElMessage.warning('请填写项目名称')
      return false
    }
    if (!projectWizardForm.type.trim() || !projectWizardForm.region.trim()) {
      ElMessage.warning('请填写项目类型和区域')
      return false
    }
  }
  if (projectWizardStep.value === 1) {
    const orgNames = [
      projectWizardForm.ownerOrgName,
      projectWizardForm.contractorOrgName,
      projectWizardForm.ndtOrgName,
      projectWizardForm.inspectionOrgName
    ]
    if (orgNames.some((name) => !name.trim())) {
      ElMessage.warning('请补齐参建单位')
      return false
    }
  }
  if (projectWizardStep.value === 2) {
    if (projectWizardRoles.some((role) => !projectWizardForm.memberUserIds[role])) {
      ElMessage.warning('请为四类角色选择初始成员')
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
    name: projectWizardForm.name,
    type: projectWizardForm.type,
    region: projectWizardForm.region,
    ownerOrgName: projectWizardForm.ownerOrgName,
    contractorOrgName: projectWizardForm.contractorOrgName,
    ndtOrgName: projectWizardForm.ndtOrgName,
    inspectionOrgName: projectWizardForm.inspectionOrgName,
    currentNodeId: projectWizardForm.currentNodeId,
    memberUserIds: { ...projectWizardForm.memberUserIds }
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
    projectDetail.value = res.data.detail
    await Promise.all([loadData(), loadAuditLogs()])
  } catch (error) {
    projectWizardError.value = getRequestErrorMessage(
      error,
      buildOperationFailureMessage('项目立项')
    )
  } finally {
    projectCreating.value = false
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
  configPublishing.value = true
  adminActionError.value = ''
  adminActionRetry.value = null
  try {
    const res = await publishAdminConfigApi(
      {
        scope: 'all',
        reason: '发布管理后台配置快照。'
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
        '规则版本差异加载失败，已保留规则版本列表。'
      )
      return
    }
    adminRuleDiff.value = res.data
  } catch (error) {
    adminRuleDiffError.value = getRequestErrorMessage(
      error,
      '规则版本差异加载失败，已保留规则版本列表。'
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
  overview.value.users.find((user) => user.role === role) || overview.value.users[0]

const getDefaultBatchMemberUserIds = () => {
  const users = batchMemberCandidateUsers.value
  const notAuthorized = users
    .filter((user) => !selectedProjectMemberUserIds.value.has(user.id))
    .map((user) => user.id)
  return (notAuthorized.length ? notAuthorized : users.map((user) => user.id)).slice(0, 4)
}

const resetMemberForm = (role: RoleCode = 'inspection') => {
  memberForm.role = role
  memberForm.nodeScopeText = '16,24,40'
  memberForm.actions = [...roleActionOptions[role]]
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
  memberForm.actions = [...roleActionOptions[memberForm.role]]
  if (memberDialogMode.value === 'single') {
    memberForm.userId = getDefaultMemberUser(memberForm.role)?.id || ''
    return
  }
  memberBatchUserIds.value = getDefaultBatchMemberUserIds()
}

const handleSaveMember = async () => {
  if (!projectDetail.value) return
  const nodeScope = parseNodeScope()
  if (memberDialogMode.value === 'single' && !memberForm.userId) {
    ElMessage.warning('请选择授权用户')
    return
  }
  if (memberDialogMode.value === 'batch' && !memberBatchUserIds.value.length) {
    ElMessage.warning('请选择批量授权用户')
    return
  }
  if (!nodeScope.length) {
    ElMessage.warning('请输入有效节点范围')
    return
  }
  if (!memberForm.actions.length) {
    ElMessage.warning('请选择动作权限')
    return
  }
  memberSaving.value = true
  memberOperationError.value = ''
  memberBatchResult.value = null
  try {
    if (memberDialogMode.value === 'batch') {
      const failed: Array<{ userId: string; name: string; message: string }> = []
      let successCount = 0
      for (const userId of memberBatchUserIds.value) {
        const user = overview.value.users.find((item) => item.id === userId)
        try {
          const res = await authorizeProjectMemberApi(projectDetail.value.project.id, {
            userId,
            role: memberForm.role,
            nodeScope,
            actions: memberForm.actions,
            expiresAt: memberForm.expiresAt || undefined
          })
          if (!res) {
            failed.push({
              userId,
              name: user?.name || userId,
              message: getRequestErrorMessage(
                undefined,
                buildOperationFailureMessage('项目成员批量授权')
              )
            })
            continue
          }
          successCount += 1
        } catch (error) {
          failed.push({
            userId,
            name: user?.name || userId,
            message: getRequestErrorMessage(error, buildOperationFailureMessage('项目成员批量授权'))
          })
        }
      }
      if (successCount) {
        ElMessage.success(
          `批量授权完成：${successCount} 人成功${failed.length ? `，${failed.length} 人失败` : ''}`
        )
        await Promise.all([loadProjectDetail(projectDetail.value.project.id), loadAuditLogs()])
      }
      if (failed.length) {
        memberBatchResult.value = { successCount, failed }
        memberOperationError.value = getRequestErrorMessage(
          undefined,
          buildOperationFailureMessage('项目成员批量授权')
        )
        return
      }
      memberDialogVisible.value = false
      return
    }

    const res = await authorizeProjectMemberApi(projectDetail.value.project.id, {
      userId: memberForm.userId,
      role: memberForm.role,
      nodeScope,
      actions: memberForm.actions,
      expiresAt: memberForm.expiresAt || undefined
    })
    if (!res) {
      memberOperationError.value = getRequestErrorMessage(
        undefined,
        buildOperationFailureMessage('项目成员授权保存')
      )
      return
    }
    ElMessage.success('项目成员授权已保存')
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
  <div class="admin-page" v-loading="loading">
    <StaticPageShell
      brand-mark="管"
      title="监督检验协作系统后台"
      status="基础配置"
      status-tone="blue"
      search-placeholder="⌕ 搜索（项目 / 单位 / 用户 / 角色 / 流程 / 待办 / 节点）"
      user-label="系统管理员 周工"
      :top-stats="[
        { label: '配置待办', value: pendingRuleCount || 3, tone: 'orange' },
        { label: '审计', value: auditPagination.total || 9, tone: 'red' }
      ]"
      menu-title="后台菜单"
      menu-root="合同功能管理"
      :menu-sections="adminShellMenuSections"
      boundary-title="后台边界"
      boundary-badge="无业务办理"
      boundary-tone="green"
      :boundary-rows="adminShellBoundaryRows"
      right-title="模板详情"
      right-subtitle="Welder-Qualification-B v2.1"
      :right-cards="adminShellRightCards"
    >
      <div class="page-toolbar">
        <div>
          <div class="page-title">项目与权限配置</div>
          <div class="page-subtitle">组织用户、权限矩阵、节点模板、规则版本、审计日志</div>
        </div>
        <ElSpace wrap>
          <ElButton type="primary" plain @click="openProjectWizard">新建项目</ElButton>
          <ElButton :loading="configExporting" @click="handleExportConfig">导出配置包</ElButton>
          <ElButton type="primary" :loading="configPublishing" @click="handlePublishConfig">
            发布配置
          </ElButton>
        </ElSpace>
      </div>

      <div v-if="overviewError || adminActionError" class="error-stack">
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
      </div>

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

      <AdminKnowledgeStaticDeepSections
        mode="admin"
        :projects="projects"
        :admin-overview="overview"
        :admin-stats="projectStats"
      />

      <ElRow :gutter="16">
        <ElCol :xl="15" :lg="15" :md="24" :sm="24" :xs="24">
          <ElCard shadow="never" class="panel">
            <template #header>
              <div class="panel-header">
                <span>项目清单</span>
                <ElTag type="info" effect="plain">{{ projects.length }} 个</ElTag>
              </div>
            </template>
            <ElTable :data="projects" border height="360">
              <ElTableColumn prop="code" label="项目编号" width="150" />
              <ElTableColumn prop="name" label="项目名称" min-width="220" show-overflow-tooltip />
              <ElTableColumn prop="region" label="区域" width="100" />
              <ElTableColumn
                prop="contractorOrgName"
                label="施工单位"
                min-width="150"
                show-overflow-tooltip
              />
              <ElTableColumn
                prop="inspectionOrgName"
                label="监检机构"
                min-width="150"
                show-overflow-tooltip
              />
              <ElTableColumn label="状态" width="130">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="todoCount" label="待办" width="76" />
              <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
              <ElTableColumn label="操作" width="92" fixed="right">
                <template #default="{ row }">
                  <ElButton link type="primary" @click="handleOpenProjectDetail(row)"
                    >详情</ElButton
                  >
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </ElCol>

        <ElCol :xl="9" :lg="9" :md="24" :sm="24" :xs="24">
          <ElCard shadow="never" class="panel config-panel">
            <template #header>
              <div class="panel-header">
                <span>系统配置摘要</span>
                <ElTag :type="pendingRuleCount ? 'warning' : 'success'" effect="plain">
                  {{ pendingRuleCount ? `${pendingRuleCount} 待发布` : '已同步' }}
                </ElTag>
              </div>
            </template>
            <ElDescriptions :column="1" border>
              <ElDescriptionsItem
                v-for="config in configSummary"
                :key="config.label"
                :label="config.label"
              >
                {{ config.value }}
              </ElDescriptionsItem>
            </ElDescriptions>
            <div v-if="selectedExportTask" class="export-task-card">
              <div>
                <strong>{{ selectedExportTask.fileName }}</strong>
                <span>{{ selectedExportTask.id }} · {{ selectedExportTask.status }}</span>
              </div>
              <ElTag :type="statusType(selectedExportTask.status)" effect="light">
                {{ selectedExportTask.progress }}%
              </ElTag>
            </div>
            <div v-if="latestConfigDiff" class="export-task-card">
              <div>
                <strong>{{ latestConfigDiff.objectName }}</strong>
                <span>{{ latestConfigDiff.objectId }} · {{ latestConfigDiff.previewedAt }}</span>
              </div>
              <ElButton link type="primary" @click="configDiffVisible = true"> 查看差异 </ElButton>
            </div>
            <div v-if="latestPublishResult" class="export-task-card publish-trace-card">
              <div>
                <strong>最近发布：{{ latestPublishResult.version }}</strong>
                <span>
                  影响 {{ latestPublishResult.impactSummary.totalAffected }} 项 ·
                  {{ latestPublishResult.impactSummary.linkedProjects }} 个在检项目 · 推送
                  {{ latestPublishResult.impactSummary.pushedMessages }} 条消息
                </span>
              </div>
              <div class="publish-trace-actions">
                <ElTag
                  :type="latestPublishResult.impactSummary.warningCount ? 'warning' : 'success'"
                  effect="plain"
                >
                  {{
                    latestPublishResult.impactSummary.warningCount
                      ? `${latestPublishResult.impactSummary.warningCount} 需复核`
                      : '已同步'
                  }}
                </ElTag>
                <ElButton link type="primary" @click="publishTraceVisible = true">
                  查看联动
                </ElButton>
              </div>
            </div>
          </ElCard>
        </ElCol>
      </ElRow>

      <ElTabs v-model="activeTab" class="admin-tabs">
        <ElTabPane label="组织用户" name="org">
          <ElRow :gutter="16">
            <ElCol :xl="11" :lg="11" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>组织单位</span>
                    <ElTag type="info" effect="plain">{{ overview.orgUnits.length }} 个</ElTag>
                  </div>
                </template>
                <ElTable :data="overview.orgUnits" border height="320">
                  <ElTableColumn
                    prop="name"
                    label="组织名称"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="type" label="类型" width="96" />
                  <ElTableColumn prop="contactName" label="联系人" width="92" />
                  <ElTableColumn prop="projectCount" label="项目" width="72" />
                  <ElTableColumn label="状态" width="88">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>

            <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>用户与角色</span>
                    <ElTag type="info" effect="plain">{{ overview.users.length }} 人</ElTag>
                  </div>
                </template>
                <ElTable :data="overview.users" border height="320">
                  <ElTableColumn prop="name" label="姓名" width="96" />
                  <ElTableColumn
                    prop="orgName"
                    label="所属组织"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="角色" width="100">
                    <template #default="{ row }">
                      <ElTag size="small" effect="plain">{{ roleLabel(row.role) }}</ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="mobile" label="手机号" width="130" />
                  <ElTableColumn label="状态" width="88">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="lastLoginAt" label="最近登录" width="170" />
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="权限与节点" name="permission">
          <ElRow :gutter="16">
            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>角色权限矩阵</span>
                    <ElTag type="info" effect="plain"
                      >{{ overview.permissionMatrix.length }} 类</ElTag
                    >
                  </div>
                </template>
                <ElTable :data="overview.permissionMatrix" border height="360">
                  <ElTableColumn prop="label" label="角色" width="100" />
                  <ElTableColumn
                    prop="projectScope"
                    label="项目范围"
                    min-width="130"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="nodeScope"
                    label="节点范围"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="动作权限" min-width="220">
                    <template #default="{ row }">
                      <div class="tag-list">
                        <ElTag
                          v-for="action in row.actions.slice(0, 5)"
                          :key="action"
                          size="small"
                          effect="plain"
                        >
                          {{ action }}
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
                  <ElTableColumn label="只读" width="76">
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
              </ElCard>
            </ElCol>

            <ElCol :xl="12" :lg="12" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>节点模板</span>
                    <ElTag type="info" effect="plain">{{ overview.nodeTemplates.length }} 组</ElTag>
                  </div>
                </template>
                <ElTable :data="overview.nodeTemplates" border height="360">
                  <ElTableColumn
                    prop="groupName"
                    label="业务分组"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="version" label="版本" width="130" />
                  <ElTableColumn prop="nodeCount" label="节点" width="70" />
                  <ElTableColumn prop="requiredCount" label="资料项" width="84" />
                  <ElTableColumn label="状态" width="96">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openNodeTemplateConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
              </ElCard>
            </ElCol>
          </ElRow>
        </ElTabPane>

        <ElTabPane label="规则与流程" name="rule">
          <ElRow :gutter="16">
            <ElCol :xl="13" :lg="13" :md="24" :sm="24" :xs="24">
              <ElCard shadow="never" class="panel">
                <template #header>
                  <div class="panel-header">
                    <span>规则版本</span>
                    <ElTag :type="pendingRuleCount ? 'warning' : 'success'" effect="plain">
                      {{ pendingRuleCount ? `${pendingRuleCount} 待发布` : '全部发布' }}
                    </ElTag>
                  </div>
                </template>
                <ElTable :data="overview.ruleVersions" border height="320">
                  <ElTableColumn
                    prop="name"
                    label="规则名称"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="version"
                    label="版本"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="promptVersion"
                    label="Prompt"
                    min-width="170"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="outputSchemaVersion"
                    label="输出结构"
                    min-width="130"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="节点" min-width="130">
                    <template #default="{ row }">{{ row.nodeIds.join('、') }}</template>
                  </ElTableColumn>
                  <ElTableColumn label="状态" width="96">
                    <template #default="{ row }">
                      <ElTag :type="statusType(row.status)" size="small" effect="plain">
                        {{ row.status }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
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
                <ElTable :data="overview.workflowStateMachines" border height="320">
                  <ElTableColumn prop="name" label="流程" min-width="170" show-overflow-tooltip />
                  <ElTableColumn prop="version" label="版本" width="140" />
                  <ElTableColumn prop="states" label="状态" width="70" />
                  <ElTableColumn prop="transitions" label="流转" width="70" />
                  <ElTableColumn label="状态" width="86">
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
              </ElCard>
            </ElCol>
          </ElRow>
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
                <ElTable :data="overview.todoRules" border height="300">
                  <ElTableColumn
                    prop="name"
                    label="规则名称"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="triggerStatus"
                    label="触发状态"
                    min-width="130"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="处理角色" width="110">
                    <template #default="{ row }">{{ roleLabel(row.assigneeRole) }}</template>
                  </ElTableColumn>
                  <ElTableColumn prop="deadlineHours" label="时限/h" width="82" />
                  <ElTableColumn label="状态" width="84">
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
                <ElTable :data="overview.messageTemplates" border height="300">
                  <ElTableColumn prop="scene" label="场景" min-width="150" show-overflow-tooltip />
                  <ElTableColumn prop="channel" label="渠道" width="86" />
                  <ElTableColumn
                    prop="titleTemplate"
                    label="标题模板"
                    min-width="210"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="状态" width="84">
                    <template #default="{ row }">
                      <ElTag :type="row.enabled ? 'success' : 'info'" size="small" effect="plain">
                        {{ row.enabled ? '启用' : '停用' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="updatedAt" label="更新时间" width="170" />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openMessageTemplateConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
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
                <ElTable :data="overview.toolSources" border height="300">
                  <ElTableColumn
                    prop="name"
                    label="工具名称"
                    min-width="160"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="toolType" label="类型" width="120" />
                  <ElTableColumn
                    prop="endpoint"
                    label="地址"
                    min-width="220"
                    show-overflow-tooltip
                  />
                  <ElTableColumn prop="authMode" label="鉴权" width="88" />
                  <ElTableColumn label="状态" width="84">
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
                <ElTable :data="overview.fieldMappings" border height="300">
                  <ElTableColumn prop="nodeId" label="节点" width="72" />
                  <ElTableColumn
                    prop="fieldName"
                    label="字段"
                    min-width="140"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="sourceField"
                    label="来源字段"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn
                    prop="targetField"
                    label="目标字段"
                    min-width="150"
                    show-overflow-tooltip
                  />
                  <ElTableColumn label="必填" width="76">
                    <template #default="{ row }">
                      <ElTag :type="row.required ? 'warning' : 'info'" size="small" effect="plain">
                        {{ row.required ? '是' : '否' }}
                      </ElTag>
                    </template>
                  </ElTableColumn>
                  <ElTableColumn prop="confidenceThreshold" label="阈值" width="76" />
                  <ElTableColumn label="操作" width="84" fixed="right">
                    <template #default="{ row }">
                      <ElButton link type="primary" @click="openFieldMappingConfig(row)"
                        >编辑</ElButton
                      >
                    </template>
                  </ElTableColumn>
                </ElTable>
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
              :data="integrationRows"
              border
              height="430"
              class="integration-contract-table"
              empty-text="当前筛选下没有字段差异"
            >
              <ElTableColumn prop="moduleLabel" label="模块" width="130" />
              <ElTableColumn label="接口" min-width="260" show-overflow-tooltip>
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
              />
              <ElTableColumn
                prop="backendField"
                label="后端字段"
                min-width="180"
                show-overflow-tooltip
              >
                <template #default="{ row }">{{ row.backendField || '-' }}</template>
              </ElTableColumn>
              <ElTableColumn label="必填" width="74">
                <template #default="{ row }">
                  <ElTag :type="row.required ? 'warning' : 'info'" size="small" effect="plain">
                    {{ row.required ? '是' : '否' }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="状态" width="118">
                <template #default="{ row }">
                  <ElTag :type="integrationStatusTagType(row.status)" size="small" effect="plain">
                    {{ row.status }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="级别" width="88">
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
              <ElTableColumn prop="owner" label="负责人" width="116" />
              <ElTableColumn prop="note" label="说明" min-width="260" show-overflow-tooltip />
            </ElTable>
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
            <ElTable :data="auditLogs" border height="360" v-loading="auditLoading">
              <ElTableColumn prop="actorName" label="操作人" width="110" />
              <ElTableColumn prop="action" label="动作" min-width="180" show-overflow-tooltip />
              <ElTableColumn prop="objectType" label="对象类型" width="130" />
              <ElTableColumn
                prop="objectId"
                label="对象 ID"
                min-width="160"
                show-overflow-tooltip
              />
              <ElTableColumn label="结果" width="88">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.result)" size="small" effect="plain">
                    {{ row.result }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn prop="createdAt" label="时间" width="170" />
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
                <ElFormItem label="项目类型">
                  <ElInput v-model="projectWizardForm.type" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="区域">
                  <ElInput v-model="projectWizardForm.region" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElFormItem label="起始节点">
              <ElInputNumber v-model="projectWizardForm.currentNodeId" :min="1" :max="69" />
            </ElFormItem>
          </div>

          <div v-show="projectWizardStep === 1">
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="建设单位">
                  <ElInput v-model="projectWizardForm.ownerOrgName" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="施工单位">
                  <ElInput v-model="projectWizardForm.contractorOrgName" />
                </ElFormItem>
              </ElCol>
            </ElRow>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="无损检测单位">
                  <ElInput v-model="projectWizardForm.ndtOrgName" />
                </ElFormItem>
              </ElCol>
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="监检机构">
                  <ElInput v-model="projectWizardForm.inspectionOrgName" />
                </ElFormItem>
              </ElCol>
            </ElRow>
          </div>

          <div v-show="projectWizardStep === 2">
            <ElAlert
              type="info"
              show-icon
              :closable="false"
              title="立项后将生成 69 个监督检验节点，并按四类角色写入初始项目成员授权。"
            />
            <ElTable :data="projectWizardRoles" border class="wizard-member-table">
              <ElTableColumn label="角色" width="120">
                <template #default="{ row }">{{ roleLabel(row) }}</template>
              </ElTableColumn>
              <ElTableColumn label="初始成员" min-width="260">
                <template #default="{ row }">
                  <ElSelect v-model="projectWizardForm.memberUserIds[row]" filterable>
                    <ElOption
                      v-for="user in wizardUsersByRole(row)"
                      :key="user.id"
                      :label="`${user.name} / ${user.orgName}`"
                      :value="user.id"
                    />
                  </ElSelect>
                </template>
              </ElTableColumn>
              <ElTableColumn label="节点范围" min-width="180">
                <template #default="{ row }">
                  {{ row === 'ndt' ? '35, 36, 40, 41, 42' : '1, 16, 24, 40, 68' }}
                </template>
              </ElTableColumn>
            </ElTable>
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
                <ElCheckbox v-for="action in allActionOptions" :key="action" :label="action">
                  {{ action }}
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
                  <ElInputNumber v-model="configForm.nodeCount" :min="0" :max="69" />
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

          <template v-else>
            <ElRow :gutter="12">
              <ElCol :xs="24" :sm="12">
                <ElFormItem label="节点编号">
                  <ElInputNumber v-model="configForm.fieldNodeId" :min="1" :max="69" />
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
          <ElTable :data="configDiffRows" border class="diff-table">
            <ElTableColumn prop="label" label="字段" width="120" />
            <ElTableColumn label="变更前" min-width="210" show-overflow-tooltip>
              <template #default="{ row }">{{ formatConfigValue(row.before) }}</template>
            </ElTableColumn>
            <ElTableColumn label="变更后" min-width="210" show-overflow-tooltip>
              <template #default="{ row }">{{ formatConfigValue(row.after) }}</template>
            </ElTableColumn>
            <ElTableColumn label="等级" width="90">
              <template #default="{ row }">
                <ElTag :type="row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                  {{ row.severity === 'warning' ? '需复核' : '信息' }}
                </ElTag>
              </template>
            </ElTableColumn>
          </ElTable>
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
          <ElTable :data="publishImpactRows" border class="publish-impact-table">
            <ElTableColumn prop="label" label="配置域" width="118" />
            <ElTableColumn prop="affectedCount" label="影响项" width="86" />
            <ElTableColumn label="状态" width="96">
              <template #default="{ row }">
                <ElTag :type="row.status === '需复核' ? 'warning' : 'success'" effect="plain">
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="trace" label="联动追溯" min-width="320" show-overflow-tooltip />
          </ElTable>
        </template>
      </ElDialog>

      <ElDrawer
        v-model="ruleDetailDrawerVisible"
        title="规则与 Prompt 版本详情"
        size="min(720px, 94vw)"
      >
        <div class="drawer-content">
          <ElEmpty v-if="!selectedRuleVersion" description="暂无规则版本详情" />
          <template v-else>
            <ElDescriptions :column="2" border>
              <ElDescriptionsItem label="规则名称">{{
                selectedRuleVersion.name
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="规则 Key">{{
                selectedRuleVersion.ruleKey
              }}</ElDescriptionsItem>
              <ElDescriptionsItem label="规则版本">{{
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

      <ElDrawer v-model="adminRuleDiffVisible" title="规则版本差异" size="min(760px, 94vw)">
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
              :data="adminRuleDiffRows"
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
                  <span class="diff-value">{{ formatRuleDiffValue(row.before) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="当前值" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span class="diff-value">{{ formatRuleDiffValue(row.after) }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="关注" width="90">
                <template #default="{ row }">
                  <ElTag :type="row.severity === 'warning' ? 'warning' : 'info'" effect="plain">
                    {{ row.severity === 'warning' ? '需复核' : '信息' }}
                  </ElTag>
                </template>
              </ElTableColumn>
            </ElTable>
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
                projectDetail.project.region
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
            <ElTable :data="projectDetail.participantUnits" border height="210">
              <ElTableColumn prop="unitName" label="单位" min-width="220" show-overflow-tooltip />
              <ElTableColumn prop="unitType" label="类型" width="110" />
              <ElTableColumn prop="contactName" label="联系人" width="100" />
              <ElTableColumn prop="contactPhone" label="电话" width="140" />
            </ElTable>

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
            <ElTable :data="selectedProjectMembers" border height="280">
              <ElTableColumn prop="name" label="姓名" width="96" />
              <ElTableColumn prop="orgName" label="组织" min-width="190" show-overflow-tooltip />
              <ElTableColumn label="角色" width="100">
                <template #default="{ row }">
                  <ElTag effect="plain">{{ roleLabel(row.role) }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="节点范围" min-width="160">
                <template #default="{ row }">{{ row.nodeScope.join(', ') }}</template>
              </ElTableColumn>
              <ElTableColumn label="动作" min-width="220">
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
              <ElTableColumn label="状态" width="96">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" size="small" effect="plain">
                    {{ row.status }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="92" fixed="right">
                <template #default="{ row }">
                  <ElButton
                    link
                    :type="row.status === '启用' ? 'danger' : 'success'"
                    :loading="memberSaving"
                    @click="handleToggleMemberStatus(row)"
                  >
                    {{ row.status === '启用' ? '停用' : '启用' }}
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>

            <ElDivider content-position="left">节点概况</ElDivider>
            <ElTable :data="projectDetail.nodeSummary" border height="260">
              <ElTableColumn
                prop="groupName"
                label="业务分组"
                min-width="190"
                show-overflow-tooltip
              />
              <ElTableColumn prop="total" label="节点" width="76" />
              <ElTableColumn prop="passed" label="已通过" width="86" />
              <ElTableColumn prop="correction" label="补正" width="76" />
              <ElTableColumn prop="pending" label="待处理" width="86" />
            </ElTable>

            <ElDivider content-position="left">近期导出</ElDivider>
            <ElTable :data="projectDetail.recentExportTasks" border height="220">
              <ElTableColumn prop="id" label="任务号" min-width="170" show-overflow-tooltip />
              <ElTableColumn prop="fileName" label="文件" min-width="220" show-overflow-tooltip />
              <ElTableColumn label="状态" width="100">
                <template #default="{ row }">
                  <ElTag :type="statusType(row.status)" effect="light">{{ row.status }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="大小" width="100">
                <template #default="{ row }">{{ formatFileSize(row.fileSize) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="createdAt" label="创建时间" width="170" />
            </ElTable>
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
              <ElFormItem v-if="memberDialogMode === 'single'" label="用户">
                <ElSelect v-model="memberForm.userId" filterable>
                  <ElOption
                    v-for="user in overview.users"
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
                  placeholder="选择要写入相同授权的用户"
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
            </ElCol>
            <ElCol :xs="24" :sm="12">
              <ElFormItem label="角色">
                <ElSelect v-model="memberForm.role" @change="handleMemberRoleChange">
                  <ElOption label="监检" value="inspection" />
                  <ElOption label="施工" value="contractor" />
                  <ElOption label="无损检测" value="ndt" />
                  <ElOption label="建设方" value="owner" />
                  <ElOption label="管理" value="admin" />
                </ElSelect>
              </ElFormItem>
            </ElCol>
          </ElRow>
          <ElFormItem label="节点范围">
            <ElInput v-model="memberForm.nodeScopeText" placeholder="例如 16,24,40" />
          </ElFormItem>
          <ElFormItem label="到期时间">
            <ElInput v-model="memberForm.expiresAt" placeholder="例如 2026-12-31 18:00:00" />
          </ElFormItem>
          <ElFormItem label="动作权限">
            <ElCheckboxGroup v-model="memberForm.actions" class="action-checkbox-grid">
              <ElCheckbox v-for="action in currentRoleActions" :key="action" :label="action">
                {{ action }}
              </ElCheckbox>
            </ElCheckboxGroup>
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
  color: #172033;
  font-size: 27px;
  font-weight: 900;
  line-height: 1.2;
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

.metric-card {
  min-height: 78px;
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-left: 4px solid #64748b;
  border-radius: 8px;
  background: #ffffff;
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
  border-left-color: #2563eb;
}

.metric-card--green {
  border-left-color: #16a34a;
}

.metric-card--orange {
  border-left-color: #f59e0b;
}

.metric-card--red {
  border-left-color: #dc2626;
}

.metric-card--gray {
  border-left-color: #64748b;
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

.admin-tabs {
  margin-top: 2px;
}

.error-stack {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
}

.local-error {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 10px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fff7f7;
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
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
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

.member-form :deep(.el-select),
.member-form :deep(.el-input),
.wizard-form :deep(.el-select),
.wizard-form :deep(.el-input),
.wizard-form :deep(.el-input-number),
.config-edit-form :deep(.el-select),
.config-edit-form :deep(.el-input),
.config-edit-form :deep(.el-input-number),
.integration-filter-bar :deep(.el-select) {
  width: 100%;
}

.wizard-form,
.config-edit-form {
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
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  color: #344054;
  line-height: 22px;
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
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
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
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}

.integration-summary-card {
  border-left: 4px solid #64748b;
}

.integration-summary-card--blue {
  border-left-color: #2563eb;
}

.integration-summary-card--green {
  border-left-color: #16a34a;
}

.integration-summary-card--orange {
  border-left-color: #f59e0b;
}

.integration-summary-card--red {
  border-left-color: #dc2626;
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
  align-items: center;
  justify-content: center;
  min-width: 52px;
  height: 22px;
  margin-right: 8px;
  padding: 0 8px;
  border-radius: 6px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
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
  background: #ffffff;
}

.action-checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 12px;
  width: 100%;
}

.batch-result {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
}

.batch-result-list {
  display: grid;
  flex-basis: 100%;
  gap: 4px;
  color: #667085;
  font-size: 12px;
  line-height: 18px;
}

.member-option-tag {
  float: right;
  margin-left: 8px;
}

.filter-bar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 140px 150px auto auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

@media (max-width: 768px) {
  .admin-page {
    padding: 0;
  }

  .page-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-bar {
    grid-template-columns: 1fr;
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

@media (max-width: 480px) {
  .metric-grid,
  .integration-summary-grid,
  .rule-diff-summary {
    grid-template-columns: 1fr;
  }
}
</style>
