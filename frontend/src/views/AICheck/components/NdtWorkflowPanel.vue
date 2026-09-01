<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip
} from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import type {
  DocumentAsset,
  NdtFeedback,
  NdtFilm,
  NdtRecord,
  NdtReport,
  ProjectTreeNode
} from '@/types/aicheck'
import { getStatusTagType } from './status'
import { pendingNdtFilms, pendingNdtReports } from '@/utils/ndtReadiness'
import { documentBusinessStatus, documentPipelineStatus } from '@/utils/documentPipelineStatus'
import {
  canRetryDocumentUpload,
  canSubmitNdtDocumentUpload,
  collectBatchSubmittableItems,
  ndtEditBlockedReason,
  ndtSubmitBlockedReason
} from '@/utils/documentUploadActions'
import AuditSummaryGrid, { type AuditSummaryCard } from './AuditSummaryGrid.vue'
import {
  NDT_ATOMIC_MATERIALS,
  NDT_NODE_IDS,
  ndtFileApprovalStatus,
  ndtBusinessRuleNames,
  type NdtAtomicMaterial
} from '@/utils/ndtAtomicMaterials'

type NdtMaterialChecklistItem = NdtAtomicMaterial & {
  uploadedCount: number
  /** 该类型下已上传的文件。展开时直接用，不再另外请求。 */
  files: DocumentAsset[]
}
const props = defineProps<{
  node?: ProjectTreeNode
  films: NdtFilm[]
  records: NdtRecord[]
  reports: NdtReport[]
  feedback: NdtFeedback[]
  projectFiles: DocumentAsset[]
  readOnly?: boolean
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
    } & Partial<NdtFilm>
  ]
  importRecords: [
    payload: {
      rows: Array<Partial<NdtRecord>>
    }
  ]
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
  uploadMaterial: [material: NdtAtomicMaterial]
  viewMaterialFile: [documentId: string]
  uploadReport: []
  replaceMaterialBindings: [payload: { documentId: string; nodeIds: number[] }]
  submitMaterial: [payload: { documentId: string; bindingIds: string[] }]
  submitMaterialBatch: [payloads: Array<{ documentId: string; bindingIds: string[] }>]
  retryUpload: [documentId: string]
}>()

const rectificationForm = reactive({
  rectificationId: '',
  description: '已补充底片包索引和检测记录页码，请复审。'
})
const filmDialogVisible = ref(false)
const bindingDialogVisible = ref(false)
const bindingDocumentId = ref('')
const bindingNodeIds = ref<number[]>([])
const filmForm = reactive({
  filmNo: '',
  weldNo: '',
  method: 'RT' as NdtFilm['method'],
  pipelineNo: '',
  reportNo: '',
  entrustNo: '',
  filmPackageNo: '',
  imageFileName: '',
  testDate: '',
  detectionRatio: '100%',
  standardCode: 'NB/T 47013.2-2015',
  evaluationLevel: 'Ⅱ级',
  evaluatorName: '',
  reviewerName: ''
})
const filmFormRef = ref<FormInstance>()
const filmRules: FormRules = {
  filmNo: [{ required: true, message: '请填写底片编号', trigger: 'blur' }],
  weldNo: [{ required: true, message: '请填写焊口编号', trigger: 'blur' }],
  method: [{ required: true, message: '请选择检测方法', trigger: 'change' }]
}
const rectificationFormRef = ref<FormInstance>()
const rectificationRules: FormRules = {
  rectificationId: [{ required: true, message: '请选择需要反馈的补正事项', trigger: 'change' }],
  description: [
    { required: true, message: '请填写本次补正说明', trigger: 'blur' },
    { min: 4, max: 240, message: '补正说明应为 4–240 个字符', trigger: 'blur' }
  ]
}

