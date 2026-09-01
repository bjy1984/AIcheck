import assert from 'node:assert/strict'

import * as uploadActions from './documentUploadActions'

const collectBatchSubmittableItems = (
  uploadActions as typeof uploadActions & {
    collectBatchSubmittableItems?: <T>(items: T[], canSubmit: (item: T) => boolean) => T[]
  }
).collectBatchSubmittableItems

assert.equal(
  typeof collectBatchSubmittableItems,
  'function',
  '批量提交必须提供与单条按钮共用判断函数的完整列表筛选能力'
)

const files = [
  { id: 'DOC-READY-1', canSubmit: true },
  { id: 'DOC-BLOCKED', canSubmit: false },
  { id: 'DOC-READY-2', canSubmit: true }
]

assert.deepEqual(
  collectBatchSubmittableItems!(files, (file) => file.canSubmit).map((file) => file.id),
  ['DOC-READY-1', 'DOC-READY-2'],
  '批量提交只能包含单条提交按钮可点击的文件，并保持完整列表顺序'
)

const runConfirmedBatchSubmission = (
  uploadActions as typeof uploadActions & {
    runConfirmedBatchSubmission?: <T>(options: {
      items: T[]
      confirm: (count: number) => Promise<boolean>
      submit: (item: T) => Promise<boolean>
    }) => Promise<{ confirmed: boolean; succeeded: T[]; failed: T[] }>
  }
).runConfirmedBatchSubmission

assert.equal(
  typeof runConfirmedBatchSubmission,
  'function',
  '批量提交必须先统一确认，再执行每份资料的提交'
)

const cancelledCalls: string[] = []
const cancelled = await runConfirmedBatchSubmission!({
  items: files.filter((file) => file.canSubmit),
  confirm: async (count) => {
    assert.equal(count, 2, '确认弹窗只需要展示可提交文件总数')
    return false
  },
  submit: async (file) => {
    cancelledCalls.push(file.id)
    return true
  }
})
assert.deepEqual(cancelledCalls, [], '用户取消确认后不能提交任何文件')
assert.deepEqual(cancelled, { confirmed: false, succeeded: [], failed: [] })

const submittedCalls: string[] = []
const completed = await runConfirmedBatchSubmission!({
  items: files.filter((file) => file.canSubmit),
  confirm: async () => true,
  submit: async (file) => {
    submittedCalls.push(file.id)
    return file.id === 'DOC-READY-1'
  }
})
assert.deepEqual(submittedCalls, ['DOC-READY-1', 'DOC-READY-2'])
assert.deepEqual(
  {
    confirmed: completed.confirmed,
    succeeded: completed.succeeded.map((file) => file.id),
    failed: completed.failed.map((file) => file.id)
  },
  {
    confirmed: true,
    succeeded: ['DOC-READY-1'],
    failed: ['DOC-READY-2']
  },
  '部分失败时要保留成功结果并准确汇总失败项'
)

const reportBatchResultThenRefresh = (
  uploadActions as typeof uploadActions & {
    reportBatchResultThenRefresh?: <T>(options: {
      result: { confirmed: boolean; succeeded: T[]; failed: T[] }
      report: (result: { confirmed: boolean; succeeded: T[]; failed: T[] }) => void
      refresh: () => Promise<void>
    }) => Promise<boolean>
  }
).reportBatchResultThenRefresh

assert.equal(
  typeof reportBatchResultThenRefresh,
  'function',
  '提交结果提示不能依赖后续刷新是否成功'
)

const completionEvents: string[] = []
const refreshed = await reportBatchResultThenRefresh!({
  result: completed,
  report: (result) => completionEvents.push(`reported:${result.succeeded.length}`),
  refresh: async () => {
    completionEvents.push('refresh-started')
    throw new Error('network unavailable')
  }
})
assert.equal(refreshed, false)
assert.deepEqual(
  completionEvents,
  ['reported:1', 'refresh-started'],
  '即使刷新失败，也必须先报告服务端已完成的批量提交结果'
)

let releaseFirstSubmission!: () => void
const firstSubmissionGate = new Promise<void>((resolve) => {
  releaseFirstSubmission = resolve
})
const sequentialCalls: string[] = []
const sequentialRun = runConfirmedBatchSubmission!({
  items: ['DOC-FIRST', 'DOC-SECOND'],
  confirm: async () => true,
  submit: async (documentId) => {
    sequentialCalls.push(documentId)
    if (documentId === 'DOC-FIRST') await firstSubmissionGate
    return true
  }
})
await Promise.resolve()
await Promise.resolve()
assert.deepEqual(sequentialCalls, ['DOC-FIRST'], '前一份提交完成前不能并发启动下一份')
releaseFirstSubmission()
await sequentialRun
assert.deepEqual(sequentialCalls, ['DOC-FIRST', 'DOC-SECOND'])

const thrownFailure = await runConfirmedBatchSubmission!({
  items: ['DOC-THROWS', 'DOC-CONTINUES'],
  confirm: async () => true,
  submit: async (documentId) => {
    if (documentId === 'DOC-THROWS') throw new Error('request failed')
    return true
  }
})
assert.deepEqual(thrownFailure, {
  confirmed: true,
  succeeded: ['DOC-CONTINUES'],
  failed: ['DOC-THROWS']
})
