import assert from 'node:assert/strict'

import { resolveReviewWorkbenchContext } from './embeddedReviewWorkbench'

assert.deepEqual(
  resolveReviewWorkbenchContext({ embedded: false, projectId: '', nodeId: 0 }),
  { source: 'standalone' }
)
assert.deepEqual(
  resolveReviewWorkbenchContext({ embedded: true, projectId: '', nodeId: 0 }),
  { source: 'waiting' }
)
assert.deepEqual(
  resolveReviewWorkbenchContext({ embedded: true, projectId: 'P-001', nodeId: 0 }),
  { source: 'waiting' }
)
assert.deepEqual(
  resolveReviewWorkbenchContext({ embedded: true, projectId: 'P-001', nodeId: 2 }),
  { source: 'embedded', projectId: 'P-001', nodeId: 2 }
)
