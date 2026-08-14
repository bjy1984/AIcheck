import type { EvidenceLink, ReviewOpinion } from '@/types/aicheck'

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
