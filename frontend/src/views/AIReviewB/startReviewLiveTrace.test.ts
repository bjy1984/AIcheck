/**
 * 发起 AI 复核的整个执行期间必须有执行动态。
 *
 * 线上实测：`ai-recheck` 是**同步执行整场审查**的一次 POST，服务器上跑要好几分钟。
 * 而 handleStartReview 从头到尾没调过 startLiveAgentTrace——这几分钟里页面上
 * 什么都不动：没有进度、没有步骤、没有事件。监检不知道是在跑、卡住了、还是已经挂了。
 *
 * 聊天路径（sendMessage）早就有现成的执行动态：SSE 推送 + 轮询兜底，
 * 事件流里会合并 ReviewRun 事件。这里只是从来没接上。
 *
 * 用源码断言而不是挂载组件：这个 SFC 依赖整套 Element Plus 与路由，
 * 为了验「有没有调这一个函数」把它整个跑起来不划算。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

// 只截 handleStartReview 自己的函数体：先前按「到 handleSaveReviewOpinion 为止」
// 切，中间夹进了 sendMessage，lastIndexOf('finally') 命中的是别人的 finally。
const start = source.indexOf('const handleStartReview')
assert.ok(start >= 0, '没找到 handleStartReview')
const nextDecl = source.indexOf('\nconst ', start + 1)
const body = source.slice(start, nextDecl > 0 ? nextDecl : undefined)

// 必须在**发起请求之前**就开始推送，否则同步等待的那几分钟仍然是空白。
const traceAt = body.indexOf('startLiveAgentTrace()')
const requestAt = body.indexOf('requestAiRecheckApi(')
assert.ok(traceAt >= 0, 'handleStartReview 没有接执行动态，用户会干等整场审查')
assert.ok(requestAt >= 0, '没找到 ai-recheck 请求')
assert.ok(traceAt < requestAt, '执行动态要在请求之前起，不然等待期仍然是空白')

// 跑完要关掉，否则 SSE 连接和兜底轮询会一直留着。
const finallyBlock = body.slice(body.lastIndexOf('finally'))
assert.ok(finallyBlock.includes('stopLiveAgentTrace()'), 'finally 里要停掉推送，别把连接漏在那')

console.log('Review B start-review live trace contract passed')
