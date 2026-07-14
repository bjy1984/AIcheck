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
import type {
  DocumentAsset,
  NdtFeedback,
  NdtFilm,
  NdtSubmissionReadiness,
  NdtRecord,
  NdtReport,
  ProjectTreeNode
} from '@/types/aicheck'
import { getStatusTagType } from './status'
import { buildNdtSubmitBlockers, pendingNdtFilms, pendingNdtReports } from '@/utils/ndtReadiness'

type NdtMaterialStatus = '已覆盖' | '待上传' | '需补正'
type NdtMaterialAction =
  | { key: 'upload'; label: string; category: string }
  | { key: 'rectify'; label: string }
type NdtMaterialChecklistItem = {
  category: string
  requiredItems: string
  uploadedCount: number
  missing: string
  status: NdtMaterialStatus
  nodeRefs: string
  actions: NdtMaterialAction[]
}
type NdtOcrMetadataRow = {
  category: string
  source: string
  fields: string
  status: string
}

const props = defineProps<{
  node?: ProjectTreeNode
  films: NdtFilm[]
  records: NdtRecord[]
  reports: NdtReport[]
  feedback: NdtFeedback[]
  projectFiles: DocumentAsset[]
  loading: boolean
  filmError?: string
  recordImportError?: string
  reportUploadError?: string
  submitError?: string
  ndtReadiness?: NdtSubmissionReadiness
  rectifyError?: string
}>()

