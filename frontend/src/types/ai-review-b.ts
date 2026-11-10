import type {
  EvidenceLink,
  NodeEvidenceReadiness,
  NodeFileBinding,
  Project,
  ProjectTreeNode
} from '@/types/aicheck'

export type ReviewBSession = {
  id: string
  projectId: string
  nodeId: number
  role: string
  status: 'active' | 'archived' | string
  currentTask: string
  activeReviewRunId?: string | null
  selectedEvidenceLinkIds: string[]
  selectedJudgmentIds?: string[]
  contextRevision: number
  revision: number
  etag: string
  createdBy?: string
  createdByName?: string
  createdAt: string
  updatedAt: string
  /** 「新对话」开出来的会话：上一本的编号与带过来的要点（见 backend review_session_memory） */
  previousSessionId?: string
  carryOver?: ReviewBCarryOver | null
  memory?: ReviewBSessionMemory
}

/** 上一段对话的要点：确定性摘取，只作线索，结论要按当前证据重新核实。 */
export type ReviewBCarryOver = {
  fromSessionId: string
  lastActivityAt?: string | null
  items: {
    askedAt?: string
    question: string
    /** 最重的一项：不符合 > 证据不足 > 需人工确认 > 符合 */
    verdict?: string | null
    /** 多项时的计数，例如「5 项：证据不足 3、符合 2」 */
    verdictSummary?: string | null
    answer?: string
  }[]
  unanswered: { askedAt?: string; question: string }[]
  createdAt?: string
}

/** AI 参考多少天的对话、这本会话是否已闲置到超出这个天数。 */
export type ReviewBSessionMemory = {
  historyDays: number
  lastMessageAt?: string | null
  historyExpired: boolean
}

export type ReviewAssistantPreferences = {
  text: string
  updatedAt?: string | null
  maxLength: number
}

export type ReviewApprovalCheck = {
  code: string
  result?: string
  usageId?: string
  approvedAt?: string
  startedAt?: string
  evidenceRefs?: Record<string, unknown>[]
}

/** 一张记录表列了多个对象时的候选（对象号、所在文件版本与页码） */
export type ReviewObjectCandidate = {
  objectId: string
  objectType?: string | null
  documentVersionId?: string | null
  pageNo?: number | null
}

export type ReviewBRun = {
  /** 记录表有多个对象、需要监检员指定时列出的候选 */
  objectCandidates?: ReviewObjectCandidate[]
  /** 本次只审的对象（发起时指定并冻结） */
  selectedObjectIds?: string[]
  approvalChecks?: ReviewApprovalCheck[]
  automationLimitations?: Array<{
    atomicCheckId: string
    code: string
    requiresHumanReview: boolean
  }>
  errorCode?: string | null
  errorMessage?: string | null
  id?: string
  reviewRunId?: string
  aiRunId?: string
  projectId?: string
  nodeId?: number
  subject?: string
  status?: string
  currentStep?: string
  ruleVersion?: string
  reviewMode?: string
  advisoryOnly?: boolean
  revision?: number
  etag?: string
  graphSummary?: {
    total?: number
    statusCounts?: Record<string, number>
  }
  findingDrafts?: Array<Record<string, unknown>>
  humanDecision?: Record<string, unknown>
  createdAt?: string
  updatedAt?: string
}

export type ReviewBBasisItem = {
  clauseId?: string
  sourceLocatorId?: string
  standardRef?: string
  standardCode?: string
  standardName?: string
  clauseNo?: string
  title?: string
  summary?: string
  /** 用途文案之外：若条款本身是公式/表格，检索命中会带这些字段 */
  blockType?: string
  latex?: string
  caption?: string
  tableColumns?: string[]
  tableRows?: Array<Record<string, string>>
  tableHeaderReliable?: boolean
  previewUrl?: string
  previewAvailable?: boolean
  knowledgeFileId?: string
  documentVersionId?: string
  fileName?: string
  sourceRelativePath?: string
  sourcePage?: number
  startPage?: number
  endPage?: number
  locatorPrecision?: string
  locators?: Array<{
    locatorId?: string
    clauseNo?: string
    sourcePage?: number
    startPage?: number
    endPage?: number
    precision?: string
  }>
  fixedBinding?: boolean
}

export type ReviewBReference = {
  kind: 'basis' | 'evidence'
  referenceId: string
  label: string
  aliases?: string[]
  basis?: ReviewBBasisItem
  evidence?: EvidenceLink
}

