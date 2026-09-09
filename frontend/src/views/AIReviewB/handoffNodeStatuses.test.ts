import assert from 'node:assert/strict'
import type { ProjectTreePayload } from '@/api/aicheck'
import type { HandoffNodeStatuses } from '@/api/aicheck/reviewHandoffs'
import { withHandoffStatuses } from './handoffNodeStatuses'
import { filterWorkstationNodes } from './workstationNavigation'

const groups = [
  {
    groupName: 'visible',
    nodes: [
      { projectId: 'P', nodeId: 24, status: '已通过' },
      { projectId: 'P', nodeId: 35, status: '待审查' }
    ]
  }
] as ProjectTreePayload['groups']
const report: HandoffNodeStatuses = {
  projectId: 'P',
  items: [
    { nodeId: 24, status: 'requires_revalidation', requiresRevalidation: true },
    { nodeId: 35, status: 'current', requiresRevalidation: false }
  ]
}
const before = JSON.stringify(groups)
const enriched = withHandoffStatuses(groups, report)
assert.equal(enriched[0].nodes[0].status, '已通过')
assert.deepEqual(
  filterWorkstationNodes(enriched, '', 'handoff_requires_revalidation')[0].nodes.map(
    (node) => node.nodeId
  ),
  [24]
)
assert.equal(filterWorkstationNodes(enriched, 'E', 'handoff_requires_revalidation').length, 0)
assert.equal(JSON.stringify(groups), before)
for (const value of [undefined, { ...report, projectId: 'OTHER' }, { ...report, items: [] }]) {
  const unknown = withHandoffStatuses(groups, value)
  assert.equal(filterWorkstationNodes(unknown, '', 'handoff_unavailable')[0].nodes.length, 2)
  assert.equal(filterWorkstationNodes(unknown, '', 'handoff_requires_revalidation').length, 0)
}
const duplicate = withHandoffStatuses(groups, {
  ...report,
  items: [...report.items, report.items[0]]
})
assert.equal(duplicate[0].nodes[0].handoffRevalidation, 'unavailable')
const contradictory = withHandoffStatuses(groups, {
  ...report,
  items: [{ nodeId: 24, status: 'requires_revalidation', requiresRevalidation: false }]
})
assert.equal(contradictory[0].nodes[0].handoffRevalidation, 'unavailable')
