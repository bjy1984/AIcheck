/**
 * 运行没变就别重取 audit-view。
 *
 * 实测（2026-08-15，事件接口瘦身之后）：3 秒一轮的轮询把 339 KB 的
 * audit-view 整个再拉一遍，13 秒里拉了 4 次，而且越拉越慢——
 * 1.4s → 3.0s → 4.4s → 13.2s。服务端是被自己人打崩的。
 *
 * 运行的 status/revision/updatedAt 都没动时，那份数据一个字都不会变。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const fn = sfc.slice(sfc.indexOf('const loadAuditView'), sfc.indexOf('const loadSessionData'))

assert.ok(fn.includes('loadedAuditViewSignature'), 'audit-view 没有做变更判据')
assert.ok(/if \(!force && auditView\.value && signature === loadedAuditViewSignature\) return/.test(fn))

// 指纹要覆盖真正会让内容变化的字段
const sig = sfc.slice(sfc.indexOf('const auditViewSignature'), sfc.indexOf('const loadAuditView'))
for (const field of ['status', 'revision', 'updatedAt']) {
  assert.ok(sig.includes(field), `指纹漏了 ${field}，内容变了却不会重取`)
}

// 失败不能留下指纹，否则一次失败会被当成「已经取过了」，永远不再重试
assert.ok(
  /catch[\s\S]*loadedAuditViewSignature = ''/.test(fn),
  '取失败要清掉指纹，下一轮还得重试'
)

console.log('Review B audit-view refetch contract passed')
