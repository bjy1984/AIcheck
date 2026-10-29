import assert from 'node:assert/strict'
import { handler, ref, deferred, noop, asyncNoop } from './workflowTestHarness'
import { previewContentError } from './components/previewContentValidation'

const failures: string[] = []
try {
  const response = deferred()
  const state = {
    activePane: ref('assistant'),
    composer: ref('A question'),
    session: ref({ id: 'A', etag: 'a' }),
    sending: ref(false),
    executionStarted: ref(false),
    messages: ref<any[]>([]),
    workspace: ref<any>({ session: { id: 'A' } }),
    reviewContextGeneration: ref(1),
    activeProjectId: ref('project-A'),
    activeNodeId: ref(1),
    startLiveAgentTrace: noop,
    stopLiveAgentTrace: noop,
    PENDING_MESSAGE_PREFIX: 'pending-',
    scrollTimelineToEnd: asyncNoop,
    sendReviewBMessageApi: () => response.promise,
    mergeMessages: (items: any[]) => state.messages.value.push(...items),
    waitForAssistantCompletion: asyncNoop,
    loadSessionData: asyncNoop,
    refreshLiveState: asyncNoop,
    scrollToLatestAnswer: asyncNoop,
    getAicheckErrorMessage: () => '',
    ElMessage: { error: noop }
  }
  const send = handler('../AIReviewB/ConversationalReviewWorkbenchB.vue', 'sendMessage', state)
  const pending = send()
  await Promise.resolve()
  state.reviewContextGeneration.value++
  state.session.value = { id: 'B', etag: 'b' }
  state.workspace.value = { session: { id: 'B' } }
  state.messages.value = [{ id: 'B-message' }]
  state.composer.value = 'B draft'
  response.resolve({
    data: {
      session: { id: 'A' },
      userMessage: { id: 'A-user' },
      assistantMessage: { id: 'A-answer' }
    }
  })
  await pending
  assert.equal(state.workspace.value.session.id, 'B', 'old session response must not replace B')
  assert.deepEqual(state.messages.value, [{ id: 'B-message' }])
} catch (error) {
  failures.push(`W05: ${error}`)
}

try {
  const a = deferred()
  const b = deferred()
  const props = { modelValue: true, detail: { document: { projectId: 'P', id: 'A' } } }
  const pdfBlobs = {
    A: new Blob(['%PDF-1.4\nA'], { type: 'application/pdf' }),
    B: new Blob(['%PDF-1.4\nB'], { type: 'application/pdf' })
  }
  const state = {
    props,
    officePreviewSupported: ref(true),
    officePreviewLoading: ref(false),
    officePreviewError: ref(''),
    officeObjectUrl: ref(''),
    officePreviewRequest: { current: 0 },
    revokeOfficeObjectUrl: noop,
    getDocumentOfficePreviewApi: (_: string, id: string) => (id === 'A' ? a.promise : b.promise),
    getDocumentOriginalBlobApi: async (url: 'A' | 'B') => ({ data: pdfBlobs[url] }),
    previewContentError,
    URL: { createObjectURL: (blob: Blob) => (blob === pdfBlobs.B ? 'blob:B' : 'blob:A') },
    getAicheckErrorMessage: () => ''
  }
  const mount = handler('./components/FileDetailDialog.vue', 'mountOfficePreview', state)
  const pendingA = mount()
  props.detail.document.id = 'B'
  const pendingB = mount()
  b.resolve({ data: { url: 'B' } })
  await pendingB
  a.resolve({ data: { url: 'A' } })
  await pendingA
  assert.equal(state.officeObjectUrl.value, 'blob:B', 'old Office response must not replace B')
} catch (error) {
  failures.push(`W16: ${error}`)
}
try {
  const created = deferred()
  const bound: any[] = []
  const state = {
    ensureWritableProject: () => true,
    actionLoading: ref(false),
    uploadDrawerError: ref(''),
    uploadDrawerReplaceTarget: ref(null),
    uploadDrawerMaterialCategory: ref('补正资料'),
    uploadDrawerAtomicMaterial: ref(null),
    uploadDrawerMode: ref('project'),
    uploadDrawerRectificationTarget: ref<any>({ rectificationId: 'R-A', nodeId: 2 }),
    activeProjectId: ref('A'),
    activeNodeId: ref(2),
    currentProject: ref({ etag: 'a' }),
    uploadDrawerVisible: ref(true),
    correctionPreferredBindingIds: ref<string[]>([]),
    activeRectificationId: ref(''),
    rectificationDialogMode: ref('submit'),
    rectificationDialogVisible: ref(false),
    inferUploadFileType: () => 'pdf',
    createDocumentUploadSessionApi: () => created.promise,
    uploadFileToSignedUrl: asyncNoop,
    completeDocumentUploadSessionApi: async () => ({ data: {} }),
    bindDocumentsToNodeApi: async (project: string, payload: any) => {
      bound.push([project, payload])
      return { data: { affectedIds: ['new-A'] } }
    },
    buildCorrectionUploadBindingPayload: (target: any) => target,
    presentUploadCompletion: () => ({}),
    loadProjectBundle: asyncNoop,
    loadNodePackage: asyncNoop,
    showUploadDrawerError: noop,
    getAicheckErrorMessage: () => '',
    ElMessage: { warning: noop, success: noop }
  }
  const upload = handler('./useWorkbenchUploadSession.ts', 'handleCreateUploadSession', state)
  const pending = upload([{ name: 'new.pdf', size: 20 }])
  state.uploadDrawerVisible.value = false
  state.uploadDrawerRectificationTarget.value = undefined
  created.resolve({
    data: {
      uploadSessionId: 'upload-A',
      uploadUrls: [{ documentId: 'doc-A', documentVersionId: 'version-A' }]
    }
  })
  await pending
  assert.equal(bound.length, 1, 'closing the drawer must not erase the correction upload target')
  assert.deepEqual(bound[0], ['A', { rectificationId: 'R-A', nodeId: 2 }])
} catch (error) {
  failures.push(`W10: ${error}`)
}
try {
  const a = deferred()
  const b = deferred()
  const state = {
    activeProjectId: ref('P'),
    fileDetailVisible: ref(false),
    fileDetailLoading: ref(false),
    fileDetail: ref<any>(undefined),
    fileDetailRequest: { current: 0 },
    getDocumentDetailApi: (_: string, id: string) => (id === 'A' ? a.promise : b.promise),
    showActionError: noop
  }
  const open = handler('./Workbench.vue', 'handleOpenFileDetail', state)
  const first = open('A')
  const second = open('B')
  b.resolve({ data: { document: { id: 'B' } } })
  await second
  a.resolve({ data: { document: { id: 'A' } } })
  await first
  assert.equal(state.fileDetail.value.document.id, 'B', 'old file detail must not replace B')
} catch (error) {
  failures.push(`W16 detail: ${error}`)
}
assert.deepEqual(failures, [])
console.log('Workflow response-order regressions passed (W05, W10, W16)')
