import { SUCCESS_CODE } from '@/constants'
import type { MockMethod } from 'vite-plugin-mock'
import type {
  ActionCode,
  AiReviewRun,
  ArchiveItem,
  DocumentAsset,
  DocumentVersion,
  EvidenceLink,
  ExportTask,
  MessageItem,
  NdtFeedback,
  NdtFilm,
  NdtRecord,
  NdtReport,
  NodeFileBinding,
  NodeStatus,
  Project,
  ProjectStatus,
  ProjectTreeNode,
  ReportVersion,
  ReviewOpinion,
  RoleCode,
  SearchResult,
  TodoItem
} from '../../src/types/aicheck'
import {
  archiveItems,
  aiRuns,
  bindings,
  documents,
  evidenceLinks,
  extractedFields,
  messages,
  ndtFeedback,
  ndtFilms,
  ndtReports,
  nodeGroups,
  projectId,
  projects,
  requirements,
  reports,
  reviewOpinions,
  roleNodeMap,
  todos,
  treeNodes,
  versions
} from './seed'

const timeout = 240
const serverTime = '2026-06-26 10:30:00'

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

type KnowledgeSourceMock = {
  id: string
  name: string
  sourceType: 'standard' | 'project-file' | 'rule' | 'manual'
  version?: string
  status: '启用' | '停用' | '过期' | '待复核'
  fileCount: number
  chunkCount: number
  vectorStatus: '未向量化' | '向量化中' | '已向量化' | '向量化失败' | '待向量化'
  updatedAt: string
  actions: ActionCode[]
}

type KnowledgeFileMock = {
  id: string
  fileName: string
  sourceId: string
  sourceName: string
  projectId?: string
  projectName?: string
  nodeId?: number
  nodeName?: string
  documentId?: string
  documentVersionId?: string
  ocrStatus: DocumentAsset['currentOcrStatus']
  sliceStatus: '未切片' | '切片中' | '已切片' | '切片失败'
  vectorStatus: KnowledgeSourceMock['vectorStatus']
  chunkCount: number
  vectorCount: number
  updatedAt: string
  actions: ActionCode[]
}

type KnowledgeTaskMock = {
  id: string
  taskType: 'ocr' | 'slice' | 'vector' | 'reindex'
  targetType: 'source' | 'file' | 'project'
  targetId: string
  targetName: string
  status: '排队中' | '运行中' | '成功' | '失败' | '已取消'
  progress: number
  errorMessage?: string
  createdAt: string
  finishedAt?: string
  actions: ActionCode[]
}

type KnowledgeRuleVersionMock = {
  id: string
  name: string
  ruleKey: string
  version: string
  status: '草稿' | '待发布' | '已发布' | '已回滚'
  nodeIds: number[]
  promptVersion: string
  outputSchemaVersion: string
  description?: string
  publishedAt?: string
  updatedAt: string
  actions: ActionCode[]
}

type KnowledgeRuleVersionDiffChangeMock = {
  field: 'version' | 'status' | 'nodes' | 'prompt' | 'schema' | 'description'
  label: string
  before?: unknown
  after?: unknown
  severity: 'info' | 'warning'
  changeType: 'added' | 'changed' | 'removed'
}

type KnowledgeRuleVersionDiffMock = {
  base: KnowledgeRuleVersionMock
  target: KnowledgeRuleVersionMock
  comparedAt: string
  summary: {
    added: number
    changed: number
    removed: number
    warning: number
  }
  changes: KnowledgeRuleVersionDiffChangeMock[]
}

type KnowledgeConfigMock = {
  embeddingModel: string
  chunkSize: number
  chunkOverlap: number
  topKDefault: number
  rerankEnabled: boolean
  evidenceStrictMode: boolean
  autoReindex: boolean
  retentionDays: number
  updatedBy: string
  updatedAt: string
}

type ProjectMemberMock = {
  id: string
  projectId: string
  userId: string
  name: string
  orgName: string
  role: RoleCode
  nodeScope: number[]
  actions: ActionCode[]
  status: '启用' | '停用' | '已过期'
  expiresAt?: string
  updatedAt: string
}

type AdminOrgUnitMock = {
  id: string
  name: string
  type: 'owner' | 'contractor' | 'ndt' | 'inspection' | 'supervision'
  contactName: string
  contactPhone: string
  status: '启用' | '停用' | '待授权'
  projectCount: number
}

type AdminUserMock = {
  id: string
  name: string
  orgName: string
  role: RoleCode
  mobile: string
  status: '启用' | '停用'
  lastLoginAt: string
}

type AdminPermissionMatrixMock = {
  role: RoleCode
  label: string
  projectScope: string
  nodeScope: string
  actions: ActionCode[]
  readonly: boolean
}

type AdminNodeTemplateMock = {
  id: string
  version: string
  groupName: string
  nodeCount: number
  requiredCount: number
  status: '草稿' | '已发布' | '已停用'
  updatedAt: string
}

type AdminWorkflowMock = {
  id: string
  name: string
  version: string
  states: number
  transitions: number
  status: '启用' | '停用'
  updatedAt: string
}

type AdminTodoRuleMock = {
  id: string
  name: string
  triggerStatus: string
  assigneeRole: RoleCode
  deadlineHours: number
  enabled: boolean
  updatedAt: string
}

type AdminMessageTemplateMock = {
  id: string
  scene: string
  channel: '站内信' | '短信' | '邮件'
  titleTemplate: string
  contentTemplate: string
  enabled: boolean
  updatedAt: string
}

type AdminToolSourceMock = {
  id: string
  name: string
  toolType: 'external-query' | 'ocr' | 'signature' | 'archive'
  endpoint: string
  authMode: 'none' | 'token' | 'signature'
  status: '启用' | '停用' | '异常'
  updatedAt: string
}

type AdminFieldMappingMock = {
  id: string
  nodeId: number
  fieldName: string
  sourceField: string
  targetField: string
  required: boolean
  confidenceThreshold: number
  updatedAt: string
}

type AdminConfigTargetMock =
  | 'permission'
  | 'node-template'
  | 'workflow'
  | 'todo-rule'
  | 'message-template'
  | 'tool-source'
  | 'field-mapping'

type AdminConfigDiffMock = {
  target: AdminConfigTargetMock
  objectId: string
  objectName: string
  previewedAt: string
  changed: Array<{
    field: string
    label: string
    before?: unknown
    after?: unknown
    severity: 'info' | 'warning'
  }>
}

type IntegrationContractModuleMock =
  | 'workbench'
  | 'documents'
  | 'submissions'
  | 'inspection'
  | 'ndt-owner-report'
  | 'knowledge-admin'

type IntegrationContractStatusMock =
  | '已对齐'
  | '待后端确认'
  | '前端缺失'
  | '后端缺失'
  | '命名不一致'

type IntegrationContractFieldMock = {
  id: string
  module: IntegrationContractModuleMock
  moduleLabel: string
  endpoint: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  frontendField: string
  backendField: string
  required: boolean
  status: IntegrationContractStatusMock
  severity: 'info' | 'warning' | 'danger'
  owner: string
  note: string
  updatedAt: string
}

type LlmCompareRunMock = {
  runId: string
  question: string
  modelCodes: string[]
  createdAt: string
  projectId?: string
  nodeId?: number
  results: Array<{
    modelCode: string
    answer: string
    confidence: number
    evidenceLinkIds: string[]
    latencyMs: number
  }>
}

type SubmissionDraftMock = {
  draftId: string
  projectId: string
  nodeIds: number[]
  bindingIds: string[]
  batchName?: string
  remark?: string
  savedAt: string
}

type SubmissionSnapshotMock = {
  submissionId: string
  snapshotId: string
  projectId: string
  nodeIds: number[]
  bindingIds: string[]
  batchName?: string
  submitterComment?: string
  nextStatus: string
  submittedAt: string
  withdrawal?: {
    bindingCount: number
    reason: string
    withdrawnAt: string
  }
  createdTodoIds: string[]
  changed: Array<{ field: string; before?: unknown; after: unknown }>
}

type StandardReferenceMock = {
  clauseId: string
  standardName: string
  clauseNo: string
  title: string
  summary: string
  effectiveVersion: string
  evidenceLinkId?: string
}

type DateComparisonMock = {
  fieldName: string
  leftLabel: string
  leftValue: string
  rightLabel: string
  rightValue: string
  result: '覆盖' | '不覆盖' | '缺失' | '待确认'
  evidenceLinkIds: string[]
}

type ReportDetailMock = {
  report: ReportVersion
  sections: Array<{
    key: string
    title: string
    content: string
    evidenceLinkIds: string[]
  }>
  evidenceLinks: EvidenceLink[]
  reviewTrail: Array<{
    title: string
    actorName: string
    result: string
    createdAt: string
    comment?: string
  }>
  versionHistory: Array<{
    id: string
    versionNo: string
    status: ReportVersion['status']
    generatedAt: string
    summary: string
  }>
}

const initialKnowledgeSources: KnowledgeSourceMock[] = [
  {
    id: 'KS-STANDARD-TSG',
    name: 'TSG D7005 工业管道监督检验规则',
    sourceType: 'standard',
    version: 'std-v2026.06',
    status: '启用',
    fileCount: 8,
    chunkCount: 1420,
    vectorStatus: '已向量化',
    updatedAt: '2026-06-26 09:10:00',
    actions: ['knowledge:view', 'knowledge:manage', 'knowledge:reindex']
  },
  {
    id: 'KS-STANDARD-WELD',
    name: '焊接与无损检测标准库',
    sourceType: 'standard',
    version: 'weld-v2026.04',
    status: '启用',
    fileCount: 6,
    chunkCount: 1066,
    vectorStatus: '已向量化',
    updatedAt: '2026-06-25 17:20:00',
    actions: ['knowledge:view', 'knowledge:manage', 'knowledge:reindex']
  },
  {
    id: 'KS-PROJECT-FILE',
    name: '项目文件知识库',
    sourceType: 'project-file',
    version: 'proj-v2026.06.26',
    status: '启用',
    fileCount: documents.length,
    chunkCount: 0,
    vectorStatus: '向量化中',
    updatedAt: '2026-06-26 09:31:00',
    actions: ['knowledge:view', 'knowledge:manage', 'knowledge:reindex']
  },
  {
    id: 'KS-RULE-PROMPT',
    name: 'AI 审查规则与 Prompt',
    sourceType: 'rule',
    version: 'rule-v2026.06',
    status: '待复核',
    fileCount: 12,
    chunkCount: 384,
    vectorStatus: '已向量化',
    updatedAt: '2026-06-24 18:00:00',
    actions: ['knowledge:view', 'knowledge:manage']
  }
]

const initialKnowledgeFiles: KnowledgeFileMock[] = documents.map((document, index) => {
  const binding = bindings.find((item) => item.documentId === document.id)
  const node = binding ? treeNodes.find((item) => item.nodeId === binding.nodeId) : undefined
  const chunkCount = [18, 10, 24, 15][index] || 8
  const vectorStatus: KnowledgeFileMock['vectorStatus'] =
    document.currentOcrStatus === '识别中'
      ? '向量化中'
      : document.currentOcrStatus === '识别失败'
        ? '向量化失败'
        : '已向量化'
  return {
    id: `KF-${document.id}`,
    fileName: document.fileName,
    sourceId: 'KS-PROJECT-FILE',
    sourceName: '项目文件知识库',
    projectId: document.projectId,
    projectName: projects.find((project) => project.id === document.projectId)?.name,
    nodeId: binding?.nodeId,
    nodeName: node?.name,
    documentId: document.id,
    documentVersionId: document.currentVersionId,
    ocrStatus: document.currentOcrStatus,
    sliceStatus: document.currentOcrStatus === '识别中' ? '切片中' : '已切片',
    vectorStatus,
    chunkCount,
    vectorCount: vectorStatus === '已向量化' ? chunkCount : Math.max(0, chunkCount - 6),
    updatedAt: document.updatedAt,
    actions: ['knowledge:view', 'knowledge:reindex']
  }
})

initialKnowledgeSources[2].chunkCount = initialKnowledgeFiles.reduce(
  (sum, file) => sum + file.chunkCount,
  0
)

const initialKnowledgeTasks: KnowledgeTaskMock[] = [
  {
    id: 'KT-20260626-001',
    taskType: 'vector',
    targetType: 'file',
    targetId: 'KF-DOC-20260625-004',
    targetName: 'RT检测报告R2.pdf',
    status: '运行中',
    progress: 64,
    createdAt: '2026-06-26 09:28:00',
    actions: []
  },
  {
    id: 'KT-20260626-002',
    taskType: 'ocr',
    targetType: 'file',
    targetId: 'KF-DOC-20260625-003',
    targetName: '钢管质量证明书.pdf',
    status: '失败',
    progress: 38,
    errorMessage: '第 2 页表格识别置信度低于阈值，需重试或人工修正。',
    createdAt: '2026-06-26 08:52:00',
    finishedAt: '2026-06-26 08:55:00',
    actions: ['knowledge:task-retry']
  },
  {
    id: 'KT-20260626-003',
    taskType: 'reindex',
    targetType: 'source',
    targetId: 'KS-PROJECT-FILE',
    targetName: '项目文件知识库',
    status: '排队中',
    progress: 0,
    createdAt: '2026-06-26 10:12:00',
    actions: ['knowledge:task-retry']
  },
  {
    id: 'KT-20260625-004',
    taskType: 'slice',
    targetType: 'source',
    targetId: 'KS-STANDARD-TSG',
    targetName: 'TSG D7005 工业管道监督检验规则',
    status: '成功',
    progress: 100,
    createdAt: '2026-06-25 16:00:00',
    finishedAt: '2026-06-25 16:08:00',
    actions: []
  }
]

const initialKnowledgeRuleVersions: KnowledgeRuleVersionMock[] = [
  {
    id: 'RULE-WELDER-202606',
    name: '焊工资格核验规则',
    ruleKey: 'welder-qualification',
    version: 'Welder-Qualification-B-v2.1',
    status: '已发布',
    nodeIds: [24, 25, 27, 28],
    promptVersion: 'prompt-welder-v2.1',
    outputSchemaVersion: 'schema-review-v1.3',
    description: '核验焊工资格证、持证项目、有效期与施工焊接方法覆盖关系。',
    publishedAt: '2026-06-26 09:12:00',
    updatedAt: '2026-06-26 09:12:00',
    actions: ['knowledge:view', 'knowledge:manage']
  },
  {
    id: 'RULE-WELDER-202605',
    name: '焊工资格核验规则',
    ruleKey: 'welder-qualification',
    version: 'Welder-Qualification-B-v2.0',
    status: '已回滚',
    nodeIds: [24, 25, 27],
    promptVersion: 'prompt-welder-v2.0',
    outputSchemaVersion: 'schema-review-v1.2',
    description: '上一版焊工资格核验规则，保留用于回滚演练。',
    publishedAt: '2026-05-28 16:30:00',
    updatedAt: '2026-06-26 09:12:00',
    actions: ['knowledge:view', 'knowledge:manage']
  },
  {
    id: 'RULE-MATERIAL-202606',
    name: '材料质量证明核验规则',
    ruleKey: 'material-certificate',
    version: 'Material-Cert-C-v1.8',
    status: '已发布',
    nodeIds: [16, 17, 18, 39, 40],
    promptVersion: 'prompt-material-v1.8',
    outputSchemaVersion: 'schema-review-v1.3',
    description: '核验材质、炉批号、标准号、质量证明书与设计文件一致性。',
    publishedAt: '2026-06-25 17:40:00',
    updatedAt: '2026-06-25 17:40:00',
    actions: ['knowledge:view', 'knowledge:manage']
  },
  {
    id: 'RULE-NDT-202606',
    name: '无损检测报告核验规则',
    ruleKey: 'ndt-report',
    version: 'NDT-Report-C-v1.4',
    status: '待发布',
    nodeIds: [35, 36, 40, 41, 42],
    promptVersion: 'prompt-ndt-v1.4',
    outputSchemaVersion: 'schema-ndt-v1.1',
    description: '核验底片、检测比例、评片结论、返修闭环和报告签章。',
    updatedAt: '2026-06-26 10:05:00',
    actions: ['knowledge:view', 'knowledge:manage']
  }
]

const initialKnowledgeConfig: KnowledgeConfigMock = {
  embeddingModel: 'text-embedding-3-large',
  chunkSize: 900,
  chunkOverlap: 120,
  topKDefault: 5,
  rerankEnabled: true,
  evidenceStrictMode: true,
  autoReindex: true,
  retentionDays: 180,
  updatedBy: '张工',
  updatedAt: '2026-06-26 09:45:00'
}

const initialLlmCompareRuns: LlmCompareRunMock[] = [
  {
    runId: 'CMP-20260626-001',
    question: '焊工资格证与持证项目是否覆盖本项目焊接方法？',
    modelCodes: ['LLM-A', 'LLM-B'],
    createdAt: '2026-06-26 09:40:00',
    projectId,
    nodeId: 24,
    results: [
      {
        modelCode: 'LLM-A',
        answer: '证书编号和持证项目基本匹配，建议人工确认外部查询截图来源后通过。',
        confidence: 0.88,
        evidenceLinkIds: ['EV-24-001', 'EV-24-002'],
        latencyMs: 1240
      },
      {
        modelCode: 'LLM-B',
        answer: '持证项目覆盖焊接方法，但外部核验资料仍需补充来源说明。',
        confidence: 0.82,
        evidenceLinkIds: ['EV-24-001'],
        latencyMs: 1580
      }
    ]
  }
]

const initialNdtRecords: NdtRecord[] = [
  {
    id: 'NDT-REC-001',
    projectId,
    nodeId: 40,
    recordNo: 'REC-RT-20260625-001',
    filmId: 'FILM-RT-001',
    reportId: 'NDT-RPT-001',
    weldNo: 'W-24-RT-018',
    pipelineNo: 'PL-HD-02',
    method: 'RT',
    testDate: '2026-06-25',
    evaluatorName: '王工',
    result: '合格',
    sampleStatus: '已抽查',
    conclusion: '底片黑度、像质计和缺陷评定记录齐全。',
    importedAt: '2026-06-25 15:00:00',
    actions: ['ndt:record-import']
  },
  {
    id: 'NDT-REC-002',
    projectId,
    nodeId: 40,
    recordNo: 'REC-RT-20260626-002',
    filmId: 'FILM-RT-002',
    reportId: 'NDT-RPT-001',
    weldNo: 'W-41-RT-020',
    pipelineNo: 'PL-HD-04',
    method: 'RT',
    testDate: '2026-06-26',
    evaluatorName: '王工',
    result: '待复核',
    sampleStatus: '需复核',
    conclusion: '底片包索引缺少原始编号页，已形成监检反馈。',
    importedAt: '2026-06-26 09:10:00',
    actions: ['ndt:record-import', 'rectification:submit']
  }
]

const initialExportTasks: ExportTask[] = [
  {
    id: 'EXP-RPT-20260625-001',
    projectId,
    exportType: 'report',
    status: '可下载',
    progress: 100,
    fileName: '监督检验报告 GDJ-JJ-2026-001.pdf',
    fileSize: 2048 * 1024,
    downloadUrl: 'mock://download/reports/RPT-20260625-001.pdf',
    createdAt: '2026-06-26 09:44:00',
    finishedAt: '2026-06-26 09:45:00',
    expiresAt: '2026-06-27 09:45:00'
  },
  {
    id: 'EXP-ARCHIVE-QUEUE-001',
    projectId,
    exportType: 'archive-package',
    status: '排队中',
    progress: 12,
    fileName: 'P-2026-HDCP-001-归档资料包.zip',
    fileSize: 4 * 1024 * 1024,
    createdAt: '2026-06-26 09:50:00',
    expiresAt: '2026-06-27 09:50:00'
  },
  {
    id: 'EXP-EVIDENCE-RUNNING-001',
    projectId,
    exportType: 'evidence-package',
    status: '生成中',
    progress: 58,
    fileName: 'P-2026-HDCP-001-节点24-证据定位包.zip',
    fileSize: 768 * 1024,
    createdAt: '2026-06-26 09:52:00',
    expiresAt: '2026-06-27 09:52:00'
  },
  {
    id: 'EXP-DOC-FAILED-001',
    projectId,
    exportType: 'document',
    status: '失败',
    progress: 64,
    fileName: '焊工资格证-王建国.pdf',
    fileSize: 512 * 1024,
    createdAt: '2026-06-26 09:55:00',
    finishedAt: '2026-06-26 09:56:00',
    errorMessage: '签名下载地址生成失败，请稍后重新发起单项资料下载。'
  },
  {
    id: 'EXP-RPT-EXPIRED-001',
    projectId: 'P-2025-NJARCH-018',
    exportType: 'report',
    status: '已过期',
    progress: 100,
    fileName: '南京老厂区管廊改造工程监督检验报告-V5.pdf',
    fileSize: 2304 * 1024,
    downloadUrl: 'mock://download/reports/RPT-20250620-018.pdf',
    createdAt: '2026-06-20 15:10:00',
    finishedAt: '2026-06-20 15:12:00',
    expiresAt: '2026-06-21 15:12:00'
  }
]

const initialMemberActions: Record<RoleCode, ActionCode[]> = {
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
    'report:archive',
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
    'fde:release:shadow',
    'fde:release:canary',
    'fde:release:rollback',
    'fde:ocr-quality:view',
    'fde:incident:manage',
    'fde:config:draft'
  ]
}

const makeInitialProjectMembers = (): ProjectMemberMock[] =>
  projects.flatMap((project) => [
    {
      id: `PM-${project.id}-INS`,
      projectId: project.id,
      userId: 'USR-INS-001',
      name: '张工',
      orgName: project.inspectionOrgName,
      role: 'inspection',
      nodeScope: [16, 24, 40, 68],
      actions: initialMemberActions.inspection,
      status: '启用',
      updatedAt: project.updatedAt
    },
    {
      id: `PM-${project.id}-CON`,
      projectId: project.id,
      userId: 'USR-CON-001',
      name: '李工',
      orgName: project.contractorOrgName,
      role: 'contractor',
      nodeScope: [1, 16, 24, 40],
      actions: initialMemberActions.contractor,
      status: project.status === '已归档' ? '停用' : '启用',
      updatedAt: project.updatedAt
    },
    {
      id: `PM-${project.id}-NDT`,
      projectId: project.id,
      userId: 'USR-NDT-001',
      name: '王工',
      orgName: project.ndtOrgName,
      role: 'ndt',
      nodeScope: [35, 36, 40, 41, 42],
      actions: initialMemberActions.ndt,
      status: project.status === '已归档' ? '停用' : '启用',
      updatedAt: project.updatedAt
    },
    {
      id: `PM-${project.id}-OWN`,
      projectId: project.id,
      userId: 'USR-OWN-001',
      name: '陈总',
      orgName: project.ownerOrgName,
      role: 'owner',
      nodeScope: [1, 16, 24, 40, 68],
      actions: initialMemberActions.owner,
      status: '启用',
      updatedAt: project.updatedAt
    }
  ])

const initialAdminUsers: AdminUserMock[] = [
  {
    id: 'USR-INS-001',
    name: '张工',
    orgName: '省特检院一部',
    role: 'inspection',
    mobile: '13800020001',
    status: '启用',
    lastLoginAt: '2026-06-26 10:10:00'
  },
  {
    id: 'USR-CON-001',
    name: '李工',
    orgName: '中石化安装有限公司',
    role: 'contractor',
    mobile: '13800020002',
    status: '启用',
    lastLoginAt: '2026-06-26 09:52:00'
  },
  {
    id: 'USR-NDT-001',
    name: '王工',
    orgName: '华测检测有限公司',
    role: 'ndt',
    mobile: '13800020003',
    status: '启用',
    lastLoginAt: '2026-06-26 09:38:00'
  },
  {
    id: 'USR-OWN-001',
    name: '陈总',
    orgName: '华东管网建设公司',
    role: 'owner',
    mobile: '13800020004',
    status: '启用',
    lastLoginAt: '2026-06-25 18:20:00'
  },
  {
    id: 'USR-ADM-001',
    name: '系统管理员',
    orgName: '省特检院平台部',
    role: 'admin',
    mobile: '13800020005',
    status: '启用',
    lastLoginAt: '2026-06-26 10:25:00'
  }
]

const initialAdminPermissionMatrix: AdminPermissionMatrixMock[] = [
  {
    role: 'inspection',
    label: '监检人员',
    projectScope: '授权项目',
    nodeScope: '全部监督检验节点',
    actions: initialMemberActions.inspection,
    readonly: false
  },
  {
    role: 'contractor',
    label: '施工方',
    projectScope: '参建项目',
    nodeScope: '资料提交节点',
    actions: initialMemberActions.contractor,
    readonly: false
  },
  {
    role: 'ndt',
    label: '无损检测',
    projectScope: '检测委托项目',
    nodeScope: '35-42 无损检测节点',
    actions: initialMemberActions.ndt,
    readonly: false
  },
  {
    role: 'owner',
    label: '建设方',
    projectScope: '建设单位项目',
    nodeScope: '只读全部节点',
    actions: initialMemberActions.owner,
    readonly: true
  },
  {
    role: 'admin',
    label: '系统管理员',
    projectScope: '全局配置',
    nodeScope: '模板和权限配置',
    actions: initialMemberActions.admin,
    readonly: false
  }
]

const makeInitialAdminNodeTemplates = (): AdminNodeTemplateMock[] =>
  nodeGroups.slice(0, 8).map((group, index) => ({
    id: `TPL-NODE-${String(index + 1).padStart(2, '0')}`,
    version: 'node-v2026.06',
    groupName: group.name,
    nodeCount: group.nodes.length,
    requiredCount: requirements.filter((requirement) =>
      group.nodes.some((node) => node.nodeId === requirement.nodeId)
    ).length,
    status: index === 0 ? '草稿' : '已发布',
    updatedAt: index === 0 ? '2026-06-26 10:20:00' : '2026-06-25 18:00:00'
  }))

const initialAdminWorkflowStateMachines: AdminWorkflowMock[] = [
  {
    id: 'WF-PIPE-202606',
    name: '压力管道监督检验流程',
    version: 'workflow-v2026.06',
    states: 13,
    transitions: 27,
    status: '启用',
    updatedAt: '2026-06-26 09:00:00'
  },
  {
    id: 'WF-ARCHIVE-202606',
    name: '报告复核与归档流程',
    version: 'archive-v2026.06',
    states: 5,
    transitions: 8,
    status: '启用',
    updatedAt: '2026-06-25 16:30:00'
  }
]

const initialAdminTodoRules: AdminTodoRuleMock[] = [
  {
    id: 'TODO-RULE-SUBMISSION-REVIEW',
    name: '资料提交后监检待审查',
    triggerStatus: 'AI 预审中',
    assigneeRole: 'inspection',
    deadlineHours: 48,
    enabled: true,
    updatedAt: '2026-06-26 09:15:00'
  },
  {
    id: 'TODO-RULE-CORRECTION',
    name: '退回补正责任单位待办',
    triggerStatus: '需补正',
    assigneeRole: 'contractor',
    deadlineHours: 72,
    enabled: true,
    updatedAt: '2026-06-26 09:18:00'
  },
  {
    id: 'TODO-RULE-NDT-FEEDBACK',
    name: '无损检测抽查反馈',
    triggerStatus: '需补正',
    assigneeRole: 'ndt',
    deadlineHours: 48,
    enabled: true,
    updatedAt: '2026-06-25 17:40:00'
  }
]

const initialAdminMessageTemplates: AdminMessageTemplateMock[] = [
  {
    id: 'MSG-TPL-SUBMISSION',
    scene: 'submission-created',
    channel: '站内信',
    titleTemplate: '资料批次已提交：{{projectName}}',
    contentTemplate: '{{submitterName}} 已提交 {{nodeName}} 资料，请在 {{deadline}} 前完成审查。',
    enabled: true,
    updatedAt: '2026-06-26 09:20:00'
  },
  {
    id: 'MSG-TPL-CORRECTION',
    scene: 'return-correction',
    channel: '站内信',
    titleTemplate: '节点 {{nodeId}} 需补正',
    contentTemplate: '监检意见：{{reason}}。请补充资料并重新提交。',
    enabled: true,
    updatedAt: '2026-06-26 09:25:00'
  },
  {
    id: 'MSG-TPL-REPORT',
    scene: 'report-archived',
    channel: '邮件',
    titleTemplate: '监督检验报告已归档',
    contentTemplate: '{{projectName}} 的报告 {{reportNo}} 已归档，可进入建设方工作台查看。',
    enabled: false,
    updatedAt: '2026-06-24 16:30:00'
  }
]

const initialAdminToolSources: AdminToolSourceMock[] = [
  {
    id: 'TOOL-WELDER-QUERY',
    name: '焊工资格外部查询',
    toolType: 'external-query',
    endpoint: 'https://mock-tools.local/welder',
    authMode: 'token',
    status: '启用',
    updatedAt: '2026-06-26 08:45:00'
  },
  {
    id: 'TOOL-OCR-PIPE',
    name: '项目文件 OCR 服务',
    toolType: 'ocr',
    endpoint: 'mock://ocr/project-documents',
    authMode: 'signature',
    status: '启用',
    updatedAt: '2026-06-25 18:00:00'
  },
  {
    id: 'TOOL-SIGNATURE',
    name: '报告签章校验服务',
    toolType: 'signature',
    endpoint: 'mock://signature/report',
    authMode: 'token',
    status: '异常',
    updatedAt: '2026-06-26 10:02:00'
  }
]

const initialAdminFieldMappings: AdminFieldMappingMock[] = [
  {
    id: 'FM-MATERIAL-HEAT',
    nodeId: 16,
    fieldName: '炉批号',
    sourceField: 'ocr.material.heatNo',
    targetField: 'materialCertificate.heatNo',
    required: true,
    confidenceThreshold: 0.86,
    updatedAt: '2026-06-26 09:32:00'
  },
  {
    id: 'FM-WELDER-CERT',
    nodeId: 24,
    fieldName: '焊工资格证编号',
    sourceField: 'ocr.welder.certNo',
    targetField: 'welderQualification.certNo',
    required: true,
    confidenceThreshold: 0.9,
    updatedAt: '2026-06-26 09:34:00'
  },
  {
    id: 'FM-NDT-REPORT',
    nodeId: 40,
    fieldName: '检测报告编号',
    sourceField: 'ocr.ndt.reportNo',
    targetField: 'ndtReport.reportNo',
    required: true,
    confidenceThreshold: 0.88,
    updatedAt: '2026-06-25 17:10:00'
  }
]

