import assert from 'node:assert/strict'
import { computed, nextTick, reactive, ref } from 'vue'
import { handler } from './workflowTestHarness'
import { latestArchiveItem, latestReportVersion, pendingFinding } from './workbenchTruth'

// Exercise the component's actual computed state and navigation handler against
// multiple authorized findings. The demo seed has only one, so it cannot expose
// selection disappearing from a filtered list.
const workbench = ref({
  findings: [
    { id: 'accepted', status: 'accepted', evidenceLinkIds: ['E1'] },
    { id: 'pending', status: 'draft', evidenceLinkIds: [] },
    { id: 'pending-evidence', status: 'draft', evidenceLinkIds: ['E2'] }
  ]
})
const findingFilter = ref('all')
const selectedFindingId = ref('accepted')
const selectedGenericView = ref('findings')
const visibleFindings = handler('./GenericReviewWorkbench.vue', 'visibleFindings', {
  computed,
  workbench,
  findingFilter,
  pendingFinding
})
const selectedFinding = handler('./GenericReviewWorkbench.vue', 'selectedFinding', {
  computed,
  workbench,
  selectedFindingId,
  visibleFindings
})
const showFindings = handler('./GenericReviewWorkbench.vue', 'showFindings', {
  findingFilter,
  selectedGenericView,
  roleContent: ref({ reviewDetails: true }),
  nextTick,
  document: { getElementById: () => null }
})

const failures: string[] = []
const check = (name: string, run: () => void) => {
  try {
    run()
  } catch (error) {
    failures.push(`${name}: ${(error as Error).message}`)
  }
}
assert.equal(selectedFinding.value?.id, 'accepted')
await showFindings('pending')
assert.equal(selectedGenericView.value, 'human')
assert.deepEqual(
  visibleFindings.value.map((item: { id: string }) => item.id),
  ['pending', 'pending-evidence']
)
check('pending navigation hides the excluded accepted finding', () => {
  assert.equal(selectedFinding.value, undefined)
})
selectedFindingId.value = 'pending'
assert.equal(selectedFinding.value?.id, 'pending')
// This is the same ref update performed by the filter select's v-model.
findingFilter.value = 'evidence'
check('evidence dropdown hides a finding with no evidence', () => {
  assert.equal(selectedFinding.value, undefined)
})
await showFindings('evidence')
assert.equal(selectedGenericView.value, 'evidence', 'evidence filter and navigation agree')
selectedFindingId.value = 'pending-evidence'
assert.equal(selectedFinding.value?.id, 'pending-evidence')
await showFindings('pending')
assert.equal(selectedFinding.value?.id, 'pending-evidence', 'a visible selection stays open')
await showFindings('all')
assert.equal(selectedGenericView.value, 'findings', 'all filter returns to the findings view')
assert.equal(findingFilter.value, 'all')
assert.equal(visibleFindings.value.length, 3)
workbench.value = { findings: [] }
assert.equal(selectedFinding.value, undefined, 'removed findings cannot leave stale details')

// Lists may arrive in insertion order. Every surface claiming to show the latest
// item must use its actual update date without reordering the caller's array.
const props = reactive({
  reports: [
    { id: 'old', generatedAt: '2026-10-01 10:00:00' },
    { id: 'recent', generatedAt: '2026-10-02 10:00:00' },
    { id: 'updated', generatedAt: '2026-09-01 10:00:00', updatedAt: '2026-10-03 10:00:00' }
  ],
  archiveItems: [
    { id: 'old', updatedAt: '2026-10-01 10:00:00' },
    { id: 'recent', updatedAt: '2026-10-03 10:00:00' }
  ]
})
for (const path of [
  './components/WorkbenchRightStaticDetails.vue',
  './components/ReportArchivePanel.vue'
]) {
  const latest = handler(path, 'latestReport', { computed, props, latestReportVersion })
  check(`${path} latest report`, () => assert.equal(latest.value?.id, 'updated'))
  if (!path.endsWith('ReportArchivePanel.vue')) {
    const archive = handler(path, 'latestArchive', { computed, props, latestArchiveItem })
    check(`${path} latest archive`, () => assert.equal(archive.value?.id, 'recent'))
  }
}
assert.deepEqual(
  props.reports.map((item) => item.id),
  ['old', 'recent', 'updated']
)
assert.deepEqual(
  props.archiveItems.map((item) => item.id),
  ['old', 'recent']
)
props.reports = []
props.archiveItems = []
assert.equal(latestReportVersion([]), undefined)
assert.equal(latestArchiveItem([]), undefined)
assert.deepEqual(failures, [])
console.log('Workbench filtered selection and latest authorized records passed')
