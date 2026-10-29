import assert from 'node:assert/strict'
import { findingReviewState, ownerActivityItems, pendingFinding } from './workbenchTruth'
import { handler, ref, deferred } from './workflowTestHarness'
import { buildContractorWorkbenchModel } from './components/contractor/contractorWorkbenchViewModel'
import type { ArchiveItem, Project, ReportVersion } from '@/types/aicheck'

assert.equal(pendingFinding({ status: 'draft', humanStatus: 'pending_human_review' }), true)
assert.equal(pendingFinding({ status: 'accepted', humanStatus: 'pending_human_review' }), false)
assert.equal(
  findingReviewState({ status: 'rejected', humanStatus: 'pending_human_review' }),
  '未采纳'
)
assert.equal(pendingFinding({ status: 'draft', humanStatus: undefined }), true)
assert.equal(pendingFinding({ status: 'draft', humanStatus: 'confirmed' }), false)

// An empty authorized report list must not manufacture a report, timeline or future milestone.
assert.deepEqual(ownerActivityItems(undefined, [], []), [])
const activity = ownerActivityItems(
  { name: 'Project', updatedAt: '2026-10-01 10:00:00' } as Project,
  [
    {
      title: 'Actual report',
      versionNo: 'V3',
      status: '已签发',
      generatedAt: '2026-10-02 10:00:00'
    }
  ] as ReportVersion[],
  [{ name: 'Actual archive', updatedAt: '2026-10-03 10:00:00' }] as ArchiveItem[]
)
assert.equal(activity.length, 3)
assert.equal(activity[0].description, 'Actual archive')
assert.equal(activity[1].description, 'Actual report · V3')
assert.ok(activity.every((item) => !item.title.includes('预计')))

const computed = (fn: () => unknown) => ({
  get value() {
    return fn()
  }
})

// Extracted or confirmed OCR fields are not a field-consistency result.
const nodePackage = ref<{ extractedFields: { fieldName: string; reviewStatus: string }[] } | null>(
  null
)
const extractedFields = handler('./Workbench.vue', 'extractedFields', { computed, nodePackage })
const reviewRole = ref('inspection')
const chainSteps = handler('./Workbench.vue', 'reviewChainSteps', {
  computed,
  extractedFields,
  role: reviewRole,
  latestAiReviewDisplay: ref({ failed: false }),
  latestAiRun: ref(null),
  evidenceLinks: ref([]),
  formatConfidence: () => '98%'
})
assert.equal(chainSteps.value[1].result, '待核验', 'unloaded fields cannot pass')
nodePackage.value = { extractedFields: [] }
assert.equal(chainSteps.value[1].result, '待核验', 'loaded empty fields cannot pass')
assert.match(chainSteps.value[1].desc, /暂未返回结构化字段/)
for (const reviewStatus of ['未复核', '已确认', '已修正']) {
  nodePackage.value.extractedFields = [{ fieldName: '证书编号', reviewStatus }]
  assert.equal(chainSteps.value[1].result, '待核验', `${reviewStatus} is not a consistency result`)
  assert.match(chainSteps.value[1].desc, /不代表一致性或关联环节完整性已通过/)
}
for (const reviewStatus of ['低置信度', '置信度未知']) {
  nodePackage.value.extractedFields = [{ fieldName: '证书编号', reviewStatus }]
  assert.equal(chainSteps.value[1].result, '需人工确认')
}
reviewRole.value = 'contractor'
nodePackage.value.extractedFields = [{ fieldName: '证书编号', reviewStatus: '已确认' }]
assert.equal(chainSteps.value[1].title, '关联环节完整性')
assert.equal(
  chainSteps.value[1].result,
  '待核验',
  'confirmed OCR cannot prove related-stage completeness'
)

const props = {
  reports: [],
  archiveItems: [],
  metrics: [{ key: 'report', label: '报告版本', value: 0 }],
  reportArchiveLoaded: false,
  reportArchiveLoading: false,
  reportArchiveIssue: ''
}
const unavailable = handler(
  './components/WorkbenchRoleStaticSections.vue',
  'reportArchiveUnavailable',
  { computed, props }
)
const emptyLabel = handler(
  './components/WorkbenchRoleStaticSections.vue',
  'reportArchiveEmptyLabel',
  { computed, props }
)
const cards = handler('./components/WorkbenchRoleStaticSections.vue', 'ownerMetricCards', {
  computed,
  props,
  reportArchiveUnavailable: unavailable,
  reportArchiveEmptyLabel: emptyLabel
})
assert.equal(cards.value[0].value, '—', 'unloaded reports must not be presented as zero')
props.reportArchiveLoaded = true
assert.equal(cards.value[0].value, 0, 'successfully loaded empty authorized list is a real zero')
props.reportArchiveIssue = 'Could not load'
assert.equal(cards.value[0].value, '—', 'load failure must not be presented as zero')

// File corrections and pending feedback count different business objects.
const contractor = buildContractorWorkbenchModel({
  projectFiles: [
    {
      id: 'D',
      updatedAt: '',
      fileStatus: '需补正',
      currentOcrStatus: '已识别',
      bindings: [{ bindingStatus: '需补正' }]
    }
  ] as any,
  rectifications: []
})
assert.equal(contractor.primaryTabs.find((item) => item.key === '需补正')?.count, 1)
assert.equal(contractor.summaryCards.find((item) => item.key === 'feedback')?.count, 0)

// Switching the finding while its evidence is loading cannot show the previous finding's evidence.
const evidenceA = deferred()
const evidenceB = deferred()
const detailState = {
  props: { finding: { id: 'A', projectId: 'P', nodeId: 1 } },
  requestGeneration: { value: 0 },
  loading: ref(false),
  issue: ref(''),
  evidence: ref<any[]>([]),
  nodePackage: ref<any>(undefined),
  getEvidenceChainApi: (_: string, nodeId: number) =>
    nodeId === 1 ? evidenceA.promise : evidenceB.promise,
  getNodePackageApi: async (_: string, nodeId: number) => ({ data: { node: { nodeId } } }),
  getAicheckErrorMessage: String
}
const detail = handler('./components/GenericFindingDetail.vue', 'loadDetail', detailState)
const first = detail()
detailState.props.finding = { id: 'B', projectId: 'P', nodeId: 2 }
const second = detail()
evidenceB.resolve({ data: { links: [{ id: 'B-evidence' }] } })
await second
evidenceA.resolve({ data: { links: [{ id: 'A-evidence' }] } })
await first
assert.deepEqual(detailState.evidence.value, [{ id: 'B-evidence' }])
assert.equal(detailState.nodePackage.value.node.nodeId, 2)

console.log('Workbench truthful statuses, scoped counts and detail context passed')
