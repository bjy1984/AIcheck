import type { ReviewBProjectAnalysisResult, ReviewBWorkspace } from '@/types/ai-review-b'

// Only use the active run's findings when present. Never substitute an older successful run.
export const overviewResult = (
  workspace: Pick<ReviewBWorkspace, 'activeReviewRun' | 'projectAnalysisResults'>
): ReviewBProjectAnalysisResult | undefined => {
  const run = workspace.activeReviewRun
  if (run) {
    const id = run.reviewRunId || run.id || ''
    const matching = workspace.projectAnalysisResults.filter((item) => item.reviewRunId === id)
    if (Array.isArray(run.findingDrafts))
      return {
        reviewRunId: id,
        projectAnalysisRunId: matching[0]?.projectAnalysisRunId || '',
        reviewResult: matching.length === 1 ? matching[0].reviewResult : undefined,
        findingDrafts: run.findingDrafts,
        status: run.status,
        createdAt: run.createdAt
      }
    return matching.length === 1 ? matching[0] : undefined
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
