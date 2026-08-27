import assert from 'node:assert/strict'

import handlers from '../mock/user/index.mock'

const login = handlers.find((handler) => handler.url === '/mock/user/login')
assert.ok(login && typeof login.response === 'function', 'mock 登录处理器必须存在')

for (const username of ['inspection', 'contractor', 'ndt', 'owner', 'admin', 'fde', 'test']) {
  const result = login.response({ query: {}, body: { username, password: 'anyuekeji.123' } })
  assert.equal(result?.code, 0, `${username} 未使用统一测试密码`)
}
