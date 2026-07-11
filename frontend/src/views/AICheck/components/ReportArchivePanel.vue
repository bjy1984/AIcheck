<script setup lang="ts">
import { computed, reactive } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElOption,
  ElPopconfirm,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type {
  ActionCode,
  ArchiveItem,
  ExportTask,
  NodePackagePayload,
  ReportVersion,
  RoleCode
} from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  role: RoleCode
  actions: ActionCode[]
  packageData?: NodePackagePayload
  reports: ReportVersion[]
  archiveItems: ArchiveItem[]
  recentExportTasks: ExportTask[]
  generateDisabledReason?: string
  loading: boolean
}>()

const emit = defineEmits<{
  generateReport: [
    payload: {
      includeEvidence: boolean
      reportScope: ReportVersion['scope']
    }
  ]
  exportReport: [reportId: string]
  archiveReport: [reportId: string]
  previewReport: [reportId: string]
  openReportDetail: [reportId: string]
  openArchiveItemDetail: [itemId: string]
  downloadArchiveItem: [item: ArchiveItem]
  downloadArchivePackage: []
  downloadEvidencePackage: [payload?: { reportId?: string }]
  openExportTask: [exportId: string]
}>()

const form = reactive({
  includeEvidence: true,
  reportScope: 'currentNode' as ReportVersion['scope']
})

const actionSet = computed(() => new Set(props.actions))
const showGenerateForm = computed(
  () =>
    props.role === 'inspection' &&
    actionSet.value.has('report:generate') &&
    Boolean(props.packageData)
)
const canGenerate = computed(() => showGenerateForm.value && !props.generateDisabledReason)
const readonlyLabel = computed(() => (props.role === 'owner' ? '建设方只读' : '报告复核'))
const latestReport = computed(() => props.reports[0])
const canReadonlyDownload = computed(() => actionSet.value.has('archive:download'))
const canExport = (report: ReportVersion) =>
  props.role === 'inspection' &&
  actionSet.value.has('report:export') &&
  ['复核完成', '已签发'].includes(report.status)
const canPreviewReport = (report: ReportVersion) =>
  actionSet.value.has('report:view') || Boolean(report.previewUrl)
const canOpenDetail = (report: ReportVersion) =>
  actionSet.value.has('report:view') || report.actions.includes('report:view')
const canArchive = (report: ReportVersion) =>
  props.role === 'inspection' &&
  actionSet.value.has('report:archive') &&
  !archiveBlockedReason(report)
const archiveBlockedReason = (report: ReportVersion) => {
  if (report.status === '已归档') return '报告已归档。'
  if (!['已签发', '复核完成'].includes(report.status)) {
    return '报告归档前必须完成复核或签发。'
  }
  if (!report.evidenceValidation) return '等待报告证据校验状态。'
  if (!report.evidenceValidation.passed) return '报告证据校验未通过，不能归档。'
  if (
    !props.recentExportTasks.some((task) => task.reportId === report.id && task.status === '可下载')
  ) {
    return '请先导出当前报告版本，再执行归档。'
  }
  return ''
}
const exportTypeLabel = (type: ExportTask['exportType']) => {
  const labelMap: Record<ExportTask['exportType'], string> = {
    report: '报告导出',
    'archive-package': '归档包',
    'evidence-package': '证据包',
    document: '资料下载',
    'config-package': '配置包'
  }
  return labelMap[type]
}

const handleGenerate = () => {
  emit('generateReport', {
    includeEvidence: form.includeEvidence,
    reportScope: form.reportScope
  })
}
</script>

