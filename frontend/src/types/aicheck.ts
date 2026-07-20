export type RoleCode = 'inspection' | 'contractor' | 'ndt' | 'owner' | 'admin' | 'fde'

export type ProjectStatus =
  | '草稿/立项中'
  | '资料提交中'
  | 'AI 预审中'
  | '监检审查中'
  | '退回补正中'
  | '报告生成/复核中'
  | '已归档'

export type NodeStatus =
  | '待提交'
  | '部分提交'
  | '已提交'
  | 'AI 预审中'
  | '待审查'
  | '待人工确认'
  | '需补正'
  | '补正中'
  | '复审中'
  | '已通过'
  | '报告生成/复核中'
  | '已归档'

export type ActionCode =
  | 'project:view'
  | 'file:view'
  | 'file:upload'
  | 'file:bind'
  | 'file:preview'
  | 'file:download'
  | 'file:withdraw'
  | 'submission:draft'
  | 'submission:submit'
  | 'submission:withdraw'
  | 'rectification:submit'
  | 'review:save'
  | 'review:return-correction'
  | 'ai:recheck'
  | 'ai:adopt'
  | 'ai:reject'
  | 'report:generate'
  | 'report:review'
  | 'report:export'
  | 'report:archive'
  | 'report:view'
  | 'archive:view'
  | 'archive:download'
  | 'project:authorize-member'
  | 'ndt:film-create'
  | 'ndt:record-import'
  | 'ndt:submit'
  | 'ndt:report-upload'
  | 'knowledge:view'
  | 'knowledge:manage'
  | 'knowledge:task-retry'
  | 'knowledge:reindex'
  | 'admin:config'
  | 'admin:export'
  | 'audit:view'
  | 'fde:dashboard:view'
  | 'fde:ai-run:view-masked'
  | 'fde:ai-run:replay'
  | 'fde:feedback:view'
  | 'fde:feedback:triage'
  | 'fde:evaluation:view'
  | 'fde:evaluation:manage'
  | 'fde:evaluation:run'
  | 'fde:business-pack:view'
  | 'fde:business-pack:validate'
  | 'fde:capability-bundle:manage'
  | 'fde:release:view'
  | 'fde:release:submit'
  | 'fde:release:shadow'
  | 'fde:release:canary'
  | 'fde:release:rollback'
  | 'fde:ocr-quality:view'
  | 'fde:incident:manage'
  | 'fde:config:draft'

export type Project = {
  id: string
  code: string
  name: string
  type: string
  region: string
  ownerOrgName: string
  contractorOrgName: string
  ndtOrgName: string
  inspectionOrgName: string
  businessPackId?: string
  businessPackVersion?: string
  domainType?: string
  businessPackSnapshotHash?: string
  status: ProjectStatus
  todoCount: number
  messageCount: number
  currentNodeId: number
  riskLevel?: '低' | '中' | '高'
  updatedAt: string
  revision?: number
  etag?: string
  actions: ActionCode[]
}

export type ProjectTreeNode = {
  id: string
  projectId: string
  nodeId: number
  code: string
  name: string
  groupName: string
  inspectionType: 'A' | 'B' | 'C' | 'C/B' | '需确认'
  status: NodeStatus
  fileCount: number
  requiredProgress: { done: number; total: number }
  requirementsSummary?: NodeRequirementsSummary
  actions: ActionCode[]
}

export type NodeDocumentRequirement = {
  id: string
  nodeId: number
  name: string
  requiredType: '必传' | '条件必传' | '可选'
  materialTypeCode?: string
  responsibleParty?: string
  applicability?: string
  note?: string
}

export type NodeRequirementMatch = NodeDocumentRequirement & {
  matchedLinkCount?: number
  matchedBindingCount: number
  matchedFileNames: string[]
  supportStatus?: string
  evidenceReviewStatus?: string
  confirmedLinkCount?: number
  pendingLinkCount?: number
  rejectedLinkCount?: number
  fulfilled: boolean
  bestConfidence?: number
  evidenceLinkIds?: string[]
  confirmedEvidenceLinkIds?: string[]
}

