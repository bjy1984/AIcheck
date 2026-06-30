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
  revision?: number
  etag?: string
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
  businessPackId?: string
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
  snapshotId: string
  nextStatus: '待审查'
  createdTodos: TodoItem[]
  submittedReportIds: string[]
  submittedFilmIds: string[]
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
  scorecard?: {
    schemaVersion?: string
    targetScore: number
    score: number
    ok: boolean
    sections: Array<{
      name: string
      score: number
      maxScore: number
      status: string
      blockers?: string[]
    }>
    blockers: string[]
    retrievalProbes?: Array<Record<string, unknown>>
  }
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
  revision?: number
  etag?: string
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
  updatedAt?: string
  finishedAt?: string
  revision?: number
  etag?: string
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

export type KnowledgePageIndexNode = {
  id?: string
  pageIndexNodeId: string
  kbDocId?: string
  kbVersion?: string
  nodeId: string
  parentNodeId?: string | null
  title: string
  summary?: string
  startPage?: number
  endPage?: number
  sectionPath?: string[]
  children?: string[]
  linkedClauseIds?: string[]
  businessPackId?: string
  nodeTypes?: string[]
  materialTypes?: string[]
  tags?: string[]
  status?: string
  score?: number
}

export type KnowledgeRetrievalTrace = {
  retrievalTraceId: string
  queryType?: string
  selectedRoute?: string
  routerVersion?: string
  routerSignals?: Record<string, unknown>
  queryRouter?: {
    selectedRoute?: string
    fallbackRoute?: string
    signals?: Record<string, unknown>
  }
  retrievers?: Array<Record<string, unknown>>
  selectedClauses?: Array<Record<string, unknown>>
  pageIndexTree?: {
    candidateNodeCount?: number
    selectedNodes?: KnowledgePageIndexNode[]
    linkedClauseIds?: string[]
    treeSearchPath?: Array<Record<string, unknown>>
  }
}

export type KnowledgeRetrievalTestPayload = {
  answerDraft: string
  hits: EvidenceLink[]
  retrievalTrace?: KnowledgeRetrievalTrace
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
  revision?: number
  etag?: string
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
  revision?: number
  etag?: string
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
  modelCodes: string[]
  status?: '排队中' | '运行中' | '完成' | '失败'
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
  status?: '排队中' | '运行中' | '完成' | '失败'
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
  revision?: number
  etag?: string
  updatedAt?: string
  lastPublishedVersion?: string
  lastPublishedAt?: string
  lastPublishedScope?: string
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
  businessPacks?: BusinessPackSummary[]
}

export type BusinessPackSummary = {
  id: string
  name: string
  version: string
  domainType: string
  status: 'draft' | 'candidate' | 'published' | 'deprecated' | 'archived' | string
  snapshotHash: string
  roleCount: number
  nodeCount: number
  materialTypeCount: number
  ruleSetCount: number
  agentSopCount: number
  fixtureProjectCount?: number
}

export type BusinessPackValidation = {
  ok: boolean
  errors: string[]
  warnings: string[]
}

export type BusinessPackPortabilityScorecard = {
  schemaVersion?: string
  targetScore: number
  score: number
  ok: boolean
  sections: Array<{
    name: string
    score: number
    maxScore: number
    status: string
    blockers?: string[]
  }>
  blockers: string[]
  packs?: Array<{
    packId: string
    domainType: string
    score: number
    ok: boolean
    summary: BusinessPackSummary
    componentStatus?: Record<string, boolean>
    fixtureStatus?: Record<string, boolean>
    portabilityStatus?: Record<string, boolean>
    blockers?: string[]
  }>
}

export type BusinessPackDetail = BusinessPackSummary & {
  validation?: BusinessPackValidation
  roles?: Array<{ code: string; label: string; platformRole: string; defaultPath: string }>
  nodeTemplates?: Array<{ nodeId: number; code: string; name: string; groupName: string }>
  materialTypes?: Array<{ code: string; name: string; requiredType: string }>
  ruleSets?: Array<{ id: string; name: string; ruleKey: string; version: string; status: string }>
  agentSops?: Array<{ id: string; name: string; version: string }>
}

export type BusinessPackValidateAllPayload = {
  ok: boolean
  scorecard?: BusinessPackPortabilityScorecard
  results: Array<{
    summary: BusinessPackSummary
    validation: BusinessPackValidation
  }>
}

export type ReviewFinding = {
  id: string
  projectId: string
  nodeId: number
  businessPackId: string
  businessPackVersion: string
  businessPackSnapshotHash?: string
  agentId?: string
  agentVersion?: string
  findingType: string
  severity: 'low' | 'medium' | 'high' | string
  title: string
  description: string
  evidenceLinkIds: string[]
  ruleRefs: Array<{ ruleSetId: string; ruleCode?: string }>
  confidence: number
  suggestedAction: string
  status: string
  source: 'ai' | 'human' | string
  humanStatus?: string
  createdAt: string
}

export type GenericReviewWorkbenchPayload = {
  project: Project
  businessPack: BusinessPackSummary
  nodes: ProjectTreeNode[]
  findings: ReviewFinding[]
  aiRuns: AiReviewRun[]
}

export type FdeMetric = {
  label: string
  value: number | string
  tone: string
  suffix?: string
}

export type FdeDashboardPayload = {
  metrics: FdeMetric[]
  alerts: Array<{ id: string; severity: string; title: string; status: string }>
  agentPerformance: Array<{
    agentId: string
    version: string
    status: string
    riskLevel: string
    acceptanceRate: number
    evidenceHitRate: number
    hallucinationRate: number
  }>
  cost: { tokenEstimate: number; estimatedPrice: number; budgetStatus: string }
  releaseStatus: { bundles: number; releasePlans: number; pendingApprovals: number }
}

export type FdeAiRun = AiReviewRun & {
  versionSnapshot?: Record<string, unknown>
  inputHash?: string
  outputHash?: string
  immutable?: boolean
  rawAccess?: boolean
  parentRunId?: string
  runType?: string
}

