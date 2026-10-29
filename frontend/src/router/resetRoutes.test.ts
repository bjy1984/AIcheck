import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { createRouter, createMemoryHistory } from 'vue-router'
import { NO_RESET_WHITE_LIST } from '../constants'

const require = createRequire(import.meta.url)
const esbuild = require(
  require.resolve('esbuild', { paths: [dirname(require.resolve('vite/package.json'))] })
)
const source = readFileSync(new URL('./index.ts', import.meta.url), 'utf8')
// Exercise the real route records and reset function with an in-memory router.
const recordsSource = source
  .slice(
    source.indexOf('export const constantRouterMap'),
    source.indexOf('export const asyncRouterMap')
  )
  .replace('export const', 'const')
const routes = new Function(
  'Layout',
  'AICheckStaticLayout',
  'FdeFeedbackTriage',
  'FdeBlindReview',
  'FdeConsole',
  `${esbuild.transformSync(recordsSource, { loader: 'ts' }).code}; return constantRouterMap`
)({}, {}, {}, {}, {})
const router = createRouter({ history: createMemoryHistory(), routes })
router.addRoute({ path: '/admin/private-test', name: 'DynamicAdmin', component: {} })
const resetSource = source
  .slice(source.indexOf('export const resetRouter'), source.indexOf('export const setupRouter'))
  .replace('export const', 'const')
const reset = new Function(
  'router',
  'NO_RESET_WHITE_LIST',
  `${esbuild.transformSync(resetSource, { loader: 'ts' }).code}; return resetRouter`
)(router, NO_RESET_WHITE_LIST)

reset()
reset() // login after logout must remain safe
for (const [path, name] of [
  ['/fde-feedback-triage', 'FdeFeedbackTriage'],
  ['/fde-blind-review', 'FdeBlindReview'],
  ['/fde/standards-vectorization', 'FdeStandardsVectorizationRedirect'],
  ['/join/capture-token', 'ProjectRegistration'],
  ['/skill-authorize/capture-payload', 'SkillAuthorize']
]) {
  assert.equal(router.resolve(path).name, name, `${path} must survive login/logout reset`)
}
assert.equal(router.hasRoute('DynamicAdmin'), false, 'role-specific routes must still be removed')