export type BusinessBlockingReason = {
  code?: string
  message?: string
  severity?: 'blocker' | 'warning' | string
  requirementId?: string
  requirementName?: string
  reportId?: string
  fieldName?: string
  actionKey?: string
  targetId?: string
  [key: string]: unknown
}

export type NodeRequirementsSummary = {
  requiredCount: number
  satisfiedCount: number
  missingCount: number
  progressPercent: number
  hasRequirementDetails: boolean
  requirements: NodeRequirementMatch[]
  missingRequirements: NodeRequirementMatch[]
}

export type DocumentAsset = {
  id: string
  projectId: string
  fileName: string
  fileType: string
  materialTypeCode?: string | null
  materialCategory?: string | null
  sourceOrgName: string
  uploaderName: string
  currentVersionId: string
  fileStatus: '草稿' | '已上传' | '已撤回' | '已替换' | '已作废'
  currentOcrStatus:
    | '待识别'
    | '未识别'
    | '排队中'
    | '识别中'
    | '已识别'
    | '抽取不完整'
    | '识别失败'
    | '人工修正'
  sliceStatus?: '未切片' | '待切片' | '已切片' | '切片失败'
  vectorStatus?: '未向量化' | '待向量化' | '已向量化' | '向量化失败'
  chunkCount?: number
  vectorCount?: number
  embeddingModel?: string
  ocrReadiness?: {
    schemaVersion: string
    status:
      | 'not_started'
      | 'queued'
      | 'processing'
      | 'ready'
      | 'incomplete'
      | 'inconsistent'
      | 'failed'
    artifactIntegrity: boolean
    sourceStatus?: string | null
    documentVersionId?: string | null
    parseResultId?: string | null
    fieldCount: number
    fragmentCount: number
    tableCount: number
    sealCount: number
    positionedEvidenceCount: number
    bboxCoverage: number
    blockingReasons: BusinessBlockingReason[]
    retryable: boolean
    finishedAt?: string | null
    providerReady?: boolean
    globalCapacityReady?: boolean
    cloudGrounded?: boolean
    outputTruncated?: boolean
    formalReadinessProfileAllowed?: boolean
    formalEvidenceReady?: boolean
    formalReadinessBlockingReasons?: BusinessBlockingReason[]
    providerMode?: string | null
    provider?: string | null
    model?: string | null
    costCny?: number
    providerWaitReason?: string | null
    lastHeartbeatAt?: string | null
  }
  bindings?: NodeFileBinding[]
  primaryBinding?: NodeFileBinding | null
  updatedAt: string
  actions: ActionCode[]
}

export type DocumentVersion = {
  id: string
  documentId: string
  versionNo: string
  hash: string
  fileSize: number
  uploaderName: string
  uploadTime: string
  isCurrent: boolean
}

export type NodeFileBinding = {
  id: string
  projectId: string
  nodeId: number
  requirementId?: string
  requirementName?: string
  documentId: string
  documentVersionId: string
  fileName: string
  versionNo: string
  usage: '原始提交' | '补正附件' | '整改说明' | '证明材料' | '监检资料' | '检测报告'
  sourceOrgName: string
  bindingStatus: '草稿挂载' | '已提交' | '需补正' | '已通过'
  boundAt: string
  actions: ActionCode[]
}

export type EvidenceLink = {
  id: string
  projectId?: string
  objectType?:
    | 'documentVersion'
    | 'extractedField'
    | 'knowledgeClause'
    | 'aiRun'
    | 'reviewOpinion'
    | 'nodeEvidenceLink'
  objectId?: string
  documentId?: string
  documentVersionId?: string
  fileName?: string
  pageNo?: number
  fieldName?: string
  quotedText?: string
  confidence?: number
  previewAvailable?: boolean
  previewUrl?: string
  sourceLocatorId?: string
  sourceRelativePath?: string
  standardRef?: string
  clauseNo?: string
  nodeId?: number
  reviewPointId?: string
  supportStatus?: string
  matchedEvidenceItems?: string[]
  manualStatus?: 'pending' | 'confirmed' | 'rejected' | string
  manualStatusLabel?: string
  manualComment?: string
  scoreReasons?: string[]
  evidenceCoverage?: number
}

