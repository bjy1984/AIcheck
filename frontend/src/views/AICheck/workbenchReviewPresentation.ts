import type { AiReviewRun, InspectionAuditItem, NodePackagePayload } from '@/types/aicheck'

export const workbenchReviewSectionOrder = ['ai_review', 'human_review'] as const

export const inspectionReviewDirectoryItems = (items: InspectionAuditItem[]) => {
  const byKey = new Map(items.map((item) => [item.key, item]))
  return workbenchReviewSectionOrder
    .map((key) => byKey.get(key))
    .filter((item): item is InspectionAuditItem => Boolean(item))
}

type ProjectAnalysisView = NonNullable<NodePackagePayload['projectAnalysis']>

export type WorkbenchAiFinding = {
  id: string
  typeLabel: string
  severity: string
  severityLabel: string
  title: string
  description: string
  confidence?: number
  evidenceCount: number
  ruleCount: number
  evidenceRefs: Array<Record<string, unknown>>
  ruleRefs: Array<Record<string, unknown>>
}

export const workbenchFindingDisplay = (finding: WorkbenchAiFinding) => ({
  id: finding.id,
  title: finding.title,
  description: finding.description,
  evidenceCount: finding.evidenceCount,
  ruleCount: finding.ruleCount,
  evidenceRefs: finding.evidenceRefs,
  ruleRefs: finding.ruleRefs
})

export type WorkbenchCertificateVerification = {
  result: string
  certificateType: string
  period: { start?: string | null; end?: string | null; referenceDate?: string | null }
  certificates: Array<{
    label: string
    holder: string
    certificateNo: string
    validFrom: string
    validUntil: string
    scopes: string[]
    result: string
  }>
  warnings: string[]
}

/** 服务端 certificateVerification 块 → 展示模型；不是对象或没有证书条目时返回 undefined。 */
export const workbenchCertificateVerification = (
  raw: unknown
): WorkbenchCertificateVerification | undefined => {
  if (!raw || typeof raw !== 'object') return undefined
  const block = raw as Record<string, unknown>
  const period = (block.period && typeof block.period === 'object' ? block.period : {}) as Record<
    string,
    unknown
  >
  const certificates = Array.isArray(block.certificates) ? block.certificates : []
  const text = (value: unknown) => (value === null || value === undefined ? '' : String(value))
  return {
    result: text(block.result),
    certificateType: text(block.certificateType),
    period: {
      start: text(period.start) || null,
      end: text(period.end) || null,
      referenceDate: text(period.referenceDate) || null
    },
    certificates: certificates
      .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
      .map((item) => ({
        label: text(item.label),
        holder: text(item.holder),
        certificateNo: text(item.certificateNo),
        validFrom: text(item.validFrom),
        validUntil: text(item.validUntil),
        scopes: Array.isArray(item.scopes) ? item.scopes.map(text) : [],
        result: text(item.result)
      })),
    warnings: Array.isArray(block.warnings) ? block.warnings.map(text) : []
  }
}

export type WorkbenchAiPresentation = {
  runId: string
  activityAt: string
  sourceLabel: string
  statusLabel: string
  statusTone: 'blue' | 'green' | 'orange' | 'red' | 'gray'
  resultLabel: string
  summary: string
  meta: string
  findings: WorkbenchAiFinding[]
  certificateVerification?: WorkbenchCertificateVerification
  errorMessage: string
  canRetry: boolean
  running: boolean
}

export const inspectionReviewDirectoryItemsWithAiStatus = (
  items: InspectionAuditItem[],
  presentation: WorkbenchAiPresentation
) =>
  inspectionReviewDirectoryItems(items).map((item) => {
    if (item.key !== 'ai_review' || presentation.sourceLabel !== '全工程一键分析') {
      return item
    }
    const statusByTone: Record<
      WorkbenchAiPresentation['statusTone'],
      InspectionAuditItem['status']
    > = {
      blue: 'in_progress',
      green: 'completed',
      orange: 'needs_attention',
      red: 'failed',
      gray: 'not_started'
    }
    return {
      ...item,
      status: statusByTone[presentation.statusTone],
      statusLabel: presentation.statusLabel,
      metric: presentation.resultLabel,
      summary: presentation.errorMessage || presentation.summary,
      issueCount: presentation.statusTone === 'red' ? 1 : item.issueCount
    }
  })