const pendingReports = computed(() => pendingNdtReports(props.reports))
const pendingFilms = computed(() => pendingNdtFilms(props.films))
const openFeedback = computed(() => props.feedback.filter((item) => item.status === '待反馈'))
const defaultFeedback = computed(() => openFeedback.value[0])
watch(
  () => defaultFeedback.value?.id,
  (defaultId) => {
    if (!openFeedback.value.some((item) => item.id === rectificationForm.rectificationId)) {
      rectificationForm.rectificationId = defaultId || ''
    }
  },
  { immediate: true }
)
watch(
  () => props.films.length,
  (count, previousCount) => {
    if (filmDialogVisible.value && count > previousCount) {
      filmDialogVisible.value = false
      filmFormRef.value?.resetFields()
    }
  }
)
const selectedRectificationId = computed(
  () => rectificationForm.rectificationId || defaultFeedback.value?.id || ''
)
const ndtMetricCards = computed<AuditSummaryCard[]>(() => [
  { label: '底片编号', value: props.films.length, hint: '已登记影像索引', tone: 'blue' },
  { label: '检测记录', value: props.records.length, hint: '已导入检测台账', tone: 'blue' },
  { label: '检测报告', value: props.reports.length, hint: '当前报告版本', tone: 'green' },
  {
    label: '待补正',
    value: openFeedback.value.length,
    hint: openFeedback.value.length ? '需按监检意见处理' : '暂无待处理反馈',
    tone: openFeedback.value.length ? 'orange' : 'gray'
  }
])
const atomicProjectFiles = computed(() =>
  props.projectFiles.filter((file) => file.materialCategory === '无损检测资料')
)
const ndtMaterialChecklist = computed<NdtMaterialChecklistItem[]>(() =>
  NDT_ATOMIC_MATERIALS.map((material) => {
    const files = atomicProjectFiles.value.filter((file) => file.materialTypeCode === material.code)
    return { ...material, uploadedCount: files.length, files }
  })
)

/* 「已上传 N 项」要能点开看是哪几份。
 *
 * 原来这一列只是个数字，旁边只有「上传文件」——传完之后没有任何入口
 * 确认自己传了什么。**只报数不报内容，等于让人凭记忆核对**：
 * 传漏了、传错了、传重了，都要等监检退回来才知道。
 * 数据本来就在手上（atomicProjectFiles），不需要新接口。
 */
const expandedMaterialCodes = ref<string[]>([])
const toggleMaterialFiles = (code: string) => {
  expandedMaterialCodes.value = expandedMaterialCodes.value.includes(code)
    ? expandedMaterialCodes.value.filter((item) => item !== code)
    : [...expandedMaterialCodes.value, code]
}
const ndtChecklistSummary = computed(() => ({
  uploaded: atomicProjectFiles.value.length,
  types: new Set(atomicProjectFiles.value.map((file) => file.materialTypeCode)).size,
  total: ndtMaterialChecklist.value.length
}))
const atomicFileRows = computed(() =>
  atomicProjectFiles.value.map((file) => {
    const bindings = file.bindings || []
    const editableBindings = bindings.filter((binding) =>
      ['草稿挂载', '需补正'].includes(binding.bindingStatus)
    )
    const approvalStatus = ndtFileApprovalStatus(file)
    const canEdit = approvalStatus === '草稿' || approvalStatus === '需补正'
    const uploadStatus = documentPipelineStatus(file)
    return {
      ...file,
      materialTypeDisplayName: file.materialTypeName || file.materialTypeCode || '未分类资料',
      nodeIds: [...new Set(bindings.map((binding) => binding.nodeId))].sort((a, b) => a - b),
      businessRuleNames: ndtBusinessRuleNames(bindings.map((binding) => binding.nodeId)),
      approvalStatus,
      uploadStatus,
      editableBindingIds: canEdit ? editableBindings.map((binding) => binding.id) : [],
      canEdit,
      canSubmit: canSubmitNdtDocumentUpload(approvalStatus, uploadStatus, !props.readOnly),
      submitBlockedReason: props.readOnly
        ? '当前项目为只读状态，不能提交文件。'
        : ndtSubmitBlockedReason(approvalStatus, uploadStatus),
      editBlockedReason: ndtEditBlockedReason(approvalStatus)
    }
  })
)
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
        status: documentBusinessStatus(file),
        updatedAt: file.updatedAt,
        detailId: ''
      }))
  ]
})

