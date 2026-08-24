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
}

export type ReviewBRun = {
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
  activeReviewRun: ReviewBRun | null
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
