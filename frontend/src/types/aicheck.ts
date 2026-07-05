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
  actions: ActionCode[]
}

export type NodeDocumentRequirement = {
  id: string
  nodeId: number
  name: string
  requiredType: '必传' | '条件必传' | '可选'
  note?: string
}

export type DocumentAsset = {
  id: string
  projectId: string
  fileName: string
  fileType: string
  materialCategory?: string | null
  sourceOrgName: string
  uploaderName: string
  currentVersionId: string
  fileStatus: '草稿' | '已上传' | '已撤回' | '已替换' | '已作废'
  currentOcrStatus: '待识别' | '未识别' | '排队中' | '识别中' | '已识别' | '识别失败' | '人工修正'
  sliceStatus?: '未切片' | '待切片' | '已切片' | '切片失败'
  vectorStatus?: '未向量化' | '待向量化' | '已向量化' | '向量化失败'
  chunkCount?: number
  vectorCount?: number
  embeddingModel?: string
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
  objectType: 'documentVersion' | 'extractedField' | 'knowledgeClause' | 'aiRun' | 'reviewOpinion'
  objectId: string
  fileName?: string
  pageNo?: number
  fieldName?: string
  quotedText?: string
  confidence?: number
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
  status: '推理中' | '完成' | '失败' | '已人工确认'
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

export type ReviewOpinion = {
  id: string
  projectId: string
  nodeId: number
  result: '满足要求' | '需补正' | '不适用'
  opinion: string
  evidenceLinkIds: string[]
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
  status: '草稿' | '复核中' | '待签发' | '已签发' | '已归档'
  scope: 'currentNode' | 'project'
  nodeIds: number[]
  generatedAt: string
  revision?: number
  etag?: string
  updatedAt?: string
  reviewerName?: string
  previewUrl?: string
  exportUrl?: string
  actions: ActionCode[]
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
  type: 'project' | 'node' | 'document' | 'report' | 'standard' | 'rule'
  id: string
  title: string
  description: string
  route: string
  highlights: string[]
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
  requirements: NodeDocumentRequirement[]
  bindings: NodeFileBinding[]
  projectFiles: DocumentAsset[]
  availableVersions: DocumentVersion[]
  extractedFields: ExtractedField[]
  reviewOpinions: ReviewOpinion[]
  rectifications: RectificationItem[]
  aiRuns: AiReviewRun[]
  actions: ActionCode[]
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
