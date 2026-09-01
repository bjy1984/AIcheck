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
assert.equal(
  canSubmitNdtDocumentUpload('草稿', '上传成功', false),
  false,
  '只读项目中无损检测资料的单条和批量提交都必须禁用'
)
assert.equal(canSubmitNdtDocumentUpload('需补正', '上传成功'), true)
assert.equal(canSubmitNdtDocumentUpload('待审查', '上传成功'), false)
assert.equal(canSubmitNdtDocumentUpload('草稿', '上传中'), false)
assert.equal(canSubmitNdtDocumentUpload('草稿', '失败重新上传'), false)

assert.equal(getStatusTagType('上传成功'), 'success')
assert.equal(getStatusTagType('上传中'), 'warning')
assert.equal(getStatusTagType('失败重新上传'), 'danger')

// ── 识别失败 ≠ 上传失败 ────────────────────────────────────────────
//
// 2026-08-15 实操：文件上传成功（对象存储里字节可读、哈希已落库、挂载也成功），
// 只是 OCR 没识别出来，界面却写「失败重新上传」。
//
// 这句话两处不对：事实不对（上传成功了）、指路不对（重传同一份文件，
// OCR 照样识别不出来）。用户按提示重传，再看到同样的字——比不给提示更耗人。

import { documentPipelineStatus } from './documentPipelineStatus'

// 本体没落盘 → 真的该重传
assert.equal(documentPipelineStatus({ bodyUploaded: false }), '失败重新上传')

// 本体在、识别链路挂了 → 不是上传的问题
assert.equal(
  documentPipelineStatus({ currentOcrStatus: '识别失败', sliceStatus: '', vectorStatus: '' }),
  '识别失败'
)
// 切片失败不再算「识别失败」：2026-08-29 起项目资料不做切片/向量化，
// 那两步的历史状态与用户无关，报出来他也处理不了、还挡着提交。
assert.equal(
  documentPipelineStatus({ currentOcrStatus: '已识别', sliceStatus: '切片失败' }),
  '上传成功'
)

// 「重新上传」按钮只在真的上传失败时出现——识别失败点它没有意义
assert.equal(canRetryDocumentUpload('识别失败'), false)
assert.equal(canRetryDocumentUpload('失败重新上传'), true)

// 能否提交的口径不变：识别失败仍不能提交（这是业务判据，本次不动）
assert.equal(canSubmitDocumentUpload(true, '识别失败'), false)
assert.equal(canSubmitDocumentUpload(true, '上传成功'), true)

// 标签颜色仍是危险色
assert.equal(getStatusTagType('识别失败'), 'danger')

console.log('Document OCR-vs-upload failure distinction passed')
