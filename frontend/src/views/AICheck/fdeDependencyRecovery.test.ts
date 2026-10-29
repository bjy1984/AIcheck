import assert from 'node:assert/strict'
import { handler, ref } from './workflowTestHarness'

// A supplemental endpoint outage must not erase independently loaded primary records.
for (const route of ['security', 'releases', 'evaluation']) {
  const fail = async () => {
    throw new Error('supplement unavailable')
  }
  const state = {
    currentFdeRouteKey: ref(route),
    routeDependencyError: ref(''),
    dashboard: ref<any>(null),
    releases: ref<any>(null),
    evaluation: ref<any>(null),
    bundles: ref<any>({ bundles: [{ id: 'stale' }] }),
    costGovernance: ref<any>({ exports: [{ id: 'stale' }] }),
    selectedReleaseId: ref(''),
    firstReleaseId: ref(''),
    activeReleaseId: ref(''),
    firstEvaluationRunId: ref(''),
    selectedEvaluationReport: ref(null),
    accessGrants: ref<any[]>([]),
    auditEvents: ref<any[]>([]),
    maskingPolicies: ref<any[]>([]),
    getFdeDashboardApi: async () => ({ data: { id: 'dashboard' } }),
    listFdeReleasesApi: async () => ({ data: { plans: [{ id: 'plan' }] } }),
    getFdeEvaluationSetsApi:
      route === 'releases' ? fail : async () => ({ data: { sets: [{ id: 'set' }] } }),
    getFdeCapabilityBundlesApi: fail,
    getFdeCostBudgetsApi: fail,
    listFdeAccessGrantsApi: async () => ({ data: [{ id: 'grant' }] }),
    getFdeAuditEventsApi: async () => ({ data: { events: [{ id: 'audit' }] } }),
    getFdeMaskingPoliciesApi: async () => ({ data: [{ id: 'masking' }] })
  }
  await handler('./FdeConsole.vue', 'loadFdeRoutePageData', state)()
  assert.ok(state.routeDependencyError.value, 'failure must remain visible and retryable')
  if (route === 'security') {
    assert.equal(state.accessGrants.value[0].id, 'grant')
    assert.equal(state.auditEvents.value[0].id, 'audit')
    assert.equal(state.maskingPolicies.value[0].id, 'masking')
    assert.equal(state.costGovernance.value, null, 'do not present a stale export target')
  } else if (route === 'releases') {
    assert.equal(state.releases.value.plans[0].id, 'plan')
    assert.equal(state.evaluation.value, null)
  } else {
    assert.equal(state.evaluation.value.sets[0].id, 'set')
    assert.equal(state.bundles.value, null)
  }
}

// HEIC previews can be converted to PNG. Download must request original attachment bytes.
const calls: string[] = []
const clicks: string[] = []
const state = {
  materialRequest: 1,
  materialDownloading: ref(false),
  materialDownloadError: ref(''),
  getDocumentOriginalBlobApi: async (url: string) => {
    calls.push(url)
    return { data: 'original-heic-bytes' }
  },
  URL: {
    createObjectURL: (value: string) => {
      assert.equal(value, 'original-heic-bytes')
      return 'blob:original'
    },
    revokeObjectURL() {}
  },
  document: {
    createElement: () => ({
      href: '',
      download: '',
      click() {
        clicks.push(this.href)
      }
    })
  },
  window: { setTimeout: (callback: () => void) => callback() }
}
await handler(
  './FdeBlindReview.vue',
  'downloadMaterial',
  state
)({
  fileName: 'scan.heic',
  originalUrl: '/version?disposition=inline',
  downloadUrl: '/version?disposition=attachment'
})
assert.deepEqual(calls, ['/version?disposition=attachment'])
assert.deepEqual(clicks, ['blob:original'])
assert.equal(state.materialDownloading.value, false)
console.log('FDE dependency recovery and original-byte download passed')