<template>
  <ElCard shadow="never" class="panel report-panel">
    <template #header>
      <div class="panel-header">
        <span>报告与归档</span>
        <ElTag :type="role === 'owner' ? 'success' : 'info'" effect="plain">
          {{ readonlyLabel }}
        </ElTag>
      </div>
    </template>

    <ElForm v-if="showGenerateForm" label-position="top" class="report-form">
      <ElFormItem label="生成范围">
        <ElSelect v-model="form.reportScope">
          <ElOption label="当前节点" value="currentNode" />
          <ElOption label="项目范围" value="project" />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="证据链">
        <ElCheckbox v-model="form.includeEvidence">包含证据链引用</ElCheckbox>
      </ElFormItem>
      <ElButton
        type="primary"
        :disabled="!canGenerate"
        :loading="loading"
        :title="generateDisabledReason"
        @click="handleGenerate"
      >
        生成报告草稿
      </ElButton>
    </ElForm>
    <ElAlert
      v-if="showGenerateForm && generateDisabledReason"
      class="report-gate-alert"
      type="warning"
      :title="generateDisabledReason"
      :closable="false"
      show-icon
    />

    <div v-if="!showGenerateForm && latestReport" class="latest-report">
      <span>最新报告</span>
      <strong>{{ latestReport.reportNo }} · {{ latestReport.versionNo }}</strong>
      <ElTag :type="getStatusTagType(latestReport.status)" size="small" effect="plain">
        {{ latestReport.status }}
      </ElTag>
    </div>

    <ElEmpty
      v-if="!showGenerateForm && !latestReport"
      description="暂无报告版本"
      class="compact-empty"
    />

    <div class="section-title">报告版本</div>
    <ElTable :data="reports" border height="160">
      <ElTableColumn prop="reportNo" label="报告编号" min-width="150" show-overflow-tooltip />
      <ElTableColumn prop="versionNo" label="版本" width="74" />
      <ElTableColumn label="状态" width="92">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="250">
        <template #default="{ row }">
          <ElButton
            link
            type="primary"
            :disabled="!canOpenDetail(row)"
            @click="emit('openReportDetail', row.id)"
          >
            详情
          </ElButton>
          <ElButton
            link
            type="primary"
            :disabled="!canPreviewReport(row)"
            @click="emit('previewReport', row.id)"
          >
            预览
          </ElButton>
          <ElButton
            link
            type="primary"
            :disabled="!canExport(row)"
            :loading="loading"
            @click="emit('exportReport', row.id)"
          >
            导出
          </ElButton>
          <ElPopconfirm
            title="确认归档该报告？归档后项目进入只读状态。"
            width="220"
            @confirm="emit('archiveReport', row.id)"
          >
            <template #reference>
              <ElButton link type="warning" :disabled="!canArchive(row)" :loading="loading">
                <span :title="archiveBlockedReason(row)">归档</span>
              </ElButton>
            </template>
          </ElPopconfirm>
        </template>
      </ElTableColumn>
    </ElTable>

    <div v-if="canReadonlyDownload" class="package-actions">
      <ElButton :loading="loading" @click="emit('downloadArchivePackage')">归档包</ElButton>
      <ElButton
        :loading="loading"
        @click="emit('downloadEvidencePackage', { reportId: latestReport?.id })"
      >
        证据包
      </ElButton>
    </div>

    <div v-if="recentExportTasks.length" class="recent-export-card">
      <div class="recent-export-head">
        <span>最近只读导出</span>
        <ElTag size="small" effect="plain">{{ recentExportTasks.length }} 项</ElTag>
      </div>
      <div v-for="task in recentExportTasks.slice(0, 3)" :key="task.id" class="recent-export-row">
        <div>
          <strong>{{ task.fileName }}</strong>
          <span>{{ exportTypeLabel(task.exportType) }} · {{ task.status }}</span>
        </div>
        <ElButton link type="primary" @click="emit('openExportTask', task.id)">详情</ElButton>
      </div>
    </div>

    <div class="section-title">归档资料</div>
    <ElTable :data="archiveItems" border height="170">
      <ElTableColumn prop="name" label="名称" min-width="180" show-overflow-tooltip />
      <ElTableColumn prop="type" label="类型" width="78" />
      <ElTableColumn prop="nodeId" label="节点" width="74" />
      <ElTableColumn prop="updatedAt" label="更新时间" width="150" />
      <ElTableColumn label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="emit('openArchiveItemDetail', row.id)">
            详情
          </ElButton>
          <ElButton
            link
            type="primary"
            :disabled="!row.downloadUrl || !canReadonlyDownload"
            @click="emit('downloadArchiveItem', row)"
          >
            下载
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.report-panel {
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  font-weight: 600;
}

.report-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  align-items: end;
  margin-bottom: 12px;
}

.package-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.package-actions :deep(.el-button) {
  min-height: 36px;
  margin-left: 0;
}

.recent-export-card {
  padding: 10px;
  margin-bottom: 12px;
  background: #f8fbff;
  border: 1px solid #d7e5f8;
  border-radius: 8px;
}

.recent-export-head,
.recent-export-row {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.recent-export-head {
  margin-bottom: 8px;
  font-weight: 600;
  color: #26364e;
}

.recent-export-row {
  padding-top: 8px;
  border-top: 1px solid #e3edf8;
}

.recent-export-row + .recent-export-row {
  margin-top: 8px;
}

.recent-export-row div {
  min-width: 0;
}

.recent-export-row strong,
.recent-export-row span {
  display: block;
}

.recent-export-row strong {
  overflow: hidden;
  font-size: 13px;
  color: #1f2937;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-export-row span {
  margin-top: 3px;
  font-size: 12px;
  color: #667085;
}

.latest-report {
  display: grid;
  padding: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.latest-report span {
  font-size: 12px;
  color: #667085;
}

.latest-report strong {
  grid-column: 1 / 2;
  color: #1f2937;
}

.section-title {
  margin: 14px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.report-gate-alert {
  margin-bottom: 12px;
}

.compact-empty {
  padding: 8px 0;
}

@media (width <= 768px) {
  .report-form,
  .latest-report,
  .package-actions {
    grid-template-columns: 1fr;
  }
}
</style>
