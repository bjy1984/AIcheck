import type { ReviewBProjectAnalysisResult, ReviewBWorkspace } from '@/types/ai-review-b'

// Only use the active run's findings when present. Never substitute an older successful run.
export const overviewResult = (
  workspace: Pick<ReviewBWorkspace, 'activeReviewRun' | 'projectAnalysisResults'>
): ReviewBProjectAnalysisResult | undefined => {
  const run = workspace.activeReviewRun
  if (run) {
    const id = run.reviewRunId || run.id || ''
    const matching = workspace.projectAnalysisResults.filter((item) => item.reviewRunId === id)
    if (Array.isArray(run.findingDrafts) && (run.findingDrafts.length || matching[0]?.reviewResult))
      return {
        reviewRunId: id,
        projectAnalysisRunId: matching[0]?.projectAnalysisRunId || '',
        reviewResult: matching.length === 1 ? matching[0].reviewResult : undefined,
        findingDrafts: run.findingDrafts,
        status: run.status,
        createdAt: run.createdAt
      }
    return matching.length === 1 && (matching[0].reviewResult || matching[0].findingDrafts?.length)
      ? matching[0]
      : undefined
  }
  return [...workspace.projectAnalysisResults].sort((a, b) =>
    String(b.finishedAt || b.createdAt || '').localeCompare(
      String(a.finishedAt || a.createdAt || '')
    )
  )[0]
}

export const needsAttention = (finding: Record<string, unknown>) => {
  // Only an explicit normal checklist verdict can leave the attention list.
  // Unknown results and contradictory grounding remain visible for manual review.
  if (
    finding.suggestedAction === 'request_correction' ||
    ['insufficient_evidence', 'conflict', 'unsupported'].includes(
      String(finding.groundingStatus || '')
    ) ||
    (Array.isArray(finding.unsupportedClaims) && finding.unsupportedClaims.length)
  )
    return true
  if (
    finding.groundingStatus !== 'grounded' ||
    !Array.isArray(finding.evidenceRefs) ||
    !finding.evidenceRefs.length
  )
    return true
  return !['符合', '不适用'].includes(String(finding.checklistVerdict || ''))
}

// Execution status is separate from a business verdict; empty findings are not a verdict.
export const overviewProgress = (status: unknown): string => {
  const value = String(status || '')
  if (value === 'queued') return '任务正在排队，还没有审查结果。开始执行后会自动更新。'
  if (['failed', 'failed_to_start'].includes(value))
    return '这次审查没能完成。已有内容会保留，请查看执行记录，处理原因后再重试。'
  if (['cancelled', 'canceled'].includes(value))
    return '这次审查已取消。已有内容会保留，需要继续时请重新发起。'
  if (value === 'waiting_human_input') return '审查正在等你处理人工待办，处理后才能继续。'
  if (['completed', 'succeeded', 'waiting_human_review'].includes(value))
    return '本次执行已结束，请核对已有分析和原文；没有列出问题不代表已经通过。'
  if (value) return '系统正在核对资料，结果还没出齐。已有内容供你先查看。'
  return '这个任务暂未提供执行状态，请查看执行记录。'
}
