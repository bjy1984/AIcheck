import assert from 'node:assert/strict'

import { buildNodeReviewHeadline, materialStats, type NodeMaterialRow } from './nodeReviewSummary'

const row = (requiredType: string, status: string, name = '资料'): NodeMaterialRow => ({
  id: `${requiredType}-${status}-${name}`,
  name,
  requiredType,
  responsibleParty: '施工方',
  matchedFileNames: status === '未找到' ? [] : ['a.pdf'],
  status
})

// 线上节点 1：必传 3 项，2 项已确认、1 项没挂
const node1 = materialStats([row('必传', '未找到'), row('必传', '已确认'), row('必传', '已确认')])
assert.deepEqual(node1, {
  requiredTotal: 3,
  requiredDone: 2,
  missing: 1,
  pending: 0,
  attention: 0,
  optional: 0
})

// 挂了没确认的不算「缺」，也不重复算进两个数里
const mixed = materialStats([
  row('必传', '待确认'),
  row('必传', '已驳回'),
  row('条件必传', '未找到'),
  row('可选', '未找到')
])
assert.equal(mixed.missing, 0)
assert.equal(mixed.pending, 2)
assert.equal(mixed.attention, 1)
assert.equal(mixed.optional, 1)
assert.equal(mixed.requiredTotal, 3, '可选不算进必传分母')

const ai = {
  runId: 'PARUN-1',
  activityAt: '2026-10-31 11:31:59',
  sourceLabel: '全工程一键分析',
  running: false,
  errorMessage: ''
}

assert.deepEqual(
  buildNodeReviewHeadline({ ai, counts: { needAction: 0, confirm: 1 }, materials: node1 }),
  {
    badge: { label: '待你下结论', tone: 'orange' },
    parts: ['AI 已初审（10-31 一键分析）', '1 条待你确认', '缺 1 份必传资料']
  },
  '摘要行只说一次：AI 到哪了、要我确认几条、缺什么；0 条的不说'
)

assert.deepEqual(
  buildNodeReviewHeadline({
    ai,
    counts: { needAction: 2, confirm: 0 },
    materials: node1,
    latestOpinion: { result: '需补正', createdAt: '2026-11-01 09:00:00' }
  }).badge,
  { label: '已下结论：需补正', tone: 'red' },
  '已经下过结论的节点徽标显示结论本身'
)

assert.deepEqual(
  buildNodeReviewHeadline({
    ai: { ...ai, running: true },
    materials: materialStats([])
  }),
  { badge: { label: 'AI 审查中', tone: 'blue' }, parts: ['AI 正在审查'] }
)
assert.deepEqual(
  buildNodeReviewHeadline({ ai: { ...ai, errorMessage: '模型超时' }, materials: node1 }).parts,
  ['AI 审查失败', '缺 1 份必传资料']
)
assert.deepEqual(
  buildNodeReviewHeadline({ ai: { ...ai, runId: '' }, materials: materialStats([]) }).parts,
  ['AI 还没审']
)
assert.equal(
  buildNodeReviewHeadline({
    ai: { ...ai, sourceLabel: '节点 AI 复核', activityAt: '2026-08-31 11:21:20' },
    materials: materialStats([])
  }).parts[0],
  'AI 已初审（08-31 节点复核）'
)