const state = {
  projects: clone<Project[]>(projects),
  treeNodes: projects.flatMap((project) =>
    treeNodes.map((node) => ({
      ...clone<ProjectTreeNode>(node),
      id: `${project.id}-${node.nodeId}`,
      projectId: project.id,
      status:
        project.id === projectId
          ? node.status
          : node.nodeId === project.currentNodeId
            ? statusFromProject(project.status)
            : '待提交',
      fileCount:
        project.id === projectId ? node.fileCount : node.nodeId === project.currentNodeId ? 1 : 0,
      requiredProgress:
        project.id === projectId
          ? clone(node.requiredProgress)
          : {
              done: node.nodeId === project.currentNodeId ? 1 : 0,
              total: node.requiredProgress.total
            }
    }))
  ),
  documents: clone<DocumentAsset[]>(documents),
  versions: clone<DocumentVersion[]>(versions),
  bindings: clone<NodeFileBinding[]>(bindings),
  aiRuns: clone<AiReviewRun[]>(aiRuns),
  reviewOpinions: clone<ReviewOpinion[]>(reviewOpinions),
  reports: clone<ReportVersion[]>(reports),
  archiveItems: clone<ArchiveItem[]>(archiveItems),
  ndtFilms: clone<NdtFilm[]>(ndtFilms),
  ndtReports: clone<NdtReport[]>(ndtReports),
  ndtRecords: clone<NdtRecord[]>(initialNdtRecords),
  ndtFeedback: clone<NdtFeedback[]>(ndtFeedback),
  todos: clone<TodoItem[]>(todos),
  messages: clone<MessageItem[]>(messages),
  knowledgeSources: clone<KnowledgeSourceMock[]>(initialKnowledgeSources),
  knowledgeFiles: clone<KnowledgeFileMock[]>(initialKnowledgeFiles),
  knowledgeTasks: clone<KnowledgeTaskMock[]>(initialKnowledgeTasks),
  knowledgeRuleVersions: clone<KnowledgeRuleVersionMock[]>(initialKnowledgeRuleVersions),
  knowledgeConfig: clone<KnowledgeConfigMock>(initialKnowledgeConfig),
  llmCompareRuns: clone<LlmCompareRunMock[]>(initialLlmCompareRuns),
  exportTasks: clone<ExportTask[]>(initialExportTasks),
  projectMembers: clone<ProjectMemberMock[]>(makeInitialProjectMembers()),
  adminUsers: clone<AdminUserMock[]>(initialAdminUsers),
  adminPermissionMatrix: clone<AdminPermissionMatrixMock[]>(initialAdminPermissionMatrix),
  adminNodeTemplates: clone<AdminNodeTemplateMock[]>(makeInitialAdminNodeTemplates()),
  adminWorkflowStateMachines: clone<AdminWorkflowMock[]>(initialAdminWorkflowStateMachines),
  adminTodoRules: clone<AdminTodoRuleMock[]>(initialAdminTodoRules),
  adminMessageTemplates: clone<AdminMessageTemplateMock[]>(initialAdminMessageTemplates),
  adminToolSources: clone<AdminToolSourceMock[]>(initialAdminToolSources),
  adminFieldMappings: clone<AdminFieldMappingMock[]>(initialAdminFieldMappings),
  submissionDrafts: [] as SubmissionDraftMock[],
  submissionSnapshots: [] as SubmissionSnapshotMock[],
  fdeReviewFeedbacks: [] as Array<Record<string, unknown>>,
  idempotencyKeys: new Set<string>(),
  auditLogs: [
    {
      id: 'AUD-001',
      actorName: '周工',
      action: '发布规则版本',
      objectType: 'RuleTemplate',
      objectId: 'RULE-24',
      result: '成功',
      createdAt: '2026-06-26 09:12:00'
    }
  ]
}

const roleActions: Record<RoleCode, ActionCode[]> = {
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
    'report:archive',
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
    'knowledge:task-retry',
    'knowledge:reindex',
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
    'fde:release:shadow',
    'fde:release:canary',
    'fde:release:rollback',
    'fde:ocr-quality:view',
    'fde:incident:manage',
    'fde:config:draft'
  ]
}

function statusFromProject(status: ProjectStatus): NodeStatus {
  if (status === '退回补正中') return '需补正'
  if (status === 'AI 预审中') return 'AI 预审中'
  if (status === '监检审查中') return '待审查'
  if (status === '已归档') return '已归档'
  return '待提交'
}

const ok = (data: unknown) => ({
  code: SUCCESS_CODE,
  data,
  operationId: `MOCK-${Date.now()}`,
  serverTime
})

const fail = (code: number, message: string, data?: unknown) => ({
  code,
  message,
  data,
  operationId: `MOCK-${Date.now()}`,
  serverTime
})

type MockMutationContext = {
  body?: Record<string, any>
  query?: Record<string, any>
  action?: string
}

const getMockErrorCode = (context?: MockMutationContext) =>
  String(context?.body?.mockError || context?.query?.mockError || '').toUpperCase()

const getForcedMutationError = (context?: MockMutationContext) => {
  const action = context?.action || '当前操作'
  const code = getMockErrorCode(context)
  if (code === 'FORBIDDEN') {
    return fail(40301, `${action}权限不足。`, { reason: 'FORBIDDEN', action })
  }
  if (code === 'TASK_RUNNING') {
    return fail(40902, `${action}已有任务正在运行，请稍后查看进度。`, {
      reason: 'TASK_RUNNING',
      runningTaskId: `TASK-${Date.now()}`
    })
  }
  if (code === 'IDEMPOTENCY_CONFLICT') {
    return fail(40903, `${action}幂等键已被其他请求占用。`, {
      reason: 'IDEMPOTENCY_CONFLICT',
      idempotencyKey: context?.body?.idempotencyKey || context?.query?.idempotencyKey
    })
  }
  if (code === 'ETAG_CONFLICT') {
    return fail(40904, `${action}数据版本已变化，请刷新后重试。`, {
      reason: 'ETAG_CONFLICT',
      expected: 'etag-current',
      actual: context?.body?.ifMatch || context?.query?.ifMatch || 'etag-stale'
    })
  }
  return undefined
}

const getRoleMutationError = (context?: MockMutationContext) => {
  const role = (context?.body?.role || context?.query?.role) as RoleCode | undefined
  if (role === 'owner') {
    return fail(40301, '建设方为只读角色，不能执行写操作。', {
      reason: 'FORBIDDEN',
      role,
      action: context?.action
    })
  }
  return undefined
}

const getIdempotencyMutationError = (context?: MockMutationContext) => {
  const idempotencyKey = context?.body?.idempotencyKey || context?.query?.idempotencyKey
  if (!idempotencyKey) return undefined
  if (state.idempotencyKeys.has(idempotencyKey)) {
    return fail(40903, '重复的幂等键与已有请求冲突。', {
      reason: 'IDEMPOTENCY_CONFLICT',
      idempotencyKey
    })
  }
  state.idempotencyKeys.add(idempotencyKey)
  return undefined
}

const getEtagMutationError = (context?: MockMutationContext) => {
  const ifMatch = context?.body?.ifMatch || context?.query?.ifMatch
  if (ifMatch && ifMatch !== 'etag-current') {
    return fail(40904, '数据版本已变化，请刷新后重试。', {
      reason: 'ETAG_CONFLICT',
      expected: 'etag-current',
      actual: ifMatch
    })
  }
  return undefined
}

const getMutationError = (projectId: string, context?: MockMutationContext) => {
  const forcedError = getForcedMutationError(context)
  if (forcedError) return forcedError
  const roleError = getRoleMutationError(context)
  if (roleError) return roleError
  const idempotencyError = getIdempotencyMutationError(context)
  if (idempotencyError) return idempotencyError
  const etagError = getEtagMutationError(context)
  if (etagError) return etagError
  const project = getProject(projectId)
  if (project.status === '已归档') {
    return fail(40901, '归档项目为只读状态，不能继续写入。', { reason: 'ARCHIVED_READONLY' })
  }
  return undefined
}

const getNodeMutationError = (projectId: string, nodeId: number, context?: MockMutationContext) => {
  const projectError = getMutationError(projectId, context)
  if (projectError) return projectError
  const node = getNode(projectId, nodeId)
  if (node.status === '已归档') {
    return fail(40901, '归档节点为只读状态，不能继续写入。', { reason: 'ARCHIVED_READONLY' })
  }
  return undefined
}

const pathParts = (url = '') => url.split('?')[0].split('/').filter(Boolean)

const getRole = (query?: Record<string, string>): RoleCode =>
  (query?.role as RoleCode) || 'inspection'

const getProject = (id = projectId) =>
  state.projects.find((project) => project.id === id) || state.projects[0]

const getNode = (projectId: string, nodeId: number) =>
  state.treeNodes.find((node) => node.projectId === projectId && node.nodeId === nodeId) ||
  state.treeNodes.find((node) => node.projectId === projectId) ||
  state.treeNodes[0]

const getProjectActions = (project: Project, role: RoleCode) => {
  if (role === 'owner' || project.status === '已归档') {
    return ['project:view', 'report:view', 'archive:view', 'archive:download'] as ActionCode[]
  }
  return roleActions[role]
}

const getPreviewType = (fileType = '') => {
  const normalized = fileType.toLowerCase()
  if (normalized === 'pdf') return 'pdf'
  if (['doc', 'docx', 'xls', 'xlsx'].includes(normalized)) return 'office'
  if (['jpg', 'jpeg', 'png'].includes(normalized)) return 'image'
  return 'unsupported'
}

const getDocumentSignedUrls = (document: DocumentAsset, version?: DocumentVersion) => {
  const fileSize = version?.fileSize || 0
  const contentType =
    document.fileType === 'pdf'
      ? 'application/pdf'
      : document.fileType.includes('xls')
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        : 'application/octet-stream'
  return {
    preview: {
      url: `mock://preview/documents/${document.id}?versionId=${document.currentVersionId}`,
      method: 'GET' as const,
      expiresAt: '2026-06-26 11:30:00',
      fileName: document.fileName,
      contentType,
      fileSize,
      previewType: getPreviewType(document.fileType),
      readonly: true,
      pageCount: document.fileType === 'pdf' ? 2 : undefined
    },
    download: {
      url: `mock://download/documents/${document.id}?versionId=${document.currentVersionId}`,
      method: 'GET' as const,
      expiresAt: '2026-06-26 11:30:00',
      fileName: document.fileName,
      contentType,
      fileSize
    }
  }
}

const getNodeId = (query?: Record<string, string>, fallback = 24) => {
  const fromQuery = Number(query?.nodeId)
  return Number.isFinite(fromQuery) && fromQuery > 0 ? fromQuery : fallback
}

const getProjectGroups = (projectId: string) =>
  nodeGroups.map((group) => ({
    groupName: group.name,
    nodes: state.treeNodes.filter(
      (node) => node.projectId === projectId && node.groupName === group.name
    )
  }))

const refreshProjectCounters = (projectId: string) => {
  const project = getProject(projectId)
  project.todoCount = state.todos.filter(
    (todo) => todo.projectId === projectId && todo.status !== '已完成' && todo.status !== '已关闭'
  ).length
  project.messageCount = state.messages.filter(
    (message) => message.projectId === projectId && !message.read
  ).length
  project.updatedAt = serverTime
}

const setProjectStatus = (projectId: string, status: ProjectStatus, currentNodeId?: number) => {
  const project = getProject(projectId)
  project.status = status
  if (currentNodeId) project.currentNodeId = currentNodeId
  refreshProjectCounters(projectId)
}

const setNodeStatus = (projectId: string, nodeId: number, status: NodeStatus) => {
  const node = getNode(projectId, nodeId)
  const before = node.status
  node.status = status
  return { node, before }
}

const updateNodeFileProgress = (projectId: string, nodeId: number) => {
  const node = getNode(projectId, nodeId)
  const count = state.bindings.filter(
    (binding) => binding.projectId === projectId && binding.nodeId === nodeId
  ).length
  node.fileCount = count
  node.requiredProgress.done = Math.min(node.requiredProgress.total, count)
  if (count > 0 && node.status === '待提交') node.status = '部分提交'
}

const addAuditLog = (action: string, objectType: string, objectId: string) => {
  const log = {
    id: `AUD-${Date.now()}`,
    actorName: 'mock 用户',
    action,
    objectType,
    objectId,
    result: '成功',
    createdAt: serverTime
  }
  state.auditLogs.unshift(log)
  return log.id
}

const addTodo = (todo: Omit<TodoItem, 'id'>) => {
  const item: TodoItem = { id: `TODO-${Date.now()}-${state.todos.length + 1}`, ...todo }
  state.todos.unshift(item)
  refreshProjectCounters(item.projectId)
  return item
}

const addMessage = (message: Omit<MessageItem, 'id' | 'read' | 'createdAt'>) => {
  const item: MessageItem = {
    id: `MSG-${Date.now()}-${state.messages.length + 1}`,
    read: false,
    createdAt: serverTime,
    ...message
  }
  state.messages.unshift(item)
  if (item.projectId) refreshProjectCounters(item.projectId)
  return item
}

const closeNodeTodos = (projectId: string, nodeId: number, assigneeName?: string) => {
  state.todos.forEach((todo) => {
    if (todo.projectId !== projectId || todo.nodeId !== nodeId) return
    if (assigneeName && todo.assigneeName !== assigneeName) return
    todo.status = '已完成'
  })
  refreshProjectCounters(projectId)
}

const createMutation = (
  objectType: string,
  objectId: string,
  nextStatus?: string,
  before?: string
) =>
  ok({
    id: `MUT-${Date.now()}`,
    objectType,
    objectId,
    nextStatus,
    changed: nextStatus ? [{ field: 'status', before, after: nextStatus }] : [],
    auditLogId: addAuditLog(`更新${objectType}`, objectType, objectId)
  })

const getEvidenceForNode = (nodeId: number): EvidenceLink[] => {
  const scoped = state.aiRuns.find((run) => run.nodeId === nodeId)?.evidenceLinks
  if (scoped?.length) return scoped
  const byNode = evidenceLinks.filter((link) => link.id.includes(`-${nodeId}-`))
  return byNode.length ? byNode : evidenceLinks
}

const getNodeExtractedFields = (projectId: string, nodeId: number) => {
  const versionIds = state.bindings
    .filter((binding) => binding.projectId === projectId && binding.nodeId === nodeId)
    .map((binding) => binding.documentVersionId)
  return extractedFields.filter((field) => versionIds.includes(field.documentVersionId))
}

const buildStandardReferences = (projectId: string, nodeId: number): StandardReferenceMock[] => {
  const node = getNode(projectId, nodeId)
  const firstEvidence = getEvidenceForNode(nodeId)[0]?.id
  if (nodeId === 24) {
    return [
      {
        clauseId: 'STD-WELDER-QUAL-01',
        standardName: '特种设备焊接操作人员考核细则',
        clauseNo: '第十九条',
        title: '焊工资格证有效期和合格项目',
        summary: '焊工资格应在有效期内，合格项目应覆盖本项目焊接方法、材料类别和位置。',
        effectiveVersion: '2026.04',
        evidenceLinkId: firstEvidence
      },
      {
        clauseId: 'STD-AICHECK-EVIDENCE-24',
        standardName: '工业管道监督检验资料审查规则',
        clauseNo: '4.2.3',
        title: '外部查询结果核验',
        summary: '对焊工资格证书编号、人员姓名和查询截图来源进行交叉核验，无法确认时转人工确认。',
        effectiveVersion: '2026.06',
        evidenceLinkId: firstEvidence
      }
    ]
  }
  if (nodeId === 16) {
    return [
      {
        clauseId: 'STD-MATERIAL-QUALITY-16',
        standardName: '压力管道元件质量证明文件审查规则',
        clauseNo: '5.1.1',
        title: '材料质量证明书完整性',
        summary: '质量证明文件应包含炉批号、牌号、规格、制造单位和检验结论，并与实物标识一致。',
        effectiveVersion: '2026.05',
        evidenceLinkId: firstEvidence
      }
    ]
  }
  if (nodeId === 40) {
    return [
      {
        clauseId: 'STD-NDT-RT-40',
        standardName: '承压设备无损检测监督抽查规则',
        clauseNo: '7.3.2',
        title: '检测报告与底片追溯',
        summary: '检测报告编号、焊口编号、检测日期和评定级别应与底片和检测记录保持一致。',
        effectiveVersion: '2026.03',
        evidenceLinkId: firstEvidence
      }
    ]
  }
  return [
    {
      clauseId: `STD-GENERAL-${nodeId}`,
      standardName: '工业管道监督检验通用资料审查规则',
      clauseNo: node.inspectionType === 'A' ? '3.1.1' : '3.2.1',
      title: `${node.name}资料完整性`,
      summary: '节点必传资料应满足完整、有效、可追溯要求，条件必传资料需说明适用条件。',
      effectiveVersion: '2026.06',
      evidenceLinkId: firstEvidence
    }
  ]
}

const buildDateComparisons = (projectId: string, nodeId: number): DateComparisonMock[] => {
  const links = getEvidenceForNode(nodeId)
  const fields = getNodeExtractedFields(projectId, nodeId)
  if (nodeId === 24) {
    return [
      {
        fieldName: '焊工资格有效期',
        leftLabel: '资格证有效期',
        leftValue: '2024-03-15 至 2028-03-14',
        rightLabel: '焊接作业日期',
        rightValue: '2026-06-20',
        result: '覆盖',
        evidenceLinkIds: links.slice(0, 2).map((item) => item.id)
      },
      {
        fieldName: '证书外部查询日期',
        leftLabel: '外部查询截图日期',
        leftValue: '2026-06-25',
        rightLabel: '资料提交日期',
        rightValue: '2026-06-25',
        result: '覆盖',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      },
      {
        fieldName: '复审确认日期',
        leftLabel: 'AI 审查完成时间',
        leftValue: '2026-06-25 15:10:00',
        rightLabel: '人工复核时间',
        rightValue: serverTime,
        result: '待确认',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      }
    ]
  }
  if (nodeId === 16) {
    return [
      {
        fieldName: '材料质证书签发日期',
        leftLabel: '质证书签发日期',
        leftValue: '2026-04-18',
        rightLabel: '材料到场日期',
        rightValue: '2026-05-06',
        result: '覆盖',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      },
      {
        fieldName: '炉批号复核',
        leftLabel: 'OCR 提取炉批号',
        leftValue: fields[0]?.fieldValue || 'H240315A07',
        rightLabel: '质量证明书炉批号',
        rightValue: 'H240315A07',
        result: fields[0]?.reviewStatus === '低置信度' ? '待确认' : '覆盖',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      }
    ]
  }
  if (nodeId === 40) {
    return [
      {
        fieldName: '无损检测日期',
        leftLabel: '检测报告日期',
        leftValue: '2026-06-23',
        rightLabel: '焊口完成日期',
        rightValue: '2026-06-21',
        result: '覆盖',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      },
      {
        fieldName: '评片复核日期',
        leftLabel: '报告上传日期',
        leftValue: '2026-06-25',
        rightLabel: '监检抽查日期',
        rightValue: '2026-06-26',
        result: '待确认',
        evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
      }
    ]
  }
  return [
    {
      fieldName: '资料有效期',
      leftLabel: '文件签发日期',
      leftValue: '2026-06-20',
      rightLabel: '节点审查日期',
      rightValue: serverTime,
      result: '待确认',
      evidenceLinkIds: links.slice(0, 1).map((item) => item.id)
    }
  ]
}

const uniqueEvidenceLinks = (links: EvidenceLink[]) =>
  Array.from(new Map(links.map((link) => [link.id, link])).values())

const buildReportDetail = (projectId: string, report: ReportVersion): ReportDetailMock => {
  const nodes = report.nodeIds.map((nodeId) => getNode(projectId, nodeId))
  const reportEvidence = uniqueEvidenceLinks(
    report.nodeIds.flatMap((nodeId) => getEvidenceForNode(nodeId))
  )
  const reviewTrail = [
    {
      title: '报告草稿生成',
      actorName: report.reviewerName || '张工',
      result: report.status,
      createdAt: report.generatedAt,
      comment: `${report.scope === 'project' ? '项目范围' : '当前节点'}报告，包含 ${nodes.length} 个监督检验节点。`
    },
    ...state.reviewOpinions
      .filter(
        (opinion) => opinion.projectId === projectId && report.nodeIds.includes(opinion.nodeId)
      )
      .map((opinion) => ({
        title: `节点 ${opinion.nodeId} 人工审查`,
        actorName: opinion.reviewerName,
        result: opinion.result,
        createdAt: opinion.createdAt,
        comment: opinion.opinion
      }))
  ]
  if (report.status === '已归档') {
    reviewTrail.push({
      title: '报告归档',
      actorName: report.reviewerName || '张工',
      result: '已归档',
      createdAt: serverTime,
      comment: '报告已锁定，归档资料和证据包可只读下载。'
    })
  }
  const versionNo = Number(report.versionNo.replace(/\D/g, '')) || 1
  const versionHistory = Array.from({ length: Math.max(versionNo, 1) }).map((_, index) => {
    const current = index + 1 === versionNo
    return {
      id: `${report.id}-V${index + 1}`,
      versionNo: `V${index + 1}`,
      status: current ? report.status : ('草稿' as ReportVersion['status']),
      generatedAt: current
        ? report.generatedAt
        : `2026-06-${String(22 + index).padStart(2, '0')} 16:00:00`,
      summary: current ? '当前复核版本，等待签发或归档。' : '历史草稿版本，已被后续复核内容替换。'
    }
  })

  return {
    report,
    sections: [
      {
        key: 'cover',
        title: '报告基本信息',
        content: `${report.title}，报告编号 ${report.reportNo}，版本 ${report.versionNo}，当前状态 ${report.status}。`,
        evidenceLinkIds: []
      },
      {
        key: 'scope',
        title: '监督检验范围',
        content: `本报告覆盖 ${nodes.map((node) => `${node.nodeId}-${node.name}`).join('、')}。`,
        evidenceLinkIds: []
      },
      {
        key: 'review',
        title: '资料审查结论',
        content: '已按节点必传资料、AI 审查结果、人工审查意见和证据链定位记录完成复核。',
        evidenceLinkIds: reportEvidence.slice(0, 3).map((link) => link.id)
      },
      {
        key: 'evidence',
        title: '证据链引用',
        content: `报告引用 ${reportEvidence.length} 条证据定位记录，可追溯到文件、页码、字段或知识条款。`,
        evidenceLinkIds: reportEvidence.map((link) => link.id)
      }
    ],
    evidenceLinks: reportEvidence,
    reviewTrail,
    versionHistory
  }
}

const makeExportTask = (
  projectId: string,
  payload: {
    id?: string
    exportType: ExportTask['exportType']
    status?: ExportTask['status']
    progress?: number
    fileName: string
    downloadUrl?: string
    fileSize?: number
    finishedAt?: string
    expiresAt?: string
    errorMessage?: string
  }
) => {
  const task: ExportTask = {
    id: payload.id || `EXP-${Date.now()}-${state.exportTasks.length + 1}`,
    projectId,
    exportType: payload.exportType,
    status: payload.status || '可下载',
    progress: payload.progress ?? 100,
    fileName: payload.fileName,
    fileSize: payload.fileSize || 1024 * 1024,
    downloadUrl: payload.downloadUrl,
    createdAt: serverTime,
    finishedAt:
      payload.finishedAt ??
      (payload.status === '排队中' || payload.status === '生成中' ? undefined : serverTime),
    expiresAt: payload.expiresAt || '2026-06-27 10:30:00',
    errorMessage: payload.errorMessage
  }
  state.exportTasks.unshift(task)
  return task
}

const buildArchiveItemDetail = (projectId: string, item: ArchiveItem) => {
  const report =
    item.type === 'report'
      ? state.reports.find(
          (report) =>
            report.projectId === projectId &&
            (item.id.includes(report.id) || item.name.includes(report.reportNo))
        )
      : undefined
  const document =
    item.type === 'document'
      ? state.documents.find(
          (document) => document.projectId === projectId && item.name.includes(document.fileName)
        )
      : undefined
  const evidenceLinks = item.nodeId ? getEvidenceForNode(item.nodeId) : []
  const relatedExportTasks = state.exportTasks.filter((task) => {
    if (task.projectId !== projectId) return false
    if (task.downloadUrl && item.downloadUrl && task.downloadUrl === item.downloadUrl) return true
    return task.fileName === item.name
  })
  return {
    item,
    report,
    document,
    evidenceLinks,
    relatedExportTasks,
    preview:
      item.type === 'report' || item.type === 'document'
        ? {
            url: `mock://preview/archive/${item.id}`,
            method: 'GET',
            expiresAt: '2026-06-26 11:30:00',
            fileName: item.name,
            previewType: item.name.endsWith('.pdf') ? 'pdf' : 'office',
            readonly: true
          }
        : undefined,
    download: item.downloadUrl
      ? {
          url: item.downloadUrl,
          method: 'GET',
          expiresAt: '2026-06-26 11:30:00',
          fileName: item.name,
          contentType: item.type === 'evidence' ? 'application/zip' : 'application/pdf',
          fileSize: item.type === 'evidence' ? 1024 * 1024 : 512 * 1024
        }
      : undefined
  }
}

const getNdtReport = (projectId: string, reportId: string) =>
  state.ndtReports.find((report) => report.projectId === projectId && report.id === reportId)

const getNdtFeedback = (projectId: string, feedbackId: string) =>
  state.ndtFeedback.find(
    (feedback) => feedback.projectId === projectId && feedback.id === feedbackId
  )

const buildNdtReportDetail = (projectId: string, report: NdtReport) => {
  const films = state.ndtFilms.filter((film) => report.relatedFilmIds.includes(film.id))
  const records = state.ndtRecords.filter(
    (record) => record.projectId === projectId && record.reportId === report.id
  )
  const feedback = state.ndtFeedback.filter(
    (item) => item.projectId === projectId && item.relatedReportIds.includes(report.id)
  )
  return {
    report,
    films,
    records,
    document: state.documents.find((document) => document.id === report.fileId),
    feedback
  }
}

const buildNdtFeedbackDetail = (projectId: string, feedback: NdtFeedback) => {
  const reports = state.ndtReports.filter((report) => feedback.relatedReportIds.includes(report.id))
  const films = state.ndtFilms.filter((film) => feedback.relatedFilmIds.includes(film.id))
  const reportIds = reports.map((report) => report.id)
  const filmIds = films.map((film) => film.id)
  const records = state.ndtRecords.filter(
    (record) =>
      record.projectId === projectId &&
      ((record.reportId && reportIds.includes(record.reportId)) ||
        (record.filmId && filmIds.includes(record.filmId)))
  )
  return {
    feedback,
    reports,
    films,
    records,
    evidenceLinks: getEvidenceForNode(feedback.nodeId),
    timeline: [
      {
        title: '监检反馈创建',
        actorName: '张工',
        status: feedback.status,
        createdAt: feedback.createdAt,
        comment: feedback.description
      },
      {
        title: feedback.status === '已反馈' ? '补正资料已提交' : '等待无损检测补正',
        actorName: feedback.status === '已反馈' ? '王工' : '系统',
        status: feedback.status,
        createdAt: feedback.status === '已反馈' ? serverTime : feedback.deadline || serverTime,
        comment:
          feedback.status === '已反馈'
            ? '相关底片、检测记录和报告已重新提交。'
            : '需在期限前补齐底片包索引和检测记录页码。'
      }
    ]
  }
}

const getRoleTodos = (role: RoleCode, projectId?: string) =>
  state.todos.filter((todo) => {
    if (projectId && todo.projectId !== projectId) return false
    if (todo.status === '已完成' || todo.status === '已关闭') return false
    if (role === 'contractor') return todo.assigneeName === '李工'
    if (role === 'ndt') return todo.assigneeName === '王工'
    if (role === 'inspection') return todo.assigneeName === '张工'
    return true
  })

const parseBool = (value: unknown) => {
  if (value === true || value === 'true') return true
  if (value === false || value === 'false') return false
  return undefined
}

const makePage = <T>(items: T[], page = 1, pageSize = 20) => ({
  items: items.slice((page - 1) * pageSize, page * pageSize),
  page,
  pageSize,
  total: items.length
})

const getSubmissionNodes = (projectId: string, nodeIds: number[]) =>
  nodeIds.map((nodeId) => getNode(projectId, nodeId))

const getSubmissionBindings = (projectId: string, bindingIds: string[]) =>
  state.bindings.filter((binding) => {
    if (binding.projectId !== projectId) return false
    return bindingIds.length ? bindingIds.includes(binding.id) : true
  })

const resolveSubmissionBindingIds = (
  projectId: string,
  nodeIds: number[],
  bindingIds: unknown[]
) => {
  const selectedBindingIds = bindingIds.map(String).filter(Boolean)
  if (selectedBindingIds.length) return selectedBindingIds
  return state.bindings
    .filter((binding) => binding.projectId === projectId && nodeIds.includes(binding.nodeId))
    .map((binding) => binding.id)
}

const getSubmissionNodeNames = (projectId: string, nodeIds: number[]) =>
  getSubmissionNodes(projectId, nodeIds).map((node) => `${node.nodeId} ${node.name}`)

const buildSubmissionHistory = (projectId: string) => ({
  drafts: state.submissionDrafts
    .filter((draft) => draft.projectId === projectId)
    .map((draft) => ({
      draftId: draft.draftId,
      projectId: draft.projectId,
      nodeIds: draft.nodeIds,
      nodeNames: getSubmissionNodeNames(draft.projectId, draft.nodeIds),
      bindingCount: draft.bindingIds.length,
      batchName: draft.batchName,
      remark: draft.remark,
      savedAt: draft.savedAt
    })),
  submissions: state.submissionSnapshots
    .filter((snapshot) => snapshot.projectId === projectId)
    .map((snapshot) => ({
      submissionId: snapshot.submissionId,
      snapshotId: snapshot.snapshotId,
      projectId: snapshot.projectId,
      nodeIds: snapshot.nodeIds,
      nodeNames: getSubmissionNodeNames(snapshot.projectId, snapshot.nodeIds),
      bindingCount: snapshot.bindingIds.length,
      todoCount: snapshot.createdTodoIds.length,
      batchName: snapshot.batchName,
      submitterComment: snapshot.submitterComment,
      nextStatus: snapshot.nextStatus,
      withdrawal: snapshot.withdrawal,
      submittedAt: snapshot.submittedAt
    }))
})

const buildSubmissionDraftDetail = (draft: SubmissionDraftMock) => ({
  ...draft,
  nodes: getSubmissionNodes(draft.projectId, draft.nodeIds),
  bindings: getSubmissionBindings(draft.projectId, draft.bindingIds)
})

const buildSubmissionDetail = (snapshot: SubmissionSnapshotMock) => ({
  ...snapshot,
  nodes: getSubmissionNodes(snapshot.projectId, snapshot.nodeIds),
  bindings: getSubmissionBindings(snapshot.projectId, snapshot.bindingIds),
  createdTodos: state.todos.filter((todo) => snapshot.createdTodoIds.includes(todo.id))
})