export type EvidenceSelectionValidation = {
  schemaVersion?: string
  passed?: boolean
  acceptedEvidenceLinkIds?: string[]
  invalidEvidenceLinkIds?: string[]
  requiresEvidenceSelection?: boolean
  availableEvidenceLinkIds?: string[]
  confirmedNodeEvidenceCount?: number
  message?: string
  [key: string]: unknown
}

export type ReportEvidenceScope = {
  schemaVersion?: string
  source?: string
  nodeId?: number
  nodeIds?: number[]
  evidenceLinkIds?: string[]
  evidenceLinks?: EvidenceLink[]
  allowedEvidenceIds?: string[]
  confirmedCount?: number
  [key: string]: unknown
}

export type ReportEvidenceValidation = {
  schemaVersion?: string
  passed?: boolean
  evidenceCount?: number
  sourceValidation?: EvidenceSelectionValidation
  invalidEvidenceLinkIds?: string[]
  requiresEvidenceSelection?: boolean
  message?: string
  [key: string]: unknown
}

export type DispatchStatus = {
  ready?: boolean
  taskId?: string
  workflowId?: string
  reviewRunId?: string
  result?: unknown
  statusReason?: string
  [key: string]: unknown
}

export type ExtractedField = {
  id: string
  documentVersionId: string
  fieldName: string
  fieldValue: string
  pageNo?: number
  confidence: number
  reviewStatus: '未复核' | '已确认' | '已修正' | '低置信度'
  evidenceLinkId: string
}

export type AiReviewRun = {
  id: string
  projectId: string
  nodeId: number
  subject: string
  model: string
  promptVersion: string
  ruleVersion: string
  llmConversationId?: string
  promptAudit?: Record<string, unknown>
  llmMetadata?: Record<string, unknown>
  reasoningProcess?: string
  llmResultText?: string
  status: '推理中' | '待人工核验' | '完成' | '失败' | '已人工确认' | '已驳回' | '已取消'
  reviewMode?: 'formal' | 'gap_precheck'
  advisoryOnly?: boolean
  confidenceScale?: 'ratio'
  operationId?: string
  taskId?: string
  reviewRunId?: string
  previousNodeStatus?: string
  stateTransition?: {
    from?: string
    to?: string
    reason?: string
  }
  suggestion: {
    id: string
    result: '满足要求' | '需补正' | '不适用' | '需人工确认'
    opinionDraft: string
    confidence: number
    manualConfirmItems: string[]
  }
  evidenceLinks: EvidenceLink[]
  finishedAt?: string
}

export type NodeBusinessBasis = {
  ruleId: string
  ruleName: string
  ruleKey?: string
  ruleVersion?: string
  sourceDocument?: string
  sourceSequence?: number | string
  businessModule?: string
  inspectionCategory?: string
  inspectionItem?: string
  inspectionClass?: string
  reviewClass?: string
  criteria?: string
  checkMethod?: string
  witnessText?: string
  materialTypeCodes?: string[]
  toolIds?: string[]
  referencedStandards?: Array<{
    reference: string
    file?: string
    fileName?: string
    knowledgeFileId?: string
    sourceRelativePath?: string
    previewAvailable?: boolean
    previewUrl?: string
  }>
  aiExecution?: {
    schemaVersion?: string
    sourceFields?: Record<string, unknown>
    requiredEvidence?: string[]
    extractionTargets?: string[]
    verificationSteps?: string[]
    acceptanceCriteria?: string[]
    humanConfirmation?: string[]
    promptContext?: string
  }
}

export type ReviewOpinion = {
  id: string
  projectId: string
  nodeId: number
  result: '满足要求' | '需补正' | '不适用'
  opinion: string
  evidenceLinkIds: string[]
  readinessSnapshot?: NodeEvidenceReadiness
  evidenceValidation?: EvidenceSelectionValidation
  businessRuleVersion?: string
  requiresEvidenceSelection?: boolean
  reviewerName: string
  createdAt: string
}

export type RectificationItem = {
  id: string
  projectId: string
  nodeId: number
  status: '待反馈' | '已反馈' | '已关闭' | string
  comment: string
  createdAt: string
  bindingIds?: string[]
  feedbackAt?: string
  feedbackByName?: string
}

