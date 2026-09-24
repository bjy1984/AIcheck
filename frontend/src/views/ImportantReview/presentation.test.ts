import assert from 'node:assert/strict'
import { displayValue, executionStatus, nodeConclusion, parseStatus } from './presentation'
import type { ImportantRun } from '@/api/aicheck/importantReview'
import type { ReviewDocument } from '@/api/aicheck/reviewDocuments'
assert.equal(executionStatus('failed'), '执行失败')
assert.equal(displayValue('drawing_catalog'), '图纸目录')
assert.equal(executionStatus('failed_to_start'), '执行失败')
assert.equal(executionStatus('waiting_human_input'), '待补充信息')
assert.equal(executionStatus('unknown'), '状态待确认')
assert.equal(executionStatus('waiting_human_review'), '已完成')
assert.equal(
  nodeConclusion({ status: 'failed', atomicCheckOutcomes: [{ result: 'passed' }] } as ImportantRun),
  '—'
)
assert.equal(
  nodeConclusion({ status: 'completed', atomicCheckOutcomes: [] } as unknown as ImportantRun),
  '待人工复核'
)
assert.equal(
  nodeConclusion({
    status: 'completed',
    atomicCheckOutcomes: [{ result: 'passed' }]
  } as ImportantRun),
  '待人工复核'
)
assert.equal(
  nodeConclusion({
    status: 'completed',
    atomicCheckOutcomes: [{ result: 'evidence_insufficient' }]
  } as ImportantRun),
  '证据不足'
)
assert.equal(
  parseStatus({ currentOcrStatus: '已识别', bodyUploaded: false } as ReviewDocument),
  '上传未完成'
)
assert.equal(
  parseStatus({
    currentOcrStatus: '已识别',
    ocrReadiness: { status: 'incomplete' }
  } as ReviewDocument),
  '解析不完整'
)
