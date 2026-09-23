import assert from 'node:assert/strict'
import { jevRoutingForNode } from './jevRoutingPresentation'
import type { ReviewDocument } from '@/api/aicheck/reviewDocuments'

const document = {
  currentVersionId: 'V2',
  jevRoutingDecision: {
    status: 'completed',
    model: 'jev-1.13.0',
    documentVersionId: 'V2',
    nodeScores: [{ nodeId: 25, choice: 'yes', confidence: 0.73 }]
  }
} as ReviewDocument

assert.deepEqual(jevRoutingForNode(document, 25), {
  label: 'Jev 建议用于本节点 · 73%',
  tone: 'success'
})
assert.equal(jevRoutingForNode(document, 13), null)
assert.equal(
  jevRoutingForNode({ ...document, currentVersionId: 'V3' }, 25),
  null,
  '旧版本的归属建议不能提示给当前上传版本'
)
assert.equal(
  jevRoutingForNode(
    {
      ...document,
      jevRoutingDecision: {
        ...document.jevRoutingDecision!,
        status: 'unavailable'
      }
    },
    25
  ),
  null
)