const getKnowledgeFile = (fileId: string) => state.knowledgeFiles.find((file) => file.id === fileId)

const getKnowledgeSource = (sourceId: string) =>
  state.knowledgeSources.find((source) => source.id === sourceId)

const knowledgeSourceTypes: KnowledgeSourceMock['sourceType'][] = [
  'standard',
  'project-file',
  'rule',
  'manual'
]

const getKnowledgeRuleVersion = (versionId: string) =>
  state.knowledgeRuleVersions.find((rule) => rule.id === versionId)

const isEmptyDiffValue = (value: unknown) =>
  value === undefined ||
  value === null ||
  value === '' ||
  (Array.isArray(value) && value.length === 0)

const isSameDiffValue = (before: unknown, after: unknown) =>
  JSON.stringify(before ?? null) === JSON.stringify(after ?? null)

const resolveKnowledgeRuleDiffTarget = (
  base: KnowledgeRuleVersionMock,
  targetVersionId?: string,
  targetVersion?: string
) => {
  const requested = [targetVersionId, targetVersion].filter(Boolean)
  if (requested.length) {
    const target = state.knowledgeRuleVersions.find(
      (item) =>
        item.ruleKey === base.ruleKey &&
        item.id !== base.id &&
        requested.some((value) => item.id === value || item.version === value)
    )
    if (target) return target
  }
  return (
    state.knowledgeRuleVersions.find(
      (item) => item.ruleKey === base.ruleKey && item.id !== base.id && item.status === '已发布'
    ) ||
    state.knowledgeRuleVersions.find((item) => item.ruleKey === base.ruleKey && item.id !== base.id)
  )
}

const buildKnowledgeRuleVersionDiff = (
  versionId: string,
  targetVersionId?: string,
  targetVersion?: string
): KnowledgeRuleVersionDiffMock | undefined => {
  const base = getKnowledgeRuleVersion(versionId)
  if (!base) return undefined
  const target = resolveKnowledgeRuleDiffTarget(base, targetVersionId, targetVersion)
  if (!target) return undefined

  const changes: KnowledgeRuleVersionDiffChangeMock[] = []
  const pushChange = (
    field: KnowledgeRuleVersionDiffChangeMock['field'],
    label: string,
    before: unknown,
    after: unknown,
    severity: KnowledgeRuleVersionDiffChangeMock['severity'] = 'info'
  ) => {
    if (isSameDiffValue(before, after)) return
    const changeType: KnowledgeRuleVersionDiffChangeMock['changeType'] = isEmptyDiffValue(before)
      ? 'added'
      : isEmptyDiffValue(after)
        ? 'removed'
        : 'changed'
    changes.push({ field, label, before, after, severity, changeType })
  }

  pushChange('version', '规则版本', target.version, base.version)
  pushChange('status', '发布状态', target.status, base.status, 'warning')
  pushChange('nodes', '节点范围', target.nodeIds, base.nodeIds, 'warning')
  pushChange('prompt', 'Prompt 版本', target.promptVersion, base.promptVersion, 'warning')
  pushChange(
    'schema',
    '输出结构版本',
    target.outputSchemaVersion,
    base.outputSchemaVersion,
    'warning'
  )
  pushChange('description', '规则说明', target.description, base.description)

  return {
    base,
    target,
    comparedAt: serverTime,
    summary: {
      added: changes.filter((item) => item.changeType === 'added').length,
      changed: changes.filter((item) => item.changeType === 'changed').length,
      removed: changes.filter((item) => item.changeType === 'removed').length,
      warning: changes.filter((item) => item.severity === 'warning').length
    },
    changes
  }
}

const makeKnowledgeMutation = (
  action: string,
  objectType: string,
  objectId: string,
  changed: Array<{ field: string; before?: unknown; after: unknown }> = []
) => {
  const auditLogId = addAuditLog(action, objectType, objectId)
  return {
    id: `MUT-${Date.now()}`,
    objectType,
    objectId,
    changed,
    auditLogId
  }
}

const getKnowledgeAuditLogs = () =>
  state.auditLogs.filter((log) =>
    [
      'KnowledgeSource',
      'KnowledgeTask',
      'KnowledgeConfig',
      'RuleVersion',
      'LlmCompareRun'
    ].includes(log.objectType)
  )

const buildKnowledgeOverview = () => {
  const failedTasks = state.knowledgeTasks.filter((task) => task.status === '失败').length
  const projectFiles = state.knowledgeFiles.filter((file) => file.sourceId === 'KS-PROJECT-FILE')
  const vectorCount = projectFiles.reduce((sum, file) => sum + file.vectorCount, 0)
  const chunkCount = projectFiles.reduce((sum, file) => sum + file.chunkCount, 0)
  const vectorRate = chunkCount ? Math.round((vectorCount / chunkCount) * 100) : 0
  return {
    metrics: [
      {
        key: 'standard',
        label: '标准规范',
        value: state.knowledgeSources
          .filter((source) => source.sourceType === 'standard')
          .reduce((sum, source) => sum + source.fileCount, 0),
        tone: 'green'
      },
      { key: 'projectFile', label: '项目文件', value: projectFiles.length, tone: 'blue' },
      {
        key: 'taskFailed',
        label: '失败任务',
        value: failedTasks,
        tone: failedTasks ? 'red' : 'gray'
      },
      { key: 'vectorRate', label: '向量化完成率', value: `${vectorRate}%`, tone: 'orange' }
    ],
    libraries: state.knowledgeSources.map((source) => ({
      key: source.id,
      name: source.name,
      fileCount: source.fileCount,
      chunkCount: source.chunkCount,
      vectorCount:
        source.sourceType === 'project-file'
          ? vectorCount
          : source.vectorStatus === '已向量化'
            ? source.chunkCount
            : Math.round(source.chunkCount * 0.72),
      indexVersion: source.version || 'manual-v1',
      status:
        source.vectorStatus === '已向量化'
          ? '健康'
          : source.vectorStatus === '向量化中'
            ? '索引中'
            : source.vectorStatus === '向量化失败'
              ? '失败'
              : source.status,
      updatedAt: source.updatedAt
    }))
  }
}

const makeKnowledgeTask = (
  payload: Pick<KnowledgeTaskMock, 'taskType' | 'targetType' | 'targetId' | 'targetName'> &
    Partial<Pick<KnowledgeTaskMock, 'status' | 'progress' | 'errorMessage'>>
) => {
  const task: KnowledgeTaskMock = {
    id: `KT-${Date.now()}-${state.knowledgeTasks.length + 1}`,
    status: payload.status || '排队中',
    progress: payload.progress ?? 0,
    createdAt: serverTime,
    actions: ['knowledge:task-retry'],
    ...payload
  }
  state.knowledgeTasks.unshift(task)
  addAuditLog('创建知识库任务', 'KnowledgeTask', task.id)
  return task
}

const getKnowledgeChunks = (file: KnowledgeFileMock) =>
  Array.from({ length: file.chunkCount }).map((_, index) => {
    const evidence = evidenceLinks[index % evidenceLinks.length]
    return {
      id: `${file.id}-CHUNK-${String(index + 1).padStart(3, '0')}`,
      chunkNo: index + 1,
      text:
        index % 3 === 0
          ? `${file.fileName} 第 ${index + 1} 个切片：提取项目、节点、证书编号、检测结论等结构化上下文。`
          : index % 3 === 1
            ? `${file.fileName} 第 ${index + 1} 个切片：用于规则匹配、证据定位和审查意见草稿生成。`
            : `${file.fileName} 第 ${index + 1} 个切片：保留页码、字段和引用关系，便于追溯。`,
      pageNo: (index % 4) + 1,
      evidenceLinkId: evidence?.id,
      tokenCount: 180 + index * 12
    }
  })

const getKnowledgeReasoningReferences = (file: KnowledgeFileMock) =>
  state.aiRuns
    .filter(
      (run) =>
        !file.nodeId ||
        run.nodeId === file.nodeId ||
        run.evidenceLinks.some((link) => link.objectId === file.documentVersionId)
    )
    .map((run) => ({
      runId: run.id,
      nodeId: run.nodeId,
      subject: run.subject,
      model: run.model,
      quotedText: run.evidenceLinks[0]?.quotedText || run.suggestion.opinionDraft,
      createdAt: run.finishedAt || serverTime
    }))

const getKnowledgeVectorSummary = (file: KnowledgeFileMock) => ({
  vectorStatus: file.vectorStatus,
  vectorCount: file.vectorCount,
  indexVersion: getKnowledgeSource(file.sourceId)?.version || 'proj-v2026.06.26',
  dimensions: 1536,
  updatedAt: file.updatedAt
})

const getLlmComparePayload = (run: LlmCompareRunMock) => ({
  runId: run.runId,
  question: run.question,
  createdAt: run.createdAt,
  results: run.results
})

const getProjectMembers = (id: string) =>
  state.projectMembers.filter((member) => member.projectId === id)

const getAdminUserSnapshot = (userId: string, role: RoleCode) => {
  const user = state.adminUsers.find((item) => item.id === userId)
  if (user) return { name: user.name, orgName: user.orgName }
  const fallback = {
    name:
      role === 'inspection'
        ? '张工'
        : role === 'contractor'
          ? '李工'
          : role === 'ndt'
            ? '王工'
            : '陈总',
    orgName:
      role === 'inspection'
        ? '省特检院一部'
        : role === 'contractor'
          ? '中石化安装有限公司'
          : role === 'ndt'
            ? '华测检测有限公司'
            : '华东管网建设公司'
  }
  const map: Record<string, { name: string; orgName: string }> = {
    'USR-INS-001': { name: '张工', orgName: '省特检院一部' },
    'USR-CON-001': { name: '李工', orgName: '中石化安装有限公司' },
    'USR-NDT-001': { name: '王工', orgName: '华测检测有限公司' },
    'USR-OWN-001': { name: '陈总', orgName: '华东管网建设公司' },
    'USR-ADM-001': { name: '赵管理员', orgName: '省特检院平台部' }
  }
  return map[userId] || fallback
}

const createProjectTreeNodes = (newProject: Project) =>
  treeNodes.map((node) => ({
    ...clone<ProjectTreeNode>(node),
    id: `${newProject.id}-${node.nodeId}`,
    projectId: newProject.id,
    status: '待提交' as NodeStatus,
    fileCount: 0,
    requiredProgress: {
      done: 0,
      total: node.requiredProgress.total
    },
    actions: roleActions.contractor
  }))

const createProjectInitialMembers = (
  newProject: Project,
  memberUserIds?: Partial<Record<RoleCode, string>>
) => {
  const memberConfigs: Array<{
    role: RoleCode
    userId: string
    nodeScope: number[]
  }> = [
    {
      role: 'inspection',
      userId: memberUserIds?.inspection || 'USR-INS-001',
      nodeScope: [16, 24, 40, 68]
    },
    {
      role: 'contractor',
      userId: memberUserIds?.contractor || 'USR-CON-001',
      nodeScope: [1, 16, 24, 40]
    },
    { role: 'ndt', userId: memberUserIds?.ndt || 'USR-NDT-001', nodeScope: [35, 36, 40, 41, 42] },
    {
      role: 'owner',
      userId: memberUserIds?.owner || 'USR-OWN-001',
      nodeScope: [1, 16, 24, 40, 68]
    }
  ]
  return memberConfigs.map((config) => {
    const user = getAdminUserSnapshot(config.userId, config.role)
    return {
      id: `PM-${newProject.id}-${config.role.toUpperCase()}`,
      projectId: newProject.id,
      userId: config.userId,
      name: user.name,
      orgName: user.orgName,
      role: config.role,
      nodeScope: config.nodeScope,
      actions: initialMemberActions[config.role],
      status: '启用' as const,
      updatedAt: serverTime
    }
  })
}

const getAdminConfigItem = (target: AdminConfigTargetMock, id: string) => {
  if (target === 'permission') {
    return state.adminPermissionMatrix.find((item) => item.role === id)
  }
  if (target === 'node-template') {
    return state.adminNodeTemplates.find((item) => item.id === id)
  }
  if (target === 'workflow') {
    return state.adminWorkflowStateMachines.find((item) => item.id === id)
  }
  if (target === 'todo-rule') {
    return state.adminTodoRules.find((item) => item.id === id)
  }
  if (target === 'message-template') {
    return state.adminMessageTemplates.find((item) => item.id === id)
  }
  if (target === 'tool-source') {
    return state.adminToolSources.find((item) => item.id === id)
  }
  return state.adminFieldMappings.find((item) => item.id === id)
}

const adminConfigLabels: Record<string, string> = {
  assigneeRole: '办理角色',
  authMode: '认证方式',
  channel: '渠道',
  confidenceThreshold: '置信度阈值',
  contentTemplate: '内容模板',
  deadlineHours: '办理时限',
  enabled: '启用',
  endpoint: '接口地址',
  fieldName: '字段名称',
  label: '名称',
  nodeId: '节点',
  projectScope: '项目范围',
  nodeScope: '节点范围',
  actions: '动作权限',
  readonly: '只读',
  required: '必填',
  scene: '触发场景',
  sourceField: '来源字段',
  targetField: '目标字段',
  titleTemplate: '标题模板',
  toolType: '工具类型',
  triggerStatus: '触发状态',
  version: '版本',
  groupName: '业务分组',
  nodeCount: '节点数',
  requiredCount: '资料项',
  status: '状态',
  name: '流程名称',
  states: '状态数',
  transitions: '流转数'
}

const normalizeConfigValue = (value: unknown) => (Array.isArray(value) ? value.join(',') : value)

const getAdminConfigObjectName = (target: AdminConfigTargetMock, item: unknown) => {
  if (target === 'permission') return (item as AdminPermissionMatrixMock).label
  if (target === 'node-template') return (item as AdminNodeTemplateMock).groupName
  if (target === 'workflow') return (item as AdminWorkflowMock).name
  if (target === 'todo-rule') return (item as AdminTodoRuleMock).name
  if (target === 'message-template') return (item as AdminMessageTemplateMock).scene
  if (target === 'tool-source') return (item as AdminToolSourceMock).name
  return (item as AdminFieldMappingMock).fieldName
}

const buildAdminConfigDiff = (
  target: AdminConfigTargetMock,
  id: string,
  values: Record<string, unknown>
): AdminConfigDiffMock | undefined => {
  const item = getAdminConfigItem(target, id)
  if (!item) return undefined
  const changed = Object.entries(values)
    .filter(
      ([field, after]) =>
        normalizeConfigValue((item as Record<string, unknown>)[field]) !==
        normalizeConfigValue(after)
    )
    .map(([field, after]) => ({
      field,
      label: adminConfigLabels[field] || field,
      before: (item as Record<string, unknown>)[field],
      after,
      severity: ['actions', 'readonly', 'status'].includes(field)
        ? ('warning' as const)
        : ('info' as const)
    }))
  return {
    target,
    objectId: id,
    objectName: getAdminConfigObjectName(target, item),
    previewedAt: serverTime,
    changed
  }
}

const applyAdminConfigChange = (
  target: AdminConfigTargetMock,
  id: string,
  values: Record<string, unknown>
) => {
  const item = getAdminConfigItem(target, id)
  if (!item) return undefined
  Object.entries(values).forEach(([field, value]) => {
    ;(item as Record<string, unknown>)[field] = value
  })
  if ('updatedAt' in item) item.updatedAt = serverTime
  return item
}

const makeAdminConfigId = (target: AdminConfigTargetMock) => {
  const prefixMap: Record<AdminConfigTargetMock, string> = {
    permission: 'PERM',
    'node-template': 'TPL',
    workflow: 'WF',
    'todo-rule': 'TODO-RULE',
    'message-template': 'MSG-TPL',
    'tool-source': 'TOOL',
    'field-mapping': 'FM'
  }
  return `${prefixMap[target]}-${Date.now()}`
}

const createAdminConfigItem = (target: AdminConfigTargetMock, values: Record<string, unknown>) => {
  const id = String(values.id || makeAdminConfigId(target))
  if (target === 'todo-rule') {
    const item: AdminTodoRuleMock = {
      id,
      name: String(values.name || '新待办规则'),
      triggerStatus: String(values.triggerStatus || '待处理'),
      assigneeRole: (values.assigneeRole as RoleCode) || 'inspection',
      deadlineHours: Number(values.deadlineHours) || 48,
      enabled: values.enabled !== false,
      updatedAt: serverTime
    }
    state.adminTodoRules.unshift(item)
    return item
  }
  if (target === 'message-template') {
    const item: AdminMessageTemplateMock = {
      id,
      scene: String(values.scene || 'custom-scene'),
      channel: (values.channel as AdminMessageTemplateMock['channel']) || '站内信',
      titleTemplate: String(values.titleTemplate || '新消息模板'),
      contentTemplate: String(values.contentTemplate || '{{projectName}} 有新的业务消息。'),
      enabled: values.enabled !== false,
      updatedAt: serverTime
    }
    state.adminMessageTemplates.unshift(item)
    return item
  }
  if (target === 'tool-source') {
    const item: AdminToolSourceMock = {
      id,
      name: String(values.name || '新工具源'),
      toolType: (values.toolType as AdminToolSourceMock['toolType']) || 'external-query',
      endpoint: String(values.endpoint || 'mock://tool-source/custom'),
      authMode: (values.authMode as AdminToolSourceMock['authMode']) || 'none',
      status: (values.status as AdminToolSourceMock['status']) || '启用',
      updatedAt: serverTime
    }
    state.adminToolSources.unshift(item)
    return item
  }
  if (target === 'field-mapping') {
    const item: AdminFieldMappingMock = {
      id,
      nodeId: Number(values.nodeId) || 1,
      fieldName: String(values.fieldName || '新字段'),
      sourceField: String(values.sourceField || 'ocr.custom.field'),
      targetField: String(values.targetField || 'review.custom.field'),
      required: values.required !== false,
      confidenceThreshold: Number(values.confidenceThreshold) || 0.85,
      updatedAt: serverTime
    }
    state.adminFieldMappings.unshift(item)
    return item
  }
  return undefined
}

const getAdminConfigCollection = (target: AdminConfigTargetMock) => {
  if (target === 'todo-rule') return state.adminTodoRules
  if (target === 'message-template') return state.adminMessageTemplates
  if (target === 'tool-source') return state.adminToolSources
  if (target === 'field-mapping') return state.adminFieldMappings
  return []
}

const adminResourceToTarget = (resource?: string): AdminConfigTargetMock | undefined => {
  const map: Record<string, AdminConfigTargetMock> = {
    'todo-rules': 'todo-rule',
    'message-templates': 'message-template',
    'tool-sources': 'tool-source',
    'field-mappings': 'field-mapping'
  }
  return resource ? map[resource] : undefined
}

const buildAdminCreateDiff = (
  target: AdminConfigTargetMock,
  item: Record<string, unknown>
): AdminConfigDiffMock => ({
  target,
  objectId: String(item.id || ''),
  objectName: getAdminConfigObjectName(target, item),
  previewedAt: serverTime,
  changed: Object.entries(item)
    .filter(([field]) => field !== 'updatedAt')
    .map(([field, after]) => ({
      field,
      label: adminConfigLabels[field] || field,
      before: undefined,
      after,
      severity: ['enabled', 'status', 'required'].includes(field) ? 'warning' : 'info'
    }))
})

const buildAdminProjectDetail = (id: string) => {
  const project = getProject(id)
  const groups = getProjectGroups(project.id).map((group) => {
    const total = group.nodes.length
    const passed = group.nodes.filter((node) => node.status === '已通过').length
    const correction = group.nodes.filter((node) =>
      ['需补正', '补正中', '复审中'].includes(node.status)
    ).length
    return {
      groupName: group.groupName,
      total,
      passed,
      correction,
      pending: total - passed - correction
    }
  })
  return {
    project,
    members: getProjectMembers(project.id),
    participantUnits: [
      {
        unitType: 'owner',
        unitName: project.ownerOrgName,
        contactName: '陈总',
        contactPhone: '13800010001'
      },
      {
        unitType: 'contractor',
        unitName: project.contractorOrgName,
        contactName: '李工',
        contactPhone: '13800010002'
      },
      {
        unitType: 'ndt',
        unitName: project.ndtOrgName,
        contactName: '王工',
        contactPhone: '13800010003'
      },
      {
        unitType: 'inspection',
        unitName: project.inspectionOrgName,
        contactName: '张工',
        contactPhone: '13800010004'
      }
    ],
    nodeSummary: groups,
    recentExportTasks: state.exportTasks.filter((task) => task.projectId === project.id).slice(0, 6)
  }
}

const buildAdminOrgUnits = (): AdminOrgUnitMock[] => {
  const configs: Array<{
    type: AdminOrgUnitMock['type']
    field: keyof Pick<
      Project,
      'ownerOrgName' | 'contractorOrgName' | 'ndtOrgName' | 'inspectionOrgName'
    >
    contactName: string
    contactPhone: string
  }> = [
    {
      type: 'owner',
      field: 'ownerOrgName',
      contactName: '陈总',
      contactPhone: '13800010001'
    },
    {
      type: 'contractor',
      field: 'contractorOrgName',
      contactName: '李工',
      contactPhone: '13800010002'
    },
    {
      type: 'ndt',
      field: 'ndtOrgName',
      contactName: '王工',
      contactPhone: '13800010003'
    },
    {
      type: 'inspection',
      field: 'inspectionOrgName',
      contactName: '张工',
      contactPhone: '13800010004'
    }
  ]
  return configs.flatMap((config) =>
    Array.from(new Set(state.projects.map((project) => project[config.field]))).map(
      (name, index) => ({
        id: `ORG-${config.type.toUpperCase()}-${String(index + 1).padStart(3, '0')}`,
        name,
        type: config.type,
        contactName: config.contactName,
        contactPhone: config.contactPhone,
        status: '启用',
        projectCount: state.projects.filter((project) => project[config.field] === name).length
      })
    )
  )
}

const buildAdminConfigOverview = () => {
  const activeProjects = state.projects.filter((project) => project.status !== '已归档')
  const orgUnits = buildAdminOrgUnits()
  const ruleVersions = state.knowledgeRuleVersions.map((rule) => ({
    id: rule.id,
    name: rule.name,
    ruleKey: rule.ruleKey,
    version: rule.version,
    status: rule.status,
    nodeIds: rule.nodeIds,
    promptVersion: rule.promptVersion,
    outputSchemaVersion: rule.outputSchemaVersion,
    description: rule.description,
    publishedAt: rule.publishedAt,
    updatedAt: rule.updatedAt,
    actions: rule.actions
  }))
  return {
    metrics: [
      { key: 'project', label: '项目总数', value: state.projects.length, tone: 'blue' },
      { key: 'activeProject', label: '在检项目', value: activeProjects.length, tone: 'green' },
      { key: 'org', label: '参建组织', value: orgUnits.length, tone: 'orange' },
      {
        key: 'rulePending',
        label: '待发布规则',
        value: ruleVersions.filter((rule) => rule.status === '待发布').length,
        tone: ruleVersions.some((rule) => rule.status === '待发布') ? 'red' : 'gray'
      }
    ],
    orgUnits,
    users: state.adminUsers,
    permissionMatrix: state.adminPermissionMatrix,
    nodeTemplates: state.adminNodeTemplates,
    ruleVersions,
    workflowStateMachines: state.adminWorkflowStateMachines,
    todoRules: state.adminTodoRules,
    messageTemplates: state.adminMessageTemplates,
    toolSources: state.adminToolSources,
    fieldMappings: state.adminFieldMappings
  }
}

const integrationModuleLabels: Record<IntegrationContractModuleMock, string> = {
  workbench: '工作台首屏',
  documents: '文件与预览',
  submissions: '提交与补正',
  inspection: '监检审查',
  'ndt-owner-report': '无损/建设方/报告',
  'knowledge-admin': '知识库与后台'
}

const initialIntegrationContractFields: IntegrationContractFieldMock[] = [
  {
    id: 'IC-WB-001',
    module: 'workbench',
    moduleLabel: integrationModuleLabels.workbench,
    endpoint: '/api/workbench/context',
    method: 'GET',
    frontendField: 'actions',
    backendField: 'permissions.actions',
    required: true,
    status: '命名不一致',
    severity: 'warning',
    owner: '前后端共同',
    note: '前端统一使用 actions，后端合同建议确认 permissions.actions 是否需要映射。',
    updatedAt: serverTime
  },
  {
    id: 'IC-WB-002',
    module: 'workbench',
    moduleLabel: integrationModuleLabels.workbench,
    endpoint: '/api/projects/{projectId}/tree',
    method: 'GET',
    frontendField: 'requiredProgress.done',
    backendField: 'requiredProgress.completed',
    required: true,
    status: '待后端确认',
    severity: 'warning',
    owner: '后端',
    note: '节点树进度字段需要确认 done/completed 命名。',
    updatedAt: serverTime
  },
  {
    id: 'IC-DOC-001',
    module: 'documents',
    moduleLabel: integrationModuleLabels.documents,
    endpoint: '/api/projects/{projectId}/documents/upload-session',
    method: 'POST',
    frontendField: 'files[].fileType',
    backendField: 'files[].mimeType',
    required: true,
    status: '命名不一致',
    severity: 'warning',
    owner: '前后端共同',
    note: '真实上传协议建议使用 MIME，前端当前 mock 使用扩展名。',
    updatedAt: serverTime
  },
  {
    id: 'IC-DOC-002',
    module: 'documents',
    moduleLabel: integrationModuleLabels.documents,
    endpoint: '/api/projects/{projectId}/documents/{documentId}/preview',
    method: 'GET',
    frontendField: 'preview.previewType',
    backendField: 'previewType',
    required: true,
    status: '已对齐',
    severity: 'info',
    owner: '前端',
    note: '预览类型已覆盖 pdf/office/image/unsupported。',
    updatedAt: serverTime
  },
  {
    id: 'IC-SUB-001',
    module: 'submissions',
    moduleLabel: integrationModuleLabels.submissions,
    endpoint: '/api/projects/{projectId}/submissions',
    method: 'GET',
    frontendField: 'drafts[].nodeNames',
    backendField: 'drafts[].nodeNames',
    required: true,
    status: '已对齐',
    severity: 'info',
    owner: '后端',
    note: '提交草稿和提交批次摘要均已返回节点名称。',
    updatedAt: serverTime
  },
  {
    id: 'IC-SUB-002',
    module: 'submissions',
    moduleLabel: integrationModuleLabels.submissions,
    endpoint: '/api/projects/{projectId}/submissions',
    method: 'POST',
    frontendField: 'nodeIds',
    backendField: 'nodeIds',
    required: true,
    status: '已对齐',
    severity: 'info',
    owner: '前后端共同',
    note: '跨节点范围提交已纳入 E2E。',
    updatedAt: serverTime
  },
  {
    id: 'IC-INS-001',
    module: 'inspection',
    moduleLabel: integrationModuleLabels.inspection,
    endpoint: '/api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions',
    method: 'POST',
    frontendField: 'riskLevel',
    backendField: 'riskLevel',
    required: true,
    status: '已对齐',
    severity: 'info',
    owner: '前后端共同',
    note: '审查意见保存已返回风险等级，前端保留风险等级字段展示和合同校验。',
    updatedAt: serverTime
  },
  {
    id: 'IC-INS-002',
    module: 'inspection',
    moduleLabel: integrationModuleLabels.inspection,
    endpoint: '/api/projects/{projectId}/inspection/reports/{reportId}/archive',
    method: 'POST',
    frontendField: 'If-Match',
    backendField: 'If-Match',
    required: true,
    status: '待后端确认',
    severity: 'warning',
    owner: '前后端共同',
    note: '归档并发版本头已在合同中定义，mock 仍以 query/body 模拟。',
    updatedAt: serverTime
  },
  {
    id: 'IC-NDT-001',
    module: 'ndt-owner-report',
    moduleLabel: integrationModuleLabels['ndt-owner-report'],
    endpoint: '/api/projects/{projectId}/ndt/records/import',
    method: 'POST',
    frontendField: 'records[].filmId',
    backendField: 'records[].filmId',
    required: false,
    status: '已对齐',
    severity: 'info',
    owner: '无损检测',
    note: '检测记录导入、报告提交已纳入 E2E。',
    updatedAt: serverTime
  },
  {
    id: 'IC-ADM-001',
    module: 'knowledge-admin',
    moduleLabel: integrationModuleLabels['knowledge-admin'],
    endpoint: '/api/admin/config-items/{target}/{id}',
    method: 'PUT',
    frontendField: 'reason',
    backendField: 'reason',
    required: true,
    status: '已对齐',
    severity: 'info',
    owner: '管理后台',
    note: '配置保存、差异预览和审计 reason 已覆盖。',
    updatedAt: serverTime
  },
  {
    id: 'IC-KB-001',
    module: 'knowledge-admin',
    moduleLabel: integrationModuleLabels['knowledge-admin'],
    endpoint: '/api/knowledge/retrieval-test',
    method: 'POST',
    frontendField: 'topK',
    backendField: 'topK',
    required: false,
    status: '待后端确认',
    severity: 'warning',
    owner: 'AI 知识库',
    note: '检索测试当前以知识库配置默认值为主，真实接口需确认是否允许单次覆盖。',
    updatedAt: serverTime
  }
]

const buildIntegrationContract = (query?: Record<string, unknown>) => {
  const moduleFilter = String(query?.module || 'all')
  const statusFilter = String(query?.status || 'all')
  const fields = initialIntegrationContractFields.filter((field) => {
    if (moduleFilter !== 'all' && field.module !== moduleFilter) return false
    if (statusFilter !== 'all' && field.status !== statusFilter) return false
    return true
  })
  const modules = Object.entries(integrationModuleLabels).map(([module, label]) => {
    const moduleFields = fields.filter((field) => field.module === module)
    return {
      module: module as IntegrationContractModuleMock,
      label,
      total: moduleFields.length,
      aligned: moduleFields.filter((field) => field.status === '已对齐').length,
      pending: moduleFields.filter(
        (field) => field.status === '待后端确认' || field.status === '命名不一致'
      ).length,
      blockers: moduleFields.filter((field) => field.severity === 'danger').length
    }
  })
  return {
    summary: {
      total: fields.length,
      aligned: fields.filter((field) => field.status === '已对齐').length,
      pending: fields.filter(
        (field) => field.status === '待后端确认' || field.status === '命名不一致'
      ).length,
      blockers: fields.filter((field) => field.severity === 'danger').length
    },
    modules,
    fields,
    generatedAt: serverTime
  }
}

