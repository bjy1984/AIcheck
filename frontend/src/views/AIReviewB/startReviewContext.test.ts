import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
const { transpileModule, ScriptTarget, ModuleKind } = createRequire(import.meta.url)(
  'typescript'
) as typeof import('typescript')

// Execute the actual SFC handler with controlled asynchronous API boundaries.
const source = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const start = source.indexOf('const handleStartReview =')
const end = source.indexOf('\n/**', start)
const compiled = transpileModule(source.slice(start, end), {
  compilerOptions: { target: ScriptTarget.ES2022, module: ModuleKind.None }
}).outputText
const ref = <T>(value: T) => ({ value })
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
const fixture = () => {
  const starts: unknown[][] = []
  const links: unknown[][] = []
  const notices: string[] = []
  let stops = 0
  let refreshes = 0
  const state = {
    canStartReview: ref(true),
    actionLoading: ref(false),
    reviewStarting: ref(false),
    executionStarted: ref(false),
    activityExpanded: ref(false),
    activeProjectId: ref('P-1'),
    activeNodeId: ref(24),
    reviewContextGeneration: ref(0),
    session: ref({ id: 'S-1', etag: 'old' }),
    reviewDocumentSelection: ref({
      versions: [{ documentId: 'D-1', versionId: 'V-1', fileName: 'old.pdf' }],
      reviewMode: 'gap_precheck'
    }),
    startReviewMode: ref('gap_precheck'),
    ElMessageBox: { confirm: async () => undefined },
    ElMessage: {
      warning: (value: string) => notices.push(value),
      success: (value: string) => notices.push(value),
      error: (value: string) => notices.push(value)
    },
    getAicheckErrorMessage: (_error: unknown, fallback: string) => fallback,
    startLiveAgentTrace: () => undefined,
    stopLiveAgentTrace: () => {
      stops++
    },
    refreshLiveState: async () => {
      refreshes++
    },
    requestAiRecheckApi: async (...args: unknown[]) => {
      starts.push(args)
      return { data: { dispatch: { reviewRunId: 'RR-1' } } }
    },
    runReviewBSessionActionApi: async (...args: unknown[]) => {
      links.push(args)
    },
    fetchWorkspace: async (..._args: unknown[]) => ({ session: { id: 'S-1', etag: 'new' } })
  }
  const run = () =>
    new Function(...Object.keys(state), `${compiled}; return handleStartReview();`)(
      ...Object.values(state)
    ) as Promise<void>
  return { state, run, starts, links, notices, stops: () => stops, refreshes: () => refreshes }
}
{
  const f = fixture()
  await f.run()
  assert.deepEqual(f.starts[0].slice(0, 3), [
    'P-1',
    24,
    { reviewMode: 'gap_precheck', inputDocumentVersionIds: ['V-1'] }
  ])
  assert.equal(f.links[0][0], 'S-1')
  assert.equal(f.refreshes(), 1)
  assert.equal(f.stops(), 1)
}
for (const returnToOriginal of [false, true]) {
  const f = fixture()
  const response = deferred<{ data: { dispatch: { reviewRunId: string } } }>()
  f.state.requestAiRecheckApi = async () => response.promise
  const running = f.run()
  await Promise.resolve()
  f.state.reviewContextGeneration.value++
  f.state.activeNodeId.value = returnToOriginal ? 24 : 25
  f.state.session.value = { id: returnToOriginal ? 'S-1' : 'S-2', etag: 'new-context' }
  // The new context may already be running its own action.
  f.state.actionLoading.value = true
  response.resolve({ data: { dispatch: { reviewRunId: 'OLD-RUN' } } })
  await running
  assert.deepEqual(f.links, [])
  assert.deepEqual(f.notices, [])
  assert.equal(f.refreshes(), 0)
  assert.equal(f.stops(), 0)
  assert.equal(f.state.actionLoading.value, true)
}
{
  const f = fixture()
  let calls = 0
  f.state.runReviewBSessionActionApi = async (...args) => {
    f.links.push(args)
    if (++calls === 1) throw new Error('stale etag')
  }
  await f.run()
  assert.equal(f.links.length, 2)
  assert.equal(f.links[1][0], 'S-1')
  assert.equal((f.links[1][3] as { etag: string }).etag, 'new')
}
{
  const f = fixture()
  const refreshed = deferred<{ session: { id: string; etag: string } }>()
  const fetching = deferred<void>()
  f.state.runReviewBSessionActionApi = async (...args) => {
    f.links.push(args)
    throw new Error('stale')
  }
  f.state.fetchWorkspace = async (...args) => {
    assert.deepEqual(args, [undefined, { projectId: 'P-1', nodeId: 24, generation: 0 }])
    fetching.resolve()
    return refreshed.promise
  }
  const running = f.run()
  await fetching.promise
  f.state.reviewContextGeneration.value++
  f.state.activeNodeId.value = 25
  refreshed.resolve({ session: { id: 'S-2', etag: 'other' } })
  await running
  assert.equal(f.links.length, 1)
  assert.deepEqual(f.notices, [])
}
{
  const f = fixture()
  f.state.ElMessageBox.confirm = async () => {
    f.state.reviewDocumentSelection.value.versions[0].versionId = 'NEW-VERSION'
  }
  await f.run()
  assert.deepEqual(
    (f.starts[0][2] as { inputDocumentVersionIds: string[] }).inputDocumentVersionIds,
    ['V-1']
  )
}
console.log(
  'Start-review context isolation: success, late response, ABA navigation, etag retry, late retry, fixed input'
)