export type ReportVersion = {
  id: string
  projectId: string
  reportNo: string
  versionNo: string
  title: string
  status: '草稿' | '复核中' | '复核完成' | '待签发' | '已签发' | '已归档'
  scope: 'currentNode' | 'project'
  nodeIds: number[]
  generatedAt: string
  revision?: number
  etag?: string
  updatedAt?: string
  reviewerName?: string
  previewUrl?: string
  exportUrl?: string
  sourceReviewOpinionId?: string
  evidenceScope?: ReportEvidenceScope
  evidenceValidation?: ReportEvidenceValidation
  actions: ActionCode[]
}

export type NdtReportReadiness = {
  reportId?: string
  documentId?: string
  documentVersionId?: string
  ocrStatus?: DocumentAsset['currentOcrStatus'] | string | null
  fieldCount?: number
  bboxFieldCount?: number
  method?: NdtFilm['method'] | string | null
  passed?: boolean
  blockingReasons?: BusinessBlockingReason[]
  warnings?: BusinessBlockingReason[]
  [key: string]: unknown
}

export type NdtSubmissionReadiness = {
  schemaVersion?: string
  passed?: boolean
  reports?: NdtReportReadiness[]
  blockingReasons?: BusinessBlockingReason[]
  [key: string]: unknown
}

export type ArchiveItem = {
  id: string
  projectId?: string
  name: string
  type: 'document' | 'report' | 'evidence'
  nodeId?: number
  sourceOrgName?: string
  status?: string
  updatedAt: string
  downloadUrl?: string
}

export type ExportTask = {
  id: string
  projectId?: string
  reportId?: string
  reportRevision?: number
  nodeId?: number
  exportType: 'report' | 'archive-package' | 'evidence-package' | 'document' | 'config-package'
  status: '排队中' | '生成中' | '可下载' | '失败' | '已过期'
  progress: number
  fileName: string
  fileSize?: number
  downloadUrl?: string
  createdAt: string
  finishedAt?: string
  expiresAt?: string
  errorMessage?: string
  manifest?: Record<string, unknown>
  manifestHash?: string
}

export type NdtFilm = {
  id: string
  projectId: string
  nodeId?: number
  filmNo: string
  weldNo: string
  pipelineNo?: string
  reportNo?: string
  entrustNo?: string
  filmPackageNo?: string
  imageFileName?: string
  method: 'RT' | 'UT' | 'MT' | 'PT'
  testDate?: string
  detectionRatio?: string
  standardCode?: string
  imageQualityIndicator?: string
  sensitivity?: string
  density?: string
  geometricUnsharpness?: string
  evaluationLevel?: string
  defectCode?: string
  defectLocation?: string
  evaluatorName?: string
  reviewerName?: string
  status: '草稿' | '待提交' | '待审查' | '需补正' | '已通过'
  actions: ActionCode[]
}

export type NdtRecord = {
  id: string
  projectId: string
  nodeId: number
  recordNo: string
  filmId?: string
  reportId?: string
  weldNo: string
  pipelineNo?: string
  entrustNo?: string
  reportNo?: string
  techniqueNo?: string
  equipmentNo?: string
  personnelCertificateNo?: string
  detectionRatio?: string
  standardCode?: string
  method: NdtFilm['method']
  testDate: string
  evaluatorName: string
  reviewerName?: string
  result: '合格' | '不合格' | '待复核'
  evaluationLevel?: string
  signatureStatus?: string
  stampStatus?: string
  sampleStatus: '未抽查' | '已抽查' | '需复核'
  conclusion?: string
  importedAt: string
  actions: ActionCode[]
}

export type NdtReport = {
  id: string
  projectId: string
  reportNo: string
  method: NdtFilm['method']
  fileId: string
  relatedFilmIds: string[]
  entrustNo?: string
  detectionRatio?: string
  standardCode?: string
  evaluatorName?: string
  reviewerName?: string
  status: NdtFilm['status']
  conclusion?: string
  uploadedAt: string
  actions: ActionCode[]
}

export type NdtFeedback = {
  id: string
  projectId: string
  nodeId: number
  title: string
  description: string
  status: '待反馈' | '已反馈' | '已关闭'
  relatedReportIds: string[]
  relatedFilmIds: string[]
  createdAt: string
  deadline?: string
}

