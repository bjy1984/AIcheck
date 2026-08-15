/**
 * 监检登录后落地的这一页，必须能退出登录、也能切回完整工作台。
 *
 * 实测（2026-08-15）：/ai-review-b 页头只有「刷新状态 / 文件库 / 文件列表 / 张工」，
 * 用户名是纯文字不可点，全页搜不到「退出」二字——监检进来之后没有任何办法登出。
 *
 * 「文件列表」这个名字也是旧的：它去的是完整的传统工作台。Workbench.vue 里
 * 早就因为「有人问怎么切换回传统视图」改叫「完整工作台」，这边漏改，
 * 而监检默认落地的恰恰是这一页。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const header = sfc.slice(sfc.indexOf('<div class="topbar-spacer">'), sfc.indexOf('</header>'))

assert.ok(header.includes('退出登录'), '页头没有退出登录入口')
assert.ok(header.includes('完整工作台'), '「文件列表」这个旧名字没改')
assert.ok(!header.includes('>文件列表<'), '还留着名不副实的「文件列表」')
assert.ok(header.includes('handleUserCommand'), '用户名没有接上菜单')

// 退出要走带确认的那条，别让人误点一下就掉线
const handler = sfc.slice(sfc.indexOf('const handleUserCommand'))
assert.ok(
  handler.slice(0, handler.indexOf('const handleBackToWorkbench')).includes('logoutConfirm'),
  '退出要二次确认'
)

console.log('Review B header user menu contract passed')
