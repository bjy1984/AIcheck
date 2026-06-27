import request from '@/axios'
import type {
  ActionCode,
  AiReviewRun,
  DocumentAsset,
  DocumentVersion,
  EvidenceLink,
  ExportTask,
  ExtractedField,
  MessageItem,
  MockMutationResult,
  NodeFileBinding,
  NodePackagePayload,
  NdtFeedback,
  NdtFilm,
  NdtReport,
  Project,
  ProjectTreeNode,
  ArchiveItem,
  NdtRecord,
  ReportVersion,
  ReviewOpinion,
  RoleCode,
  SearchResult,
  TodoItem,
  WorkbenchContextPayload,
  WorkbenchSummaryPayload
} from '@/types/aicheck'

export type ProjectTreePayload = {
  project: Project
  groups: Array<{
    groupName: string
    nodes: ProjectTreeNode[]
  }>
}

export type PagePayload<T> = {
  items: T[]
  page: number
  pageSize: number
  total: number
}

export type UploadSessionPayload = {
  uploadSessionId: string
  expiresAt: string
  uploadUrls: Array<{
    fileName: string
    documentId: string
    documentVersionId: string
    url: string
    method: 'PUT'
    expiresAt: string
    headers: Record<string, string>
  }>
}

export type SubmissionDraftPayload = {
  draftId: string
  savedAt: string
  bindingIds: string[]
}

export type SubmissionDraftSummary = {
  draftId: string
  projectId: string
  nodeIds: number[]
  nodeNames: string[]
  bindingCount: number
  batchName?: string
  remark?: string
  savedAt: string
}

export type SubmissionDraftDetailPayload = {
  draftId: string
  projectId: string
  nodeIds: number[]
  nodes: ProjectTreeNode[]
  bindings: NodeFileBinding[]
  batchName?: string
  remark?: string
  savedAt: string
}

export type SubmissionPayload = {
  submissionId: string
  snapshotId: string
  nextStatus: string
  createdTodos: TodoItem[]
}

export type SubmissionSummary = {
  submissionId: string
  snapshotId: string
  projectId: string
  nodeIds: number[]
  nodeNames: string[]
  bindingCount: number
  todoCount: number
  batchName?: string
  submitterComment?: string
  nextStatus: string
  submittedAt: string
  withdrawal?: {
    bindingCount: number
    reason: string
    withdrawnAt: string
  }
}

export type SubmissionDetailPayload = {
  submissionId: string
  snapshotId: string
  projectId: string
  nodeIds: number[]
  nodes: ProjectTreeNode[]
  bindings: NodeFileBinding[]
  batchName?: string
  submitterComment?: string
  nextStatus: string
  submittedAt: string
  withdrawal?: {
    bindingCount: number
    reason: string
    withdrawnAt: string
  }
  createdTodos: TodoItem[]
  changed: Array<{ field: string; before?: unknown; after: unknown }>
}

export type SubmissionHistoryPayload = {
  drafts: SubmissionDraftSummary[]
  submissions: SubmissionSummary[]
}

export type ReportReviewPayload = {
  report: ReportVersion
  nextStatus: '报告生成/复核中'
  createdTodos: TodoItem[]
}

export type ReportExportPayload = {
  exportId: string
  report: ReportVersion
}

export type ReportArchivePayload = {
  report: ReportVersion
  nextStatus: '已归档'
}

export type SignedUrlPayload = {
  url: string
  method: 'GET'
  expiresAt: string
  fileName: string
  contentType?: string
  fileSize?: number
}

export type DocumentPreviewPayload = SignedUrlPayload & {
  previewType: 'pdf' | 'office' | 'image' | 'unsupported'
  readonly: boolean
  pageCount?: number
}

export type DocumentDetailPayload = {
  document: DocumentAsset
  currentVersion?: DocumentVersion
  versions: DocumentVersion[]
  bindings: NodeFileBinding[]
  extractedFields: ExtractedField[]
  evidenceLinks: EvidenceLink[]
  preview: DocumentPreviewPayload
  download: SignedUrlPayload
}

export type ArchivePackagePayload = SignedUrlPayload & {
  exportId: string
  projectId: string
  packageType: 'archive' | 'evidence'
  itemCount: number
  generatedAt: string
}

export type ArchiveItemDetailPayload = {
  item: ArchiveItem
  preview?: DocumentPreviewPayload
  download?: SignedUrlPayload
  report?: ReportVersion
  document?: DocumentAsset
  evidenceLinks: EvidenceLink[]
  relatedExportTasks: ExportTask[]
}

export type ExportTaskPayload = {
  task: ExportTask
}

