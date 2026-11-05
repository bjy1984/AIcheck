import assert from 'node:assert/strict'
import type { NodeAuditTask, NodeAuditTasksPayload } from '@/api/aicheck/nodeAuditTasks'
import {
  describeTask,
  formatDuration,
  groupTasks,
  queueBadge,
  settledSince,
  taskSection
} from './nodeAuditTaskPresentation'

const task = (nodeId: number, extra: Partial<NodeAuditTask>): NodeAuditTask => ({
  nodeId,
  nodeName: `节点${nodeId}`,
  state: 'done',
  stale: false,
  reviewMode: 'formal',
  advisoryOnly: false,
  confirmed: false,
  ...extra
})

const payload = (items: NodeAuditTask[]): NodeAuditTasksPayload => ({
  projectId: 'P-1',
  items,
  counts: {
    running: 0,
    queued: 0,
    needs_input: 0,
    failed: 0,
    done: 0,
    cancelled: 0,
    awaitingConfirmation: 0
  },
  active: items.filter((item) => item.state === 'running' || item.state === 'queued').length,
  settledTotal: 0,
  settledShown: 0,
  dataAsOf: '2026-11-05 10:00:00'
})

assert.equal(formatDuration(38), '38 秒')
assert.equal(formatDuration(6 * 60 + 5), '6 分钟')
assert.equal(formatDuration(72 * 60), '1 小时 12 分')
assert.equal(formatDuration(120 * 60), '2 小时')
assert.equal(formatDuration(null), '')

// 排队中说清楚前面还有几个、等了多久
assert.equal(
  describeTask(task(1, { state: 'queued', queueAhead: 2, waitSeconds: 720 })).line,
  '前面还有 2 个，已等 12 分钟'
)
assert.equal(describeTask(task(1, { state: 'queued', queueAhead: 0 })).line, '下一个就轮到')
assert.equal(describeTask(task(1, { state: 'queued' })).line, '等待执行')
assert.equal(
  describeTask(task(2, { state: 'running', elapsedSeconds: 400 })).line,
  'AI 复核进行中，已 6 分钟'
)

// 出了结果没确认 → 去人工结论；已确认、缺项预审不算要你处理
const unconfirmed = task(3, { result: { group: 'failed', notApplicable: false } })
assert.equal(taskSection(unconfirmed), 'attention')
assert.deepEqual(
  [describeTask(unconfirmed).badge, describeTask(unconfirmed).action],
  ['未通过', '去确认']
)
assert.equal(describeTask(unconfirmed).auditItem, 'human_review')
assert.equal(
  taskSection(task(4, { confirmed: true, result: { group: 'passed', notApplicable: false } })),
  'settled'
)
assert.equal(taskSection(task(5, { advisoryOnly: true })), 'settled')
assert.equal(taskSection(task(6, { state: 'failed' })), 'attention')
assert.equal(describeTask(task(6, { state: 'failed', errorMessage: '模型超时' })).line, '模型超时')
assert.equal(describeTask(task(6, { state: 'failed' })).auditItem, 'ai_review')

// 分段顺序固定，空段不出现
const listed = payload([
  task(1, { state: 'queued' }),
  task(2, { state: 'running' }),
  unconfirmed,
  task(4, { confirmed: true })
])
assert.deepEqual(
  groupTasks(listed).map((section) => [section.key, section.tasks.map((item) => item.nodeId)]),
  [
    ['active', [1, 2]],
    ['attention', [3]],
    ['settled', [4]]
  ]
)
assert.deepEqual(
  groupTasks(payload([task(4, { confirmed: true })])).map((s) => s.key),
  ['settled']
)

// 顶栏数字：有在跑的数在跑的，否则数要你处理的
assert.deepEqual(queueBadge(listed), { count: 2, tone: 'active' })
assert.deepEqual(queueBadge(payload([unconfirmed, task(4, { confirmed: true })])), {
  count: 1,
  tone: 'attention'
})
assert.equal(queueBadge(payload([task(4, { confirmed: true })])), null)

// 刚审完的：上次进行中、这次不在进行中
const before = payload([task(1, { state: 'running' }), task(2, { state: 'queued' })])
const after = payload([
  task(1, { result: { group: 'passed', notApplicable: false } }),
  task(2, { state: 'running' })
])
assert.deepEqual(
  settledSince(before, after).map((item) => item.nodeId),
  [1]
)
assert.deepEqual(settledSince(undefined, after), [])
