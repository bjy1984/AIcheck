import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { createTechnicalTextFormatter } from './fdeTechnicalText'
import { completedTaskCount, reportedCount, reportedNumber } from './fdeReportedData'
import {
  statusLabelMap as sharedStatusLabelMap,
  techTermLabels as sharedTechTermLabels
} from './components/auditLabels'
const require = createRequire(import.meta.url)
const esbuild = require(
  require.resolve('esbuild', { paths: [dirname(require.resolve('vite/package.json'))] })
)
const source = readFileSync(new URL('./FdeConsole.vue', import.meta.url), 'utf8')
const formatterSource = source.slice(
  source.indexOf('const statusLabelMap:'),
  source.indexOf('const friendlyReferenceLabel')
)
const format = new Function(
  'sharedStatusLabelMap',
  'sharedTechTermLabels',
  'getAicheckRoleLabel',
  'createTechnicalTextFormatter',
  esbuild.transformSync(formatterSource, { loader: 'ts' }).code + ';return friendlyTechnicalText'
)(
  sharedStatusLabelMap,
  sharedTechTermLabels,
  (value: string) => value,
  createTechnicalTextFormatter
)
const diagnosis = 'API 服务未配置 OCR 服务地址（AICHECK_OCR_BASE_URL）。'
assert.equal(
  format(diagnosis),
  diagnosis,
  'preserve already-readable API diagnosis and config identifier'
)
assert.equal(format('AICHECK_OCR_BASE_URL'), 'OCR 服务地址（AICHECK_OCR_BASE_URL）')
assert.equal(format(format('AICHECK_OCR_BASE_URL')), format('AICHECK_OCR_BASE_URL'))
assert.equal(
  format('Check AICHECK_OCR_BASE_URL: not configured'),
  '请检查 OCR 服务地址（AICHECK_OCR_BASE_URL）: 未配置'
)
assert.equal(
  format('OCR 运行体检接口（/internal/ocr/doctor）'),
  'OCR 运行体检接口（/internal/ocr/doctor）'
)
assert.equal(format('prefixAICHECK_OCR_BASE_URL_suffix'), 'prefixAICHECK_OCR_BASE_URL_suffix')
assert.equal(format('EV-CA-001 / job-123 / unknown_config'), 'EV-CA-001 / job-123 / unknown_config')
assert.equal(format(null), '-')
assert.equal(
  completedTaskCount([
    { status: 'completed' },
    { status: 'not_completed' },
    { status: 'failed' },
    { parseStatus: '已识别' },
    {}
  ]),
  2
)
const capabilitySource = source.slice(
  source.indexOf('const projectAuditCapabilityRows ='),
  source.indexOf('const projectAuditRecentTaskRows =')
)
const capability = (overrides: Record<string, unknown> = {}) => {
  const data: Record<string, unknown> = {
    projectAuditDocuments: [],
    projectAuditMetrics: {},
    projectAuditOcrJobs: [],
    projectAuditBlockers: [],
    projectAuditAnnotationTasks: [],
    projectAuditVectorIssueRows: [],
    projectAuditPageIndexIssueRows: [],
    projectAuditPageIndexTraceRows: [],
    projectAuditPageIndexCards: [],
    projectAuditReviewRuns: [],
    reviewGraphNodes: [],
    projectAuditLangGraphIssueRows: [],
    projectAuditEvaluationGateRows: [],
    projectAuditEvaluationIssueRows: [],
    ...overrides
  }
  const refs = Object.fromEntries(Object.entries(data).map(([key, value]) => [key, { value }]))
  const context = {
    ...refs,
    completedTaskCount,
    reportedCount,
    reportedNumber,
    computed: (fn: () => unknown) => ({ value: fn() })
  }
  return new Function(
    ...Object.keys(context),
    esbuild.transformSync(capabilitySource, { loader: 'ts' }).code +
      ';return {rows:projectAuditCapabilityRows.value,summary:projectAuditCapabilitySummary.value}'
  )(...Object.values(context))
}
const empty = capability()
assert.equal(
  empty.summary,
  '待补齐',
  'zero known blockers is not evidence that capabilities are ready'
)
assert.ok(empty.rows.every((row: any) => row.tone !== 'green'))
assert.equal(empty.rows[1].value, '未提供/0 份', 'do not invent a denominator of one document')
assert.equal(empty.rows[3].status, '暂无审查任务')
assert.ok(
  empty.rows.every((row: any) => !('score' in row)),
  'no hard-coded health scores'
)
const ready = {
  projectAuditDocuments: [{}],
  projectAuditMetrics: { vectorizedDocuments: 1, pageIndexNodes: 2, lowConfidenceFields: 0 },
  projectAuditOcrJobs: [{ status: 'completed' }],
  projectAuditReviewRuns: [{ status: 'succeeded' }],
  reviewGraphNodes: [{}],
  projectAuditEvaluationGateRows: [{ passed: true }]
}
assert.equal(capability(ready).summary, '当前检查通过')
assert.notEqual(
  capability({ ...ready, projectAuditOcrJobs: [{ status: 'running' }] }).rows[0].tone,
  'green'
)
assert.notEqual(
  capability({ ...ready, projectAuditReviewRuns: [{ status: 'failed' }] }).rows[3].tone,
  'green'
)
assert.notEqual(
  capability({ ...ready, projectAuditMetrics: { vectorizedDocuments: 1, pageIndexNodes: 2 } })
    .rows[0].tone,
  'green'
)
assert.notEqual(
  capability({ ...ready, projectAuditEvaluationGateRows: [{ passed: null }] }).rows[4].tone,
  'green'
)
assert.equal(capability({ ...ready, projectAuditVectorIssueRows: [{}] }).summary, '需处理')
console.log('FDE diagnostic text and observed capability status regressions passed')