export type FdeAiRunDetailPayload = {
  run: FdeAiRun
  traceSteps: Array<Record<string, unknown>>
  replays: Array<Record<string, unknown>>
  feedback: FdeFeedback[]
  accessPolicy: { rawAccess: boolean; rawAccessRequiresGrant: boolean }
}

export type FdeReviewRun = {
  id: string
  reviewRunId: string
  aiRunId?: string
  projectId?: string
  nodeId?: number | string
  businessPackId?: string
  agentId?: string
  agentVersion?: string
  promptVersion?: string
  modelAlias?: string
  modelGateway?: string
  workflowEngine?: string
  graphEngine?: string
  graphRunner?: string
  workflowId?: string
  temporalRunId?: string
  status?: string
  currentStep?: string
  runMode?: string
  inputHash?: string
  outputHash?: string
  parentReviewRunId?: string
  graphSummary?: { total: number; statusCounts: Record<string, number> }
  graphExecution?: Record<string, unknown>
  createdAt?: string
  updatedAt?: string
}

export type ReviewGraphPayload = {
  reviewRunId?: string
  nodes: Array<Record<string, unknown>>
  edges: Array<Record<string, unknown>>
  timeline: Array<Record<string, unknown>>
  artifactSummary?: Record<string, number>
  artifacts?: {
    ruleCheckResults?: Array<Record<string, unknown>>
    retrievalTraces?: Array<Record<string, unknown>>
    findingDrafts?: Array<Record<string, unknown>>
  }
}

export type FdeReviewRunDetailPayload = {
  run: FdeReviewRun
  graph: ReviewGraphPayload
  timeline: Array<Record<string, unknown>>
  temporal: Record<string, unknown>
  reasoningTrace?: Array<Record<string, unknown>>
  lineage?: Record<string, unknown>
  qualityEvaluation?: {
    score?: number
    status?: string
    dimensions?: Array<Record<string, unknown>>
    gates?: Array<Record<string, unknown>>
    humanReviewRequired?: boolean
  }
  humanCorrections?: Array<Record<string, unknown>>
  redactionPolicy?: string
  scorecard?: {
    schemaVersion?: string
    targetScore: number
    score: number
    ok: boolean
    sections: Array<{
      name: string
      score: number
      maxScore: number
      status: string
      blockers?: string[]
    }>
    blockers: string[]
  }
}

export type FdeProjectAuditSummary = {
  project: Project
  metrics: Record<string, number>
  currentNodeId?: number
  currentNodeName?: string
  topBlockers: Array<Record<string, unknown>>
  updatedAt?: string
}

export type FdeProjectAuditDocument = DocumentAsset & {
  knowledgeFileId?: string
  knowledgeSourceId?: string
  knowledgeSourceName?: string
  sliceStatus?: '未切片' | '切片中' | '已切片' | '切片失败' | string
  vectorStatus?: KnowledgeSource['vectorStatus'] | string
  chunkCount?: number
  vectorCount?: number
  embeddingModel?: string
  indexVersion?: string
  vectorDimensions?: number
  pageIndexStatus?: string
  pageIndexNodeCount?: number
  latestKnowledgeTask?: Record<string, unknown> | string
}

export type FdeProjectAuditWorkspace = {
  project: Project
  selectedNodeId?: number
  selectedNode?: ProjectTreeNode | null
  groups: Array<{ groupName: string; nodes: ProjectTreeNode[] }>
  nodeSummaries: Array<Record<string, unknown>>
  metrics: Record<string, number>
  documents: FdeProjectAuditDocument[]
  bindings: NodeFileBinding[]
  submissions: Array<Record<string, unknown>>
  reviewRuns: FdeReviewRun[]
  aiRuns: FdeAiRun[]
  ocrJobs: Array<Record<string, unknown>>
  ocrAnnotationTasks: Array<Record<string, unknown>>
  qualityBlockers: Array<Record<string, unknown>>
  updatedAt?: string
}

export type FdeFeedback = {
  id: string
  aiRunId: string
  projectId: string
  nodeId: number
  feedbackType: string
  accepted: boolean
  comment?: string
  status?: string
  rootCause?: string
  shouldEnterEvaluationSet?: boolean
  governanceState?: string
  evaluationCaseId?: string
  evaluationSetId?: string
  evaluationCaseStatus?: string
  canUseForEval?: boolean
  canUseForTraining?: boolean
  dataSensitivity?: string
  adjudicationRequired?: boolean
  sampleUsage?: Record<string, unknown>
  createdAt: string
  triage?: Record<string, unknown>
}

export type FdeEvaluationCaseResult = {
  id: string
  evaluationRunId: string
  evaluationCaseId: string
  sourceFeedbackId?: string
  feedbackType?: string
  rootCause?: string
  riskLevel?: string
  status: string
  expectedFindingCount?: number
  matchedFindingCount?: number
  actualFindingCount?: number
  missingFindings?: string[]
  unexpectedFindings?: string[]
  expectedEvidenceCount?: number
  actualEvidenceCount?: number
  evidencePassed?: boolean
  retrievalQuery?: string
  retrievalTraceId?: string
  expectedClauseIds?: string[]
  selectedClauseIds?: string[]
  missingClauseIds?: string[]
  unexpectedTopClauseId?: string
  expectedClauseCount?: number
  matchedClauseCount?: number
  retrievalRecall?: number
  retrievalPassed?: boolean
  selectedRoute?: string
  expectedRoute?: string
  routePassed?: boolean
  replayMode?: string
  createdAt?: string
}

export type FdeEvaluationRun = {
  id: string
  evaluationSetId: string
  capabilityBundleId?: string
  status: string
  metrics?: Record<string, number | string | boolean>
  caseSummary?: Record<string, number | string | boolean>
  startedAt?: string
  finishedAt?: string
}

export type FdeEvaluationReport = {
  id: string
  evaluationRunId: string
  capabilityBundleId?: string
  businessPackId?: string
  status: string
  summary?: string
  metrics?: Record<string, number | string | boolean>
  caseSummary?: Record<string, number | string | boolean>
  caseResults?: FdeEvaluationCaseResult[]
  gateResults?: Array<Record<string, unknown>>
  createdAt?: string
}

export type FdeEvaluationReportPayload = {
  report: FdeEvaluationReport
  metrics: Array<Record<string, unknown>>
  caseResults: FdeEvaluationCaseResult[]
}

