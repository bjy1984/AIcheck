import assert from 'node:assert/strict'
import { validateOriginalBlob } from './originalBlob'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const url = '/api/projects/P/documents/D/original?versionId=OLD&disposition=inline'
const envelope = {
  code: 404,
  message: '所选版本的原文不可用',
  operationId: 'OP-1',
  serverTime: '2026-09-09',
  data: { reason: 'NOT_FOUND' }
}
const response = { data: new Blob([JSON.stringify(envelope)], { type: 'application/json' }) }
await assert.rejects(validateOriginalBlob(response, url), (error: unknown) => {
  assert.match(getAicheckErrorMessage(error, 'fallback'), /所选版本的原文不可用/)
  assert.equal((error as { response: { data: typeof envelope } }).response.data.operationId, 'OP-1')
  return true
})
// Files (including legitimate JSON documents) remain exactly the original blob.
for (const blob of [
  new Blob(['%PDF-1.7 file'], { type: 'application/pdf' }),
  new Blob([JSON.stringify({ code: 404, message: 'document content' })], {
    type: 'application/json'
  }),
  new Blob(['broken json'], { type: 'application/json' }),
  new Blob([JSON.stringify({ ...envelope, code: 0 })], { type: 'application/json' })
]) {
  const original = { data: blob }
  assert.equal(await validateOriginalBlob(original, url), original)
}
assert.equal(
  response.data.type,
  'application/json',
  'error handling does not mutate the received file'
)