export const buildWorkbenchHumanAiContext = (presentation: WorkbenchAiPresentation) => ({
  overall: presentation.summary,
  ruleConclusion: presentation.resultLabel,
  ruleDescription: presentation.summary,
  manualConfirmItems: presentation.findings
    .map((finding) => finding.title || finding.description)
    .filter(Boolean)
})

const RESULT_LABELS: Record<string, string> = {
  supported: '证据支持',
  partially_supported: '部分证据支持',
  insufficient_evidence: '证据不足',
  conflict: '证据冲突',
  mismatch: '不一致'
}

const SEVERITY_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重'
}

const runningPhases = new Set([
  'preparing_snapshot',
  'building_prompt',
  'queued',
  'model_running',
  'validating_output',
  'persisting_results'
])

export const PROJECT_ANALYSIS_PHASES = [
  'preparing_snapshot',
  'building_prompt',
  'queued',
  'model_running',
  'validating_output',
  'persisting_results',
  'waiting_human_review'
] as const

export const projectAnalysisExecutionStepStatus = (
  phase: string,
  targetIndex: number,
  failedFromPhase?: string
) => {
  if (phase === 'failed') {
    const failedIndex = PROJECT_ANALYSIS_PHASES.indexOf(
      failedFromPhase as (typeof PROJECT_ANALYSIS_PHASES)[number]
    )
    if (failedIndex < 0) return '异常'
    if (targetIndex < failedIndex) return '完成'
    if (targetIndex === failedIndex) return '异常'
    return '待执行'
  }
  const currentIndex = PROJECT_ANALYSIS_PHASES.indexOf(
    phase as (typeof PROJECT_ANALYSIS_PHASES)[number]
  )
  if (currentIndex > targetIndex) return '完成'
  if (currentIndex === targetIndex) return phase === 'waiting_human_review' ? '完成' : '执行中'
  return '待执行'
}

const findingView = (raw: Record<string, unknown>, index: number): WorkbenchAiFinding => {
  const severity = String(raw.severity || '')
  const evidenceRefs = Array.isArray(raw.evidenceRefs)
    ? (raw.evidenceRefs as Array<Record<string, unknown>>)
    : []
  const ruleRefs = Array.isArray(raw.ruleRefs)
    ? (raw.ruleRefs as Array<Record<string, unknown>>)
    : []
  return {
    id: String(raw.id || `finding-${index + 1}`),
    typeLabel: String(raw.findingType || '审查发现'),
    severity,
    severityLabel: SEVERITY_LABELS[severity] || severity,
    title: String(raw.title || ''),
    description: String(raw.description || ''),
    confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
    evidenceCount: evidenceRefs.length,
    ruleCount: ruleRefs.length,
    evidenceRefs,
    ruleRefs
  }
}

export const buildWorkbenchAiPresentation = (
  projectAnalysis?: ProjectAnalysisView | null
): WorkbenchAiPresentation => {
  if (!projectAnalysis) {
    return {
      runId: '',
      activityAt: '',
      sourceLabel: 'AI 审查',
      statusLabel: '尚未运行',
      statusTone: 'gray',
      resultLabel: '等待分析',
      summary: '当前节点尚未形成可展示的 AI 审查结果。',
      meta: '',
      findings: [],
      errorMessage: '',
      canRetry: false,
      running: false
    }
  }
  const { run, nodeReview } = projectAnalysis
  const phase = String(run.phase || run.status || '')
  const failed = phase === 'failed' || String(run.status || '') === 'failed'
  const running = !failed && runningPhases.has(phase)
  const findings = (nodeReview?.findingDrafts || []).map(findingView)
  const result = String(nodeReview?.reviewResult || '')
  const statusLabel = failed
    ? run.errorCode === 'PROJECT_ANALYSIS_RUN_STALLED'
      ? 'AI 执行已中断'
      : 'AI 结果生成失败'
    : running
      ? phase === 'validating_output'
        ? '正在校验 AI 结果'
        : 'AI 正在分析'
      : nodeReview
        ? 'AI 已完成，等待人工确认'
        : 'AI 已完成，当前节点暂无有效结果'
  const statusTone = failed ? 'red' : running ? 'blue' : nodeReview ? 'green' : 'orange'
  const summary = failed
    ? '本次 AI 分析未形成可供人工审查的结构化结果。'
    : running
      ? phase === 'validating_output'
        ? '模型调用已经完成，正在校验结果结构、节点覆盖和证据引用。'
        : 'AI 正在处理工程资料，完成后将在这里展示当前节点结果。'
      : nodeReview
        ? `当前节点形成 ${findings.length} 条审查发现，所有结果均需人工确认。`
        : '工程分析已结束，但当前节点没有通过校验的审查结果。'
  return {
    runId: String(run.projectAnalysisRunId || ''),
    activityAt: String(run.finishedAt || run.updatedAt || run.createdAt || ''),
    sourceLabel: '全工程一键分析',
    statusLabel,
    statusTone,
    resultLabel:
      RESULT_LABELS[result] || result || (failed ? '未产出结论' : running ? '分析中' : '等待结果'),
    summary,
    meta: [run.projectAnalysisRunId, run.finishedAt || run.updatedAt || run.createdAt]
      .filter(Boolean)
      .join(' · '),
    findings,
    certificateVerification: workbenchCertificateVerification(
      (nodeReview as Record<string, unknown> | undefined)?.certificateVerification
    ),
    errorMessage: failed
      ? String(run.errorMessage || run.errorCode || '模型结果未通过校验，请重新发起分析。')
      : '',
    canRetry: failed,
    running
  }
}

