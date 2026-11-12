/**
 * 2026-11-12 线上验证：电脑设成深色模式时整页半黑半白。
 * 原因是 initTheme 用 vueuse useDark，值等于系统偏好时存成 auto、之后跟随系统。
 * 本系统只有浅色样式，主题必须只认用户自己的开关。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const store = readFileSync(
  fileURLToPath(new URL('../store/modules/app.ts', import.meta.url)),
  'utf8'
)
const init = store.slice(store.indexOf('initTheme()'), store.indexOf('initTheme()') + 900)
assert.ok(!/useDark\(/.test(store), '不要用 useDark：它会把主题存成 auto 跟随系统')
assert.match(
  init,
  /classList\.toggle\('dark', this\.getIsDark\)/,
  '启动时按用户自己的开关设 dark 类'
)
assert.match(init, /removeItem\('vueuse-color-scheme'\)/, '要清掉旧的 auto 记录')

console.log('theme init ignores the OS color scheme')