export type FdeEvaluationPayload = {
  sets: Array<Record<string, unknown>>
  cases: Array<Record<string, unknown>>
  runs: FdeEvaluationRun[]
  reports: FdeEvaluationReport[]
}

export type FdeCapabilityBundlePayload = {
  bundles: Array<Record<string, unknown>>
  agents: Array<Record<string, unknown>>
  prompts: Array<Record<string, unknown>>
  modelRoutes: Array<Record<string, unknown>>
  ocrProfiles: Array<Record<string, unknown>>
}

export type FdeReleasePayload = {
  plans: Array<Record<string, unknown>>
  approvals: Array<Record<string, unknown>>
  gates: Array<Record<string, unknown>>
}

export type FdeAccessPayload = {
  grants: Array<Record<string, unknown>>
  exports: Array<Record<string, unknown>>
  budgets: Array<Record<string, unknown>>
  changeRequests?: Array<Record<string, unknown>>
  usage: { tokenEstimate: number; estimatedPrice: number; runCount: number }
}

export type FdeIncidentPayload = {
  incidents: Array<Record<string, unknown>>
  rca: Array<Record<string, unknown>>
}

export type FdeOcrQualityPayload = {
  fileLevel: { total: number; success: number; failed: number; parseSuccessRate?: number }
  fieldLevel: {
    total: number
    lowConfidence: number
    manualCorrectionRate: number
    parseResultCount?: number
    parseFieldCount?: number
    lowConfidenceParseFieldCount?: number
    conflictFieldCount?: number
    evidenceMissingFieldCount?: number
    missingRequiredFieldCount?: number
    averageFieldConfidence?: number
    missingRequiredFieldBreakdown?: Array<{ fieldCode: string; count: number }>
    sampleMissingRequiredFields?: Array<Record<string, unknown>>
    sourceBreakdown?: Array<{ source: string; count: number }>
    fieldCodeBreakdown?: Array<{ fieldCode: string; count: number }>
    qualityFlagCounts?: Array<{ flag: string; count: number }>
    sampleFields?: Array<Record<string, unknown>>
  }
  evidenceLevel?: {
    parseResultCount: number
    scoredResultCount: number
    averageEvidenceCompleteness: number
    missingEvidence: number
    fieldEvidenceMissing: number
    tableEvidenceMissing: number
    sealEvidenceMissing: number
    unknownEvidenceMissing: number
    missingEvidenceItems: Array<Record<string, unknown>>
  }
  tableLevel?: {
    parseResultCount: number
    tableCount: number
    formalTableCount: number
    heuristicTableCount: number
    reviewRequiredCount: number
    missingRequiredTableCount?: number
    businessRowCount: number
    normalizedRowCount: number
    cellCount: number
    averageTableConfidence: number
    formalTableRate: number
    heuristicTableRate: number
    reviewRequiredRate: number
    missingRequiredTableBreakdown?: Array<{ tableCode: string; count: number }>
    sampleMissingRequiredTables?: Array<Record<string, unknown>>
    sourceBreakdown: Array<{ source: string; count: number }>
    qualityFlagCounts: Array<{ flag: string; count: number }>
    sampleTables: Array<Record<string, unknown>>
  }
  sealLevel?: {
    parseResultCount: number
    sealCount: number
    readableSealCount: number
    fragmentSealCount: number
    visualCandidateCount: number
    reviewRequiredCount: number
    missingExpectedSealTypeCount?: number
    missingTextCount: number
    averageSealConfidence: number
    readableSealRate: number
    fragmentSealRate: number
    visualCandidateReviewRate: number
    sealTypeBreakdown?: Array<{ sealType: string; count: number }>
    readableSealTypeBreakdown?: Array<{ sealType: string; count: number }>
    matchedExpectedSealTypeBreakdown?: Array<{ sealType: string; count: number }>
    missingExpectedSealTypeBreakdown?: Array<{ sealType: string; count: number }>
    sampleMissingExpectedSealTypes?: Array<Record<string, unknown>>
    sourceBreakdown: Array<{ source: string; count: number }>
    qualityFlagCounts: Array<{ flag: string; count: number }>
    sampleSeals: Array<Record<string, unknown>>
  }
  jobLevel?: { total: number; success: number; failed: number; running: number }
  lowConfidenceFields: ExtractedField[]
  jobs?: Array<Record<string, unknown>>
  parseResults?: Array<Record<string, unknown>>
  corrections?: Array<Record<string, unknown>>
  evalRuns?: FdeOcrEvalRun[]
  cacheMetrics?: {
    engineRunCount: number
    engineCacheHits: number
    engineCacheHitRate: number
    variantCacheHits: number
    variantCacheHitRate: number
    resultCacheHits: number
    totalDurationMs: number
    averageDurationMs: number
    slowEngines: Array<Record<string, unknown>>
  }
  qualityReasonCounts?: Array<{ reason: string; count: number }>
  runtimeDoctor?: {
    status?: string
    ok?: boolean
    summary?: { pass?: number; warn?: number; fail?: number; total?: number }
    topIssues?: Array<Record<string, unknown>>
    subprocessPython?: string
    schemaVersion?: string
  }
  ocr100Scorecard?: {
    schemaVersion?: string
    targetScore: number
    score: number
    ok: boolean
    sections: Array<{
      name: string
      score: number
      maxScore: number
      status: string
      blockers?: string[]
    }>
    blockers: string[]
  }
  failurePools?: {
    fieldFailures?: Array<Record<string, unknown> | string>
    tableFailures: Array<Record<string, unknown> | string>
    sealFailures: Array<Record<string, unknown> | string>
    engineFailures: Array<Record<string, unknown> | string>
  }
}

