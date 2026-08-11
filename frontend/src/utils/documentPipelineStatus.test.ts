import assert from 'node:assert/strict'

import { documentPipelineStatus, isDocumentUploadSuccessful } from './documentPipelineStatus'

const cases = [
  [{ currentOcrStatus: '排队中' }, '上传中'],
  [{ currentOcrStatus: '识别中' }, '上传中'],
  [{ currentOcrStatus: '抽取不完整', sliceStatus: '待切片' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片中' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化中' }, '上传中'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],
  [
    {
      currentOcrStatus: '已识别',
      sliceStatus: '已切片',
      vectorStatus: '已向量化',
      bodyUploaded: false
    },
    '失败重新上传'
  ],
  [{ currentOcrStatus: '人工修正', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],
  [{ currentOcrStatus: '抽取不完整', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],
  [{ currentOcrStatus: '已识别', sliceStatus: '切片失败' }, '失败重新上传'],
  [
    { currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '向量化失败' },
    '失败重新上传'
  ],
  [{ currentOcrStatus: '未知状态' }, '上传中'],
  [{}, '上传中']
] as const

for (const [file, expected] of cases) {
  assert.equal(documentPipelineStatus(file), expected)
  assert.equal(isDocumentUploadSuccessful(file), expected === '上传成功')
}
