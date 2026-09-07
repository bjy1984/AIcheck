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
  /** 以下为 P9 R1 契约字段；旧路径（自由文本解析）没有，按"通过守卫、无待核对项"处理。 */
  findingType?: string
  groundingStatus?: string
  /** 已翻译成监检能读的"待核对句"，原始 {claim, reason} 在 rawUnsupportedClaims。 */
  unsupportedClaims?: string[]
  rawUnsupportedClaims?: Array<{ claim: string; reason: string }>
  suggestedAction?: string
  actionLabel?: string
  modelTitle?: string
  modelDescription?: string
  unverified?: boolean
  policyPending?: boolean
  policyName?: string
}

export type WorkbenchEvidenceGroup = {
  fileId: string
  fileName: string
  pages: number[]
  quotes: string[]
}

/** 同一文件的多条引用合成一组：文件名只出现一次，引用原文列在下面，页码去重。 */
export const workbenchEvidenceGroups = (
  refs: Array<Record<string, unknown>>
): WorkbenchEvidenceGroup[] => {
  const groups = new Map<string, WorkbenchEvidenceGroup>()
  refs.forEach((ref) => {
    const fileId = String(ref.fileId || ref.documentId || '')
    const fileName = String(ref.fileName || fileId || '证据文件')
    const key = fileId || fileName
    const group = groups.get(key) || { fileId, fileName, pages: [], quotes: [] }
    const pageNo = Number(ref.pageNo)
    if (Number.isFinite(pageNo) && pageNo > 0 && !group.pages.includes(pageNo))
      group.pages.push(pageNo)
    const quote = String(ref.quotedText || '')
      .replace(/\s+/g, ' ')
      .trim()
    if (quote && !group.quotes.includes(quote)) group.quotes.push(quote)
    groups.set(key, group)
  })
  return [...groups.values()].map((group) => ({
    ...group,
    pages: [...group.pages].sort((a, b) => a - b)
  }))
}

const SEVERITY_TONES: Record<string, 'gray' | 'blue' | 'orange' | 'red'> = {
  low: 'gray',
  medium: 'blue',
  high: 'orange',
  critical: 'red'
}
const SEVERITY_TAGS: Record<string, string> = {
  low: '提示',
  medium: '一般',
  high: '重要',
  critical: '严重'
}

const CERT_RESULT_WORDS: Record<string, string> = {
  passed: '核验通过',
  failed: '核验未通过',
  evidence_insufficient: '证据不足',
  not_applicable: '不适用'
}

/**
 * 旧 run 里模型把字段名和枚举值原样写进了发现文案（"certificateVerification.result为passed"），
 * 提示词已改，但已落库的文案不会重跑；展示层按业务语言改写，监检人员不必认字段名。
 */
