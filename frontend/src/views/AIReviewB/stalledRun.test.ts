/**
 * 一条久无动静的运行，不能永远显示「执行中」。
 *
 * 用户报的原话：「ai 对话等待了很久，一直在执行中，顶部刷新状态一直在加载转圈」。
 *
 * 2026-08-15 复验：工作台上仍挂着一条 09:59 建的 queued 运行，
 * 十几个小时后还在显示「执行中」——它早就没有执行器在跑了，
 * 是修复 I-1 之前留下的僵尸运行。
 *
 * 后端那半（运行跑完并落库）已经修好，但界面这半没有：
 * 「排队中」和「已经死了」长得一模一样，监检不知道该继续等还是该重新发起。
 * 这是这条问题最耗人的地方。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

assert.ok(sfc.includes('const runLooksStalled'), '没有判断运行是否已经停住')
assert.ok(/STALE_RUN_AFTER_MS\s*=\s*\d+/.test(sfc), '没有定义停滞阈值')

// 停住的运行不能再算「执行中」，否则转圈永远停不下来
const active = sfc.slice(sfc.indexOf('const executionActive'), sfc.indexOf('const showExecutionActivity'))
assert.ok(active.includes('!runLooksStalled.value'), '停住的运行仍被算作执行中')

// 状态文案要说「中断」，不能继续假装在跑
assert.ok(sfc.includes("'执行已中断'"), '没有把停滞状态说出来')

// 摘要要给出停在哪一刻 + 下一步能做什么
const summary = sfc.slice(sfc.indexOf('const executionSummary'), sfc.indexOf('const executionStatusLabel'))
assert.ok(summary.includes('runLooksStalled'), '摘要没有区分停滞')
assert.ok(/可重新发起复核/.test(summary), '没有告诉用户下一步能做什么')

// 时间取 updatedAt 优先——createdAt 只说明何时建的，不代表最后一次进展
assert.ok(
  /updatedAt \|\| activeRun\.value\?\.createdAt/.test(sfc),
  '停滞时间应以最后更新为准'
)

console.log('Stalled run contract passed')
