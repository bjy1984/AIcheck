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
  // 监检员已判定不属于本节点：人的结论优先，模型的原始分数不再提示。
  if (decision.humanRejectedNodeIds?.includes(nodeId)) return null
  const score = decision.nodeScores?.find((row) => row.nodeId === nodeId)
  if (!score || !Number.isFinite(score.confidence) || score.confidence < 0 || score.confidence > 1)
    return null
  // 「建议」以后端认可的 suggestedNodeIds 为准（还要过把握值门槛）；
  // 选了「是」但没被认可的，只说不确定，不给绿色建议。
  const choice =
    score.choice === 'yes' &&
    decision.suggestedNodeIds &&
    !decision.suggestedNodeIds.includes(nodeId)
      ? 'uncertain'
      : score.choice
  const label =
    choice === 'yes'
      ? 'Jev 建议用于本节点'
      : choice === 'no'
        ? 'Jev 认为不属于本节点'
        : 'Jev 归属不确定'
  const tone: 'success' | 'info' | 'warning' =
    choice === 'yes' ? 'success' : choice === 'no' ? 'info' : 'warning'
  return { label: `${label} · ${Math.round(score.confidence * 100)}%`, tone }
}
