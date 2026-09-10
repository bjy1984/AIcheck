import assert from 'node:assert/strict'
import { handoffStatusError } from './handoffStatusError'
assert.match(handoffStatusError({ response: { status: 401 } }), /重新登录/)
assert.match(handoffStatusError({ response: { status: 403 } }), /工程权限/)
assert.match(handoffStatusError({ response: { status: 404 } }), /接口当前不可用/)
assert.match(handoffStatusError({ code: 501 }), /状态未知/)
assert.match(handoffStatusError({ response: { data: { code: 403 } } }), /工程权限/)
assert.match(handoffStatusError({ response: { status: 200, data: { code: 403 } } }), /工程权限/)
assert.match(handoffStatusError({ response: { status: 200, data: { code: 401 } } }), /重新登录/)
for (const error of [
  undefined,
  null,
  new Error('secret'),
  { response: { status: 503 } },
  { code: 'ECONNRESET' }
]) {
  assert.match(handoffStatusError(error), /暂时无法/)
  assert.doesNotMatch(handoffStatusError(error), /secret|ECONNRESET/)
}