export type ProjectMember = {
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

export type ProjectMemberSavePayload = {
  userId: string
  role: RoleCode
  nodeScope: number[]
  actions: ActionCode[]
  expiresAt?: string
}

export type AdminProjectDetailPayload = {
  project: Project
  members: ProjectMember[]
  participantUnits: Array<{
    unitType: 'owner' | 'contractor' | 'ndt' | 'inspection'
    unitName: string
    contactName: string
    contactPhone: string
  }>
  nodeSummary: Array<{
    groupName: string
    total: number
    passed: number
    pending: number
    correction: number
  }>
  recentExportTasks: ExportTask[]
}

export type AdminProjectCreatePayload = {
  code?: string
  name: string
  type: string
  region: string
  ownerOrgName: string
  contractorOrgName: string
  ndtOrgName: string
  inspectionOrgName: string
  currentNodeId?: number
  memberUserIds?: Partial<Record<RoleCode, string>>
}

export type AdminProjectCreateResult = {
  project: Project
  detail: AdminProjectDetailPayload
  auditLogId: string
  createdNodeCount: number
}

export type NdtReportUploadPayload = UploadSessionPayload

export type NdtRecordImportPayload = {
  imported: number
  failed: Array<{ row: number; reason: string }>
  records: NdtRecord[]
}

export type NdtReportDetailPayload = {
  report: NdtReport
  films: NdtFilm[]
  records: NdtRecord[]
  document?: DocumentAsset
  feedback: NdtFeedback[]
}

export type NdtFeedbackDetailPayload = {
  feedback: NdtFeedback
  reports: NdtReport[]
  films: NdtFilm[]
  records: NdtRecord[]
  evidenceLinks: EvidenceLink[]
  timeline: Array<{
    title: string
    actorName: string
    status: string
    createdAt: string
    comment?: string
  }>
}

export type NdtSubmissionPayload = {
  submissionId: string
  nextStatus: '待审查'
  createdTodos: TodoItem[]
}

export type NdtRectificationPayload = {
  rectification: {
    id: string
    projectId: string
    nodeId: number
    status: string
  }
  nextStatus: '复审中'
}

export type RectificationPayload = {
  rectification: {
    id: string
    projectId: string
    nodeId: number
    status: string
  }
  nextStatus: string
  createdTodos: TodoItem[]
}

export type AiRecheckPayload = {
  runId: string
  status: string
  latestRun: AiReviewRun
}

export type ReviewOpinionPayload = {
  opinion: ReviewOpinion
  nextStatus: string
}

export type AiSuggestionAdoptPayload = {
  draftOpinion: ReviewOpinion
  auditLogId: string
}

export type ReturnCorrectionPayload = {
  rectification: {
    id: string
    projectId: string
    nodeId: number
    status: string
  }
  nextStatus: string
  createdTodos: TodoItem[]
}

export type EvidenceChainPayload = {
  node: ProjectTreeNode
  links: EvidenceLink[]
  groupedByObject: Array<{
    objectType: EvidenceLink['objectType']
    links: EvidenceLink[]
  }>
}

export type StandardReference = {
  clauseId: string
  standardName: string
  clauseNo: string
  title: string
  summary: string
  effectiveVersion: string
  evidenceLinkId?: string
}

export type DateComparisonItem = {
  fieldName: string
  leftLabel: string
  leftValue: string
  rightLabel: string
  rightValue: string
  result: '覆盖' | '不覆盖' | '缺失' | '待确认'
  evidenceLinkIds: string[]
}

export type ReportDetailPayload = {
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

export type KnowledgeOverviewPayload = {
  metrics: Array<{
    key: string
    label: string
    value: string | number
    tone: 'blue' | 'green' | 'orange' | 'red' | 'gray'
  }>
  libraries: Array<{
    key: string
    name: string
    fileCount: number
    chunkCount: number
    vectorCount: number
    indexVersion: string
    status: string
    updatedAt: string
  }>
}

export type KnowledgeStatus = '启用' | '停用' | '过期' | '待复核'

export type KnowledgeSource = {
  id: string
  name: string
  sourceType: 'standard' | 'project-file' | 'rule' | 'manual'
  version?: string
  status: KnowledgeStatus
  fileCount: number
  chunkCount: number
  vectorStatus: '未向量化' | '向量化中' | '已向量化' | '向量化失败' | '待向量化'
  updatedAt: string
  actions: ActionCode[]
}

export type KnowledgeSourceSavePayload = {
  name: string
  sourceType: KnowledgeSource['sourceType']
  version?: string
  status?: KnowledgeSource['status']
  fileCount?: number
  chunkCount?: number
  vectorStatus?: KnowledgeSource['vectorStatus']
}

export type KnowledgeFile = {
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
  vectorStatus: KnowledgeSource['vectorStatus']
  chunkCount: number
  vectorCount: number
  updatedAt: string
  actions: ActionCode[]
}

export type KnowledgeTask = {
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

export type KnowledgeChunk = {
  id: string
  chunkNo: number
  text: string
  pageNo?: number
  evidenceLinkId?: string
  tokenCount: number
}

export type KnowledgeVectorSummary = {
  vectorStatus: KnowledgeSource['vectorStatus']
  vectorCount: number
  indexVersion: string
  dimensions: number
  updatedAt: string
}

export type KnowledgeReasoningReference = {
  runId: string
  nodeId: number
  subject: string
  model: string
  quotedText: string
  createdAt: string
}

export type KnowledgeFileDetailPayload = {
  file: KnowledgeFile
  document?: DocumentAsset
  currentVersion?: DocumentVersion
  latestTask?: KnowledgeTask
  vectorSummary: KnowledgeVectorSummary
}

export type KnowledgeRetrievalTestPayload = {
  answerDraft: string
  hits: EvidenceLink[]
  latencyMs: number
  usedIndexVersions: string[]
}

export type KnowledgeRuleVersion = {
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

export type KnowledgeRuleVersionDiffChange = {
  field: 'version' | 'status' | 'nodes' | 'prompt' | 'schema' | 'description'
  label: string
  before?: unknown
  after?: unknown
  severity: 'info' | 'warning'
  changeType: 'added' | 'changed' | 'removed'
}

export type KnowledgeRuleVersionDiffPayload = {
  base: KnowledgeRuleVersion
  target: KnowledgeRuleVersion
  comparedAt: string
  summary: {
    added: number
    changed: number
    removed: number
    warning: number
  }
  changes: KnowledgeRuleVersionDiffChange[]
}

export type KnowledgeConfig = {
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

export type KnowledgeAuditLog = {
  id: string
  actorName: string
  action: string
  objectType: string
  objectId: string
  result: string
  createdAt: string
}

export type ReasoningLogDetailPayload = {
  log: AiReviewRun
  evidenceLinks: EvidenceLink[]
}

export type LlmComparePayload = {
  runId: string
  question: string
  createdAt: string
  results: Array<{
    modelCode: string
    answer: string
    confidence: number
    evidenceLinkIds: string[]
    latencyMs: number
  }>
}

export type LlmCompareRunSummary = {
  runId: string
  question: string
  modelCodes: string[]
  createdAt: string
  projectId?: string
  nodeId?: number
}

export type AuditLogPayload = {
  items: Array<{
    id: string
    actorName: string
    action: string
    objectType: string
    objectId: string
    result: string
    createdAt: string
  }>
  page: number
  pageSize: number
  total: number
}

export type AdminTodoRule = {
  id: string
  name: string
  triggerStatus: string
  assigneeRole: RoleCode
  deadlineHours: number
  enabled: boolean
  updatedAt: string
}

export type AdminMessageTemplate = {
  id: string
  scene: string
  channel: '站内信' | '短信' | '邮件'
  titleTemplate: string
  contentTemplate: string
  enabled: boolean
  updatedAt: string
}

export type AdminToolSource = {
  id: string
  name: string
  toolType: 'external-query' | 'ocr' | 'signature' | 'archive'
  endpoint: string
  authMode: 'none' | 'token' | 'signature'
  status: '启用' | '停用' | '异常'
  updatedAt: string
}

export type AdminFieldMapping = {
  id: string
  nodeId: number
  fieldName: string
  sourceField: string
  targetField: string
  required: boolean
  confidenceThreshold: number
  updatedAt: string
}

export type AdminConfigOverviewPayload = {
  metrics: Array<{
    key: string
    label: string
    value: string | number
    tone: 'blue' | 'green' | 'orange' | 'red' | 'gray'
  }>
  orgUnits: Array<{
    id: string
    name: string
    type: 'owner' | 'contractor' | 'ndt' | 'inspection' | 'supervision'
    contactName: string
    contactPhone: string
    status: '启用' | '停用' | '待授权'
    projectCount: number
  }>
  users: Array<{
    id: string
    name: string
    orgName: string
    role: RoleCode
    mobile: string
    status: '启用' | '停用'
    lastLoginAt: string
  }>
  permissionMatrix: Array<{
    role: RoleCode
    label: string
    projectScope: string
    nodeScope: string
    actions: ActionCode[]
    readonly: boolean
  }>
  nodeTemplates: Array<{
    id: string
    version: string
    groupName: string
    nodeCount: number
    requiredCount: number
    status: '草稿' | '已发布' | '已停用'
    updatedAt: string
  }>
  ruleVersions: Array<{
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
  }>
  workflowStateMachines: Array<{
    id: string
    name: string
    version: string
    states: number
    transitions: number
    status: '启用' | '停用'
    updatedAt: string
  }>
  todoRules: AdminTodoRule[]
  messageTemplates: AdminMessageTemplate[]
  toolSources: AdminToolSource[]
  fieldMappings: AdminFieldMapping[]
}

export type AdminConfigTarget =
  | 'permission'
  | 'node-template'
  | 'workflow'
  | 'todo-rule'
  | 'message-template'
  | 'tool-source'
  | 'field-mapping'

export type AdminConfigPermissionValues = Partial<
  AdminConfigOverviewPayload['permissionMatrix'][number]
>

export type AdminConfigNodeTemplateValues = Partial<
  AdminConfigOverviewPayload['nodeTemplates'][number]
>

export type AdminConfigWorkflowValues = Partial<
  AdminConfigOverviewPayload['workflowStateMachines'][number]
>

export type AdminTodoRuleValues = Partial<AdminTodoRule>

export type AdminMessageTemplateValues = Partial<AdminMessageTemplate>

export type AdminToolSourceValues = Partial<AdminToolSource>

export type AdminFieldMappingValues = Partial<AdminFieldMapping>

export type AdminConfigChangePayload =
  | {
      target: 'permission'
      id: RoleCode
      values: AdminConfigPermissionValues
      reason: string
    }
  | {
      target: 'node-template'
      id: string
      values: AdminConfigNodeTemplateValues
      reason: string
    }
  | {
      target: 'workflow'
      id: string
      values: AdminConfigWorkflowValues
      reason: string
    }
  | {
      target: 'todo-rule'
      id: string
      values: AdminTodoRuleValues
      reason: string
    }
  | {
      target: 'message-template'
      id: string
      values: AdminMessageTemplateValues
      reason: string
    }
  | {
      target: 'tool-source'
      id: string
      values: AdminToolSourceValues
      reason: string
    }
  | {
      target: 'field-mapping'
      id: string
      values: AdminFieldMappingValues
      reason: string
    }

export type AdminConfigCreatePayload =
  | {
      target: 'todo-rule'
      values: AdminTodoRuleValues
      reason: string
    }
  | {
      target: 'message-template'
      values: AdminMessageTemplateValues
      reason: string
    }
  | {
      target: 'tool-source'
      values: AdminToolSourceValues
      reason: string
    }
  | {
      target: 'field-mapping'
      values: AdminFieldMappingValues
      reason: string
    }

export type AdminConfigDiffPayload = {
  target: AdminConfigTarget
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

export type AdminConfigSaveResult = {
  overview: AdminConfigOverviewPayload
  diff: AdminConfigDiffPayload
  auditLogId: string
  updatedAt: string
}

export type AdminPublishImpact = {
  domain:
    | 'permission'
    | 'workflow'
    | 'node-template'
    | 'rule'
    | 'todo-rule'
    | 'message-template'
    | 'tool-source'
    | 'field-mapping'
  label: string
  affectedCount: number
  status: '已同步' | '需复核'
  trace: string
}

export type IntegrationContractModule =
  | 'workbench'
  | 'documents'
  | 'submissions'
  | 'inspection'
  | 'ndt-owner-report'
  | 'knowledge-admin'

export type IntegrationContractStatus =
  | '已对齐'
  | '待后端确认'
  | '前端缺失'
  | '后端缺失'
  | '命名不一致'

export type IntegrationContractField = {
  id: string
  module: IntegrationContractModule
  moduleLabel: string
  endpoint: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  frontendField: string
  backendField: string
  required: boolean
  status: IntegrationContractStatus
  severity: 'info' | 'warning' | 'danger'
  owner: string
  note: string
  updatedAt: string
}

export type IntegrationContractPayload = {
  summary: {
    total: number
    aligned: number
    pending: number
    blockers: number
  }
  modules: Array<{
    module: IntegrationContractModule
    label: string
    total: number
    aligned: number
    pending: number
    blockers: number
  }>
  fields: IntegrationContractField[]
  generatedAt: string
}

export type AdminPublishConfigPayload = {
  publishId: string
  status: '已发布'
  version: string
  auditLogId: string
  publishedAt: string
  impactSummary: {
    totalAffected: number
    warningCount: number
    linkedProjects: number
    pushedMessages: number
    reviewTodos: number
  }
  impacts: AdminPublishImpact[]
}

export type TodoDetailPayload = TodoItem & {
  relatedObject?: unknown
  evidenceLinks?: EvidenceLink[]
}

export const listWorkbenchProjectsApi = (role: RoleCode): Promise<IResponse<Project[]>> => {
  return request.get({ url: '/api/workbench/projects', params: { role } })
}

export const getAdminProjectDetailApi = (
  projectId: string
): Promise<IResponse<AdminProjectDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}` })
}

export const listProjectMembersApi = (
  projectId: string
): Promise<IResponse<PagePayload<ProjectMember>>> => {
  return request.get({ url: `/api/projects/${projectId}/members`, params: { pageSize: 100 } })
}

export const authorizeProjectMemberApi = (
  projectId: string,
  payload: ProjectMemberSavePayload
): Promise<IResponse<{ member: ProjectMember; auditLogId: string }>> => {
  return request.post({ url: `/api/projects/${projectId}/members`, data: payload })
}

export const updateProjectMemberApi = (
  projectId: string,
  memberId: string,
  payload: Partial<ProjectMemberSavePayload> & { status?: ProjectMember['status'] }
): Promise<IResponse<{ member: ProjectMember; auditLogId: string }>> => {
  return request.put({ url: `/api/projects/${projectId}/members/${memberId}`, data: payload })
}

export const createAdminProjectApi = (
  payload: AdminProjectCreatePayload
): Promise<IResponse<AdminProjectCreateResult>> => {
  return request.post({ url: '/api/admin/projects', data: payload })
}

export const createAdminConfigExportApi = (payload: {
  scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
  includeAudit?: boolean
  reason?: string
}): Promise<IResponse<{ exportId: string; task: ExportTask }>> => {
  return request.post({ url: '/api/admin/config-export', data: payload })
}

export const getWorkbenchContextApi = (
  projectId: string,
  role: RoleCode
): Promise<IResponse<WorkbenchContextPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/workbench/context`, params: { role } })
}

export const getWorkbenchSummaryApi = (
  projectId: string,
  role: RoleCode
): Promise<IResponse<WorkbenchSummaryPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/workbench/summary`, params: { role } })
}

export const getProjectTreeApi = (projectId: string): Promise<IResponse<ProjectTreePayload>> => {
  return request.get({ url: `/api/projects/${projectId}/tree` })
}

export const getNodePackageApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<NodePackagePayload>> => {
  return request.get({ url: `/api/projects/${projectId}/nodes/${nodeId}/package` })
}

export const getDocumentDetailApi = (
  projectId: string,
  documentId: string
): Promise<IResponse<DocumentDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/documents/${documentId}` })
}