const buildSearchResults = (keyword: string, projectId?: string): SearchResult[] => {
  const normalized = keyword.trim().toLowerCase()
  const includesKeyword = (value?: string | number) =>
    !normalized ||
    String(value || '')
      .toLowerCase()
      .includes(normalized)
  const projectResults = state.projects
    .filter(
      (project) =>
        (!projectId || project.id === projectId) &&
        includesKeyword(`${project.name}${project.code}${project.status}`)
    )
    .map<SearchResult>((project) => ({
      type: 'project',
      id: project.id,
      title: project.name,
      description: `${project.code} / ${project.status}`,
      route: `/workbench/inspection?projectId=${project.id}`,
      highlights: [project.code, project.status]
    }))
  const nodeResults = state.treeNodes
    .filter(
      (node) =>
        (!projectId || node.projectId === projectId) &&
        includesKeyword(`${node.nodeId}${node.name}${node.groupName}${node.status}`)
    )
    .slice(0, 20)
    .map<SearchResult>((node) => ({
      type: 'node',
      id: String(node.nodeId),
      title: `${node.nodeId} · ${node.name}`,
      description: `${node.groupName} / ${node.status}`,
      route: `/workbench/inspection?projectId=${node.projectId}&nodeId=${node.nodeId}`,
      highlights: [node.groupName, node.status]
    }))
  const documentResults = state.documents
    .filter(
      (document) =>
        (!projectId || document.projectId === projectId) &&
        includesKeyword(`${document.fileName}${document.sourceOrgName}${document.currentOcrStatus}`)
    )
    .map<SearchResult>((document) => ({
      type: 'document',
      id: document.id,
      title: document.fileName,
      description: `${document.sourceOrgName} / ${document.currentOcrStatus}`,
      route: `/workbench/contractor?projectId=${document.projectId}`,
      highlights: [document.sourceOrgName, document.currentOcrStatus]
    }))
  const reportResults = state.reports
    .filter(
      (report) =>
        (!projectId || report.projectId === projectId) &&
        includesKeyword(`${report.reportNo}${report.title}${report.status}`)
    )
    .map<SearchResult>((report) => ({
      type: 'report',
      id: report.id,
      title: report.reportNo,
      description: `${report.title} / ${report.status}`,
      route: `/workbench/owner?projectId=${report.projectId}`,
      highlights: [report.versionNo, report.status]
    }))
  const staticCandidates: SearchResult[] = [
    {
      type: 'standard',
      id: 'TSG-D7005-2026',
      title: '压力管道监督检验规则',
      description: '焊工持证、无损检测、耐压试验和报告归档依据。',
      route: '/knowledge/overview',
      highlights: ['TSG D7005', '监督检验']
    },
    {
      type: 'rule',
      id: 'RULE-24-WELDER',
      title: '焊工资格证 AI 审查规则',
      description: '校验证书编号、有效期、持证项目和证据链引用。',
      route: '/knowledge/overview',
      highlights: ['节点 24', 'AI 审查']
    }
  ]
  const staticResults = staticCandidates.filter((item) =>
    includesKeyword(`${item.title}${item.description}${item.highlights.join('')}`)
  )
  return [...projectResults, ...nodeResults, ...documentResults, ...reportResults, ...staticResults]
}

const getFdeProjectVersionIds = (id: string, nodeId?: number) => {
  const selectedBindings = state.bindings.filter((binding) => {
    if (binding.projectId !== id) return false
    if (nodeId && binding.nodeId !== nodeId) return false
    return true
  })
  const ids = selectedBindings.map((binding) => binding.documentVersionId).filter(Boolean)
  if (ids.length) return ids
  return state.documents
    .filter((document) => document.projectId === id)
    .map((document) => document.currentVersionId)
}

const fdeAuditDocumentTemplates = [
  {
    fileName: '管道特性表-第2版.png',
    fileType: 'png',
    requirementName: '管道特性表',
    usage: '设计资料',
    currentOcrStatus: '人工修正',
    sliceStatus: '已切片',
    vectorStatus: '已向量化',
    chunkCount: 42,
    vectorCount: 42,
    pageIndexStatus: '已构建',
    latestTaskStatus: '成功'
  },
  {
    fileName: '质量证明书-QX201903S.pdf',
    fileType: 'pdf',
    requirementName: '产品质量证明文件',
    usage: '证明材料',
    currentOcrStatus: '已识别',
    sliceStatus: '已切片',
    vectorStatus: '已向量化',
    chunkCount: 34,
    vectorCount: 31,
    pageIndexStatus: '已构建',
    latestTaskStatus: '成功'
  },
  {
    fileName: 'RT检测报告-焊口清单.pdf',
    fileType: 'pdf',
    requirementName: '无损检测报告',
    usage: '检测报告',
    currentOcrStatus: '已识别',
    sliceStatus: '已切片',
    vectorStatus: '向量化中',
    chunkCount: 28,
    vectorCount: 19,
    pageIndexStatus: '待补齐向量',
    latestTaskStatus: '运行中'
  },
  {
    fileName: '焊工资格证与外部查询截图.pdf',
    fileType: 'pdf',
    requirementName: '焊工资格证及外部查询截图',
    usage: '资质证明',
    currentOcrStatus: '已识别',
    sliceStatus: '切片中',
    vectorStatus: '待向量化',
    chunkCount: 16,
    vectorCount: 0,
    pageIndexStatus: '等待切片',
    latestTaskStatus: '排队中'
  }
] as const

const compactFdeId = (id: string) => id.replace(/[^a-zA-Z0-9]/g, '').slice(-10) || 'LOCAL'

const makeFdeProjectDocumentSeeds = (id: string) => {
  const project = getProject(id)
  const key = compactFdeId(id)
  return fdeAuditDocumentTemplates.map((template, index) => ({
    id: `FDE-DOC-${key}-${index + 1}`,
    projectId: id,
    fileName: template.fileName,
    fileType: template.fileType,
    sourceOrgName: index === 2 ? project.ndtOrgName : project.contractorOrgName,
    uploaderName: index === 2 ? 'NDT 王工' : '施工方 李工',
    currentVersionId: `FDE-DV-${key}-${index + 1}-V${index === 0 ? 2 : 1}`,
    fileStatus: '已上传',
    currentOcrStatus: template.currentOcrStatus,
    updatedAt: `2026-06-26 ${String(9 + index).padStart(2, '0')}:1${index}:00`,
    actions: ['file:view', 'file:bind', 'file:preview', 'file:download'] as ActionCode[]
  }))
}

const getMockPageIndexNodes = (id: string, documentVersionId?: string) => {
  const project = getProject(id)
  const docSuffix = documentVersionId ? documentVersionId.slice(-2) : '00'
  return [
    {
      pageIndexNodeId: `PIN-${id}-${docSuffix}-01`,
      nodeId: `PI-${docSuffix}-01`,
      title: '资料完整性与字段要求',
      summary: '定位资料目录、必填字段、证书编号、日期和签章要求。',
      businessPackId: project.businessPackId || 'engineering_inspection_v1',
      startPage: 1,
      endPage: 2,
      sectionPath: ['工程监检业务包', '资料审查', '完整性要求'],
      linkedClauseIds: ['CLAUSE-QC-5.3.2', 'CLAUSE-DOC-2.1.1'],
      score: 0.92
    },
    {
      pageIndexNodeId: `PIN-${id}-${docSuffix}-02`,
      nodeId: `PI-${docSuffix}-02`,
      title: '印章、资质和有效期核验',
      summary: '定位单位印章、人员资质、证书有效期和外部查询截图。',
      businessPackId: project.businessPackId || 'engineering_inspection_v1',
      startPage: 2,
      endPage: 4,
      sectionPath: ['工程监检业务包', '证据链', '签章与资质'],
      linkedClauseIds: ['CLAUSE-SEAL-4.2.1', 'CLAUSE-WELDER-6.1.3'],
      score: 0.88
    },
    {
      pageIndexNodeId: `PIN-${id}-${docSuffix}-03`,
      nodeId: `PI-${docSuffix}-03`,
      title: '跨文件一致性与证据回放',
      summary: '串联设计资料、质量证明书、NDT 报告和焊工资格证，定位跨资料矛盾。',
      businessPackId: project.businessPackId || 'engineering_inspection_v1',
      startPage: 4,
      endPage: 7,
      sectionPath: ['工程监检业务包', '跨文件一致性', '证据回放'],
      linkedClauseIds: ['CLAUSE-CROSS-7.2.4', 'CLAUSE-EVIDENCE-3.3.1'],
      score: 0.86
    },
    {
      pageIndexNodeId: `PIN-${id}-${docSuffix}-04`,
      nodeId: `PI-${docSuffix}-04`,
      title: 'PageIndex 路由诊断与回退依据',
      summary: '记录长文档检索为何触发 PageIndex，以及 Hybrid RAG 回退命中的条款。',
      businessPackId: project.businessPackId || 'engineering_inspection_v1',
      startPage: 8,
      endPage: 9,
      sectionPath: ['FDE 审计手册', 'PageIndex 路由', '质量门禁'],
      linkedClauseIds: ['CLAUSE-ROUTER-1.1.0', 'CLAUSE-RAG-2.4.2'],
      score: 0.81
    }
  ]
}

const getFdeProjectDocuments = (id: string) => {
  const sourceDocuments = state.documents.filter((document) => document.projectId === id)
  const documentsForAudit =
    sourceDocuments.length >= 3 ? sourceDocuments : makeFdeProjectDocumentSeeds(id)
  return documentsForAudit.map((document, index) => {
    const template = fdeAuditDocumentTemplates[index % fdeAuditDocumentTemplates.length]
    const knowledgeFile = state.knowledgeFiles.find(
      (file) => file.documentVersionId === document.currentVersionId
    )
    const knowledgeSource = knowledgeFile ? getKnowledgeSource(knowledgeFile.sourceId) : undefined
    const latestTask = knowledgeFile
      ? state.knowledgeTasks.find((task) => task.targetId === knowledgeFile.id)
      : undefined
    const pageIndexNodes = getMockPageIndexNodes(id, document.currentVersionId)
    return {
      ...document,
      knowledgeFileId: knowledgeFile?.id,
      knowledgeSourceId: knowledgeFile?.sourceId,
      knowledgeSourceName: knowledgeFile?.sourceName || knowledgeSource?.name,
      sliceStatus:
        knowledgeFile?.sliceStatus ||
        template.sliceStatus ||
        (document.currentOcrStatus === '已识别' ? '已切片' : '等待OCR'),
      vectorStatus:
        knowledgeFile?.vectorStatus ||
        template.vectorStatus ||
        (document.currentOcrStatus === '已识别' ? '已向量化' : '待向量化'),
      chunkCount: knowledgeFile?.chunkCount || template.chunkCount || [42, 34, 28, 16][index] || 8,
      vectorCount:
        knowledgeFile?.vectorCount || template.vectorCount || [42, 31, 19, 0][index] || 0,
      embeddingModel: state.knowledgeConfig.embeddingModel,
      indexVersion: knowledgeSource?.version || 'proj-v2026.06.26',
      vectorDimensions: 3072,
      pageIndexStatus: template.pageIndexStatus || (pageIndexNodes.length ? '已构建' : '待构建'),
      pageIndexNodeCount: template.pageIndexStatus === '等待切片' ? 0 : pageIndexNodes.length,
      latestKnowledgeTask: latestTask || null,
      latestTask:
        latestTask?.status || template.latestTaskStatus || knowledgeFile?.vectorStatus || '已向量化'
    }
  })
}

const buildMockFdeAiRuns = (id?: string, nodeId?: number) =>
  state.aiRuns
    .filter((run) => {
      if (id && run.projectId !== id) return false
      if (nodeId && run.nodeId !== nodeId) return false
      return true
    })
    .map((run) => ({
      ...run,
      immutable: true,
      rawAccess: false,
      runType: 'production',
      inputHash: `sha256:${run.id.toLowerCase()}-input`,
      outputHash: `sha256:${run.id.toLowerCase()}-output`,
      versionSnapshot: {
        businessPackVersion: 'engineering_inspection_v1@2026.06',
        agentVersion: 'compliance_review_agent@1.4.0',
        promptVersion: run.promptVersion,
        modelRouteVersion: 'deepseek-reasoner@litellm-local',
        ruleSetVersion: run.ruleVersion,
        kbVersion: 'knowledge-index@local'
      }
    }))

const buildMockReviewRun = (
  aiRun = state.aiRuns[0],
  id = aiRun?.projectId || projectId,
  nodeId = aiRun?.nodeId || getProject(id).currentNodeId
) => {
  const reviewRunId = `RR-${String(aiRun?.id || 'LOCAL').replace('AIRUN-', '')}`
  return {
    id: reviewRunId,
    reviewRunId,
    aiRunId: aiRun?.id,
    projectId: id,
    nodeId,
    businessPackId: getProject(id).businessPackId || 'engineering_inspection_v1',
    agentId: 'compliance_review_agent',
    agentVersion: 'compliance_review_agent@1.4.0',
    promptVersion: aiRun?.promptVersion || 'review_prompt@2026.06',
    modelAlias: 'deepseek-reasoner',
    modelGateway: 'litellm',
    workflowEngine: 'temporal',
    graphEngine: 'langgraph',
    graphRunner: 'local-dev-graph-runner',
    workflowId: `wf-review-${id}-${nodeId}`,
    temporalRunId: `temporal-${reviewRunId.toLowerCase()}`,
    status: 'waiting_human_review',
    currentStep: 'waiting_human_review',
    runMode: 'production',
    inputHash: `sha256:${reviewRunId.toLowerCase()}-input`,
    outputHash: `sha256:${reviewRunId.toLowerCase()}-output`,
    graphSummary: {
      total: 8,
      statusCounts: { completed: 7, waiting_human_review: 1 }
    },
    graphExecution: {
      checkpointer: 'postgres',
      checkpointNamespace: `review:${id}:${nodeId}`,
      persistence: 'langgraph_postgres_checkpointer',
      temporalTaskQueue: 'review-orchestrator-local'
    },
    createdAt: '2026-06-26 09:42:00',
    updatedAt: serverTime
  }
}

const buildMockReviewRuns = (id?: string, nodeId?: number) => {
  const runs = buildMockFdeAiRuns(id, nodeId)
  const fallbackProjectId = id || projectId
  const baseRuns = runs.length
    ? runs.map((run) => buildMockReviewRun(run, run.projectId, run.nodeId))
    : [
        buildMockReviewRun(
          state.aiRuns[0],
          fallbackProjectId,
          nodeId || getProject(fallbackProjectId).currentNodeId
        )
      ]
  const primary = baseRuns[0]
  if (!primary || baseRuns.length >= 2) return baseRuns
  return [
    primary,
    {
      ...primary,
      id: `${primary.reviewRunId}-SHADOW`,
      reviewRunId: `${primary.reviewRunId}-SHADOW`,
      runMode: 'shadow',
      status: 'draft_persisted',
      currentStep: 'quality_gate',
      workflowId: `${primary.workflowId}-shadow`,
      temporalRunId: `${primary.temporalRunId}-shadow`,
      graphSummary: {
        total: 8,
        statusCounts: { completed: 8 }
      },
      updatedAt: '2026-06-26 10:24:00'
    }
  ]
}

const buildMockReviewGraph = (reviewRunId: string) => {
  const selectedNodes = getMockPageIndexNodes(projectId, state.documents[0]?.currentVersionId)
  return {
    reviewRunId,
    nodes: [
      {
        nodeKey: 'load_document_context',
        status: 'completed',
        taskQueue: 'review-orchestrator-local',
        durationMs: 260,
        toolCalls: ['get_project_context', 'get_batch_documents']
      },
      {
        nodeKey: 'load_ocr_result',
        status: 'completed',
        taskQueue: 'document-intelligence-local',
        durationMs: 810,
        toolCalls: ['get_ocr_result']
      },
      {
        nodeKey: 'run_rule_checks',
        status: 'completed',
        taskQueue: 'knowledge-rule-local',
        durationMs: 430,
        toolCalls: ['run_rule_engine']
      },
      {
        nodeKey: 'retrieve_knowledge',
        status: 'completed',
        taskQueue: 'knowledge-rule-local',
        durationMs: 720,
        toolCalls: ['search_knowledge_base', 'retrieve_pageindex_nodes']
      },
      {
        nodeKey: 'llm_generate_findings',
        status: 'completed',
        taskQueue: 'litellm-local',
        durationMs: 2800,
        toolCalls: ['litellm.chat.completions']
      },
      {
        nodeKey: 'evidence_validation',
        status: 'completed',
        taskQueue: 'review-orchestrator-local',
        durationMs: 360,
        toolCalls: ['validate_evidence_refs']
      },
      {
        nodeKey: 'quality_gate',
        status: 'completed',
        taskQueue: 'review-orchestrator-local',
        durationMs: 180,
        toolCalls: ['validate_schema', 'validate_references']
      },
      {
        nodeKey: 'waiting_human_review',
        status: 'waiting_human_review',
        taskQueue: 'business-review',
        durationMs: 0,
        toolCalls: []
      }
    ],
    edges: [
      { source: 'load_document_context', target: 'load_ocr_result' },
      { source: 'load_ocr_result', target: 'run_rule_checks' },
      { source: 'run_rule_checks', target: 'retrieve_knowledge' },
      { source: 'retrieve_knowledge', target: 'llm_generate_findings' },
      { source: 'llm_generate_findings', target: 'evidence_validation' },
      { source: 'evidence_validation', target: 'quality_gate' },
      { source: 'quality_gate', target: 'waiting_human_review' }
    ],
    timeline: [
      {
        stepName: 'load_document_context',
        status: 'completed',
        startedAt: '2026-06-26 09:42:01',
        durationMs: 260
      },
      {
        stepName: 'load_ocr_result',
        status: 'completed',
        startedAt: '2026-06-26 09:42:02',
        durationMs: 810
      },
      {
        stepName: 'run_rule_checks',
        status: 'completed',
        startedAt: '2026-06-26 09:42:03',
        durationMs: 430
      },
      {
        stepName: 'retrieve_knowledge',
        status: 'completed',
        startedAt: '2026-06-26 09:42:04',
        durationMs: 720
      },
      {
        stepName: 'llm_generate_findings',
        status: 'completed',
        startedAt: '2026-06-26 09:42:05',
        durationMs: 2800
      },
      {
        stepName: 'waiting_human_review',
        status: 'waiting_human_review',
        startedAt: serverTime,
        durationMs: 0
      }
    ],
    artifactSummary: {
      toolCalls: 9,
      ruleCheckResults: 3,
      retrievalTraces: 3,
      pageIndexTraces: 1,
      findingDrafts: 3,
      validationFailures: 1
    },
    artifacts: {
      ruleCheckResults: [
        {
          ruleCode: 'WELDER_CERT_001',
          result: 'passed',
          severity: 'medium',
          message: '焊工资格证编号、有效期和持证项目已识别。',
          linkedClauseIds: ['CLAUSE-WELDER-6.1.3']
        },
        {
          ruleCode: 'OCR_FIELD_CONF_002',
          result: 'warning',
          severity: 'medium',
          message: '证书编号字段置信度 0.84，低于人工确认阈值 0.90。',
          linkedClauseIds: ['CLAUSE-DOC-2.1.1']
        }
      ],
      retrievalTraces: [
        {
          retrievalTraceId: `RT-${reviewRunId}-HYBRID`,
          query: '焊工资格证有效期和持证项目审查依据',
          queryType: 'review_basis_search',
          selectedRoute: 'hybrid_rag',
          selectedClauseCount: 3,
          selectedClauseIds: ['CLAUSE-WELDER-6.1.3', 'CLAUSE-DOC-2.1.1'],
          queryRouter: { selectedRoute: 'hybrid_rag', reason: '条款号和资料类型明确' }
        },
        {
          retrievalTraceId: `RT-${reviewRunId}-PAGEINDEX`,
          query: '资质证书、外部查询截图和签章跨章节依据',
          queryType: 'long_document_cross_section',
          selectedRoute: 'pageindex_tree_search',
          selectedClauseCount: 2,
          selectedClauseIds: ['CLAUSE-SEAL-4.2.1', 'CLAUSE-WELDER-6.1.3'],
          queryRouter: {
            selectedRoute: 'pageindex_tree_search',
            fallbackRoute: 'hybrid_rag',
            reason: '问题涉及证书、截图、印章多个章节'
          },
          pageIndexTree: {
            rootNodeId: 'PI-ROOT',
            candidateNodeCount: selectedNodes.length,
            selectedNodes
          }
        },
        {
          retrievalTraceId: `RT-${reviewRunId}-VECTOR`,
          query: '管道特性表、质量证明书和 NDT 报告的证据片段是否已入库',
          queryType: 'review_basis_search',
          selectedRoute: 'hybrid_rag',
          selectedClauseCount: 4,
          selectedClauseIds: [
            'CLAUSE-DOC-2.1.1',
            'CLAUSE-QC-5.3.2',
            'CLAUSE-NDT-8.1.4',
            'CLAUSE-EVIDENCE-3.3.1'
          ],
          queryRouter: {
            selectedRoute: 'hybrid_rag',
            reason: '问题以资料字段和条款号为主，优先使用向量索引和 BM25 融合检索'
          },
          vectorSearch: {
            embeddingModel: state.knowledgeConfig.embeddingModel,
            indexVersion: 'knowledge-index@local',
            topK: 12,
            hitCount: 10,
            minScore: 0.72
          }
        }
      ],
      findingDrafts: [
        {
          id: `FD-${reviewRunId}-001`,
          findingType: 'needs_human_confirmation',
          severity: 'medium',
          title: '外部查询截图来源需人工确认',
          confidence: 0.88,
          evidenceRefs: [
            {
              documentVersionId: state.documents[0]?.currentVersionId,
              pageNo: 1,
              bbox: [120, 220, 560, 420]
            }
          ],
          ruleRefs: [{ ruleCode: 'WELDER_CERT_001' }],
          kbRefs: [{ clauseId: 'CLAUSE-WELDER-6.1.3' }],
          requiresHumanConfirmation: true
        },
        {
          id: `FD-${reviewRunId}-002`,
          findingType: 'low_confidence_field',
          severity: 'low',
          title: '证书编号 OCR 置信度低于阈值',
          confidence: 0.84,
          evidenceRefs: [
            {
              documentVersionId: state.documents[0]?.currentVersionId,
              pageNo: 1,
              bbox: [640, 300, 980, 360]
            }
          ],
          ruleRefs: [{ ruleCode: 'OCR_FIELD_CONF_002' }],
          kbRefs: [{ clauseId: 'CLAUSE-DOC-2.1.1' }],
          requiresHumanConfirmation: true
        },
        {
          id: `FD-${reviewRunId}-003`,
          findingType: 'cross_document_consistency_warning',
          severity: 'medium',
          title: 'NDT 报告焊口编号与施工记录需复核一致性',
          confidence: 0.79,
          evidenceRefs: [
            {
              documentVersionId: state.documents[3]?.currentVersionId,
              pageNo: 2,
              bbox: [220, 460, 1120, 720]
            }
          ],
          ruleRefs: [{ ruleCode: 'CROSS_DOC_WELD_NO_001' }],
          kbRefs: [{ clauseId: 'CLAUSE-CROSS-7.2.4' }],
          requiresHumanConfirmation: true
        }
      ]
    }
  }
}

const buildMockFdeReviewRunDetail = (reviewRunId: string) => {
  const run =
    buildMockReviewRuns().find((item) => item.reviewRunId === reviewRunId) || buildMockReviewRun()
  const graph = buildMockReviewGraph(reviewRunId)
  return {
    run,
    graph,
    timeline: graph.timeline,
    temporal: {
      workflowId: run.workflowId,
      runId: run.temporalRunId,
      eventCount: 18,
      status: 'running',
      historyPolicy: 'ids_hashes_versions_only',
      taskQueue: 'review-orchestrator-local'
    },
    reasoningTrace: [
      {
        step: '规则优先',
        thought: '缺项和低置信字段先由规则库确定，不由 LLM 直接判断。',
        evidence: 'WELDER_CERT_001 / OCR_FIELD_CONF_002',
        quality: '可追溯'
      },
      {
        step: '依据检索',
        thought: '普通依据走 Hybrid RAG，跨章节资质和签章要求触发 PageIndex。',
        evidence: 'RT-RR-PAGEINDEX',
        quality: '需人工确认'
      }
    ],
    lineage: {
      documentVersions: getFdeProjectVersionIds(
        run.projectId || projectId,
        Number(run.nodeId || 0)
      ),
      ocrResultVersions: ['parse-local-20260626-001'],
      kbVersion: 'knowledge-index@local',
      ruleSetVersion: 'engineering_rules@2026.06',
      promptVersion: run.promptVersion,
      modelRouteVersion: 'deepseek-reasoner@litellm-local'
    },
    qualityEvaluation: {
      score: 0.91,
      status: 'needs_human_review',
      humanReviewRequired: true,
      dimensions: [
        { name: '证据命中率', score: 0.93, status: 'pass' },
        { name: '依据正确率', score: 0.9, status: 'pass' },
        { name: '低置信字段处理', score: 0.82, status: 'warning' }
      ],
      gates: [
        { name: 'Schema 校验', status: 'pass', message: '结构化输出字段完整。' },
        { name: '证据校验', status: 'pass', message: 'bbox 和页码可回显。' },
        { name: '人工确认', status: 'warning', message: '外部查询截图来源需人工确认。' }
      ]
    },
    humanCorrections: [
      {
        id: 'HC-FDE-001',
        targetType: 'finding_draft',
        correctionType: 'edit',
        before: '建议通过',
        after: '建议人工确认外部查询截图来源后通过',
        rootCause: 'evidence_scope_needs_human'
      },
      ...state.fdeReviewFeedbacks.filter((item) => item.reviewRunId === reviewRunId)
    ],
    redactionPolicy: 'masked_by_default',
    scorecard: {
      schemaVersion: 'review-orchestrator-scorecard@1.0',
      targetScore: 100,
      score: 92,
      ok: false,
      sections: [
        { name: 'Temporal 工作流', score: 20, maxScore: 20, status: 'pass' },
        { name: 'LangGraph Checkpoint', score: 20, maxScore: 20, status: 'pass' },
        { name: '证据与依据校验', score: 28, maxScore: 30, status: 'pass' },
        { name: '人工确认闭环', score: 24, maxScore: 30, status: 'warning' }
      ],
      blockers: ['外部查询截图来源仍需人工确认']
    }
  }
}

const buildMockOcrJobs = (id?: string, nodeId?: number) =>
  getFdeProjectDocuments(id || projectId)
    .filter((document) => {
      if (!nodeId) return true
      const boundVersionIds = state.bindings
        .filter((binding) => binding.projectId === (id || projectId) && binding.nodeId === nodeId)
        .map((binding) => binding.documentVersionId)
      if (boundVersionIds.length < 2) return true
      return boundVersionIds.some(
        (binding) => String(binding) === String(document.currentVersionId)
      )
    })
    .map((document, index) => ({
      id: `OCR-JOB-${document.currentVersionId}`,
      jobId: `OCR-JOB-${document.currentVersionId}`,
      projectId: document.projectId,
      nodeId: state.bindings.find(
        (binding) => binding.documentVersionId === document.currentVersionId
      )?.nodeId,
      documentId: document.id,
      documentVersionId: document.currentVersionId,
      profileId:
        index === 0
          ? 'qualification_certificate_v1'
          : index === 2
            ? 'quality_certificate_v1'
            : index === 3
              ? 'ndt_rt_report_v1'
              : 'construction_record_v1',
      status: document.currentOcrStatus === '识别中' ? 'running' : 'success',
      parseResultId: `PARSE-${document.currentVersionId}`,
      resultSummary: {
        fieldCount: index === 3 ? 16 : 9,
        tableCount: index === 1 || index === 3 ? 2 : 1,
        sealCount: index === 2 || index === 3 ? 1 : 0,
        lowConfidenceFieldCount: index === 2 ? 3 : 1
      },
      engineRuns: [
        {
          engine: 'pp_ocr_v6',
          status: 'success',
          durationMs: 1260,
          selectedVariantId: 'v1_deskew'
        },
        {
          engine: 'pp_structure_v3',
          status: 'success',
          durationMs: 2180,
          selectedVariantId: 'table_v1_line_enhanced'
        },
        {
          engine: 'paddlex_seal',
          status: index === 1 ? 'skipped' : 'success',
          durationMs: 740,
          selectedVariantId: 'seal_v0_color_original'
        }
      ],
      updatedAt: document.updatedAt
    }))

const buildMockOcrRunDetail = (jobId: string) => {
  const job =
    buildMockOcrJobs().find((item) => item.jobId === jobId || item.id === jobId) ||
    buildMockOcrJobs()[0]
  return {
    job,
    parseResult: {
      parseResultId: job.parseResultId,
      status: job.status,
      profileId: job.profileId,
      preprocessStatus: {
        requestedVariants: [
          'original',
          'deskew',
          'gray_clahe',
          'table_line_enhanced',
          'seal_color_crop'
        ],
        generatedVariants: [
          'original',
          'deskew',
          'gray_clahe',
          'table_line_enhanced',
          'seal_color_crop'
        ],
        selectedVariantId: 'table_v1_line_enhanced',
        missingVariants: []
      },
      engineRuns: job.engineRuns,
      diagnostics: [
        {
          code: 'FIELD_LOW_CONFIDENCE',
          level: 'warning',
          message: '证书编号字段置信度低于 0.90，建议人工复核。',
          pageNo: 1
        },
        {
          code: 'TABLE_STRUCTURE_LOW_CONFIDENCE',
          level: 'warning',
          message: '第 2 页表格跨列结构需标注样本补强。',
          pageNo: 2
        }
      ]
    },
    corrections: [
      {
        id: 'OCR-CORR-001',
        documentVersionId: job.documentVersionId,
        fieldCode: 'certificate_no',
        originalValue: 'TS1810648-202',
        correctedValue: 'TS1810648-2021',
        reason: '低清晰度导致末位漏识别',
        shouldEnterEvaluationSet: true
      }
    ]
  }
}

const buildMockOcrAnnotationTasks = (id?: string, nodeId?: number) =>
  buildMockOcrJobs(id, nodeId)
    .slice(0, 6)
    .map((job, index) => {
      const profileId = index === 2 ? 'seal_text_profile_v1' : job.profileId
      return {
        taskId: `OCR-LABEL-${index + 1}`,
        caseId: `OCR-CASE-${index + 1}`,
        projectId: job.projectId,
        nodeId: job.nodeId,
        documentVersionId: job.documentVersionId,
        scenario:
          index === 0
            ? '字段框选与证书编号修正'
            : index === 1
              ? '表格单元格结构标定'
              : index === 2
                ? '红章区域与章名标定'
                : 'NDT 报告跨页表格标定',
        profileId,
        documentType: profileId,
        pageNo: index + 1,
        collectionStatus:
          index === 0 ? 'labeled' : index === 1 ? 'needs_labeling' : 'ready_for_eval',
        readinessBlockers: index === 1 ? ['缺少人工表格单元格标注'] : [],
        certificationBlockers: index === 2 ? ['印章名称需二审'] : [],
        pageDimensions: { 1: [2480, 3508], 2: [2480, 3508], 3: [2480, 3508], 4: [2480, 3508] },
        candidateCounts: {
          fields: 8 + index,
          tables: index % 2 ? 2 : 1,
          seals: index >= 2 ? 1 : 0
        },
        labelCounts: {
          fields: index === 1 ? 0 : 6 + index,
          tables: index === 1 ? 0 : 1,
          seals: index >= 2 ? 1 : 0
        },
        readyForEval: index !== 1,
        labeler: index === 1 ? '' : 'FDE 张工',
        reviewer: index === 2 ? 'OCR 负责人' : ''
      }
    })

