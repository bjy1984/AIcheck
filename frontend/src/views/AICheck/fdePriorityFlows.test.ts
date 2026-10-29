import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'

const require = createRequire(import.meta.url)
const esbuild = require(
  require.resolve('esbuild', { paths: [dirname(require.resolve('vite/package.json'))] })
)
const source = readFileSync(new URL('./FdeConsole.vue', import.meta.url), 'utf8')
const handler = (name: string, context: Record<string, unknown>) => {
  const start = source.indexOf(`const ${name} = `)
  assert.ok(start >= 0, name)
  const end = source.indexOf('\n}', start) + 2
  const code = esbuild.transformSync(source.slice(start, end), { loader: 'ts' }).code
  return new Function(...Object.keys(context), `${code}; return ${name}`)(...Object.values(context))
}
const ref = <T>(value: T) => ({ value })
const failures: string[] = []
for (const [route, required] of [
  ['releases', 'evaluation'],
  ['evaluation', 'bundles'],
  ['security', 'costGovernance']
]) {
  try {
    const ctx = {
      currentFdeRouteKey: ref(route),
      routeDependencyError: ref(''),
      dashboard: ref(null),
      releases: ref(null),
      evaluation: ref(null),
      bundles: ref(null),
      costGovernance: ref(null),
      selectedReleaseId: ref(''),
      firstReleaseId: ref(''),
      activeReleaseId: ref(''),
      firstEvaluationRunId: ref(''),
      selectedEvaluationReport: ref(null),
      accessGrants: ref([]),
      auditEvents: ref([]),
      maskingPolicies: ref([]),
      getFdeDashboardApi: async () => ({ data: {} }),
      listFdeReleasesApi: async () => ({ data: { plans: [] } }),
      getFdeEvaluationSetsApi: async () => ({ data: { sets: [], reports: [{ id: 'report-B' }] } }),
      getFdeCapabilityBundlesApi: async () => ({ data: { bundles: [{ id: 'bundle-B' }] } }),
      getFdeCostBudgetsApi: async () => ({ data: { exports: [{ id: 'export-B' }] } }),
      listFdeAccessGrantsApi: async () => ({ data: [] }),
      getFdeAuditEventsApi: async () => ({ data: { events: [] } }),
      getFdeMaskingPoliciesApi: async () => ({ data: [] })
    }
    await handler('loadFdeRoutePageData', ctx)()
    assert.ok((ctx as any)[required].value, `${route} must load ${required} on a fresh visit`)
  } catch (error) {
    failures.push(String(error))
  }
}
try {
  const empty = ref('')
  const ctx = {
    activeRunId: empty,
    activeReviewRunId: empty,
    activeFeedbackId: empty,
    firstEvaluationSetId: empty,
    activeBusinessPackId: empty,
    firstBudgetId: ref('budget-A'),
    selectedOcrRun: ref(null),
    firstBundleId: empty,
    routeDependencyError: ref(''),
    governanceActionMode: ref(''),
    governanceActionForm: ref<any>({}),
    governanceActionDialogVisible: ref(false),
    costGovernance: ref({
      budgets: [
        { id: 'budget-A', monthlyBudget: 1000 },
        { id: 'budget-B', monthlyBudget: 0 }
      ]
    }),
    toRecord: (x: any) => x || {},
    ElMessage: { warning: () => {} }
  }
  handler('openGovernanceAction', ctx)('budget-change', 'budget-B')
  assert.equal(
    ctx.governanceActionForm.value.targetId,
    'budget-B',
    'must operate on the clicked budget'
  )
  assert.equal(ctx.governanceActionForm.value.proposedLimit, 0, 'zero is a valid current budget')
} catch (error) {
  failures.push(String(error))
}
for (const cancelled of [true, false]) {
  try {
    const calls: string[] = []
    const ctx = {
      ElMessageBox: {
        confirm: async (message: string) => {
          assert.ok(message.includes('export-B'))
          if (cancelled) throw new Error('cancel')
        }
      },
      actionLoading: ref(false),
      expireFdeDataExportApi: async (id: string) => {
        calls.push(id)
      },
      ElMessage: { success() {}, error() {} },
      getAicheckErrorMessage: () => 'failed',
      loadData: async () => {}
    }
    await handler('expireDataExport', ctx)({ id: 'export-B', status: 'approved' })
    assert.deepEqual(calls, cancelled ? [] : ['export-B'])
    assert.equal(ctx.actionLoading.value, false)
  } catch (error) {
    failures.push(String(error))
  }
}
assert.deepEqual(failures, [])
console.log('FDE direct-entry and explicit-target regressions passed')
