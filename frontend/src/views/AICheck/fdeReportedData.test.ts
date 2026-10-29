import assert from 'node:assert/strict'
import {
  reportedCount,
  reportedPercent,
  reportedRatioGate,
  reportedBoolean,
  standardFileReadiness,
  standardLibraryIndexed
} from './fdeReportedData'

for (const missing of [undefined, null, '', ' ', false, true, NaN, Infinity, -1, {}, 'unknown']) {
  assert.equal(reportedCount(missing), '未提供')
  assert.equal(reportedPercent(missing), '未提供')
  // A missing error rate cannot satisfy the <= 3% release gate.
  assert.equal(reportedRatioGate(missing, 0.03, 'lte').passed, null)
}
assert.equal(reportedCount(0), '0')
assert.equal(reportedCount('12'), '12')
assert.equal(reportedCount(1.5), '未提供')
assert.equal(reportedPercent(0), '0%')
assert.equal(reportedRatioGate(0, 0.03, 'lte').passed, true)
assert.equal(reportedRatioGate(0, 0.9, 'gte').passed, false)
assert.equal(reportedRatioGate(2, 0.9, 'gte').passed, null)
assert.equal(reportedBoolean(undefined).label, '未提供')
assert.equal(reportedBoolean(false).tone, 'danger')
assert.equal(reportedBoolean(true).tone, 'success')

const unprocessed = standardFileReadiness({
  chunkCount: 0,
  vectorCount: 0,
  vectorGap: 0,
  noiseLikeWatermarkCount: 0,
  vectorStatus: '未向量化'
})
assert.equal(unprocessed.noiseLabel, '未检测')
assert.equal(unprocessed.vectorTone, 'warning')
const indexed = {
  chunkCount: 20,
  vectorCount: 20,
  vectorGap: 0,
  noiseLikeWatermarkCount: 0,
  vectorStatus: '已向量化'
}
assert.equal(standardFileReadiness(indexed).vectorTone, 'success')
assert.equal(standardFileReadiness(indexed).noiseLabel, '未发现水印')
assert.equal(
  standardFileReadiness({ ...indexed, vectorCount: 15, vectorGap: 5 }).vectorTone,
  'warning'
)
assert.equal(
  standardFileReadiness({ ...indexed, noiseLikeWatermarkCount: undefined }).noiseLabel,
  '未提供'
)

const emptyIndex = {
  fileCount: 1,
  vectorizedFileCount: 0,
  chunkCount: 0,
  vectorCount: 0,
  vectorGap: 0,
  issueFileCount: 0
}
assert.equal(
  standardLibraryIndexed(emptyIndex),
  false,
  'zero gaps do not prove indexing is complete'
)
const completeIndex = { ...emptyIndex, vectorizedFileCount: 1, chunkCount: 12, vectorCount: 12 }
assert.equal(standardLibraryIndexed(completeIndex), true)
assert.equal(standardLibraryIndexed({ ...completeIndex, vectorizedFileCount: undefined }), false)
assert.equal(standardLibraryIndexed({ ...completeIndex, vectorCount: 11 }), false)
assert.equal(standardLibraryIndexed({ ...completeIndex, issueFileCount: 1 }), false)
