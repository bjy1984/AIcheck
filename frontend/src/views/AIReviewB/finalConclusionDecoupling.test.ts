import assert from 'node:assert/strict'
import {
  buildFinalConclusionPayload,
  canSubmitFinalConclusion,
  isConclusionConfirmationCurrent
} from './finalConclusion'

const captured = { projectId: 'P1', nodeId: 16, generation: 1, etag: 'v1' }
assert.equal(isConclusionConfirmationCurrent(captured, { ...captured }), true)
for (const change of [{ projectId: 'P2' }, { nodeId: 24 }, { generation: 3 }, { etag: 'v2' }]) {
  assert.equal(isConclusionConfirmationCurrent(captured, { ...captured, ...change }), false)
}

const evidence = [{ id: 'E1', manualStatus: 'confirmed' }]
const frozenPayload = buildFinalConclusionPayload('证据不足', '  原意见  ', evidence)
evidence[0].id = 'E2'
evidence[0].manualStatus = 'pending'
assert.deepEqual(frozenPayload.evidenceLinkIds, ['E1'])
assert.equal(frozenPayload.opinion, '原意见')

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
