import assert from 'node:assert/strict'

import { createAutoReviewApi } from './autoReview'

const calls: Array<{ method: string; config: Record<string, unknown> }> = []
const adapter = {
  get: async (config: Record<string, unknown>) => {
    calls.push({ method: 'GET', config })
    return { data: {} }
  },
  put: async (config: Record<string, unknown>) => {
    calls.push({ method: 'PUT', config })
    return { data: {} }
  },
  post: async (config: Record<string, unknown>) => {
    calls.push({ method: 'POST', config })
    return { data: {} }
  }
}
const api = createAutoReviewApi(adapter, (options) => ({
  'If-Match': options?.etag || '',
  'Idempotency-Key': options?.idempotencyKey || 'generated'
}))

await api.getProjectAutoReviewPolicyApi('P-1')
await api.getProjectAutoReviewStatusApi('P-1')
await api.listProjectReviewRunsApi('P-1')
await api.getProjectReviewRunApi('P-1', 'PRRUN-1')
await api.updateProjectAutoReviewPolicyApi(
  'P-1',
  {
    enabled: true,
    triggerModes: ['ocr_mounted', 'daily_schedule'],
    dailyTime: '02:00',
    timezone: 'Asia/Shanghai',
    debounceSeconds: 300
  },
  { etag: 'W/"auto-review-policy-r1"', idempotencyKey: 'policy-once' }
)
await api.runProjectAutoReviewApi('P-1', { idempotencyKey: 'run-once' })

assert.deepEqual(
  calls.map(({ method, config }) => [method, config.url]),
  [
    ['GET', '/api/projects/P-1/inspection/auto-review-policy'],
    ['GET', '/api/projects/P-1/inspection/auto-review-status'],
    ['GET', '/api/projects/P-1/inspection/project-review-runs'],
    ['GET', '/api/projects/P-1/inspection/project-review-runs/PRRUN-1'],
    ['PUT', '/api/projects/P-1/inspection/auto-review-policy'],
    ['POST', '/api/projects/P-1/inspection/auto-review/run']
  ]
)
const policyHeaders = calls[4].config.headers as Record<string, string>
assert.equal(policyHeaders['If-Match'], 'W/"auto-review-policy-r1"')
assert.equal(policyHeaders['Idempotency-Key'], 'policy-once')
const runHeaders = calls[5].config.headers as Record<string, string>
assert.equal(runHeaders['Idempotency-Key'], 'run-once')
