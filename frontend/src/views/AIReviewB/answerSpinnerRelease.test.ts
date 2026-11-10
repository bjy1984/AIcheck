/**
 * 回答落定，「停止回答」就该停（2026-11-10 生产：回答 00:44:52 落库，按钮又转了十几秒）。
 *
 * 原来 sendMessage 等完回答还要 await 一整套工作台刷新（工作台、会话、事件、审计视图），
 * 全部回来才进 finally 把 sending 置 false。现在收尾刷新放到 finally 之后、不再 await；
 * 下一问要用的会话 etag 直接取消息接口带回的那份（回答落定会把 revision 加一）。
 *
 * 用源码断言而不是挂载组件：这个 SFC 依赖整套 Element Plus 与路由。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

const bodyOf = (name: string) => {
  const start = source.indexOf(`const ${name} = async`)
  assert.ok(start >= 0, `没找到 ${name}`)
  const next = source.indexOf('\nconst ', start + 1)
  return source.slice(start, next > 0 ? next : undefined)
}

const send = bodyOf('sendMessage')
const releaseAt = send.indexOf('sending.value = false')
const refreshAt = send.indexOf('refreshLiveState()')
assert.ok(releaseAt >= 0 && refreshAt >= 0, 'sendMessage 里要有释放和收尾刷新')
assert.ok(releaseAt < refreshAt, '先把「停止回答」停下，再做收尾刷新')
assert.ok(
  !/await\s+Promise\.all\(\[loadSessionData\(false\),\s*refreshLiveState\(\)\]\)/.test(send),
  '收尾刷新不能再 await 着，否则按钮要陪它转'
)
assert.ok(send.indexOf('scrollToLatestAnswer()') < releaseAt, '答完先把镜头对准回答开头')

const wait = bodyOf('waitForAssistantCompletion')
assert.ok(
  /res\.data\.session/.test(wait) && /session:\s*res\.data\.session/.test(wait),
  '回答落定时要用消息接口带回的会话，下一问才不会因为 etag 过期被拒'
)

console.log('Review B answer spinner release contract passed')
