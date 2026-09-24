import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import type { ReviewBRun, ReviewObjectCandidate } from '@/types/ai-review-b'

/** 上次审查发现一张记录表列了多个对象（多条管线）时，给监检员挑的候选。 */
export const runObjectCandidates = (run: ReviewBRun | null | undefined): ReviewObjectCandidate[] =>
  (run?.objectCandidates || []).filter(
    (item) => item && typeof item.objectId === 'string' && item.objectId
  )

/** 这次运行只审了哪些对象（发起时冻结）。页面要说出来，否则看结果的人不知道另一条管线还没审。 */
export const runReviewedObjectIds = (run: ReviewBRun | null | undefined): string[] =>
  (run?.selectedObjectIds || []).filter((item) => typeof item === 'string' && item)

export const objectCandidateLabel = (candidate: ReviewObjectCandidate) =>
  candidate.pageNo ? `${candidate.objectId}（第 ${candidate.pageNo} 页）` : candidate.objectId

/**
 * 指定下次只审这个对象。审查对象必须配合明确的文件版本（后端同样要求），
 * 且与规则试跑的对象映射二选一——选了这里就清掉那边。
 */
export const selectionWithObject = (
  selection: ReviewDocumentSelection | null,
  objectId: string
): ReviewDocumentSelection => {
  if (!selection?.versions.length) throw new Error('请先选择本次审查的文件版本，再指定审查对象。')
  return { ...selection, conditionObjectMapping: undefined, selectedObjectIds: [objectId] }
}
