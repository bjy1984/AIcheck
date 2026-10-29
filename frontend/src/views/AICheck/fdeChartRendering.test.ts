import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { computed, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { measuredCountRows, measuredDuration } from './fdeVisualData'
import { friendlyFieldLabel } from './components/auditLabels'
import { getStatusTone } from './components/status'

const require = createRequire(import.meta.url)
const ts = require('typescript') as typeof import('typescript')
const productionDeclarations = (path: string, names: string[]) => {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = source.split('<script setup lang="ts">')[1].split('</script>')[0]
  const ast = ts.createSourceFile(path, script, ts.ScriptTarget.Latest, true)
  const selected = ast.statements.filter(
    (statement) =>
      ts.isVariableStatement(statement) &&
      statement.declarationList.declarations.some((decl) => names.includes(decl.name.getText(ast)))
  )
  assert.equal(
    selected.length,
    names.length,
    'all chart declarations must come from the production component'
  )
  return ts.transpileModule(selected.map((statement) => statement.getText(ast)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None }
  }).outputText
}

echarts.use([BarChart, AriaComponent, GridComponent, TooltipComponent, SVGRenderer])
const render = (option: echarts.EChartsCoreOption) => {
  const chart = echarts.init(null, undefined, {
    renderer: 'svg',
    ssr: true,
    width: 900,
    height: 300
  })
  try {
    chart.setOption({ ...option, animation: false })
    return chart.renderToSVGString()
  } finally {
    chart.dispose()
  }
}

// Explicit synthetic measurements, supplied through the real component props.
const props = {
  quality: {
    fieldLevel: {
      qualityFlagCounts: [
        { flag: '低置信度', count: 2 },
        { flag: '缺少证据', count: 7 }
      ],
      missingRequiredFieldBreakdown: [
        { fieldCode: 'certificateNo', count: 1 },
        { fieldCode: 'expiryDate', count: 4 }
      ]
    }
  },
  issueLabel: (value: unknown) => String(value)
}
const ocr = new Function(
  'computed',
  'ref',
  'props',
  'measuredCountRows',
  'friendlyFieldLabel',
  productionDeclarations('./components/FdeOcrQualityCharts.vue', [
    'dimension',
    'sourceRows',
    'rows',
    'displayRows',
    'option'
  ]) + ';return {dimension,rows,option}'
)(computed, ref, props, measuredCountRows, friendlyFieldLabel)
assert.deepEqual(
  ocr.option.value.series[0].data,
  [7, 2],
  'positive quality counts are sorted by frequency'
)
assert.deepEqual(ocr.option.value.yAxis.data, ['缺少证据', '低置信度'])
const qualitySvg = render(ocr.option.value)
assert.match(qualitySvg, /缺少证据/)
assert.match(qualitySvg, />7<\/text>/)
assert.match(qualitySvg, />2<\/text>/)
ocr.dimension.value = 'missing'
assert.deepEqual(
  ocr.option.value.series[0].data,
  [4, 1],
  'switching scope replaces the data rather than combining counts'
)
assert.equal(ocr.rows.value.length, 2)
const fieldsSvg = render(ocr.option.value)
assert.match(fieldsSvg, />4<\/text>/)
assert.match(fieldsSvg, />1<\/text>/)

const context = {
  computed,
  reviewGraphTimeline: {
    value: [
      { stepName: '已完成步骤', durationMs: 0, status: 'completed' },
      { stepName: '缺失步骤', status: 'unknown' }
    ]
  },
  langGraphFlowGroups: { value: [] },
  measuredDuration,
  toRecord: (value: unknown) => value,
  friendlyTechLabel: String,
  friendlyStatus: String,
  friendlyTaskQueueLabel: String,
  shortText: String,
  langGraphStatusTone: (value: unknown) => getStatusTone(String(value))
}
const timeline = new Function(
  ...Object.keys(context),
  productionDeclarations('./FdeConsole.vue', [
    'reviewTimelineChartRows',
    'langGraphToneColor',
    'reviewTimelineEchartOption'
  ]) + ';return {rows:reviewTimelineChartRows.value,option:reviewTimelineEchartOption.value}'
)(...Object.values(context))
assert.deepEqual(
  timeline.option.series[0].data.map((row: { value: number | null }) => row.value),
  [0, null]
)
assert.equal(timeline.option.series[0].data[0].label.formatter, '0ms')
assert.match(timeline.option.yAxis.data[1], /未取得耗时/)
assert.doesNotMatch(render(timeline.option), /80ms/)
console.log(
  'Production OCR chart options render both synthetic count scopes; timeline keeps zero and unknown distinct.'
)