const handleMaterialUpload = (material: NdtAtomicMaterial) => emit('uploadMaterial', material)

const openBindingDialog = (row: (typeof atomicFileRows.value)[number]) => {
  bindingDocumentId.value = row.id
  bindingNodeIds.value = [...row.nodeIds]
  bindingDialogVisible.value = true
}

const saveBindingAdjustment = () => {
  if (!bindingNodeIds.value.length) return
  emit('replaceMaterialBindings', {
    documentId: bindingDocumentId.value,
    nodeIds: [...bindingNodeIds.value]
  })
  bindingDialogVisible.value = false
}

const submitAtomicFile = (row: (typeof atomicFileRows.value)[number]) => {
  if (!row.canSubmit) return
  emit('submitMaterial', { documentId: row.id, bindingIds: row.editableBindingIds })
}

const batchSubmittableAtomicFiles = computed(() =>
  collectBatchSubmittableItems(atomicFileRows.value, (row) => row.canSubmit)
)

const submitAtomicFilesBatch = () => {
  if (!batchSubmittableAtomicFiles.value.length || props.loading) return
  emit(
    'submitMaterialBatch',
    batchSubmittableAtomicFiles.value.map((row) => ({
      documentId: row.id,
      bindingIds: row.editableBindingIds
    }))
  )
}

const retryAtomicFileUpload = (row: (typeof atomicFileRows.value)[number]) => {
  if (canRetryDocumentUpload(row.uploadStatus)) emit('retryUpload', row.id)
}

const handleCreateFilm = async () => {
  const valid = await filmFormRef.value?.validate().catch(() => false)
  if (!valid) return
  emit('createFilm', {
    filmNo: filmForm.filmNo.trim(),
    weldNo: filmForm.weldNo.trim(),
    method: filmForm.method,
    pipelineNo: filmForm.pipelineNo.trim(),
    reportNo: filmForm.reportNo.trim(),
    entrustNo: filmForm.entrustNo.trim(),
    filmPackageNo: filmForm.filmPackageNo.trim(),
    imageFileName: filmForm.imageFileName.trim(),
    testDate: filmForm.testDate.trim(),
    detectionRatio: filmForm.detectionRatio.trim(),
    standardCode: filmForm.standardCode.trim(),
    evaluationLevel: filmForm.evaluationLevel.trim(),
    evaluatorName: filmForm.evaluatorName.trim(),
    reviewerName: filmForm.reviewerName.trim()
  })
}

