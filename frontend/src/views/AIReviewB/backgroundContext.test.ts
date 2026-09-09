import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
const { transpileModule, ScriptTarget, ModuleKind } = createRequire(import.meta.url)(
  'typescript'
) as typeof import('typescript')
const source = readFileSync(
  fileURLToPath(new URL('./ConversationalReviewWorkbenchB.vue', import.meta.url)),
  'utf8'
)
const ref = <T>(value: T) => ({ value })
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
const execute = (name: string, state: Record<string, unknown>) => {
  state.workspaceReadSequence ??= ref(0)
  state.auditReadSequence ??= ref(0)
  const start = source.indexOf(`const ${name} =`)
  const next = source.indexOf('\nconst ', start + 1)
  const code = transpileModule(source.slice(start, next), {
    compilerOptions: { target: ScriptTarget.ES2022, module: ModuleKind.None }
  }).outputText
  return new Function(...Object.keys(state), `${code}; return ${name}(...args);`)(
    ...Object.values(state)
  ) as Promise<void>
}
for (const name of ['loadNodeWorkspace', 'refreshLiveState']) {
  for (const reject of [false, true]) {
    const response = deferred<unknown>()
    const state = {
      args: [false],
      activeProjectId: ref('P'),
      activeNodeId: ref(24),
      reviewContextGeneration: ref(0),
      workspace: ref<unknown>({ id: 'old' }),
      auditView: ref(undefined),
      reviewOpinion: ref(''),
      nodeLoading: ref(false),
      polling: ref(false),
      pageError: ref(''),
      activeRunId: ref('RUN'),
      route: { query: {} },
      fetchWorkspace: () => response.promise,
      ensureSession: () => {
        throw new Error('stale response must not ensure session')
      },
      loadSessionData: () => {
        throw new Error('must not load stale messages')
      },
      loadAuditView: () => {
        throw new Error('must not load stale audit')
      },
      updateRouteQuery: () => undefined,
      getAicheckErrorMessage: () => 'STALE ERROR'
    }
    const running = execute(name, state)
    state.reviewContextGeneration.value++
    state.workspace.value = { id: 'new' }
    state.pageError.value = 'new context message'
    state.nodeLoading.value = true
    state.polling.value = true
    if (reject) response.reject(new Error('old failure'))
    else response.resolve({ id: 'late workspace' })
    await running
    assert.deepEqual(state.workspace.value, { id: 'new' })
    assert.equal(state.pageError.value, 'new context message')
    assert.equal(state.nodeLoading.value, true)
    assert.equal(state.polling.value, true)
  }
}
for (const name of ['loadSessionData', 'pollLiveAgentTrace']) {
  const response = deferred<{ data: { messages: unknown[]; events: unknown[] } }>()
  const merges: unknown[] = []
  const state = {
    args: [false],
    session: ref({ id: 'S1' }),
    reviewContextGeneration: ref(0),
    messages: ref([]),
    events: ref([]),
    listReviewBMessagesApi: () => response.promise,
    listReviewBEventsApi: () => response.promise,
    eventPollCursor: () => 0,
    mergeMessages: (value: unknown) => merges.push(value),
    mergeEvents: (value: unknown) => merges.push(value),
    isTimelineNearBottom: () => true,
    scrollTimelineToEnd: () => merges.push('scroll')
  }
  const running = execute(name, state)
  state.reviewContextGeneration.value++
  state.session.value = { id: 'S2' }
  response.resolve({ data: { messages: ['old'], events: ['old'] } })
  await running
  assert.deepEqual(merges, [])
}
for (const reject of [false, true]) {
  const response = deferred<{ data: string }>()
  const state = {
    args: [],
    activeRunId: ref('R1'),
    reviewContextGeneration: ref(0),
    auditView: ref<unknown>(undefined),
    loadedAuditViewSignature: '',
    auditViewSignature: () => 'signature',
    getReviewBAuditViewApi: () => response.promise
  }
  const running = execute('loadAuditView', state)
  state.activeRunId.value = 'R2'
  state.auditView.value = 'new audit'
  if (reject) response.reject(new Error('late failure'))
  else response.resolve({ data: 'old audit' })
  await running
  assert.equal(state.auditView.value, 'new audit')
}
{
  const response = deferred<unknown>()
  const state = {
    args: [],
    activeProjectId: ref('P1'),
    activeNodeId: ref(24),
    reviewContextGeneration: ref(0),
    treeGroups: ref<unknown[]>([]),
    allNodes: ref([]),
    getProjectTreeApi: () => response.promise,
    loadNodeWorkspace: () => {
      throw new Error('must not load old project node')
    }
  }
  const running = execute('loadProjectTree', state)
  state.activeProjectId.value = 'P2'
  state.reviewContextGeneration.value++
  response.resolve({ data: { groups: ['old'], project: { currentNodeId: 16 } } })
  await running
  assert.deepEqual(state.treeGroups.value, [])
  assert.equal(state.activeNodeId.value, 24)
}
console.log(
  'Background reads preserve new context on late workspace, error, messages, events, audit and tree responses'
)