export const getDocumentPreviewUrlApi = (
  projectId: string,
  documentId: string
): Promise<IResponse<DocumentPreviewPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/documents/${documentId}/preview-url` })
}

export const getDocumentDownloadUrlApi = (
  projectId: string,
  documentId: string
): Promise<IResponse<SignedUrlPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/documents/${documentId}/download-url` })
}

export const createDocumentUploadSessionApi = (
  projectId: string,
  files: Array<{ fileName: string; fileSize: number; fileType: string }>
): Promise<IResponse<UploadSessionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/upload-session`,
    data: { files }
  })
}

export const bindDocumentsToNodeApi = (
  projectId: string,
  payload: {
    nodeId?: number
    nodeIds?: number[]
    bindings: Array<Pick<NodeFileBinding, 'documentId' | 'documentVersionId' | 'usage'>>
  }
): Promise<IResponse<MockMutationResult>> => {
  return request.post({ url: `/api/projects/${projectId}/documents/bindings`, data: payload })
}

export const saveSubmissionDraftApi = (
  projectId: string,
  payload: {
    nodeId?: number
    nodeIds?: number[]
    bindingIds: string[]
    remark?: string
    batchName?: string
  }
): Promise<IResponse<SubmissionDraftPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/submissions/drafts`, data: payload })
}

