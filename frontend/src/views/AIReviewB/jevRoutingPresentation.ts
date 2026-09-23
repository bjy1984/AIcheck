import type { ReviewDocument } from '@/api/aicheck/reviewDocuments'

export const jevRoutingForNode = (document: ReviewDocument, nodeId: number) => {
  const decision = document.jevRoutingDecision
  if (
    !decision ||
    decision.documentVersionId !== document.currentVersionId ||
    !['completed', 'partial'].includes(decision.status) ||
    decision.model !== 'jev-1.13.0'
  )
    return null
  const score = decision.nodeScores?.find((row) => row.nodeId === nodeId)
  if (!score || !Number.isFinite(score.confidence) || score.confidence < 0 || score.confidence > 1)
    return null
  const label =
    score.choice === 'yes'
      ? 'Jev 建议用于本节点'
      : score.choice === 'no'
        ? 'Jev 认为不属于本节点'
        : 'Jev 归属不确定'
  const tone: 'success' | 'info' | 'warning' =
    score.choice === 'yes' ? 'success' : score.choice === 'no' ? 'info' : 'warning'
  return { label: `${label} · ${Math.round(score.confidence * 100)}%`, tone }
}
