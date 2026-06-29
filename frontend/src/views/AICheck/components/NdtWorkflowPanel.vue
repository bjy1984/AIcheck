<script setup lang="ts">
import { computed, reactive } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { NdtFeedback, NdtFilm, NdtRecord, NdtReport, ProjectTreeNode } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  node?: ProjectTreeNode
  films: NdtFilm[]
  records: NdtRecord[]
  reports: NdtReport[]
  feedback: NdtFeedback[]
  loading: boolean
  filmError?: string
  recordImportError?: string
  reportUploadError?: string
  submitError?: string
  rectifyError?: string
}>()

const emit = defineEmits<{
  createFilm: [
    payload: {
      filmNo: string
      weldNo: string
      method: NdtFilm['method']
      pipelineNo?: string
      testDate?: string
    }
  ]
  uploadReport: [
    payload: {
      files: Array<{ fileName: string; fileType: string; fileSize: number }>
      relatedFilmIds: string[]
    }
  ]
  importRecords: [
    payload: {
      rows: Array<Partial<NdtRecord>>
    }
  ]
  submitNdt: [payload: { reportIds: string[]; filmIds: string[] }]
  rectifyNdt: [
    payload: {
      rectificationId: string
      description: string
      reportIds: string[]
      filmIds: string[]
    }
  ]
  openReportDetail: [reportId: string]
  openFeedbackDetail: [feedbackId: string]
}>()

const filmForm = reactive({
  filmNo: 'RT-R2-021-01',
  weldNo: 'W-41-RT-021',
  pipelineNo: 'PL-HD-04',
  method: 'RT' as NdtFilm['method'],
  testDate: '2026-06-26'
})

const reportForm = reactive({
  fileName: 'RT检测报告-补充.pdf',
  fileType: 'pdf',
  fileSize: 245760,
  relatedFilmIds: [] as string[]
})

const recordForm = reactive({
  recordNo: 'REC-RT-20260626-003',
  weldNo: 'W-42-RT-022',
  pipelineNo: 'PL-HD-04',
  method: 'RT' as NdtFilm['method'],
  result: '合格' as NdtRecord['result']
})

const rectificationForm = reactive({
  rectificationId: '',
  description: '已补充底片包索引和检测记录页码，请复审。'
})

const pendingReports = computed(() =>
  props.reports.filter((report) => ['草稿', '待提交', '需补正'].includes(report.status))
)
const pendingFilms = computed(() =>
  props.films.filter((film) => ['草稿', '待提交', '需补正'].includes(film.status))
)
const openFeedback = computed(() => props.feedback.filter((item) => item.status === '待反馈'))
const defaultFeedback = computed(() => openFeedback.value[0])
const selectedRectificationId = computed(
  () => rectificationForm.rectificationId || defaultFeedback.value?.id || ''
)
const sampledRecords = computed(() =>
  props.records.filter((record) => record.sampleStatus !== '未抽查')
)

const handleCreateFilm = () => {
  emit('createFilm', {
    filmNo: filmForm.filmNo.trim(),
    weldNo: filmForm.weldNo.trim(),
    pipelineNo: filmForm.pipelineNo.trim(),
    method: filmForm.method,
    testDate: filmForm.testDate
  })
}

const handleUploadReport = () => {
  emit('uploadReport', {
    files: [
      {
        fileName: reportForm.fileName.trim(),
        fileType: reportForm.fileType,
        fileSize: Number(reportForm.fileSize) || 1024
      }
    ],
    relatedFilmIds: reportForm.relatedFilmIds
  })
}

const handleImportRecords = () => {
  emit('importRecords', {
    rows: [
      {
        recordNo: recordForm.recordNo.trim(),
        weldNo: recordForm.weldNo.trim(),
        pipelineNo: recordForm.pipelineNo.trim(),
        method: recordForm.method,
        result: recordForm.result,
        sampleStatus: '已抽查',
        conclusion: '导入记录已进入监检抽查样本。'
      }
    ]
  })
}

const handleSubmitNdt = () => {
  emit('submitNdt', {
    reportIds: pendingReports.value.map((report) => report.id),
    filmIds: pendingFilms.value.map((film) => film.id)
  })
}

const handleRectifyNdt = () => {
  const feedback = props.feedback.find((item) => item.id === selectedRectificationId.value)
  emit('rectifyNdt', {
    rectificationId: selectedRectificationId.value,
    description: rectificationForm.description.trim(),
    reportIds: feedback?.relatedReportIds || pendingReports.value.map((report) => report.id),
    filmIds: feedback?.relatedFilmIds || pendingFilms.value.map((film) => film.id)
  })
}
</script>