export type FdeOcrEvalRun = {
  id: string
  profileId: string
  status: string
  startedAt?: string
  finishedAt?: string
  metrics: Record<string, number | string | boolean>
  gateResults?: Array<Record<string, unknown>>
  evaluationReport?: {
    ok?: boolean
    summary?: {
      cases?: number
      total?: number
      passed?: number
      failed?: number
      averageScore?: number
    }
    metrics?: Record<string, number>
    findingCounts?: Record<string, number>
    thresholdFailures?: Array<Record<string, unknown>>
  }
  evaluationSummary?: {
    ok?: boolean
    summary?: {
      cases?: number
      total?: number
      passed?: number
      failed?: number
      averageScore?: number
    }
    metrics?: Record<string, number>
    findingCounts?: Record<string, number>
    thresholdFailures?: Array<Record<string, unknown>>
    scenarioMetrics?: Record<
      string,
      {
        ok?: boolean
        cases?: number
        passed?: number
        failed?: number
        averageScore?: number
        findingCounts?: Record<string, number>
        thresholdFailures?: Array<Record<string, unknown>>
      }
    >
    failedCases?: Array<{
      caseId?: string
      scenario?: string
      score?: number
      minScore?: number
      qualityStatus?: string
      findings?: string[]
    }>
  }
  scenarioMetrics?: Record<
    string,
    {
      ok?: boolean
      summary?: {
        cases?: number
        total?: number
        passed?: number
        failed?: number
        averageScore?: number
      }
      metrics?: Record<string, number>
      findingCounts?: Record<string, number>
      thresholdFailures?: Array<Record<string, unknown>>
    }
  >
  caseDiagnostics?: Array<{
    caseId?: string
    scenario?: string
    score?: number
    passed?: boolean
    findings?: Array<Record<string, unknown>>
    details?: Record<string, unknown>
  }>
}

export type FdeOcrRunDetailPayload = {
  job: Record<string, unknown>
  parseResult: Record<string, unknown> | null
  corrections: Array<Record<string, unknown>>
}

export type FdeOcrAnnotationTask = {
  taskId?: string
  caseId?: string
  scenario?: string
  profileId?: string
  documentType?: string
  sourcePath?: string
  pageNo?: number
  collectionStatus?: string
  labeledExpected?: Record<string, unknown>
  suggestedExpected?: Record<string, unknown>
  certificationBlockers?: string[]
  readinessBlockers?: string[]
  previewPaths?: string[]
  previewUrl?: string
  pagePreviewUrl?: string
  pageDimensions?: Record<string, [number, number]>
  candidateCounts?: Record<'fields' | 'tables' | 'seals', number>
  labelCounts?: Record<'fields' | 'tables' | 'seals', number>
  readyForEval?: boolean
  labeler?: string
  reviewer?: string
}

export type FdeOcrAnnotationReadinessPayload = {
  schemaVersion?: string
  ok: boolean
  summary: {
    tasks: number
    humanLabeled: number
    readyForEval: number
    missingHumanLabels: number
    completionRate: number
    scenarioCounts?: Record<string, number>
    readyScenarioCounts?: Record<string, number>
    statusCounts?: Record<string, number>
    blockerCounts?: Record<string, number>
  }
  nextActions: string[]
  tasks?: Array<Record<string, unknown>>
}

export type FdeOcrAnnotationPayload = {
  summary: FdeOcrAnnotationReadinessPayload['summary']
  nextActions: string[]
  page: PagePayload<FdeOcrAnnotationTask>
}

export type FdeOcrAnnotationDetailPayload = {
  task: FdeOcrAnnotationTask
  readiness: FdeOcrAnnotationReadinessPayload
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
  revision?: number
  etag?: string
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
  revision?: number
  etag?: string
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
  payload: ProjectMemberSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ member: ProjectMember; auditLogId: string }>> => {
  return request.post({
    url: `/api/projects/${projectId}/members`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updateProjectMemberApi = (
  projectId: string,
  memberId: string,
  payload: Partial<ProjectMemberSavePayload> & { status?: ProjectMember['status'] },
  options?: MutationHeaderOptions
): Promise<IResponse<{ member: ProjectMember; auditLogId: string }>> => {
  return request.put({
    url: `/api/projects/${projectId}/members/${memberId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const createAdminProjectApi = (
  payload: AdminProjectCreatePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<AdminProjectCreateResult>> => {
  return request.post({
    url: '/api/admin/projects',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const createAdminConfigExportApi = (
  payload: {
    scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
    includeAudit?: boolean
    reason?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ exportId: string; task: ExportTask }>> => {
  return request.post({
    url: '/api/admin/config-export',
    data: payload,
    headers: mutationHeaders(options)
  })
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
  files: Array<{ fileName: string; fileSize: number; fileType: string }>,
  options?: MutationHeaderOptions
): Promise<IResponse<UploadSessionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/upload-session`,
    data: { files },
    headers: mutationHeaders(options)
  })
}

export const bindDocumentsToNodeApi = (
  projectId: string,
  payload: {
    nodeId?: number
    nodeIds?: number[]
    bindings: Array<Pick<NodeFileBinding, 'documentId' | 'documentVersionId' | 'usage'>>
  },
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/bindings`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const saveSubmissionDraftApi = (
  projectId: string,
  payload: {
    nodeId?: number
    nodeIds?: number[]
    bindingIds: string[]
    remark?: string
    batchName?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<SubmissionDraftPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/submissions/drafts`,
    data: payload,
    headers: mutationHeaders(options)
  })
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
  },
  options?: MutationHeaderOptions
): Promise<IResponse<SubmissionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/submissions`,
    data: payload,
    headers: mutationHeaders(options)
  })
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
  payload: { bindingIds?: string[]; documentVersionIds?: string[]; reason: string },
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/submissions/${submissionId}/withdraw-items`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const submitRectificationApi = (
  projectId: string,
  payload: { nodeId: number; bindingIds: string[]; comment: string },
  options?: MutationHeaderOptions
): Promise<IResponse<RectificationPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/rectifications`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const requestAiRecheckApi = (
  projectId: string,
  nodeId: number,
  options?: MutationHeaderOptions
): Promise<IResponse<AiRecheckPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-recheck`,
    headers: mutationHeaders(options)
  })
}

