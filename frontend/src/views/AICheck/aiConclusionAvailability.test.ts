import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
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

const workbench = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')
assert.match(workbench, /const reviewOpinion = ref\(''\)/)
assert.doesNotMatch(workbench, /ref\('资料、证据链与规则要求一致，同意通过。'\)/)