export type TodoItem = {
  id: string
  title: string
  projectId: string
  nodeId?: number
  targetType: 'node' | 'document' | 'submission' | 'rectification' | 'report' | 'knowledgeTask'
  targetId: string
  status: '待处理' | '处理中' | '已完成' | '已延期' | '已关闭'
  priority: '低' | '中' | '高'
  deadline?: string
  assigneeName?: string
  completedAt?: string
  deferredUntil?: string
  updatedAt?: string
  revision?: number
  etag?: string
  actions: ActionCode[]
}

export type MessageItem = {
  id: string
  title: string
  content: string
  projectId?: string
  targetType?: TodoItem['targetType']
  targetId?: string
  read: boolean
  createdAt: string
  readAt?: string
  updatedAt?: string
  revision?: number
  etag?: string
}

export type SearchResult = {
  type:
    | 'project'
    | 'node'
    | 'document'
    | 'report'
    | 'standard'
    | 'rule'
    | 'user'
    | 'organization'
    | 'audit_event'
    | 'knowledge_file'
    | 'knowledge_task'
    | 'review_run'
    | 'ocr_run'
    | 'incident'
  id: string
  title: string
  description: string
  route: string
  highlights: string[]
  status?: string
  updatedAt?: string
  breadcrumb?: string
}

export type OperationArea = 'admin' | 'knowledge' | 'fde' | 'workbench'

export type RuntimeUiContext = {
  environment: string
  strictProduction: boolean
  demoDataAllowed: boolean
  buildVersion: string
  release: {
    releaseId: string
    gitSha: string
    backendDigest?: string | null
    frontendAssetHash?: string | null
    rulesHash?: string | null
    businessPackHash?: string | null
    materialMappingHash?: string | null
    manifestHash?: string | null
  }
  serverTime: string
  support: {
    label: string
    email?: string | null
    phone?: string | null
    url?: string | null
  }
}

export type OperationsOverview = {
  area: OperationArea
  scope: {
    role: RoleCode
    projectId?: string | null
  }
  totals: Record<string, number>
  metrics: Array<{
    key: string
    label: string
    value: number
    route?: string
  }>
  attentionItems: Array<{
    id: string
    type: string
    severity: 'info' | 'warning' | 'danger' | string
    title: string
    summary: string
    route?: string
    updatedAt?: string
  }>
  dataAsOf: string
  generatedAt: string
}

export type OperationTask = {
  id: string
  area: OperationArea
  projectId?: string | null
  taskType: string
  status: string
  statusCode?:
    | 'queued'
    | 'running'
    | 'retrying'
    | 'waiting_human'
    | 'cancel_requested'
    | 'cancelled'
    | 'succeeded'
    | 'failed'
    | 'partial'
    | 'blocked'
    | 'unknown'
  displayStatus?: string
  progress: number
  operationId?: string | null
  targetId?: string | null
  targetLabel: string
  errorSummary?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  actions: Array<'retry' | 'cancel' | 'replay' | 'rerun' | string>
  route?: string | null
  parentTaskId?: string | null
  pipelineRunId?: string | null
  stage?: string | null
  stageLabel?: string | null
  queuePosition?: number | null
  attempt?: number
  elapsedSeconds?: number | null
  engineStatus?: Record<string, unknown>
  blockingReasons?: Array<{ code?: string; message?: string; [key: string]: unknown }>
  recommendedAction?: string | null
  providerMode?: string | null
  provider?: string | null
  model?: string | null
  providerWaitReason?: string | null
  providerCallCount?: number
  callCount?: number
  costCny?: number
  budgetUsed?: number
  pageProgress?: {
    completed?: number
    total?: number
    currentPage?: number | null
    status?: string
  }
  lastHeartbeatAt?: string | null
  retryFromPage?: number | null
}

export type ImpactPreview<TImpact extends Record<string, unknown> = Record<string, unknown>> = {
  previewId: string
  kind: string
  generatedAt: string
  expiresAt: string
  impact: TImpact
}

