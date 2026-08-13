import request from '@/axios'
import type {
  ActionCode,
  AiReviewRun,
  DispatchStatus,
  DocumentAsset,
  DocumentVersion,
  EvidenceLink,
  EvidenceSelectionValidation,
  ExportTask,
  ExtractedField,
  MessageItem,
  MockMutationResult,
  NodeEvidenceReadiness,
  NodeFileBinding,
  NodePackagePayload,
  NdtFeedback,
  NdtFilm,
  NdtSubmissionReadiness,
  NdtReport,
  Project,
  ProjectTreeNode,
  ArchiveItem,
  NdtRecord,
  ReportEvidenceScope,
  ReportEvidenceValidation,
  ReportVersion,
  ReviewOpinion,
  RoleCode,
  RuntimeUiContext,
  OperationsOverview,
  OperationArea,
  OperationTask,
  ImpactPreview,
  InspectionAuditOverviewPayload,
  InspectionSubmittedDocumentsPayload,
  InspectionAuditWorkspacePayload,
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

export type KnowledgeReindexPayload = {
  scope: 'all' | 'project' | 'source'
  projectId?: string
  sourceId?: string
  sourceType?: KnowledgeSource['sourceType']
  includeOcr?: boolean
  onlyIncomplete?: boolean
  limit?: number
  reason?: string
  previewId?: string
}

export type KnowledgeReindexImpact = Record<string, unknown> & {
  scope: KnowledgeReindexPayload['scope']
  matchedFiles: number
  estimatedTasks: number
  includeOcr: boolean
  onlyIncomplete: boolean
  sampleFiles: string[]
  warnings: string[]
}

export type AdminConfigPublishImpact = Record<string, unknown> & {
  scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
  totalAffected: number
  linkedProjects: number
  impacts: AdminPublishImpact[]
  warnings: string[]
}

export type KnowledgeRuleOperationImpact = Record<string, unknown> & {
  action: 'publish' | 'rollback'
  ruleVersionId: string
  targetVersionId?: string | null
  targetVersion?: string | null
  nodeIds: number[]
  linkedProjects: number
  summary: {
    added: number
    changed: number
    removed: number
    warning: number
  }
  changes: Array<Record<string, unknown>>
  warnings: string[]
}

export type UploadSessionPayload = {
  uploadSessionId: string
  expiresAt: string
  uploadUrls: Array<{
    fileName: string
    materialCategory?: string | null
    materialTypeCode?: string | null
    materialTypeName?: string | null
    nodeIds?: number[]
    documentId: string
    documentVersionId: string
    url: string
    method: 'PUT'
    expiresAt: string
    headers: Record<string, string>
  }>
}

export type DocumentUploadSessionFile = {
  fileName: string
  fileSize: number
  fileType: string
  materialCategory?: string
  materialTypeCode?: string
  materialTypeName?: string
  nodeIds?: number[]
}

export type UploadSessionCompletePayload = MockMutationResult & {
  queuedTasks: unknown[]
  fileCount: number
  documents?: Array<{
    documentId: string
    documentVersionId: string
    materialTypeCode: string
    materialTypeName: string
    nodeIds: number[]
    bindingIds: string[]
  }>
}

export type SubmissionDraftPayload = {
  draftId: string
  savedAt: string
  bindingIds: string[]
  createdBindingIds?: string[]
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
  bindingIds?: string[]
  createdBindingIds?: string[]
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
  manifest?: Record<string, unknown>
  manifestHash?: string
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
  orgId?: string
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
  userId?: string
  userIds?: string[]
  role?: RoleCode
  nodeScope?: number[]
  actions?: ActionCode[]
  expiresAt?: string
}

export type ProjectMemberMutationPayload = {
  member?: ProjectMember
  members: ProjectMember[]
  successCount: number
  failed: Array<{ userId: string; name: string; message: string }>
  auditLogId?: string
  auditLogIds?: string[]
}

export type AdminOrgUnitType =
  | 'owner'
  | 'contractor'
  | 'ndt'
  | 'inspection'
  | 'supervision'
  | 'admin'
  | 'fde'

export type AdminOrgUnit = {
  id: string
  name: string
  type: AdminOrgUnitType
  contactName: string
  contactPhone: string
  status: '启用' | '停用' | '待授权'
  projectCount: number
  updatedAt?: string
  revision?: number
  etag?: string
}

export type AdminUser = {
  id: string
  username: string
  name: string
  displayName?: string
  orgId?: string
  orgName: string
  role: RoleCode
  roleLabel?: string
  mobile: string
  status: '启用' | '停用'
  lastLoginAt: string
  updatedAt?: string
  revision?: number
  etag?: string
}

export type AdminOrgUnitSavePayload = {
  name: string
  type: AdminOrgUnitType
  contactName?: string
  contactPhone?: string
  status?: AdminOrgUnit['status']
}

export type AdminUserSavePayload = {
  username: string
  name: string
  mobile?: string
  role: RoleCode
  orgId?: string
  orgName?: string
  status?: AdminUser['status']
  password?: string
  initialPassword?: string
}

export type AdminProjectDetailPayload = {
  project: Project
  members: ProjectMember[]
  participantUnits: Array<{
    unitType: 'owner' | 'contractor' | 'ndt' | 'inspection'
    unitName: string
    orgId?: string
    contactName: string
    contactPhone: string
    memberCount?: number
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

export type NdtReportUploadRequest = {
  nodeId: number
  files: Array<{ fileName: string; fileSize: number; fileType: string }>
  reportNo: string
  method: NdtReport['method']
  standardCode: string
  evaluatorName: string
  conclusion: string
  entrustNo?: string
  detectionRatio?: string
  reviewerName?: string
  relatedFilmIds?: string[]
}

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
  ndtReadiness?: NdtSubmissionReadiness
  nodeEvidenceLinks?: EvidenceLink[]
}

export type NdtAtomicMaterialSubmissionPayload = {
  submissionId: string
  snapshotId: string
  documentId: string
  bindingIds: string[]
  nodeIds: number[]
  nextStatus: '待审查'
  createdTodos: TodoItem[]
}

export type NdtAtomicMaterialBindingsPayload = {
  documentId: string
  nodeIds: number[]
  bindingIds: string[]
  createdBindingIds: string[]
  removedBindingIds: string[]
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
  reviewMode?: 'formal' | 'gap_precheck'
  advisoryOnly?: boolean
  stateTransition?: AiReviewRun['stateTransition']
  dispatch?: DispatchStatus
}

export type R12LicenseCandidate = {
  candidateId: string
  documentVersionId: string
  documentId?: string
  fileName?: string
  pageNo: number
  licenseNo?: string
  organizationName?: string
  licenseScopeRaw?: string
  validFrom?: string
  validUntil?: string
  issuer?: string
  ocrConfidence?: number
  evidence?: {
    documentVersionId: string
    pageNo: number
    bbox?: number[]
    quotedText?: string
    confidence?: number
  }
}

export type ReviewHumanInputTask = {
  taskId: string
  taskType: 'official_registry_license_verification' | 'r19_semantic_evidence_confirmation' | string
  schemaVersion?: string
  nodeId: number
  title: string
  description: string
  status: 'pending' | 'completed' | 'stale'
  required: boolean
  blocking?: boolean
  requestedBy?: 'llm_agent' | 'workflow_guard' | string
  officialRegistryUrl?: string
  inputHash: string
  candidateCount?: number
  candidates?: R12LicenseCandidate[]
  questionCount?: number
  questions?: R19HumanInputQuestion[]
  evidenceCandidateCount?: number
  evidenceCandidates?: R19EvidenceCandidate[]
  atomicCheckIds?: string[]
  reasonCode?: string
  responseSchemaRef?: string
  uiSchemaRef?: string
  createdAt: string
  updatedAt: string
}

export type R19HumanInputQuestion = {
  questionId: string
  title: string
  instruction: string
  clauseRefs: string[]
}

export type R19EvidenceCandidate = {
  evidenceRefId: string
  sourceType?: string
  documentVersionId?: string
  fileName?: string
  pageNo?: number
  bbox?: number[]
  quotedText?: string
  confidence?: number
  questionId?: string
  sourceRefs?: Array<{ type: string; url?: string; reference?: string; title?: string }>
  attachmentIds?: string[]
}

export type R19HumanInputAnswer = {
  questionId: string
  outcome: 'confirmed' | 'rejected' | 'unknown'
  value?: unknown
  evidenceRefIds?: string[]
  sourceRefs?: Array<{ type: string; url?: string; reference?: string; title?: string }>
  attachmentIds?: string[]
  comment?: string
  attested: boolean
}

export type R12RegistryVerificationInput = {
  candidateId: string
  outcome: 'verified_match' | 'verified_mismatch' | 'not_found' | 'unable_to_verify'
  registryLicenseNo?: string
  registryOrganizationName?: string
  registryStatus: 'active' | 'expired' | 'revoked' | 'suspended' | 'unknown'
  registryScopeRaw?: string
  registryValidFrom?: string
  registryValidUntil?: string
  sourceUrl?: string
  attachmentIds?: string[]
  comment?: string
  correctionReason?: string
  attested: boolean
}

export type ReviewHumanInputResponsePayload =
  | { verifications: R12RegistryVerificationInput[]; comment?: string }
  | { answers: R19HumanInputAnswer[]; comment?: string }

export type ActiveReviewHumanInputTaskPayload = {
  task: ReviewHumanInputTask | null
  reviewRun: {
    reviewRunId: string
    status: string
    revision: number
    etag: string
  }
}

export type ReviewOpinionPayload = {
  opinion: ReviewOpinion
  nextStatus: string
}

export type AiSuggestionAdoptPayload = {
  draftOpinion: ReviewOpinion & {
    requiresEvidenceSelection?: boolean
    requiresResultSelection?: boolean
    requiresOpinionInput?: boolean
    evidenceValidation?: EvidenceSelectionValidation
  }
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
  reference?: string
  file?: string
  fileName?: string
  knowledgeFileId?: string
  sourceRelativePath?: string
  previewAvailable?: boolean
  previewUrl?: string
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

export type ReportSection = {
  key: string
  title: string
  content: string
  evidenceLinkIds: string[]
}

export type ReportDetailPayload = {
  report: ReportVersion
  sections: ReportSection[]
  evidenceLinks: EvidenceLink[]
  evidenceScope?: ReportEvidenceScope
  evidenceValidation?: ReportEvidenceValidation
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

export type ReportUpdatePayload = MockMutationResult & {
  report: ReportVersion
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
    sourceType?: KnowledgeSource['sourceType']
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

export type KnowledgeNetworkNode = {
  id: string
  type: string
  typeLabel: string
  family: 'business' | 'evidence' | 'rule' | 'semantic' | 'standard' | 'execution' | string
  label: string
  description?: string
  group?: string
  status?: string
  metadata: Record<string, unknown>
}

export type KnowledgeNetworkEdge = {
  id: string
  source: string
  target: string
  type: string
  label: string
  metadata: Record<string, unknown>
}

export type KnowledgeNetworkPayload = {
  schemaVersion: string
  graphId: string
  name: string
  businessPackId: string
  businessPackVersion: string
  sourceSnapshotHash?: string
  checksum: string
  generatedAt: string
  summary: {
    nodeCount: number
    edgeCount: number
    nodeTypeCounts: Record<string, number>
    edgeTypeCounts: Record<string, number>
  }
  nodeTypes: Array<{
    type: string
    label: string
    family: string
    count: number
  }>
  edgeTypes: Array<{
    type: string
    label: string
    count: number
  }>
  nodes: KnowledgeNetworkNode[]
  edges: KnowledgeNetworkEdge[]
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
  originalFileName?: string
  sourceId: string
  sourceName: string
  sourceRelativePath?: string
  contextDescription?: string
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
  revision?: number
  etag?: string
  actions: ActionCode[]
}

export type KnowledgeFileSavePayload = {
  fileName?: string
  sourceRelativePath?: string
  contextDescription?: string
  projectId?: string
  projectName?: string
}

export type KnowledgeFileImportPayload = {
  source: KnowledgeSource
  files: KnowledgeFile[]
  tasks: KnowledgeTask[]
  dispatches?: Array<Record<string, unknown>>
  summary?: {
    sourceId?: string
    standardsRoot?: string
    businessRulesPath?: string
    scanned?: number
    imported?: number
    skipped?: number
    reset?: boolean
    removed?: number
  }
  skipped?: Array<{
    fileName: string
    reason: string
  }>
  auditLogId: string
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
  preview?: DocumentPreviewPayload
  download?: SignedUrlPayload
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
  sourceRuleId?: string
  sourceDocument?: string
  sourceSequence?: number
  businessModule?: string
  inspectionCategory?: string
  inspectionItem?: string
  inspectionClass?: 'A' | 'B' | 'C' | 'C/B' | string
  standardText?: string
  witnessText?: string
  sourceWitness?: string
  reviewClass?: string
  criteria?: string
  checkMethod?: string
  agentThinking?: string
  toolchainThinking?: string
  referencedStandards?: Array<{
    reference?: string
    file?: string
    fileName?: string
    knowledgeFileId?: string
    sourceRelativePath?: string
    previewAvailable?: boolean
    previewUrl?: string
    [key: string]: unknown
  }>
  materialTypeCodes?: string[]
  thinkingModeIds?: string[]
  toolIds?: string[]
  severity?: string
  aiExecution?: {
    schemaVersion?: string
    compiledAt?: string
    sourceFields?: Record<string, unknown>
    requiredEvidence?: string[]
    extractionTargets?: string[]
    verificationSteps?: string[]
    acceptanceCriteria?: string[]
    humanConfirmation?: string[]
    promptContext?: string
  }
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
  field: string
  label: string
  before?: unknown
  after?: unknown
  severity: 'info' | 'warning'
  changeType: 'added' | 'changed' | 'removed'
}

export type KnowledgeRuleVersionSavePayload = {
  sequence?: number
  sourceSequence?: number
  sourceRuleId?: string
  sourceDocument?: string
  businessModule?: string
  inspectionCategory?: string
  inspectionItem: string
  inspectionClass?: string
  standardText?: string
  witnessText?: string
  sourceWitness?: string
  agentThinking?: string
  toolchainThinking?: string
  referencedStandards?: KnowledgeRuleVersion['referencedStandards']
  materialTypeCodes?: string[]
  thinkingModeIds?: string[]
  toolIds?: string[]
  aiExecution?: KnowledgeRuleVersion['aiExecution']
  nodeIds?: number[]
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

export type BusinessRuleImportPayload = {
  rules: KnowledgeRuleVersion[]
  importedRules: KnowledgeRuleVersion[]
  skipped: Array<{
    fileName: string
    reason: string
  }>
  summary: {
    importVersion: string
    imported: number
    skipped: number
    status: KnowledgeRuleVersion['status']
  }
  auditLogId: string
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
  traceSteps?: Array<Record<string, unknown>>
  graphNodes?: Array<Record<string, unknown>>
  promptAudit?: Record<string, unknown>
  llmMetadata?: Record<string, unknown>
}

export type PromptTemplate = {
  id: string
  name: string
  promptKey: string
  version: string
  status: 'draft' | 'production' | 'retired' | '草稿' | '已发布' | '已停用'
  riskLevel: string
  businessPackId: string
  agentId: string
  promptVersionId?: string
  systemPrompt: string
  userPromptTemplate: string
  plannerPromptTemplate?: string
  criticPromptTemplate?: string
  outputSchema?: Record<string, unknown>
  variables?: string[]
  createdAt?: string
  updatedAt: string
  revision?: number
  etag?: string
}

export type PromptTemplateSavePayload = Partial<Omit<PromptTemplate, 'revision' | 'etag'>> & {
  name: string
  systemPrompt: string
  userPromptTemplate: string
}

export type ReportTemplateSection = {
  code: string
  title: string
  source: string
}

export type ReportTemplate = {
  id: string
  name: string
  version: string
  status: 'draft' | 'production' | 'retired' | '草稿' | '已发布' | '已停用'
  businessPackId: string
  businessPackVersion?: string
  exportTypes: Array<'report' | 'archive-package' | 'evidence-package'>
  sections: ReportTemplateSection[]
  createdAt?: string
  updatedAt: string
  publishedAt?: string
  revision?: number
  etag?: string
}

export type ReportTemplateSavePayload = Partial<Omit<ReportTemplate, 'revision' | 'etag'>> & {
  name: string
  sections: ReportTemplateSection[]
}

export type LlmComparePayload = {
  runId: string
  question: string
  createdAt: string
  modelCodes: string[]
  status?: '排队中' | '运行中' | '完成' | '失败' | '未知'
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
  status?: '排队中' | '运行中' | '完成' | '失败' | '未知'
}

export type AuditIntegrityPayload = {
  tenantId: string
  status: 'verified' | 'tampered'
  coverageStatus: 'complete' | 'legacy_unverified_sealed' | 'legacy_unverified_unsealed'
  verifiedEventCount: number
  chainedEventCount: number
  legacyUnverifiedEventCount: number
  legacyUnsealedEventCount?: number
  headHash?: string | null
  failures: Array<Record<string, unknown>>
  legacyManifest?: {
    manifestHash?: string | null
    manifestReference?: string | null
    integrityStatus: 'legacy_unverified'
    sealEventId?: string | null
    sealSequence?: number | null
  } | null
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
  hasMore?: boolean
  nextCursor?: string | null
  paginationMode?: 'offset' | 'keyset'
  integrity?: AuditIntegrityPayload
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

export type AdminMaterialReviewPoint = {
  id: string
  businessPackId: string
  nodeId: number
  nodeName: string
  ruleId?: string
  businessModule?: string
  reviewClass?: string
  reviewContent: string
  materialCategory: string
  materialTypeCode: string
  materialTypeName: string
  fileContent?: string
  evidenceItemText?: string
  evidenceItems: string[]
  responsibleParty: RoleCode | 'inspection'
  responsiblePartyLabel?: string
  requiredType: '必传' | '条件必传' | '可选'
  mappingRelation?: string
  minConfidence: number
  enabled: boolean
  source?: string
  updatedAt: string
  revision?: number
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
  orgUnits: AdminOrgUnit[]
  users: AdminUser[]
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
  materialReviewPoints: AdminMaterialReviewPoint[]
  businessPacks?: BusinessPackSummary[]
}

export type BusinessPackSummary = {
  id: string
  name: string
  version: string
  domainType: string
  description?: string
  pipelineTypeCode?: string
  pipelineTypeName?: string
  commonGrades?: string
  scopeDescription?: string
  projectType?: string
  status: 'draft' | 'candidate' | 'published' | 'deprecated' | 'archived' | string
  snapshotHash: string
  roleCount: number
  nodeCount: number
  materialTypeCount: number
  ruleSetCount: number
  agentSopCount: number
  fixtureProjectCount?: number
  roles?: Array<{
    code: string
    label: string
    platformRole: 'reviewer' | 'submitter' | 'specialist_submitter' | 'observer' | string
  }>
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
  key?: string
  label: string
  value: number | string | null
  tone: string
  suffix?: string
  unit?: string
  numerator?: number | null
  denominator?: number | null
  sampleSize?: number | null
  availability?: 'available' | 'insufficient_data' | string
  scope?: string
}

export type FdeDashboardPayload = {
  schemaVersion?: string
  scope?: { type: string; tenantId?: string; timezone?: string }
  generatedAt?: string
  freshness?: { asOf?: string; stale?: boolean; sourceMaxUpdatedAt?: string | null }
  totals?: {
    projects: number
    aiRuns: number
    reviewRuns: number
    ocrRuns: number
    openBlockers: number
    pendingApprovals: number
  }
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
  runStatus?: Record<string, Record<string, number>>
  blockerSummary?: {
    total: number
    critical: number
    warning: number
    byDomain: Record<string, number>
  }
  dataQuality?: { complete: boolean; warnings: string[] }
}

export type FdeStatusCatalogItem = {
  code: string
  label: string
  tone: 'info' | 'primary' | 'warning' | 'danger' | 'success' | string
  terminal: boolean
}

export type FdeMetaPayload = {
  schemaVersion: string
  viewer: { userId?: string; role?: string; grantedActions: string[] }
  capabilities: Array<{
    key: string
    label: string
    group: string
    route: string
    permission: string
    granted: boolean
  }>
  boundaries: {
    tenantId: string
    tenantScoped: boolean
    businessWriteAllowed: boolean
    productionApprovalAllowed: boolean
    rawModelContentRequiresGrant: boolean
  }
  statusCatalog: FdeStatusCatalogItem[]
  navigationGroups: Array<{ key: string; label: string }>
}

export type FdeBlocker = {
  id: string
  domain: string
  category: string
  severity: 'critical' | 'warning' | 'info' | string
  code: string
  title: string
  description: string
  sourceType: string
  sourceId: string
  projectId?: string | null
  statusCode: string
  statusLabel: string
  statusTone: string
  detectedAt?: string | null
  route: string
  actionLabel: string
}

export type FdeBlockerPage = {
  items: FdeBlocker[]
  page: number
  pageSize: number
  total: number
  summary: {
    total: number
    filtered: number
    bySeverity: Record<string, number>
    byDomain: Record<string, number>
  }
}

export type FdeAiRun = AiReviewRun & {
  versionSnapshot?: Record<string, unknown>
  inputHash?: string
  outputHash?: string
  immutable?: boolean
  rawAccess?: boolean
  llmAuditAvailable?: boolean
  parentRunId?: string
  runType?: string
}

export type FdeLlmAuditPayload = {
  schemaVersion?: string
  runType?: string
  runId?: string
  linkedAiRunId?: string
  visibility?: string
  redactionPolicy?: string
  inputs?: Record<string, unknown>
  outputs?: Record<string, unknown>
  metadata?: Record<string, unknown>
  reasoning?: Record<string, unknown>
  trace?: Record<string, unknown>
}

export type FdeAiRunDetailPayload = {
  run: FdeAiRun
  traceSteps: Array<Record<string, unknown>>
  replays: Array<Record<string, unknown>>
  feedback: FdeFeedback[]
  accessPolicy: { rawAccess: boolean; rawAccessRequiresGrant: boolean }
  llmAudit?: FdeLlmAuditPayload
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
  rawAccess?: boolean
  llmAuditAvailable?: boolean
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
  llmAudit?: FdeLlmAuditPayload
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

export type FdeRawVaultEvent = {
  id: string
  eventType: string
  sequence: number
  stage?: string
  turn?: number
  hasPayload: boolean
  payloadHash?: string
  payloadByteLength?: number
  payloadMediaType?: string
  eventHash: string
  previousEventHash: string
  metadata?: Record<string, unknown>
  createdAt: string
}

export type FdeRawVaultSummary = {
  reviewRunId?: string
  runStreamId?: string
  status:
    | 'complete'
    | 'archive_incomplete'
    | 'unrecoverable_gap'
    | 'hash_mismatch'
    | 'legacy_not_captured'
  chainHead?: string
  eventCount: number
  pendingCount: number
  events: FdeRawVaultEvent[]
}

export type FdeReviewRunAuditPackagePayload = {
  schemaVersion: string
  packageId?: string
  fileName?: string
  reviewRunId: string
  generatedAt?: string
  visibility?: string
  redactionPolicy?: string
  chainOfThoughtPolicy?: Record<string, unknown>
  run: FdeReviewRun
  lineage: Record<string, unknown>
  llmAudit?: FdeLlmAuditPayload
  reasoningTrace: Array<Record<string, unknown>>
  qualityEvaluation: Record<string, unknown>
  humanCorrections: Array<Record<string, unknown>>
  graph: Record<string, unknown>
  timeline: Array<Record<string, unknown>>
  temporal: Record<string, unknown>
  scorecard?: FdeReviewRunDetailPayload['scorecard']
  integrity?: Record<string, unknown>
}

export type FdeProjectAuditSummary = {
  project: Project
  metrics: Record<string, number>
  currentNodeId?: number
  currentNodeName?: string
  topBlockers: Array<Record<string, unknown>>
  updatedAt?: string
}

export type FdeKnowledgeLineageStage = {
  key: string
  label: string
  status: string
  done: boolean
  tone?: string
  evidence?: string
  action?: string
  blocker?: string | null
  metrics?: Record<string, unknown>
}

export type FdeDocumentKnowledgeLineage = {
  schemaVersion?: string
  documentId?: string
  documentVersionId?: string
  knowledgeFileId?: string
  fileName?: string
  readiness?: string
  readinessLabel?: string
  auditConclusion?: string
  localOnly?: boolean
  latestTaskType?: string
  latestTaskStatus?: string
  vectorIndex?: Record<string, unknown>
  pageIndex?: Record<string, unknown>
  stages?: FdeKnowledgeLineageStage[]
  blockers?: string[]
}

export type FdeProjectKnowledgeLineage = {
  schemaVersion?: string
  source?: string
  documents?: FdeDocumentKnowledgeLineage[]
  vectorFlow?: Array<Record<string, unknown>>
  pageIndexFlow?: Array<Record<string, unknown>>
  retrievalTraceCount?: number
  pageIndexTraceCount?: number
  blockers?: Array<Record<string, unknown>>
}

export type FdeVectorQualityPayload = {
  schemaVersion?: string
  score?: number
  targetScore?: number
  status?: string
  statusLabel?: string
  evaluationMode?: string
  localOnly?: boolean
  sections?: Array<{
    key?: string
    name?: string
    score?: number
    maxScore?: number
    metric?: number
    threshold?: number
    status?: string
    blockers?: string[]
  }>
  blockers?: string[]
  metrics?: Record<string, unknown>
  thresholds?: Record<string, unknown>
  documentScores?: Array<Record<string, unknown>>
  retrievalProbeRows?: Array<Record<string, unknown>>
  updatedAt?: string
}

export type FdeTechnologyStackPayload = {
  schemaVersion?: string
  updatedAt?: string
  hotSwap?: Record<string, unknown>
  active?: Record<string, Record<string, unknown>>
  sections?: Array<Record<string, unknown>>
  embeddingModelRegistry?: Array<Record<string, unknown>>
  runtimeReadiness?: Record<string, unknown>
}

export type FdeEvidenceBox = number[] | null | undefined

export type FdeSourcePreviewPage = {
  pageNo?: number
  width?: number | null
  height?: number | null
  previewUrl?: string
  imageObjectKey?: string
  quality?: Record<string, unknown>
}

export type FdeSourcePreviewPayload = {
  schemaVersion?: string
  stage?: string
  label?: string
  status?: string
  fileName?: string
  fileType?: string
  documentId?: string
  documentVersionId?: string
  storageKey?: string
  storageBucket?: string
  fileSize?: number
  contentHash?: string
  previewUrl?: string
  previewType?: string
  pageCount?: number
  pages?: FdeSourcePreviewPage[]
  previewAvailable?: boolean
  previewUnavailableReason?: string
}

export type FdeOcrArtifactRow = {
  id?: string
  fieldName?: string
  fieldCode?: string
  fieldValue?: string
  pageNo?: number | string
  bbox?: FdeEvidenceBox
  confidence?: number
  source?: string
  sourceEngine?: string
  textPreview?: string
}

export type FdeTextRecord = {
  id?: string
  sourceType?: string
  sourceLabel?: string
  pageNo?: number | string
  text?: string
  textHash?: string
  bbox?: FdeEvidenceBox
  confidence?: number | null
  tokenCount?: number
}

export type FdeVectorPayloadRow = {
  id?: string
  chunkNo?: number
  chunkId?: string
  vectorStatus?: string
  textPreview?: string
  embeddingInput?: Record<string, unknown>
  vectorRecord?: Record<string, unknown>
  indexRecord?: Record<string, unknown>
}

export type FdeOcrArtifactsPayload = {
  schemaVersion?: string
  stage?: string
  label?: string
  status?: string
  parseResultId?: string
  profileId?: string
  documentType?: string
  parserVersion?: string
  engineVersion?: string
  summary?: Record<string, unknown>
  fields?: FdeOcrArtifactRow[]
  fragments?: FdeOcrArtifactRow[]
  tables?: Array<Record<string, unknown>>
  seals?: Array<Record<string, unknown>>
  fieldRows?: FdeOcrArtifactRow[]
  fragmentRows?: FdeOcrArtifactRow[]
  diagnostics?: Array<Record<string, unknown>>
  quality?: Record<string, unknown>
}

export type FdeLlmUsagePayload = {
  schemaVersion?: string
  scope?: string
  relatedReviewRunCount?: number
  retrievalTraceCount?: number
  retrievedChunkCount?: number
  retrievalCoverage?: number
  proxyTrace?: boolean
  proxyReason?: string
}

export type FdeQualityIssuePayload = {
  severity?: string
  code?: string
  message?: string
  targetType?: string
  count?: number
}

export type FdeVectorFileDetailPayload = {
  schemaVersion?: string
  compatibleSchemaVersion?: string
  scope?: string
  projectId?: string
  documentId?: string
  documentVersionId?: string
  knowledgeFileId?: string
  fileName?: string
  requirementName?: string
  score?: number
  status?: string
  sliceStatus?: string
  vectorStatus?: string
  embeddingModel?: string
  indexVersion?: string
  vectorDimensions?: number
  chunkSummary?: Record<string, unknown>
  chunkRows?: Array<Record<string, unknown>>
  chunkPage?: PagePayload<Record<string, unknown>>
  chunkCharts?: Record<string, Record<string, number>>
  processingPipeline?: Record<string, unknown>
  sourcePreview?: FdeSourcePreviewPayload
  ocrArtifacts?: FdeOcrArtifactsPayload
  textRecords?: FdeTextRecord[]
  vectorPayloads?: FdeVectorPayloadRow[]
  indexRecords?: Array<Record<string, unknown>>
  llmUsage?: FdeLlmUsagePayload
  qualityIssues?: FdeQualityIssuePayload[]
  corrections?: FdeVectorCorrectionPayload[]
  correctionSummary?: Record<string, unknown>
  retrievalTraceRows?: Array<Record<string, unknown>>
  pageIndexNodes?: Array<Record<string, unknown>>
  sourceRelativePath?: string
  contextType?: string
  blockers?: string[]
  updatedAt?: string
}

export type FdeStandardsVectorizationPayload = {
  schemaVersion?: string
  sourceId?: string
  sourceName?: string
  source?: Record<string, unknown>
  metrics?: Record<string, unknown>
  correctionSummary?: Record<string, unknown>
  files?: Array<Record<string, unknown>>
  filePage?: PagePayload<Record<string, unknown>>
  storage?: Record<string, unknown>
  qualityIssues?: FdeQualityIssuePayload[]
  updatedAt?: string
}

export type FdeVectorCorrectionPayload = {
  id: string
  projectId?: string
  documentId?: string
  documentVersionId?: string
  knowledgeFileId?: string
  fileId?: string
  chunkId?: string
  chunkNo?: number
  pageNo?: number
  bbox?: unknown
  correctionType?: string
  before?: unknown
  after?: unknown
  reason?: string
  status?: string
  statusLabel?: string
  beforePreview?: string
  afterPreview?: string
  taskId?: string
  createdAt?: string
  updatedAt?: string
  reviewedAt?: string
  appliedAt?: string
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
  knowledgeLineage?: FdeDocumentKnowledgeLineage
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
  knowledgeLineage?: FdeProjectKnowledgeLineage
  vectorQuality?: FdeVectorQualityPayload
  technologyStack?: FdeTechnologyStackPayload
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
  ocr100ActionBoard?: {
    schemaVersion?: string
    ok?: boolean
    summary?: {
      status?: string
      score?: number
      readyForEval?: number
      requiredReadyForEval?: number
      collectionMissingCases?: number
      placeholderSampleSlots?: number
      annotationTasks?: number
      remainingHumanLabels?: number
      newLocalCandidates?: number
      duplicateLocalCandidates?: number
      actions?: number
      laneCounts?: Record<string, number>
    }
    handoff?: {
      schemaVersion?: string
      ok?: boolean
      status?: string
      generatedAt?: string
      outputDir?: string
      manifestPath?: string
      summary?: Record<string, unknown>
      staleReasons?: Array<Record<string, unknown>>
      laneCounts?: Record<string, number>
      files?: Array<{
        key?: string
        label?: string
        owner?: string
        purpose?: string
        path?: string
        exists?: boolean
        sizeBytes?: number
      }>
    }
    actions?: Array<Record<string, unknown>>
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

export type FdeOcrCapabilityTestRun = {
  id?: string
  runId: string
  uploadSessionId?: string
  status: string
  profileId?: string
  documentType?: string
  fileName?: string
  contentType?: string
  fileSize?: number
  storageKey?: string
  parseResultId?: string
  annotationTaskId?: string
  evaluationCaseId?: string
  resultSummary?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown> | string>
  engineRuns?: Array<Record<string, unknown>>
  createdAt?: string
  startedAt?: string
  finishedAt?: string
}

export type FdeOcrCapabilityUploadSessionPayload = {
  uploadSession: {
    id?: string
    uploadSessionId: string
    uploadUrl: string
    directUploadUrl?: string
    method: 'PUT'
    headers?: Record<string, string>
    expiresAt?: string
    fileName: string
    contentType?: string
    fileSize?: number
    storageKey: string
    storageUrl?: string
  }
  auditLogId: string
}

export type FdeOcrCapabilityTestDetailPayload = {
  run: FdeOcrCapabilityTestRun
  job?: Record<string, unknown> | null
  parseResult?: Record<string, unknown> | null
  uploadSession?: Record<string, unknown> | null
  preview?: {
    url?: string
    method?: string
    fileName?: string
    contentType?: string
    fileSize?: number
    previewType?: 'pdf' | 'image' | 'office' | 'unsupported'
    pagePreviewUrl?: string
    readonly?: boolean
    storageUnavailable?: boolean
  }
}

export type FdeOcrAnnotationTask = {
  taskId?: string
  caseId?: string
  scenario?: string
  profileId?: string
  documentType?: string
  sourceType?: string
  sourceRunId?: string
  parseResultId?: string
  sourcePath?: string
  pageNo?: number
  pageCount?: number
  collectionStatus?: string
  labeledExpected?: Record<string, unknown>
  suggestedExpected?: Record<string, unknown>
  certificationBlockers?: string[]
  readinessBlockers?: string[]
  previewPaths?: string[]
  previewUrl?: string
  pagePreviewUrl?: string
  pagePreviewPath?: string
  previewType?: 'pdf' | 'image' | 'office' | 'unsupported' | string
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
  | 'material-review-point'

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

export type AdminMaterialReviewPointValues = Partial<AdminMaterialReviewPoint>

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
  | {
      target: 'material-review-point'
      id: string
      values: AdminMaterialReviewPointValues
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
  | {
      target: 'material-review-point'
      values: AdminMaterialReviewPointValues
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

export type AdminConfigDeleteResult = {
  item: Record<string, unknown>
  overview: AdminConfigOverviewPayload
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

export type NodeEvidenceDecisionPayload = {
  evidenceLink: EvidenceLink
  evidenceReadiness: NodeEvidenceReadiness
  auditLogId: string
}

export const listWorkbenchProjectsApi = (role: RoleCode): Promise<IResponse<Project[]>> => {
  return request.get({ url: '/api/workbench/projects', params: { role } })
}

export const listAdminProjectsApi = (params?: {
  page?: number
  pageSize?: number
  keyword?: string
  status?: Project['status'] | ''
}): Promise<IResponse<PagePayload<Project>>> => {
  return request.get({ url: '/api/projects', params })
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
): Promise<IResponse<ProjectMemberMutationPayload>> => {
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

export const deleteProjectMemberApi = (
  projectId: string,
  memberId: string,
  options?: MutationHeaderOptions
): Promise<IResponse<{ deleted: boolean; memberId: string; auditLogId: string }>> => {
  return request.delete({
    url: `/api/projects/${projectId}/members/${memberId}`,
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

export const updateAdminProjectApi = (
  projectId: string,
  payload: Partial<AdminProjectCreatePayload> & { status?: Project['status'] },
  options?: MutationHeaderOptions
): Promise<IResponse<{ project: Project; auditLogId: string }>> => {
  return request.put({
    url: `/api/projects/${projectId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deleteAdminProjectApi = (
  projectId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    deleted: boolean
    archived: boolean
    projectId?: string
    project?: Project
    auditLogId: string
  }>
> => {
  return request.delete({
    url: `/api/projects/${projectId}`,
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

export type NodeLiveStatus = {
  nodeId: number
  nodeStatus?: string
  nodeRevision?: number
  latestAiRun?: {
    id: string
    status: string
    reviewMode?: string
    suggestionResult?: string
    finishedAt?: string
  } | null
  processingDocumentCount: number
  processingDocuments: {
    documentId: string
    fileName?: string
    ocrStatus?: string
    sliceStatus?: string
    vectorStatus?: string
  }[]
}

/** 轮询专用的轻量状态接口，约为完整节点包体积的 0.4%，用于避免定时重拉全量数据。 */
export const getNodeLiveStatusApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<NodeLiveStatus>> => {
  return request.get({ url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/live-status` })
}

export const getInspectionAuditOverviewApi = (
  projectId: string,
  params: {
    keyword?: string
    status?: string
    page?: number
    pageSize?: number
  } = {}
): Promise<IResponse<InspectionAuditOverviewPayload>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/audit-overview`,
    params
  })
}

export const getInspectionSubmittedDocumentsApi = (
  projectId: string,
  params: {
    keyword?: string
    page?: number
    pageSize?: number
  } = {}
): Promise<IResponse<InspectionSubmittedDocumentsPayload>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/submitted-documents`,
    params
  })
}

export const getInspectionAuditWorkspaceApi = (
  projectId: string,
  nodeId: number
): Promise<IResponse<InspectionAuditWorkspacePayload>> => {
  return request.get({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/audit-workspace`
  })
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

export const getDocumentOriginalBlobApi = (url: string): Promise<{ data: Blob }> => {
  return request.get({
    url,
    responseType: 'blob',
    headers: {
      'X-Silent-Http-Error': 'true',
      'X-Silent-Business-Error': 'true'
    }
  }) as unknown as Promise<{ data: Blob }>
}

export interface OfficePreviewPayload {
  documentServerBase: string
  apiScriptUrl: string
  config: Record<string, unknown>
}

/** Office 文件的只读在线预览配置（ONLYOFFICE）。 */
export const getDocumentOfficePreviewApi = (
  projectId: string,
  documentId: string
): Promise<IResponse<OfficePreviewPayload>> => {
  return request.get({
    url: `/api/projects/${projectId}/documents/${documentId}/office-preview`,
    headers: {
      // 未部署预览服务时后端返回 503，由调用方自行呈现，不弹全局错误提示
      'X-Silent-Http-Error': 'true',
      'X-Silent-Business-Error': 'true'
    }
  })
}

export const createDocumentUploadSessionApi = (
  projectId: string,
  files: DocumentUploadSessionFile[],
  options?: MutationHeaderOptions
): Promise<IResponse<UploadSessionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/upload-session`,
    data: { files, requireSignedUrls: true },
    headers: mutationHeaders(options)
  })
}

export const createInspectionAttachmentUploadSessionApi = (
  projectId: string,
  nodeId: number,
  files: DocumentUploadSessionFile[],
  options?: MutationHeaderOptions
): Promise<IResponse<UploadSessionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/attachments`,
    data: { files },
    headers: mutationHeaders(options)
  })
}

export const completeDocumentUploadSessionApi = (
  projectId: string,
  sessionId: string,
  completedFiles: Array<{ documentVersionId: string; fileSize?: number; hash?: string }>,
  options?: MutationHeaderOptions
): Promise<IResponse<UploadSessionCompletePayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/upload-session/${sessionId}/complete`,
    data: { completedFiles },
    headers: mutationHeaders(options)
  })
}

export const retryDocumentUploadApi = (
  projectId: string,
  documentId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    documentId: string
    documentVersionId: string
    uploadStatus: '上传中'
    queuedTask: Record<string, unknown>
  }>
> => {
  return request.post({
    url: `/api/projects/${projectId}/documents/${documentId}/retry-upload`,
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

export const bindInspectionDocumentsApi = (
  projectId: string,
  nodeId: number,
  bindings: Array<Pick<NodeFileBinding, 'documentId' | 'documentVersionId' | 'usage'>>,
  options?: MutationHeaderOptions
): Promise<IResponse<MockMutationResult>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/file-bindings`,
    data: { bindings },
    headers: mutationHeaders(options)
  })
}

export const submitInspectionDocumentBindingsApi = (
  projectId: string,
  nodeId: number,
  payload: { bindingIds: string[]; batchName?: string; submitterComment?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<SubmissionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/file-bindings/submit`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deleteProjectDocumentApi = (
  projectId: string,
  documentId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<MockMutationResult & { documentId: string; removed: Record<string, number> }>
> => {
  return request.delete({
    url: `/api/projects/${projectId}/documents/${documentId}`,
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
    bindingIds?: string[]
    documentIds?: string[]
    submissionType?: 'document' | 'project'
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

export const submitRectificationApi = (
  projectId: string,
  payload: { nodeId: number; bindingIds: string[]; comment: string; rectificationId?: string },
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
  payload: { reviewMode: 'formal' | 'gap_precheck'; auditInputMode?: 'ocr_llm' | 'pure_llm' },
  options?: MutationHeaderOptions
): Promise<IResponse<AiRecheckPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/inspection/nodes/${nodeId}/ai-recheck`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const getActiveReviewHumanInputTaskApi = (
  reviewRunId: string
): Promise<IResponse<ActiveReviewHumanInputTaskPayload>> => {
  return request.get({ url: `/api/review-runs/${reviewRunId}/human-input-tasks/active` })
}

export const submitReviewHumanInputResponseApi = (
  reviewRunId: string,
  taskId: string,
  payload: ReviewHumanInputResponsePayload,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    reviewRun: Record<string, unknown>
    commandId: string
    commandStatus?: string
    graphResult?: Record<string, unknown>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/review-runs/${reviewRunId}/human-input-tasks/${taskId}/responses`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const confirmNodeEvidenceLinkApi = (
  projectId: string,
  nodeId: number,
  evidenceLinkId: string,
  payload: { comment?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<NodeEvidenceDecisionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/nodes/${nodeId}/evidence-links/${evidenceLinkId}/confirm`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const rejectNodeEvidenceLinkApi = (
  projectId: string,
  nodeId: number,
  evidenceLinkId: string,
  payload: { comment?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<NodeEvidenceDecisionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/nodes/${nodeId}/evidence-links/${evidenceLinkId}/reject`,
    data: payload,
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
  payload: {
    // 省略时由后端按 AI 建议预填；映射不到的建议会置 requiresResultSelection，交人工选择。
    result?: ReviewOpinion['result']
    opinion: string
    reason: string
    evidenceLinkIds?: string[]
  },
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
  payload: { reason: string; bindingIds: string[]; evidenceLinkIds: string[] },
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

export const updateReportApi = (
  projectId: string,
  reportId: string,
  payload: {
    title?: string
    status?: ReportVersion['status']
    sections?: ReportSection[]
    remark?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<ReportUpdatePayload>> => {
  return request.patch({
    url: `/api/projects/${projectId}/reports/${reportId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const getArchivePackageApi = (
  projectId: string
): Promise<IResponse<ArchivePackagePayload>> => {
  return request.get({ url: `/api/projects/${projectId}/archive/package` })
}

export const getEvidencePackageApi = (
  projectId: string,
  params?: { nodeId?: number; reportId?: string }
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
  payload: Pick<NdtFilm, 'filmNo' | 'weldNo' | 'method'> &
    Partial<
      Pick<
        NdtFilm,
        | 'nodeId'
        | 'pipelineNo'
        | 'reportNo'
        | 'entrustNo'
        | 'filmPackageNo'
        | 'imageFileName'
        | 'testDate'
        | 'detectionRatio'
        | 'standardCode'
        | 'imageQualityIndicator'
        | 'sensitivity'
        | 'density'
        | 'geometricUnsharpness'
        | 'evaluationLevel'
        | 'defectCode'
        | 'defectLocation'
        | 'evaluatorName'
        | 'reviewerName'
      >
    >,
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
    keyword?: string
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
    keyword?: string
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
  payload: NdtReportUploadRequest,
  options?: MutationHeaderOptions
): Promise<IResponse<NdtReportUploadPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/reports/upload-session`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const completeNdtReportUploadSessionApi = (
  projectId: string,
  sessionId: string,
  completedFiles: Array<{ documentVersionId: string; fileSize?: number; hash?: string }>,
  options?: MutationHeaderOptions
): Promise<IResponse<UploadSessionCompletePayload & { reports?: NdtReport[] }>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/reports/upload-session/${sessionId}/complete`,
    data: { completedFiles },
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

export const replaceNdtAtomicMaterialBindingsApi = (
  projectId: string,
  documentId: string,
  nodeIds: number[],
  options?: MutationHeaderOptions
): Promise<IResponse<NdtAtomicMaterialBindingsPayload>> => {
  return request.put({
    url: `/api/projects/${projectId}/ndt/documents/${documentId}/bindings`,
    data: { nodeIds },
    headers: mutationHeaders(options)
  })
}

export const submitNdtAtomicMaterialApi = (
  projectId: string,
  payload: { documentId: string; bindingIds: string[] },
  options?: MutationHeaderOptions
): Promise<IResponse<NdtAtomicMaterialSubmissionPayload>> => {
  return request.post({
    url: `/api/projects/${projectId}/ndt/material-submissions`,
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
  silentBusinessError?: boolean
  silentHttpError?: boolean
}

type RequestHeaderOptions = {
  silentBusinessError?: boolean
}

const createIdempotencyKey = () => {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `aicheck-${random}`
}

const safeHeaderValue = (value: string, fallback: string) => {
  const safe = String(value || '')
    .replace(/[^\x20-\x7e]/g, '-')
    .replace(/[^A-Za-z0-9._~:/@-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 180)
  return safe || fallback
}

const safeContentTypeHeaderValue = (value: string | undefined) => {
  const contentType = String(value || '').trim()
  return /^[A-Za-z0-9!#$%&'*+.^_`|~-]+\/[A-Za-z0-9!#$%&'*+.^_`|~-]+(?:\s*;\s*[A-Za-z0-9!#$%&'*+.^_`|~-]+=[A-Za-z0-9!#$%&'*+.^_`|~-]+)*$/.test(
    contentType
  )
    ? contentType
    : 'application/octet-stream'
}

const mutationHeaders = (
  options?: MutationHeaderOptions,
  extraHeaders?: Record<string, string>
) => {
  const headers: Record<string, string> = { ...(extraHeaders || {}) }
  if (options?.etag) headers['If-Match'] = options.etag
  const fallbackIdempotencyKey = createIdempotencyKey()
  headers['Idempotency-Key'] = safeHeaderValue(
    options?.idempotencyKey || fallbackIdempotencyKey,
    fallbackIdempotencyKey
  )
  if (options?.silentBusinessError) headers['X-Silent-Business-Error'] = 'true'
  if (options?.silentHttpError) headers['X-Silent-Http-Error'] = 'true'
  return Object.keys(headers).length ? headers : undefined
}

const requestHeaders = (options?: RequestHeaderOptions) => {
  const headers: Record<string, string> = {}
  if (options?.silentBusinessError) headers['X-Silent-Business-Error'] = 'true'
  return Object.keys(headers).length ? headers : undefined
}

export const getKnowledgeOverviewApi = (): Promise<IResponse<KnowledgeOverviewPayload>> => {
  return request.get({ url: '/api/knowledge/overview' })
}

export const getKnowledgeNetworkApi = (params?: {
  businessPackId?: string
  includeRuntime?: boolean
}): Promise<IResponse<KnowledgeNetworkPayload>> => {
  return request.get({ url: '/api/knowledge/network', params })
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

export const importKnowledgeFilesApi = (
  payload: {
    files: File[]
    sourceId?: string
    sourceName?: string
    sourceType?: KnowledgeSource['sourceType']
    sourceVersion?: string
    sourceStatus?: KnowledgeSource['status']
    vectorStatus?: KnowledgeSource['vectorStatus']
    projectId?: string
    projectName?: string
    fileMetas?: Array<{
      fileName?: string
      relativePath?: string
      contextDescription?: string
    }>
  },
  options?: MutationHeaderOptions
): Promise<IResponse<KnowledgeFileImportPayload>> => {
  const formData = new FormData()
  if (payload.sourceId) formData.append('sourceId', payload.sourceId)
  if (payload.sourceName) formData.append('sourceName', payload.sourceName)
  if (payload.sourceType) formData.append('sourceType', payload.sourceType)
  if (payload.sourceVersion) formData.append('sourceVersion', payload.sourceVersion)
  if (payload.sourceStatus) formData.append('sourceStatus', payload.sourceStatus)
  if (payload.vectorStatus) formData.append('vectorStatus', payload.vectorStatus)
  if (payload.projectId) formData.append('projectId', payload.projectId)
  if (payload.projectName) formData.append('projectName', payload.projectName)
  payload.files.forEach((file, index) => {
    const meta = payload.fileMetas?.[index]
    const relativePath =
      meta?.relativePath ||
      (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
      file.name
    formData.append('files', file)
    formData.append('relativePaths', relativePath)
    formData.append('fileNames', meta?.fileName || file.name)
    formData.append('contextDescriptions', meta?.contextDescription || '')
  })
  return request.post({
    url: '/api/knowledge/files/import',
    data: formData,
    headers: mutationHeaders(options)
  })
}

export const importRulesStandardsApi = (
  payload?: {
    sourceId?: string
    sourceName?: string
    sourceVersion?: string
    sourceStatus?: KnowledgeSource['status']
    reset?: boolean
  },
  options?: MutationHeaderOptions
): Promise<IResponse<KnowledgeFileImportPayload>> => {
  return request.post({
    url: '/api/knowledge/standards/import-from-rules',
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const importBusinessRulesApi = (
  payload: {
    files: File[]
    importVersion?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<BusinessRuleImportPayload>> => {
  const formData = new FormData()
  if (payload.importVersion) formData.append('importVersion', payload.importVersion)
  payload.files.forEach((file) => {
    formData.append('files', file)
  })
  return request.post({
    url: '/api/business-rules/import',
    data: formData,
    headers: mutationHeaders(options)
  })
}

export const listKnowledgeProjectFilesApi = (params?: {
  keyword?: string
  projectId?: string
  nodeId?: number
  status?: string
  sourceType?: KnowledgeSource['sourceType']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<KnowledgeFile>>> => {
  return request.get({ url: '/api/knowledge/project-files', params })
}

export const getKnowledgeFileDetailApi = (
  fileId: string,
  options?: RequestHeaderOptions
): Promise<IResponse<KnowledgeFileDetailPayload>> => {
  return request.get({ url: `/api/knowledge/files/${fileId}`, headers: requestHeaders(options) })
}

export const updateKnowledgeFileApi = (
  fileId: string,
  payload: KnowledgeFileSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ file: KnowledgeFile; auditLogId: string; changed: unknown[] }>> => {
  return request.put({
    url: `/api/knowledge/files/${fileId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const replaceKnowledgeFileVersionApi = (
  fileId: string,
  payload: {
    file: File
    fileName?: string
    relativePath?: string
    contextDescription?: string
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    file: KnowledgeFile
    currentVersion: DocumentVersion
    task: KnowledgeTask
    dispatch?: Record<string, unknown>
    auditLogId: string
  }>
> => {
  const formData = new FormData()
  formData.append('files', payload.file)
  if (payload.fileName) formData.append('fileName', payload.fileName)
  if (payload.relativePath) formData.append('relativePath', payload.relativePath)
  if (payload.contextDescription) {
    formData.append('contextDescription', payload.contextDescription)
  }
  return request.post({
    url: `/api/knowledge/files/${fileId}/replace`,
    data: formData,
    headers: mutationHeaders(options)
  })
}

export const deleteKnowledgeFileApi = (
  fileId: string,
  payload?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    fileId: string
    source?: KnowledgeSource
    removed: Record<string, number>
    auditLogId: string
  }>
> => {
  return request.delete({
    url: `/api/knowledge/files/${fileId}`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const listKnowledgeFileChunksApi = (
  fileId: string,
  params?: { page?: number; pageSize?: number },
  options?: RequestHeaderOptions
): Promise<IResponse<PagePayload<KnowledgeChunk>>> => {
  return request.get({
    url: `/api/knowledge/files/${fileId}/chunks`,
    params,
    headers: requestHeaders(options)
  })
}

export const getKnowledgeFileVectorApi = (
  fileId: string,
  options?: RequestHeaderOptions
): Promise<IResponse<KnowledgeVectorSummary>> => {
  return request.get({
    url: `/api/knowledge/files/${fileId}/vectors`,
    headers: requestHeaders(options)
  })
}

export const listKnowledgeFileReasoningReferencesApi = (
  fileId: string,
  params?: { page?: number; pageSize?: number },
  options?: RequestHeaderOptions
): Promise<IResponse<PagePayload<KnowledgeReasoningReference>>> => {
  return request.get({
    url: `/api/knowledge/files/${fileId}/reasoning-references`,
    params,
    headers: requestHeaders(options)
  })
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
  payload?: { force?: boolean; includeOcr?: boolean },
  options?: MutationHeaderOptions
): Promise<IResponse<{ task: KnowledgeTask }>> => {
  return request.post({
    url: `/api/knowledge/files/${fileId}/reindex`,
    data: payload || {},
    headers: mutationHeaders(options)
  })
}

export const batchReindexKnowledgeApi = (
  payload: KnowledgeReindexPayload,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    taskIds: string[]
    dispatches?: Array<Record<string, unknown>>
    summary?: Record<string, unknown>
  }>
> => {
  return request.post({
    url: '/api/knowledge/reindex',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const previewKnowledgeReindexApi = (
  payload: Omit<KnowledgeReindexPayload, 'previewId'>
): Promise<IResponse<ImpactPreview<KnowledgeReindexImpact>>> => {
  return request.post({ url: '/api/knowledge/reindex-preview', data: payload })
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

export const createKnowledgeRuleVersionApi = (
  payload: KnowledgeRuleVersionSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ rule: KnowledgeRuleVersion; auditLogId: string }>> => {
  return request.post({
    url: '/api/rules/versions',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updateKnowledgeRuleVersionApi = (
  versionId: string,
  payload: KnowledgeRuleVersionSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ rule: KnowledgeRuleVersion; auditLogId: string }>> => {
  return request.put({
    url: `/api/rules/versions/${versionId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const forkKnowledgeRuleVersionApi = (
  versionId: string,
  payload: Partial<KnowledgeRuleVersionSavePayload> = {},
  options?: MutationHeaderOptions
): Promise<
  IResponse<{ rule: KnowledgeRuleVersion; source: KnowledgeRuleVersion; auditLogId: string }>
> => {
  return request.post({
    url: `/api/rules/versions/${versionId}/fork`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const getKnowledgeRuleVersionDiffApi = (
  versionId: string,
  params?: { targetVersionId?: string; targetVersion?: string }
): Promise<IResponse<KnowledgeRuleVersionDiffPayload>> => {
  return request.get({ url: `/api/rules/versions/${versionId}/diff`, params })
}

export const publishKnowledgeRuleVersionApi = (
  versionId: string,
  payload: { reason: string; effectiveAt?: string; previewId?: string },
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
  payload: { reason: string; targetVersion: string; targetVersionId?: string; previewId?: string },
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

export const previewKnowledgeRuleVersionOperationApi = (
  versionId: string,
  action: 'publish' | 'rollback',
  payload: {
    reason: string
    effectiveAt?: string
    targetVersion?: string
    targetVersionId?: string
  }
): Promise<IResponse<ImpactPreview<KnowledgeRuleOperationImpact>>> => {
  return request.post({
    url: `/api/rules/versions/${versionId}/${action}-preview`,
    data: payload
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

export const listPromptTemplatesApi = (params?: {
  keyword?: string
  status?: string
  businessPackId?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<PromptTemplate>>> => {
  return request.get({ url: '/api/admin/prompt-templates', params })
}

export const getPromptTemplateApi = (
  templateId: string
): Promise<IResponse<{ template: PromptTemplate }>> => {
  return request.get({ url: `/api/admin/prompt-templates/${templateId}` })
}

export const createPromptTemplateApi = (
  payload: PromptTemplateSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: PromptTemplate; auditLogId: string }>> => {
  return request.post({
    url: '/api/admin/prompt-templates',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updatePromptTemplateApi = (
  templateId: string,
  payload: Partial<PromptTemplateSavePayload>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: PromptTemplate; auditLogId: string }>> => {
  return request.put({
    url: `/api/admin/prompt-templates/${templateId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const publishPromptTemplateApi = (
  templateId: string,
  payload: { reason?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: PromptTemplate; auditLogId: string }>> => {
  return request.post({
    url: `/api/admin/prompt-templates/${templateId}/publish`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deletePromptTemplateApi = (
  templateId: string,
  options?: MutationHeaderOptions
): Promise<IResponse<{ deleted: boolean; templateId: string; auditLogId: string }>> => {
  return request.delete({
    url: `/api/admin/prompt-templates/${templateId}`,
    headers: mutationHeaders(options)
  })
}

export const listReportTemplatesApi = (params?: {
  keyword?: string
  status?: string
  businessPackId?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<ReportTemplate>>> => {
  return request.get({ url: '/api/admin/report-templates', params })
}

export const getReportTemplateApi = (
  templateId: string
): Promise<IResponse<{ template: ReportTemplate }>> => {
  return request.get({ url: `/api/admin/report-templates/${templateId}` })
}

export const createReportTemplateApi = (
  payload: ReportTemplateSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: ReportTemplate; auditLogId: string }>> => {
  return request.post({
    url: '/api/admin/report-templates',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updateReportTemplateApi = (
  templateId: string,
  payload: Partial<ReportTemplateSavePayload>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: ReportTemplate; auditLogId: string }>> => {
  return request.put({
    url: `/api/admin/report-templates/${templateId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const publishReportTemplateApi = (
  templateId: string,
  payload: { reason?: string } = {},
  options?: MutationHeaderOptions
): Promise<IResponse<{ template: ReportTemplate; auditLogId: string }>> => {
  return request.post({
    url: `/api/admin/report-templates/${templateId}/publish`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deleteReportTemplateApi = (
  templateId: string,
  options?: MutationHeaderOptions
): Promise<IResponse<{ deleted: boolean; templateId: string; auditLogId: string }>> => {
  return request.delete({
    url: `/api/admin/report-templates/${templateId}`,
    headers: mutationHeaders(options)
  })
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
  cursor?: string
}): Promise<IResponse<AuditLogPayload>> => {
  return request.get({ url: '/api/admin/audit-logs', params })
}

export const getAdminConfigOverviewApi = (): Promise<IResponse<AdminConfigOverviewPayload>> => {
  return request.get({ url: '/api/admin/config-overview' })
}

export const listAdminOrgUnitsApi = (params?: {
  keyword?: string
  type?: AdminOrgUnitType
  status?: AdminOrgUnit['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<AdminOrgUnit>>> => {
  return request.get({ url: '/api/admin/org-units', params })
}

export const createAdminOrgUnitApi = (
  payload: AdminOrgUnitSavePayload,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{ orgUnit: AdminOrgUnit; auditLogId: string; revision: number; etag: string }>
> => {
  return request.post({
    url: '/api/admin/org-units',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updateAdminOrgUnitApi = (
  orgId: string,
  payload: Partial<AdminOrgUnitSavePayload>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{ orgUnit: AdminOrgUnit; auditLogId: string; revision: number; etag: string }>
> => {
  return request.put({
    url: `/api/admin/org-units/${orgId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deleteAdminOrgUnitApi = (
  orgId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    deleted: boolean
    orgUnitId: string
    auditLogId: string
    revision: number
    etag: string
  }>
> => {
  return request.delete({
    url: `/api/admin/org-units/${orgId}`,
    headers: mutationHeaders(options)
  })
}

export const listAdminUsersApi = (params?: {
  keyword?: string
  role?: RoleCode
  orgId?: string
  status?: AdminUser['status']
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<AdminUser>>> => {
  return request.get({ url: '/api/admin/users', params })
}

export const createAdminUserApi = (
  payload: AdminUserSavePayload,
  options?: MutationHeaderOptions
): Promise<IResponse<{ user: AdminUser; auditLogId: string; revision: number; etag: string }>> => {
  return request.post({
    url: '/api/admin/users',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const updateAdminUserApi = (
  userId: string,
  payload: Partial<AdminUserSavePayload>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ user: AdminUser; auditLogId: string; revision: number; etag: string }>> => {
  return request.put({
    url: `/api/admin/users/${userId}`,
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const deleteAdminUserApi = (
  userId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    deleted: boolean
    userId: string
    user?: AdminUser
    auditLogId: string
    revision: number
    etag: string
  }>
> => {
  return request.delete({
    url: `/api/admin/users/${userId}`,
    headers: mutationHeaders(options)
  })
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

export const getFdeMetaApi = (): Promise<IResponse<FdeMetaPayload>> => {
  return request.get({ url: '/api/fde/meta' })
}

export const listFdeBlockersApi = (params?: {
  domain?: string
  severity?: string
  category?: string
  projectId?: string
  keyword?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<FdeBlockerPage>> => {
  return request.get({ url: '/api/fde/blockers', params })
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

export const getFdeProjectVectorFileDetailApi = (
  projectId: string,
  documentVersionId: string,
  params?: { page?: number; pageSize?: number }
): Promise<IResponse<FdeVectorFileDetailPayload>> => {
  return request.get({
    url: `/api/fde/projects/${projectId}/documents/${documentVersionId}/vector-detail`,
    params
  })
}

export const getFdeStandardsVectorizationApi = (params?: {
  keyword?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<FdeStandardsVectorizationPayload>> => {
  return request.get({ url: '/api/fde/standards/vectorization', params })
}

export const getFdeStandardVectorFileDetailApi = (
  fileId: string,
  params?: { page?: number; pageSize?: number }
): Promise<IResponse<FdeVectorFileDetailPayload>> => {
  return request.get({
    url: `/api/fde/standards/files/${encodeURIComponent(fileId)}/vector-detail`,
    params
  })
}

export const getFdeStandardVectorFilePagePreviewApi = (
  fileId: string,
  params?: { pageNo?: number }
): Promise<{ data: Blob }> => {
  return request.get({
    url: `/api/fde/standards/files/${encodeURIComponent(fileId)}/page-preview`,
    params,
    responseType: 'blob',
    headers: {
      'X-Silent-Http-Error': 'true',
      'X-Silent-Business-Error': 'true'
    }
  }) as unknown as Promise<{ data: Blob }>
}

export const createFdeVectorCorrectionApi = (
  data: {
    projectId?: string
    documentVersionId?: string
    knowledgeFileId?: string
    chunkId?: string
    correctionType?: string
    before?: unknown
    after?: unknown
    reason?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ correction: FdeVectorCorrectionPayload; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/vector-corrections',
    data,
    headers: mutationHeaders(options)
  })
}

export const approveFdeVectorCorrectionApi = (
  correctionId: string,
  data?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ correction: FdeVectorCorrectionPayload; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/vector-corrections/${correctionId}/approve`,
    data,
    headers: mutationHeaders(options)
  })
}

export const rejectFdeVectorCorrectionApi = (
  correctionId: string,
  data?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<IResponse<{ correction: FdeVectorCorrectionPayload; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/vector-corrections/${correctionId}/reject`,
    data,
    headers: mutationHeaders(options)
  })
}

export const applyFdeVectorCorrectionApi = (
  correctionId: string,
  data?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    correction: FdeVectorCorrectionPayload
    file: Record<string, unknown>
    task: Record<string, unknown>
    dispatch: Record<string, unknown>
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/vector-corrections/${correctionId}/apply`,
    data,
    headers: mutationHeaders(options)
  })
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

export const getFdeReviewRunAuditPackageApi = (
  reviewRunId: string
): Promise<IResponse<FdeReviewRunAuditPackagePayload>> => {
  return request.get({ url: `/api/fde/review-runs/${reviewRunId}/audit-package` })
}

export const getFdeRawVaultApi = (reviewRunId: string): Promise<IResponse<FdeRawVaultSummary>> => {
  return request.get({ url: `/api/fde/review-runs/${reviewRunId}/raw-vault` })
}

export const getFdeRawVaultPayloadApi = (eventId: string): Promise<{ data: Blob }> => {
  return request.get({
    url: `/api/fde/raw-vault/events/${eventId}/payload`,
    responseType: 'blob',
    headers: {
      'X-Silent-Http-Error': 'true',
      'X-Silent-Business-Error': 'true'
    }
  }) as unknown as Promise<{ data: Blob }>
}

export const verifyFdeRawVaultApi = (
  reviewRunId: string
): Promise<
  IResponse<{
    status: 'verified' | 'hash_mismatch'
    eventCount: number
    chainHead?: string
    findings: Array<Record<string, unknown>>
  }>
> => {
  return request.post({ url: `/api/fde/review-runs/${reviewRunId}/raw-vault/verify` })
}

export const exportFdeRawVaultApi = (reviewRunId: string): Promise<{ data: Blob }> => {
  return request.get({
    url: `/api/fde/review-runs/${reviewRunId}/raw-vault/export`,
    responseType: 'blob',
    headers: {
      'X-Silent-Http-Error': 'true',
      'X-Silent-Business-Error': 'true'
    }
  }) as unknown as Promise<{ data: Blob }>
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

export const createFdeReviewRunFeedbackApi = (
  reviewRunId: string,
  data: {
    feedbackType?: string
    comment?: string
    correctedOutput?: unknown
    rootCause?: string
    shouldEnterEvaluationSet?: boolean
  },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    feedback: FdeFeedback
    reviewRun: FdeReviewRun
    auditLogId: string
    businessImpactPolicy: string
  }>
> => {
  return request.post({
    url: `/api/fde/review-runs/${reviewRunId}/feedback`,
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
    reason?: string
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

export const getFdeBusinessPackValidationApi = (): Promise<
  IResponse<
    BusinessPackValidateAllPayload & {
      schemaVersion?: string
      readOnly?: boolean
      generatedAt?: string
    }
  >
> => {
  return request.get({ url: '/api/fde/business-packs/validation' })
}

export const getFdeBusinessPackDiffApi = (
  packId: string,
  params?: { compareTo?: string; tenantId?: string }
): Promise<IResponse<Record<string, unknown>>> => {
  return request.get({ url: `/api/fde/business-packs/${packId}/diff`, params })
}

export const installFdeBusinessPackApi = (
  packId: string,
  data: { tenantId?: string; dryRun?: boolean; reason?: string },
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

export const refreshFdeOcr100ActionBoardApi = (
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    board: NonNullable<FdeOcrQualityPayload['ocr100ActionBoard']>
    outputs: Record<string, string>
    auditLogId: string
  }>
> => {
  return request.post({
    url: '/api/fde/ocr-100/action-board/refresh',
    data: {},
    headers: mutationHeaders(options)
  })
}

export const getFdeOcr100HandoffArtifactApi = (artifactKey: string): Promise<any> => {
  return request.get({
    url: `/api/fde/ocr-100/action-board/handoff/${encodeURIComponent(artifactKey)}`,
    responseType: 'blob'
  })
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

export const createFdeOcrCapabilityTestUploadSessionApi = (
  data: {
    file?: { fileName: string; fileType?: string; contentType?: string; fileSize: number }
    files?: Array<{ fileName: string; fileType?: string; contentType?: string; fileSize: number }>
  },
  options?: MutationHeaderOptions
): Promise<IResponse<FdeOcrCapabilityUploadSessionPayload>> => {
  return request.post({
    url: '/api/fde/capability-tests/ocr/upload-session',
    data,
    headers: mutationHeaders(options)
  })
}

export const uploadFdeOcrCapabilityTestFileApi = (
  uploadSessionId: string,
  file: File,
  options?: MutationHeaderOptions
): Promise<IResponse<FdeOcrCapabilityUploadSessionPayload>> => {
  return request.post({
    url: `/api/fde/capability-tests/ocr/upload-session/${encodeURIComponent(uploadSessionId)}/file`,
    data: file,
    headers: mutationHeaders(options, { 'Content-Type': safeContentTypeHeaderValue(file.type) })
  })
}

export const createFdeOcrCapabilityTestRunApi = (
  data: {
    uploadSessionId: string
    profileId?: string
    documentType?: string
    businessPackId?: string
    maxPages?: number
    enableTables?: boolean
    enableSeals?: boolean
    enableFallback?: boolean
    disableRemediation?: boolean
    quickMode?: boolean
  },
  options?: MutationHeaderOptions
): Promise<IResponse<{ run: FdeOcrCapabilityTestRun; auditLogId: string }>> => {
  return request.post({
    url: '/api/fde/capability-tests/ocr/runs',
    data,
    headers: mutationHeaders(options)
  })
}

export const rerunFdeOcrCapabilityTestRunApi = (
  runId: string,
  data?: { reason?: string },
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    run: FdeOcrCapabilityTestRun
    alreadyRunning: boolean
    auditLogId?: string | null
  }>
> => {
  return request.post({
    url: `/api/fde/capability-tests/ocr/runs/${encodeURIComponent(runId)}/rerun`,
    data: data || {},
    headers: mutationHeaders(options)
  })
}

export const listFdeOcrCapabilityTestRunsApi = (params?: {
  pageNo?: number
  pageSize?: number
  status?: string
  profileId?: string
}): Promise<IResponse<PagePayload<FdeOcrCapabilityTestRun>>> => {
  return request.get({ url: '/api/fde/capability-tests/ocr/runs', params })
}

export const getFdeOcrCapabilityTestRunApi = (
  runId: string
): Promise<IResponse<FdeOcrCapabilityTestDetailPayload>> => {
  return request.get({ url: `/api/fde/capability-tests/ocr/runs/${runId}` })
}

export const getFdeOcrCapabilityTestPagePreviewApi = (
  runId: string,
  params?: { pageNo?: number }
): Promise<any> => {
  return request.get({
    url: `/api/fde/capability-tests/ocr/runs/${encodeURIComponent(runId)}/page-preview`,
    params,
    responseType: 'blob'
  })
}

export const convertFdeOcrCapabilityTestToAnnotationApi = (
  runId: string,
  data?: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    task: FdeOcrAnnotationTask
    readiness: FdeOcrAnnotationReadinessPayload
    auditLogId: string
  }>
> => {
  return request.post({
    url: `/api/fde/capability-tests/ocr/runs/${runId}/to-annotation`,
    data: data || {},
    headers: mutationHeaders(options)
  })
}

export const convertFdeOcrCapabilityTestToEvaluationCaseApi = (
  runId: string,
  data?: Record<string, unknown>,
  options?: MutationHeaderOptions
): Promise<IResponse<{ case: Record<string, unknown>; auditLogId: string }>> => {
  return request.post({
    url: `/api/fde/capability-tests/ocr/runs/${runId}/to-evaluation-case`,
    data: data || {},
    headers: mutationHeaders(options)
  })
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

export const deleteFdeOcrAnnotationTaskApi = (
  taskId: string,
  options?: MutationHeaderOptions
): Promise<
  IResponse<{
    deleted: boolean
    taskId: string
    task: FdeOcrAnnotationTask
    summary: FdeOcrAnnotationReadinessPayload['summary']
    nextActions: string[]
    page: PagePayload<FdeOcrAnnotationTask>
    auditLogId: string
  }>
> => {
  return request.delete({
    url: `/api/fde/ocr-annotation/tasks/${taskId}`,
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
    reason?: string
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

export const listAdminMaterialReviewPointsApi = (): Promise<
  IResponse<PagePayload<AdminMaterialReviewPoint>>
> => {
  return request.get({ url: '/api/admin/material-review-points', params: { pageSize: 100 } })
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

export const deleteAdminConfigItemApi = (
  payload: { target: AdminConfigTarget; id: string },
  options?: MutationHeaderOptions
): Promise<IResponse<AdminConfigDeleteResult>> => {
  return request.delete({
    url: `/api/admin/config-items/${payload.target}/${payload.id}`,
    headers: mutationHeaders(options)
  })
}

export const publishAdminConfigApi = (
  payload: {
    scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
    reason: string
    previewId?: string
  },
  options?: MutationHeaderOptions
): Promise<IResponse<AdminPublishConfigPayload>> => {
  return request.post({
    url: '/api/admin/config-overview/publish',
    data: payload,
    headers: mutationHeaders(options)
  })
}

export const previewAdminConfigPublishApi = (payload: {
  scope: 'all' | 'permission' | 'workflow' | 'node-template' | 'rule'
  reason: string
}): Promise<IResponse<ImpactPreview<AdminConfigPublishImpact>>> => {
  return request.post({ url: '/api/admin/config-overview/publish-preview', data: payload })
}

export const getRuntimeUiContextApi = (): Promise<IResponse<RuntimeUiContext>> => {
  return request.get({ url: '/api/runtime/ui-context' })
}

export const getOperationsOverviewApi = (params: {
  area: OperationArea
  projectId?: string
}): Promise<IResponse<OperationsOverview>> => {
  return request.get({ url: '/api/operations/overview', params })
}

export const listOperationTasksApi = (params?: {
  area?: OperationArea
  projectId?: string
  status?: string
  page?: number
  pageSize?: number
}): Promise<IResponse<PagePayload<OperationTask>>> => {
  return request.get({ url: '/api/operations/tasks', params })
}

export const searchApi = (params: {
  keyword: string
  projectId?: string
  type?: SearchResult['type']
  scope?: OperationArea
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
