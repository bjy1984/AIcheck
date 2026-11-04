import assert from 'node:assert/strict'
import type { InspectionAuditOverviewNode, InspectionNodeConclusion } from '@/types/aicheck'
import { buildStationOverview, conclusionReason, conclusionSourceTag } from './stationOverview'

const row = (nodeId: number, conclusion?: Partial<InspectionNodeConclusion> | null) =>
  ({
    node: { nodeId, name: `节点${nodeId}` },
    items: [],
    conclusion:
      conclusion === null ? null : { group: 'not_started', confirmed: false, ...conclusion }
  }) as unknown as InspectionAuditOverviewNode

const stations = [
  { stationId: 'B', stationName: '设计与技术基准', nodeIds: [1, 4, 9] },
  { stationId: 'C', stationName: '施工组织与品质体系', nodeIds: [2, 11] }
]
const rows = [
  row(1, { group: 'passed', confirmed: true }),
  row(4, { group: 'needs_materials', reason: { checkCodes: ['catalog_pages_submitted'] } }),
  row(9, { group: 'failed', reason: { checkCodes: ['standard_scope_matches_project_medium'] } }),
  row(2, { group: 'passed', notApplicable: true }),
  row(11, null),
  row(99, { group: 'needs_human' })
]

const overview = buildStationOverview(rows, stations)

// 按工位归组，不在任何工位里的节点进「其他」，总数和节点数对得上
assert.deepEqual(
  overview.stations.map((station) => [
    station.stationId,
    station.nodes.map((node) => node.node.nodeId)
  ]),
  [
    ['B', [1, 4, 9]],
    ['C', [2, 11]],
    ['其他', [99]]
  ]
)
assert.deepEqual(overview.totals, {
  failed: 1,
  needs_materials: 1,
  needs_human: 1,
  passed: 2,
  not_started: 1
})
assert.equal(overview.confirmedPassed, 1)
// 没有结论的节点算未开始审核
assert.equal(overview.stations[1].counts.not_started, 1)

// 行内原因翻成中文；人工意见原文优先
assert.equal(conclusionReason(rows[2]), '未满足：引用标准的适用介质与本工程介质一致')
assert.equal(
  conclusionReason(row(5, { group: 'failed', reason: { humanOpinion: '壁厚表缺第 1 页' } })),
  '监检意见：壁厚表缺第 1 页'
)
assert.equal(conclusionReason(rows[0]), '')

// 结论来源：已确认 / AI 判定·待确认 / 不适用 / 复核中
assert.deepEqual(conclusionSourceTag(rows[0]), { text: '已确认', tone: 'success' })
assert.deepEqual(conclusionSourceTag(rows[2]), { text: 'AI 判定·待确认', tone: 'info' })
assert.deepEqual(conclusionSourceTag(rows[3]), { text: '不适用', tone: 'info' })
assert.deepEqual(conclusionSourceTag(row(7, { runState: 'running' })), {
  text: '复核中',
  tone: 'info'
})
assert.equal(conclusionSourceTag(row(8)), null)

// 身份证号不在总览里全量展示
assert.equal(
  conclusionReason(
    row(6, {
      group: 'failed',
      reason: { checkCodes: ['410521198609180550:holder_matches_registry'] }
    })
  ),
  '未满足：4105**********0550：持证人与平台登记一致'
)