export const saveReviewOpinionApi = (
  projectId: string,
  nodeId: number,
  payload: { result: ReviewOpinion['result']; opinion: string; evidenceLinkIds: string[] },
  options?: MutationHeaderOptions
): Promise<IResponse<ReviewOpinionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/review-opinions`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const adoptAiSuggestionApi = (
  projectId: string,
  nodeId: number,
  suggestionId: string,
  payload: { result: ReviewOpinion['result']; opinion: string; reason: string },
  options?: MutationHeaderOptions
): Promise<IResponse<AiSuggestionAdoptPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-suggestions/${suggestionId}/adopt`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const rejectAiSuggestionApi = (
  projectId: string,
  nodeId: number,
  suggestionId: string,
  payload: { reason: string; manualOpinion?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-suggestions/${suggestionId}/reject`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const returnCorrectionApi = (
  projectId: string,
  nodeId: number,
  payload: { reason: string; evidenceLinkIds: string[] },
  options?: MutationHeaderOptions
): Promise<IResponse<ReturnCorrectionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/actions/return-correction`,
    data: payload,
    headers: mutationHeaders(options)
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
  },
  options?: MutationHeaderOptions
): Promise<IResponse<ReportReviewPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/report-review`,
    data: payload,
    headers: mutationHeaders(options)
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
  payload: { format: 'docx' | 'pdf' },
  options?: MutationHeaderOptions
): Promise<IResponse<ReportExportPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/reports/${reportId}/export`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const archiveReportApi = (
  projectId: string,
  reportId: string,
  payload: { archiveNote?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<ReportArchivePayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/reports/${reportId}/archive`,
    data: payload,
    headers: mutationHeaders(options)
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
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ film: NdtFilm }>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/films`,
    data: payload,
    headers: mutationHeaders(options)
  })
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
  },
  options?: MutationHeaderOptions
): Promise<IResponse<NdtRecordImportPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/records/import`,
    data: payload,
    headers: mutationHeaders(options)
  })
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
  },
  options?: MutationHeaderOptions
): Promise<IResponse<NdtReportUploadPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/reports/upload-session`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const submitNdtSubmissionApi = (
  projectId: string,
  payload: { reportIds: string[]; filmIds?: string[]; nodeId: number },
  options?: MutationHeaderOptions
): Promise<IResponse<NdtSubmissionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/submissions`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const submitNdtRectificationApi = (
  projectId: string,
  payload: {
    rectificationId: string
    description: string
    reportIds?: string[]
    filmIds?: string[]
  },
  options?: MutationHeaderOptions
): Promise<IResponse<NdtRectificationPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/rectifications`,
    data: payload,
    headers: mutationHeaders(options)
  })
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

type MutationHeaderOptions = {
  etag?: string
  idempotencyKey?: string
}

const createIdempotencyKey = () => {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `aicheck-${random}`
}

