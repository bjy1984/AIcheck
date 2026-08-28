import type { ReviewBMessage, ReviewBProjectAnalysisResult } from '@/types/ai-review-b'
import type { EvidenceLink } from '@/types/aicheck'

const projectAnalysisMessage = (
  result: ReviewBProjectAnalysisResult,
  sessionId: string,
  nodeId: number
): ReviewBMessage => ({
  id: `project-analysis:${result.projectAnalysisRunId}:${nodeId}`,
  sessionId: sessionId || `project-analysis-node-${nodeId}`,
  sequence: 0,
  role: 'assistant',
  messageType: 'project_analysis_result',
  status: 'completed',
  contentBlocks: [{ type: 'project_analysis_result', result }],
  reviewRunId: result.reviewRunId,
  createdAt: String(result.finishedAt || result.createdAt || '')
})

export const mergeProjectAnalysisResultsIntoConversation = (
  messages: ReviewBMessage[],
  results: ReviewBProjectAnalysisResult[],
  sessionId: string,
  nodeId: number
) => {
  const realMessages = [...messages].sort(
    (left, right) => Number(left.sequence || 0) - Number(right.sequence || 0)
  )
  const syntheticMessages = results
    .map((result) => projectAnalysisMessage(result, sessionId, nodeId))
    .sort((left, right) => String(left.createdAt).localeCompare(String(right.createdAt)))
  const merged: ReviewBMessage[] = []
  let syntheticIndex = 0
  for (const message of realMessages) {
    while (
      syntheticIndex < syntheticMessages.length &&
      String(syntheticMessages[syntheticIndex].createdAt) <= String(message.createdAt || '')
    ) {
      merged.push(syntheticMessages[syntheticIndex])
      syntheticIndex += 1
    }
    merged.push(message)
  }
  merged.push(...syntheticMessages.slice(syntheticIndex))
  return merged
}

export const projectAnalysisResultTagType = (reviewResult?: string) => {
  if (reviewResult === 'supported') return 'success'
  if (reviewResult === 'partially_supported') return 'warning'
  if (reviewResult === 'conflict' || reviewResult === 'mismatch') return 'danger'
  return 'info'
}

export const resolveProjectAnalysisEvidenceLink = (
  evidence: Record<string, unknown>,
  evidenceLinks: EvidenceLink[]
) => {
  const evidenceLinkId = String(evidence.evidenceLinkId || '')
  if (evidenceLinkId) {
    const exactIdMatches = evidenceLinks.filter((item) => item.id === evidenceLinkId)
    return exactIdMatches.length === 1 ? exactIdMatches[0] : undefined
  }

  const fileId = String(evidence.fileId || '')
  const documentVersionId = String(evidence.documentVersionId || '')
  const pageNo = Number(evidence.pageNo || 0)
  const quotedText = String(evidence.quotedText || '').trim()
  let candidates = evidenceLinks.filter((item) => {
    if (fileId && String(item.documentId || '') !== fileId) return false
    if (documentVersionId && String(item.documentVersionId || '') !== documentVersionId) {
      return false
    }
    if (pageNo && Number(item.pageNo || 0) !== pageNo) return false
    return true
  })
  if (quotedText) {
    const exactQuoteMatches = candidates.filter(
      (item) => String(item.quotedText || '').trim() === quotedText
    )
    if (exactQuoteMatches.length === 1) return exactQuoteMatches[0]
    candidates = candidates.filter((item) => {
      const candidateText = String(item.quotedText || '').trim()
      if (!candidateText) return false
      return candidateText.includes(quotedText) || quotedText.includes(candidateText)
    })
  }
  return candidates.length === 1 ? candidates[0] : undefined
}
