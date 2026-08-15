/**
 * 发起复核后，必须把新运行绑成会话的当前运行——绑不上要说话。
 *
 * 原来这里是 `.catch(() => undefined)`。后果不是「少了个链接」：
 * 工作台读的是会话上的 activeReviewRunId，绑不上就永远停在上一条运行。
 *
 * 2026-08-15 线上实测：界面钉在 09:59 那条永久 queued 的旧运行上显示
 * 「执行中」，而新运行早已 waiting_human_review 跑完并落库。刷新也不变。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const start = sfc.indexOf('const handleStartReview')
const body = sfc.slice(start, sfc.indexOf('\nconst ', start + 1))

assert.ok(body.includes('set_active_review_run'), '没找到绑定当前运行的调用')
// 只看代码行——注释里引用这段旧代码是在解释历史，不算违规
const codeLines = body
  .split('\n')
  .filter((line) => !line.trim().startsWith('//') && !line.trim().startsWith('*'))
  .join('\n')
assert.ok(!/catch\(\(\) => undefined\)/.test(codeLines), '绑定失败不能悄悄丢掉')
// etag 过期是最常见的失败原因，取新会话重试一次
assert.ok(body.includes('loadNodeWorkspace'), '失败后要取一份新会话再试')
assert.ok(/ElMessage\.(warning|error)/.test(body), '两次都失败要如实告诉用户')

console.log('Review B active run binding contract passed')