const buildMockOcrAnnotationPayload = (id?: string, nodeId?: number, page = 1, pageSize = 20) => {
  const tasks = buildMockOcrAnnotationTasks(id, nodeId)
  const blockerCounts = tasks.reduce<Record<string, number>>((acc, task) => {
    for (const blocker of [
      ...(task.readinessBlockers || []),
      ...(task.certificationBlockers || [])
    ]) {
      acc[blocker] = (acc[blocker] || 0) + 1
    }
    return acc
  }, {})
  const humanLabeled = tasks.filter((task) => task.collectionStatus !== 'needs_labeling').length
  const readyForEval = tasks.filter((task) => task.readyForEval).length
  return {
    summary: {
      tasks: tasks.length,
      humanLabeled,
      readyForEval,
      missingHumanLabels: tasks.length - humanLabeled,
      completionRate: tasks.length ? Math.round((humanLabeled / tasks.length) * 100) / 100 : 0,
      scenarioCounts: tasks.reduce<Record<string, number>>((acc, task) => {
        const scenario = String(task.profileId || 'unknown')
        acc[scenario] = (acc[scenario] || 0) + 1
        return acc
      }, {}),
      readyScenarioCounts: tasks.reduce<Record<string, number>>((acc, task) => {
        if (!task.readyForEval) return acc
        const scenario = String(task.profileId || 'unknown')
        acc[scenario] = (acc[scenario] || 0) + 1
        return acc
      }, {}),
      statusCounts: tasks.reduce<Record<string, number>>((acc, task) => {
        const status = String(task.collectionStatus || 'unknown')
        acc[status] = (acc[status] || 0) + 1
        return acc
      }, {}),
      blockerCounts
    },
    nextActions: ['补齐表格单元格标注', '复核低置信印章章名', '将通过样本加入 OCR Regression Set'],
    page: makePage(tasks, page, pageSize)
  }
}

const buildMockFdeOcrQuality = () => ({
  overview: {
    parseResultCount: 4,
    autoUsableRate: 0.82,
    needsHumanReviewRate: 0.18,
    averageConfidence: 0.89
  },
  evidenceLevel: {
    bboxCoverage: 0.94,
    missingEvidenceItems: [
      {
        documentVersionId: state.documents[2]?.currentVersionId,
        fieldCode: 'seal_name',
        reason: '印章文字低置信'
      }
    ]
  },
  fieldLevel: {
    fieldCount: 38,
    lowConfidenceFieldCount: 4,
    averageFieldConfidence: 0.88,
    fieldCodeBreakdown: [{ fieldCode: 'certificate_no', count: 2 }],
    qualityFlagCounts: [{ flag: 'low_confidence', count: 4 }],
    missingRequiredFieldBreakdown: [{ fieldCode: 'material_grade', count: 1 }]
  },
  tableLevel: {
    tableCount: 6,
    formalTableCount: 4,
    heuristicTableCount: 2,
    reviewRequiredCount: 2,
    businessRowCount: 42,
    normalizedRowCount: 38,
    cellCount: 216,
    averageTableConfidence: 0.86,
    formalTableRate: 0.67,
    heuristicTableRate: 0.33,
    reviewRequiredRate: 0.33,
    sourceBreakdown: [{ source: 'pp_structure_v3', count: 4 }],
    qualityFlagCounts: [{ flag: 'merged_cell_uncertain', count: 2 }],
    sampleTables: []
  },
  sealLevel: {
    parseResultCount: 4,
    sealCount: 2,
    readableSealCount: 1,
    fragmentSealCount: 1,
    visualCandidateCount: 2,
    reviewRequiredCount: 1,
    missingTextCount: 1,
    averageSealConfidence: 0.78,
    readableSealRate: 0.5,
    fragmentSealRate: 0.5,
    visualCandidateReviewRate: 0.5,
    sourceBreakdown: [{ source: 'paddlex_seal', count: 2 }],
    qualityFlagCounts: [{ flag: 'seal_text_low_confidence', count: 1 }],
    sampleSeals: []
  },
  jobLevel: { total: 4, success: 3, failed: 0, running: 1 },
  lowConfidenceFields: extractedFields.slice(0, 4),
  jobs: buildMockOcrJobs(),
  parseResults: buildMockOcrJobs().map(
    (job) => buildMockOcrRunDetail(String(job.jobId)).parseResult
  ),
  corrections: buildMockOcrRunDetail(String(buildMockOcrJobs()[0]?.jobId || '')).corrections,
  evalRuns: [
    {
      id: 'OCR-EVAL-20260626-001',
      profileId: 'engineering_inspection_ocr_release',
      status: 'completed',
      startedAt: '2026-06-26 09:00:00',
      finishedAt: '2026-06-26 09:12:00',
      metrics: {
        caseCount: 12,
        averageScore: 0.91,
        fieldAccuracy: 0.93,
        tableAccuracy: 0.88,
        sealAccuracy: 0.82
      },
      evaluationSummary: {
        ok: false,
        summary: { cases: 12, total: 12, passed: 10, failed: 2, averageScore: 0.91 },
        metrics: {
          fieldAccuracy: 0.93,
          tableAccuracy: 0.88,
          sealAccuracy: 0.82,
          bboxHitRate: 0.94
        },
        findingCounts: {
          FIELD_LOW_CONFIDENCE: 3,
          TABLE_STRUCTURE_LOW_CONFIDENCE: 2,
          SEAL_TEXT_LOW_CONFIDENCE: 1
        },
        thresholdFailures: [{ metric: 'sealNameAccuracy', actual: 0.82, threshold: 0.9 }],
        scenarioMetrics: {
          field_extraction: {
            ok: true,
            cases: 4,
            passed: 4,
            failed: 0,
            averageScore: 0.94,
            findingCounts: {},
            thresholdFailures: []
          },
          table_structure: {
            ok: false,
            cases: 4,
            passed: 3,
            failed: 1,
            averageScore: 0.88,
            findingCounts: { TABLE_STRUCTURE_LOW_CONFIDENCE: 2 },
            thresholdFailures: [{ metric: 'cellAccuracy', actual: 0.88, threshold: 0.9 }]
          },
          seal_recognition: {
            ok: false,
            cases: 2,
            passed: 1,
            failed: 1,
            averageScore: 0.82,
            findingCounts: { SEAL_TEXT_LOW_CONFIDENCE: 1 },
            thresholdFailures: [{ metric: 'sealNameAccuracy', actual: 0.82, threshold: 0.9 }]
          },
          pageindex_evidence: {
            ok: true,
            cases: 2,
            passed: 2,
            failed: 0,
            averageScore: 0.93,
            findingCounts: {},
            thresholdFailures: []
          }
        },
        failedCases: [
          {
            caseId: 'OCR-CASE-002',
            scenario: 'table_structure',
            score: 0.86,
            minScore: 0.9,
            qualityStatus: 'needs_human_review',
            findings: ['跨列表格单元格边界需人工修正']
          },
          {
            caseId: 'OCR-CASE-003',
            scenario: 'seal_recognition',
            score: 0.82,
            minScore: 0.9,
            qualityStatus: 'needs_human_review',
            findings: ['印章名称末尾公司名识别不完整']
          }
        ]
      },
      caseDiagnostics: []
    }
  ],
  qualityReasonCounts: [
    { reason: 'FIELD_LOW_CONFIDENCE', count: 4 },
    { reason: 'TABLE_STRUCTURE_LOW_CONFIDENCE', count: 2 }
  ],
  runtimeDoctor: {
    status: 'warning',
    ok: false,
    summary: { pass: 8, warn: 2, fail: 0, total: 10 },
    topIssues: [{ code: 'SEAL_MODEL_NEEDS_EVAL', message: '印章文字准确率低于发布阈值。' }],
    subprocessPython: 'python3.11',
    schemaVersion: 'ocr-runtime-doctor@1.0'
  },
  ocr100Scorecard: {
    schemaVersion: 'ocr-100@1.0',
    targetScore: 100,
    score: 91,
    ok: false,
    sections: [
      { name: '统一 Schema', score: 20, maxScore: 20, status: 'pass' },
      { name: '候选图与选优', score: 18, maxScore: 20, status: 'pass' },
      {
        name: '表格结构',
        score: 24,
        maxScore: 30,
        status: 'warning',
        blockers: ['跨列表格样本不足']
      },
      {
        name: '印章识别',
        score: 19,
        maxScore: 30,
        status: 'warning',
        blockers: ['印章文字准确率未达 90%']
      }
    ],
    blockers: ['印章文字准确率未达 90%', '跨列表格标注样本不足']
  },
  ocr100ActionBoard: {
    schemaVersion: 'aicheck-ocr-100-action-board-v1',
    ok: false,
    summary: {
      status: 'needs_sample_files',
      score: 91,
      readyForEval: 30,
      requiredReadyForEval: 100,
      collectionMissingCases: 12,
      placeholderSampleSlots: 12,
      annotationTasks: 42,
      remainingHumanLabels: 12,
      newLocalCandidates: 3,
      duplicateLocalCandidates: 8,
      actions: 7,
      laneCounts: { collect_samples: 2, label_existing: 4, triage_candidates: 1 }
    },
    actions: [
      {
        id: 'collect-ndt_ut_profile',
        lane: 'collect_samples',
        scenario: 'ndt_ut_profile',
        title: 'Collect 8 real OCR sample(s) for ndt_ut_profile',
        doneWhen: '真实 UT 报告已放入场景目录并通过 manifest 校验。'
      },
      {
        id: 'label-real-piping_table_profile-002',
        lane: 'label_existing',
        scenario: 'piping_table_profile',
        title: 'Human-review OCR label for real-piping_table_profile-002',
        doneWhen: '字段、表格、印章证据已人工校对并二审。'
      },
      {
        id: 'triage-new-candidates',
        lane: 'triage_candidates',
        scenario: 'mixed',
        title: 'Triage 3 new local OCR sample candidate(s)',
        doneWhen: '候选样本完成去重并进入正确场景目录。'
      }
    ]
  },
  failurePools: {
    fieldFailures: [{ code: 'FIELD_LOW_CONFIDENCE', source: 'ocr_eval' }],
    tableFailures: [{ code: 'TABLE_STRUCTURE_LOW_CONFIDENCE', source: 'ocr_eval' }],
    sealFailures: [{ code: 'SEAL_TEXT_LOW_CONFIDENCE', source: 'ocr_eval' }],
    engineFailures: []
  }
})

const buildMockFdeProjectWorkspace = (id: string, nodeId?: number) => {
  const project = getProject(id)
  const nodes = state.treeNodes.filter((node) => node.projectId === id)
  const selectedNodeId = nodeId || project.currentNodeId || nodes[0]?.nodeId
  const selectedNode = selectedNodeId ? getNode(id, selectedNodeId) : nodes[0]
  const documents = getFdeProjectDocuments(id)
  const bindingsForProject = state.bindings.filter((binding) => binding.projectId === id)
  const bindingsForNode = selectedNodeId
    ? bindingsForProject.filter((binding) => binding.nodeId === selectedNodeId)
    : bindingsForProject
  const auditBindingsForNode = documents.map((document, index) => {
    const existing = bindingsForNode.find(
      (binding) => binding.documentVersionId === document.currentVersionId
    )
    if (existing) return existing
    const template = fdeAuditDocumentTemplates[index % fdeAuditDocumentTemplates.length]
    return {
      id: `FDE-BIND-${compactFdeId(id)}-${selectedNodeId || 'NODE'}-${index + 1}`,
      projectId: id,
      nodeId: selectedNodeId || project.currentNodeId || 0,
      requirementId: `FDE-REQ-${index + 1}`,
      requirementName: template.requirementName,
      documentId: document.id,
      documentVersionId: document.currentVersionId,
      fileName: document.fileName,
      versionNo: String(document.currentVersionId || '').includes('V2') ? 'V2' : 'V1',
      usage: template.usage,
      sourceOrgName: document.sourceOrgName,
      bindingStatus: index === 2 ? '需人工复核' : '已提交',
      boundAt: document.updatedAt,
      actions: ['file:view', 'review:save'] as ActionCode[]
    }
  })
  const reviewRuns = buildMockReviewRuns(id, selectedNodeId)
  const ocrJobs = buildMockOcrJobs(id, selectedNodeId)
  const annotationTasks = buildMockOcrAnnotationTasks(id, selectedNodeId)
  const nodeSummaries = nodes.map((node) => {
    const nodeBindings = bindingsForProject.filter((binding) => binding.nodeId === node.nodeId)
    const effectiveNodeBindings =
      nodeBindings.length || node.nodeId !== selectedNodeId ? nodeBindings : auditBindingsForNode
    const nodeDocuments = documents.filter((document) =>
      effectiveNodeBindings.some(
        (binding) => binding.documentVersionId === document.currentVersionId
      )
    )
    return {
      nodeId: node.nodeId,
      name: node.name,
      status: node.status,
      documentCount: nodeDocuments.length,
      vectorizedDocumentCount: nodeDocuments.filter((document) =>
        String(document.vectorStatus).startsWith('已向量化')
      ).length,
      pageIndexNodeCount: nodeDocuments.reduce(
        (sum, document) => sum + Number(document.pageIndexNodeCount || 0),
        0
      ),
      reviewRunCount: reviewRuns.filter((run) => Number(run.nodeId) === node.nodeId).length,
      ocrJobCount: ocrJobs.filter((job) => Number(job.nodeId) === node.nodeId).length,
      annotationTaskCount: annotationTasks.filter((task) => Number(task.nodeId) === node.nodeId)
        .length,
      blockerCount: node.nodeId === 24 ? 2 : node.nodeId === 40 ? 1 : 0,
      lowConfidenceFieldCount: node.nodeId === 24 ? 2 : node.nodeId === 40 ? 2 : 0
    }
  })
  const submissions = state.submissionSnapshots
    .filter((snapshot) => snapshot.projectId === id)
    .map((snapshot) => ({
      submissionId: snapshot.submissionId,
      batchName: snapshot.batchName,
      nodeIds: snapshot.nodeIds,
      nodeNames: snapshot.nodeIds.map((nodeId) => getNode(id, nodeId).name),
      status: snapshot.nextStatus || 'submitted',
      bindingCount: snapshot.bindingIds.length,
      submittedAt: snapshot.submittedAt
    }))
  if (!submissions.length) {
    submissions.push({
      submissionId: `FDE-SUB-${compactFdeId(id)}-${selectedNodeId || 'NODE'}`,
      batchName: `${selectedNode?.name || '审查节点'}资料批次`,
      nodeIds: selectedNodeId ? [selectedNodeId] : [],
      nodeNames: selectedNode?.name ? [selectedNode.name] : [],
      status: 'waiting_human_review',
      bindingCount: auditBindingsForNode.length,
      submittedAt: '2026-06-26 10:18:00'
    })
  }
  const qualityBlockers = [
    {
      id: 'FDE-BLOCK-OCR-001',
      type: 'ocr-field',
      level: 'warning',
      title: '证书编号字段置信度低',
      target: documents[0]?.fileName,
      action: '进入 OCR 打标页修正 bbox 与字段值'
    },
    {
      id: 'FDE-BLOCK-AGENT-001',
      type: 'agent',
      level: 'warning',
      title: 'ReviewRun 等待人工复核',
      target: reviewRuns[0]?.reviewRunId,
      action: '检查 LangGraph Trace 后确认或修正发现项'
    },
    {
      id: 'FDE-BLOCK-SEAL-001',
      type: 'ocr',
      level: 'danger',
      title: '印章文字准确率未达发布阈值',
      target: documents[2]?.fileName,
      action: '补充印章标注样本并重新评估'
    }
  ]
  const metrics = {
    nodes: nodes.length,
    documents: documents.length,
    knowledgeChunks: documents.reduce((sum, document) => sum + Number(document.chunkCount || 0), 0),
    knowledgeVectors: documents.reduce(
      (sum, document) => sum + Number(document.vectorCount || 0),
      0
    ),
    vectorizedDocuments: documents.filter((document) =>
      String(document.vectorStatus).startsWith('已向量化')
    ).length,
    pageIndexNodes: documents.reduce(
      (sum, document) => sum + Number(document.pageIndexNodeCount || 0),
      0
    ),
    submissions: submissions.length,
    ocrJobs: ocrJobs.length,
    reviewRuns: reviewRuns.length,
    annotationTasks: annotationTasks.length,
    blockers: qualityBlockers.length,
    lowConfidenceFields: 4
  }
  return {
    project,
    selectedNodeId,
    selectedNode,
    groups: getProjectGroups(id),
    nodeSummaries,
    metrics,
    documents,
    bindings: auditBindingsForNode,
    submissions,
    reviewRuns,
    aiRuns: buildMockFdeAiRuns(id, selectedNodeId),
    ocrJobs,
    ocrAnnotationTasks: annotationTasks,
    qualityBlockers,
    updatedAt: serverTime
  }
}

const buildMockFdeProjectSummaries = () =>
  state.projects.map((project) => {
    const workspace = buildMockFdeProjectWorkspace(project.id, project.currentNodeId)
    return {
      project,
      metrics: workspace.metrics,
      currentNodeId: workspace.selectedNodeId,
      currentNodeName: workspace.selectedNode?.name,
      topBlockers: workspace.qualityBlockers.slice(0, 3),
      updatedAt: workspace.updatedAt
    }
  })

const buildMockFdeDashboard = () => ({
  metrics: [
    { label: '资料向量化完成率', value: 0.75, tone: 'green', suffix: '%' },
    { label: 'PageIndex 命中率', value: 0.5, tone: 'blue', suffix: '%' },
    { label: 'Agent 待人工复核', value: 1, tone: 'orange' },
    { label: 'OCR 标注缺口', value: 2, tone: 'red' }
  ],
  alerts: [
    {
      id: 'FDE-ALERT-001',
      severity: 'warning',
      title: '印章文字准确率低于 90% 门禁',
      status: 'open'
    },
    {
      id: 'FDE-ALERT-002',
      severity: 'info',
      title: 'PageIndex 已命中跨章节依据',
      status: 'monitoring'
    }
  ],
  agentPerformance: [
    {
      agentId: 'compliance_review_agent',
      version: '1.4.0',
      status: 'production',
      riskLevel: 'high',
      acceptanceRate: 0.86,
      evidenceHitRate: 0.93,
      hallucinationRate: 0.006
    }
  ],
  cost: { tokenEstimate: 18620, estimatedPrice: 1.42, budgetStatus: 'normal' },
  releaseStatus: { bundles: 1, releasePlans: 0, pendingApprovals: 0 }
})

