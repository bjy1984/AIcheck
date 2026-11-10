/**
 * 对话记忆的界面口径：上次要点怎么排、闲置提示什么时候出现、偏好字数怎么数，
 * 以及工作台确实把记忆条接上了（新对话、不再带上、回答偏好三个入口都在）。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import type { ReviewBSession } from '@/types/ai-review-b'
import {
  carryOverDigest,
  carryOverLines,
  hasCarryOver,
  historyHint,
  preferenceLength,
  shortStamp
} from './conversationMemory'

assert.equal(shortStamp('2026-11-02 14:03:11'), '11-02 14:03')
assert.equal(shortStamp(undefined), '')
assert.equal(shortStamp('昨天'), '昨天')

const lines = carryOverLines({
  fromSessionId: 'RSESSION-1',
  lastActivityAt: '2026-11-02 14:03:11',
  items: [
    { askedAt: '2026-11-02 14:00:00', question: '焊工证？', verdict: '不符合', answer: '已过期' },
    { askedAt: '2026-11-02 14:01:00', question: '检测报告？', verdict: null, answer: '' },
    {
      askedAt: '2026-11-02 14:01:30',
      question: '印章齐吗？',
      verdict: '需人工确认',
      verdictSummary: '3 项：需人工确认 1、符合 2',
      answer: '印章待核'
    }
  ],
  unanswered: [{ askedAt: '2026-11-02 14:02:00', question: '许可证？' }]
})
assert.deepEqual(
  lines.map((line) => [line.kind, line.verdict, line.tone, line.askedAt]),
  [
    ['answered', '不符合', 'danger', '11-02 14:00'],
    ['answered', '未下结论', 'info', '11-02 14:01'],
    ['answered', '需人工确认', 'warning', '11-02 14:01'],
    ['unanswered', '没答完', 'info', '11-02 14:02']
  ]
)
assert.equal(lines[2].summary, '3 项：需人工确认 1、符合 2')
assert.equal(lines[0].summary, '')
assert.equal(carryOverLines(null).length, 0)

// 收起时标题行的结论摘要：同一结论合并计数、按首次出现排序、最多 4 个
assert.deepEqual(
  carryOverDigest([...lines, ...lines]).map((chip) => [chip.verdict, chip.tone, chip.count]),
  [
    ['不符合', 'danger', 2],
    ['未下结论', 'info', 2],
    ['需人工确认', 'warning', 2],
    ['没答完', 'info', 2]
  ]
)
assert.equal(
  carryOverDigest(
    ['a', 'b', 'c', 'd', 'e', 'f'].map((verdict) => ({ ...lines[0], verdict })),
    3
  ).length,
  3
)
assert.deepEqual(carryOverDigest([]), [])

const base = { id: 'RSESSION-2', etag: 'W/"x"' } as unknown as ReviewBSession
assert.equal(hasCarryOver(base), false)
assert.equal(
  hasCarryOver({ ...base, carryOver: { fromSessionId: 'x', items: [], unanswered: [] } }),
  false
)
assert.equal(
  hasCarryOver({
    ...base,
    carryOver: { fromSessionId: 'x', items: [], unanswered: [{ question: 'q' }] }
  }),
  true
)

assert.equal(historyHint(base), '')
assert.equal(
  historyHint({
    ...base,
    memory: { historyDays: 7, lastMessageAt: '2026-10-20 09:00:00', historyExpired: false }
  }),
  ''
)
const hint = historyHint({
  ...base,
  memory: { historyDays: 7, lastMessageAt: '2026-10-20 09:00:00', historyExpired: true }
})
assert.ok(hint.includes('10-20 09:00') && hint.includes('7 天') && hint.includes('新对话'), hint)

// 后端按字符数限 300：一个汉字、一个表情都算 1
assert.equal(preferenceLength('  先列不符合项  '), 6)
assert.equal(preferenceLength('简短😀'), 3)

// 工作台接上了记忆条：工具条在标题行（对话再长也够得着），要点在对话开头
const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8')
const workbench = read('./ConversationalReviewWorkbenchB.vue')
const head = workbench.slice(
  workbench.indexOf('<section class="conversation-head">'),
  workbench.indexOf('</section>', workbench.indexOf('<section class="conversation-head">'))
)
assert.ok(head.includes('<ReviewConversationMemory'), '新对话、回答偏好不在对话栏标题行')
assert.ok(head.includes('@restarted="handleConversationRestarted"'), '新对话之后没有换会话')
const timeline = workbench.slice(workbench.indexOf('class="conversation-timeline"'))
assert.ok(
  timeline.indexOf('<ReviewConversationCarryOver') < timeline.indexOf('class="welcome-card"'),
  '上次要点要在对话开头'
)
// 悬浮助手里对话栏是按位置分行的网格，多插一个直接子元素会抢走对话区的弹性行
const column = workbench.slice(
  workbench.indexOf('<main class="conversation-column"'),
  workbench.indexOf('</main>')
)
assert.ok(!/\n {8}<ReviewConversation/.test(column), '记忆组件不能做对话栏的直接子元素')

// 建会话的幂等键要带会话代次：上一本归档后换键，否则中间件重放旧响应、永远建不出新会话
const ensureSession = workbench.slice(workbench.indexOf('const ensureSession = async'))
assert.ok(
  ensureSession.slice(0, 1200).includes('sessionGeneration') &&
    ensureSession.slice(0, 1200).includes('-after-${sessionGeneration}'),
  '建会话的幂等键没有带会话代次'
)

const toolbar = read('./components/ReviewConversationMemory.vue')
for (const label of ['新对话', '回答偏好']) {
  assert.ok(toolbar.includes(label), `工具条缺少「${label}」`)
}
assert.ok(toolbar.includes('restartReviewBSessionApi'), '新对话没有调后端')
assert.ok(toolbar.includes('saveReviewAssistantPreferencesApi'), '回答偏好没有保存到后端')
const carryOver = read('./components/ReviewConversationCarryOver.vue')
assert.ok(carryOver.includes('不再带上'), '要点卡片没有「不再带上」')
assert.ok(carryOver.includes('dismissReviewBCarryOverApi'), '不再带上没有调后端')
// 要点卡片：收起时标题行里要有结论摘要；展开后封顶，不能占满悬浮助手的可视区
const carrySource = readFileSync(
  fileURLToPath(new URL('./components/ReviewConversationCarryOver.vue', import.meta.url)),
  'utf8'
)
assert.ok(carrySource.includes('carry-over-digest'), '收起时标题行要有结论摘要')
assert.ok(
  /\.carry-over\[open\]\s*\{[^}]*max-height:[^;]+;[^}]*overflow-y:\s*auto/.test(carrySource),
  '展开后要封顶并内部滚动'
)