export const listSubmissionHistoryApi = (
  projectId: string
): Promise<IResponse<SubmissionHistoryPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/submissions` })
}

export const getSubmissionDraftDetailApi = (
  projectId: string,
  draftId: string
): Promise<IResponse<SubmissionDraftDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/submissions/drafts/${draftId}` })
}

export const submitNodePackageApi = (
  projectId: string,
  payload: {
    nodeId?: number
    nodeIds?: number[]
    bindingIds: string[]
    submitterComment?: string
    batchName?: string
  }
): Promise<IResponse<SubmissionPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/submissions`, data: payload })
}

export const getSubmissionDetailApi = (
  projectId: string,
  submissionId: string
): Promise<IResponse<SubmissionDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/submissions/${submissionId}` })
}

export const withdrawSubmissionItemsApi = (
  projectId: string,
  submissionId: string,
  payload: { bindingIds?: string[]; documentVersionIds?: string[]; reason: string }
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/submissions/${submissionId}/withdraw-items`,
    data: payload
  })
}

export const submitRectificationApi = (
  projectId: string,
  payload: { nodeId: number; bindingIds: string[]; comment: string }
): Promise<IResponse<RectificationPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/rectifications`, data: payload })
}

export const requestAiRecheckApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<AiRecheckPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-recheck` })
}

export const saveReviewOpinionApi = (
  projectId: string,
  nodeId: number,
  payload: { result: ReviewOpinion['result']; opinion: string; evidenceLinkIds: string[] }
): Promise<IResponse<ReviewOpinionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/review-opinions`,
    data: payload
  })
}

