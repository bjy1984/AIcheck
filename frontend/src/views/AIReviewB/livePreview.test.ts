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
  /v-if="!activityExpanded && executionActive && livePreview\.length"/.test(sfc),
  '收起且执行中时要渲染执行动态预览'
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

// 展开那份也要显示真正的文字。第一次修复只改了收起的预览，展开的列表
// 仍然只认 payload.summary——于是展开后满屏「模型推理流」，一个字都没有。
// **同一条规则写在两处、只改一处**，是这轮反复出现的形态。
assert.ok(
  /<small v-if="streamTextOf\(event\)">· \{\{ streamTextOf\(event\) \}\}<\/small>/.test(sfc),
  '展开的轨迹要用同一套取字逻辑'
)
assert.ok(!/'summary' in event\.payload/.test(sfc), '不该再只认 payload.summary')

// 预览与完整列表的 key 不能重复——同一批事件同时渲染两处会撞 key
assert.ok(/:key="'preview-' \+ item\.eventId"/.test(sfc), '预览的 key 要加前缀')

// 自动展开必须**一处都不剩**。第一版只去掉了 sendMessage 里那句，
// startLiveAgentTrace 和发起复核处还有两句，线上面板依旧 aria-expanded=true，
// 三行预览和光标一个都没渲染出来。**同一条规则写在三处，改一处等于没改。**
assert.ok(
  !/activityExpanded\.value = true/.test(sfc),
  '任何地方都不该自动展开执行面板——展开就没有三行预览'
)

// 右侧「当前状态」要说人话，且说的是这一轮
assert.ok(/RUN_STATUS_LABELS/.test(sfc), '状态枚举要翻成中文，不能把 failed 原样打给用户')
assert.ok(/const runStatusText = computed/.test(sfc), '要有面向用户的状态文案')
assert.ok(/\{\{ runStatusText \}\}/.test(sfc), '模板要用中文状态而不是原始枚举')
assert.ok(
  /if \(runStatusText\.value === '本轮已完成'\) return 'success'/.test(sfc),
  '颜色要跟着文字走，否则文字说完成、颜色还是红的'
)

// 发送时不许自动展开：展开渲染的是全量轨迹，收起态才是三行滚动预览。
// 自动展开会把用户要的那三行直接跳过去，面板还会把输入框挤下屏。
const sendAt = sfc.indexOf('const sendMessage = async')
const sendFn = sfc.slice(sendAt, sfc.indexOf('const stopCurrentExecution'))
assert.ok(!/activityExpanded\.value = true/.test(sendFn), '发送时不该自动展开执行面板')
assert.ok(!/activityExpanded\.value = false/.test(sendFn), '执行结束不该替用户合上他打开的面板')

// 跑完就收起推理预览：还挂着三行推理残片会把刚出的结论往下挤，
// 而那三行此刻已经没有信息量——过程看完了，该让位给结果。
assert.ok(
  /v-if="!activityExpanded && executionActive && livePreview\.length"/.test(sfc),
  '三行预览只在执行中显示'
)

// 答完把回答的开头滚进视口。一条几千字的结论，滚到最底看到的是它的尾巴，
// 用户还得自己往上翻才能读到判定。
assert.ok(/const scrollToLatestAnswer = async/.test(sfc), '要有对准回答开头的滚动')
assert.ok(/data-message-role="assistant"/.test(sfc), '选择器要有对应的真实属性')
assert.ok(
  /:data-message-role="message\.role"/.test(sfc),
  '消息节点要带上这个属性——选择器写了而元素没有，滚动会静默失败'
)
assert.ok(/await scrollToLatestAnswer\(\)/.test(sfc), '发送流程结束要调用它')

// 推理过程要有打字感：光标只跟最新一条、且只在执行中显示。
// 静止时还闪会让人以为内容还在生成——**假的进行中比没有反馈更糟**。
assert.ok(/class="typing-caret"/.test(sfc), '流式预览要有打字光标')
assert.ok(
  /v-if="executionActive && index === livePreview\.length - 1"/.test(sfc),
  '光标只跟在最新一条且仅执行中显示'
)
assert.ok(/prefers-reduced-motion/.test(sfc), '要尊重系统的减少动效设置')

// 新内容进来要跟到底部，且跟随判断必须在合并之前取——
// 合并后高度已变，那时再问「是否贴底」永远是 false，新内容会一直在屏幕外。
const pollAt = sfc.indexOf('const pollLiveAgentTrace')
const pollFn = sfc.slice(pollAt, sfc.indexOf('const LIVE_TRACE_FALLBACK_POLL_INTERVAL_MS'))
const followAt = pollFn.indexOf('const shouldFollow = isTimelineNearBottom()')
const mergeAt2 = pollFn.indexOf('mergeEvents(')
assert.ok(followAt > 0 && followAt < mergeAt2, '跟随判断要在合并事件之前取')
assert.ok(
  /if \(shouldFollow\) await scrollTimelineToEnd\(true\)/.test(pollFn),
  '流式刷新后要滚到底部'
)

// 「刷新状态」按钮已去掉：实测 16 次采样 14 次在转圈，文字被 spinner 盖住，
// 看起来就是「时有时无」；而状态本来就在自动轮询。
assert.ok(!/>刷新状态</.test(sfc), '不应再有手动刷新按钮')

// 单行不换行：三行是硬上限，长文案要省略而不是撑高
assert.ok(/\.execution-preview li \{[^}]*white-space: nowrap/s.test(sfc), '预览每条限一行')
