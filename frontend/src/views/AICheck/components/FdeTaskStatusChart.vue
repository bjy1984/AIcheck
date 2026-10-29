<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElEmpty } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { taskStatusRows } from '../fdeVisualData'
import { getStatusTone } from './status'
const Echart = defineAsyncComponent(() => import('@/components/Echart').then((m) => m.Echart))
const props = defineProps<{
  groups?: Record<string, Record<string, number>>
  statusLabel: (value: unknown) => string
}>()
const aggregateStatusLabels: Record<string, string> = {
  not_started: '未开始',
  in_progress: '处理中',
  needs_attention: '需关注',
  failed: '执行失败',
  failed_to_start: '启动失败',
  completed: '已完成',
  unknown: '状态未知'
}
const labelForStatus = (status: string) =>
  aggregateStatusLabels[status] || props.statusLabel(status)
const router = useRouter()
const rows = computed(() => taskStatusRows(props.groups))
const statuses = computed(() => [
  ...new Set(
    rows.value
      .filter((row) => row.available)
      .flatMap((row) => row.states.filter((state) => state.count > 0).map((state) => state.status))
  )
])
const colors = {
  green: '#15803d',
  blue: '#2563eb',
  orange: '#b45309',
  red: '#b91c1c',
  gray: '#64748b'
}
const option = computed<EChartsOption>(() => ({
  aria: {
    enabled: true,
    description: rows.value
      .map(
        (row) =>
          `${row.label}：${row.available ? row.states.map((state) => `${labelForStatus(state.status)} ${state.count} 个`).join('，') || '暂无任务' : '未取得统计'}`
      )
      .join('；')
  },
  legend: { top: 0, type: 'scroll', textStyle: { color: '#475569' } },
  grid: { left: 12, right: 28, top: 42, bottom: 28, containLabel: true },
  xAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#e2e8f0' } } },
  yAxis: {
    type: 'category',
    inverse: true,
    data: rows.value.map((row) => `${row.label}${row.available ? '' : '（未取得）'}`),
    axisTick: { show: false },
    axisLine: { show: false }
  },
  tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' } },
  series: statuses.value.map((status) => ({
    name: labelForStatus(status),
    type: 'bar',
    stack: 'tasks',
    barMaxWidth: 24,
    itemStyle: { color: colors[getStatusTone(status)] },
    label: {
      show: true,
      formatter: (p: any) => (p.value > 0 ? String(p.value) : ''),
      color: '#fff'
    },
    data: rows.value.map((row) => ({
      value: row.available
        ? (row.states.find((state) => state.status === status)?.count ?? 0)
        : null,
      route: row.route
    }))
  }))
}))
const openSegment = (event: unknown) => {
  const route = (event as { data?: { route?: string } })?.data?.route
  if (route && rows.value.some((row) => row.route === route)) void router.push(route)
}
</script>

<template>
  <section class="task-status-chart" aria-label="任务状态分布">
    <div class="chart-heading"
      ><strong>任务状态分布</strong><span>按任务数统计，点击图条查看对应任务列表。</span></div
    >
    <Echart
      v-if="statuses.length"
      :key="statuses.join('|')"
      :options="option"
      height="220px"
      @chart-click="openSegment"
    />
    <ElEmpty
      v-else
      :description="
        rows.some((row) => row.available) ? '当前没有任务记录。' : '尚未取得完整任务状态统计。'
      "
      :image-size="64"
    />
    <div class="chart-links"
      ><ElButton
        v-for="row in rows"
        :key="row.key"
        text
        type="primary"
        @click="router.push(row.route)"
        >{{ row.label }} · {{ row.available ? `${row.total} 个` : '未取得' }}</ElButton
      ></div
    >
  </section>
</template>

<style scoped>
.task-status-chart {
  margin: 16px 0;
  padding: 20px;
  background: var(--el-bg-color);
  border: 1px solid var(--aicheck-border, #d4deeb);
  border-radius: 12px;
}
.chart-heading {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: baseline;
}
.chart-heading strong {
  font-size: 15px;
}
.chart-heading span {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.chart-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chart-links .el-button {
  margin: 0;
}
</style>
