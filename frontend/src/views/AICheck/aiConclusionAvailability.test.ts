import assert from 'node:assert/strict'
import { ref } from 'vue'
import { useNodeReviewDraft } from './useNodeReviewDraft'
import {
  buildWorkbenchAiPresentation,
  canShowWorkbenchAiConclusion
} from './workbenchReviewPresentation'
const empty = buildWorkbenchAiPresentation(null)
assert.equal(canShowWorkbenchAiConclusion(empty), false)
assert.equal(canShowWorkbenchAiConclusion({ ...empty, runId: '   ' }), false)
assert.equal(canShowWorkbenchAiConclusion({ ...empty, runId: 'R', running: true }), false)
assert.equal(
  canShowWorkbenchAiConclusion({ ...empty, runId: 'R', errorMessage: '请求失败' }),
  false
)
assert.equal(
  canShowWorkbenchAiConclusion({
    ...empty,
    runId: 'R',
    deterministicResult: 'evidence_insufficient'
  }),
  true
)
assert.equal(
  canShowWorkbenchAiConclusion({ ...empty, runId: 'R', deterministicResult: 'passed' }),
  true
)

const draft = useNodeReviewDraft(ref('P'), ref(1))
assert.equal(draft.reviewOpinion.value, '', '人工意见必须由用户填写，不能预填同意通过')
