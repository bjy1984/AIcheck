/**
 * 发版之后，开着旧页面的用户下一次路由跳转会白屏——必须能自愈。
 *
 * 每次构建 chunk 哈希全变、旧 chunk 被删；用户手上的 index.html 还是上一版的，
 * 记的还是旧名字。一跳到尚未加载过的路由就去要一个不存在的 chunk：
 *
 *   Failed to fetch dynamically imported module: /assets/Login-CjKYWBpL.js
 *
 * 后果不是报错，是那个路由**什么都渲染不出来**。2026-08-15 实测：部署后点
 * 退出登录，落到一片空白的登录页（标题在、表单没有），除了硬刷新没有出路，
 * 而普通用户不会知道要硬刷。
 *
 * 早前修 nginx 已经把「返回 HTML 冒充 JS」改成干净的 404，
 * 但「前端据此自愈」这一半一直没做。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(fileURLToPath(new URL('./permission.ts', import.meta.url)), 'utf8')

assert.ok(source.includes('router.onError'), '路由没有兜住加载失败')
assert.ok(source.includes('Failed to fetch dynamically imported module'), '没有识别版本错位的错误')
// 不同浏览器措辞不同，只认一种会漏
assert.ok(source.includes('Importing a module script failed'), 'Safari 的措辞没覆盖')

// 必须防死循环：重载后仍失败就不能再刷，否则把用户关进无限刷新
assert.ok(/CHUNK_RELOAD_COOLDOWN_MS|cooldown/i.test(source), '没有防重复重载的冷却')
assert.ok(source.includes('sessionStorage'), '重载标记要跨一次导航存活')
assert.ok(/console\.error/.test(source), '放弃重试时要留下真实原因')

// 只对版本错位重载——别把所有路由错误都变成刷新
assert.ok(source.includes('if (!isStaleChunkError(error)) return'), '不该对所有错误都重载')

console.log('Stale chunk recovery contract passed')
