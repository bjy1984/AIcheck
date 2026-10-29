import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { computed, ref } from 'vue'

const require = createRequire(import.meta.url)
const ts = require('typescript') as typeof import('typescript')
const { parse } = require('vue/compiler-sfc')
const consoleTemplate = parse(readFileSync(new URL('./FdeConsole.vue', import.meta.url), 'utf8'))
  .descriptor.template.ast
const elements = (node: any): any[] => [
  ...(node.type === 1 ? [node] : []),
  ...(node.children || []).flatMap(elements)
]
const runPane = elements(consoleTemplate).find(
  (node) =>
    node.tag === 'ElTabPane' &&
    node.props.some((prop: any) => prop.name === 'name' && prop.value?.content === 'runs')
)
assert.ok(runPane, 'inspect the actual AI Run pane')
const runElements = elements(runPane)
for (const source of [
  'reviewReasoningTraceRows',
  'reviewLineageRows',
  'normalizedReviewQualityRows',
  'normalizedReviewHumanCorrectionRows'
]) {
  assert.equal(
    runElements.filter(
      (node) =>
        node.tag === 'ElTable' &&
        node.props.some((prop: any) => prop.arg?.content === 'data' && prop.exp?.content === source)
    ).length,
    1,
    `AI Run audit evidence must remain available exactly once: ${source}`
  )
}
for (const action of ['createReviewDiagnosticFeedback', 'requestRawAccess', 'replayFirstRun']) {
  assert.ok(
    runElements.some((node) =>
      node.props.some((prop: any) => prop.name === 'on' && prop.exp?.content === action)
    ),
    `deduplication must preserve the audit action: ${action}`
  )
}
const declarations = (file: string, names: string[]) => {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8')
  const script = source.split('<script setup lang="ts">')[1].split('</script>')[0]
  const ast = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true)
  const selected = ast.statements.filter(
    (statement) =>
      ts.isVariableStatement(statement) &&
      statement.declarationList.declarations.some((decl) => names.includes(decl.name.getText(ast)))
  )
  assert.equal(selected.length, names.length, 'exercise declarations from the production component')
  return ts.transpileModule(selected.map((statement) => statement.getText(ast)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None }
  }).outputText
}

const route = ref('dashboard')
const summaryContext = {
  computed,
  isFdeRoute: (...keys: string[]) => keys.includes(route.value),
  dashboard: ref({
    totals: { projects: 2, reviewRuns: 3, aiRuns: 7, openBlockers: 1, pendingApprovals: 4 }
  }),
  fdeBlockerTotal: ref(1),
  reviewRuns: ref([{}, {}]),
  reviewGraphNodes: ref([{}]),
  reviewArtifactSummary: ref({ validationFailures: 3 }),
  selectedReviewTemporal: ref({ eventCount: 4 }),
  reviewGraphTimeline: ref([]),
  ocrRuns: ref([{}]),
  ocrAnnotationRows: ref([{}, {}]),
  latestOcrEvalCaseTotal: ref(0),
  latestOcrEvalOk: ref(false),
  ocr100Scorecard: ref(null as null | { score: number; targetScore: number }),
  recordNumber: (record: Record<string, unknown>, key: string) => Number(record[key] || 0)
}
const summary = new Function(
  ...Object.keys(summaryContext),
  declarations('./FdeConsole.vue', ['fdeTopStats', 'fdeShellRightCards']) +
    ';return {top:fdeTopStats,cards:fdeShellRightCards}'
)(...Object.values(summaryContext))
assert.equal(summary.top.value.length, 4)
assert.deepEqual(
  summary.cards.value.map((card: any) => card.title),
  ['全局运行概况']
)
for (const key of [
  'projects',
  'ai-runs',
  'feedback',
  'evaluation',
  'capability-bundles',
  'releases',
  'business-packs',
  'standards-vectorization',
  'security',
  'incidents',
  'costs',
  'acceptance'
]) {
  route.value = key
  assert.deepEqual(summary.top.value, [], `${key}: no unrelated global counters`)
  assert.deepEqual(summary.cards.value, [], `${key}: no unrelated OCR/Agent summaries`)
}
route.value = 'review-runs'
assert.deepEqual(summary.top.value, [])
assert.deepEqual(
  summary.cards.value.map((card: any) => card.title),
  ['当前审查编排']
)
assert.equal(summary.cards.value[0].rows.find((row: any) => row.label === '校验失败').value, '3')
route.value = 'ocr-quality'
assert.deepEqual(
  summary.cards.value.map((card: any) => card.title),
  ['OCR 质量与标注']
)
assert.equal(
  summary.cards.value[0].rows.find((row: any) => row.label === '最近评测').value,
  '暂无评测'
)
summaryContext.latestOcrEvalCaseTotal.value = 5
summaryContext.latestOcrEvalOk.value = true
assert.equal(summary.cards.value[0].rows.find((row: any) => row.label === '最近评测').value, '通过')
route.value = 'costs'
assert.deepEqual(summary.cards.value, [], 'moving away clears the previously selected OCR summary')

