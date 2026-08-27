import assert from 'node:assert/strict'

import {
  createSessionWithAuthorizationRecovery,
  reviewSessionMutationHeaders
} from '@/views/AIReviewB/reviewSessionRecovery'
import { canLoadProjectNode, resolveLoadableProjectNodeId } from './projectNodeSelection'

const attempts: Array<{ key: string; silent: boolean }> = []
const result = await createSessionWithAuthorizationRecovery(
  async (idempotencyKey, silent) => {
    attempts.push({ key: idempotencyKey, silent })
    if (attempts.length === 1) {
      throw { response: { data: { data: { reason: 'FORBIDDEN' } } } }
    }
    return { sessionId: 'RSESSION-RECOVERED' }
  },
  'review-session-P-1-24',
  () => 'nonce-1'
)

assert.deepEqual(result, { sessionId: 'RSESSION-RECOVERED' })
assert.deepEqual(attempts, [
  { key: 'review-session-P-1-24', silent: true },
  { key: 'review-session-P-1-24-reauth-nonce-1', silent: false }
])

await assert.rejects(
  () =>
    createSessionWithAuthorizationRecovery(
      async () => {
        throw { response: { data: { data: { reason: 'NOT_FOUND' } } } }
      },
      'review-session-P-1-24',
      () => 'unused'
    ),
  (error: unknown) =>
    (error as { response?: { data?: { data?: { reason?: string } } } }).response?.data?.data
      ?.reason === 'NOT_FOUND'
)

let forbiddenAttempts = 0
await assert.rejects(
  () =>
    createSessionWithAuthorizationRecovery(
      async () => {
        forbiddenAttempts += 1
        throw { response: { data: { data: { reason: 'FORBIDDEN' } } } }
      },
      'review-session-P-1-24',
      () => 'nonce-2'
    ),
  (error: unknown) =>
    (error as { response?: { data?: { data?: { reason?: string } } } }).response?.data?.data
      ?.reason === 'FORBIDDEN'
)
assert.equal(forbiddenAttempts, 2, '真实权限拒绝只允许重试一次')

assert.equal(
  resolveLoadableProjectNodeId(24, [{ nodes: [{ nodeId: 1 }, { nodeId: 2 }] }]),
  1,
  '切换项目后不能沿用不存在的旧节点'
)
assert.equal(resolveLoadableProjectNodeId(24, []), undefined, '无节点项目不能继续请求节点资料包')
assert.equal(canLoadProjectNode(24, []), false)
assert.equal(canLoadProjectNode(24, [{ nodes: [{ nodeId: 24 }] }]), true)

assert.deepEqual(
  reviewSessionMutationHeaders('review-session-P-1-24', {
    silentBusinessError: true,
    silentHttpError: true
  }),
  {
    'Idempotency-Key': 'review-session-P-1-24',
    'X-Silent-Business-Error': 'true',
    'X-Silent-Http-Error': 'true'
  }
)