export const adoptAiSuggestionApi = (
  projectId: string,
  nodeId: number,
  suggestionId: string,
  payload: { result: ReviewOpinion['result']; opinion: string; reason: string }
): Promise<IResponse<AiSuggestionAdoptPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-suggestions/${suggestionId}/adopt`,
    data: payload
  })
}

export const rejectAiSuggestionApi = (
  projectId: string,
  nodeId: number,
  suggestionId: string,
  payload: { reason: string; manualOpinion?: string }
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-suggestions/${suggestionId}/reject`,
    data: payload
  })
}

export const returnCorrectionApi = (
  projectId: string,
  nodeId: number,
  payload: { reason: string; evidenceLinkIds: string[] }
): Promise<IResponse<ReturnCorrectionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/actions/return-correction`,
    data: payload
  })
}

export const getEvidenceChainApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<EvidenceChainPayload>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/evidence-chain`
  })
}

export const listInspectionStandardsApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<StandardReference[]>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/standards`
  })
}

export const getInspectionDateCompareApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<DateComparisonItem[]>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/date-compare`
  })
}

export const generateReportReviewApi = (
  projectId: string,
  nodeId: number,
  payload: {
    includeEvidence: boolean
    reportScope: ReportVersion['scope']
    reviewerNote?: string
  }
): Promise<IResponse<ReportReviewPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/report-review`,
    data: payload
  })
}

export const listOwnerReportsApi = (projectId: string): Promise<IResponse<ReportVersion[]>> => {
  return request.get({ url: `/api/projects/${projectId}/owner/reports` })
}

export const listProjectArchiveApi = (
  projectId: string,
  params?: { keyword?: string; nodeId?: number; page?: number; pageSize?: number }
): Promise<IResponse<PagePayload<ArchiveItem>>> => {
  return request.get({ url: `/api/projects/${projectId}/archive`, params })
}

export const getArchiveItemDetailApi = (
  projectId: string,
  archiveItemId: string
): Promise<IResponse<ArchiveItemDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/archive/${archiveItemId}` })
}

