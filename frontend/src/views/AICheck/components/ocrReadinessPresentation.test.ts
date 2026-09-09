import assert from 'node:assert/strict'
import { ocrReadinessAlert, ocrReadinessLabel } from './ocrReadinessPresentation'

assert.equal(ocrReadinessLabel('incomplete'), '部分完成')
assert.equal(ocrReadinessLabel('ready'), '已完成')
assert.equal(ocrReadinessAlert({ status: 'ready' }), undefined)
assert.equal(ocrReadinessAlert(undefined), undefined)
assert.ok(ocrReadinessAlert({ status: 'incomplete' }))
assert.equal(
  ocrReadinessAlert({
    status: 'incomplete',
    blockingReasons: [{ code: 'OCR_QUALITY_GATE_BLOCKED', message: '需要核对定位证据' }]
  })?.description,
  '需要核对定位证据'
)
assert.equal(
  ocrReadinessAlert({ status: 'incomplete', blockingReasons: [{ fieldName: '版次' }] })
    ?.description,
  '未识别到版次。'
)
assert.deepEqual(
  ocrReadinessAlert({
    status: 'incomplete',
    blockingReasons: [
      { fieldName: '版次' },
      { code: 'OCR_PAGE_COVERAGE_INCOMPLETE', message: '第 13–28 页还没完成辨识。' }
    ]
  }),
  { title: '还有页面没辨识完', description: '第 13–28 页还没完成辨识。' }
)
assert.equal(
  ocrReadinessAlert({ status: 'failed', blockingReasons: [{ message: '服务暂不可用' }] })
    ?.description,
  '服务暂不可用'
)
