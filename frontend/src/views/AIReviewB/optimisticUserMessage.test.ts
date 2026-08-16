/**
 * 发出去的话要立刻上屏，输入框要立刻清空。
 *
 * ## 线上实测（2026-08-16）
 *
 * 点发送后连续采样八次、跨 5.6 秒：
 *
 *     输入框: "测试用问题：本节点缺哪些证据"   ← 一直是原文
 *     我的问题在页面上: false                  ← 一次都没出现
 *
 * 原因是「上屏」和「清空」都排在 `await sendReviewBMessageApi` 之后，
 * 而那个接口要等 Agent 跑完才返回（几十秒）。
 *
 * **用户看到的是「点了发送什么都没发生」**——于是会再点一次，
 * 或者认定系统坏了。等待本身不是问题，等待时没有任何回应才是。
 *
 * ## 判据
 *
 * - 占位消息在 await 之前入列，输入框在 await 之前清空
 * - 服务端回来后先摘占位再合并，否则同一句话显示两遍
 * - 发送失败要摘掉占位并把原话还给输入框——
 *   让人重打一遍自己刚写的东西，是最不该有的惩罚
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

const start = sfc.indexOf('const sendMessage = async')
assert.ok(start > 0, '找不到发送函数')
const fn = sfc.slice(start, sfc.indexOf('const stopCurrentExecution'))

// 常量定义在函数外，占位入列这一步要在函数体里找
const pendingAt = fn.indexOf('id: pendingId')
const clearAt = fn.indexOf("composer.value = ''")
// 注意：注释里也写着 await sendReviewBMessageApi，直接 indexOf 会命中注释，
// 得出「占位在 await 之后」的假失败。按真实调用形态匹配。
const awaitAt = fn.indexOf('const res = await sendReviewBMessageApi')

assert.ok(pendingAt > 0 && pendingAt < awaitAt, '占位消息必须在发请求之前入列')
assert.ok(clearAt > 0 && clearAt < awaitAt, '输入框必须在发请求之前清空')

// 回来后先摘占位再合并——否则同一句话会显示两遍
const removeAt = fn.indexOf('filter((item) => item.id !== pendingId)', awaitAt)
const mergeAt = fn.indexOf('mergeMessages(', awaitAt)
assert.ok(removeAt > awaitAt, '服务端回来后要摘掉本地占位')
assert.ok(removeAt < mergeAt, '要先摘占位再合并真实记录')

// 失败路径：摘占位 + 把原话还回去
const catchAt = fn.indexOf('} catch (error) {')
assert.ok(
  fn.indexOf('filter((item) => item.id !== pendingId)', catchAt) > catchAt,
  '发送失败要摘掉占位，不能留一条假消息在屏上'
)
assert.ok(/composer\.value = text/.test(fn.slice(catchAt)), '发送失败要把原话还给输入框')

// 占位用本地 id 前缀，便于识别与清理
assert.ok(
  /const PENDING_MESSAGE_PREFIX = 'local-pending-'/.test(sfc),
  '占位消息要有可识别的 id 前缀'
)