export type WorkbenchContextPayload = {
  project: Project
  role: RoleCode
  currentNodeId: number
  topbar: {
    todoCount: number
    messageCount: number
    statusText: string
    projectSwitcherEnabled: boolean
  }
  actions: ActionCode[]
}

export type WorkbenchSummaryPayload = {
  metrics: Array<{
    key: string
    label: string
    value: string | number
    tone?: 'blue' | 'green' | 'orange' | 'red' | 'gray'
  }>
  todos: TodoItem[]
  messages: MessageItem[]
  updatedAt: string
}

export type NodePackagePayload = {
  node: ProjectTreeNode
  businessBasis?: NodeBusinessBasis
  requirements: NodeDocumentRequirement[]
  evidenceReadiness?: NodeEvidenceReadiness
  nodeEvidenceLinks?: EvidenceLink[]
  bindings: NodeFileBinding[]
  projectFiles: DocumentAsset[]
  availableVersions: DocumentVersion[]
  extractedFields: ExtractedField[]
  reviewOpinions: ReviewOpinion[]
  rectifications: RectificationItem[]
  aiRuns: AiReviewRun[]
  actions: ActionCode[]
}

export type InspectionAuditItemKey =
  | 'submission'
  | 'ocr'
  | 'evidence'
  | 'ai_review'
  | 'human_review'
  | 'report'
  | 'archive'

export type InspectionAuditItemStatus =
  | 'not_started'
  | 'in_progress'
  | 'needs_attention'
  | 'failed'
  | 'completed'

export type InspectionAuditSourceRef = {
  type: string
  id: string
  status?: string | null
}

export type InspectionAuditIssue = {
  code: string
  message: string
}

export type InspectionAuditItem = {
  key: InspectionAuditItemKey
  label: string
  status: InspectionAuditItemStatus
  statusLabel: string
  metric: string
  summary: string
  issueCount: number
  issues: InspectionAuditIssue[]
  updatedAt?: string | null
  relationStatus?: 'linked' | 'unlinked_legacy'
  sourceRefs: InspectionAuditSourceRef[]
  availableActions: ActionCode[]
}

export type InspectionAuditOverviewNode = {
  node: ProjectTreeNode
  items: InspectionAuditItem[]
  latestActivityAt?: string | null
}

export type InspectionAuditOverviewPayload = {
  schemaVersion: 'InspectionAuditOverview@1.0.0' | string
  project: Project
  summary: Record<InspectionAuditItemStatus, number> & {
    nodeCount: number
  }
  items: InspectionAuditOverviewNode[]
  page: number
  pageSize: number
  total: number
  dataAsOf: string
}

export type InspectionAuditWorkspacePayload = {
  schemaVersion: 'InspectionAuditWorkspace@1.0.0' | string
  project: Project
  node: ProjectTreeNode
  items: InspectionAuditItem[]
  content: {
    submission: Record<string, unknown>
    ocr: Record<string, unknown>
    evidence: Record<string, unknown>
    aiReview: Record<string, unknown>
    humanReview: Record<string, unknown>
    report: Record<string, unknown>
    archive: Record<string, unknown>
  }
  dataAsOf: string
}

export type NodeEvidenceReadiness = {
  schemaVersion: string
  hasReviewPoints: boolean
  requiredCount: number
  satisfiedCount: number
  missingCount: number
  pendingCount?: number
  rejectedCount?: number
  progressPercent: number
  readyForAi: boolean
  readyForAiFormal?: boolean
  readyForGapPrecheck?: boolean
  availableReviewModes?: Array<'formal' | 'gap_precheck'>
  recommendedAction?: 'run_formal_review' | 'run_gap_precheck' | 'configure_review_points' | string
  blockingReasons?: BusinessBlockingReason[]
  evidenceReviewComplete?: boolean
  requirements: NodeRequirementMatch[]
  missingRequirements: NodeRequirementMatch[]
  nodeEvidenceLinks: EvidenceLink[]
  inputDocumentVersionIds: string[]
  supportingDocumentCount: number
}

export type MockMutationResult = {
  id: string
  objectType: string
  objectId: string
  nextStatus?: string
  changed: Array<{ field: string; before?: unknown; after: unknown }>
  todoDelta?: number
  messageDelta?: number
  auditLogId: string
  affectedIds?: string[]
}