export const selectWorkbenchAiPresentation = ({
  projectAnalysis,
  projectAnalysisFinishedAt,
  nodeRun,
  nodeFindings,
  nodeOutputText
}: {
  projectAnalysis: WorkbenchAiPresentation
  projectAnalysisFinishedAt?: string
  nodeRun?: AiReviewRun
  nodeFindings: WorkbenchAiFinding[]
  nodeOutputText: string
}): WorkbenchAiPresentation => {
  const nodeActivityAt = String(
    nodeRun?.finishedAt || nodeRun?.updatedAt || nodeRun?.createdAt || ''
  )
  const projectFinishedAt = String(projectAnalysisFinishedAt || '')
  const hasProjectAnalysis = projectAnalysis.sourceLabel === '全工程一键分析'
  if (
    !nodeRun ||
    (hasProjectAnalysis &&
      Boolean(projectFinishedAt) &&
      (!nodeActivityAt || projectFinishedAt >= nodeActivityAt))
  ) {
    return projectAnalysis
  }
  const failed = nodeRun.status === '失败'
  const running = nodeRun.status === '推理中'
  const failureText = String(
    nodeRun.failure?.reason || nodeRun.failure?.detail || 'AI 复核执行失败。'
  )
  return {
    runId: String(nodeRun.id || ''),
    activityAt: nodeActivityAt,
    sourceLabel: '节点 AI 复核',
    statusLabel: failed ? 'AI 结果生成失败' : running ? 'AI 正在分析' : 'AI 已完成，等待人工确认',
    statusTone: failed ? 'red' : running ? 'blue' : 'green',
    resultLabel: failed ? '未产出结论' : String(nodeRun.suggestion?.result || '等待结果'),
    summary: failed
      ? failureText
      : (nodeFindings.length ? String(nodeRun.suggestion?.opinionDraft || '') : nodeOutputText) ||
        String(nodeRun.suggestion?.opinionDraft || '') ||
        '当前节点暂无结果说明。',
    meta: [nodeRun.model, nodeRun.finishedAt || nodeRun.id].filter(Boolean).join(' · '),
    findings: nodeFindings,
    certificateVerification: workbenchCertificateVerification(
      (nodeRun as unknown as Record<string, unknown>).certificateVerification
    ),
    errorMessage: failed ? failureText : '',
    canRetry: failed ? nodeRun.failure?.retryable !== false : false,
    running
  }
}

export const buildWorkbenchAiHistory = ({
  current,
  projectAnalysis,
  nodeRuns
}: {
  current: WorkbenchAiPresentation
  projectAnalysis: WorkbenchAiPresentation
  nodeRuns: AiReviewRun[]
}) => {
  const candidates = [
    ...(projectAnalysis.runId ? [projectAnalysis] : []),
    ...nodeRuns.map((nodeRun) =>
      selectWorkbenchAiPresentation({
        projectAnalysis: buildWorkbenchAiPresentation(null),
        nodeRun,
        nodeFindings: [],
        nodeOutputText: String(
          nodeRun.llmResultText || nodeRun.suggestion?.opinionDraft || '暂无结果说明。'
        )
      })
    )
  ]
  const unique = new Map<string, WorkbenchAiPresentation>()
  for (const item of candidates) {
    if (!item.runId || item.runId === current.runId) continue
    unique.set(item.runId, item)
  }
  return [...unique.values()].sort((left, right) =>
    String(right.activityAt).localeCompare(String(left.activityAt))
  )
}
