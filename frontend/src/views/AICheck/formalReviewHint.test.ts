/**
 * 文件完整度现在只提供审查提示，不能再禁用正式复核。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

const disabledReason = sfc.slice(
  sfc.indexOf('const aiRecheckDisabledReason'),
  sfc.indexOf('const aiRecheckButtonLabel')
)
assert.ok(disabledReason.includes("role.value !== 'inspection'"), '权限门禁仍需保留')
assert.ok(disabledReason.includes('isReadOnly.value'), '只读状态门禁仍需保留')
assert.ok(disabledReason.includes("availableActions.value.includes('ai:recheck')"), '动作权限门禁仍需保留')
assert.ok(!disabledReason.includes('readyForAiFormal.value'), '资料完整度仍在禁用正式复核')
assert.ok(!disabledReason.includes('readinessBlockingReasons.value'), '缺项提示仍被当成操作门禁')

const hint = sfc.slice(
  sfc.indexOf('const formalReviewBlockedReason'),
  sfc.indexOf('const reviewSaveDisabledReason')
)
assert.ok(hint.includes('资料完整度仅供审查参考'), '没有说明完整度是提示信息')
assert.ok(hint.includes('missingCount'), '提示中应保留缺项数量')
assert.ok(hint.includes('pendingCount'), '提示中应保留待确认证据数量')

console.log('Formal review advisory-readiness contract passed')
