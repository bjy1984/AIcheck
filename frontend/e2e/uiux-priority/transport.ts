// Isolated synthetic fixtures. No call can reach a real service.
type Config = { url: string; data?: any; params?: any; responseType?: string }
export const mutations: Array<Config> = []
const report = {
  id: 'REPORT-READY',
  evaluationRunId: 'EVAL-READY',
  status: 'passed',
  caseSummary: { cases: 10, casePassRate: 1 }
}
const budget = {
  grants: [],
  exports: [
    { id: 'EXPORT-A', targetId: 'RUN-A', status: 'approved' },
    { id: 'EXPORT-B', targetId: 'RUN-B', status: 'expired' }
  ],
  budgets: [
    { id: 'BUDGET-A', scopeId: '项目甲', monthlyBudget: 1000, currency: 'CNY' },
    { id: 'BUDGET-B', scopeId: '项目乙', monthlyBudget: 0, currency: 'CNY' }
  ],
  usage: { runCount: 3, estimatedPrice: 20 },
  changeRequests: []
}
const get = async (c: Config) => {
  const u = c.url
  if (
    new URLSearchParams(window.location.search).get('fail') === 'exports' &&
    u.endsWith('/cost-budgets')
  )
    throw new Error('合成导出服务暂不可用')
  let data: any = {}
  if (u.endsWith('/dashboard'))
    data = {
      summary: {},
      cards: [],
      metrics: {},
      boundaries: [],
      cost: { tokenEstimate: 0 },
      releaseStatus: { bundles: 1, pendingApprovals: 0 }
    }
  else if (u.endsWith('/meta'))
    data = {
      viewer: {
        role: 'fde',
        grantedActions: [
          'fde:dashboard:view',
          'fde:feedback:view',
          'fde:evaluation:view',
          'fde:business-pack:view',
          'fde:release:view',
          'fde:security:manage',
          'fde:cost:manage'
        ]
      },
      boundaries: []
    }
  else if (u.endsWith('/blockers')) data = { items: [], summary: { total: 0 } }
  else if (u.endsWith('/evaluation-sets'))
    data = {
      sets: [
        { id: 'SET-A', name: '验收样本集', setType: 'regression', caseCount: 10, status: 'ready' }
      ],
      reports: [report],
      runs: [{ id: 'EVAL-READY' }]
    }
  else if (u.includes('/evaluation-runs/') || u.includes('/evaluation-reports/'))
    data = {
      report,
      metrics: [],
      caseResults: [
        {
          evaluationCaseId: 'CASE-A',
          status: 'passed',
          evidencePassed: true,
          retrievalPassed: true
        }
      ]
    }
  else if (u.endsWith('/capability-bundles'))
    data = { bundles: [{ id: 'BUNDLE-A', name: '管道资料组合', status: 'validated' }] }
  else if (u.endsWith('/releases'))
    data = {
      plans: [
        { id: 'RELEASE-A', name: '待发布版本', status: 'draft', rollbackPlanId: 'ROLLBACK-A' }
      ]
    }
  else if (u.includes('/impact'))
    data = { summary: {}, blockers: [], impactedProjects: [], impact: {} }
  else if (u.endsWith('/cost-budgets')) data = budget
  else if (u.endsWith('/access-grants')) data = [{ id: 'GRANT-A' }]
  else if (u.endsWith('/masking-policies')) data = []
  else if (u.endsWith('/audit-events'))
    data = {
      events: [{ createdAt: '2026-10-28', action: '审计记录加载成功', objectType: 'DataExport' }]
    }
  else if (u.endsWith('/blind-review/tasks'))
    data = {
      tasks: [
        { id: 'BRT-A', projectId: 'PROJECT-A', nodeId: 24, status: 'open', batchId: 'BATCH-A' }
      ],
      rubberStampIndex: { value: null, sampleSize: 0 }
    }
  else if (u.endsWith('/materials'))
    data = {
      taskId: 'BRT-A',
      scopeSource: 'run_snapshot',
      materials: [
        {
          documentId: 'DOC-A',
          documentVersionId: 'VERSION-ORIGINAL',
          fileName: '审查时原件.svg',
          fileType: 'image/svg+xml',
          originalUrl: '/synthetic-original',
          downloadUrl: '/synthetic-original'
        }
      ],
      unavailableCount: 0,
      unavailableReason: ''
    }
  else if (u === '/synthetic-original')
    return {
      data: new Blob(
        [
          '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="250"><rect width="600" height="250" fill="white"/><text x="30" y="80" font-size="24">Original source version — no AI conclusions</text></svg>'
        ],
        { type: 'image/svg+xml' }
      )
    }
  else if (u.includes('/tasks')) data = { items: [], total: 0 }
  else data = { items: [], total: 0 }
  return { code: 0, data }
}
const post = async (c: Config) => {
  mutations.push(c)
  if (c.url.endsWith('/evaluation-runs'))
    return { code: 0, data: { report: { ...report, id: 'REPORT-NEW' }, caseResults: [] } }
  if (c.url.endsWith('/expire')) {
    const item = budget.exports.find((x) => c.url.includes(x.id))
    if (item) item.status = 'expired'
  }
  if (c.url.endsWith('/propose-change')) {
    ;(budget.changeRequests as any[]).push({
      id: 'CHANGE-A',
      status: 'pending_approval',
      ...c.data
    })
  }
  return { code: 0, data: {} }
}
export default { get, post, patch: post, put: post, delete: post }
