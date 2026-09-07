import assert from 'node:assert/strict'

import type { ProjectAnalysisSummaryNode } from '@/api/aicheck/projectAnalysis'

import { projectAnalysisPriorityRows, projectAnalysisSummaryTotals } from './projectAnalysisSummary'

// P9 R4：节点优先级表按 需处理 → 待确认 → 证据不足 → 未见问题 排序，结论只由 12.3 决策表推导
const grounded = (title: string, severity: string) => ({
  title,
  description: '说明',
  severity,
  groundingStatus: 'grounded',
  evidenceRefs: [{ fileName: '证.pdf', pageNo: 1 }],
  ruleRefs: []
})
const downgraded = {
  title: '证据不足，需人工确认',
  description: '模板',
  severity: 'medium',
  groundingStatus: 'insufficient_evidence',
  unsupportedClaims: [{ claim: 'TS1', reason: 'not_present_in_supplied_evidence' }],
  evidenceRefs: [],
  ruleRefs: []
}
const nodes: ProjectAnalysisSummaryNode[] = [
  {
    nodeId: 2,
    nodeName: '安装许可',
    findingDrafts: [grounded('医院', 'low')],
    failedEvidenceShardIds: []
  },
  {
    nodeId: 24,
    nodeName: '焊工',
    findingDrafts: [downgraded, downgraded],
    failedEvidenceShardIds: ['ESHARD-1']
  },
  {
    nodeId: 1,
    nodeName: '设计许可',
    findingDrafts: [grounded('范围不覆盖 GC1', 'high'), grounded('日期', 'medium')],
    failedEvidenceShardIds: []
  },
  { nodeId: 9, nodeName: '空节点', findingDrafts: [], failedEvidenceShardIds: [] }
]
const rows = projectAnalysisPriorityRows({ nodes })
assert.deepEqual(
  rows.map((row) => [row.nodeId, row.verdict]),
  [
    [1, '需处理'],
    [2, '待确认'],
    [24, '证据不足'],
    [9, '证据不足']
  ]
)
assert.equal(rows[0].maxSeverityLabel, '重要')
assert.equal(rows[0].needAction, 1)
assert.equal(rows[0].confirm, 1)
assert.equal(rows[2].partialCoverage, true)
assert.equal(rows[2].insufficient, 2)
assert.deepEqual(projectAnalysisSummaryTotals(rows), {
  nodes: 4,
  needAction: 1,
  confirm: 1,
  insufficient: 2,
  clean: 0
})
assert.deepEqual(projectAnalysisPriorityRows(null), [])
