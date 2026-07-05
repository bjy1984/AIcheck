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

type NdtMaterialStatus = '已覆盖' | '待上传' | '需补正'

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
const ndtMaterialChecklist = computed(() => {
  const openFeedbackCount = openFeedback.value.length
  const rows: Array<{
    category: string
    requiredItems: string
    uploadedCount: number
    missing: string
    status: NdtMaterialStatus
    nodeRefs: string
  }> = [
    {
      category: '机构与人员资质',
      requiredItems: '无损检测机构核准证、检测人员资格证、执业注册证、项目人员任命',
      uploadedCount: 0,
      missing: '当前接口未返回资质文件，需在无损检测资料库中补充或核验',
      status: '待上传',
      nodeRefs: 'R23、R24、R25'
    },
    {
      category: '检测方案与工艺',
      requiredItems: '无损检测方案、单项检测工艺文件、操作指导书、受控表格',
      uploadedCount: 0,
      missing: '需补充检测方案、工艺文件和操作指导书',
      status: '待上传',
      nodeRefs: 'R23、R27、R28'
    },
    {
      category: '检测设备与校准',
      requiredItems: '检测设备台账、检定/校准报告、设备有效期证明',
      uploadedCount: 0,
      missing: '需补充设备检定或校准证明',
      status: '待上传',
      nodeRefs: 'R26'
    },
    {
      category: '底片与影像资料',
      requiredItems: '底片编号、射线底片或数字影像、底片包索引',
      uploadedCount: props.films.length,
      missing: props.films.length ? '已登记底片，等待监检核验' : '需上传或登记底片编号和影像资料',
      status: props.films.some((film) => film.status === '需补正')
        ? '需补正'
        : props.films.length
          ? '已覆盖'
          : '待上传',
      nodeRefs: 'R28、R53'
    },
    {
      category: '检测记录',
      requiredItems: '无损检测委托单、检测记录、原始记录、抽查样本记录',
      uploadedCount: props.records.length,
      missing: props.records.length ? '已导入检测记录，等待监检核验' : '需导入检测记录和原始记录',
      status: props.records.length ? '已覆盖' : '待上传',
      nodeRefs: 'R28、R29'
    },
    {
      category: '检测报告',
      requiredItems: 'RT/UT/MT/PT 检测报告、检测结论、报告与底片对应关系',
      uploadedCount: props.reports.length,
      missing: props.reports.length ? '已上传检测报告，等待监检核验' : '需上传检测报告',
      status: props.reports.some((report) => report.status === '需补正')
        ? '需补正'
        : props.reports.length
          ? '已覆盖'
          : '待上传',
      nodeRefs: 'R28、R53'
    },
    {
      category: '问题处理闭环',
      requiredItems: '不合格品控制、联络单/意见书、处理反馈、返修后复检报告',
      uploadedCount: openFeedbackCount,
      missing: openFeedbackCount ? `${openFeedbackCount} 项监检反馈待处理` : '暂无待处理反馈',
      status: openFeedbackCount ? '需补正' : '已覆盖',
      nodeRefs: 'R29、R30'
    }
  ]
  return rows.sort((a, b) => {
    const priority: Record<NdtMaterialStatus, number> = { 需补正: 0, 待上传: 1, 已覆盖: 2 }
    return priority[a.status] - priority[b.status]
  })
})
const ndtChecklistSummary = computed(() => ({
  covered: ndtMaterialChecklist.value.filter((item) => item.status === '已覆盖').length,
  pending: ndtMaterialChecklist.value.filter((item) => item.status === '待上传').length,
  correction: ndtMaterialChecklist.value.filter((item) => item.status === '需补正').length,
  total: ndtMaterialChecklist.value.length
}))
const ndtAssetRows = computed(() => [
  ...props.films.map((film) => ({
    id: film.id,
    assetType: '底片编号',
    name: film.filmNo,
    relation: film.weldNo,
    method: film.method,
    status: film.status,
    updatedAt: film.testDate || '-',
    detailId: ''
  })),
  ...props.records.map((record) => ({
    id: record.id,
    assetType: '检测记录',
    name: record.recordNo,
    relation: record.weldNo,
    method: record.method,
    status: record.sampleStatus,
    updatedAt: record.importedAt,
    detailId: ''
  })),
  ...props.reports.map((report) => ({
    id: report.id,
    assetType: '检测报告',
    name: report.reportNo,
    relation: report.relatedFilmIds.length
      ? `${report.relatedFilmIds.length} 个底片`
      : '未关联底片',
    method: report.method,
    status: report.status,
    updatedAt: report.uploadedAt,
    detailId: report.id
  }))
])

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
  <div class="ndt-workspace">
    <ElCard shadow="never" class="panel ndt-panel">
      <template #header>
        <div class="panel-header">
          <div>
            <span>一、无损检测资料库 / 检测资料台账</span>
            <div class="panel-subtitle"
              >无损检测机构负责检测方案、底片、记录、报告和补正资料；节点仅用于业务定位。</div
            >
          </div>
          <ElTag type="primary" effect="plain"> {{ ndtAssetRows.length }} 项资料 </ElTag>
        </div>
      </template>

      <div class="ndt-metrics">
        <div>
          <span>底片编号</span>
          <strong>{{ films.length }}</strong>
        </div>
        <div>
          <span>检测记录</span>
          <strong>{{ records.length }}</strong>
        </div>
        <div>
          <span>检测报告</span>
          <strong>{{ reports.length }}</strong>
        </div>
        <div>
          <span>待补正</span>
          <strong>{{ openFeedback.length }}</strong>
        </div>
      </div>

      <section class="ndt-checklist">
        <div class="ndt-section-head">
          <div>
            <strong>标准资料上传</strong>
            <p>按无损检测单位应提交的资料类别归类，监检节点可在上传或提交后补充关联。</p>
          </div>
          <ElTag type="info" effect="plain">
            {{ ndtChecklistSummary.covered }} / {{ ndtChecklistSummary.total }} 类已有资料
          </ElTag>
        </div>
        <ElTable :data="ndtMaterialChecklist" border height="255">
          <ElTableColumn prop="category" label="资料类别" min-width="150" show-overflow-tooltip />
          <ElTableColumn
            prop="requiredItems"
            label="标准要求资料"
            min-width="260"
            show-overflow-tooltip
          />
          <ElTableColumn label="已上传/登记" width="110">
            <template #default="{ row }">{{ row.uploadedCount }} 项</template>
          </ElTableColumn>
          <ElTableColumn prop="missing" label="缺口/待核验" min-width="260" show-overflow-tooltip />
          <ElTableColumn label="状态" width="110">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="nodeRefs" label="关联规则" width="130" />
        </ElTable>
      </section>

      <section class="ndt-action-grid">
        <div class="ndt-action-box">
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
            <ElButton type="primary" :loading="loading" @click="handleCreateFilm">
              新增底片
            </ElButton>
          </ElForm>
        </div>

        <div class="ndt-action-box">
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
        </div>

        <div class="ndt-action-box">
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
              <ElSelect
                v-model="reportForm.relatedFilmIds"
                multiple
                collapse-tags
                collapse-tags-tooltip
              >
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
        </div>
      </section>

      <section class="ndt-library">
        <div class="ndt-section-head">
          <div>
            <strong>检测资料列表</strong>
            <p>底片、检测记录和检测报告统一在资料库中管理，再提交给监检方审核。</p>
          </div>
          <div class="ndt-actions">
            <span
              >待提交报告 {{ pendingReports.length }} 份，底片 {{ pendingFilms.length }} 个</span
            >
            <ElButton
              type="primary"
              :disabled="!pendingReports.length && !pendingFilms.length"
              :loading="loading"
              @click="handleSubmitNdt"
            >
              提交检测资料
            </ElButton>
          </div>
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
        <ElTable :data="ndtAssetRows" border height="280">
          <ElTableColumn type="index" label="序号" width="72" />
          <ElTableColumn prop="name" label="资料名称/编号" min-width="180" show-overflow-tooltip />
          <ElTableColumn prop="assetType" label="资料类型" width="110" />
          <ElTableColumn prop="method" label="方法" width="80" />
          <ElTableColumn prop="relation" label="关联对象" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="状态" width="110">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="updatedAt" label="更新时间" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <ElButton
                v-if="row.detailId"
                link
                type="primary"
                @click="emit('openReportDetail', row.detailId)"
              >
                查看详情
              </ElButton>
              <span v-else class="muted-action">台账项</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </section>
    </ElCard>

    <ElCard id="ndt-feedback-list" shadow="never" class="panel ndt-panel">
      <template #header>
        <div class="panel-header">
          <div>
            <span>二、监检反馈列表</span>
            <div class="panel-subtitle"
              >按监检退回意见逐项处理，补充报告、底片或检测记录后提交反馈。</div
            >
          </div>
          <ElTag :type="openFeedback.length ? 'warning' : 'success'" effect="plain">
            {{ openFeedback.length }} 项待处理
          </ElTag>
        </div>
      </template>

      <ElTable v-if="feedback.length" :data="feedback" border height="220">
        <ElTableColumn prop="id" label="反馈编号" width="130" />
        <ElTableColumn prop="title" label="反馈事项" min-width="190" show-overflow-tooltip />
        <ElTableColumn prop="description" label="问题说明" min-width="260" show-overflow-tooltip />
        <ElTableColumn prop="deadline" label="期限" width="150" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
              {{ row.status }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="emit('openFeedbackDetail', row.id)"
              >详情</ElButton
            >
            <ElButton
              link
              type="warning"
              :disabled="row.status === '已关闭'"
              @click="handleRectifyNdt"
            >
              提交反馈
            </ElButton>
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
  </div>
</template>

<style scoped>
.panel {
  border-radius: 8px;
}

.ndt-workspace {
  display: grid;
  gap: 12px;
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

.ndt-checklist,
.ndt-library {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.ndt-section-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.ndt-section-head strong {
  font-size: 15px;
  color: #1f2937;
}

.ndt-section-head p {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: #667085;
}

.ndt-action-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.ndt-action-box {
  min-width: 0;
  padding: 12px;
  background: #fbfdff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
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

.muted-action {
  font-size: 13px;
  font-weight: 700;
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
  .ndt-section-head,
  .ndt-action-grid,
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