export const getExportTaskApi = (
  projectId: string,
  exportId: string
): Promise<IResponse<ExportTaskPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/export-tasks/${exportId}` })
}

export const getReportDetailApi = (
  projectId: string,
  reportId: string
): Promise<IResponse<ReportDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/reports/${reportId}` })
}

export const getArchivePackageApi = (
  projectId: string
): Promise<IResponse<ArchivePackagePayload>> => {
  return request.get({ url: `/api/projects/${projectId}/archive/package` })
}

export const getEvidencePackageApi = (
  projectId: string,
  params?: { nodeId?: number }
): Promise<IResponse<ArchivePackagePayload>> => {
  return request.get({ url: `/api/projects/${projectId}/archive/evidence-package`, params })
}

export const exportReportApi = (
  projectId: string,
  reportId: string,
  payload: { format: 'docx' | 'pdf' }
): Promise<IResponse<ReportExportPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/reports/${reportId}/export`,
    data: payload
  })
}

export const archiveReportApi = (
  projectId: string,
  reportId: string,
  payload: { archiveNote?: string }
): Promise<IResponse<ReportArchivePayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/reports/${reportId}/archive`,
    data: payload
  })
}

export const listNdtFilmsApi = (
  projectId: string,
  params?: {
    status?: NdtFilm['status']
    method?: NdtFilm['method']
    keyword?: string
    page?: number
    pageSize?: number
  }
): Promise<IResponse<PagePayload<NdtFilm>>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/films`, params })
}

export const createNdtFilmApi = (
  projectId: string,
  payload: Pick<NdtFilm, 'filmNo' | 'weldNo' | 'method'> & {
    pipelineNo?: string
    testDate?: string
  }
): Promise<IResponse<{ film: NdtFilm }>> => {
  return request.post({ url: `/api/projects/${projectId}/ndt/films`, data: payload })
}

export const listNdtRecordsApi = (
  projectId: string,
  params?: {
    filmId?: string
    reportId?: string
    sampleStatus?: NdtRecord['sampleStatus']
    page?: number
    pageSize?: number
  }
): Promise<IResponse<PagePayload<NdtRecord>>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/records`, params })
}

export const importNdtRecordsApi = (
  projectId: string,
  payload: {
    fileId?: string
    nodeId: number
    rows?: Array<Partial<NdtRecord>>
  }
): Promise<IResponse<NdtRecordImportPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/ndt/records/import`, data: payload })
}

export const listNdtReportsApi = (
  projectId: string,
  params?: {
    status?: NdtReport['status']
    method?: NdtReport['method']
    page?: number
    pageSize?: number
  }
): Promise<IResponse<PagePayload<NdtReport>>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/reports`, params })
}

export const getNdtReportDetailApi = (
  projectId: string,
  reportId: string
): Promise<IResponse<NdtReportDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/reports/${reportId}` })
}

export const createNdtReportUploadSessionApi = (
  projectId: string,
  payload: {
    files: Array<{ fileName: string; fileSize: number; fileType: string }>
    relatedFilmIds?: string[]
  }
): Promise<IResponse<NdtReportUploadPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/reports/upload-session`,
    data: payload
  })
}

export const submitNdtSubmissionApi = (
  projectId: string,
  payload: { reportIds: string[]; filmIds?: string[]; nodeId: number }
): Promise<IResponse<NdtSubmissionPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/ndt/submissions`, data: payload })
}

export const submitNdtRectificationApi = (
  projectId: string,
  payload: {
    rectificationId: string
    description: string
    reportIds?: string[]
    filmIds?: string[]
  }
): Promise<IResponse<NdtRectificationPayload>> => {
  return request.post({ url: `/api/projects/${projectId}/ndt/rectifications`, data: payload })
}

export const listNdtInspectionFeedbackApi = (
  projectId: string,
  params?: { status?: NdtFeedback['status']; page?: number; pageSize?: number }
): Promise<IResponse<PagePayload<NdtFeedback>>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/inspection-feedback`, params })
}

