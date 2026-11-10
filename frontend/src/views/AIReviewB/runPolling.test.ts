import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { isRunSettled, shouldRefreshLiveState } from './runPolling'

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
assert.ok(body.includes('shouldRefreshLiveState'), '运行已落定就不该继续轮询')
// 2026-11-10：原条件里的 executionStarted 发完一问就一直是 true，
// 于是问过一句之后页面开着就每 3 秒刷一次全套，和后台 Agent 抢同一个 API 进程。
assert.ok(!body.includes('executionStarted'), '问过一句不等于还在执行，别拿它当轮询条件')

const idle = { hidden: false, sending: false, reviewStarting: false }
// 问过一句、回答已落定、没有在跑的运行：不再轮
assert.equal(shouldRefreshLiveState({ ...idle, runStatus: 'completed' }), false)
assert.equal(shouldRefreshLiveState({ ...idle, runStatus: undefined }), false)
// 运行还在跑：继续轮
assert.equal(shouldRefreshLiveState({ ...idle, runStatus: 'running' }), true)
// 聊天回答进行中：有自己的等待轮询和 SSE，这里不再叠一套
assert.equal(shouldRefreshLiveState({ ...idle, sending: true, runStatus: 'running' }), false)
// 正式复核发起中（同步 POST 跑好几分钟）：要靠这里看运行状态
assert.equal(
  shouldRefreshLiveState({ ...idle, reviewStarting: true, runStatus: 'completed' }),
  true
)
// 后台标签页：什么都不轮
assert.equal(
  shouldRefreshLiveState({ ...idle, hidden: true, reviewStarting: true, runStatus: 'running' }),
  false
)

console.log('Review B run polling contract passed')
