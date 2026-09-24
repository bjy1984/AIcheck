import assert from 'node:assert/strict'
import { explicitJevSetting, reviewPluginPatch } from './reviewPlugins'

assert.equal(explicitJevSetting({}), undefined)
assert.equal(explicitJevSetting({ reviewPlugins: { jev: { enabled: false } } }), false)
assert.equal(explicitJevSetting({ reviewPlugins: { jev: { enabled: true } } }), true)

assert.deepEqual(reviewPluginPatch(undefined, false), {}, '没动过开关，不改旧白名单工程')
assert.deepEqual(reviewPluginPatch(true, true), {})
assert.deepEqual(reviewPluginPatch(undefined, true), { reviewPlugins: { jev: { enabled: true } } })
assert.deepEqual(reviewPluginPatch(true, false), { reviewPlugins: { jev: { enabled: false } } })
