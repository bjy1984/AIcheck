import assert from 'node:assert/strict'

import {
  canRetryDocumentUpload,
  canSubmitDocumentUpload,
  canSubmitNdtDocumentUpload
} from './documentUploadActions'
import { getStatusTagType } from '@/views/AICheck/components/status'

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

assert.equal(canSubmitNdtDocumentUpload('草稿', '上传成功'), true)
assert.equal(canSubmitNdtDocumentUpload('需补正', '上传成功'), true)
assert.equal(canSubmitNdtDocumentUpload('待审查', '上传成功'), false)
assert.equal(canSubmitNdtDocumentUpload('草稿', '上传中'), false)
assert.equal(canSubmitNdtDocumentUpload('草稿', '失败重新上传'), false)

assert.equal(getStatusTagType('上传成功'), 'success')
assert.equal(getStatusTagType('上传中'), 'warning')
assert.equal(getStatusTagType('失败重新上传'), 'danger')