export const getNdtInspectionFeedbackDetailApi = (
  projectId: string,
  feedbackId: string
): Promise<IResponse<NdtFeedbackDetailPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/ndt/inspection-feedback/${feedbackId}` })
}

export const getKnowledgeOverviewApi = (): Promise<IResponse<KnowledgeOverviewPayload>> => {
  return request.get({ url: '/api/knowledge/overview' })
}

export const listKnowledgeSourcesApi = (params?: {
  keyword?: string
  sourceType?: KnowledgeSource['sourceType']
  status?: KnowledgeSource['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeSource>>> => {
  return request.get({ url: '/api/knowledge/sources', params })
}

export const createKnowledgeSourceApi = (
  payload: KnowledgeSourceSavePayload
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({ url: '/api/knowledge/sources', data: payload })
}

export const getKnowledgeSourceApi = (
  sourceId: string
): Promise<IResponse<{ source: KnowledgeSource }>> => {
  return request.get({ url: `/api/knowledge/sources/${sourceId}` })
}

export const updateKnowledgeSourceApi = (
  sourceId: string,
  payload: Partial<KnowledgeSourceSavePayload>
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.put({ url: `/api/knowledge/sources/${sourceId}`, data: payload })
}

export const enableKnowledgeSourceApi = (
  sourceId: string,
  payload?: { reason?: string }
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({ url: `/api/knowledge/sources/${sourceId}/enable`, data: payload || {} })
}

export const disableKnowledgeSourceApi = (
  sourceId: string,
  payload?: { reason?: string }
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({ url: `/api/knowledge/sources/${sourceId}/disable`, data: payload || {} })
}

export const listKnowledgeProjectFilesApi = (params?: {
  keyword?: string
  projectId?: string
  nodeId?: number
  status?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeFile>>> => {
  return request.get({ url: '/api/knowledge/project-files', params })
}

export const getKnowledgeFileDetailApi = (
  fileId: string
): Promise<IResponse<KnowledgeFileDetailPayload>> => {
  return request.get({ url: `/api/knowledge/files/${fileId}` })
}

export const listKnowledgeFileChunksApi = (
  fileId: string,
  params?: { page?: number; pageSize?: number }
): Promise<IResponse<PagePayload<KnowledgeChunk>>> => {
  return request.get({ url: `/api/knowledge/files/${fileId}/chunks`, params })
}

export const getKnowledgeFileVectorApi = (
  fileId: string
): Promise<IResponse<KnowledgeVectorSummary>> => {
  return request.get({ url: `/api/knowledge/files/${fileId}/vectors` })
}

export const listKnowledgeFileReasoningReferencesApi = (
  fileId: string,
  params?: { page?: number; pageSize?: number }
): Promise<IResponse<PagePayload<KnowledgeReasoningReference>>> => {
  return request.get({ url: `/api/knowledge/files/${fileId}/reasoning-references`, params })
}

export const listKnowledgeTasksApi = (params?: {
  taskType?: KnowledgeTask['taskType']
  status?: KnowledgeTask['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeTask>>> => {
  return request.get({ url: '/api/knowledge/tasks', params })
}

export const retryKnowledgeTaskApi = (
  taskId: string,
  payload?: { reason?: string }
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({ url: `/api/knowledge/tasks/${taskId}/retry`, data: payload || {} })
}

export const cancelKnowledgeTaskApi = (
  taskId: string,
  payload?: { reason?: string }
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({ url: `/api/knowledge/tasks/${taskId}/cancel`, data: payload || {} })
}

export const reindexKnowledgeFileApi = (
  fileId: string,
  payload?: { force?: boolean }
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({ url: `/api/knowledge/files/${fileId}/reindex`, data: payload || {} })
}

export const batchReindexKnowledgeApi = (payload: {
  scope: 'all' | 'project' | 'source'
  projectId?: string
  sourceId?: string
}): Promise<IResponse<{ taskIds: string[] }>> => {
  return request.post({ url: '/api/knowledge/reindex', data: payload })
}

export const runKnowledgeRetrievalTestApi = (payload: {
  question: string
  scope: string[]
  projectId?: string
  nodeId?: number
  topK: number
}): Promise<IResponse<KnowledgeRetrievalTestPayload>> => {
  return request.post({ url: '/api/knowledge/retrieval-test', data: payload })
}

export const listKnowledgeRuleVersionsApi = (params?: {
  keyword?: string
  status?: KnowledgeRuleVersion['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeRuleVersion>>> => {
  return request.get({ url: '/api/rules/versions', params })
}

export const getKnowledgeRuleVersionDiffApi = (
  versionId: string,
  params?: { targetVersionId?: string; targetVersion?: string }
): Promise<IResponse<KnowledgeRuleVersionDiffPayload>> => {
  return request.get({ url: `/api/rules/versions/${versionId}/diff`, params })
}

export const publishKnowledgeRuleVersionApi = (
  versionId: string,
  payload: { reason: string; effectiveAt?: string }
): Promise<IResponse<MockMutationResult & { rule: KnowledgeRuleVersion }>> => {
  return request.post({ url: `/api/rules/versions/${versionId}/publish`, data: payload })
}

export const rollbackKnowledgeRuleVersionApi = (
  versionId: string,
  payload: { reason: string; targetVersion: string }
): Promise<
  IResponse<MockMutationResult & { rule: KnowledgeRuleVersion; target: KnowledgeRuleVersion }>
> => {
  return request.post({ url: `/api/rules/versions/${versionId}/rollback`, data: payload })
}

export const getKnowledgeConfigApi = (): Promise<
  IResponse<{ config: KnowledgeConfig; updatedAt: string }>
> => {
  return request.get({ url: '/api/knowledge/config' })
}

export const updateKnowledgeConfigApi = (
  payload: Partial<KnowledgeConfig>
): Promise<IResponse<{ config: KnowledgeConfig; updatedAt: string; auditLogId: string }>> => {
  return request.put({ url: '/api/knowledge/config', data: payload })
}

export const listKnowledgeAuditLogsApi = (params?: {
  keyword?: string
  objectType?: string
  result?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeAuditLog>>> => {
  return request.get({ url: '/api/knowledge/audit-logs', params })
}

export const listReasoningLogsApi = (params?: {
  projectId?: string
  nodeId?: number
  status?: AiReviewRun['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<AiReviewRun>>> => {
  return request.get({ url: '/api/reasoning/logs', params })
}

export const getReasoningLogDetailApi = (
  logId: string
): Promise<IResponse<ReasoningLogDetailPayload>> => {
  return request.get({ url: `/api/reasoning/logs/${logId}` })
}

export const getReasoningLogEvidenceApi = (logId: string): Promise<IResponse<EvidenceLink[]>> => {
  return request.get({ url: `/api/reasoning/logs/${logId}/evidence` })
}

export const runLlmCompareApi = (payload: {
  question: string
  modelCodes: string[]
  projectId?: string
  nodeId?: number
  evidenceLinkIds?: string[]
}): Promise<IResponse<LlmComparePayload>> => {
  return request.post({ url: '/api/llm/compare', data: payload })
}

export const listLlmCompareRunsApi = (params?: {
  projectId?: string
  nodeId?: number
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<LlmCompareRunSummary>>> => {
  return request.get({ url: '/api/llm/compare-runs', params })
}

export const getLlmCompareRunApi = (runId: string): Promise<IResponse<LlmComparePayload>> => {
  return request.get({ url: `/api/llm/compare-runs/${runId}` })
}

export const getAuditLogsApi = (params?: {
  keyword?: string
  result?: string
  objectType?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<AuditLogPayload>> => {
  return request.get({ url: '/api/admin/audit-logs', params })
}

export const getAdminConfigOverviewApi = (): Promise<IResponse<AdminConfigOverviewPayload>> => {
  return request.get({ url: '/api/admin/config-overview' })
}

export const getAdminIntegrationContractApi = (params?: {
  module?: IntegrationContractModule | 'all'
  status?: IntegrationContractStatus | 'all'
}): Promise<IResponse<IntegrationContractPayload>> => {
  return request.get({ url: '/api/admin/integration-contract', params })
}

export const listAdminTodoRulesApi = (): Promise<IResponse<PagePayload<AdminTodoRule>>> => {
  return request.get({ url: '/api/admin/todo-rules', params: { pageSize: 100 } })
}

export const listAdminMessageTemplatesApi = (): Promise<
  IResponse<PagePayload<AdminMessageTemplate>>
> => {
  return request.get({ url: '/api/admin/message-templates', params: { pageSize: 100 } })
}

export const listAdminToolSourcesApi = (): Promise<IResponse<PagePayload<AdminToolSource>>> => {
  return request.get({ url: '/api/admin/tool-sources', params: { pageSize: 100 } })
}

export const listAdminFieldMappingsApi = (): Promise<IResponse<PagePayload<AdminFieldMapping>>> => {
  return request.get({ url: '/api/admin/field-mappings', params: { pageSize: 100 } })
}

export const previewAdminConfigDiffApi = (
  payload: AdminConfigChangePayload
): Promise<IResponse<AdminConfigDiffPayload>> => {
  return request.post({ url: '/api/admin/config-diff/preview', data: payload })
}

export const createAdminConfigItemApi = (
  payload: AdminConfigCreatePayload
): Promise<IResponse<AdminConfigSaveResult>> => {
  return request.post({ url: `/api/admin/config-items/${payload.target}`, data: payload })
}

export const saveAdminConfigItemApi = (
  payload: AdminConfigChangePayload
): Promise<IResponse<AdminConfigSaveResult>> => {
  return request.put({
    url: `/api/admin/config-items/${payload.target}/${payload.id}`,
    data: payload
  })
}

export const publishAdminConfigApi = (payload: {
  scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
  reason: string
}): Promise<IResponse<AdminPublishConfigPayload>> => {
  return request.post({ url: '/api/admin/config-overview/publish', data: payload })
}

export const searchApi = (params: {
  keyword: string
  projectId?: string
  type?: SearchResult['type']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<SearchResult>>> => {
  return request.get({ url: '/api/search', params })
}

export const listTodosApi = (params?: {
  role?: RoleCode
  projectId?: string
  status?: TodoItem['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<TodoItem>>> => {
  return request.get({ url: '/api/todos', params })
}

export const getTodoDetailApi = (todoId: string): Promise<IResponse<TodoDetailPayload>> => {
  return request.get({ url: `/api/todos/${todoId}` })
}

export const completeTodoApi = (
  todoId: string,
  payload?: { result?: string; comment?: string }
): Promise<IResponse<MockMutationResult>> => {
  return request.post({ url: `/api/todos/${todoId}/complete`, data: payload || {} })
}

export const listMessagesApi = (params?: {
  projectId?: string
  read?: boolean
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<MessageItem>>> => {
  return request.get({ url: '/api/messages', params })
}

export const markMessageReadApi = (messageId: string): Promise<IResponse<MockMutationResult>> => {
  return request.post({ url: `/api/messages/${messageId}/read` })
}

export const markAllMessagesReadApi = (payload?: {
  projectId?: string
}): Promise<IResponse<{ affectedCount: number }>> => {
  return request.post({ url: '/api/messages/read-all', data: payload || {} })
}
