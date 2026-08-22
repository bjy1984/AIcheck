import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const contracts = (await import('../../types/aicheck')) as Record<string, unknown>

assert.equal(
  typeof contracts.uploadCompletionPresentationFor,
  'function',
  '缺少上传完成状态的展示策略'
)
const uploadCompletionPresentationFor = contracts.uploadCompletionPresentationFor as (payload: {
  fileCount?: number
  processingStatus?: string
  completionWarnings?: Array<{ stage?: string; status?: string; errorCode?: string }>
  queuedTasks?: Array<{ status?: string; retryable?: boolean; errorCode?: string }>
}) => {
  tone: 'success' | 'warning'
  message: string
  resetSelection: boolean
}

const queued = uploadCompletionPresentationFor({
  fileCount: 2,
  processingStatus: '排队中',
  queuedTasks: [{ status: 'dispatched' }, { status: 'dispatched' }]
})
assert.deepEqual(queued, {
  tone: 'success',
  message: '已上传 2 个文件，OCR 和索引处理已进入队列',
  resetSelection: true
})

const retry = uploadCompletionPresentationFor({
  fileCount: 2,
  processingStatus: '需重试',
  queuedTasks: [{ status: 'dispatch_failed', retryable: true, errorCode: 'BROKER_UNAVAILABLE' }]
})
assert.equal(retry.tone, 'warning')
assert.equal(retry.resetSelection, true, '文件已保存后必须清空选择，不能诱导重复上传')
assert.equal(retry.message, '文件已保存，请联系管理员在 OCR/向量任务中心重试后续处理。')
assert.doesNotMatch(retry.message, /已进入队列|重传/)

const warning = uploadCompletionPresentationFor({
  fileCount: 1,
  processingStatus: '排队中',
  completionWarnings: [{ stage: 'dispatch', status: 'failed', errorCode: 'BROKER_UNAVAILABLE' }],
  queuedTasks: [{ status: 'dispatched' }]
})
assert.equal(warning.tone, 'warning')
assert.equal(warning.resetSelection, true, '后处理警告不应保留上传选择')
assert.equal(warning.message, '文件已保存，请联系管理员在 OCR/向量任务中心重试后续处理。')

const workbench = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')
assert.match(workbench, /uploadPostProcessingWarning/, '后处理警告必须独立于上传错误状态')
const warningStart = workbench.indexOf('v-if="uploadPostProcessingWarning"')
const warningBlock = workbench.slice(warningStart, workbench.indexOf('</ElAlert>', warningStart))
assert.ok(warningStart >= 0, '缺少独立的后处理警告')
assert.doesNotMatch(warningBlock, /handleOpenQuickAccess|重传|重试|任务中心/)
assert.doesNotMatch(
  workbench,
  /uploadDrawerError\.value\s*=\s*presentation\.message/,
  '派发失败不能进入重新上传错误通道'
)

console.log('upload completion presentation behavior contract passed')
