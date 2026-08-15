/**
 * 同一个节点包不该在同一轮里请求两次。
 *
 * 实测（2026-08-15，施工方进场）：nodes/16/package 连发两次，
 * 第二次等了 11.4 秒——两个相同请求打在一起，服务端按顺序处理，
 * 后一个纯粹在白等前一个。
 *
 * 触发点有十几处（进场加载、路由 watcher、静默刷新……），
 * 在六千行里逐个追是追一个漏一个，所以去重放在请求这层。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')
const start = sfc.indexOf('let inFlightNodePackage')
assert.ok(start > 0, '节点包请求没有做去重')

const fn = sfc.slice(start, sfc.indexOf('const loadInspectionDetails'))

// 去重键要带项目：同一个 nodeId 在不同项目下是不同的东西
assert.ok(/requestKey = `\$\{activeProjectId\.value\}#\$\{nodeId\}`/.test(fn), '去重键要含项目 id')

// 登记必须在 await 之前，否则同一轮的第二次调用看不到它
const bodyStart = fn.indexOf('const request = getNodePackageApi')
const register = fn.indexOf('inFlightNodePackage = { key: requestKey')
const awaitAt = fn.indexOf('await request')
assert.ok(bodyStart > 0 && register > bodyStart && register < awaitAt, '要先登记再 await')

// 结束时必须清掉，否则这个节点包永远不会再请求
assert.ok(fn.includes('inFlightNodePackage = undefined'), '结束要清掉飞行标记')

// 复用那一支也要照顾 loading 态，别让静默刷新把界面的 loading 关掉
const reuse = fn.slice(fn.indexOf('if (inFlightNodePackage?.key === requestKey)'))
assert.ok(reuse.slice(0, 400).includes('options.silent'), '复用时 loading 态要按本次调用的意图')

console.log('Workbench node package dedup contract passed')
