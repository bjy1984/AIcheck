import { computed, reactive, type Ref } from 'vue'
import type { ReviewOpinion } from '@/types/aicheck'

type ReviewDraft = {
  // 空串＝还没选。不预选「满足要求」：受阻的节点一打开就带着一个不允许保存的结论，既冲突又容易误点。
  result: ReviewOpinion['result'] | ''
  opinion: string
  correctionReason: string
  evidenceIds: string[]
  requiresEvidence: boolean
}

/** Keep unfinished reviews in their project/node, including the selected evidence. */
export const useNodeReviewDraft = (projectId: Ref<string>, nodeId: Ref<number>) => {
  const drafts = reactive<Record<string, ReviewDraft>>({})
  const current = () => {
    const key = JSON.stringify([projectId.value, nodeId.value])
    return (drafts[key] ||= {
      result: '',
      opinion: '',
      correctionReason: '',
      evidenceIds: [],
      requiresEvidence: false
    })
  }
  const field = <K extends keyof ReviewDraft>(name: K) =>
    computed({
      get: () => current()[name],
      set: (value: ReviewDraft[K]) => {
        current()[name] = value
      }
    })
  return {
    reviewResult: field('result'),
    reviewOpinion: field('opinion'),
    correctionReason: field('correctionReason'),
    selectedReviewEvidenceIds: field('evidenceIds'),
    draftRequiresEvidenceSelection: field('requiresEvidence')
  }
}