export default [
  {
    url: '/api/fde/dashboard',
    method: 'get',
    timeout,
    response: () => ok(buildMockFdeDashboard())
  },
  {
    url: '/api/fde/projects',
    method: 'get',
    timeout,
    response: () => ok(buildMockFdeProjectSummaries())
  },
  {
    url: /\/api\/fde\/projects\/[^/]+\/audit-workspace/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const id = pathParts(url)[3] || projectId
      const nodeId = Number(query?.nodeId || 0) || undefined
      return ok(buildMockFdeProjectWorkspace(id, nodeId))
    }
  },
  {
    url: /\/api\/fde\/projects\/[^/]+\/nodes\/[^/]+\/audit-detail/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[3] || projectId
      const nodeId = Number(parts[5] || 0) || getProject(id).currentNodeId
      return ok({
        project: getProject(id),
        node: getNode(id, nodeId),
        workspace: buildMockFdeProjectWorkspace(id, nodeId),
        pageIndexNodes: getMockPageIndexNodes(id),
        updatedAt: serverTime
      })
    }
  },
  {
    url: '/api/fde/ai-runs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const items = buildMockFdeAiRuns(
        query?.projectId ? String(query.projectId) : undefined,
        Number(query?.nodeId || 0) || undefined
      )
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/fde\/ai-runs\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const runId = pathParts(url)[3]
      const run = buildMockFdeAiRuns().find((item) => item.id === runId) || buildMockFdeAiRuns()[0]
      return ok({
        run,
        traceSteps: [
          { step: 'context', status: 'completed', message: '加载项目、节点、资料版本上下文。' },
          { step: 'ocr', status: 'completed', message: '读取 OCR 字段、表格和印章结果。' },
          { step: 'rag', status: 'completed', message: 'Hybrid RAG 与 PageIndex 检索依据。' },
          {
            step: 'llm',
            status: 'completed',
            message: '通过 LiteLLM 调用 deepseek-reasoner 生成草稿。'
          }
        ],
        replays: [],
        feedback: [],
        accessPolicy: { rawAccess: false, rawAccessRequiresGrant: true }
      })
    }
  },
  {
    url: '/api/fde/review-runs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const items = buildMockReviewRuns(
        query?.projectId ? String(query.projectId) : undefined,
        Number(query?.nodeId || 0) || undefined
      )
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/fde\/review-runs\/[^/]+\/graph$/,
    method: 'get',
    timeout,
    response: ({ url }) => ok(buildMockReviewGraph(pathParts(url)[3] || 'RR-LOCAL'))
  },
  {
    url: /\/api\/fde\/review-runs\/[^/]+\/temporal-history$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const reviewRunId = pathParts(url)[3] || 'RR-LOCAL'
      const detail = buildMockFdeReviewRunDetail(reviewRunId)
      return ok({
        workflowId: detail.run.workflowId,
        runId: detail.run.temporalRunId,
        eventCount: detail.temporal.eventCount,
        events: detail.timeline.map((item, index) => ({
          eventId: index + 1,
          eventType:
            item.status === 'waiting_human_review'
              ? 'WorkflowExecutionSignaled'
              : 'ActivityTaskCompleted',
          stepName: item.stepName,
          status: item.status
        }))
      })
    }
  },
  {
    url: /\/api\/fde\/review-runs\/[^/]+\/feedback$/,
    method: 'post',
    timeout,
    response: ({ url, body }) => {
      const reviewRunId = pathParts(url)[3] || 'RR-LOCAL'
      const record = {
        id: `HC-FDE-${state.fdeReviewFeedbacks.length + 2}`,
        reviewRunId,
        targetType: 'finding_draft',
        correctionType: body?.feedbackType || 'wrong_evidence',
        feedbackType: body?.feedbackType || 'wrong_evidence',
        before: 'AI 草稿证据或依据待复核',
        after:
          body?.correctedOutput?.[0]?.description ||
          '建议补齐证据页码、bbox、规则编号和知识条款映射。',
        rootCause: body?.rootCause || 'prompt_error',
        status: 'created',
        shouldEnterEvaluationSet: body?.shouldEnterEvaluationSet ?? true,
        comment: body?.comment || 'FDE 诊断修正，不改变正式业务结论。',
        createdAt: serverTime
      }
      state.fdeReviewFeedbacks.unshift(record)
      return ok({
        feedback: {
          ...record,
          source: 'fde_review_run_diagnostic',
          governanceState: 'needs_triage'
        },
        reviewRun: buildMockFdeReviewRunDetail(reviewRunId).run,
        auditLogId: 'AUD-FDE-REVIEW-FEEDBACK',
        businessImpactPolicy: 'diagnostic_only_no_business_state_change'
      })
    }
  },
  {
    url: /\/api\/fde\/review-runs\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => ok(buildMockFdeReviewRunDetail(pathParts(url)[3] || 'RR-LOCAL'))
  },
  {
    url: '/api/fde/feedback',
    method: 'get',
    timeout,
    response: () =>
      ok([
        {
          id: 'FDB-001',
          aiRunId: state.aiRuns[0]?.id,
          projectId,
          nodeId: 24,
          feedbackType: 'edited',
          accepted: false,
          comment: 'AI 建议方向正确，但外部查询截图需要人工确认来源。',
          status: 'triaged',
          rootCause: 'evidence_scope_needs_human',
          shouldEnterEvaluationSet: true,
          createdAt: serverTime
        }
      ])
  },
  {
    url: '/api/fde/evaluation-sets',
    method: 'get',
    timeout,
    response: () =>
      ok({
        sets: [
          {
            id: 'ESET-OCR-RELEASE',
            name: 'OCR Release 回归集',
            setType: 'ocr_release',
            caseCount: 12,
            status: 'active'
          },
          {
            id: 'ESET-AGENT-GOLDEN',
            name: 'Agent 审查金标集',
            setType: 'agent_golden',
            caseCount: 8,
            status: 'active'
          }
        ],
        cases: [
          {
            id: 'ECASE-001',
            evaluationCaseId: 'ECASE-001',
            scenario: 'pageindex_evidence',
            expectedRoute: 'pageindex_tree_search',
            riskLevel: 'high',
            status: 'active'
          }
        ],
        runs: [],
        reports: []
      })
  },
  {
    url: '/api/fde/capability-bundles',
    method: 'get',
    timeout,
    response: () =>
      ok({
        bundles: [],
        agents: [],
        prompts: [],
        modelRoutes: [],
        ocrProfiles: []
      })
  },
  {
    url: '/api/fde/releases',
    method: 'get',
    timeout,
    response: () => ok({ plans: [], approvals: [], gates: [] })
  },
  {
    url: '/api/fde/ocr-quality',
    method: 'get',
    timeout,
    response: () => ok(buildMockFdeOcrQuality())
  },
  {
    url: '/api/fde/ocr-runs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const items = buildMockOcrJobs(
        query?.projectId ? String(query.projectId) : undefined,
        Number(query?.nodeId || 0) || undefined
      )
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/fde\/ocr-runs\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => ok(buildMockOcrRunDetail(pathParts(url)[3] || ''))
  },
  {
    url: '/api/fde/ocr-annotation/tasks',
    method: 'get',
    timeout,
    response: ({ query }) =>
      ok(
        buildMockOcrAnnotationPayload(
          query?.projectId ? String(query.projectId) : undefined,
          Number(query?.nodeId || 0) || undefined,
          Number(query?.page) || 1,
          Number(query?.pageSize) || 20
        )
      )
  },
  {
    url: /\/api\/fde\/ocr-annotation\/tasks\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const taskId = pathParts(url)[4]
      const payload = buildMockOcrAnnotationPayload()
      const task =
        payload.page.items.find((item) => item.taskId === taskId) || payload.page.items[0]
      return ok({
        task,
        readiness: { ok: true, summary: payload.summary, nextActions: payload.nextActions }
      })
    }
  },
  {
    url: '/api/fde/ocr-annotation/readiness',
    method: 'post',
    timeout,
    response: () => {
      const payload = buildMockOcrAnnotationPayload()
      return ok({
        ok: true,
        summary: payload.summary,
        nextActions: payload.nextActions,
        tasks: payload.page.items
      })
    }
  },
  {
    url: '/api/fde/incidents',
    method: 'get',
    timeout,
    response: () =>
      ok({
        incidents: [
          {
            id: 'INC-OCR-SEAL-001',
            title: '印章文字识别准确率低于门禁',
            severity: 'warning',
            status: 'monitoring',
            createdAt: serverTime
          }
        ],
        rca: []
      })
  },
  {
    url: '/api/fde/acceptance-reports',
    method: 'get',
    timeout,
    response: () => ok([])
  },
  {
    url: '/api/fde/business-packs/validate-all',
    method: 'post',
    timeout,
    response: () =>
      ok({
        summary: { total: 1, passed: 1, failed: 0, warning: 0 },
        results: [
          {
            summary: {
              id: 'engineering_inspection_v1',
              name: '工程监检业务包',
              version: '2026.06',
              status: 'production'
            },
            validation: { status: 'passed', score: 0.96, blockers: [] }
          }
        ]
      })
  },
  {
    url: '/api/fde/access-grants',
    method: 'get',
    timeout,
    response: () => ok([])
  },
  {
    url: '/api/fde/cost-budgets',
    method: 'get',
    timeout,
    response: () =>
      ok({
        grants: [],
        exports: [],
        budgets: [{ id: 'BUDGET-FDE-LOCAL', name: '本地开发预算', limit: 1000, used: 38 }],
        changeRequests: [],
        usage: { tokenEstimate: 18620, estimatedPrice: 1.42, runCount: 3 }
      })
  },
  {
    url: '/api/fde/audit-events',
    method: 'get',
    timeout,
    response: () => ok({ events: state.auditLogs.slice(0, 20), total: state.auditLogs.length })
  },
  {
    url: '/api/fde/security/masking-policies',
    method: 'get',
    timeout,
    response: () =>
      ok([
        {
          id: 'MASK-FDE-DEFAULT',
          name: 'FDE 默认脱敏',
          status: 'active',
          fields: ['document.rawText', 'credentialNo', 'phone']
        }
      ])
  },
  {
    url: '/api/workbench/projects',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const role = getRole(query)
      return ok(
        state.projects.map((project) => ({
          ...project,
          currentNodeId: roleNodeMap[role] || project.currentNodeId,
          actions: getProjectActions(project, role)
        }))
      )
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/members\/[^/]+/,
    method: 'put',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '更新项目成员授权' })
      if (error) return error
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const memberId = parts[4]
      const member = state.projectMembers.find(
        (item) => item.projectId === id && item.id === memberId
      )
      if (!member) return fail(40486, '项目成员不存在。', { reason: 'PROJECT_MEMBER_NOT_FOUND' })
      const before = { ...member }
      if (body?.role) member.role = body.role
      if (Array.isArray(body?.nodeScope)) member.nodeScope = body.nodeScope.map(Number)
      if (Array.isArray(body?.actions)) member.actions = body.actions
      if (body?.status) member.status = body.status
      if (typeof body?.expiresAt === 'string') member.expiresAt = body.expiresAt || undefined
      member.updatedAt = serverTime
      const auditLogId = addAuditLog('更新项目成员授权', 'ProjectMember', member.id)
      return ok({
        member,
        auditLogId,
        changed: [
          { field: 'role', before: before.role, after: member.role },
          { field: 'nodeScope', before: before.nodeScope, after: member.nodeScope },
          { field: 'actions', before: before.actions, after: member.actions }
        ]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/members/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const id = pathParts(url)[2] || projectId
      const role = String(query?.role || '').trim()
      const items = getProjectMembers(id).filter((member) => {
        if (role && member.role !== role) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/members/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '项目成员授权' })
      if (error) return error
      const id = pathParts(url)[2] || projectId
      const project = getProject(id)
      const role = (body?.role || 'inspection') as RoleCode
      const userId = String(body?.userId || '').trim()
      if (!userId) return fail(40086, '成员用户不能为空。', { reason: 'USER_REQUIRED' })
      if (!Array.isArray(body?.nodeScope) || !body.nodeScope.length) {
        return fail(40087, '成员节点范围不能为空。', { reason: 'NODE_SCOPE_REQUIRED' })
      }
      const user = getAdminUserSnapshot(userId, role)
      const existing = state.projectMembers.find(
        (member) => member.projectId === id && member.userId === userId
      )
      const member: ProjectMemberMock = existing || {
        id: `PM-${id}-${Date.now()}-${state.projectMembers.length + 1}`,
        projectId: id,
        userId,
        name: user.name,
        orgName: user.orgName,
        role,
        nodeScope: [],
        actions: [],
        status: '启用',
        updatedAt: serverTime
      }
      member.role = role
      member.nodeScope = body.nodeScope.map(Number)
      member.actions = Array.isArray(body?.actions) ? body.actions : initialMemberActions[role]
      member.expiresAt = body?.expiresAt || undefined
      member.status = project.status === '已归档' ? '停用' : '启用'
      member.updatedAt = serverTime
      if (!existing) state.projectMembers.unshift(member)
      const auditLogId = addAuditLog('项目成员授权', 'ProjectMember', member.id)
      return ok({ member, auditLogId })
    }
  },
  {
    url: /\/api\/projects\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const id = pathParts(url)[2] || projectId
      return ok(buildAdminProjectDetail(id))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/workbench\/context/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const role = getRole(query)
      const project = getProject(pathParts(url)[2])
      const currentNodeId = roleNodeMap[role] || project.currentNodeId
      refreshProjectCounters(project.id)
      return ok({
        project: { ...project, currentNodeId, actions: getProjectActions(project, role) },
        role,
        currentNodeId,
        topbar: {
          todoCount: project.todoCount,
          messageCount: project.messageCount,
          statusText: project.status,
          projectSwitcherEnabled: true
        },
        actions: getProjectActions(project, role)
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/workbench\/summary/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const role = getRole(query)
      const id = pathParts(url)[2] || projectId
      const correctionCount = state.treeNodes.filter(
        (node) => node.projectId === id && ['需补正', '补正中'].includes(node.status)
      ).length
      const passedCount = state.treeNodes.filter(
        (node) => node.projectId === id && node.status === '已通过'
      ).length
      const roleTodos = getRoleTodos(role, id)
      const reportCount = state.reports.filter((report) => report.projectId === id).length
      const archiveCount = state.archiveItems.filter((item) => item.projectId === id).length
      const metrics =
        role === 'owner'
          ? [
              {
                key: 'progress',
                label: '总体进度',
                value: `${Math.round((passedCount / 69) * 100)}%`,
                tone: 'blue'
              },
              { key: 'report', label: '报告版本', value: reportCount, tone: 'green' },
              { key: 'archive', label: '归档资料', value: archiveCount, tone: 'gray' }
            ]
          : [
              { key: 'todo', label: '待办', value: roleTodos.length, tone: 'orange' },
              { key: 'correction', label: '补正项', value: correctionCount, tone: 'red' },
              { key: 'evidence', label: '证据引用', value: evidenceLinks.length, tone: 'blue' },
              { key: 'passed', label: '已通过节点', value: passedCount, tone: 'green' }
            ]
      return ok({
        metrics,
        todos: roleTodos,
        messages: state.messages.filter(
          (message) => !message.projectId || message.projectId === id
        ),
        updatedAt: serverTime
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/tree/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const project = getProject(pathParts(url)[2])
      return ok({
        project,
        groups: getProjectGroups(project.id)
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/nodes\/[^/]+\/package/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[4]) || 24
      updateNodeFileProgress(id, nodeId)
      const node = getNode(id, nodeId)
      const nodeBindings = state.bindings.filter(
        (binding) => binding.projectId === id && binding.nodeId === node.nodeId
      )
      const projectFiles = state.documents.filter((document) => document.projectId === id)
      return ok({
        node,
        requirements: requirements.filter((item) => item.nodeId === node.nodeId),
        bindings: nodeBindings,
        projectFiles,
        availableVersions: state.versions.filter((version) =>
          projectFiles.some((document) => document.id === version.documentId)
        ),
        extractedFields,
        reviewOpinions: state.reviewOpinions.filter(
          (item) => item.projectId === id && item.nodeId === node.nodeId
        ),
        aiRuns: state.aiRuns.filter((item) => item.projectId === id && item.nodeId === node.nodeId),
        actions: node.actions
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/documents\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const documentId = parts[4]
      const document = state.documents.find(
        (item) => item.projectId === id && item.id === documentId
      )
      if (!document) return fail(40421, '文件不存在或已被移除。', { reason: 'DOCUMENT_NOT_FOUND' })
      const documentVersions = state.versions.filter(
        (version) => version.documentId === document.id
      )
      const currentVersion =
        documentVersions.find((version) => version.id === document.currentVersionId) ||
        documentVersions[0]
      const documentBindings = state.bindings.filter(
        (binding) => binding.projectId === id && binding.documentId === document.id
      )
      const documentFields = extractedFields.filter((field) =>
        documentVersions.some((version) => version.id === field.documentVersionId)
      )
      const fieldEvidenceIds = new Set(documentFields.map((field) => field.evidenceLinkId))
      const documentEvidence = evidenceLinks.filter(
        (link) =>
          link.objectId === document.currentVersionId ||
          fieldEvidenceIds.has(link.id) ||
          documentFields.some((field) => field.id === link.objectId)
      )
      const signedUrls = getDocumentSignedUrls(document, currentVersion)
      return ok({
        document,
        currentVersion,
        versions: documentVersions,
        bindings: documentBindings,
        extractedFields: documentFields,
        evidenceLinks: documentEvidence,
        preview: signedUrls.preview,
        download: signedUrls.download
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/documents\/[^/]+\/preview-url/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const documentId = parts[4]
      const document = state.documents.find(
        (item) => item.projectId === id && item.id === documentId
      )
      if (!document) return fail(40421, '文件不存在或已被移除。', { reason: 'DOCUMENT_NOT_FOUND' })
      const version = state.versions.find((item) => item.id === document.currentVersionId)
      return ok(getDocumentSignedUrls(document, version).preview)
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/documents\/[^/]+\/download-url/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const documentId = parts[4]
      const document = state.documents.find(
        (item) => item.projectId === id && item.id === documentId
      )
      if (!document) return fail(40421, '文件不存在或已被移除。', { reason: 'DOCUMENT_NOT_FOUND' })
      const version = state.versions.find((item) => item.id === document.currentVersionId)
      return ok(getDocumentSignedUrls(document, version).download)
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/documents\/upload-session/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const mutationError = getMutationError(id, { body, query, action: '创建上传会话' })
      if (mutationError) return mutationError
      const files = body?.files || [{ fileName: '未命名文件.pdf', fileSize: 1024, fileType: 'pdf' }]
      const allowedTypes = ['pdf', 'xlsx', 'xls', 'docx', 'jpg', 'png']
      const invalidFile = files.find(
        (file) => !allowedTypes.includes(String(file.fileType || '').toLowerCase())
      )
      if (invalidFile) {
        return fail(40015, `暂不支持 ${invalidFile.fileName || '未命名文件'} 的文件类型。`, {
          reason: 'UNSUPPORTED_FILE_TYPE'
        })
      }
      const oversizedFile = files.find((file) => Number(file.fileSize || 0) > 50 * 1024 * 1024)
      if (oversizedFile) {
        return fail(40016, `${oversizedFile.fileName || '未命名文件'} 超过 50MB 上传限制。`, {
          reason: 'FILE_TOO_LARGE'
        })
      }
      const uploadUrls = files.map((file, index) => {
        const seed = `${Date.now()}-${index}`
        const documentId = `DOC-MOCK-${seed}`
        const documentVersionId = `DV-MOCK-${seed}-V1`
        const document: DocumentAsset = {
          id: documentId,
          projectId: id,
          fileName: file.fileName || '未命名文件.pdf',
          fileType: file.fileType || 'pdf',
          sourceOrgName: getProject(id).contractorOrgName,
          uploaderName: '李工',
          currentVersionId: documentVersionId,
          fileStatus: '已上传',
          currentOcrStatus: '识别中',
          updatedAt: serverTime,
          actions: ['file:view', 'file:bind', 'file:preview', 'file:download']
        }
        const version: DocumentVersion = {
          id: documentVersionId,
          documentId,
          versionNo: 'V1',
          hash: `mock-sha256-${documentId}`,
          fileSize: file.fileSize || 1024,
          uploaderName: document.uploaderName,
          uploadTime: serverTime,
          isCurrent: true
        }
        state.documents.unshift(document)
        state.versions.unshift(version)
        return {
          fileName: document.fileName,
          documentId,
          documentVersionId,
          url: `mock://upload/${seed}`,
          method: 'PUT',
          expiresAt: '2026-06-26 11:00:00',
          headers: { 'Content-Type': file.fileType || 'application/octet-stream' }
        }
      })
      addMessage({
        title: '资料已上传',
        content: `${uploadUrls.length} 个文件已进入项目资料池。`,
        projectId: id,
        targetType: 'document',
        targetId: uploadUrls[0]?.documentId || ''
      })
      return ok({
        uploadSessionId: `UP-${Date.now()}`,
        expiresAt: '2026-06-26 11:00:00',
        uploadUrls
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/documents\/bindings/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const nodeId = Number(body?.nodeId) || roleNodeMap.contractor
      const requestedNodeIds = Array.isArray(body?.nodeIds) ? (body.nodeIds as unknown[]) : []
      const nodeIds: number[] = requestedNodeIds.length
        ? Array.from(
            new Set(
              requestedNodeIds
                .map(Number)
                .filter((item): item is number => Number.isFinite(item) && item > 0)
            )
          )
        : [nodeId]
      const mutationError = getNodeMutationError(id, nodeIds[0], {
        body,
        query,
        action: '挂载资料'
      })
      if (mutationError) return mutationError
      const payloadBindings = body?.bindings?.length
        ? body.bindings
        : state.documents
            .filter((document) => document.projectId === id)
            .slice(0, 1)
            .map((document) => ({
              documentId: document.id,
              documentVersionId: document.currentVersionId,
              usage: '原始提交'
            }))
      if (!payloadBindings.length) {
        return fail(40020, '请选择至少一个项目资料后再挂载。', { reason: 'EMPTY_BINDINGS' })
      }
      const missingDocument = payloadBindings.find(
        (item) => !state.documents.some((document) => document.id === item.documentId)
      )
      if (missingDocument) {
        return fail(40420, '选择的项目资料不存在或已被移除。', { reason: 'DOCUMENT_NOT_FOUND' })
      }
      const createdBindings: NodeFileBinding[] = nodeIds.flatMap((currentNodeId, nodeIndex) => {
        const nodeRequirements = requirements.filter((item) => item.nodeId === currentNodeId)
        return payloadBindings.map((item, index) => {
          const document = state.documents.find((candidate) => candidate.id === item.documentId)
          const version = state.versions.find(
            (candidate) => candidate.id === item.documentVersionId
          )
          const requirement = nodeRequirements[index % Math.max(nodeRequirements.length, 1)]
          return {
            id: `BIND-MOCK-${Date.now()}-${nodeIndex}-${index}`,
            projectId: id,
            nodeId: currentNodeId,
            requirementId: requirement?.id,
            requirementName: requirement?.name,
            documentId: item.documentId,
            documentVersionId: item.documentVersionId,
            fileName: document?.fileName || '未命名文件.pdf',
            versionNo: version?.versionNo || 'V1',
            usage: item.usage || '原始提交',
            sourceOrgName: document?.sourceOrgName || getProject(id).contractorOrgName,
            bindingStatus: '草稿挂载',
            boundAt: serverTime,
            actions: ['submission:draft', 'submission:submit']
          }
        })
      })
      state.bindings.unshift(...createdBindings)
      const changed: Array<{ field: string; before?: string; after: string }> = []
      nodeIds.forEach((currentNodeId) => {
        updateNodeFileProgress(id, currentNodeId)
        const { before } = setNodeStatus(id, currentNodeId, '部分提交')
        changed.push({ field: `nodes.${currentNodeId}.status`, before, after: '部分提交' })
      })
      return ok({
        id: `MUT-${Date.now()}`,
        objectType: 'binding',
        objectId: createdBindings[0]?.id || 'BIND-MOCK',
        nextStatus: '部分提交',
        changed,
        auditLogId: addAuditLog(
          '跨节点挂载资料',
          'NodeFileBinding',
          createdBindings[0]?.id || 'BIND-MOCK'
        )
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions\/drafts\/[^/]+/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const draftId = parts[5]
      const draft = state.submissionDrafts.find(
        (item) => item.projectId === id && item.draftId === draftId
      )
      if (!draft) return fail(40430, '提交草稿不存在或已被覆盖。', { reason: 'DRAFT_NOT_FOUND' })
      return ok(buildSubmissionDraftDetail(draft))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions\/drafts/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const nodeId = Number(body?.nodeId) || roleNodeMap.contractor
      const requestedNodeIds = Array.isArray(body?.nodeIds) ? (body.nodeIds as unknown[]) : []
      const nodeIds: number[] = requestedNodeIds.length
        ? Array.from(
            new Set(
              requestedNodeIds
                .map(Number)
                .filter((item): item is number => Number.isFinite(item) && item > 0)
            )
          )
        : [nodeId]
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '保存提交草稿'
      })
      if (mutationError) return mutationError
      const bindingIds = resolveSubmissionBindingIds(
        id,
        nodeIds,
        Array.isArray(body?.bindingIds) ? body.bindingIds : []
      )
      const draftId = `SUB-DRAFT-${Date.now()}`
      const draft: SubmissionDraftMock = {
        draftId,
        projectId: id,
        nodeIds,
        bindingIds,
        batchName: body?.batchName,
        remark: body?.remark,
        savedAt: serverTime
      }
      state.submissionDrafts.unshift(draft)
      addAuditLog('保存提交草稿', 'SubmissionDraft', draftId)
      return ok({
        draftId,
        savedAt: serverTime,
        bindingIds
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const id = pathParts(url)[2] || projectId
      return ok(buildSubmissionHistory(id))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions$/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const nodeId = Number(body?.nodeId) || roleNodeMap.contractor
      const nodeIds = Array.isArray(body?.nodeIds) && body.nodeIds.length ? body.nodeIds : [nodeId]
      const mutationError = getNodeMutationError(id, nodeIds[0], {
        body,
        query,
        action: '提交节点资料'
      })
      if (mutationError) return mutationError
      const selectedBindingIds = Array.isArray(body?.bindingIds) ? body.bindingIds : []
      const selectedBindings = state.bindings.filter((binding) => {
        if (binding.projectId !== id || !nodeIds.includes(binding.nodeId)) return false
        return selectedBindingIds.length ? selectedBindingIds.includes(binding.id) : true
      })
      if (!selectedBindings.length) {
        return fail(40920, '当前批次还没有可提交的挂载资料。', { reason: 'EMPTY_NODE_PACKAGE' })
      }
      const changed: Array<{ field: string; before?: string; after: string }> = []
      nodeIds.forEach((currentNodeId) => {
        const nodeBindings = selectedBindings.filter((binding) => binding.nodeId === currentNodeId)
        if (!nodeBindings.length) return
        const { before } = setNodeStatus(id, currentNodeId, 'AI 预审中')
        changed.push({ field: `nodes.${currentNodeId}.status`, before, after: 'AI 预审中' })
      })
      state.bindings.forEach((binding) => {
        if (selectedBindings.some((item) => item.id === binding.id)) {
          binding.bindingStatus = '已提交'
          binding.actions = ['review:save', 'review:return-correction']
        }
      })
      setProjectStatus(id, 'AI 预审中', nodeIds[0])
      const submissionId = `SUB-${Date.now()}`
      const createdTodo = addTodo({
        title: `${body?.batchName || `节点 ${nodeIds.join('、')} 资料`}待 AI 预审确认`,
        projectId: id,
        nodeId: nodeIds[0],
        targetType: 'submission',
        targetId: submissionId,
        status: '待处理',
        priority: '中',
        deadline: '2026-06-27 18:00:00',
        assigneeName: '张工',
        actions: ['ai:recheck']
      })
      const snapshotId = `SNAP-${Date.now()}`
      state.submissionSnapshots.unshift({
        submissionId,
        snapshotId,
        projectId: id,
        nodeIds,
        bindingIds: selectedBindings.map((binding) => binding.id),
        batchName: body?.batchName,
        submitterComment: body?.submitterComment,
        nextStatus: 'AI 预审中',
        submittedAt: serverTime,
        createdTodoIds: [createdTodo.id],
        changed
      })
      addMessage({
        title: '节点资料已提交',
        content: `节点 ${nodeIds.join('、')} 已提交，进入 AI 预审。`,
        projectId: id,
        targetType: 'submission',
        targetId: createdTodo.targetId
      })
      return ok({
        submissionId,
        snapshotId,
        nextStatus: 'AI 预审中',
        changed,
        createdTodos: [createdTodo]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const submissionId = parts[4]
      const snapshot = state.submissionSnapshots.find(
        (item) => item.projectId === id && item.submissionId === submissionId
      )
      if (!snapshot) {
        return fail(40431, '提交批次不存在或快照已过期。', { reason: 'SUBMISSION_NOT_FOUND' })
      }
      return ok(buildSubmissionDetail(snapshot))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/submissions\/[^/]+\/withdraw-items/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const submissionId = parts[4] || `SUB-${Date.now()}`
      const mutationError = getMutationError(id, { body, query, action: '撤回提交项' })
      if (mutationError) return mutationError
      if (!body?.reason) {
        return fail(40021, '撤回原因不能为空。', { reason: 'WITHDRAW_REASON_REQUIRED' })
      }
      const selectedBindingIds = Array.isArray(body?.bindingIds) ? body.bindingIds : []
      const selectedVersionIds = Array.isArray(body?.documentVersionIds)
        ? body.documentVersionIds
        : []
      const targetBindings = state.bindings.filter((binding) => {
        if (binding.projectId !== id) return false
        if (selectedBindingIds.length && selectedBindingIds.includes(binding.id)) return true
        if (selectedVersionIds.length && selectedVersionIds.includes(binding.documentVersionId))
          return true
        return false
      })
      if (!targetBindings.length) {
        return fail(40421, '没有找到可撤回的提交项。', { reason: 'WITHDRAW_ITEM_NOT_FOUND' })
      }
      const lockedBinding = targetBindings.find((binding) => binding.bindingStatus === '已通过')
      if (lockedBinding) {
        return fail(40921, '已通过资料不能撤回。', { reason: 'WITHDRAW_LOCKED' })
      }
      const affectedNodeIds = Array.from(new Set(targetBindings.map((binding) => binding.nodeId)))
      const changed: Array<{ field: string; before?: unknown; after: unknown }> = []
      targetBindings.forEach((binding) => {
        changed.push({
          field: `bindings.${binding.id}.bindingStatus`,
          before: binding.bindingStatus,
          after: '草稿挂载'
        })
        binding.bindingStatus = '草稿挂载'
        binding.actions = ['submission:draft', 'submission:submit', 'submission:withdraw']
      })
      affectedNodeIds.forEach((currentNodeId) => {
        const { before } = setNodeStatus(id, currentNodeId, '部分提交')
        changed.push({ field: `nodes.${currentNodeId}.status`, before, after: '部分提交' })
        updateNodeFileProgress(id, currentNodeId)
      })
      setProjectStatus(id, '资料提交中', affectedNodeIds[0])
      const snapshot = state.submissionSnapshots.find(
        (item) => item.projectId === id && item.submissionId === submissionId
      )
      if (snapshot) {
        snapshot.nextStatus = '部分提交'
        snapshot.withdrawal = {
          bindingCount: targetBindings.length,
          reason: String(body.reason),
          withdrawnAt: serverTime
        }
        snapshot.changed.push(...changed)
      }
      addMessage({
        title: '提交项已撤回',
        content: `提交 ${submissionId} 已撤回 ${targetBindings.length} 个资料项：${body.reason}`,
        projectId: id,
        targetType: 'submission',
        targetId: submissionId
      })
      return ok({
        id: `MUT-${Date.now()}`,
        objectType: 'submission',
        objectId: submissionId,
        nextStatus: '部分提交',
        changed,
        auditLogId: addAuditLog('撤回提交项', 'Submission', submissionId),
        affectedIds: targetBindings.map((binding) => binding.id)
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/rectifications/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const nodeId = Number(body?.nodeId) || roleNodeMap.contractor
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '提交补正反馈'
      })
      if (mutationError) return mutationError
      const { before } = setNodeStatus(id, nodeId, '复审中')
      state.bindings.forEach((binding) => {
        if (binding.projectId === id && binding.nodeId === nodeId) binding.bindingStatus = '已提交'
      })
      closeNodeTodos(id, nodeId, '李工')
      setProjectStatus(id, '监检审查中', nodeId)
      const createdTodo = addTodo({
        title: `节点 ${nodeId} 补正资料待复审`,
        projectId: id,
        nodeId,
        targetType: 'rectification',
        targetId: `REC-${Date.now()}`,
        status: '待处理',
        priority: '高',
        deadline: '2026-06-27 18:00:00',
        assigneeName: '张工',
        actions: ['review:save', 'review:return-correction']
      })
      addMessage({
        title: '补正反馈已提交',
        content: `节点 ${nodeId} 已提交补正反馈，等待监检复审。`,
        projectId: id,
        targetType: 'rectification',
        targetId: createdTodo.targetId
      })
      return ok({
        rectification: { id: createdTodo.targetId, projectId: id, nodeId, status: '已反馈' },
        nextStatus: '复审中',
        changed: [{ field: 'status', before, after: '复审中' }],
        createdTodos: [createdTodo]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/ai-recheck/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const mutationError = getNodeMutationError(id, nodeId, { body, query, action: 'AI 复核' })
      if (mutationError) return mutationError
      const node = getNode(id, nodeId)
      const run: AiReviewRun = {
        id: `AIRUN-${nodeId}-${Date.now()}`,
        projectId: id,
        nodeId,
        subject: node.name,
        model: 'LLM-A',
        promptVersion: `${nodeId}-mock-v1`,
        ruleVersion: 'rule-v2026.06',
        status: '完成',
        suggestion: {
          id: `AIS-${nodeId}-${Date.now()}`,
          result: '需人工确认',
          opinionDraft: `${node.name} 已完成 AI 复核，建议结合证据链进行人工确认。`,
          confidence: 0.86,
          manualConfirmItems: ['证据链页码', '外部来源一致性']
        },
        evidenceLinks: getEvidenceForNode(nodeId),
        finishedAt: serverTime
      }
      state.aiRuns.unshift(run)
      const { before } = setNodeStatus(id, nodeId, '待人工确认')
      setProjectStatus(id, '监检审查中', nodeId)
      addMessage({
        title: 'AI 复核完成',
        content: `节点 ${nodeId} 已生成新的 AI 审查建议。`,
        projectId: id,
        targetType: 'node',
        targetId: String(nodeId)
      })
      return ok({
        runId: run.id,
        status: '完成',
        changed: [{ field: 'status', before, after: '待人工确认' }],
        latestRun: run
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/review-opinions/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '保存审查意见'
      })
      if (mutationError) return mutationError
      if (!body?.opinion) {
        return fail(40030, '人工审查意见不能为空。', { reason: 'REVIEW_OPINION_REQUIRED' })
      }
      const result = body?.result || '满足要求'
      const opinion: ReviewOpinion = {
        id: `OPN-${Date.now()}`,
        projectId: id,
        nodeId,
        result,
        opinion: body?.opinion || '审查意见已保存。',
        evidenceLinkIds: body?.evidenceLinkIds || ['EV-24-001'],
        reviewerName: '张工',
        createdAt: serverTime
      }
      state.reviewOpinions.unshift(opinion)
      const nextStatus: NodeStatus = result === '需补正' ? '需补正' : '已通过'
      const { before } = setNodeStatus(id, nodeId, nextStatus)
      state.bindings.forEach((binding) => {
        if (binding.projectId === id && binding.nodeId === nodeId) {
          binding.bindingStatus = nextStatus === '已通过' ? '已通过' : '需补正'
        }
      })
      if (nextStatus === '已通过') closeNodeTodos(id, nodeId, '张工')
      addAuditLog('保存审查意见', 'ReviewOpinion', opinion.id)
      refreshProjectCounters(id)
      return ok({
        opinion,
        nextStatus,
        changed: [{ field: 'status', before, after: nextStatus }]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/ai-suggestions\/[^/]+\/adopt/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const suggestionId = parts[7]
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '采纳 AI 建议'
      })
      if (mutationError) return mutationError
      const run = state.aiRuns.find((item) => item.suggestion.id === suggestionId)
      if (!run) {
        return fail(40430, 'AI 建议不存在或已过期。', { reason: 'AI_SUGGESTION_NOT_FOUND' })
      }
      const draftOpinion: ReviewOpinion = {
        id: `DRAFT-OPN-${Date.now()}`,
        projectId: id,
        nodeId,
        result: body?.result || '满足要求',
        opinion: body?.opinion || run.suggestion.opinionDraft,
        evidenceLinkIds: run.evidenceLinks.map((item) => item.id),
        reviewerName: '张工',
        createdAt: serverTime
      }
      const auditLogId = addAuditLog('采纳 AI 建议为草稿', 'AiSuggestion', suggestionId)
      return ok({
        draftOpinion,
        auditLogId
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/ai-suggestions\/[^/]+\/reject/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const suggestionId = parts[7]
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '驳回 AI 建议'
      })
      if (mutationError) return mutationError
      const run = state.aiRuns.find((item) => item.suggestion.id === suggestionId)
      if (!run) {
        return fail(40430, 'AI 建议不存在或已过期。', { reason: 'AI_SUGGESTION_NOT_FOUND' })
      }
      run.status = '已人工确认'
      addMessage({
        title: 'AI 建议已驳回',
        content: body?.reason || '监检人员已驳回 AI 建议。',
        projectId: id,
        targetType: 'node',
        targetId: String(nodeId)
      })
      return createMutation('AiSuggestion', suggestionId, '已人工确认', '完成')
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/actions\/return-correction/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const mutationError = getNodeMutationError(id, nodeId, { body, query, action: '退回补正' })
      if (mutationError) return mutationError
      if (!body?.reason) {
        return fail(40031, '退回补正原因不能为空。', { reason: 'CORRECTION_REASON_REQUIRED' })
      }
      const { before } = setNodeStatus(id, nodeId, '需补正')
      state.bindings.forEach((binding) => {
        if (binding.projectId === id && binding.nodeId === nodeId) binding.bindingStatus = '需补正'
      })
      setProjectStatus(id, '退回补正中', nodeId)
      const createdTodo = addTodo({
        title: `节点 ${nodeId} 资料需补正`,
        projectId: id,
        nodeId,
        targetType: 'rectification',
        targetId: `REC-${Date.now()}`,
        status: '待处理',
        priority: '高',
        deadline: '2026-06-28 18:00:00',
        assigneeName: '李工',
        actions: ['rectification:submit']
      })
      const createdMessage = addMessage({
        title: '退回补正提醒',
        content: `节点 ${nodeId} 已退回补正：${body.reason}`,
        projectId: id,
        targetType: 'rectification',
        targetId: createdTodo.targetId
      })
      return ok({
        rectification: { id: createdTodo.targetId, projectId: id, nodeId, status: '待补正' },
        nextStatus: '需补正',
        changed: [{ field: 'status', before, after: '需补正' }],
        createdTodos: [createdTodo],
        messages: [createdMessage]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/evidence-chain/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = getNodeId(undefined, Number(parts[5]) || 24)
      const links = getEvidenceForNode(nodeId)
      return ok({
        node: getNode(id, nodeId),
        links,
        groupedByObject: [{ objectType: 'documentVersion', links }]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/standards/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = getNodeId(undefined, Number(parts[5]) || 24)
      return ok(buildStandardReferences(id, nodeId))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/date-compare/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = getNodeId(undefined, Number(parts[5]) || 24)
      return ok(buildDateComparisons(id, nodeId))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/inspection\/nodes\/[^/]+\/report-review/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const nodeId = Number(parts[5]) || 24
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '生成报告草稿'
      })
      if (mutationError) return mutationError
      const reportScope: ReportVersion['scope'] = body?.reportScope || 'currentNode'
      const nodeIds =
        reportScope === 'project'
          ? state.treeNodes
              .filter(
                (node) => node.projectId === id && ['已通过', '待人工确认'].includes(node.status)
              )
              .map((node) => node.nodeId)
              .slice(0, 12)
          : [nodeId]
      if (!nodeIds.includes(nodeId)) nodeIds.unshift(nodeId)
      const report: ReportVersion = {
        id: `RPT-${Date.now()}`,
        projectId: id,
        reportNo: `GDJ-JJ-${new Date().getFullYear()}-${String(state.reports.length + 1).padStart(3, '0')}`,
        versionNo: 'V1',
        title: `${getProject(id).name}监督检验报告`,
        status: '复核中',
        scope: reportScope,
        nodeIds,
        generatedAt: serverTime,
        reviewerName: '张工',
        previewUrl: `mock://preview/reports/${Date.now()}`,
        exportUrl: `mock://download/reports/${Date.now()}.pdf`,
        actions: ['report:view', 'report:export', 'report:archive']
      }
      state.reports.unshift(report)
      state.archiveItems.unshift({
        id: `ARCH-${report.id}`,
        projectId: id,
        name: `${report.title}-${report.versionNo}.pdf`,
        type: 'report',
        nodeId,
        sourceOrgName: getProject(id).inspectionOrgName,
        status: report.status,
        updatedAt: serverTime,
        downloadUrl: report.exportUrl
      })
      const { before } = setNodeStatus(id, nodeId, '报告生成/复核中')
      setProjectStatus(id, '报告生成/复核中', nodeId)
      const createdTodo = addTodo({
        title: `报告 ${report.reportNo} 待复核`,
        projectId: id,
        nodeId,
        targetType: 'report',
        targetId: report.id,
        status: '待处理',
        priority: '中',
        deadline: '2026-06-29 18:00:00',
        assigneeName: '张工',
        actions: ['report:review', 'report:export', 'report:archive']
      })
      addMessage({
        title: '报告草稿已生成',
        content: `报告 ${report.reportNo} 已进入复核。${body?.includeEvidence ? '已包含证据链。' : ''}`,
        projectId: id,
        targetType: 'report',
        targetId: report.id
      })
      addAuditLog('生成报告草稿', 'ReportVersion', report.id)
      return ok({
        report,
        nextStatus: '报告生成/复核中',
        changed: [{ field: 'status', before, after: '报告生成/复核中' }],
        createdTodos: [createdTodo]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/owner\/reports/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const id = pathParts(url)[2] || projectId
      return ok(state.reports.filter((report) => report.projectId === id))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/reports$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const id = pathParts(url)[2] || projectId
      const items = state.reports.filter((report) => report.projectId === id)
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/reports\/[^/?]+(?:\?.*)?$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const reportId = parts[4]
      const report = state.reports.find((item) => item.projectId === id && item.id === reportId)
      if (!report) return fail(40450, '报告不存在或已被移除。', { reason: 'REPORT_NOT_FOUND' })
      return ok(buildReportDetail(id, report))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/reports\/[^/]+\/export/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const reportId = parts[4]
      const mutationError = getMutationError(id, { body, query, action: '导出报告' })
      if (mutationError) return mutationError
      const report = state.reports.find((item) => item.projectId === id && item.id === reportId)
      if (!report) return fail(40450, '报告不存在或已被移除。', { reason: 'REPORT_NOT_FOUND' })
      const format = body?.format === 'docx' ? 'docx' : 'pdf'
      const exportId = `EXP-${Date.now()}`
      report.exportUrl = `mock://download/reports/${report.id}.${format}`
      report.actions = Array.from(new Set([...report.actions, 'report:export']))
      makeExportTask(id, {
        id: exportId,
        exportType: 'report',
        fileName: `${report.title}-${report.versionNo}.${format}`,
        downloadUrl: report.exportUrl,
        fileSize: 1536 * 1024
      })
      addMessage({
        title: '报告导出任务已创建',
        content: `报告 ${report.reportNo} 已创建 ${format.toUpperCase()} 导出任务。`,
        projectId: id,
        targetType: 'report',
        targetId: report.id
      })
      addAuditLog('导出报告', 'ReportVersion', report.id)
      return ok({ exportId, report })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/reports\/[^/]+\/archive/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const reportId = parts[4]
      const mutationError = getMutationError(id, { body, query, action: '报告归档' })
      if (mutationError) return mutationError
      const report = state.reports.find((item) => item.projectId === id && item.id === reportId)
      if (!report) return fail(40450, '报告不存在或已被移除。', { reason: 'REPORT_NOT_FOUND' })
      report.status = '已归档'
      report.actions = ['report:view', 'archive:view', 'archive:download']
      if (!report.exportUrl) report.exportUrl = `mock://download/reports/${report.id}.pdf`
      const exists = state.archiveItems.some((item) => item.id === `ARCH-${report.id}`)
      if (!exists) {
        state.archiveItems.unshift({
          id: `ARCH-${report.id}`,
          projectId: id,
          name: `${report.title}-${report.versionNo}.pdf`,
          type: 'report',
          nodeId: report.nodeIds[0],
          sourceOrgName: getProject(id).inspectionOrgName,
          status: '已归档',
          updatedAt: serverTime,
          downloadUrl: report.exportUrl
        })
      }
      closeNodeTodos(id, report.nodeIds[0], '张工')
      setProjectStatus(id, '已归档', report.nodeIds[0])
      addMessage({
        title: '报告已归档',
        content: body?.archiveNote || `报告 ${report.reportNo} 已完成归档。`,
        projectId: id,
        targetType: 'report',
        targetId: report.id
      })
      addAuditLog('报告归档', 'ReportVersion', report.id)
      return ok({ report, nextStatus: '已归档' })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/archive\/package/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const id = pathParts(url)[2] || projectId
      const forcedError = getForcedMutationError({ query, action: '生成归档包' })
      if (forcedError) return forcedError
      const items = state.archiveItems.filter((item) => item.projectId === id)
      const exportId = `EXP-ARCHIVE-${Date.now()}`
      const fileName = `${getProject(id).code}-归档资料包.zip`
      const fileSize = Math.max(items.length, 1) * 1024 * 1024
      const downloadUrl = `mock://download/archive/${id}-${exportId}.zip`
      makeExportTask(id, {
        id: exportId,
        exportType: 'archive-package',
        fileName,
        downloadUrl,
        fileSize
      })
      addAuditLog('下载归档包', 'ProjectArchive', id)
      return ok({
        exportId,
        projectId: id,
        packageType: 'archive',
        itemCount: items.length,
        generatedAt: serverTime,
        url: downloadUrl,
        method: 'GET',
        expiresAt: '2026-06-26 11:30:00',
        fileName,
        contentType: 'application/zip',
        fileSize
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/archive\/evidence-package/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const forcedError = getForcedMutationError({ query, action: '生成证据定位包' })
      if (forcedError) return forcedError
      const nodeId = Number(query?.nodeId)
      const evidenceItems = state.archiveItems.filter((item) => {
        if (item.projectId !== id || item.type !== 'evidence') return false
        if (Number.isFinite(nodeId) && nodeId > 0 && item.nodeId !== nodeId) return false
        return true
      })
      const fallbackCount = evidenceLinks.filter((link) => {
        if (!Number.isFinite(nodeId) || nodeId <= 0) return true
        return String(link.id).includes(`-${nodeId}-`)
      }).length
      const itemCount = evidenceItems.length || fallbackCount
      const exportId = `EXP-EVIDENCE-${Date.now()}`
      const fileName = `${getProject(id).code}-${nodeId ? `节点${nodeId}-` : ''}证据定位包.zip`
      const fileSize = Math.max(itemCount, 1) * 512 * 1024
      const downloadUrl = `mock://download/evidence/${id}-${nodeId || 'all'}-${exportId}.zip`
      makeExportTask(id, {
        id: exportId,
        exportType: 'evidence-package',
        fileName,
        downloadUrl,
        fileSize
      })
      addAuditLog('下载证据定位包', 'EvidencePackage', id)
      return ok({
        exportId,
        projectId: id,
        packageType: 'evidence',
        itemCount,
        generatedAt: serverTime,
        url: downloadUrl,
        method: 'GET',
        expiresAt: '2026-06-26 11:30:00',
        fileName,
        contentType: 'application/zip',
        fileSize
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/archive$/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const keyword = String(query?.keyword || '').trim()
      const nodeId = Number(query?.nodeId)
      const items = state.archiveItems.filter((item) => {
        if (item.projectId !== id) return false
        if (Number.isFinite(nodeId) && nodeId > 0 && item.nodeId !== nodeId) return false
        if (keyword && !item.name.includes(keyword)) return false
        return true
      })
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/archive\/[^/]+/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const archiveItemId = parts[4]
      const item = state.archiveItems.find(
        (archiveItem) => archiveItem.projectId === id && archiveItem.id === archiveItemId
      )
      if (!item) return fail(40460, '归档资料不存在或已被移除。', { reason: 'ARCHIVE_NOT_FOUND' })
      return ok(buildArchiveItemDetail(id, item))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/export-tasks\/[^/]+/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const exportId = parts[4]
      const task = state.exportTasks.find((task) => task.projectId === id && task.id === exportId)
      if (!task) return fail(40461, '导出任务不存在或已过期。', { reason: 'EXPORT_TASK_NOT_FOUND' })
      return ok({ task })
    }
  },
  {
    url: /\/api\/exports\/[^/]+\/download-url/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const exportId = pathParts(url)[2]
      const task = state.exportTasks.find((task) => task.id === exportId)
      if (!task) return fail(40461, '导出任务不存在或已过期。', { reason: 'EXPORT_TASK_NOT_FOUND' })
      if (task.status === '已过期') {
        return fail(41061, '导出任务下载地址已过期，请重新生成。', {
          reason: 'EXPORT_TASK_EXPIRED'
        })
      }
      if (task.status !== '可下载' || !task.downloadUrl) {
        return fail(40961, '导出任务尚未生成可下载地址。', {
          reason: 'EXPORT_TASK_NOT_READY',
          status: task.status
        })
      }
      return ok({
        url: task.downloadUrl,
        method: 'GET',
        expiresAt: task.expiresAt || '2026-06-27 10:30:00',
        fileName: task.fileName,
        fileSize: task.fileSize,
        contentType: task.fileName.endsWith('.zip') ? 'application/zip' : 'application/pdf'
      })
    }
  },
  {
    url: /\/api\/exports\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const exportId = pathParts(url)[2]
      const task = state.exportTasks.find((task) => task.id === exportId)
      if (!task) return fail(40461, '导出任务不存在或已过期。', { reason: 'EXPORT_TASK_NOT_FOUND' })
      return ok({ task })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/summary/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const id = pathParts(url)[2] || projectId
      const roleTodos = getRoleTodos('ndt', id)
      const feedbackCount = state.ndtFeedback.filter(
        (item) => item.projectId === id && item.status === '待反馈'
      ).length
      return ok({
        metrics: [
          {
            key: 'film',
            label: '底片编号',
            value: state.ndtFilms.filter((film) => film.projectId === id).length,
            tone: 'blue'
          },
          {
            key: 'report',
            label: '检测报告',
            value: state.ndtReports.filter((report) => report.projectId === id).length,
            tone: 'green'
          },
          { key: 'feedback', label: '监检反馈', value: feedbackCount, tone: 'orange' },
          { key: 'todo', label: '待办', value: roleTodos.length, tone: 'red' }
        ],
        todos: roleTodos,
        messages: state.messages.filter(
          (message) => !message.projectId || message.projectId === id
        ),
        updatedAt: serverTime
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/films$/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const keyword = String(query?.keyword || '').trim()
      const items = state.ndtFilms.filter((film) => {
        if (film.projectId !== id) return false
        if (query?.status && film.status !== query.status) return false
        if (query?.method && film.method !== query.method) return false
        if (keyword && !`${film.filmNo}${film.weldNo}${film.pipelineNo || ''}`.includes(keyword)) {
          return false
        }
        return true
      })
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/films$/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const mutationError = getMutationError(id, { body, query, action: '新增无损检测底片' })
      if (mutationError) return mutationError
      if (!body?.filmNo || !body?.weldNo || !body?.method) {
        return fail(40040, '底片编号、焊口编号和检测方法不能为空。', {
          reason: 'NDT_FILM_REQUIRED'
        })
      }
      const methods: NdtFilm['method'][] = ['RT', 'UT', 'MT', 'PT']
      const method = methods.includes(body.method) ? body.method : 'RT'
      const film: NdtFilm = {
        id: `FILM-${Date.now()}`,
        projectId: id,
        filmNo: body.filmNo,
        weldNo: body.weldNo,
        pipelineNo: body.pipelineNo || 'PL-MOCK',
        method,
        testDate: body.testDate || '2026-06-26',
        status: '待提交',
        actions: ['ndt:submit']
      }
      state.ndtFilms.unshift(film)
      addAuditLog('新增无损检测底片', 'NdtFilm', film.id)
      return ok({ film })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/films\/[^/]+/,
    method: 'patch',
    timeout,
    response: ({ body, query, url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const filmId = parts[5]
      const mutationError = getMutationError(id, { body, query, action: '更新无损检测底片' })
      if (mutationError) return mutationError
      const film = state.ndtFilms.find((item) => item.projectId === id && item.id === filmId)
      if (!film) return fail(40440, '底片不存在或已被移除。', { reason: 'NDT_FILM_NOT_FOUND' })
      Object.assign(film, body || {})
      addAuditLog('更新无损检测底片', 'NdtFilm', film.id)
      return ok({ film })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/records$/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const items = state.ndtRecords.filter((record) => {
        if (record.projectId !== id) return false
        if (query?.filmId && record.filmId !== query.filmId) return false
        if (query?.reportId && record.reportId !== query.reportId) return false
        if (query?.sampleStatus && record.sampleStatus !== query.sampleStatus) return false
        return true
      })
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/records\/import/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const mutationError = getMutationError(id, {
        body,
        query,
        action: '导入无损检测记录'
      })
      if (mutationError) return mutationError
      const nodeId = Number(body?.nodeId) || 40
      const rows = Array.isArray(body?.rows) ? body.rows : []
      if (!rows.length) {
        return fail(40041, '检测记录编号、焊口编号和检测方法不能为空。', {
          reason: 'NDT_RECORD_REQUIRED'
        })
      }
      const failed: Array<{ row: number; reason: string }> = []
      const records: NdtRecord[] = []
      rows.forEach((row, index) => {
        if (!row?.recordNo || !row?.weldNo || !row?.method) {
          failed.push({ row: index + 1, reason: '记录编号、焊口编号和检测方法不能为空' })
          return
        }
        const method: NdtFilm['method'] = ['RT', 'UT', 'MT', 'PT'].includes(row?.method)
          ? row.method
          : 'RT'
        const film = row?.filmId
          ? state.ndtFilms.find((item) => item.id === row.filmId)
          : state.ndtFilms.find((item) => item.projectId === id && item.method === method)
        const report = row?.reportId
          ? state.ndtReports.find((item) => item.id === row.reportId)
          : state.ndtReports.find((item) => item.projectId === id && item.method === method)
        const seed = `${Date.now()}-${index}`
        const record: NdtRecord = {
          id: `NDT-REC-${seed}`,
          projectId: id,
          nodeId,
          recordNo:
            row?.recordNo || `REC-${method}-${state.ndtRecords.length + records.length + 1}`,
          filmId: row?.filmId || film?.id,
          reportId: row?.reportId || report?.id,
          weldNo: row?.weldNo || film?.weldNo || `W-${nodeId}-MOCK-${index + 1}`,
          pipelineNo: row?.pipelineNo || film?.pipelineNo || 'PL-MOCK',
          method,
          testDate: row?.testDate || serverTime.slice(0, 10),
          evaluatorName: row?.evaluatorName || '王工',
          result: row?.result || '合格',
          sampleStatus: row?.sampleStatus || (index === 0 ? '已抽查' : '未抽查'),
          conclusion: row?.conclusion || '检测记录已导入，等待监检抽查。',
          importedAt: serverTime,
          actions: ['ndt:record-import']
        }
        records.push(record)
      })
      if (!records.length && failed.length) {
        return fail(40041, '检测记录编号、焊口编号和检测方法不能为空。', {
          reason: 'NDT_RECORD_REQUIRED',
          failed
        })
      }
      state.ndtRecords.unshift(...records)
      addMessage({
        title: '无损检测记录导入完成',
        content: `已导入 ${records.length} 条检测记录，失败 ${failed.length} 条。`,
        projectId: id,
        targetType: 'node',
        targetId: String(nodeId)
      })
      addAuditLog('导入无损检测记录', 'NdtRecord', `${id}-${nodeId}`)
      return ok({ imported: records.length, failed, records })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/reports$/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const items = state.ndtReports.filter((report) => {
        if (report.projectId !== id) return false
        if (query?.status && report.status !== query.status) return false
        if (query?.method && report.method !== query.method) return false
        return true
      })
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/reports\/upload-session/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const mutationError = getMutationError(id, {
        body,
        query,
        action: '创建无损检测报告上传会话'
      })
      if (mutationError) return mutationError
      const files = body?.files || [
        { fileName: '无损检测报告.pdf', fileSize: 1024, fileType: 'pdf' }
      ]
      const allowedTypes = ['pdf', 'zip', 'jpg', 'png']
      const invalidFile = files.find(
        (file) => !allowedTypes.includes(String(file.fileType || '').toLowerCase())
      )
      if (invalidFile) {
        return fail(40041, `暂不支持 ${invalidFile.fileName || '未命名文件'} 的检测资料类型。`, {
          reason: 'UNSUPPORTED_NDT_FILE_TYPE'
        })
      }
      const oversizedFile = files.find((file) => Number(file.fileSize || 0) > 100 * 1024 * 1024)
      if (oversizedFile) {
        return fail(40042, `${oversizedFile.fileName || '未命名文件'} 超过 100MB 上传限制。`, {
          reason: 'NDT_FILE_TOO_LARGE'
        })
      }
      const relatedFilmIds = Array.isArray(body?.relatedFilmIds) ? body.relatedFilmIds : []
      const uploadUrls = files.map((file, index) => {
        const seed = `${Date.now()}-${index}`
        const documentId = `DOC-NDT-${seed}`
        const documentVersionId = `DV-NDT-${seed}-V1`
        const document: DocumentAsset = {
          id: documentId,
          projectId: id,
          fileName: file.fileName || '无损检测报告.pdf',
          fileType: file.fileType || 'pdf',
          sourceOrgName: getProject(id).ndtOrgName,
          uploaderName: '王工',
          currentVersionId: documentVersionId,
          fileStatus: '已上传',
          currentOcrStatus: '识别中',
          updatedAt: serverTime,
          actions: ['file:bind', 'ndt:submit']
        }
        const version: DocumentVersion = {
          id: documentVersionId,
          documentId,
          versionNo: 'V1',
          hash: `mock-sha256-${documentId}`,
          fileSize: file.fileSize || 1024,
          uploaderName: document.uploaderName,
          uploadTime: serverTime,
          isCurrent: true
        }
        const method: NdtReport['method'] = file.fileName?.includes('UT') ? 'UT' : 'RT'
        const reportName = String(file.fileName || `${method}检测报告.pdf`).replace(/\.[^.]+$/, '')
        const report: NdtReport = {
          id: `NDT-RPT-${seed}`,
          projectId: id,
          reportNo: reportName,
          method,
          fileId: documentId,
          relatedFilmIds,
          status: '待提交',
          conclusion: '检测资料已上传，等待提交监检。',
          uploadedAt: serverTime,
          actions: ['ndt:submit']
        }
        state.documents.unshift(document)
        state.versions.unshift(version)
        state.ndtReports.unshift(report)
        return {
          fileName: document.fileName,
          documentId,
          documentVersionId,
          url: `mock://upload/ndt/${seed}`,
          method: 'PUT',
          expiresAt: '2026-06-26 11:00:00',
          headers: { 'Content-Type': file.fileType || 'application/octet-stream' }
        }
      })
      addMessage({
        title: '无损检测报告已上传',
        content: `${uploadUrls.length} 个检测报告/影像包已进入待提交列表。`,
        projectId: id,
        targetType: 'document',
        targetId: uploadUrls[0]?.documentId || ''
      })
      return ok({
        uploadSessionId: `NDT-UP-${Date.now()}`,
        expiresAt: '2026-06-26 11:00:00',
        uploadUrls
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/reports\/(?!upload-session)[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const reportId = parts[5]
      const report = getNdtReport(id, reportId)
      if (!report) {
        return fail(40441, '无损检测报告不存在或已被移除。', {
          reason: 'NDT_REPORT_NOT_FOUND'
        })
      }
      return ok(buildNdtReportDetail(id, report))
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/submissions/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const nodeId = Number(body?.nodeId) || 40
      const mutationError = getNodeMutationError(id, nodeId, {
        body,
        query,
        action: '提交无损检测资料'
      })
      if (mutationError) return mutationError
      const reportIds = Array.isArray(body?.reportIds) ? body.reportIds : []
      const filmIds = Array.isArray(body?.filmIds) ? body.filmIds : []
      const selectedReports = state.ndtReports.filter(
        (report) => report.projectId === id && reportIds.includes(report.id)
      )
      const selectedFilms = state.ndtFilms.filter(
        (film) => film.projectId === id && filmIds.includes(film.id)
      )
      if (!selectedReports.length) {
        return fail(40043, '请选择至少一份检测报告后再提交。', {
          reason: 'NDT_REPORT_REQUIRED'
        })
      }
      selectedReports.forEach((report) => {
        report.status = '待审查'
        report.actions = ['project:view']
      })
      selectedFilms.forEach((film) => {
        film.status = '待审查'
        film.actions = ['project:view']
      })
      const nodeRequirements = requirements.filter((item) => item.nodeId === nodeId)
      const createdBindings = selectedReports
        .filter(
          (report) =>
            !state.bindings.some(
              (binding) =>
                binding.projectId === id &&
                binding.nodeId === nodeId &&
                binding.documentId === report.fileId
            )
        )
        .map((report, index) => {
          const document = state.documents.find((item) => item.id === report.fileId)
          const requirement = nodeRequirements[index % Math.max(nodeRequirements.length, 1)]
          const binding: NodeFileBinding = {
            id: `BIND-NDT-${Date.now()}-${index}`,
            projectId: id,
            nodeId,
            requirementId: requirement?.id,
            requirementName: requirement?.name || '无损检测报告',
            documentId: report.fileId,
            documentVersionId: document?.currentVersionId || '',
            fileName: document?.fileName || `${report.reportNo}.pdf`,
            versionNo: 'V1',
            usage: '检测报告',
            sourceOrgName: getProject(id).ndtOrgName,
            bindingStatus: '已提交',
            boundAt: serverTime,
            actions: ['review:save', 'review:return-correction']
          }
          return binding
        })
      state.bindings.unshift(...createdBindings)
      updateNodeFileProgress(id, nodeId)
      const { before } = setNodeStatus(id, nodeId, '待审查')
      setProjectStatus(id, '监检审查中', nodeId)
      const createdTodo = addTodo({
        title: `节点 ${nodeId} 无损检测资料待审查`,
        projectId: id,
        nodeId,
        targetType: 'submission',
        targetId: `NDT-SUB-${Date.now()}`,
        status: '待处理',
        priority: '中',
        deadline: '2026-06-27 18:00:00',
        assigneeName: '张工',
        actions: ['review:save', 'review:return-correction']
      })
      addMessage({
        title: '无损检测资料已提交',
        content: `节点 ${nodeId} 已提交 ${selectedReports.length} 份报告和 ${selectedFilms.length} 个底片编号。`,
        projectId: id,
        targetType: 'submission',
        targetId: createdTodo.targetId
      })
      return ok({
        submissionId: createdTodo.targetId,
        nextStatus: '待审查',
        changed: [{ field: 'status', before, after: '待审查' }],
        createdTodos: [createdTodo]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/rectifications/,
    method: 'post',
    timeout,
    response: ({ body, query, url }) => {
      const id = pathParts(url)[2] || projectId
      const mutationError = getMutationError(id, { body, query, action: '提交无损检测补正反馈' })
      if (mutationError) return mutationError
      if (!body?.rectificationId || !body?.description) {
        return fail(40044, '补正反馈和说明不能为空。', {
          reason: 'NDT_RECTIFICATION_REQUIRED'
        })
      }
      const feedback =
        state.ndtFeedback.find(
          (item) => item.projectId === id && item.id === body.rectificationId
        ) || state.ndtFeedback.find((item) => item.projectId === id)
      if (!feedback)
        return fail(40444, '监检反馈不存在或已关闭。', { reason: 'NDT_FEEDBACK_NOT_FOUND' })
      feedback.status = '已反馈'
      const reportIds = Array.isArray(body?.reportIds) ? body.reportIds : feedback.relatedReportIds
      const filmIds = Array.isArray(body?.filmIds) ? body.filmIds : feedback.relatedFilmIds
      state.ndtReports.forEach((report) => {
        if (report.projectId === id && reportIds.includes(report.id)) report.status = '待审查'
      })
      state.ndtFilms.forEach((film) => {
        if (film.projectId === id && filmIds.includes(film.id)) film.status = '待审查'
      })
      const { before } = setNodeStatus(id, feedback.nodeId, '复审中')
      closeNodeTodos(id, feedback.nodeId, '王工')
      setProjectStatus(id, '监检审查中', feedback.nodeId)
      addTodo({
        title: `节点 ${feedback.nodeId} 无损检测补正待复审`,
        projectId: id,
        nodeId: feedback.nodeId,
        targetType: 'rectification',
        targetId: `NDT-REC-${Date.now()}`,
        status: '待处理',
        priority: '中',
        deadline: '2026-06-28 18:00:00',
        assigneeName: '张工',
        actions: ['review:save', 'review:return-correction']
      })
      addMessage({
        title: '无损检测补正已反馈',
        content: body.description,
        projectId: id,
        targetType: 'rectification',
        targetId: feedback.id
      })
      addAuditLog('提交无损检测补正', 'NdtFeedback', feedback.id)
      return ok({
        rectification: {
          id: feedback.id,
          projectId: id,
          nodeId: feedback.nodeId,
          status: '已反馈'
        },
        nextStatus: '复审中',
        changed: [{ field: 'status', before, after: '复审中' }]
      })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/inspection-feedback$/,
    method: 'get',
    timeout,
    response: ({ url, query }) => {
      const id = pathParts(url)[2] || projectId
      const items = state.ndtFeedback.filter((item) => {
        if (item.projectId !== id) return false
        if (query?.status && item.status !== query.status) return false
        return true
      })
      return ok({ items, page: 1, pageSize: 20, total: items.length })
    }
  },
  {
    url: /\/api\/projects\/[^/]+\/ndt\/inspection-feedback\/[^/]+/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const parts = pathParts(url)
      const id = parts[2] || projectId
      const feedbackId = parts[5]
      const feedback = getNdtFeedback(id, feedbackId)
      if (!feedback) {
        return fail(40443, '无损检测反馈不存在或已被移除。', {
          reason: 'NDT_FEEDBACK_NOT_FOUND'
        })
      }
      return ok(buildNdtFeedbackDetail(id, feedback))
    }
  },
  {
    url: '/api/search',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      if (!keyword) {
        return fail(40060, '搜索关键词不能为空。', { reason: 'SEARCH_KEYWORD_REQUIRED' })
      }
      const type = query?.type as SearchResult['type'] | undefined
      const results = buildSearchResults(keyword, query?.projectId).filter((item) =>
        type ? item.type === type : true
      )
      return ok(makePage(results, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: '/api/todos',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const role = query?.role as RoleCode | undefined
      const items = state.todos.filter((todo) => {
        if (query?.projectId && todo.projectId !== query.projectId) return false
        if (query?.status && todo.status !== query.status) return false
        if (!role) return true
        return getRoleTodos(role, query?.projectId).some((item) => item.id === todo.id)
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/todos\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const todoId = pathParts(url)[2]
      const todo = state.todos.find((item) => item.id === todoId)
      if (!todo) return fail(40460, '待办不存在或已关闭。', { reason: 'TODO_NOT_FOUND' })
      return ok({
        ...todo,
        relatedObject: todo.nodeId ? getNode(todo.projectId, todo.nodeId) : undefined,
        evidenceLinks: todo.nodeId ? getEvidenceForNode(todo.nodeId) : []
      })
    }
  },
  {
    url: /\/api\/todos\/[^/]+\/complete/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const todoId = pathParts(url)[2]
      const todo = state.todos.find((item) => item.id === todoId)
      if (!todo) return fail(40460, '待办不存在或已关闭。', { reason: 'TODO_NOT_FOUND' })
      const before = todo.status
      todo.status = '已完成'
      refreshProjectCounters(todo.projectId)
      addMessage({
        title: '待办已完成',
        content: body?.comment || `${todo.title} 已处理完成。`,
        projectId: todo.projectId,
        targetType: todo.targetType,
        targetId: todo.targetId
      })
      return ok({
        id: `MUT-${Date.now()}`,
        objectType: 'TodoItem',
        objectId: todo.id,
        nextStatus: '已完成',
        changed: [{ field: 'status', before, after: '已完成' }],
        auditLogId: addAuditLog('完成待办', 'TodoItem', todo.id)
      })
    }
  },
  {
    url: /\/api\/todos\/[^/]+\/defer/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const todoId = pathParts(url)[2]
      const todo = state.todos.find((item) => item.id === todoId)
      if (!todo) return fail(40460, '待办不存在或已关闭。', { reason: 'TODO_NOT_FOUND' })
      if (!body?.deferTo || !body?.reason) {
        return fail(40061, '延期时间和原因不能为空。', { reason: 'TODO_DEFER_REQUIRED' })
      }
      todo.deadline = body.deferTo
      todo.status = '已延期'
      refreshProjectCounters(todo.projectId)
      addAuditLog('延期待办', 'TodoItem', todo.id)
      return ok({ todo })
    }
  },
  {
    url: '/api/messages',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const read = parseBool(query?.read)
      const items = state.messages.filter((message) => {
        if (query?.projectId && message.projectId && message.projectId !== query.projectId)
          return false
        if (read !== undefined && message.read !== read) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/messages\/[^/]+\/read/,
    method: 'post',
    timeout,
    response: ({ url }) => {
      const messageId = pathParts(url)[2]
      const message = state.messages.find((item) => item.id === messageId)
      if (!message) return fail(40461, '消息不存在或已移除。', { reason: 'MESSAGE_NOT_FOUND' })
      const before = message.read
      message.read = true
      if (message.projectId) refreshProjectCounters(message.projectId)
      return ok({
        id: `MUT-${Date.now()}`,
        objectType: 'MessageItem',
        objectId: message.id,
        nextStatus: '已读',
        changed: [{ field: 'read', before, after: true }],
        auditLogId: addAuditLog('标记消息已读', 'MessageItem', message.id)
      })
    }
  },
  {
    url: '/api/messages/read-all',
    method: 'post',
    timeout,
    response: ({ body }) => {
      let affectedCount = 0
      state.messages.forEach((message) => {
        if (body?.projectId && message.projectId !== body.projectId) return
        if (!message.read) {
          message.read = true
          affectedCount += 1
        }
      })
      state.projects.forEach((project) => refreshProjectCounters(project.id))
      return ok({ affectedCount })
    }
  },
  {
    url: '/api/knowledge/overview',
    method: 'get',
    timeout,
    response: () => ok(buildKnowledgeOverview())
  },
  {
    url: '/api/knowledge/sources',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      const sourceType = String(query?.sourceType || '').trim()
      const status = String(query?.status || '').trim()
      const items = state.knowledgeSources.filter((source) => {
        if (keyword && !`${source.name}${source.version || ''}`.includes(keyword)) return false
        if (sourceType && source.sourceType !== sourceType) return false
        if (status && source.status !== status) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: '/api/knowledge/sources',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '新增知识源' })
      if (error) return error
      const name = String(body?.name || '').trim()
      if (!name) return fail(40083, '知识源名称不能为空。', { reason: 'SOURCE_NAME_REQUIRED' })
      const sourceType = knowledgeSourceTypes.includes(body?.sourceType)
        ? body.sourceType
        : 'standard'
      const source: KnowledgeSourceMock = {
        id: `KS-${Date.now()}-${state.knowledgeSources.length + 1}`,
        name,
        sourceType,
        version: String(body?.version || '').trim() || undefined,
        status: body?.status || '待复核',
        fileCount: Math.max(0, Number(body?.fileCount) || 0),
        chunkCount: Math.max(0, Number(body?.chunkCount) || 0),
        vectorStatus: body?.vectorStatus || '待向量化',
        updatedAt: serverTime,
        actions: ['knowledge:view', 'knowledge:manage', 'knowledge:reindex']
      }
      state.knowledgeSources.unshift(source)
      const auditLogId = addAuditLog('新增知识源', 'KnowledgeSource', source.id)
      return ok({ source, auditLogId })
    }
  },
  {
    url: /\/api\/knowledge\/sources\/[^/]+\/enable/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '启用知识源' })
      if (error) return error
      const sourceId = pathParts(url)[3]
      const source = getKnowledgeSource(sourceId)
      if (!source) return fail(40483, '知识源不存在。', { reason: 'KNOWLEDGE_SOURCE_NOT_FOUND' })
      const before = source.status
      source.status = '启用'
      source.updatedAt = serverTime
      const mutation = makeKnowledgeMutation('启用知识源', 'KnowledgeSource', source.id, [
        { field: 'status', before, after: source.status }
      ])
      return ok({ source, auditLogId: mutation.auditLogId })
    }
  },
  {
    url: /\/api\/knowledge\/sources\/[^/]+\/disable/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '停用知识源' })
      if (error) return error
      const sourceId = pathParts(url)[3]
      const source = getKnowledgeSource(sourceId)
      if (!source) return fail(40483, '知识源不存在。', { reason: 'KNOWLEDGE_SOURCE_NOT_FOUND' })
      const before = source.status
      source.status = '停用'
      source.updatedAt = serverTime
      const mutation = makeKnowledgeMutation('停用知识源', 'KnowledgeSource', source.id, [
        { field: 'status', before, after: source.status }
      ])
      return ok({ source, auditLogId: mutation.auditLogId })
    }
  },
  {
    url: /\/api\/knowledge\/sources\/[^/]+$/,
    method: 'put',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '更新知识源' })
      if (error) return error
      const sourceId = pathParts(url)[3]
      const source = getKnowledgeSource(sourceId)
      if (!source) return fail(40483, '知识源不存在。', { reason: 'KNOWLEDGE_SOURCE_NOT_FOUND' })
      const before = { ...source }
      if (typeof body?.name === 'string') source.name = body.name.trim() || source.name
      if (knowledgeSourceTypes.includes(body?.sourceType)) source.sourceType = body.sourceType
      if (typeof body?.version === 'string') source.version = body.version.trim() || undefined
      if (body?.status) source.status = body.status
      if (body?.vectorStatus) source.vectorStatus = body.vectorStatus
      if (body?.fileCount !== undefined) source.fileCount = Math.max(0, Number(body.fileCount) || 0)
      if (body?.chunkCount !== undefined)
        source.chunkCount = Math.max(0, Number(body.chunkCount) || 0)
      source.updatedAt = serverTime
      const auditLogId = addAuditLog('更新知识源', 'KnowledgeSource', source.id)
      return ok({
        source,
        auditLogId,
        changed: [
          { field: 'name', before: before.name, after: source.name },
          { field: 'version', before: before.version, after: source.version },
          { field: 'status', before: before.status, after: source.status }
        ]
      })
    }
  },
  {
    url: /\/api\/knowledge\/sources\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const sourceId = pathParts(url)[3]
      const source = getKnowledgeSource(sourceId)
      if (!source) return fail(40483, '知识源不存在。', { reason: 'KNOWLEDGE_SOURCE_NOT_FOUND' })
      return ok({ source })
    }
  },
  {
    url: '/api/knowledge/project-files',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      const status = String(query?.status || '').trim()
      const nodeId = Number(query?.nodeId)
      const items = state.knowledgeFiles.filter((file) => {
        if (
          keyword &&
          !`${file.fileName}${file.nodeName || ''}${file.projectName || ''}`.includes(keyword)
        )
          return false
        if (query?.projectId && file.projectId !== query.projectId) return false
        if (Number.isFinite(nodeId) && nodeId > 0 && file.nodeId !== nodeId) return false
        if (
          status &&
          file.ocrStatus !== status &&
          file.sliceStatus !== status &&
          file.vectorStatus !== status
        )
          return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/knowledge\/files\/[^/]+\/chunks/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const fileId = pathParts(url)[3]
      const file = getKnowledgeFile(fileId)
      if (!file) return fail(40480, '知识文件不存在。', { reason: 'KNOWLEDGE_FILE_NOT_FOUND' })
      return ok(
        makePage(getKnowledgeChunks(file), Number(query?.page) || 1, Number(query?.pageSize) || 20)
      )
    }
  },
  {
    url: /\/api\/knowledge\/files\/[^/]+\/vectors/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const fileId = pathParts(url)[3]
      const file = getKnowledgeFile(fileId)
      if (!file) return fail(40480, '知识文件不存在。', { reason: 'KNOWLEDGE_FILE_NOT_FOUND' })
      return ok(getKnowledgeVectorSummary(file))
    }
  },
  {
    url: /\/api\/knowledge\/files\/[^/]+\/reasoning-references/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const fileId = pathParts(url)[3]
      const file = getKnowledgeFile(fileId)
      if (!file) return fail(40480, '知识文件不存在。', { reason: 'KNOWLEDGE_FILE_NOT_FOUND' })
      return ok(
        makePage(
          getKnowledgeReasoningReferences(file),
          Number(query?.page) || 1,
          Number(query?.pageSize) || 20
        )
      )
    }
  },
  {
    url: /\/api\/knowledge\/files\/[^/]+\/reindex/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '重建文件索引' })
      if (error) return error
      const fileId = pathParts(url)[3]
      const file = getKnowledgeFile(fileId)
      if (!file) return fail(40480, '知识文件不存在。', { reason: 'KNOWLEDGE_FILE_NOT_FOUND' })
      file.vectorStatus = '向量化中'
      file.updatedAt = serverTime
      const task = makeKnowledgeTask({
        taskType: 'reindex',
        targetType: 'file',
        targetId: file.id,
        targetName: file.fileName
      })
      return ok({ task })
    }
  },
  {
    url: /\/api\/knowledge\/files\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const fileId = pathParts(url)[3]
      const file = getKnowledgeFile(fileId)
      if (!file) return fail(40480, '知识文件不存在。', { reason: 'KNOWLEDGE_FILE_NOT_FOUND' })
      const document = state.documents.find((item) => item.id === file.documentId)
      const currentVersion = state.versions.find((version) => version.id === file.documentVersionId)
      const latestTask = state.knowledgeTasks.find((task) => task.targetId === file.id)
      return ok({
        file,
        document,
        currentVersion,
        latestTask,
        vectorSummary: getKnowledgeVectorSummary(file)
      })
    }
  },
  {
    url: '/api/knowledge/tasks',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const taskType = String(query?.taskType || '').trim()
      const status = String(query?.status || '').trim()
      const items = state.knowledgeTasks.filter((task) => {
        if (taskType && task.taskType !== taskType) return false
        if (status && task.status !== status) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/knowledge\/tasks\/[^/]+\/retry/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '重试知识库任务' })
      if (error) return error
      const taskId = pathParts(url)[3]
      const sourceTask = state.knowledgeTasks.find((task) => task.id === taskId)
      if (!sourceTask)
        return fail(40481, '知识库任务不存在。', { reason: 'KNOWLEDGE_TASK_NOT_FOUND' })
      if (sourceTask.status !== '失败' && sourceTask.status !== '已取消') {
        return fail(40920, '只有失败或已取消的任务可以重试。', { reason: 'TASK_NOT_RETRYABLE' })
      }
      const task = makeKnowledgeTask({
        taskType: sourceTask.taskType,
        targetType: sourceTask.targetType,
        targetId: sourceTask.targetId,
        targetName: sourceTask.targetName
      })
      addMessage({
        title: '知识库任务已重试',
        content: body?.reason || `${sourceTask.targetName} 已重新加入任务队列。`,
        projectId,
        targetType: 'knowledgeTask',
        targetId: task.id
      })
      return ok({ task })
    }
  },
  {
    url: /\/api\/knowledge\/tasks\/[^/]+\/cancel/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '取消知识库任务' })
      if (error) return error
      const taskId = pathParts(url)[3]
      const task = state.knowledgeTasks.find((item) => item.id === taskId)
      if (!task) return fail(40481, '知识库任务不存在。', { reason: 'KNOWLEDGE_TASK_NOT_FOUND' })
      if (task.status !== '排队中') {
        return fail(40921, '只有排队中的任务可以取消。', { reason: 'TASK_NOT_CANCELABLE' })
      }
      task.status = '已取消'
      task.finishedAt = serverTime
      task.progress = 0
      addAuditLog('取消知识库任务', 'KnowledgeTask', task.id)
      return ok({ task })
    }
  },
  {
    url: '/api/knowledge/reindex',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '批量重建知识库索引' })
      if (error) return error
      const scope = body?.scope || 'all'
      const targets =
        scope === 'source' && body?.sourceId
          ? state.knowledgeSources.filter((source) => source.id === body.sourceId)
          : scope === 'project' && body?.projectId
            ? state.knowledgeFiles.filter((file) => file.projectId === body.projectId)
            : state.knowledgeSources
      const taskIds = targets.map((target) => {
        const isFile = 'fileName' in target
        const task = makeKnowledgeTask({
          taskType: 'reindex',
          targetType: isFile ? 'file' : 'source',
          targetId: target.id,
          targetName: isFile ? target.fileName : target.name
        })
        return task.id
      })
      return ok({ taskIds })
    }
  },
  {
    url: '/api/knowledge/retrieval-test',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '知识库检索测试' })
      if (error) return error
      const question = String(body?.question || '').trim()
      if (!question) return fail(40080, '检索问题不能为空。', { reason: 'QUESTION_REQUIRED' })
      const topK = Math.max(1, Math.min(Number(body?.topK) || 5, 10))
      const hits = evidenceLinks.slice(0, topK)
      return ok({
        answerDraft: `根据当前知识库，问题“${question}”可从 ${hits.length} 条证据中得到支撑。建议进入正式审查前复核文件版本、页码和标准条款有效性。`,
        hits,
        latencyMs: 420 + hits.length * 36,
        usedIndexVersions: state.knowledgeSources
          .filter(
            (source) => body?.scope?.includes(source.sourceType) || body?.scope?.includes(source.id)
          )
          .map((source) => source.version || source.id)
      })
    }
  },
  {
    url: '/api/rules/versions',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      const status = String(query?.status || '').trim()
      const items = state.knowledgeRuleVersions.filter((rule) => {
        if (
          keyword &&
          !`${rule.name}${rule.ruleKey}${rule.version}${rule.description || ''}`.includes(keyword)
        )
          return false
        if (status && rule.status !== status) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/rules\/versions\/[^/]+\/diff/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const versionId = pathParts(url)[3]
      const base = getKnowledgeRuleVersion(versionId)
      if (!base) return fail(40484, '规则版本不存在。', { reason: 'RULE_VERSION_NOT_FOUND' })
      const diff = buildKnowledgeRuleVersionDiff(
        versionId,
        String(query?.targetVersionId || '').trim() || undefined,
        String(query?.targetVersion || '').trim() || undefined
      )
      if (!diff)
        return fail(40486, '缺少可对比的规则版本。', { reason: 'RULE_DIFF_TARGET_NOT_FOUND' })
      return ok(diff)
    }
  },
  {
    url: /\/api\/rules\/versions\/[^/]+\/publish/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '发布规则版本' })
      if (error) return error
      const reason = String(body?.reason || '').trim()
      if (!reason) return fail(40084, '发布原因不能为空。', { reason: 'PUBLISH_REASON_REQUIRED' })
      const versionId = pathParts(url)[3]
      const rule = getKnowledgeRuleVersion(versionId)
      if (!rule) return fail(40484, '规则版本不存在。', { reason: 'RULE_VERSION_NOT_FOUND' })
      const before = rule.status
      state.knowledgeRuleVersions.forEach((item) => {
        if (item.ruleKey === rule.ruleKey && item.id !== rule.id && item.status === '已发布') {
          item.status = '已回滚'
          item.updatedAt = serverTime
        }
      })
      rule.status = '已发布'
      rule.publishedAt = body?.effectiveAt || serverTime
      rule.updatedAt = serverTime
      const mutation = makeKnowledgeMutation('发布规则版本', 'RuleVersion', rule.id, [
        { field: 'status', before, after: rule.status },
        { field: 'publishedAt', before: undefined, after: rule.publishedAt }
      ])
      return ok({ ...mutation, rule })
    }
  },
  {
    url: /\/api\/rules\/versions\/[^/]+\/rollback/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '回滚规则版本' })
      if (error) return error
      const reason = String(body?.reason || '').trim()
      if (!reason) return fail(40085, '回滚原因不能为空。', { reason: 'ROLLBACK_REASON_REQUIRED' })
      const versionId = pathParts(url)[3]
      const rule = getKnowledgeRuleVersion(versionId)
      if (!rule) return fail(40484, '规则版本不存在。', { reason: 'RULE_VERSION_NOT_FOUND' })
      const targetVersion = String(body?.targetVersion || '').trim()
      const target = state.knowledgeRuleVersions.find(
        (item) =>
          item.ruleKey === rule.ruleKey &&
          item.id !== rule.id &&
          (item.id === targetVersion || item.version === targetVersion)
      )
      if (!target)
        return fail(40485, '目标回滚版本不存在。', { reason: 'TARGET_VERSION_NOT_FOUND' })
      const before = rule.status
      const targetBefore = target.status
      rule.status = '已回滚'
      rule.updatedAt = serverTime
      target.status = '已发布'
      target.publishedAt = serverTime
      target.updatedAt = serverTime
      const mutation = makeKnowledgeMutation('回滚规则版本', 'RuleVersion', rule.id, [
        { field: 'status', before, after: rule.status },
        { field: 'target.status', before: targetBefore, after: target.status }
      ])
      return ok({ ...mutation, rule, target })
    }
  },
  {
    url: '/api/knowledge/config',
    method: 'get',
    timeout,
    response: () =>
      ok({
        config: state.knowledgeConfig,
        updatedAt: state.knowledgeConfig.updatedAt
      })
  },
  {
    url: '/api/knowledge/config',
    method: 'put',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '保存知识库配置' })
      if (error) return error
      const before = { ...state.knowledgeConfig }
      if (typeof body?.embeddingModel === 'string' && body.embeddingModel.trim()) {
        state.knowledgeConfig.embeddingModel = body.embeddingModel.trim()
      }
      if (body?.chunkSize !== undefined) {
        state.knowledgeConfig.chunkSize = Math.max(
          200,
          Math.min(Number(body.chunkSize) || 900, 2000)
        )
      }
      if (body?.chunkOverlap !== undefined) {
        state.knowledgeConfig.chunkOverlap = Math.max(
          0,
          Math.min(Number(body.chunkOverlap) || 0, state.knowledgeConfig.chunkSize - 1)
        )
      }
      if (body?.topKDefault !== undefined) {
        state.knowledgeConfig.topKDefault = Math.max(1, Math.min(Number(body.topKDefault) || 5, 20))
      }
      if (body?.rerankEnabled !== undefined)
        state.knowledgeConfig.rerankEnabled = !!body.rerankEnabled
      if (body?.evidenceStrictMode !== undefined)
        state.knowledgeConfig.evidenceStrictMode = !!body.evidenceStrictMode
      if (body?.autoReindex !== undefined) state.knowledgeConfig.autoReindex = !!body.autoReindex
      if (body?.retentionDays !== undefined) {
        state.knowledgeConfig.retentionDays = Math.max(30, Number(body.retentionDays) || 180)
      }
      state.knowledgeConfig.updatedBy = 'mock 用户'
      state.knowledgeConfig.updatedAt = serverTime
      const mutation = makeKnowledgeMutation('保存知识库配置', 'KnowledgeConfig', 'KB-CONFIG', [
        {
          field: 'embeddingModel',
          before: before.embeddingModel,
          after: state.knowledgeConfig.embeddingModel
        },
        { field: 'chunkSize', before: before.chunkSize, after: state.knowledgeConfig.chunkSize },
        {
          field: 'topKDefault',
          before: before.topKDefault,
          after: state.knowledgeConfig.topKDefault
        }
      ])
      return ok({
        config: state.knowledgeConfig,
        updatedAt: state.knowledgeConfig.updatedAt,
        auditLogId: mutation.auditLogId
      })
    }
  },
  {
    url: '/api/knowledge/audit-logs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      const objectType = String(query?.objectType || '').trim()
      const result = String(query?.result || '').trim()
      const items = getKnowledgeAuditLogs().filter((log) => {
        if (keyword && !`${log.action}${log.actorName}${log.objectId}`.includes(keyword))
          return false
        if (objectType && log.objectType !== objectType) return false
        if (result && log.result !== result) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/reasoning\/logs\/[^/]+\/evidence/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const logId = pathParts(url)[3]
      const run = state.aiRuns.find((item) => item.id === logId)
      if (!run) return fail(40482, '推理日志不存在。', { reason: 'REASONING_LOG_NOT_FOUND' })
      return ok(run.evidenceLinks)
    }
  },
  {
    url: /\/api\/reasoning\/logs\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const logId = pathParts(url)[3]
      const run = state.aiRuns.find((item) => item.id === logId)
      if (!run) return fail(40482, '推理日志不存在。', { reason: 'REASONING_LOG_NOT_FOUND' })
      return ok({ log: run, evidenceLinks: run.evidenceLinks })
    }
  },
  {
    url: '/api/reasoning/logs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const nodeId = Number(query?.nodeId)
      const status = String(query?.status || '').trim()
      const items = state.aiRuns.filter((run) => {
        if (query?.projectId && run.projectId !== query.projectId) return false
        if (Number.isFinite(nodeId) && nodeId > 0 && run.nodeId !== nodeId) return false
        if (status && run.status !== status) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: '/api/llm/compare',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '多模型对比' })
      if (error) return error
      const question = String(body?.question || '').trim()
      const modelCodes = Array.isArray(body?.modelCodes) ? body.modelCodes : []
      if (!question) return fail(40090, '对比问题不能为空。', { reason: 'QUESTION_REQUIRED' })
      if (modelCodes.length < 2) {
        return fail(40091, '至少选择两个模型进行对比。', { reason: 'MODEL_COUNT_REQUIRED' })
      }
      const evidenceIds = body?.evidenceLinkIds?.length
        ? body.evidenceLinkIds
        : evidenceLinks.slice(0, 2).map((link) => link.id)
      const run: LlmCompareRunMock = {
        runId: `CMP-${Date.now()}`,
        question,
        modelCodes,
        createdAt: serverTime,
        projectId: body?.projectId,
        nodeId: body?.nodeId,
        results: modelCodes.map((modelCode: string, index: number) => ({
          modelCode,
          answer:
            index === 0
              ? `模型 ${modelCode} 认为材料基本满足要求，但建议核对证据页码和条款版本。`
              : `模型 ${modelCode} 认为需补充人工确认项，重点检查外部查询截图和文件版本。`,
          confidence: Number((0.86 - index * 0.04).toFixed(2)),
          evidenceLinkIds: evidenceIds,
          latencyMs: 980 + index * 260
        }))
      }
      state.llmCompareRuns.unshift(run)
      addAuditLog('发起多模型对比', 'LlmCompareRun', run.runId)
      return ok(getLlmComparePayload(run))
    }
  },
  {
    url: /\/api\/llm\/compare-runs\/[^/]+$/,
    method: 'get',
    timeout,
    response: ({ url }) => {
      const runId = pathParts(url)[3]
      const run = state.llmCompareRuns.find((item) => item.runId === runId)
      if (!run) return fail(40483, '多模型对比记录不存在。', { reason: 'COMPARE_RUN_NOT_FOUND' })
      return ok(getLlmComparePayload(run))
    }
  },
  {
    url: '/api/llm/compare-runs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const nodeId = Number(query?.nodeId)
      const items = state.llmCompareRuns.filter((run) => {
        if (query?.projectId && run.projectId !== query.projectId) return false
        if (Number.isFinite(nodeId) && nodeId > 0 && run.nodeId !== nodeId) return false
        return true
      })
      return ok(
        makePage(
          items.map((run) => ({
            runId: run.runId,
            question: run.question,
            modelCodes: run.modelCodes,
            createdAt: run.createdAt,
            projectId: run.projectId,
            nodeId: run.nodeId
          })),
          Number(query?.page) || 1,
          Number(query?.pageSize) || 20
        )
      )
    }
  },
  {
    url: '/api/admin/projects',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '项目立项' })
      if (error) return error
      const name = String(body?.name || '').trim()
      if (!name) return fail(40090, '项目名称不能为空。', { reason: 'PROJECT_NAME_REQUIRED' })
      const code =
        String(body?.code || '').trim() ||
        `P-2026-MOCK-${String(state.projects.length + 1).padStart(3, '0')}`
      if (state.projects.some((project) => project.id === code || project.code === code)) {
        return fail(40990, '项目编号已存在。', { reason: 'PROJECT_CODE_DUPLICATED', code })
      }
      const project: Project = {
        id: code,
        code,
        name,
        type: String(body?.type || '工业管道工程'),
        region: String(body?.region || '华东'),
        ownerOrgName: String(body?.ownerOrgName || '华东管网建设公司'),
        contractorOrgName: String(body?.contractorOrgName || '中石化安装有限公司'),
        ndtOrgName: String(body?.ndtOrgName || '华测检测有限公司'),
        inspectionOrgName: String(body?.inspectionOrgName || '省特检院一部'),
        status: '草稿/立项中',
        todoCount: 0,
        messageCount: 0,
        currentNodeId: Number(body?.currentNodeId) || 1,
        updatedAt: serverTime,
        actions: ['project:view', 'project:authorize-member']
      }
      state.projects.unshift(project)
      state.treeNodes.push(...createProjectTreeNodes(project))
      const members = createProjectInitialMembers(project, body?.memberUserIds)
      state.projectMembers.unshift(...members)
      const auditLogId = addAuditLog('项目立项', 'Project', project.id)
      addMessage({
        projectId: project.id,
        title: `新项目已立项：${project.name}`,
        content: '系统已生成 69 个监督检验节点和初始成员授权。',
        targetType: 'node',
        targetId: `${project.id}-${project.currentNodeId}`
      })
      return ok({
        project,
        detail: buildAdminProjectDetail(project.id),
        auditLogId,
        createdNodeCount: 69
      })
    }
  },
  {
    url: '/api/admin/config-diff/preview',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const target = body?.target as AdminConfigTargetMock
      const id = String(body?.id || '').trim()
      const values = (body?.values || {}) as Record<string, unknown>
      const diff = buildAdminConfigDiff(target, id, values)
      if (!diff) return fail(40490, '配置项不存在。', { reason: 'ADMIN_CONFIG_ITEM_NOT_FOUND' })
      return ok(diff)
    }
  },
  {
    url: '/api/admin/integration-contract',
    method: 'get',
    timeout,
    response: ({ query }) => ok(buildIntegrationContract(query))
  },
  {
    url: /\/api\/admin\/config-items\/[^/]+$/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '新增后台配置' })
      if (error) return error
      const reason = String(body?.reason || '').trim()
      if (!reason) {
        return fail(40091, '配置变更原因不能为空。', { reason: 'CONFIG_REASON_REQUIRED' })
      }
      const target = (body?.target || pathParts(url)[3]) as AdminConfigTargetMock
      const values = (body?.values || {}) as Record<string, unknown>
      const item = createAdminConfigItem(target, values)
      if (!item) return fail(40092, '不支持新增该类配置。', { reason: 'CONFIG_CREATE_UNSUPPORTED' })
      const auditLogId = addAuditLog(`新增后台配置-${target}`, 'AdminConfig', item.id)
      return ok({
        overview: buildAdminConfigOverview(),
        diff: buildAdminCreateDiff(target, item as Record<string, unknown>),
        auditLogId,
        updatedAt: serverTime
      })
    }
  },
  {
    url: /\/api\/admin\/config-items\/[^/]+\/[^/]+/,
    method: 'put',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '保存后台配置' })
      if (error) return error
      const reason = String(body?.reason || '').trim()
      if (!reason) {
        return fail(40091, '配置变更原因不能为空。', { reason: 'CONFIG_REASON_REQUIRED' })
      }
      const parts = pathParts(url)
      const target = (body?.target || parts[3]) as AdminConfigTargetMock
      const id = String(body?.id || parts[4] || '').trim()
      const values = (body?.values || {}) as Record<string, unknown>
      const diff = buildAdminConfigDiff(target, id, values)
      if (!diff) return fail(40490, '配置项不存在。', { reason: 'ADMIN_CONFIG_ITEM_NOT_FOUND' })
      applyAdminConfigChange(target, id, values)
      const auditLogId = addAuditLog(`保存后台配置-${target}`, 'AdminConfig', id)
      return ok({
        overview: buildAdminConfigOverview(),
        diff,
        auditLogId,
        updatedAt: serverTime
      })
    }
  },
  {
    url: /\/api\/admin\/(todo-rules|message-templates|tool-sources|field-mappings)$/,
    method: 'get',
    timeout,
    response: ({ query, url }) => {
      const target = adminResourceToTarget(pathParts(url)[2])
      if (!target) return fail(40491, '配置资源不存在。', { reason: 'CONFIG_RESOURCE_NOT_FOUND' })
      const keyword = String(query?.keyword || '').trim()
      const items = getAdminConfigCollection(target).filter((item) => {
        if (!keyword) return true
        return JSON.stringify(item).includes(keyword)
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  },
  {
    url: /\/api\/admin\/(todo-rules|message-templates|tool-sources|field-mappings)$/,
    method: 'post',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '新增后台细项配置' })
      if (error) return error
      const target = adminResourceToTarget(pathParts(url)[2])
      if (!target) return fail(40491, '配置资源不存在。', { reason: 'CONFIG_RESOURCE_NOT_FOUND' })
      const item = createAdminConfigItem(target, body || {})
      if (!item) return fail(40092, '不支持新增该类配置。', { reason: 'CONFIG_CREATE_UNSUPPORTED' })
      const auditLogId = addAuditLog(`新增后台细项配置-${target}`, 'AdminConfig', item.id)
      return ok({ item, auditLogId })
    }
  },
  {
    url: /\/api\/admin\/(todo-rules|message-templates|tool-sources|field-mappings)\/[^/]+/,
    method: 'patch',
    timeout,
    response: ({ body, url }) => {
      const error = getForcedMutationError({ body, action: '更新后台细项配置' })
      if (error) return error
      const parts = pathParts(url)
      const target = adminResourceToTarget(parts[2])
      const id = parts[3]
      if (!target) return fail(40491, '配置资源不存在。', { reason: 'CONFIG_RESOURCE_NOT_FOUND' })
      const item = applyAdminConfigChange(target, id, body || {})
      if (!item) return fail(40490, '配置项不存在。', { reason: 'ADMIN_CONFIG_ITEM_NOT_FOUND' })
      const auditLogId = addAuditLog(`更新后台细项配置-${target}`, 'AdminConfig', id)
      return ok({ item, auditLogId })
    }
  },
  {
    url: '/api/admin/config-overview',
    method: 'get',
    timeout,
    response: () => ok(buildAdminConfigOverview())
  },
  {
    url: '/api/admin/config-overview/publish',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '发布后台配置' })
      if (error) return error
      const reason = String(body?.reason || '').trim()
      if (!reason) {
        return fail(40070, '发布原因不能为空。', { reason: 'PUBLISH_REASON_REQUIRED' })
      }
      const scope = body?.scope || 'all'
      const version = `config-v2026.06.${String(state.auditLogs.length + 1).padStart(2, '0')}`
      const auditLogId = addAuditLog(`发布后台配置-${scope}`, 'AdminConfig', version)
      const activeProjects = state.projects.filter((project) => project.status !== '已归档')
      const impacts = [
        {
          domain: 'permission',
          label: '权限矩阵',
          affectedCount: state.adminPermissionMatrix.length,
          status: '已同步',
          trace: '权限矩阵已同步到工作台动作权限和项目成员授权校验。'
        },
        {
          domain: 'workflow',
          label: '流程状态机',
          affectedCount: state.adminWorkflowStateMachines.length,
          status: '已同步',
          trace: '流程状态机已刷新节点提交流转和归档前置校验。'
        },
        {
          domain: 'todo-rule',
          label: '待办规则',
          affectedCount: state.adminTodoRules.length,
          status: '已同步',
          trace: '待办规则已刷新施工、监检、无损检测角色的任务生成口径。'
        },
        {
          domain: 'message-template',
          label: '消息模板',
          affectedCount: state.adminMessageTemplates.length,
          status: '已同步',
          trace: '消息模板已刷新待办通知、补正通知和归档通知内容。'
        },
        {
          domain: 'field-mapping',
          label: '字段映射',
          affectedCount: state.adminFieldMappings.length,
          status: '需复核',
          trace: '字段映射阈值变更后需在真实 OCR 样例中复核抽取命中率。'
        }
      ]
      const warningCount = impacts.filter((item) => item.status === '需复核').length
      const linkedMessages = activeProjects.map((project) =>
        addMessage({
          projectId: project.id,
          title: `后台配置已发布：${version}`,
          content: `发布范围 ${scope}，影响 ${impacts.reduce(
            (sum, item) => sum + item.affectedCount,
            0
          )} 项配置，${warningCount} 项需复核。发布原因：${reason}`,
          targetType: 'node',
          targetId: `${project.id}-${project.currentNodeId}`
        })
      )
      const reviewTodos = warningCount
        ? activeProjects.map((project) =>
            addTodo({
              title: `复核 ${project.name} 字段映射配置发布影响`,
              projectId: project.id,
              nodeId: project.currentNodeId,
              targetType: 'node',
              targetId: `${project.id}-${project.currentNodeId}`,
              status: '待处理',
              priority: '中',
              deadline: '2026-06-28 18:00:00',
              assigneeName: '张工',
              actions: ['audit:view']
            })
          )
        : []
      return ok({
        publishId: `PUB-${Date.now()}`,
        status: '已发布',
        version,
        auditLogId,
        publishedAt: serverTime,
        impactSummary: {
          totalAffected: impacts.reduce((sum, item) => sum + item.affectedCount, 0),
          warningCount,
          linkedProjects: activeProjects.length,
          pushedMessages: linkedMessages.length,
          reviewTodos: reviewTodos.length
        },
        impacts
      })
    }
  },
  {
    url: '/api/admin/config-export',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const error = getForcedMutationError({ body, action: '导出后台配置' })
      if (error) return error
      const scope = body?.scope || 'all'
      const exportId = `EXP-CONFIG-${Date.now()}`
      const task = makeExportTask(projectId, {
        id: exportId,
        exportType: 'config-package',
        fileName: `后台配置包-${scope}-20260626.zip`,
        downloadUrl: `mock://download/config/${exportId}.zip`,
        fileSize: 768 * 1024
      })
      const auditLogId = addAuditLog(`导出后台配置-${scope}`, 'AdminConfigExport', exportId)
      return ok({ exportId, task, auditLogId })
    }
  },
  {
    url: '/api/admin/audit-logs',
    method: 'get',
    timeout,
    response: ({ query }) => {
      const keyword = String(query?.keyword || '').trim()
      const result = String(query?.result || '').trim()
      const objectType = String(query?.objectType || '').trim()
      const items = state.auditLogs.filter((log) => {
        if (
          keyword &&
          !`${log.actorName}${log.action}${log.objectType}${log.objectId}`.includes(keyword)
        ) {
          return false
        }
        if (result && log.result !== result) return false
        if (objectType && log.objectType !== objectType) return false
        return true
      })
      return ok(makePage(items, Number(query?.page) || 1, Number(query?.pageSize) || 20))
    }
  }
] as MockMethod[]