const emit = defineEmits<{
  createFilm: [
    payload: {
      filmNo: string
      weldNo: string
      method: NdtFilm['method']
    } & Partial<NdtFilm>
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
  uploadMaterial: [materialCategory: string]
}>()

const rectificationForm = reactive({
  rectificationId: '',
  description: '已补充底片包索引和检测记录页码，请复审。'
})

const pendingReports = computed(() => pendingNdtReports(props.reports))
const pendingFilms = computed(() => pendingNdtFilms(props.films))
const blockerText = (item: { code?: string; message?: string; reportId?: string }) =>
  [item.reportId, item.message || item.code].filter(Boolean).join('：')
const submitBlockers = computed(() =>
  buildNdtSubmitBlockers({
    reports: props.reports,
    films: props.films,
    projectFiles: props.projectFiles,
    readiness: props.ndtReadiness
  })
)
const canSubmitNdt = computed(() => pendingReports.value.length > 0 && !submitBlockers.value.length)
const openFeedback = computed(() => props.feedback.filter((item) => item.status === '待反馈'))
const defaultFeedback = computed(() => openFeedback.value[0])
const selectedRectificationId = computed(
  () => rectificationForm.rectificationId || defaultFeedback.value?.id || ''
)
const filesByCategory = (category: string) =>
  props.projectFiles.filter((file) => file.materialCategory === category)
const statusForCategory = (category: string, fallbackCount = 0): NdtMaterialStatus => {
  const files = filesByCategory(category)
  if (files.length || fallbackCount) return '已覆盖'
  return '待上传'
}
const pipelineStatusForFile = (file: DocumentAsset) => {
  const statuses = [file.currentOcrStatus, file.sliceStatus, file.vectorStatus].filter(Boolean)
  if (statuses.some((status) => String(status).includes('失败'))) return '失败可重试'
  if (file.currentOcrStatus === '排队中') return '排队中'
  if (file.currentOcrStatus && file.currentOcrStatus !== '已识别') return 'OCR 中'
  if (file.sliceStatus && file.sliceStatus !== '已切片') return '切片中'
  if (file.vectorStatus && file.vectorStatus !== '已向量化') return '向量化中'
  if (file.vectorStatus === '已向量化') return '已完成'
  return file.currentOcrStatus || '排队中'
}
const ndtMaterialChecklist = computed(() => {
  const openFeedbackCount = openFeedback.value.length
  const rows: NdtMaterialChecklistItem[] = [
    {
      category: '机构与人员资质',
      requiredItems: '无损检测机构核准证、检测人员资格证、执业注册证、项目人员任命',
      uploadedCount: filesByCategory('机构与人员资质').length,
      missing: filesByCategory('机构与人员资质').length
        ? '已上传资质资料，等待监检核验'
        : '当前接口未返回资质文件，需在无损检测资料库中补充或核验',
      status: statusForCategory('机构与人员资质'),
      nodeRefs: 'R35、R36、R37',
      actions: [{ key: 'upload', label: '上传资料', category: '机构与人员资质' }]
    },
    {
      category: '检测方案与工艺',
      requiredItems: '无损检测方案、单项检测工艺文件、操作指导书、受控表格',
      uploadedCount: filesByCategory('检测方案与工艺').length,
      missing: filesByCategory('检测方案与工艺').length
        ? '已上传检测方案与工艺资料'
        : '需补充检测方案、工艺文件和操作指导书',
      status: statusForCategory('检测方案与工艺'),
      nodeRefs: 'R35、R39、R40',
      actions: [{ key: 'upload', label: '上传资料', category: '检测方案与工艺' }]
    },
    {
      category: '检测设备与校准',
      requiredItems: '检测设备台账、检定/校准报告、设备有效期证明',
      uploadedCount: filesByCategory('检测设备与校准').length,
      missing: filesByCategory('检测设备与校准').length
        ? '已上传设备与校准资料'
        : '需补充设备检定或校准证明',
      status: statusForCategory('检测设备与校准'),
      nodeRefs: 'R38',
      actions: [{ key: 'upload', label: '上传资料', category: '检测设备与校准' }]
    },
    {
      category: '底片与影像资料',
      requiredItems: '底片编号、射线底片或数字影像、底片包索引',
      uploadedCount: filesByCategory('底片与影像资料').length + props.films.length,
      missing:
        filesByCategory('底片与影像资料').length || props.films.length
          ? '已登记或上传底片影像，等待监检核验'
          : '需上传或登记底片编号和影像资料',
      status: props.films.some((film) => film.status === '需补正')
        ? '需补正'
        : statusForCategory('底片与影像资料', props.films.length),
      nodeRefs: 'R40、R65',
      actions: [{ key: 'upload', label: '上传底片/影像', category: '底片与影像资料' }]
    },
    {
      category: '检测记录',
      requiredItems: '无损检测委托单、检测记录、原始记录、抽查样本记录',
      uploadedCount: filesByCategory('检测记录').length + props.records.length,
      missing:
        filesByCategory('检测记录').length || props.records.length
          ? '已上传或导入检测记录，等待监检核验'
          : '需导入检测记录和原始记录',
      status: statusForCategory('检测记录', props.records.length),
      nodeRefs: 'R40、R41',
      actions: [{ key: 'upload', label: '上传检测记录', category: '检测记录' }]
    },
    {
      category: '检测报告',
      requiredItems: 'RT/UT/MT/PT 检测报告、检测结论、报告与底片对应关系',
      uploadedCount: filesByCategory('检测报告').length + props.reports.length,
      missing:
        filesByCategory('检测报告').length || props.reports.length
          ? '已上传检测报告，等待监检核验'
          : '需上传检测报告',
      status: props.reports.some((report) => report.status === '需补正')
        ? '需补正'
        : statusForCategory('检测报告', props.reports.length),
      nodeRefs: 'R40、R65',
      actions: [{ key: 'upload', label: '上传检测报告', category: '检测报告' }]
    },
    {
      category: '问题处理闭环',
      requiredItems: '不合格品控制、联络单/意见书、处理反馈、返修后复检报告',
      uploadedCount: openFeedbackCount,
      missing: openFeedbackCount ? `${openFeedbackCount} 项监检反馈待处理` : '暂无待处理反馈',
      status: openFeedbackCount ? '需补正' : '已覆盖',
      nodeRefs: 'R41、R42',
      actions: [
        { key: 'upload', label: '上传补正', category: '问题处理闭环' },
        { key: 'rectify', label: '提交反馈' }
      ]
    }
  ]
  return rows
})
const ndtChecklistSummary = computed(() => ({
  covered: ndtMaterialChecklist.value.filter((item) => item.status === '已覆盖').length,
  pending: ndtMaterialChecklist.value.filter((item) => item.status === '待上传').length,
  correction: ndtMaterialChecklist.value.filter((item) => item.status === '需补正').length,
  total: ndtMaterialChecklist.value.length
}))
const ndtAssetRows = computed(() => {
  const reportFileIds = new Set(props.reports.map((report) => report.fileId))
  return [
    ...props.films.map((film) => ({
      id: film.id,
      assetType: '底片编号',
      name: film.filmNo,
      relation: film.weldNo,
      method: film.method,
      documentNo: film.reportNo || film.entrustNo || '-',
      standardCode: film.standardCode || '-',
      operator: [film.evaluatorName, film.reviewerName].filter(Boolean).join(' / ') || '-',
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
      documentNo: record.reportNo || record.entrustNo || '-',
      standardCode: record.standardCode || '-',
      operator: [record.evaluatorName, record.reviewerName].filter(Boolean).join(' / ') || '-',
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
      documentNo: report.reportNo || report.entrustNo || '-',
      standardCode: report.standardCode || '-',
      operator: [report.evaluatorName, report.reviewerName].filter(Boolean).join(' / ') || '-',
      status: report.status,
      updatedAt: report.uploadedAt,
      detailId: report.id
    })),
    ...props.projectFiles
      .filter((file) => !reportFileIds.has(file.id))
      .map((file) => ({
        id: file.id,
        assetType: file.materialCategory || '项目文件',
        name: file.fileName,
        relation: file.currentVersionId,
        method: '-',
        documentNo: file.currentVersionId,
        standardCode: file.embeddingModel || '-',
        operator: file.uploaderName || '-',
        status: pipelineStatusForFile(file),
        updatedAt: file.updatedAt,
        detailId: ''
      }))
  ]
})

const ocrMetadataRows = computed<NdtOcrMetadataRow[]>(() => [
  {
    category: '底片与影像资料',
    source: '底片、数字影像、底片包索引',
    fields: '底片编号、焊口编号、底片包索引、影像文件名、评定级别、缺陷位置',
    status: props.films.length ? '已识别' : '待上传'
  },
  {
    category: '检测记录',
    source: '委托单、检测记录、原始记录',
    fields: '记录编号、委托单号、报告编号、工艺编号、设备编号、人员证书、检测结论',
    status: props.records.length ? '已识别' : '待上传'
  },
  {
    category: '检测报告',
    source: 'RT/UT/MT/PT 检测报告',
    fields: '报告编号、检测方法、检测比例、执行标准、报告结论、检测/复核人员',
    status: props.reports.length ? '已识别' : '待上传'
  }
])

const scrollToNdtSection = (sectionId: string) => {
  document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const handleMaterialAction = (action: NdtMaterialAction) => {
  if (action.key === 'upload') {
    emit('uploadMaterial', action.category)
    return
  }
  scrollToNdtSection('ndt-feedback-list')
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
        <ElTable :data="ndtMaterialChecklist" border class="ndt-checklist-table">
          <ElTableColumn type="index" label="序号" width="72" />
          <ElTableColumn prop="category" label="资料类别" min-width="150" />
          <ElTableColumn label="操作" min-width="170">
            <template #default="{ row }">
              <div class="ndt-table-actions">
                <ElButton
                  v-for="action in row.actions"
                  :key="`${row.category}-${action.key}-${action.label}`"
                  link
                  type="primary"
                  :loading="loading"
                  @click="handleMaterialAction(action)"
                >
                  {{ action.label }}
                </ElButton>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="requiredItems" label="标准要求资料" min-width="260" />
          <ElTableColumn label="已上传/登记" width="110">
            <template #default="{ row }">{{ row.uploadedCount }} 项</template>
          </ElTableColumn>
          <ElTableColumn prop="missing" label="缺口/待核验" min-width="260" />
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

      <section class="ndt-ocr-panel">
        <div class="ndt-section-head">
          <div>
            <strong>OCR 字段确认</strong>
            <p
              >底片、检测记录和检测报告的关键字段由资料识别结果进入台账，人工只处理低置信度和监检反馈项。</p
            >
          </div>
          <ElTag type="warning" effect="plain">字段待确认</ElTag>
        </div>
        <ElTable :data="ocrMetadataRows" border>
          <ElTableColumn type="index" label="序号" width="72" />
          <ElTableColumn prop="category" label="资料类别" width="150" show-overflow-tooltip />
          <ElTableColumn prop="source" label="识别来源" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="fields" label="关键字段" min-width="360" show-overflow-tooltip />
          <ElTableColumn label="识别状态" width="120">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
        </ElTable>
        <ElTable
          v-if="ndtReadiness?.reports?.length"
          :data="ndtReadiness.reports"
          border
          class="ndt-readiness-table"
        >
          <ElTableColumn prop="reportId" label="报告" min-width="150" show-overflow-tooltip />
          <ElTableColumn prop="ocrStatus" label="OCR" width="100" />
          <ElTableColumn label="字段/bbox" width="110">
            <template #default="{ row }">
              {{ row.fieldCount || 0 }} / {{ row.bboxFieldCount || 0 }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="100">
            <template #default="{ row }">
              <ElTag :type="row.passed ? 'success' : 'danger'" size="small" effect="plain">
                {{ row.passed ? '可提交' : '阻断' }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="原因" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              {{ (row.blockingReasons || []).map(blockerText).join('；') || '无' }}
            </template>
          </ElTableColumn>
        </ElTable>
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
              :disabled="!canSubmitNdt"
              :loading="loading"
              :title="submitBlockers.join('；')"
              @click="handleSubmitNdt"
            >
              提交检测资料
            </ElButton>
          </div>
        </div>
        <ElAlert
          v-if="submitBlockers.length"
          class="ndt-submit-error"
          type="warning"
          title="检测资料暂不满足提交条件"
          :closable="false"
          show-icon
        >
          <ul class="ndt-blocker-list">
            <li v-for="reason in submitBlockers" :key="reason">{{ reason }}</li>
          </ul>
        </ElAlert>
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
          <ElTableColumn
            prop="documentNo"
            label="委托/报告号"
            min-width="150"
            show-overflow-tooltip
          />
          <ElTableColumn
            prop="standardCode"
            label="执行标准"
            min-width="160"
            show-overflow-tooltip
          />
          <ElTableColumn
            prop="operator"
            label="检测/复核人"
            min-width="130"
            show-overflow-tooltip
          />
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
          <ElSelect v-model="rectificationForm.rectificationId" aria-label="选择补正反馈">
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
            aria-label="补正反馈说明"
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

.ndt-workspace :deep(.el-button),
.ndt-workspace :deep(.el-input__wrapper),
.ndt-workspace :deep(.el-select__wrapper) {
  min-height: 44px;
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
  font-weight: 600;
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 400;
  color: #52617a;
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
  color: #52617a;
}

.ndt-metrics strong {
  color: #1f2937;
}

.section-title {
  margin: 14px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.ndt-checklist,
.ndt-ocr-panel,
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
  color: #52617a;
}

.ndt-submit-error,
.ndt-rectify-error {
  margin-bottom: 10px;
}

.ndt-submit-error,
.ndt-rectify-error {
  margin-top: 10px;
}

.ndt-readiness-table {
  margin-top: 8px;
}

.ndt-blocker-list {
  padding-left: 18px;
  margin: 4px 0 0;
  line-height: 1.6;
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

.ndt-table-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
}

.ndt-checklist-table :deep(.el-table__body-wrapper) {
  overflow-y: visible;
}

.ndt-checklist-table :deep(.el-table__cell .cell) {
  overflow: visible;
  line-height: 1.45;
  text-overflow: clip;
  white-space: normal;
}

.rectify-form {
  grid-template-columns: 1fr;
}

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
  color: #52617a;
}

.muted-action {
  font-size: 13px;
  font-weight: 600;
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
