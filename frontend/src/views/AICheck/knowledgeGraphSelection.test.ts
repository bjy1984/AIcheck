import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { SVGRenderer } from 'echarts/renderers'

const require = createRequire(import.meta.url)
const ts = require('typescript') as typeof import('typescript')
const source = readFileSync(new URL('./KnowledgeNetwork.vue', import.meta.url), 'utf8')
const script = source.split('<script setup lang="ts">')[1].split('</script>')[0]
const ast = ts.createSourceFile('KnowledgeNetwork.ts', script, ts.ScriptTarget.Latest, true)
const fn = ast.statements.find(
  (statement) =>
    ts.isFunctionDeclaration(statement) && statement.name?.text === 'syncSelectionToChart'
)
assert.ok(fn, 'production selection synchronization must exist')
const js = ts.transpileModule(fn.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None }
}).outputText

echarts.use([GraphChart, SVGRenderer])
const chart = echarts.init(null, undefined, { renderer: 'svg', ssr: true, width: 800, height: 600 })
const allNodes = [
  { id: 'industrial', name: 'Industrial', x: 0, y: 0 },
  { id: 'welding', name: 'Welding', x: 100, y: 0 },
  { id: 'welder', name: 'Welder', x: 200, y: 0 }
]
const visibleNodes = { value: allNodes }
const selectedNodeId = { value: 'industrial' }
const syncSelectionToChart = new Function(
  'chart',
  'visibleNodes',
  'selectedNodeId',
  `${js}; return syncSelectionToChart`
)(chart, visibleNodes, selectedNodeId) as () => void
const selectedNames = () => {
  const series = (chart.getOption().series as Array<{ selectedMap?: Record<string, boolean> }>)[0]
  return Object.entries(series.selectedMap || {})
    .filter(([, selected]) => selected)
    .map(([name]) => name)
}

try {
  chart.setOption({
    animation: false,
    series: [{ type: 'graph', layout: 'none', selectedMode: 'single', data: allNodes, links: [] }]
  })
  syncSelectionToChart()
  assert.deepEqual(selectedNames(), ['Industrial'])

  // Reproduce the real filter flow: hide the selection, then show all nodes again.
  visibleNodes.value = allNodes.slice(1)
  selectedNodeId.value = ''
  chart.setOption({ series: [{ data: visibleNodes.value }] })
  syncSelectionToChart()
  visibleNodes.value = allNodes
  chart.setOption({ series: [{ data: allNodes }] })
  syncSelectionToChart()
  assert.deepEqual(selectedNames(), [], 'clearing a filter must not revive an old canvas selection')

  selectedNodeId.value = 'welder'
  syncSelectionToChart()
  assert.deepEqual(selectedNames(), ['Welder'])
  visibleNodes.value = allNodes.slice(1)
  chart.setOption({ series: [{ data: visibleNodes.value, zoom: 2, center: [30, 40] }] })
  syncSelectionToChart()
  assert.deepEqual(selectedNames(), ['Welder'], 'a visible selection stays selected')
  const series = (chart.getOption().series as Array<{ zoom: number; center: number[] }>)[0]
  assert.equal(series.zoom, 2, 'synchronizing selection must not reset zoom')
  assert.deepEqual(series.center, [30, 40], 'synchronizing selection must not reset pan')

  selectedNodeId.value = ''
  syncSelectionToChart()
  assert.deepEqual(
    selectedNames(),
    [],
    'clearing details must clear the actual ECharts selected state'
  )
  console.log('Knowledge graph real ECharts selection synchronization passed')
} finally {
  chart.dispose()
}