const mutationHeaders = (options?: MutationHeaderOptions) => {
  const headers: Record<string, string> = {}
  if (options?.etag) headers['If-Match'] = options.etag
  headers['Idempotency-Key'] = options?.idempotencyKey || createIdempotencyKey()
  return Object.keys(headers).length ? headers : undefined
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
  payload: KnowledgeSourceSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({
    url: '/api/knowledge/sources',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const getKnowledgeSourceApi = (
  sourceId: string
): Promise<IResponse<{ source: KnowledgeSource }>> => {
  return request.get({ url: `/api/knowledge/sources/${sourceId}` })
}

export const updateKnowledgeSourceApi = (
  sourceId: string,
  payload: Partial<KnowledgeSourceSavePayload>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.put({
    url: `/api/knowledge/sources/${sourceId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const enableKnowledgeSourceApi = (
  sourceId: string,
  payload?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({
    url: `/api/knowledge/sources/${sourceId}/enable`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const disableKnowledgeSourceApi = (
  sourceId: string,
  payload?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ source: KnowledgeSource; auditLogId: string }>> => {
  return request.post({
    url: `/api/knowledge/sources/${sourceId}/disable`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
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
  payload?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({
    url: `/api/knowledge/tasks/${taskId}/retry`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const cancelKnowledgeTaskApi = (
  taskId: string,
  payload?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({
    url: `/api/knowledge/tasks/${taskId}/cancel`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const reindexKnowledgeFileApi = (
  fileId: string,
  payload?: { force?: boolean },
  options?: MutationHeaderOptions
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({
    url: `/api/knowledge/files/${fileId}/reindex`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const batchReindexKnowledgeApi = (
  payload: {
    scope: 'all' | 'project' | 'source'
    projectId?: string
    sourceId?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ taskIds: string[] }>> => {
  return request.post({
    url: '/api/knowledge/reindex',
    data: payload,
    headers: mutationHeaders(options)
  })
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

export const listKnowledgePageIndexNodesApi = (params?: {
  keyword?: string
  kbDocId?: string
  parentNodeId?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgePageIndexNode>>> => {
  return request.get({ url: '/api/knowledge/page-index-nodes', params })
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
  payload: { reason: string; effectiveAt?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult & { rule: KnowledgeRuleVersion }>> => {
  return request.post({
    url: `/api/rules/versions/${versionId}/publish`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const rollbackKnowledgeRuleVersionApi = (
  versionId: string,
  payload: { reason: string; targetVersion: string },
  options?: MutationHeaderOptions
): Promise<
  IResponse<MockMutationResult & { rule: KnowledgeRuleVersion; target: KnowledgeRuleVersion }>
> => {
  return request.post({
    url: `/api/rules/versions/${versionId}/rollback`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const getKnowledgeConfigApi = (): Promise<
  IResponse<{ config: KnowledgeConfig; updatedAt: string; revision?: number; etag?: string }>
> => {
  return request.get({ url: '/api/knowledge/config' })
}

export const updateKnowledgeConfigApi = (
  payload: Partial<KnowledgeConfig>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    config: KnowledgeConfig
    updatedAt: string
    auditLogId: string
    revision?: number
    etag?: string
  }>
> => {
  return request.put({
    url: '/api/knowledge/config',
    data: payload,
    headers: mutationHeaders(options)
  })
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

export const runLlmCompareApi = (
  payload: {
    question: string
    modelCodes: string[]
    projectId?: string
    nodeId?: number
    evidenceLinkIds?: string[]
  },
  options?: MutationHeaderOptions
): Promise<IResponse<LlmComparePayload>> => {
  return request.post({
    url: '/api/llm/compare',
    data: payload,
    headers: mutationHeaders(options)
  })
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

export const listBusinessPacksApi = (): Promise<IResponse<BusinessPackSummary[]>> => {
  return request.get({ url: '/api/business-packs' })
}

export const getBusinessPackApi = (packId: string): Promise<IResponse<BusinessPackDetail>> => {
  return request.get({ url: `/api/business-packs/${packId}` })
}

export const validateBusinessPackApi = (
  packId: string
): Promise<IResponse<{ summary: BusinessPackSummary; validation: BusinessPackValidation }>> => {
  return request.post({ url: `/api/business-packs/${packId}/validate` })
}

export const validateAllBusinessPacksApi = (): Promise<
  IResponse<BusinessPackValidateAllPayload>
> => {
  return request.post({ url: '/api/business-packs/validate-all' })
}

export const getProjectReviewWorkbenchApi = (
  projectId: string,
  params?: { nodeId?: number }
): Promise<IResponse<GenericReviewWorkbenchPayload>> => {
  return request.get({ url: `/api/projects/${projectId}/review-workbench`, params })
}

export const getFdeDashboardApi = (): Promise<IResponse<FdeDashboardPayload>> => {
  return request.get({ url: '/api/fde/dashboard' })
}

export const listFdeProjectsApi = (): Promise<IResponse<FdeProjectAuditSummary[]>> => {
  return request.get({ url: '/api/fde/projects' })
}

export const getFdeProjectAuditWorkspaceApi = (
  projectId: string,
  params?: { nodeId?: number }
): Promise<IResponse<FdeProjectAuditWorkspace>> => {
  return request.get({ url: `/api/fde/projects/${projectId}/audit-workspace`, params })
}

export const getFdeProjectNodeAuditDetailApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/projects/${projectId}/nodes/${nodeId}/audit-detail` })
}

export const listFdeAiRunsApi = (params?: {
  projectId?: string
  nodeId?: number
  businessPackId?: string
  status?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<FdeAiRun>>> => {
  return request.get({ url: '/api/fde/ai-runs', params })
}

export const getFdeAiRunApi = (runId: string): Promise<IResponse<FdeAiRunDetailPayload>> => {
  return request.get({ url: `/api/fde/ai-runs/${runId}` })
}

export const listFdeReviewRunsApi = (params?: {
  projectId?: string
  nodeId?: number
  submissionId?: string
  documentVersionId?: string
  businessPackId?: string
  status?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<FdeReviewRun>>> => {
  return request.get({ url: '/api/fde/review-runs', params })
}

export const getFdeReviewRunApi = (
  reviewRunId: string
): Promise<IResponse<FdeReviewRunDetailPayload>> => {
  return request.get({ url: `/api/fde/review-runs/${reviewRunId}` })
}

export const getFdeReviewRunGraphApi = (
  reviewRunId: string
): Promise<IResponse<ReviewGraphPayload>> => {
  return request.get({ url: `/api/fde/review-runs/${reviewRunId}/graph` })
}

export const getFdeReviewRunTemporalHistoryApi = (
  reviewRunId: string
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/review-runs/${reviewRunId}/temporal-history` })
}

export const listFdeAccessGrantsApi = (): Promise<IResponse<Array<Record<string, unknown>>>> => {
  return request.get({ url: '/api/fde/access-grants' })
}

export const requestFdeAccessGrantApi = (
  data: { targetType: string; targetId: string; reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ grant: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/access-grants/request',
    data,
    headers: mutationHeaders(options)
  })
}

export const approveFdeAccessGrantApi = (
  grantId: string,
  data: { status?: string; expiresAt?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ grant: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/access-grants/${grantId}/approve`,
    data,
    headers: mutationHeaders(options)
  })
}

export const createFdeDataExportApi = (
  data: { targetType?: string; targetId?: string; masked?: boolean },
  options?: MutationHeaderOptions
): Promise<IResponse<{ export: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/data-exports',
    data,
    headers: mutationHeaders(options)
  })
}

export const approveFdeDataExportApi = (
  exportId: string,
  data: { status?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ export: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/data-exports/${exportId}/approve`,
    data,
    headers: mutationHeaders(options)
  })
}

export const expireFdeDataExportApi = (
  exportId: string,
  data: { reason?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ export: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/data-exports/${exportId}/expire`,
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeAuditEventsApi = (params?: {
  objectType?: string
  objectId?: string
  limit?: number
}): Promise<IResponse<{ events: Array<Record<string, unknown>>; total: number }>> => {
  return request.get({ url: '/api/fde/audit-events', params })
}

export const getFdeMaskingPoliciesApi = (): Promise<IResponse<Array<Record<string, unknown>>>> => {
  return request.get({ url: '/api/fde/security/masking-policies' })
}

export const createFdeMaskingPolicyApi = (
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ policy: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/security/masking-policies',
    data,
    headers: mutationHeaders(options)
  })
}

export const replayFdeAiRunApi = (
  runId: string,
  data: { runType?: 'diagnostic_replay' | 'evaluation_replay' | 'shadow_replay'; reason?: string },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{ replay: Record<string, unknown>; childRun: FdeAiRun; auditLogId: string }>
> => {
  return request.post({
    url: `/api/fde/ai-runs/${runId}/replay`,
    data,
    headers: mutationHeaders(options)
  })
}

export const replayFdeReviewRunApi = (
  reviewRunId: string,
  data: { runMode?: 'diagnostic_replay' | 'evaluation_replay' | 'shadow_replay'; reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ reviewRun: FdeReviewRun; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/review-runs/${reviewRunId}/replay`,
    data,
    headers: mutationHeaders(options)
  })
}

export const shadowFdeReviewRunApi = (
  reviewRunId: string,
  data: { reason?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ reviewRun: FdeReviewRun; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/review-runs/${reviewRunId}/shadow-run`,
    data,
    headers: mutationHeaders(options)
  })
}

export const listFdeFeedbackApi = (params?: {
  feedbackType?: string
  status?: string
}): Promise<IResponse<FdeFeedback[]>> => {
  return request.get({ url: '/api/fde/feedback', params })
}

export const triageFdeFeedbackApi = (
  feedbackId: string,
  data: {
    rootCause?: string
    status?: string
    canUseForEval?: boolean
    canUseForTraining?: boolean
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    feedback: FdeFeedback
    triage: Record<string, unknown>
    evaluationCase?: Record<string, unknown> | null
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/feedback/${feedbackId}/triage`,
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeEvaluationSetsApi = (params?: {
  setType?: string
}): Promise<IResponse<FdeEvaluationPayload>> => {
  return request.get({ url: '/api/fde/evaluation-sets', params })
}

export const createFdeEvaluationRunApi = (
  data: {
    evaluationSetId: string
    capabilityBundleId?: string
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    run: FdeEvaluationRun
    report: FdeEvaluationReport
    caseResults: FdeEvaluationCaseResult[]
    auditLogId: string
  }>
> => {
  return request.post({
    url: '/api/fde/evaluation-runs',
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeEvaluationReportApi = (
  runId: string
): Promise<IResponse<FdeEvaluationReportPayload>> => {
  return request.get({ url: `/api/fde/evaluation-runs/${runId}/report` })
}

export const getFdeCapabilityBundlesApi = (): Promise<IResponse<FdeCapabilityBundlePayload>> => {
  return request.get({ url: '/api/fde/capability-bundles' })
}

export const createFdeCapabilityBundleApi = (
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ bundle: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/capability-bundles',
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeCapabilityBundleDiffApi = (
  bundleId: string,
  params?: { compareTo?: string }
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/capability-bundles/${bundleId}/diff`, params })
}

export const listFdeReleasesApi = (): Promise<IResponse<FdeReleasePayload>> => {
  return request.get({ url: '/api/fde/releases' })
}

export const createFdeReleaseApi = (
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    plan: Record<string, unknown>
    gates: Array<Record<string, unknown>>
    auditLogId: string
  }>
> => {
  return request.post({
    url: '/api/fde/releases',
    data,
    headers: mutationHeaders(options)
  })
}

export const submitFdeReleaseApi = (
  releaseId: string,
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    plan: Record<string, unknown>
    gates: Array<Record<string, unknown>>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/submit`,
    data,
    headers: mutationHeaders(options)
  })
}

export const approveFdeReleaseApi = (
  releaseId: string,
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    plan: Record<string, unknown>
    approval: Record<string, unknown>
    gates: Array<Record<string, unknown>>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/approve`,
    data,
    headers: mutationHeaders(options)
  })
}

