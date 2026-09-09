import assert from 'node:assert/strict'
import { needsFreshReview } from './inputRecovery'

assert.equal(needsFreshReview(null), false)
assert.equal(needsFreshReview({ status: 'failed', errorCode: 'TIMEOUT' }), false)
assert.equal(
  needsFreshReview({ status: 'failed', errorCode: 'REVIEW_INPUT_CHANGED_RECREATE_RUN' }),
  true
)
// An old code carried by an active or completed task must not offer recovery.
for (const status of ['running', 'queued', 'waiting_human_review', 'accepted_by_human']) {
  assert.equal(needsFreshReview({ status, errorCode: 'REVIEW_INPUT_CHANGED_RECREATE_RUN' }), false)
}
