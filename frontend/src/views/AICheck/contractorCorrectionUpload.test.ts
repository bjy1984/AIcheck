import assert from 'node:assert/strict'

import { buildCorrectionUploadBindingPayload } from './contractorCorrectionUpload'

assert.deepEqual(
  buildCorrectionUploadBindingPayload({ rectificationId: 'REC-16-001', nodeId: 16 }, [
    { documentId: 'DOC-1', documentVersionId: 'VER-1' },
    { documentId: 'DOC-2', documentVersionId: 'VER-2' }
  ]),
  {
    nodeId: 16,
    nodeIds: [16],
    bindings: [
      { documentId: 'DOC-1', documentVersionId: 'VER-1', usage: '补正附件' },
      { documentId: 'DOC-2', documentVersionId: 'VER-2', usage: '补正附件' }
    ]
  }
)

console.log('Contractor correction upload binding contract passed')
