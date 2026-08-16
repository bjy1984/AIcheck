/**
 * 收起状态下也要看得见执行动态，最多三行。
 *
 * 用户反馈（2026-08-16 PDF 第 1 条）：
 *   「AI 审查的过程中，streaming 的信息没有输出，用户只能看到标签，过程很枯燥，
 *     应该在标签下面刷新 streaming 消息，最多三行文字。」
 *
 * 成因：执行动态只在 activityExpanded 为真时渲染，而它默认收起。
 * 后台七八十条事件一条都露不出来——**过程不可见的等待，会被当成卡死**。
 *
 * 三行是上限不是目标：再多会把输入框挤下去，用户反而没法继续问。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)

// 常驻预览：收起时渲染
assert.ok(
  /v-if="!activityExpanded && livePreview\.length"/.test(sfc),
  '收起状态下要渲染执行动态预览'
)

// 三行上限
assert.ok(/\.slice\(-3\)/.test(sfc), '预览最多三条')

// **要显示真正的流式文字，不是事件名。**
// 第一版只渲染 event.title，三行全是「模型推理流 / 回答内容增量 / 模型推理流」——
// 用户看到的仍然只是标签。真正的文字在 payload.content 里
// （agent.reasoning.delta / agent.message.delta，实测各 91 / 24 条），
// 而第一版读的是 payload.summary——那个字段在这些事件上根本不存在。
// **读错字段和没实现，在界面上长得一模一样。**
assert.ok(/STREAM_TEXT_KEYS/.test(sfc), '要有取流式文字的字段清单')
assert.ok(/'content'/.test(sfc), 'payload.content 是实测里真正装文字的字段')
assert.ok(/const streamTextOf/.test(sfc), '要有取文字的函数')
assert.ok(/\.filter\(\(item\) => item\.text\)/.test(sfc), '优先显示带文字的事件')

// 展开后仍是全量，不能因为加了预览就把详情砍掉
assert.ok(/v-if="activityExpanded" class="execution-details"/.test(sfc), '展开后仍要有完整轨迹')
assert.ok(/v-for="event in liveTrace"/.test(sfc), '完整轨迹用的仍是 liveTrace')

// 预览与完整列表的 key 不能重复——同一批事件同时渲染两处会撞 key
assert.ok(/:key="'preview-' \+ item\.eventId"/.test(sfc), '预览的 key 要加前缀')

// 「刷新状态」按钮已去掉：实测 16 次采样 14 次在转圈，文字被 spinner 盖住，
// 看起来就是「时有时无」；而状态本来就在自动轮询。
assert.ok(!/>刷新状态</.test(sfc), '不应再有手动刷新按钮')

// 单行不换行：三行是硬上限，长文案要省略而不是撑高
assert.ok(/\.execution-preview li \{[^}]*white-space: nowrap/s.test(sfc), '预览每条限一行')
