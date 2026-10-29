<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { ElEmpty, ElSegmented, ElTable, ElTableColumn } from 'element-plus'
import type { EChartsOption } from 'echarts'
import type { FdeOcrQualityPayload } from '@/api/aicheck'
import { measuredCountRows, measuredScore } from '../fdeVisualData'
import { reportedCount, reportedNumber } from '../fdeReportedData'
import { friendlyFieldLabel } from './auditLabels'

const Echart = defineAsyncComponent(() => import('@/components/Echart').then((m) => m.Echart))
const props = defineProps<{
  quality: FdeOcrQualityPayload | null
  scenarios: Array<Record<string, unknown>>
  issueLabel: (value: unknown) => string
}>()
const dimension = ref('flags')
const sourceRows = computed(() =>
  dimension.value === 'flags'
    ? props.quality?.fieldLevel?.qualityFlagCounts
    : props.quality?.fieldLevel?.missingRequiredFieldBreakdown
)
const rows = computed(() =>
  measuredCountRows(sourceRows.value || [], dimension.value === 'flags' ? 'flag' : 'fieldCode').map(
    (row) => ({
      ...row,
      label: dimension.value === 'flags' ? props.issueLabel(row.key) : friendlyFieldLabel(row.key)
    })
  )
)
const displayRows = computed(() => rows.value.slice(0, 10))
const option = computed<EChartsOption>(() => ({
  aria: {
    enabled: true,
    description: `${dimension.value === 'flags' ? 'OCR 质量标记' : '缺失必填字段'}发生次数。${displayRows.value.map((row) => `${row.label} ${row.count} 次`).join('；')}`
  },
  grid: { left: 12, right: 36, top: 12, bottom: 30, containLabel: true },
  xAxis: {
    type: 'value',
    minInterval: 1,
    name: '次数',
    nameLocation: 'middle',
    nameGap: 22,
    splitLine: { lineStyle: { color: '#e2e8f0' } }
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: displayRows.value.map((row) => row.label),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { width: 170, overflow: 'break', color: '#475569' }
  },
  tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' } },
  series: [
    {
      type: 'bar',
      name: '发生次数',
      data: displayRows.value.map((row) => row.count),
      barMaxWidth: 20,
      itemStyle: { color: '#b45309' },
      label: { show: true, position: 'right', color: '#334155' }
    }
  ]
}))
const scoreLabel = (value: unknown) => {
  const score = measuredScore(value, 'ratio')
  return score === null ? '未取得' : `${Math.round(score * 10) / 10}/100`
}
const passRate = (row: Record<string, unknown>) => {
  const total = reportedNumber(row.total)
  const passed = reportedNumber(row.passed)
  return total && passed !== null && passed <= total
    ? `${Math.round((passed / total) * 1000) / 10}%`
    : '无有效样本'
}
</script>

<template>
  <div class="ocr-quality-charts">
    <ElSegmented
      v-model="dimension"
      :options="[
        { label: '质量标记', value: 'flags' },
        { label: '缺失必填字段', value: 'missing' }
      ]"
      aria-label="OCR 问题统计口径"
    />
    <p class="chart-caption"
      >{{
        dimension === 'flags'
          ? '按质量标记发生次数排序，同一字段可有多个标记。'
          : '按必填字段缺失次数排序。'
      }}{{ rows.length > 10 ? '展示次数最多的 10 类。' : '' }}</p
    >
    <Echart
      v-if="rows.some((row) => row.count > 0)"
      :key="dimension"
      :options="option"
      :height="Math.max(180, displayRows.length * 44 + 50)"
    />
    <ElEmpty
      v-else
      :description="
        sourceRows === undefined
          ? '尚未取得此项统计，请刷新或检查解析结果。'
          : '当前统计未发现此类问题。'
      "
      :image-size="64"
    />
    <details v-if="rows.length" class="chart-data">
      <summary>查看全部统计数据</summary>
      <ElTable :data="rows" size="small"
        ><ElTableColumn prop="label" label="问题" min-width="180" /><ElTableColumn
          prop="count"
          label="发生次数"
          width="100"
      /></ElTable>
    </details>
    <template v-if="scenarios.length">
      <h3>场景评估实测</h3>
      <ElTable :data="scenarios" size="small">
        <ElTableColumn prop="scenario" label="场景" min-width="120" />
        <ElTableColumn label="样本数" width="90"
          ><template #default="{ row }">{{ reportedCount(row.total) }}</template></ElTableColumn
        >
        <ElTableColumn label="平均分" width="100"
          ><template #default="{ row }">{{ scoreLabel(row.averageScore) }}</template></ElTableColumn
        >
        <ElTableColumn label="通过率" min-width="110"
          ><template #default="{ row }">{{ passRate(row) }}</template></ElTableColumn
        >
        <ElTableColumn label="阈值未达标" width="110"
          ><template #default="{ row }">{{
            reportedCount(row.thresholdFailureCount)
          }}</template></ElTableColumn
        >
      </ElTable>
    </template>
  </div>
</template>

<style scoped>
.ocr-quality-charts {
  min-width: 0;
}
.chart-caption {
  margin: 12px 0 4px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
.chart-data {
  margin-top: 12px;
}
.chart-data summary {
  cursor: pointer;
  color: var(--el-color-primary);
  font-size: 13px;
  padding: 8px 0;
}
.chart-data summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
h3 {
  font-size: 14px;
  margin: 24px 0 10px;
}
</style>