const blockerScrolls: unknown[] = []
const blockerRoutes: unknown[] = []
const currentFdePath = ref('/fde/dashboard')
const blockerClick = new Function(
  'currentFdePath',
  'document',
  'router',
  declarations('./FdeConsole.vue', ['handleFdeTopStatClick']) + ';return handleFdeTopStatClick'
)(
  currentFdePath,
  {
    getElementById: (id: string) => {
      assert.equal(id, 'fde-blocker-center')
      return { scrollIntoView: (options: unknown) => blockerScrolls.push(options) }
    }
  },
  { push: (target: unknown) => blockerRoutes.push(target) }
)
blockerClick({ key: 'projects' })
assert.equal(blockerScrolls.length, 0)
blockerClick({ key: 'blockers' })
assert.equal(
  blockerScrolls.length,
  1,
  'the remaining dashboard counter must reach the blocker list'
)
assert.equal(blockerRoutes.length, 0)
currentFdePath.value = '/fde/costs'
blockerClick({ key: 'blockers' })
assert.deepEqual(blockerRoutes, [{ path: '/fde/dashboard', query: { focus: 'blockers' } }])

const feedbackRows = [{ id: 'feedback-1', comment: '待处理意见' }]
const loadTriage = async (listFails: boolean, metricsFails: boolean) => {
  const context = {
    loading: ref(false),
    error: ref('previous error'),
    metricsError: ref('previous metrics error'),
    rows: ref([{ id: 'previous', comment: 'existing' }]),
    metrics: ref<unknown>({ previous: true }),
    metricsMarkdown: ref('previous metrics'),
    drafts: ref<Record<string, unknown>>({ previous: {} }),
    listFdeFeedbackApi: async () => {
      if (listFails) throw new Error('feedback unavailable')
      return { data: feedbackRows }
    },
    getFdeFeedbackMetricsApi: async () => {
      if (metricsFails) throw new Error('metrics unavailable')
      return { data: { metrics: { adoptionRate: 0.5 }, markdown: 'current quality metrics' } }
    }
  }
  const load = new Function(
    ...Object.keys(context),
    declarations('./FdeFeedbackTriage.vue', ['load']) + ';return load'
  )(...Object.values(context))
  await load()
  assert.equal(context.loading.value, false)
  return context
}
const optionalFailure = await loadTriage(false, true)
assert.deepEqual(
  optionalFailure.rows.value,
  feedbackRows,
  'quality analytics cannot make feedback work disappear'
)
assert.equal(optionalFailure.error.value, '')
assert.equal(optionalFailure.metrics.value, null, 'stale analytics are not shown as current')
assert.equal(optionalFailure.metricsMarkdown.value, '')
assert.match(optionalFailure.metricsError.value, /反馈归因不受影响/)
const listFailure = await loadTriage(true, false)
assert.equal(
  listFailure.error.value,
  'feedback unavailable',
  'a real feedback loading error remains actionable'
)
assert.equal(listFailure.metricsError.value, '')
const recovered = await loadTriage(false, false)
assert.deepEqual(recovered.rows.value, feedbackRows)
assert.equal(recovered.error.value, '')
assert.equal(recovered.metricsError.value, '')
assert.equal(recovered.metricsMarkdown.value, 'current quality metrics')
console.log('FDE role-scoped summaries and optional analytics regressions passed')
