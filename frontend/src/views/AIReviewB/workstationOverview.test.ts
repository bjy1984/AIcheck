import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { needsAttention, overviewResult } from './workstationOverview'
import { filterWorkstationNodes, workstationNavigation } from './workstationNavigation'
import type { ReviewBWorkspace } from '@/types/ai-review-b'
import type { ProjectTreePayload } from '@/api/aicheck'
const registry = JSON.parse(
  readFileSync(
    new URL('../../../../backend/config/workstations/registry.json', import.meta.url),
    'utf8'
  )
)
assert.deepEqual(
  workstationNavigation,
  registry.stations.map(({ id, name, nodeIds }) => ({ id, name, nodeIds }))
)
assert.equal(new Set(workstationNavigation.flatMap((item) => item.nodeIds)).size, 69)
const groups = [
  {
    groupName: 'authorized only',
    nodes: [
      { nodeId: 24, status: '待人工确认' },
      { nodeId: 35, status: '已通过' }
    ]
  }
] as ProjectTreePayload['groups']
assert.deepEqual(
  filterWorkstationNodes(groups, 'A', '').flatMap((group) =>
    group.nodes.map((node) => node.nodeId)
  ),
  [24]
)
assert.deepEqual(filterWorkstationNodes(groups, 'A', '已通过'), [])
assert.equal(groups[0].nodes.length, 2)
const workspace: Pick<ReviewBWorkspace, 'activeReviewRun' | 'projectAnalysisResults'> = {
  activeReviewRun: { id: 'new', findingDrafts: [] },
  projectAnalysisResults: [
    {
      reviewRunId: 'old',
      projectAnalysisRunId: 'old-project',
      reviewResult: 'supported',
      findingDrafts: [{ title: 'old success' }],
      createdAt: '2026-09-08'
    }
  ]
}
assert.equal(overviewResult(workspace)?.reviewRunId, 'new')
assert.deepEqual(overviewResult(workspace)?.findingDrafts, [])
assert.equal(overviewResult(workspace)?.reviewResult, undefined)
workspace.activeReviewRun = { id: 'pending' }
assert.equal(
  overviewResult(workspace),
  undefined,
  'pending run must not display previous success as current'
)
workspace.activeReviewRun = null
assert.equal(overviewResult(workspace)?.reviewRunId, 'old')
assert.equal(needsAttention({}), true)
assert.equal(
  needsAttention({
    checklistVerdict: '符合',
    groundingStatus: 'grounded',
    evidenceRefs: [{ evidenceLinkId: 'E1' }]
  }),
  false
)
assert.equal(
  needsAttention({
    checklistVerdict: '不适用',
    groundingStatus: 'grounded',
    evidenceRefs: [{ evidenceLinkId: 'E1' }]
  }),
  false
)
assert.equal(needsAttention({ checklistVerdict: '不符合' }), true)
assert.equal(
  needsAttention({ checklistVerdict: '符合', suggestedAction: 'request_correction' }),
  true
)
assert.equal(
  needsAttention({ checklistVerdict: '符合', groundingStatus: 'insufficient_evidence' }),
  true
)
assert.equal(
  needsAttention({ checklistVerdict: '符合', unsupportedClaims: ['unverified claim'] }),
  true
)
console.log(
  'Overview: active-run boundaries, conservative filtering and backend station parity passed'
)

assert.equal(needsAttention({ checklistVerdict: '符合' }), true, '缺引用的符合不能离开待核对列表')
