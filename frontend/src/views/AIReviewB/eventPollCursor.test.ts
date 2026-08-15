/**
 * 轮询取事件要用游标，但要往回退一段。
 *
 * 原来每一轮都 after=0 取完整快照，理由是「合并会话事件与 ReviewRun 事件后
 * 会重排，用游标怕漏读」——担心是对的，代价是每 3 秒 204 KB：
 * 切一次节点的 9 秒里拉了 3 次、600 多 KB 纯背景流量。
 *
 * 重排只发生在最近一小段，退一个安全窗口即可两头兼顾。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

assert.ok(sfc.includes('const eventPollCursor'), '没有游标函数')
assert.ok(/EVENT_POLL_OVERLAP\s*=\s*(\d+)/.test(sfc), '没有重叠窗口')
const overlap = Number(/EVENT_POLL_OVERLAP\s*=\s*(\d+)/.exec(sfc)![1])
assert.ok(overlap >= 10, '重叠窗口太小，重排就会漏事件')

// 首次加载（reset）仍要全量，否则新会话拿不到历史
assert.ok(
  /listReviewBEventsApi\(sessionId, reset \? 0 : eventPollCursor\(\)\)/.test(sfc),
  'reset 时要全量，轮询时才用游标'
)
// 旁路轮询也要用游标，漏一处就等于没改
assert.ok(
  /listReviewBEventsApi\(session\.value\.id, eventPollCursor\(\)\)/.test(sfc),
  '发送期间的旁路轮询还在全量拉'
)
// 游标不能为负
assert.ok(/Math\.max\(0,/.test(sfc), '游标要夹在 0 以上')

console.log('Review B event poll cursor contract passed')