{
  const response = deferred<void>()
  const calls: unknown[][] = []
  const state = {
    args: [],
    workspace: ref<unknown>({ businessBasis: { inspectionItem: 'original task' } }),
    activeProjectId: ref('P1'),
    activeNodeId: ref(24),
    reviewContextGeneration: ref(0),
    route: { query: { reviewRunId: 'R1' } },
    createSessionWithAuthorizationRecovery: async (
      create: (key: string, silent: boolean) => Promise<void>
    ) => {
      await create('first', true)
      await create('retry', false)
    },
    createReviewBSessionApi: async (...args: unknown[]) => {
      calls.push(args)
      await response.promise
    },
    fetchWorkspace: () => {
      throw new Error('old session completion must not reload new workspace')
    }
  }
  const running = execute('ensureSession', state)
  state.activeProjectId.value = 'P2'
  state.activeNodeId.value = 25
  state.reviewContextGeneration.value++
  state.workspace.value = { session: { id: 'NEW-SESSION' } }
  response.resolve()
  await running
  assert.equal(calls.length, 2)
  for (const call of calls)
    assert.deepEqual(call.slice(0, 3), [
      'P1',
      24,
      { currentTask: 'original task', reviewRunId: 'R1' }
    ])
  assert.deepEqual(state.workspace.value, { session: { id: 'NEW-SESSION' } })
}
{
  const merged: unknown[] = []
  const state = {
    args: [false],
    session: ref({ id: 'S1' }),
    reviewContextGeneration: ref(0),
    messages: ref([]),
    events: ref([]),
    listReviewBMessagesApi: async () => ({ data: { messages: ['current message'] } }),
    listReviewBEventsApi: async () => ({ data: { events: ['current event'] } }),
    eventPollCursor: () => 0,
    mergeMessages: (rows: unknown[]) => merged.push(...rows),
    mergeEvents: (rows: unknown[]) => merged.push(...rows),
    isTimelineNearBottom: () => true,
    scrollTimelineToEnd: () => merged.push('scroll')
  }
  await execute('loadSessionData', state)
  assert.deepEqual(merged, ['current message', 'current event', 'scroll'])
}

for (const firstName of ['loadNodeWorkspace', 'refreshLiveState'])
  for (const rejectOld of [false, true]) {
    const old = deferred<unknown>()
    const recent = deferred<unknown>()
    let requests = 0
    const state = {
      args: [false],
      activeProjectId: ref('P'),
      activeRunId: ref('RUN'),
      activeNodeId: ref(24),
      reviewContextGeneration: ref(0),
      workspaceReadSequence: ref(0),
      workspace: ref<unknown>({ id: 'initial' }),
      auditView: ref(undefined),
      reviewOpinion: ref(''),
      nodeLoading: ref(false),
      polling: ref(false),
      pageError: ref(''),
      route: { query: {} },
      fetchWorkspace: () => (++requests === 1 ? old.promise : recent.promise),
      ensureSession: async () => undefined,
      loadSessionData: async () => undefined,
      loadAuditView: async () => undefined,
      updateRouteQuery: async () => undefined,
      getAicheckErrorMessage: () => 'old error'
    }
    const first = execute(firstName, state)
    const second = execute('loadNodeWorkspace', state)
    recent.resolve({ id: 'latest' })
    await second
    state.pageError.value = 'latest message'
    if (rejectOld) old.reject(new Error('late failure'))
    else old.resolve({ id: 'stale' })
    await first
    assert.deepEqual(state.workspace.value, { id: 'latest' })
    assert.equal(state.pageError.value, 'latest message')
    assert.equal(state.nodeLoading.value, false)
  }
for (const rejectOld of [false, true]) {
  const old = deferred<{ data: string }>()
  const recent = deferred<{ data: string }>()
  let requests = 0
  const state = {
    args: [true],
    activeRunId: ref('SAME-RUN'),
    reviewContextGeneration: ref(0),
    auditReadSequence: ref(0),
    auditView: ref<unknown>(undefined),
    loadedAuditViewSignature: '',
    auditViewSignature: () => 'same',
    getReviewBAuditViewApi: () => (++requests === 1 ? old.promise : recent.promise)
  }
  const first = execute('loadAuditView', state)
  const second = execute('loadAuditView', state)
  recent.resolve({ data: 'latest audit' })
  await second
  if (rejectOld) old.reject(new Error('late failure'))
  else old.resolve({ data: 'old audit' })
  await first
  assert.equal(state.auditView.value, 'latest audit')
}
console.log(
  'Latest workspace and audit request wins on same-context reverse completion and late errors'
)
