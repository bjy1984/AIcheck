/**
 * 复核跑起来的时候，用户得看得见东西在动、也得能叫停。
 *
 * 线上实测（2026-08-15 用户反馈）：
 *   - 发送按钮不转圈、还能再点；
 *   - 没有任何叫停入口，一场几分钟的复核只能干等；
 *   - 执行动态只有一句「执行中」，后台七八十条事件一条都没露面。
 *
 * 根因是这三处都只认聊天路径的 sending，而正式复核用的是 reviewStarting：
 * 执行动态的事件源只过滤 agent.*，而复核发的是 graph_node.* / quality_gate.*，
 * 一条都不匹配。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

// 复核的事件也要进执行动态
assert.ok(sfc.includes('liveRunTrace'), '复核事件没有对应的动态流')
assert.ok(
  /REVIEW_RUN_EVENT_PREFIXES\s*=\s*\/\^\(graph_node/.test(sfc),
  'graph_node 之类的运行事件要被认出来'
)

// 发送按钮与停止按钮两条路径共用一个口径
assert.ok(sfc.includes('executionInFlight'), '发送/停止还在只认聊天路径')
const composer = sfc.slice(sfc.indexOf('class="composer-actions"'))
const composerBlock = composer.slice(0, composer.indexOf('</section>'))
assert.ok(
  composerBlock.includes(':loading="executionInFlight"'),
  '复核期间发送按钮要转圈'
)
assert.ok(
  composerBlock.includes(':disabled="executionInFlight"'),
  '复核期间不该还能再点发送'
)
assert.ok(composerBlock.includes('stopCurrentExecution'), '要有叫停入口')

// 叫停复核走的是 ReviewRun 取消，不是会话取消
const stop = sfc.slice(sfc.indexOf('const stopCurrentExecution'))
assert.ok(
  stop.slice(0, stop.indexOf('\nconst stopCurrentAnswer')).includes('cancelReviewRunApi'),
  '停止复核要调 ReviewRun 的取消接口'
)

console.log('Review B execution feedback contract passed')
