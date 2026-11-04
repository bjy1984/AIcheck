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
  '未满足：4105**********0550·持证人与平台登记一致'
)

// 行内展开的详情：审计项结论分布、全部不过的检查项、缺的资料、流程各步
{
  const { nodeDetail } = await import('./stationOverview')
  const expandRow = {
    node: {
      nodeId: 4,
      name: '设计文件的批准程序',
      requirementsSummary: {
        requiredCount: 3,
        satisfiedCount: 2,
        missingCount: 1,
        missingRequirements: [{ fileContent: '设计说明及管道特性表' }]
      }
    },
    items: [
      {
        key: 'ai_review',
        label: 'AI 复核',
        status: 'completed',
        statusLabel: '已完成',
        summary: ''
      }
    ],
    conclusion: {
      group: 'needs_materials',
      confirmed: false,
      atomicCounts: { passed: 1, evidence_insufficient: 2, human_review_required: 0 },
      reason: {
        checkCodes: [
          'catalog_pages_submitted',
          'corrosion_requirements_acceptancecriteria',
          'leaktest_requirements_testpressure'
        ]
      }
    }
  } as unknown as InspectionAuditOverviewNode
  const detail = nodeDetail(expandRow)
  assert.equal(detail.atomicSummary, '符合 1 · 证据不足 2')
  assert.equal(detail.failedChecks.length, 3)
  assert.equal(detail.materials?.done, 2)
  assert.deepEqual(detail.materials?.missing, ['设计说明及管道特性表'])
  assert.equal(detail.evidenceGapNote, '', '还缺资料时不说「资料已齐」')
  const complete = nodeDetail({
    ...expandRow,
    node: {
      ...expandRow.node,
      requirementsSummary: { requiredCount: 3, satisfiedCount: 3, missingCount: 0 }
    }
  } as unknown as InspectionAuditOverviewNode)
  assert.match(complete.evidenceGapNote, /^必传资料已齐/)
  assert.deepEqual(
    detail.process.map((step) => step.statusLabel),
    ['已完成']
  )
  // 折叠时那一行只写前两项，后面写「等 n 项」
  assert.match(
    conclusionReason(expandRow),
    /^未满足：图纸目录所列页数已交全；防腐蚀·已写明合格标准 等 3 项$/
  )
}

// 资料清单：全部 / 已传 / 未传；有文档 id 的文件才能点开预览
{
  const { nodeDetail, filterMaterials } = await import('./stationOverview')
  const withFiles = {
    node: {
      nodeId: 28,
      name: '管道组对',
      requirementsSummary: {
        requiredCount: 2,
        satisfiedCount: 1,
        missingCount: 1,
        requirements: [
          {
            id: 'R1',
            fileContent: '管道组对检查记录',
            requiredType: '必传',
            fulfilled: true,
            matchedFiles: [{ documentId: 'DOC-1', fileName: '组对记录.pdf' }]
          },
          {
            id: 'R2',
            fileContent: '现场照片',
            requiredType: '必传',
            fulfilled: false,
            matchedFileNames: []
          }
        ],
        missingRequirements: [{ id: 'R2', fileContent: '现场照片' }]
      }
    },
    items: [],
    conclusion: { group: 'needs_materials', confirmed: false }
  } as unknown as InspectionAuditOverviewNode
  const items = nodeDetail(withFiles).materials!.items
  assert.deepEqual(
    filterMaterials(items, 'uploaded').map((item) => item.name),
    ['管道组对检查记录']
  )
  assert.deepEqual(
    filterMaterials(items, 'missing').map((item) => item.name),
    ['现场照片']
  )
  assert.equal(filterMaterials(items, 'all').length, 2)
  assert.equal(items[0].files[0].documentId, 'DOC-1')
}

// 标准版本核对的检查码就是标准号：要说出它要的条件，不能只印编号
assert.equal(
  conclusionReason(row(9, { group: 'failed', reason: { checkCodes: ['GB/T 12459-2025'] } })),
  '未满足：GB/T 12459-2025 在审查日有效'
)

// 边框：不通过红、缺资料黄（没审但必传没交齐也算）、通过绿、其余灰
{
  const { nodeBorderTone, requiredMaterials } = await import('./stationOverview')
  const withReq = (group: string, done: number, total: number) =>
    ({
      ...row(30, { group: group as never }),
      group,
      node: {
        nodeId: 30,
        name: '节点30',
        requirementsSummary: { requiredCount: total, satisfiedCount: done }
      }
    }) as unknown as InspectionAuditOverviewNode
  assert.equal(nodeBorderTone(withReq('not_started', 0, 6)), 'missing', '没审但缺文件也是黄')
  assert.equal(nodeBorderTone(withReq('not_started', 6, 6)), 'neutral')
  assert.equal(nodeBorderTone(withReq('not_started', 0, 0)), 'neutral', '没有资料要求的不算缺')
  assert.equal(nodeBorderTone(withReq('failed', 0, 6)), 'failed', '不通过优先于缺资料')
  assert.equal(nodeBorderTone(withReq('passed', 6, 6)), 'passed')
  assert.equal(nodeBorderTone(withReq('needs_materials', 6, 6)), 'missing')
  assert.deepEqual(requiredMaterials(withReq('not_started', 2, 6)), { done: 2, total: 6 })
  assert.equal(requiredMaterials(withReq('not_started', 0, 0)), null)
}
