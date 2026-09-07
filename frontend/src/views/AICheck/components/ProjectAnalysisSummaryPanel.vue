<script setup lang="ts">
import { computed } from 'vue'
import { ElButton } from 'element-plus'

import type { ProjectAnalysisSummary } from '@/api/aicheck/projectAnalysis'

import {
  projectAnalysisPriorityRows,
  projectAnalysisSummaryTotals
} from '../projectAnalysisSummary'
import AuditStatusTag from './AuditStatusTag.vue'

const props = defineProps<{
  summary?: ProjectAnalysisSummary | null
  loading?: boolean
}>()

const emit = defineEmits<{
  selectNode: [nodeId: number]
}>()

const rows = computed(() => projectAnalysisPriorityRows(props.summary))
const totals = computed(() => projectAnalysisSummaryTotals(rows.value))
</script>

<template>
  <section class="pa-summary" aria-label="工程级分析结果">
    <div class="pa-summary-head">
      <strong>工程级结果</strong>
      <span class="pa-summary-note">AI 建议，未经人工确认</span>
    </div>
    <p v-if="loading" class="pa-summary-empty">正在汇总各节点结果…</p>
    <p v-else-if="!rows.length" class="pa-summary-empty">本次分析没有落库的节点结果。</p>
    <template v-else>
      <dl class="pa-summary-totals">
        <div class="is-red">
          <dt>需处理</dt>
          <dd>{{ totals.needAction }}</dd>
        </div>
        <div class="is-orange">
          <dt>待确认</dt>
          <dd>{{ totals.confirm }}</dd>
        </div>
        <div class="is-gray">
          <dt>证据不足</dt>
          <dd>{{ totals.insufficient }}</dd>
        </div>
        <div class="is-green">
          <dt>未见问题</dt>
          <dd>{{ totals.clean }}</dd>
        </div>
      </dl>
      <div v-if="summary?.commonRisks?.length" class="pa-summary-risks">
        <strong>共性风险</strong>
        <ul>
          <li v-for="risk in summary.commonRisks.slice(0, 3)" :key="risk.title">
            <span>{{ risk.title }}</span>
            <small>{{ risk.nodeCount }} 个节点：{{ risk.nodeIds.join('、') }}</small>
          </li>
        </ul>
      </div>
      <div class="pa-summary-table-wrap">
        <table class="pa-summary-table">
          <thead>
            <tr>
              <th>节点</th>
              <th>结论</th>
              <th>最高严重度</th>
              <th>需处理</th>
              <th>待确认</th>
              <th>证据不足</th>
              <th>建议动作</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.nodeId">
              <td class="pa-node">
                <span class="pa-node-id">{{ row.nodeId }}</span>
                <span class="pa-node-name" :title="row.headline">{{ row.nodeName }}</span>
                <small v-if="row.partialCoverage" class="pa-partial">部分分片未完成</small>
              </td>
              <td>
                <AuditStatusTag :tone="row.tone" round>{{ row.verdict }}</AuditStatusTag>
              </td>
              <td>{{ row.maxSeverityLabel || '—' }}</td>
              <td class="pa-num">{{ row.needAction }}</td>
              <td class="pa-num">{{ row.confirm }}</td>
              <td class="pa-num">{{ row.insufficient }}</td>
              <td>{{ row.action }}</td>
              <td>
                <ElButton size="small" text bg @click="emit('selectNode', row.nodeId)">
                  查看节点
                </ElButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.pa-summary {
  display: grid;
  padding: 12px 0 0;
  border-top: 1px solid var(--el-border-color-lighter);
  gap: 10px;
}

.pa-summary-head {
  display: flex;
  gap: 10px;
  align-items: center;
}

.pa-summary-note {
  padding: 2px 8px;
  font-size: 12px;
  color: #7a4b00;
  background: #fff5e0;
  border: 1px solid #f3dfb0;
  border-radius: 999px;
}

.pa-summary-empty {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.pa-summary-totals {
  display: grid;
  margin: 0;
  gap: 8px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.pa-summary-totals > div {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 6px 10px;
  background: #f8fafc;
  border-radius: 8px;
}

.pa-summary-totals dt {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.pa-summary-totals dd {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.pa-summary-totals > .is-red dd {
  color: var(--el-color-danger);
}

.pa-summary-totals > .is-orange dd {
  color: var(--el-color-warning);
}

.pa-summary-totals > .is-green dd {
  color: var(--el-color-success);
}

.pa-summary-risks strong {
  font-size: 13px;
}

.pa-summary-risks ul {
  display: grid;
  padding: 0;
  margin: 6px 0 0;
  list-style: none;
  gap: 4px;
}

.pa-summary-risks li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
}

.pa-summary-risks small {
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.pa-summary-table-wrap {
  overflow-x: auto;
}

.pa-summary-table {
  width: 100%;
  font-size: 13px;
  border-collapse: collapse;
}

.pa-summary-table th,
.pa-summary-table td {
  padding: 6px 8px;
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.pa-summary-table th {
  font-weight: 600;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.pa-node {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.pa-node-id {
  display: inline-grid;
  height: 22px;
  min-width: 22px;
  padding: 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  background: #9db5d3;
  border-radius: 11px;
  place-items: center;
}

.pa-node-name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pa-partial {
  color: var(--el-color-danger);
}

.pa-num {
  font-variant-numeric: tabular-nums;
  text-align: right;
}
</style>
