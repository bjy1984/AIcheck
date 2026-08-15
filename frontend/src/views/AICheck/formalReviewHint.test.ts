/**
 * 「正式复核」灰着的时候，必须说清楚还差什么。
 *
 * 用户实测反馈：「所有的『正式复核』按钮都不可点击，是流程没有推进到这一步还是 bug？」
 *
 * 判据本身是对的（必传资料未齐、候选证据未确认），问题在于那句解释只描述
 * **当前选中**的模式——而正式复核不可用时选中的必然是缺项预审，
 * 于是页面上写的是「缺项预审只生成补充资料建议…」，
 * 为什么正式复核是灰的一个字都没有。
 *
 * 一个不给理由的禁用按钮，和坏掉的按钮在用户眼里没有区别。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

assert.ok(sfc.includes('const formalReviewBlockedReason'), '没有「为什么不可用」的说明')

const reason = sfc.slice(
  sfc.indexOf('const formalReviewBlockedReason'),
  sfc.indexOf('const aiReviewModeHint')
)
// 要给出具体数字，不能只说「条件不满足」
assert.ok(reason.includes('missingCount'), '要说清还差几项必传资料')
assert.ok(reason.includes('pendingCount'), '要说清还有几条证据待确认')
assert.ok(reason.includes('补齐后即可发起'), '要告诉用户补齐之后能做什么')

// 选中缺项预审时也要带上这句，否则用户永远看不到
const hint = sfc.slice(
  sfc.indexOf('const aiReviewModeHint'),
  sfc.indexOf('const reviewSaveDisabledReason')
)
assert.ok(hint.includes('formalReviewBlockedReason'), '选中缺项预审时看不到正式复核的原因')

// 禁用的那个单选按钮自己也要挂说明
assert.ok(
  /:title="formalReviewBlockedReason \|\|/.test(sfc),
  '禁用的「正式复核」按钮上没有悬浮说明'
)

console.log('Formal review hint contract passed')