<template>
  <ElCard shadow="never" class="panel ndt-panel">
    <template #header>
      <div class="panel-header">
        <div>
          <span>无损检测流程</span>
          <div class="panel-subtitle"
            >节点 {{ node?.nodeId || 40 }} · {{ node?.name || '无损检测记录、报告' }}</div
          >
        </div>
        <ElTag type="info" effect="plain">节点 40/41/42</ElTag>
      </div>
    </template>

    <div class="ndt-metrics">
      <div>
        <span>底片编号</span>
        <strong>{{ films.length }}</strong>
      </div>
      <div>
        <span>检测报告</span>
        <strong>{{ reports.length }}</strong>
      </div>
      <div>
        <span>检测记录</span>
        <strong>{{ records.length }}</strong>
      </div>
      <div>
        <span>已抽查</span>
        <strong>{{ sampledRecords.length }}</strong>
      </div>
    </div>

    <div class="section-title">新增底片编号</div>
    <ElAlert
      v-if="filmError"
      class="ndt-film-error"
      type="error"
      title="底片编号新增失败"
      :closable="false"
      show-icon
    >
      <div class="ndt-error-content">
        <span>{{ filmError }}</span>
        <ElButton link type="primary" :loading="loading" @click="handleCreateFilm">
          重试新增底片
        </ElButton>
      </div>
    </ElAlert>
    <ElForm label-position="top" class="inline-form">
      <ElFormItem label="底片编号">
        <ElInput v-model="filmForm.filmNo" />
      </ElFormItem>
      <ElFormItem label="焊口编号">
        <ElInput v-model="filmForm.weldNo" />
      </ElFormItem>
      <ElFormItem label="方法">
        <ElSelect v-model="filmForm.method">
          <ElOption label="RT" value="RT" />
          <ElOption label="UT" value="UT" />
          <ElOption label="MT" value="MT" />
          <ElOption label="PT" value="PT" />
        </ElSelect>
      </ElFormItem>
      <ElButton type="primary" :loading="loading" @click="handleCreateFilm">新增底片</ElButton>
    </ElForm>

    <ElTable :data="films" border height="160">
      <ElTableColumn prop="filmNo" label="底片编号" min-width="140" show-overflow-tooltip />
      <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
      <ElTableColumn prop="method" label="方法" width="70" />
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </ElTag>
        </template>
      </ElTableColumn>
    </ElTable>

    <div class="section-title">检测记录导入</div>
    <ElAlert
      v-if="recordImportError"
      class="ndt-record-import-error"
      type="error"
      title="检测记录导入失败"
      :closable="false"
      show-icon
    >
      <div class="ndt-error-content">
        <span>{{ recordImportError }}</span>
        <ElButton link type="primary" :loading="loading" @click="handleImportRecords">
          重试导入记录
        </ElButton>
      </div>
    </ElAlert>
    <ElForm label-position="top" class="record-form">
      <ElFormItem label="记录编号">
        <ElInput v-model="recordForm.recordNo" />
      </ElFormItem>
      <ElFormItem label="焊口编号">
        <ElInput v-model="recordForm.weldNo" />
      </ElFormItem>
      <ElFormItem label="方法">
        <ElSelect v-model="recordForm.method">
          <ElOption label="RT" value="RT" />
          <ElOption label="UT" value="UT" />
          <ElOption label="MT" value="MT" />
          <ElOption label="PT" value="PT" />
        </ElSelect>
      </ElFormItem>
      <ElButton type="primary" plain :loading="loading" @click="handleImportRecords">
        导入检测记录
      </ElButton>
    </ElForm>

    <ElTable :data="records" border height="150">
      <ElTableColumn prop="recordNo" label="记录编号" min-width="150" show-overflow-tooltip />
      <ElTableColumn prop="weldNo" label="焊口" min-width="120" show-overflow-tooltip />
      <ElTableColumn prop="method" label="方法" width="70" />
      <ElTableColumn label="抽查" width="96">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.sampleStatus)" size="small" effect="plain">
            {{ row.sampleStatus }}
          </ElTag>
        </template>
      </ElTableColumn>
    </ElTable>

    <div class="section-title">检测报告上传</div>
    <ElAlert
      v-if="reportUploadError"
      class="ndt-report-upload-error"
      type="error"
      title="检测报告上传会话创建失败"
      :closable="false"
      show-icon
    >
      <div class="ndt-error-content">
        <span>{{ reportUploadError }}</span>
        <ElButton link type="primary" :loading="loading" @click="handleUploadReport">
          重试上传会话
        </ElButton>
      </div>
    </ElAlert>
    <ElForm label-position="top" class="report-form">
      <ElFormItem label="报告文件名">
        <ElInput v-model="reportForm.fileName" />
      </ElFormItem>
      <ElFormItem label="关联底片">
        <ElSelect v-model="reportForm.relatedFilmIds" multiple collapse-tags collapse-tags-tooltip>
          <ElOption
            v-for="film in films"
            :key="film.id"
            :label="`${film.filmNo} / ${film.weldNo}`"
            :value="film.id"
          />
        </ElSelect>
      </ElFormItem>
      <ElButton type="primary" plain :loading="loading" @click="handleUploadReport">
        创建报告上传会话
      </ElButton>
    </ElForm>

    <ElTable class="ndt-report-table" :data="reports" border height="160">
      <ElTableColumn prop="reportNo" label="报告编号" min-width="150" show-overflow-tooltip />
      <ElTableColumn prop="method" label="方法" width="70" />
      <ElTableColumn prop="conclusion" label="结论" min-width="160" show-overflow-tooltip />
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="74" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="emit('openReportDetail', row.id)">详情</ElButton>
        </template>
      </ElTableColumn>
    </ElTable>

    <div class="ndt-actions">
      <span>待提交报告 {{ pendingReports.length }} 份，底片 {{ pendingFilms.length }} 个</span>
      <ElButton
        type="primary"
        :disabled="!pendingReports.length"
        :loading="loading"
        @click="handleSubmitNdt"
      >
        提交检测资料
      </ElButton>
    </div>
    <ElAlert
      v-if="submitError"
      class="ndt-submit-error"
      type="error"
      title="无损检测资料提交失败"
      :closable="false"
      show-icon
    >
      <div class="ndt-error-content">
        <span>{{ submitError }}</span>
        <ElButton link type="primary" :loading="loading" @click="handleSubmitNdt">
          重试提交
        </ElButton>
      </div>
    </ElAlert>

    <div class="section-title">监检反馈</div>
    <ElTable v-if="feedback.length" :data="feedback" border height="150">
      <ElTableColumn prop="title" label="反馈事项" min-width="190" show-overflow-tooltip />
      <ElTableColumn prop="deadline" label="期限" width="150" />
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
            {{ row.status }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="74" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="emit('openFeedbackDetail', row.id)">详情</ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    <ElEmpty v-else description="暂无监检反馈" class="compact-empty" />

    <ElForm label-position="top" class="rectify-form">
      <ElFormItem label="补正反馈">
        <ElSelect v-model="rectificationForm.rectificationId">
          <ElOption
            v-for="item in openFeedback"
            :key="item.id"
            :label="item.title"
            :value="item.id"
          />
        </ElSelect>
      </ElFormItem>
      <ElFormItem label="反馈说明">
        <ElInput
          v-model="rectificationForm.description"
          type="textarea"
          :rows="2"
          maxlength="240"
          show-word-limit
        />
      </ElFormItem>
      <ElAlert
        v-if="rectifyError"
        class="ndt-rectify-error"
        type="error"
        title="无损检测补正反馈提交失败"
        :closable="false"
        show-icon
      >
        <div class="ndt-error-content">
          <span>{{ rectifyError }}</span>
          <ElButton link type="primary" :loading="loading" @click="handleRectifyNdt">
            重试补正反馈
          </ElButton>
        </div>
      </ElAlert>
      <ElButton
        type="warning"
        plain
        :disabled="!openFeedback.length"
        :loading="loading"
        @click="handleRectifyNdt"
      >
        提交补正反馈
      </ElButton>
    </ElForm>
  </ElCard>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.ndt-panel {
  margin-bottom: 16px;
}

.panel-header {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  font-weight: 700;
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 400;
  color: #667085;
}

.ndt-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.ndt-metrics div {
  padding: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.ndt-metrics span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.ndt-metrics strong {
  color: #1f2937;
}

.section-title {
  margin: 14px 0 8px;
  font-size: 14px;
  font-weight: 700;
}

.ndt-film-error,
.ndt-record-import-error,
.ndt-report-upload-error,
.ndt-submit-error,
.ndt-rectify-error {
  margin-bottom: 10px;
}

.ndt-submit-error,
.ndt-rectify-error {
  margin-top: 10px;
}

.ndt-error-content {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  line-height: 1.6;
}

.ndt-error-content span {
  overflow-wrap: anywhere;
}

.inline-form,
.report-form,
.record-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  align-items: end;
}

.inline-form :deep(.el-button),
.record-form :deep(.el-button) {
  grid-column: 1 / -1;
  min-height: 36px;
  margin-left: 0;
}

.report-form,
.rectify-form {
  grid-template-columns: 1fr;
}

.report-form :deep(.el-button),
.rectify-form :deep(.el-button) {
  min-height: 36px;
  margin-left: 0;
}

.ndt-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.ndt-actions span {
  color: #667085;
}

.rectify-form {
  display: grid;
  gap: 10px;
  align-items: end;
  margin-top: 12px;
}

.compact-empty {
  padding: 8px 0;
}

@media (width <= 768px) {
  .ndt-metrics,
  .inline-form,
  .report-form,
  .record-form,
  .rectify-form {
    grid-template-columns: 1fr;
  }

  .ndt-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .ndt-error-content {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
