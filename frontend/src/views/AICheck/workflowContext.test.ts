import assert from 'node:assert/strict'
import { ref as vueRef } from 'vue'
import { useNodeReviewDraft } from './useNodeReviewDraft'
import { correctionSubmissionCandidates } from './correctionSubmission'
import { handler, ref, noop, asyncNoop } from './workflowTestHarness'
import type { NodeFileBinding, RectificationItem } from '@/types/aicheck'

// W01: A → B → A restores the authored text and evidence without leaking into B.
const project = vueRef('P1')
const node = vueRef(1)
const draft = useNodeReviewDraft(project, node)
draft.reviewOpinion.value = 'A evidence checked'
draft.correctionReason.value = 'A missing signature'
draft.selectedReviewEvidenceIds.value = ['A-evidence']
node.value = 2
assert.equal(draft.reviewOpinion.value, '')
assert.equal(draft.correctionReason.value, '')
assert.deepEqual(draft.selectedReviewEvidenceIds.value, [])
draft.reviewOpinion.value = 'B independent draft'
node.value = 1
assert.equal(draft.reviewOpinion.value, 'A evidence checked')
assert.deepEqual(draft.selectedReviewEvidenceIds.value, ['A-evidence'])
project.value = 'P2'
assert.equal(draft.reviewOpinion.value, '')

// W02: adding an attachment must not disappear when an old rejected file exists.
const bindings = [
  { id: 'old', nodeId: 2, bindingStatus: '需补正', usage: '原始提交' },
  { id: 'new', nodeId: 2, bindingStatus: '草稿挂载', usage: '补正附件' },
  { id: 'unrelated', nodeId: 2, bindingStatus: '已通过', usage: '原始提交' },
  { id: 'other-node', nodeId: 9, bindingStatus: '需补正', usage: '补正附件' }
] as NodeFileBinding[]
const correction = { id: 'R', nodeId: 2, bindingIds: ['old'] } as RectificationItem
assert.deepEqual(
  correctionSubmissionCandidates(bindings, correction, ['new']).map((item) => item.id),
  ['old', 'new']
)

// W03: use all authorized pages, not the selected node's correction slice.
const requestedPages: number[] = []
const useList = handler('./useProjectRectifications.ts', 'useProjectRectifications', {
  ref,
  watch: noop,
  getAicheckErrorMessage: () => 'Could not load',
  request: {
    get: async ({ params }: any) => {
      requestedPages.push(params.page)
      return { data: { items: [{ id: `R${params.page}`, nodeId: params.page }], total: 2 } }
    }
  }
})
const list = useList(ref('P'), ref('contractor'))
await list.loadProjectRectifications()
assert.deepEqual(requestedPages, [1, 2])
assert.deepEqual(
  list.projectRectifications.value.map((item: any) => item.nodeId),
  [1, 2]
)

// W04: a mutation refresh preserves node 7 and its current section; explicit
// project navigation can still choose the role's default node 1.
const loadedNodes: number[] = []
const bundleState = {
  activeProjectId: ref('P'),
  activeNodeId: ref(7),
  context: ref<any>({ project: { id: 'P' } }),
  role: ref('inspection'),
  loading: ref(false),
  pageIssue: ref(undefined),
  treeGroups: ref([]),
  activeWorkbenchSection: ref('node'),
  activeInspectionWorkspaceView: ref('manual'),
  summary: ref({}),
  getWorkbenchContextApi: async () => ({ data: { project: { id: 'P' }, currentNodeId: 1 } }),
  getProjectTreeApi: async () => ({ data: { groups: [] } }),
  resolveLoadableProjectNodeId: (id: number) => id,
  loadNodePackage: async (id: number) => {
    loadedNodes.push(id)
  },
  getWorkbenchSummaryApi: async () => ({ data: {} }),
  loadProjectRectifications: asyncNoop,
  loadReportArchive: asyncNoop,
  loadNdtData: asyncNoop,
  loadInspectionAuditOverview: asyncNoop,
  loadInspectionSubmittedDocuments: asyncNoop,
  getErrorMessage: String
}
const refresh = handler('./Workbench.vue', 'loadProjectBundle', bundleState)
await refresh()
assert.equal(loadedNodes.at(-1), 7)
assert.equal(bundleState.activeWorkbenchSection.value, 'node')
await refresh({ preserveSelection: false })
assert.equal(loadedNodes.at(-1), 1)
assert.equal(bundleState.activeWorkbenchSection.value, 'overview')

