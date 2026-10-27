import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { NO_RESET_WHITE_LIST } from '../../constants'
import { isPathAllowedForRole, resolveRoleEntryPath } from '../../utils/roleAccess'
import {
  decodeSkillAuthorizeRequest,
  loopbackCallbackPort,
  skillCallbackUrl
} from './skillAuthorize'

const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url')
const STATE = 'Qm9vdHN0cmFwU3RhdGVWYWx1ZTEyMzQ1'
const CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
const good = { r: 'http://127.0.0.1:54321/callback', s: STATE, c: CHALLENGE }

// skill 生成的授权请求能解开
const decoded = decodeSkillAuthorizeRequest(encode(good))
assert.deepEqual(decoded, {
  redirectUri: good.r,
  state: STATE,
  codeChallenge: CHALLENGE,
  port: 54321
})

// 回调地址只认本机：和后端同一套规则，授权码不能被送到别的主机
for (const ok of [
  'http://127.0.0.1:54321/callback',
  'http://localhost:8765/callback',
  'http://[::1]:9000/callback'
]) {
  assert.notEqual(loopbackCallbackPort(ok), null, ok)
}
for (const bad of [
  'https://127.0.0.1:54321/callback',
  'http://evil.example:54321/callback',
  'http://127.0.0.1.evil.example:54321/callback',
  'http://user@127.0.0.1:54321/callback',
  'http://127.0.0.1:54321/callback?x=1',
  'http://127.0.0.1:54321/other',
  'http://127.0.0.1/callback',
  'http://127.0.0.1:80/callback',
  'http://127.0.0.1:99999/callback'
]) {
  assert.equal(loopbackCallbackPort(bad), null, bad)
  assert.equal(decodeSkillAuthorizeRequest(encode({ ...good, r: bad })), null, bad)
}

// 缺字段、格式不对、不是 base64url 的一律不认
assert.equal(decodeSkillAuthorizeRequest(encode({ ...good, s: 'short' })), null)
assert.equal(decodeSkillAuthorizeRequest(encode({ ...good, c: 'x' })), null)
assert.equal(decodeSkillAuthorizeRequest('not base64!'), null)
assert.equal(decodeSkillAuthorizeRequest(Buffer.from('not json').toString('base64url')), null)
assert.equal(decodeSkillAuthorizeRequest(undefined), null)

// 回调 URL 带上 state；授权带 code，拒绝带 error
assert.equal(
  skillCallbackUrl(decoded!, { code: 'abc-DEF_123' }),
  `http://127.0.0.1:54321/callback?code=abc-DEF_123&state=${STATE}`
)
assert.equal(
  skillCallbackUrl(decoded!, { error: 'access_denied' }),
  `http://127.0.0.1:54321/callback?error=access_denied&state=${STATE}`
)

// 未登录时守卫把 to.path 带去登录页，登录后要能原样回到授权页（参数在路径里，不会丢）
const path = `/skill-authorize/${encode(good)}`
for (const role of ['inspection', 'admin', 'contractor']) {
  assert.equal(isPathAllowedForRole(path, role), true, role) // 页面谁都能看；不能授权的角色由页面说明、后端拒绝
  assert.equal(resolveRoleEntryPath(role, path), path, role)
}
assert.equal(isPathAllowedForRole('/skill-authorize', 'inspection'), false) // 没有授权请求的空地址不放行

// 回归（2026-10-28 生产实测）：未登录 → 登录页 → 登录时 resetRouter() 删掉不在 NO_RESET_WHITE_LIST
// 里的路由 → 回跳授权页落到 404。授权页的路由名必须在保留名单里，而且和路由定义里写的名字一致。
const routerSource = readFileSync(
  fileURLToPath(new URL('../../router/index.ts', import.meta.url)),
  'utf8'
)
assert.match(
  routerSource,
  /path: '\/skill-authorize\/:payload',\s*component: [^\n]+\n\s*name: 'SkillAuthorize'/
)
assert.ok(NO_RESET_WHITE_LIST.includes('SkillAuthorize'))
