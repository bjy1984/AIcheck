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
assert.ok(/liveTrace\.value\.slice\(-3\)/.test(sfc), '预览最多三条')

// 展开后仍是全量，不能因为加了预览就把详情砍掉
assert.ok(/v-if="activityExpanded" class="execution-details"/.test(sfc), '展开后仍要有完整轨迹')
assert.ok(/v-for="event in liveTrace"/.test(sfc), '完整轨迹用的仍是 liveTrace')

// 预览与完整列表的 key 不能重复——同一批事件同时渲染两处会撞 key
assert.ok(/:key="'preview-' \+ event\.eventId"/.test(sfc), '预览的 key 要加前缀')

// 单行不换行：三行是硬上限，长文案要省略而不是撑高
assert.ok(/\.execution-preview li \{[^}]*white-space: nowrap/s.test(sfc), '预览每条限一行')
