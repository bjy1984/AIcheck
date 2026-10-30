import assert from 'node:assert/strict'
import test from 'node:test'

import { friendlyHttpErrorMessage, getAicheckErrorMessage } from '../src/utils/aicheckError.ts'

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

test('turns raw axios messages into something a user can act on', () => {
  assert.match(friendlyHttpErrorMessage('Request failed with status code 500'), /服务暂时不可用/)
  assert.match(friendlyHttpErrorMessage('Request failed with status code 403'), /没有权限/)
  assert.match(friendlyHttpErrorMessage('Network Error'), /网络连接失败/)
  assert.match(friendlyHttpErrorMessage('timeout of 5000ms exceeded'), /超时/)
  assert.equal(friendlyHttpErrorMessage('密码错误'), '密码错误', 'Chinese business messages pass through')
  assert.match(
    getAicheckErrorMessage(new Error('Request failed with status code 502'), '登录失败'),
    /服务器错误 502/
  )
})