export const startFdeShadowApi = (
  releaseId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    plan: Record<string, unknown>
    gates: Array<Record<string, unknown>>
    auditLogId: string | null
  }>
> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/start-shadow`,
    data,
    headers: mutationHeaders(options)
  })
}

export const markFdeShadowPassedApi = (
  releaseId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ plan: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/mark-shadow-passed`,
    data,
    headers: mutationHeaders(options)
  })
}

export const requestFdeCanaryApi = (
  releaseId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ plan: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/request-canary`,
    data,
    headers: mutationHeaders(options)
  })
}

export const approveFdeProductionReleaseApi = (
  releaseId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    plan: Record<string, unknown>
    gates: Array<Record<string, unknown>>
    auditLogId: string | null
  }>
> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/approve-production`,
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeReleaseImpactApi = (
  releaseId: string
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/releases/${releaseId}/impact` })
}

export const rollbackFdeReleaseApi = (
  releaseId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ plan: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/releases/${releaseId}/rollback`,
    data,
    headers: mutationHeaders(options)
  })
}

export const validateFdeBusinessPacksApi = (): Promise<
  IResponse<BusinessPackValidateAllPayload>
> => {
  return request.post({ url: '/api/fde/business-packs/validate-all' })
}

export const getFdeBusinessPackDiffApi = (
  packId: string,
  params?: { compareTo?: string; tenantId?: string }
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/business-packs/${packId}/diff`, params })
}

export const installFdeBusinessPackApi = (
  packId: string,
  data: { tenantId?: string; dryRun?: boolean },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    installation: Record<string, unknown>
    validation: Record<string, unknown>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/business-packs/${packId}/install`,
    data,
    headers: mutationHeaders(options)
  })
}

