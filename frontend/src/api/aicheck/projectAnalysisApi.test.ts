import assert from 'node:assert/strict'

import { createProjectAnalysisApi } from './projectAnalysis'

const calls: Array<{ method: string; config: Record<string, any> }> = []
const adapter = {
  get: async (config: Record<string, any>) => {
    calls.push({ method: 'GET', config })
    return { data: {} }
  },
  post: async (config: Record<string, any>) => {
    calls.push({ method: 'POST', config })
    return { data: {} }
  }
}
const api = createProjectAnalysisApi(adapter, (options) => ({
  'Idempotency-Key': options?.idempotencyKey || 'generated'
}))

await api.getProjectAnalysisPreviewApi('P-1')
await api.createProjectAnalysisRunApi('P-1', 'sha256:snapshot', {
  idempotencyKey: 'run-once'
})
await api.listProjectAnalysisRunsApi('P-1')
await api.getProjectAnalysisRunApi('P-1', 'PARUN-1')
await api.getProjectAnalysisStatusApi('P-1', 'PARUN-1')

assert.deepEqual(
  calls.map(({ method, config }) => [method, config.url]),
  [
    ['GET', '/api/projects/P-1/inspection/full-project-analysis/preview'],
    ['POST', '/api/projects/P-1/inspection/full-project-analysis/runs'],
    ['GET', '/api/projects/P-1/inspection/full-project-analysis/runs'],
    ['GET', '/api/projects/P-1/inspection/full-project-analysis/runs/PARUN-1'],
    ['GET', '/api/projects/P-1/inspection/full-project-analysis/runs/PARUN-1/status']
  ]
)
assert.deepEqual(calls[1].config.data, { snapshotHash: 'sha256:snapshot' })
assert.equal(calls[1].config.headers['Idempotency-Key'], 'run-once')
