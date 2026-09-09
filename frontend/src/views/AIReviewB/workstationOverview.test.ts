import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { needsAttention, overviewProgress, overviewResult } from './workstationOverview'
import {
  filterWorkstationNodes,
  workstationCounts,
  workstationNavigation
} from './workstationNavigation'
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
assert.deepEqual(workstationCounts(groups, 'A'), { total: 1, review: 0, confirm: 1, correction: 0 })
assert.deepEqual(workstationCounts(groups, 'E'), { total: 1, review: 0, confirm: 0, correction: 0 })
assert.deepEqual(workstationCounts(groups, ''), { total: 2, review: 0, confirm: 1, correction: 0 })
const mixed = [
  {
    groupName: 'visible',
    nodes: [
      { nodeId: 24, status: '待审查' },
      { nodeId: 25, status: '复审中' },
      { nodeId: 26, status: '需补正' },
      { nodeId: 27, status: '补正中' },
      { nodeId: 28, status: 'AI 预审中' },
      { nodeId: 29, status: '待提交' }
    ]
  }
] as ProjectTreePayload['groups']
assert.deepEqual(workstationCounts(mixed, 'A'), { total: 6, review: 2, confirm: 0, correction: 2 })
assert.equal(filterWorkstationNodes(mixed, 'A', '').flatMap((group) => group.nodes).length, 6)
assert.deepEqual(workstationCounts([], 'A'), { total: 0, review: 0, confirm: 0, correction: 0 })
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
assert.equal(overviewResult(workspace), undefined, 'empty draft array is not a result')
for (const status of ['queued', 'running', 'failed', 'completed', 'waiting_human_input']) {
  workspace.activeReviewRun = { id: 'new', status, findingDrafts: [] }
  assert.equal(overviewResult(workspace), undefined)
  workspace.activeReviewRun.findingDrafts = [{ title: 'partial finding' }]
  assert.equal(
    overviewResult(workspace)?.findingDrafts?.length,
    1,
    'retain actual partial findings'
  )
}
assert.match(overviewProgress('queued'), /排队/)
assert.match(overviewProgress('failed'), /没能完成/)
assert.match(overviewProgress('waiting_human_input'), /人工待办/)
assert.match(overviewProgress('completed'), /不代表已经通过/)
assert.match(overviewProgress('running'), /还没出齐/)
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
