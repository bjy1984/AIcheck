import assert from 'node:assert/strict'

import { canRetryDocumentUpload, canSubmitDocumentUpload } from './documentUploadActions'

const submitCases = [
  [true, '上传成功', true],
  [true, '上传中', false],
  [true, '失败重新上传', false],
  [false, '上传成功', false]
] as const

for (const [workflowEligible, uploadStatus, expected] of submitCases) {
  assert.equal(canSubmitDocumentUpload(workflowEligible, uploadStatus), expected)
}

assert.equal(canRetryDocumentUpload('失败重新上传'), true)
assert.equal(canRetryDocumentUpload('上传中'), false)
assert.equal(canRetryDocumentUpload('上传成功'), false)