export type ReviewBWorkspace = {
  schemaVersion: string
  workspaceRevision: number
  project: Project
  node: ProjectTreeNode
  permissions: {
    canStartReview: boolean
    canSubmitHumanInput: boolean
    canSubmitHumanDecision: boolean
    canSubmitReviewOpinion: boolean
    canReturnCorrection: boolean
    canManageEvidence: boolean
  }
  evidenceReadiness: NodeEvidenceReadiness
  evidenceLinks: EvidenceLink[]
  selectedEvidence: EvidenceLink[]
  returnableBindings: Array<
    Pick<NodeFileBinding, 'id' | 'documentId' | 'fileName' | 'bindingStatus'> & {
      materialTypeName?: string | null
      materialCategory?: string | null
    }
  >
  businessBasis?: Record<string, unknown>
  basisSnapshot: ReviewBBasisItem[]
  session: ReviewBSession | null
  /** 没有可用会话时：上一本不能再用的会话编号。建会话的幂等键要拼上它，否则请求中间件会重放旧响应 */
  sessionGeneration?: string
  activeReviewRun: ReviewBRun | null
  projectAnalysisResults: ReviewBProjectAnalysisResult[]
  activeHumanInputTask: Record<string, unknown> | null
  latestHumanDecision: Record<string, unknown> | null
  contextSummary: {
    currentTask: string
    selectedEvidenceCount: number
    confirmedEvidenceCount: number
    processTodoCount: number
    finalReviewTodoCount: number
  }
  lastEventSequence: number
  updatedAt: string
}

export type ReviewBProjectAnalysisResult = {
  reviewRunId: string
  projectAnalysisRunId: string
  status?: string
  reviewResult?: string
  findingDrafts: Array<Record<string, unknown>>
  createdAt?: string
  finishedAt?: string
}

export type ReviewBContentBlock =
  | { type: 'text'; text: string; references?: ReviewBReference[] }
  /* 模型的推理过程。与正文分开成块，而不是拼进 text——
     推理模型（deepseek-v4-pro 等）的这一段动辄上千字，混进正文会把结论淹没。 */
  | { type: 'reasoning'; text: string }
  | { type: 'basis_card'; basisRefIds?: string[]; items?: ReviewBBasisItem[] }
  | {
      type: 'evidence_card'
      title?: string
      advisory?: boolean
      evidenceLinkIds?: string[]
      items?: EvidenceLink[]
    }
  | {
      type: 'judgment_summary'
      reviewRunId?: string
      status?: string
      currentStep?: string
      findingCount?: number
    }
  | { type: 'project_analysis_result'; result: ReviewBProjectAnalysisResult }
  | {
      type: 'action_suggestions'
      actions?: Array<{
        actionKey: string
        label: string
        targetRefs?: string[]
        requiresUserConfirmation?: boolean
      }>
    }
  | { type: string; [key: string]: unknown }

export type ReviewBTokenUsage = {
  inputTokens?: number
  outputTokens?: number
  totalTokens?: number
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export type ReviewBMessage = {
  id: string
  sessionId: string
  sequence: number
  role: 'user' | 'assistant' | 'system'
  messageType: string
  /** running：后台 Agent 执行中（占位消息）；completed/cancelled/failed：已终态。 */
  status?: 'running' | 'completed' | 'cancelled' | 'failed' | string
  contentBlocks: ReviewBContentBlock[]
  execution?: {
    executionId?: string
    mode: 'llm_agent' | 'deterministic_command' | 'deterministic_fallback' | 'cancelled' | string
    modelCalled: boolean
    agentEnabled: boolean
    toolCallCount: number
    turnCount: number
    provider?: string | null
    model?: string | null
    failureReason?: string | null
    usage?: ReviewBTokenUsage
  }
  reviewRunId?: string | null
  createdBy?: string
  createdAt: string
  /** 回答落定的时间（占位消息被回填时写入） */
  updatedAt?: string
}

export type ReviewBEvent = {
  schema: 'review-event/v1' | string
  eventId: string
  sequence: number
  eventType: string
  title?: string
  sessionId?: string
  reviewRunId?: string | null
  status?: string
  payload?: Record<string, unknown>
  payloadHash?: string
  occurredAt?: string
}

export type ReviewBAuditView = {
  reviewRun: ReviewBRun
  graph: {
    nodes?: Array<Record<string, unknown>>
    edges?: Array<Record<string, unknown>>
    timeline?: Array<Record<string, unknown>>
    artifactSummary?: Record<string, number>
    artifacts?: Record<string, unknown>
  }
  timeline: Array<Record<string, unknown>>
  basisSnapshot: ReviewBBasisItem[]
  evidenceSnapshot: EvidenceLink[]
  activeHumanInputTask: Record<string, unknown> | null
  humanDecision: Record<string, unknown> | null
}