export const upgradeFdeBusinessPackApi = (
  packId: string,
  data: { tenantId?: string; dryRun?: boolean },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    installation: Record<string, unknown>
    validation: Record<string, unknown>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/business-packs/${packId}/upgrade`,
    data,
    headers: mutationHeaders(options)
  })
}

export const rollbackFdeBusinessPackApi = (
  packId: string,
  data: { tenantId?: string; dryRun?: boolean; targetVersion?: string; reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ installation: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/business-packs/${packId}/rollback`,
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeOcrQualityApi = (params?: {
  projectId?: string
  nodeId?: number
  profileId?: string
}): Promise<IResponse<FdeOcrQualityPayload>> => {
  return request.get({ url: '/api/fde/ocr-quality', params })
}

export const listFdeOcrRunsApi = (params?: {
  projectId?: string
  nodeId?: number
  documentVersionId?: string
  pageNo?: number
  pageSize?: number
  status?: string
  profileId?: string
}): Promise<IResponse<PagePayload<Record<string, unknown>>>> => {
  return request.get({ url: '/api/fde/ocr-runs', params })
}

export const getFdeOcrRunApi = (jobId: string): Promise<IResponse<FdeOcrRunDetailPayload>> => {
  return request.get({ url: `/api/fde/ocr-runs/${jobId}` })
}

export const listFdeOcrAnnotationTasksApi = (params?: {
  projectId?: string
  nodeId?: number
  documentVersionId?: string
  pageNo?: number
  pageSize?: number
  status?: string
  scenario?: string
  profileId?: string
}): Promise<IResponse<FdeOcrAnnotationPayload>> => {
  return request.get({ url: '/api/fde/ocr-annotation/tasks', params })
}

export const getFdeOcrAnnotationTaskApi = (
  taskId: string
): Promise<IResponse<FdeOcrAnnotationDetailPayload>> => {
  return request.get({ url: `/api/fde/ocr-annotation/tasks/${taskId}` })
}

export const getFdeOcrAnnotationReadinessApi = (
  data?: { tasks?: FdeOcrAnnotationTask[] },
  options?: MutationHeaderOptions
): Promise<IResponse<FdeOcrAnnotationReadinessPayload>> => {
  return request.post({
    url: '/api/fde/ocr-annotation/readiness',
    data: data || {},
    headers: mutationHeaders(options)
  })
}

export const importFdeOcrAnnotationPackApi = (
  data: {
    tasks?: FdeOcrAnnotationTask[]
    pack?: { tasks?: FdeOcrAnnotationTask[] }
    replace?: boolean
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    summary: Record<string, unknown>
    readiness: FdeOcrAnnotationReadinessPayload
    page: PagePayload<FdeOcrAnnotationTask>
    auditLogId: string
  }>
> => {
  return request.post({
    url: '/api/fde/ocr-annotation/import-pack',
    data,
    headers: mutationHeaders(options)
  })
}

export const exportFdeOcrAnnotationLabelStudioApi = (
  data?: {
    tasks?: FdeOcrAnnotationTask[]
    includeWithoutImage?: boolean
    previewBaseDir?: string
    localFilesRoot?: string
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    summary: Record<string, unknown>
    labelConfigXml: string
    tasks: Array<Record<string, unknown>>
  }>
> => {
  return request.post({
    url: '/api/fde/ocr-annotation/export-label-studio',
    data: data || {},
    headers: mutationHeaders(options)
  })
}

export const saveFdeOcrAnnotationLabelApi = (
  taskId: string,
  data: {
    labeler?: string
    comment?: string
    collectionStatus?: string
    labeledExpected: Record<string, unknown>
    pageDimensions?: Record<string, [number, number]>
    pageNo?: number
    previewUrl?: string
    pagePreviewUrl?: string
    pagePreviewPath?: string
    sourcePath?: string
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    task: FdeOcrAnnotationTask
    readiness: FdeOcrAnnotationReadinessPayload
    auditLogId: string
  }>
> => {
  return request.put({
    url: `/api/fde/ocr-annotation/tasks/${taskId}/label`,
    data,
    headers: mutationHeaders(options)
  })
}

export const verifyFdeOcrAnnotationTaskApi = (
  taskId: string,
  data: {
    labeler?: string
    reviewer?: string
    decision?: 'approved' | 'rejected'
    reason?: string
    comment?: string
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    task: FdeOcrAnnotationTask
    readiness: FdeOcrAnnotationReadinessPayload
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/ocr-annotation/tasks/${taskId}/verify`,
    data,
    headers: mutationHeaders(options)
  })
}

export const reviewFdeOcrAnnotationTaskApi = (
  taskId: string,
  data: {
    labeler?: string
    reviewer?: string
    comment?: string
    collectionStatus?: string
    labeledExpected?: Record<string, unknown>
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    task: FdeOcrAnnotationTask
    readiness: FdeOcrAnnotationReadinessPayload
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/ocr-annotation/tasks/${taskId}/review`,
    data,
    headers: mutationHeaders(options)
  })
}

export const createFdeOcrCorrectionApi = (
  data: {
    fieldId?: string
    documentVersionId?: string
    correctedValue?: string
    correctedBbox?: unknown
    reason?: string
    shouldEnterEvaluationSet?: boolean
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ correction: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/ocr-corrections',
    data,
    headers: mutationHeaders(options)
  })
}

export const createFdeOcrEvaluationRunApi = (
  data?: {
    profileId?: string
    caseCount?: number
    cases?: Array<Record<string, unknown>>
    thresholds?: Record<string, unknown>
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ run: FdeOcrEvalRun; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/ocr-evaluation-runs',
    data: data || {},
    headers: mutationHeaders(options)
  })
}

export const listFdeIncidentsApi = (): Promise<IResponse<FdeIncidentPayload>> => {
  return request.get({ url: '/api/fde/incidents' })
}

export const updateFdeIncidentRcaApi = (
  incidentId: string,
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ rca: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/incidents/${incidentId}/rca`,
    data,
    headers: mutationHeaders(options)
  })
}

export const closeFdeIncidentApi = (
  incidentId: string,
  data: Record<string, unknown> = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ incident: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/incidents/${incidentId}/close`,
    data,
    headers: mutationHeaders(options)
  })
}

export const getFdeCostBudgetsApi = (): Promise<IResponse<FdeAccessPayload>> => {
  return request.get({ url: '/api/fde/cost-budgets' })
}

export const proposeFdeCostBudgetChangeApi = (
  budgetId: string,
  data: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ changeRequest: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/cost-budgets/${budgetId}/propose-change`,
    data,
    headers: mutationHeaders(options)
  })
}

export const listFdeAcceptanceReportsApi = (): Promise<
  IResponse<Array<Record<string, unknown>>>
> => {
  return request.get({ url: '/api/fde/acceptance-reports' })
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
  payload: AdminConfigCreatePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<AdminConfigSaveResult>> => {
  return request.post({
    url: `/api/admin/config-items/${payload.target}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const saveAdminConfigItemApi = (
  payload: AdminConfigChangePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<AdminConfigSaveResult>> => {
  return request.put({
    url: `/api/admin/config-items/${payload.target}/${payload.id}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const publishAdminConfigApi = (
  payload: {
    scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
    reason: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<AdminPublishConfigPayload>> => {
  return request.post({
    url: '/api/admin/config-overview/publish',
    data: payload,
    headers: mutationHeaders(options)
  })
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
  payload?: { result?: string; comment?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult & { todo?: TodoItem }>> => {
  return request.post({
    url: `/api/todos/${todoId}/complete`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const listMessagesApi = (params?: {
  projectId?: string
  read?: boolean
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<MessageItem>>> => {
  return request.get({ url: '/api/messages', params })
}

export const markMessageReadApi = (
  messageId: string,
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult & { message?: MessageItem }>> => {
  return request.post({
    url: `/api/messages/${messageId}/read`,
    headers: mutationHeaders(options)
  })
}

export const markAllMessagesReadApi = (
  payload?: {
    projectId?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ affectedCount: number; messages?: MessageItem[]; auditLogId?: string }>> => {
  return request.post({
    url: '/api/messages/read-all',
    data: payload || {},
    headers: mutationHeaders(options)
  })
}
