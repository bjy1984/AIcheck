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
  /* 幂等：先剔除输入里已有的合成消息，再合并。
   *
   * 正常渲染路径是 computed（输入永远是原始会话消息），不会撞上；
   * 但任何把合并结果回写 messages 的代码——乐观更新、快照回放——
   * 都会让同一张分析卡片静默出现两次。实测：二次合并 2 条变 3 条。
   * 合成消息有稳定 id（project-analysis:runId:nodeId），按类型剔除即可。 */
  const realMessages = [...messages]
    .filter((message) => message.messageType !== 'project_analysis_result')
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
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
  const identity = (value: unknown) => (typeof value === 'string' ? value.trim() : '')
  const evidenceLinkId = identity(evidence.evidenceLinkId)
  const fileId = identity(evidence.fileId)
  const documentVersionId = identity(evidence.documentVersionId)
  if (!evidenceLinkId && !fileId && !documentVersionId) return undefined
  const rawPage = evidence.pageNo
  const pageNo = rawPage == null ? undefined : Number(rawPage)
  if (
    rawPage != null &&
    ((typeof rawPage !== 'number' && !(typeof rawPage === 'string' && /^\d+$/.test(rawPage))) ||
      !Number.isSafeInteger(pageNo) ||
      Number(pageNo) < 1)
  )
    return undefined
  // An ID is a selector, not permission to ignore a conflicting version or page.
  if (evidenceLinkId && evidenceLinks.filter((item) => item.id === evidenceLinkId).length !== 1)
    return undefined
  const quotedText = String(evidence.quotedText || '').trim()
  let candidates = evidenceLinks.filter((item) => {
    if (evidenceLinkId && item.id !== evidenceLinkId) return false
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
