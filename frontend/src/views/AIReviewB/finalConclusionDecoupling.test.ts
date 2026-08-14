import assert from 'node:assert/strict'
import { buildFinalConclusionPayload, canSubmitFinalConclusion } from './finalConclusion'

for (const runStatus of [undefined, 'queued', 'running', 'waiting_human_input', 'failed']) {
  assert.equal(canSubmitFinalConclusion({ canSubmitReviewOpinion: true }, runStatus), true)
}

assert.equal(
  canSubmitFinalConclusion({ canSubmitReviewOpinion: false }, 'waiting_human_review'),
  false
)

assert.deepEqual(
  buildFinalConclusionPayload('证据不足', '  证据尚未闭合  ', [
    { id: 'EV-CONFIRMED', manualStatus: 'confirmed' },
    { id: 'EV-PENDING', manualStatus: 'pending' }
  ]),
  {
    result: '证据不足',
    opinion: '证据尚未闭合',
    evidenceLinkIds: ['EV-CONFIRMED']
  }
)

console.log('Review B final conclusion decoupling contract passed')
