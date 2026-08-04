import assert from 'node:assert/strict'
import test from 'node:test'

import { getAicheckErrorMessage } from '../src/utils/aicheckError.ts'

test('explains how to recover when the Redis security backend is unavailable', () => {
  const message = getAicheckErrorMessage(
    {
      response: {
        data: {
          code: 503,
          message: '安全服务不可用',
          data: { reason: 'SECURITY_BACKEND_UNAVAILABLE' }
        }
      }
    },
    '登录失败'
  )

  assert.match(message, /启动 Redis/)
  assert.match(message, /本地开发模式/)
  assert.match(message, /SECURITY_BACKEND_UNAVAILABLE/)
})

test('keeps actionable CONFLICT business messages without recovery clutter', () => {
  const message = getAicheckErrorMessage(
    {
      response: {
        data: {
          code: 40900,
          message: '用户名已存在，请更换用户名。',
          data: { reason: 'CONFLICT' }
        }
      }
    },
    '用户保存失败'
  )

  assert.equal(message, '用户名已存在，请更换用户名。')
})
