export type ReviewEvidenceSelectionCandidate = {
  selectable?: boolean
}

export const canSelectReviewEvidence = (evidence: ReviewEvidenceSelectionCandidate) =>
  evidence.selectable !== false