export const humanizeFindingText = (text: string) =>
  String(text || '')
    .replace(
      /certificateVerification(?:\.result)?\s*(?:为|=|:|：|是)\s*[「"']?([a-z_]+)[」"']?/gi,
      (_match, value: string) =>
        `服务端证照核验结论为「${CERT_RESULT_WORDS[value.toLowerCase()] || value}」`
    )
    .replace(/certificateVerification\.result/g, '证照核验结论')
    .replace(/certificateVerification/g, '证照核验')
    .replace(/\bevidence_insufficient\b/g, '证据不足')

export const workbenchFindingDisplay = (finding: WorkbenchAiFinding) => ({
  id: finding.id,
  title: humanizeFindingText(finding.title),
  description: humanizeFindingText(finding.description),
  evidenceCount: finding.evidenceCount,
  ruleCount: finding.ruleCount,
  evidenceRefs: finding.evidenceRefs,
  ruleRefs: finding.ruleRefs,
  severityTag: SEVERITY_TAGS[finding.severity] || finding.severityLabel || '',
  severityTone: SEVERITY_TONES[finding.severity] || 'gray',
  confidencePercent:
    typeof finding.confidence === 'number' ? Math.round(finding.confidence * 100) : undefined,
  evidenceGroups: workbenchEvidenceGroups(finding.evidenceRefs)
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
  /** 后端 suggestion.deterministicResult（passed/failed/evidence_insufficient/not_applicable）。 */
  deterministicResult?: string
  /** P8 H4：部分证据分片修复与升级后仍失败时的提示，例如"部分分片未完成 1/9"。 */
  partialCoverageLabel?: string
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
  const rawClaims = rawUnsupportedClaims(raw.unsupportedClaims)
  const suggestedAction = String(raw.suggestedAction || '')
  const findingType = String(raw.findingType || '')
  return {
    id: String(raw.id || `finding-${index + 1}`),
    typeLabel: FINDING_TYPE_LABELS[findingType] || findingType || '审查发现',
    severity,
    severityLabel: SEVERITY_LABELS[severity] || severity,
    title: String(raw.title || ''),
    description: String(raw.description || ''),
    confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
    evidenceCount: evidenceRefs.length,
    ruleCount: ruleRefs.length,
    evidenceRefs,
    ruleRefs,
    findingType,
    groundingStatus: String(raw.groundingStatus || ''),
    unsupportedClaims: rawClaims.map(describeUnsupportedClaim),
    rawUnsupportedClaims: rawClaims,
    suggestedAction,
    actionLabel: SUGGESTED_ACTION_LABELS[suggestedAction] || '',
    modelTitle: String(raw.modelTitle || ''),
    modelDescription: String(raw.modelDescription || ''),
    unverified: raw.unverified === true,
    policyPending: raw.policyPending === true,
    policyName: String(raw.policyName || raw.policyKey || '')
  }
}

/**
 * 节点级 AiRun 的发现视图：直接读后端落库的 findings 数组。
 * 只有数组为空时，调用方才退回到解析 llmResultText 的旧路径。
 */
export const nodeRunFindingViews = (
  run?: Pick<AiReviewRun, 'findings'> | null
): WorkbenchAiFinding[] =>
  (Array.isArray(run?.findings) ? run.findings : [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(findingView)

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
    deterministicResult:
      String((nodeReview as Record<string, unknown> | undefined)?.deterministicResult || '') ||
      undefined,
    errorMessage: failed
      ? String(run.errorMessage || run.errorCode || '模型结果未通过校验，请重新发起分析。')
      : '',
    canRetry: failed,
    running
  }
}

// ── P9 R1：结论卡与三组发现（契约见《优化计划-焊接节点》12.3，词表全文唯一） ──────────

const FINDING_TYPE_LABELS: Record<string, string> = {
  missing_evidence: '缺少证据',
  evidence_conflict: '证据冲突',
  qualification_mismatch: '资质不匹配',
  expired_certificate: '证书过期',
  scope_mismatch: '范围不覆盖',
  inconsistency: '前后不一致',
  ai_review_suggestion: 'AI 复核建议'
}

const SUGGESTED_ACTION_LABELS: Record<string, string> = {
  human_confirm: '人工确认',
  request_correction: '要求补资料'
}

const CLAIM_REASON_TEXT: Record<string, (claim: string) => string> = {
  not_present_in_supplied_evidence: (claim) => `「${claim}」在已提交资料中未找到`,
  positive_claim_without_specific_evidence_token: () => '肯定结论没有指向任何具体证据'
}

export const rawUnsupportedClaims = (value: unknown): Array<{ claim: string; reason: string }> =>
  (Array.isArray(value) ? value : [])
    .map((item) =>
      item && typeof item === 'object'
        ? {
            claim: String((item as Record<string, unknown>).claim || '').trim(),
            reason: String((item as Record<string, unknown>).reason || '').trim()
          }
        : { claim: String(item || '').trim(), reason: '' }
    )
    .filter((item) => item.claim)

/** unsupportedClaims 里的 {claim, reason} → 监检能读的一句"待核对"。 */
export const describeUnsupportedClaim = (item: { claim: string; reason: string }) => {
  const render = CLAIM_REASON_TEXT[item.reason]
  if (render) return render(item.claim)
  return item.claim === 'positive_business_conclusion'
    ? '肯定结论没有指向任何具体证据'
    : `「${item.claim}」待核对`
}

export type WorkbenchAiVerdict = '需处理' | '待确认' | '证据不足' | '未见问题'
export type WorkbenchAiAction = '发联络单' | '要求补资料' | '现场核对原件' | '平台核验' | '人工确认'
export type WorkbenchAiFindingGroupKey = 'needAction' | 'confirm' | 'insufficient'

export type WorkbenchAiConclusion = {
  verdict: WorkbenchAiVerdict
  tone: 'red' | 'orange' | 'gray' | 'green'
  headline: string
  counts: Record<WorkbenchAiFindingGroupKey, number>
  keyFacts: Array<{ text: string; location: string }>
  action: WorkbenchAiAction
  groups: Record<WorkbenchAiFindingGroupKey, WorkbenchAiFinding[]>
  /** 证据不足组展开后的去重待核对项；每项指回第一条带它的发现。 */
  insufficientClaims: Array<{ text: string; claim: string; findingId: string }>
  deterministicLabel: string
}

const DETERMINISTIC_LABELS: Record<string, string> = {
  passed: '确定性核验通过',
  failed: '确定性核验未通过',
  evidence_insufficient: '确定性核验证据不足',
  not_applicable: '规则不适用'
}

const clip = (text: string, max: number) => {
  const compact = String(text || '')
    .replace(/\s+/g, ' ')
    .trim()
  return compact.length > max ? `${compact.slice(0, max - 1)}…` : compact
}

const isInsufficient = (finding: WorkbenchAiFinding) =>
  finding.groundingStatus === 'insufficient_evidence' ||
  (finding.unsupportedClaims?.length ?? 0) > 0 ||
  finding.title.startsWith('证据不足，需人工确认')

/** 状态映射表 12.3：通过守卫且 critical/high → 需处理；其余通过守卫 → 待确认；降级 → 证据不足。 */
export const workbenchFindingGroup = (finding: WorkbenchAiFinding): WorkbenchAiFindingGroupKey => {
  if (isInsufficient(finding)) return 'insufficient'
  if (finding.severity === 'critical' || finding.severity === 'high') return 'needAction'
  return 'confirm'
}

const findingLocation = (finding: WorkbenchAiFinding) => {
  const group = workbenchEvidenceGroups(finding.evidenceRefs)[0]
  if (!group) return ''
  return group.pages.length ? `${group.fileName} 第 ${group.pages[0]} 页` : group.fileName
}

const SITE_CHECK_RE = /印章|盖章|签字|签名|原件|涂改/
const PLATFORM_CHECK_RE = /平台|公示|注册|持证|证书号|许可证/

const recommendedAction = (
  verdict: WorkbenchAiVerdict,
  groups: WorkbenchAiConclusion['groups'],
  deterministic: string
): WorkbenchAiAction => {
  if (verdict === '需处理') {
    const heads = groups.needAction
    if (heads.some((item) => item.suggestedAction === 'request_correction')) return '要求补资料'
    const text = heads.map((item) => `${item.typeLabel} ${item.title}`).join(' ')
    if (SITE_CHECK_RE.test(text)) return '现场核对原件'
    if (PLATFORM_CHECK_RE.test(text)) return '平台核验'
    return '发联络单'
  }
  if (verdict === '证据不足') {
    return deterministic === 'evidence_insufficient' || groups.insufficient.length
      ? '要求补资料'
      : '人工确认'
  }
  return '人工确认'
}

/**
 * 结论只由 12.3 的决策表推导，不由模型自由发挥；卡片上必须标"AI 建议，未经人工确认"。
 * 决策表按行第一条命中：需处理 → 待确认 → 证据不足 → 未见问题。
 */
export const buildWorkbenchAiConclusion = ({
  findings,
  deterministicResult
}: {
  findings: WorkbenchAiFinding[]
  deterministicResult?: string | null
}): WorkbenchAiConclusion => {
  const deterministic = String(deterministicResult || '').toLowerCase()
  const groups: WorkbenchAiConclusion['groups'] = { needAction: [], confirm: [], insufficient: [] }
  findings.forEach((finding) => groups[workbenchFindingGroup(finding)].push(finding))
  const seen = new Map<string, { text: string; claim: string; findingId: string }>()
  groups.insufficient.forEach((finding) => {
    ;(finding.rawUnsupportedClaims || []).forEach((raw) => {
      const key = raw.claim.replace(/\s+/g, '').toLowerCase()
      if (!seen.has(key)) {
        seen.set(key, {
          text: describeUnsupportedClaim(raw),
          claim: raw.claim,
          findingId: finding.id
        })
      }
    })
  })
  const insufficientClaims = [...seen.values()]
  const counts = {
    needAction: groups.needAction.length,
    confirm: groups.confirm.length,
    insufficient: groups.insufficient.length
  }
  let verdict: WorkbenchAiVerdict
  if (deterministic === 'failed' || counts.needAction) verdict = '需处理'
  else if (counts.confirm) verdict = '待确认'
  else if (counts.insufficient || deterministic === 'evidence_insufficient') verdict = '证据不足'
  else if (deterministic === 'passed' || deterministic === 'not_applicable') verdict = '未见问题'
  else verdict = '证据不足'

  const first = groups.needAction[0] || groups.confirm[0]
  let headline: string
  if (verdict === '需处理') {
    headline = first
      ? clip(first.title, 40)
      : clip(`${DETERMINISTIC_LABELS.failed}，请按规则结果处理`, 40)
  } else if (verdict === '待确认') {
    headline = clip(`${counts.confirm} 项待人工确认：${first?.title || ''}`, 40)
  } else if (verdict === '证据不足') {
    headline = counts.insufficient
      ? clip(`${counts.insufficient} 条发现证据不足，待核对 ${insufficientClaims.length} 项`, 40)
      : deterministic === 'evidence_insufficient'
        ? '确定性核验证据不足，请补充资料后复核'
        : 'AI 未形成任何发现，也无确定性核验结果'
  } else {
    headline =
      deterministic === 'not_applicable' ? '规则不适用，AI 未见问题' : '确定性核验通过，AI 未见问题'
  }
  const keyFacts = [...groups.needAction, ...groups.confirm].slice(0, 3).map((finding) => ({
    text: clip(finding.title || finding.description, 40),
    location: findingLocation(finding)
  }))
  return {
    verdict,
    tone:
      verdict === '需处理'
        ? 'red'
        : verdict === '待确认'
          ? 'orange'
          : verdict === '未见问题'
            ? 'green'
            : 'gray',
    headline,
    counts,
    keyFacts,
    action: recommendedAction(verdict, groups, deterministic),
    groups,
    insufficientClaims,
    deterministicLabel: DETERMINISTIC_LABELS[deterministic] || ''
  }
}

export const partialCoverageLabel = (
  run?: Pick<AiReviewRun, 'failedEvidenceShardIds' | 'evidenceCoverage'> | null
): string | undefined => {
  const failed = Array.isArray(run?.failedEvidenceShardIds) ? run.failedEvidenceShardIds.length : 0
  if (!failed) return undefined
  const expected = Number(run?.evidenceCoverage?.expectedShardCount || 0)
  return expected > 0 ? `部分分片未完成 ${failed}/${expected}` : `部分分片未完成 ${failed} 片`
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
    deterministicResult: String(nodeRun.suggestion?.deterministicResult || '') || undefined,
    partialCoverageLabel: partialCoverageLabel(nodeRun),
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