// W08: search routes to a visible target; failed targets keep the results open.
const opened: string[] = []
const searchState = {
  activeProjectId: ref('P'),
  activeNodeId: ref(1),
  role: ref('inspection'),
  projectTreeNodes: ref([{ nodeId: 7, name: 'Seven' }]),
  quickAccessVisible: ref(true),
  activeWorkbenchSection: ref('overview'),
  loadProjectBundle: asyncNoop,
  handleNodeSelect: async () => {
    opened.push('node')
    searchState.activeWorkbenchSection.value = 'node'
  },
  handleOpenFileDetail: async (id: string) => {
    opened.push(`file:${id}`)
    return true
  },
  handleOpenReportDetail: async (id: string) => {
    opened.push(`report:${id}`)
    return true
  },
  router: { resolve: () => ({ matched: [] }), push: asyncNoop },
  getAicheckErrorMessage: String,
  ElMessage: { warning: noop }
}
const locate = handler('./Workbench.vue', 'handleLocateQuickResult', searchState)
await locate({ type: 'node', id: '7', route: '/inspection?projectId=P&nodeId=7' })
assert.equal(searchState.activeWorkbenchSection.value, 'node')
await locate({ type: 'document', id: 'D', route: '/inspection?projectId=P' })
await locate({ type: 'report', id: 'R', route: '/inspection?projectId=P' })
assert.deepEqual(opened, ['node', 'file:D', 'report:R'])
searchState.quickAccessVisible.value = true
await locate({ type: 'rule', id: 'X', route: '/unavailable' })
assert.equal(searchState.quickAccessVisible.value, true)

// W11: transport failure leaves the loaded report and editor source intact.
const detail = { report: { id: 'R', etag: '1' }, sections: [{ content: 'original' }] }
const reportState = {
  activeProjectId: ref('P'),
  activeReportDetailId: ref('R'),
  reportDetail: ref(detail),
  actionLoading: ref(false),
  reportSaveError: ref(''),
  reportDetailError: ref(''),
  updateReportApi: async () => {
    throw new Error('offline')
  },
  getAicheckErrorMessage: (_: unknown, fallback: string) => fallback,
  ElMessage: { success: noop, warning: noop },
  loadReportArchive: asyncNoop
}
const save = handler('./Workbench.vue', 'handleSaveReportDetail', reportState)
const unsaved = { sections: [{ content: 'user draft' }] }
await save(unsaved)
assert.equal(reportState.reportDetail.value, detail)
assert.equal(reportState.reportDetailError.value, '')
assert.match(reportState.reportSaveError.value, /已保留编辑内容/)
assert.equal(unsaved.sections[0].content, 'user draft')
const uploadState = {
  props: { loading: false },
  selectedFile: ref<any>({ name: 'A.pdf' }),
  uploadRef: ref({ clearFiles: noop, handleStart: noop }),
  nextUploadFileId: () => 42
}
const replace = handler('./components/NdtReportUploadDrawer.vue', 'handleUploadExceed', uploadState)
replace([{ name: 'B.pdf' }])
assert.equal(uploadState.selectedFile.value.name, 'B.pdf')
assert.equal(uploadState.selectedFile.value.uid, 42)
console.log('Workflow context regressions passed (W01–W04, W08, W11, W12)')
