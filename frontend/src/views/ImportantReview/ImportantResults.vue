<script setup lang="ts">
import { ElAlert, ElButton, ElEmpty, ElTable, ElTableColumn, ElTag } from 'element-plus'
import type {
  ImportantRun,
  ImportantEvidence,
  ImportantOutcome
} from '@/api/aicheck/importantReview'
import { friendlyCheckCode, friendlyCheckReason } from '@/views/AICheck/components/auditLabels'
import { verdict, tagType, displayValue, executionStatus } from './presentation'
import ReviewAutomationLimitations from '@/views/AIReviewB/components/ReviewAutomationLimitations.vue'
const props = defineProps<{ run: ImportantRun }>()
const emit = defineEmits<{ rule: []; evidence: [item: ImportantEvidence, label: string] }>()
const rows = () =>
  [...props.run.atomicCheckOutcomes].sort(
    (a, b) => Number(a.result === 'passed') - Number(b.result === 'passed')
  )
const references = (row: ImportantOutcome) => {
  const unique = new Map<string, ImportantEvidence>()
  for (const fact of row.facts || [])
    for (const item of fact.evidence || []) {
      if (item.documentId || item.documentVersionId)
        unique.set(JSON.stringify([item.documentId, item.documentVersionId, item.pageNo]), item)
    }
  return [...unique.values()]
}
const filename = (item: ImportantEvidence) =>
  item.fileName ||
  props.run.documents.find(
    (file) => file.versionId === item.documentVersionId || file.documentId === item.documentId
  )?.fileName ||
  '查看原文'
</script>
<template>
  <div class="important-outcomes">
    <ReviewAutomationLimitations :items="run.automationLimitations || []" />
    <ElAlert v-if="run.errorMessage" :title="run.errorMessage" type="error" :closable="false" />
    <ElTable v-if="run.atomicCheckOutcomes.length" :data="rows()" border stripe>
      <ElTableColumn type="index" label="序号" width="55" />
      <ElTableColumn prop="name" label="核查项" min-width="170" />
      <ElTableColumn label="业务结论" width="125"
        ><template #default="{ row }"
          ><ElTag :type="tagType(verdict(row.result))">{{ verdict(row.result) }}</ElTag></template
        ></ElTableColumn
      >
      <ElTableColumn label="问题说明／逐项比较" min-width="270"
        ><template #default="{ row }"
          ><p v-if="row.reason">{{ friendlyCheckReason(row.reason) }}</p
          ><div v-for="(check, index) in row.checks || []" :key="index" class="check"
            ><span>{{ friendlyCheckCode(check.code) }}</span
            ><div>实际：{{ displayValue(check.actual) }}</div
            ><div>要求：{{ displayValue(check.expected) }}</div></div
          ><span v-if="!row.reason && !row.checks?.length"
            >详见本次证据及辅助审查意见</span
          ></template
        ></ElTableColumn
      >
      <ElTableColumn label="对应规则" width="110"
        ><template #default
          ><ElButton link type="primary" @click="emit('rule')">查看规则</ElButton></template
        ></ElTableColumn
      >
      <ElTableColumn label="相关资料" min-width="180"
        ><template #default="{ row }"
          ><div v-for="(item, index) in references(row)" :key="index"
            ><ElButton link type="primary" @click="emit('evidence', item, row.name)"
              >{{ filename(item) }}{{ item.pageNo ? ` · 第 ${item.pageNo} 页` : '' }}</ElButton
            ></div
          ><span v-if="!references(row).length">未返回可定位的原文引用</span></template
        ></ElTableColumn
      >
      <ElTableColumn label="下一步" min-width="140"
        ><template #default="{ row }">{{
          row.result === 'passed'
            ? '人工复核后确认'
            : row.result === 'failed'
              ? '核对原文及判定依据，确认处理意见'
              : '核查缺失事实，补充资料或人工确认'
        }}</template></ElTableColumn
      >
    </ElTable>
    <ElEmpty
      v-else
      :description="
        executionStatus(run.status) === '已完成'
          ? '未返回结构化核查留痕，请查看辅助意见；不能据此判为符合'
          : '任务尚未返回核查结果'
      "
      :image-size="65"
    />
    <details v-if="run.findingDrafts.length" open class="findings"
      ><summary>辅助审查意见（{{ run.findingDrafts.length }} 项）</summary
      ><article v-for="(finding, index) in run.findingDrafts" :key="finding.id || index"
        ><h4>{{ finding.title }}</h4
        ><p>{{ finding.description }}</p
        ><ElButton
          v-for="(item, refIndex) in finding.evidenceRefs || []"
          :key="refIndex"
          link
          type="primary"
          @click="emit('evidence', item, finding.title)"
          >{{ filename(item) }}{{ item.pageNo ? ` · 第 ${item.pageNo} 页` : '' }}</ElButton
        ></article
      ></details
    >
    <p v-if="run.summary">{{ run.summary }}</p>
  </div>
</template>
<style scoped>
.important-outcomes :deep(.el-table__cell) {
  vertical-align: top;
}

.check {
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  overflow-wrap: anywhere;
}

.check div {
  color: var(--el-text-color-regular);
}

.findings {
  margin-top: 16px;
}

.findings summary {
  color: var(--el-color-primary);
  cursor: pointer;
}

.findings article {
  padding: 12px;
  margin-top: 8px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}

.findings p {
  white-space: pre-wrap;
}

.important-outcomes :deep(.el-button) {
  height: auto;
  text-align: left;
  white-space: normal;
}
</style>
