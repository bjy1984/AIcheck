import type { EvidenceLink, ReviewOpinion } from '@/types/aicheck'

type ConclusionContext = {
  projectId: string
  nodeId: number
  generation: number
  etag?: string
}

// Returning to the same node after switching away still invalidates a pending confirmation.
export const isConclusionConfirmationCurrent = (
  captured: ConclusionContext,
  current: ConclusionContext
) =>
  captured.projectId === current.projectId &&
  captured.nodeId === current.nodeId &&
  captured.generation === current.generation &&
  captured.etag === current.etag

export const canSubmitFinalConclusion = (
  permissions: { canSubmitReviewOpinion?: boolean } | undefined,
  _reviewRunStatus?: string
) => permissions?.canSubmitReviewOpinion === true

export const buildFinalConclusionPayload = (
  result: ReviewOpinion['result'],
  opinion: string,
  selectedEvidence: Array<Pick<EvidenceLink, 'id' | 'manualStatus'>>
) => ({
  result,
  opinion: opinion.trim(),
  evidenceLinkIds: selectedEvidence
    .filter((item) => item.manualStatus === 'confirmed')
    .map((item) => item.id)
})
