import assert from 'node:assert/strict'

import { documentPipelineStatus } from './documentPipelineStatus'

const cases = [
  [{ currentOcrStatus: '排队中' }, '排队中'],
  [{ currentOcrStatus: '识别中' }, 'OCR 中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '待切片' }, '待切片'],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片中' }, '切片中'],
  [
    { currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '待向量化' },
    '待向量化'
  ],
  [
    { currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化中' },
    '向量化中'
  ],
  [
    { currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '已向量化' },
    '已完成'
  ],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片失败' }, '失败可重试'],
  [
    { currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化失败' },
    '失败可重试'
  ]
] as const

for (const [file, expected] of cases) {
  assert.equal(documentPipelineStatus(file), expected)
}
