import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { isRunSettled } from './runPolling'

// 终态不再轮询
for (const status of [
  'completed',
  'failed',
  'failed_to_start',
  'cancelled',
  'waiting_human_review',
  'waiting_human_input'
]) {
  assert.equal(isRunSettled(status), true, `${status} 应当停止轮询`)
}

// 没有运行时也不该轮询——空节点占着一个 3 秒定时器毫无意义
assert.equal(isRunSettled(undefined), true)
assert.equal(isRunSettled(''), true)
assert.equal(isRunSettled('   '), true)

// 进行中的必须继续轮
for (const status of ['queued', 'running', 'retrieving', '未来才加的新状态']) {
  assert.equal(isRunSettled(status), false, `${status} 应当继续轮询`)
}

// 轮询本身要挂条件，而不是无条件每 3 秒打一次。
// 这个轮询不只是浪费：线上实测它会把正在派发的 ReviewRun 弄丢
// （工作台开着 5.4s 返回 missing，关掉 91s 正常完成）。
const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const timer = sfc.slice(sfc.indexOf('pollTimer = window.setInterval'))
const body = timer.slice(0, timer.indexOf('}, 3000)'))
assert.ok(body.includes('document.hidden'), '标签页在后台时不该继续轮询')
assert.ok(body.includes('isRunSettled'), '运行已落定就不该继续轮询')

console.log('Review B run polling contract passed')
