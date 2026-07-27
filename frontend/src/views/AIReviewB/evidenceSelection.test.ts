import assert from 'node:assert/strict'

import { canSelectReviewEvidence } from './evidenceSelection'

assert.equal(canSelectReviewEvidence({ selectable: false }), false)
assert.equal(canSelectReviewEvidence({ selectable: true }), true)
assert.equal(canSelectReviewEvidence({}), true)
