import assert from 'node:assert/strict'

import { documentPipelineStatus, isDocumentUploadSuccessful } from './documentPipelineStatus'

/**
 * 契约：上传成功 = 本体落盘 + OCR 完成，**与切片/向量化无关**。
 *
 * 2026-08-29 架构调整：项目资料是被审查的对象、不是检索语料，后端不再对它们
 * 切片和向量化。判据里留着那两条会让它们**永远不满足**——线上实操就是这样：
 * 工作台显示「8 个文件，0 个上传成功」，全部卡在「上传中」且无法提交，
 * 而文件其实早已完整落盘、OCR 也识别完了。
 */
const cases = [
  // OCR 没走完 → 还在处理
  [{ currentOcrStatus: '排队中' }, '上传中'],
  [{ currentOcrStatus: '识别中' }, '上传中'],
  [{ currentOcrStatus: '未知状态' }, '上传中'],
  [{}, '上传中'],

  // OCR 完成即上传成功——切片/向量化是什么状态都不影响
  [{ currentOcrStatus: '已识别' }, '上传成功'],
  [{ currentOcrStatus: '人工修正' }, '上传成功'],
  [{ currentOcrStatus: '抽取不完整' }, '上传成功'],
  [{ currentOcrStatus: '已识别', sliceStatus: '未切片', vectorStatus: '未向量化' }, '上传成功'],
  [{ currentOcrStatus: '抽取不完整', sliceStatus: '待切片' }, '上传成功'],
  [{ currentOcrStatus: '已识别', sliceStatus: '已切片', vectorStatus: '已向量化' }, '上传成功'],

  // 历史遗留的切片/向量化失败不该再挡住用户：那两步已不再执行，
  // 报也没用（他处理不了，也不影响提交）。
  [{ currentOcrStatus: '已识别', sliceStatus: '切片失败' }, '上传成功'],
  [{ currentOcrStatus: '已识别', vectorStatus: '向量化失败' }, '上传成功'],

  // OCR 自己失败了：本体在，重传没用，要重新识别或人工修正
  [{ currentOcrStatus: '识别失败' }, '识别失败'],

  // 本体没落盘：只有这种情况重传才有意义
  [{ currentOcrStatus: '已识别', bodyUploaded: false }, '失败重新上传'],
  [
    {
      currentOcrStatus: '已识别',
      sliceStatus: '已切片',
      vectorStatus: '已向量化',
      bodyUploaded: false
    },
    '失败重新上传'
  ]
] as const

for (const [file, expected] of cases) {
  assert.equal(documentPipelineStatus(file), expected, JSON.stringify(file))
  assert.equal(isDocumentUploadSuccessful(file), expected === '上传成功', JSON.stringify(file))
}