const handleRectifyNdt = async (rectificationId?: string) => {
  if (rectificationId) rectificationForm.rectificationId = rectificationId
  const valid = await rectificationFormRef.value?.validate().catch(() => false)
  if (!valid) return
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
    <ElDialog
      v-model="filmDialogVisible"
      title="新增底片编号"
      width="720px"
      destroy-on-close
      append-to-body
    >
      <ElAlert
        v-if="filmError"
        type="error"
        title="底片编号登记失败"
        :description="filmError"
        :closable="false"
        show-icon
        class="ndt-film-error"
      />
      <ElForm
        ref="filmFormRef"
        :model="filmForm"
        :rules="filmRules"
        label-position="top"
        status-icon
        class="ndt-film-form"
      >
        <ElFormItem label="底片编号" prop="filmNo">
          <ElInput v-model="filmForm.filmNo" placeholder="例如 RT-S03-001" />
        </ElFormItem>
        <ElFormItem label="焊口编号" prop="weldNo">
          <ElInput v-model="filmForm.weldNo" placeholder="例如 W-S03-RT-001" />
        </ElFormItem>
        <ElFormItem label="检测方法" prop="method">
          <ElSelect v-model="filmForm.method" aria-label="检测方法">
            <ElOption
              v-for="method in ['RT', 'UT', 'MT', 'PT']"
              :key="method"
              :label="method"
              :value="method"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="关联管线">
          <ElInput v-model="filmForm.pipelineNo" placeholder="管线或管段编号" />
        </ElFormItem>
        <ElFormItem label="报告编号">
          <ElInput v-model="filmForm.reportNo" placeholder="检测报告编号" />
        </ElFormItem>
        <ElFormItem label="委托单号">
          <ElInput v-model="filmForm.entrustNo" placeholder="检测委托单号" />
        </ElFormItem>
        <ElFormItem label="底片包号">
          <ElInput v-model="filmForm.filmPackageNo" placeholder="底片包索引编号" />
        </ElFormItem>
        <ElFormItem label="影像文件名">
          <ElInput v-model="filmForm.imageFileName" placeholder="与随后上传的 JPG 文件名一致" />
        </ElFormItem>
        <ElFormItem label="检测日期">
          <ElInput v-model="filmForm.testDate" placeholder="YYYY-MM-DD" />
        </ElFormItem>
        <ElFormItem label="检测比例">
          <ElInput v-model="filmForm.detectionRatio" placeholder="例如 100%" />
        </ElFormItem>
        <ElFormItem label="执行标准">
          <ElInput v-model="filmForm.standardCode" />
        </ElFormItem>
        <ElFormItem label="评定级别">
          <ElInput v-model="filmForm.evaluationLevel" />
        </ElFormItem>
        <ElFormItem label="检测人员">
          <ElInput v-model="filmForm.evaluatorName" />
        </ElFormItem>
        <ElFormItem label="复核人员">
          <ElInput v-model="filmForm.reviewerName" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="filmDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="loading" @click="handleCreateFilm">登记底片</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="bindingDialogVisible" title="调整适用业务规则" width="640px" append-to-body>
      <p class="binding-dialog-hint">草稿或需补正的文件可以调整，提交审批后不能再修改。</p>
      <ElCheckboxGroup v-model="bindingNodeIds" class="binding-node-options">
        <ElCheckbox v-for="nodeId in NDT_NODE_IDS" :key="nodeId" :value="nodeId">
          {{ ndtBusinessRuleNames([nodeId])[0] }}
        </ElCheckbox>
      </ElCheckboxGroup>
      <template #footer>
        <ElButton @click="bindingDialogVisible = false">取消</ElButton>
        <ElButton
          type="primary"
          :disabled="!bindingNodeIds.length"
          :loading="loading"
          @click="saveBindingAdjustment"
        >
          保存
        </ElButton>
      </template>
    </ElDialog>

    <ElCard shadow="never" class="panel ndt-panel">
      <template #header>
        <div class="panel-header">
          <div>
            <span>一、无损检测资料</span>
            <div class="panel-subtitle"
              >集中管理检测方案、底片、记录、报告和补正资料，并逐项提交监检审核。</div
            >
          </div>
          <ElTag type="primary" effect="plain"> {{ ndtAssetRows.length }} 项资料 </ElTag>
        </div>
      </template>

      <AuditSummaryGrid class="ndt-metrics" :cards="ndtMetricCards" aria-label="无损检测资料摘要" />

      <section class="ndt-checklist">
        <div class="ndt-section-head">
          <div>
            <strong>无损检测资料上传</strong>
            <p
              >选择资料类型后，系统自动关联适用的业务规则；可在上传前调整。每个文件上传后单独保存为草稿。</p
            >
          </div>
          <ElTag type="info" effect="plain">
            {{ ndtChecklistSummary.uploaded }} 个文件 / {{ ndtChecklistSummary.types }} 种类型
          </ElTag>
        </div>
        <ElTable :data="ndtMaterialChecklist" border class="ndt-checklist-table">
          <ElTableColumn type="index" label="序号" width="72" />
          <ElTableColumn prop="name" label="资料类型" min-width="250" show-overflow-tooltip />
          <ElTableColumn prop="group" label="业务规则" min-width="360" show-overflow-tooltip />
          <ElTableColumn label="已上传" width="110">
            <template #default="{ row }">
              <!-- 0 项不做成可点：点开是空的，不如让人一眼看出还没传 -->
              <ElButton
                v-if="row.uploadedCount"
                link
                type="primary"
                @click="toggleMaterialFiles(row.code)"
              >
                {{ row.uploadedCount }} 项{{
                  expandedMaterialCodes.includes(row.code) ? ' ▴' : ' ▾'
                }}
              </ElButton>
              <span v-else class="ndt-empty-count">0 项</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <ElButton link type="primary" :loading="loading" @click="handleMaterialUpload(row)">
                上传文件
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>

        <!-- 展开的已传文件清单。放表下方而不是 expand 列：
             这张表只有五行，独立区块比每行塞一个展开箭头更好读。 -->
        <div
          v-for="material in ndtMaterialChecklist.filter(
            (item) => expandedMaterialCodes.includes(item.code) && item.files.length
          )"
          :key="`expanded-${material.code}`"
          class="ndt-uploaded-files"
        >
          <div class="ndt-uploaded-head">
            <strong>{{ material.name }}</strong>
            <span>已上传 {{ material.files.length }} 份</span>
          </div>
          <ul>
            <li v-for="file in material.files" :key="file.id">
              <ElButton link type="primary" @click="emit('viewMaterialFile', file.id)">
                {{ file.fileName }}
              </ElButton>
              <!-- 上传状态和识别状态是两件事：文件已上传但 OCR 还在排队，
                   跟文件根本没传上去，处置完全不同。 -->
              <small>{{ file.fileStatus }} · OCR {{ file.currentOcrStatus }}</small>
            </li>
          </ul>
        </div>
      </section>

      <!-- 摘要卡片「待提交/补正」滚到这里。锚点必须真实存在——
           选择器写了而元素没有，滚动会静默失败（本轮已踩过两次）。 -->
      <section id="ndt-pending-files" class="ndt-library">
        <div class="ndt-section-head">
          <div>
            <strong>已上传资料</strong>
            <p>请逐个核对资料类型；文件上传成功后可分别提交审批，无需等待其他资料上传完成。</p>
          </div>
          <div class="ndt-actions">
            <ElButton
              type="primary"
              :loading="loading"
              :disabled="readOnly || loading || !batchSubmittableAtomicFiles.length"
              @click="submitAtomicFilesBatch"
            >
              批量提交
            </ElButton>
            <ElButton plain @click="filmDialogVisible = true">登记底片编号</ElButton>
            <ElButton plain type="primary" @click="emit('uploadReport')">上传检测报告</ElButton>
          </div>
        </div>
        <ElAlert
          v-if="submitError"
          class="ndt-submit-error"
          type="error"
          title="无损检测文件操作失败"
          :closable="false"
          show-icon
        >
          {{ submitError }}
        </ElAlert>
        <ElTable :data="atomicFileRows" border height="360">
          <ElTableColumn type="index" label="序号" width="72" />
          <ElTableColumn prop="fileName" label="文件名称" min-width="220" show-overflow-tooltip />
          <ElTableColumn
            prop="materialTypeDisplayName"
            label="资料类型"
            min-width="230"
            show-overflow-tooltip
          />
          <ElTableColumn label="适用业务规则" min-width="300" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.businessRuleNames.join('；') || '尚未关联' }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="上传状态" width="130">
            <template #default="{ row }">
              <ElButton
                v-if="canRetryDocumentUpload(row.uploadStatus)"
                link
                type="danger"
                :disabled="loading"
                @click="retryAtomicFileUpload(row)"
              >
                失败重新上传
              </ElButton>
              <ElTag v-else :type="getStatusTagType(row.uploadStatus)" size="small" effect="plain">
                {{ row.uploadStatus }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="审批状态" width="110">
            <template #default="{ row }">
              <ElTag :type="getStatusTagType(row.approvalStatus)" size="small" effect="plain">
                {{ row.approvalStatus }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="updatedAt" label="更新时间" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="操作" width="190" fixed="right">
            <template #default="{ row }">
              <ElTooltip :disabled="row.canEdit" :content="row.editBlockedReason" placement="top">
                <span>
                  <ElButton
                    link
                    type="primary"
                    :disabled="!row.canEdit"
                    @click="openBindingDialog(row)"
                  >
                    调整业务规则
                  </ElButton>
                </span>
              </ElTooltip>
              <!-- 禁用时把理由挂在 tooltip 上：三种情况该做的事完全不同
                   （等一等 / 重新上传 / 已经提交过了），不能都用一个灰按钮打发。 -->
              <ElTooltip
                :disabled="row.canSubmit"
                :content="row.submitBlockedReason"
                placement="top"
              >
                <span>
                  <ElButton
                    link
                    type="primary"
                    :disabled="!row.canSubmit"
                    :loading="loading"
                    @click="submitAtomicFile(row)"
                  >
                    提交审批
                  </ElButton>
                </span>
              </ElTooltip>
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
            <ElTooltip
              content="该反馈已关闭，无需重复提交"
              :disabled="row.status !== '已关闭'"
              placement="top"
              popper-class="audit-action-tooltip-popper"
            >
              <span class="ndt-action-tooltip">
                <ElButton
                  link
                  type="warning"
                  :disabled="row.status === '已关闭'"
                  @click="handleRectifyNdt(row.id)"
                >
                  提交反馈
                </ElButton>
              </span>
            </ElTooltip>
          </template>
        </ElTableColumn>
      </ElTable>
      <ElEmpty v-else description="暂无监检反馈" class="compact-empty" />

      <ElForm
        ref="rectificationFormRef"
        :model="rectificationForm"
        :rules="rectificationRules"
        label-position="top"
        status-icon
        class="rectify-form"
      >
        <ElFormItem label="补正反馈" prop="rectificationId">
          <ElSelect
            v-model="rectificationForm.rectificationId"
            :disabled="!openFeedback.length"
            placeholder="选择待处理反馈"
            aria-label="选择补正反馈"
          >
            <ElOption
              v-for="item in openFeedback"
              :key="item.id"
              :label="item.title"
              :value="item.id"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="反馈说明" prop="description">
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
            <ElButton link type="primary" :loading="loading" @click="handleRectifyNdt()">
              重试补正反馈
            </ElButton>
          </div>
        </ElAlert>
        <ElTooltip
          content="暂无待处理的监检反馈"
          :disabled="Boolean(openFeedback.length)"
          placement="top"
          popper-class="audit-action-tooltip-popper"
        >
          <span class="ndt-action-tooltip">
            <ElButton
              type="warning"
              plain
              :disabled="!openFeedback.length"
              :loading="loading"
              @click="handleRectifyNdt()"
            >
              提交补正反馈
            </ElButton>
          </span>
        </ElTooltip>
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

.ndt-film-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.ndt-film-error {
  margin-bottom: 14px;
}

.binding-dialog-hint {
  margin: 0 0 14px;
  color: #667085;
}

.binding-node-options {
  display: grid;
  gap: 10px;
}

.binding-node-options :deep(.el-checkbox) {
  height: auto;
  margin-right: 0;
  line-height: 1.5;
}

.ndt-workspace :deep(.el-button),
.ndt-workspace :deep(.el-input__wrapper),
.ndt-workspace :deep(.el-select__wrapper) {
  min-height: 44px;
}

.ndt-panel {
  margin-bottom: 16px;
  border: 0;
  box-shadow: 0 8px 20px rgb(15 23 42 / 7%);
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
  --audit-summary-columns: 4;

  margin-bottom: 14px;
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

.ndt-action-tooltip {
  display: inline-flex;
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
