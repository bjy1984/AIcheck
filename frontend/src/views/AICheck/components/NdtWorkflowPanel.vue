<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Document, FolderOpened, UploadFilled } from '@element-plus/icons-vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElSelect,
  ElTag
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
import FileTypeIcon from './FileTypeIcon.vue'
import { pendingNdtFilms, pendingNdtReports } from '@/utils/ndtReadiness'
import { documentPipelineStatus } from '@/utils/documentPipelineStatus'
import { plainWording } from '@/utils/reviewerWording'
import {
  canRetryDocumentUpload,
  canSubmitNdtDocumentUpload,
  collectBatchSubmittableItems,
  ndtEditBlockedReason,
  ndtSubmitBlockedReason
} from '@/utils/documentUploadActions'
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
const CHECKLIST_PREVIEW = 4
const checklistExpanded = ref(false)
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

const replyDialogVisible = ref(false)
const closedOpen = ref(false)
const closedFeedback = computed(() => props.feedback.filter((item) => item.status !== '待反馈'))
const openReply = (rectificationId: string) => {
  rectificationForm.rectificationId = rectificationId
  replyDialogVisible.value = true
}
// 提交成功后这条反馈会离开「待反馈」：弹窗跟着关，和底片登记弹窗一个做法
watch(
  () => openFeedback.value.length,
  (count, previousCount) => {
    if (replyDialogVisible.value && count < previousCount) replyDialogVisible.value = false
  }
)
/** 还缺的资料：没展开时只列没传过的前几种；展开后列全部 22 种。 */
const missingMaterialCount = computed(
  () => ndtMaterialChecklist.value.filter((item) => !item.uploadedCount).length
)
const visibleChecklist = computed(() => {
  if (checklistExpanded.value) return ndtMaterialChecklist.value
  const missing = ndtMaterialChecklist.value.filter((item) => !item.uploadedCount)
  return (missing.length ? missing : ndtMaterialChecklist.value).slice(0, CHECKLIST_PREVIEW)
})
const goToChecklist = () => {
  checklistExpanded.value = true
  document.getElementById('ndt-checklist')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const ndtFileSubtext = (row: (typeof atomicFileRows.value)[number]) =>
  [
    row.materialTypeDisplayName,
    row.businessRuleNames[0] || '尚未关联',
    String(row.updatedAt || '').slice(5, 10)
  ]
    .filter(Boolean)
    .join(' · ')
const handleNdtFileMenu = (command: string, row: (typeof atomicFileRows.value)[number]) => {
  if (command === 'view') emit('viewMaterialFile', row.id)
  else if (command === 'submit') submitAtomicFile(row)
  else if (command === 'rules') openBindingDialog(row)
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
  <!-- 2026-11-04 手机简化稿：反馈卡 → 三个常用操作 → 一行登记数 → 还缺的资料 → 已上传。
       有待处理的监检反馈时放最前：这是唯一有期限、要立刻动手的事，不该排在 22 种资料类型后面。 -->
  <div class="ndt-workspace">
    <ElDialog
      v-model="filmDialogVisible"
      title="新增底片编号"
      width="min(720px, 94vw)"
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

    <ElDialog
      v-model="bindingDialogVisible"
      title="调整适用业务规则"
      width="min(640px, 94vw)"
      append-to-body
    >
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

    <!-- 回复反馈：说明写在弹窗里，不在页面上摊开一个表单（2026-11-04 手机简化稿） -->
    <ElDialog
      v-model="replyDialogVisible"
      title="回复监检反馈"
      width="min(560px, 92vw)"
      append-to-body
    >
      <ElForm
        ref="rectificationFormRef"
        :model="rectificationForm"
        :rules="rectificationRules"
        label-position="top"
        status-icon
        class="rectify-form"
      >
        <ElFormItem label="反馈事项" prop="rectificationId">
          <ElSelect
            v-model="rectificationForm.rectificationId"
            :disabled="!openFeedback.length"
            placeholder="选择待处理反馈"
            aria-label="选择补正反馈"
          >
            <ElOption
              v-for="item in openFeedback"
              :key="item.id"
              :label="plainWording(item.title)"
              :value="item.id"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="补正说明" prop="description">
          <ElInput
            v-model="rectificationForm.description"
            type="textarea"
            :rows="3"
            maxlength="240"
            show-word-limit
            aria-label="补正反馈说明"
          />
        </ElFormItem>
        <ElAlert
          v-if="rectifyError"
          class="ndt-rectify-error"
          type="error"
          title="补正反馈提交失败"
          :closable="false"
          show-icon
        >
          {{ rectifyError }}
        </ElAlert>
      </ElForm>
      <template #footer>
        <ElButton @click="replyDialogVisible = false">取消</ElButton>
        <ElButton
          type="primary"
          :disabled="!openFeedback.length"
          :loading="loading"
          @click="handleRectifyNdt()"
        >
          提交反馈
        </ElButton>
      </template>
    </ElDialog>

    <!-- 有待处理的监检反馈时放最前：这是唯一有期限、要立刻动手的事 -->
    <section
      v-if="feedback.length"
      id="ndt-feedback-list"
      class="ndt-section"
      aria-label="监检反馈"
    >
      <h2>
        监检反馈<span v-if="openFeedback.length" class="ndt-count is-red">{{
          openFeedback.length
        }}</span>
      </h2>
      <article v-for="row in openFeedback" :key="row.id" class="ndt-feedback-card">
        <ElTag type="danger" size="small" effect="light">{{ plainWording(row.status) }}</ElTag>
        <strong>{{ plainWording(row.title) }}</strong>
        <p v-if="row.description">{{ plainWording(row.description) }}</p>
        <div class="ndt-feedback-foot">
          <small>期限 {{ row.deadline }}</small>
          <div class="ndt-feedback-actions">
            <ElButton type="primary" :disabled="readOnly" @click="emit('uploadReport')">
              补充资料
            </ElButton>
            <ElButton plain type="primary" :disabled="readOnly" @click="openReply(row.id)">
              回复反馈
            </ElButton>
          </div>
        </div>
        <button type="button" class="ndt-link" @click="emit('openFeedbackDetail', row.id)">
          查看详情
        </button>
      </article>
      <p v-if="!openFeedback.length" class="ndt-note">监检反馈都已处理。</p>
      <div v-if="closedFeedback.length" class="ndt-closed">
        <button
          type="button"
          class="ndt-link is-muted"
          :aria-expanded="closedOpen"
          @click="closedOpen = !closedOpen"
        >
          已处理 {{ closedFeedback.length }} 条{{ closedOpen ? ' 收起' : ' ›' }}
        </button>
        <ul v-if="closedOpen" class="ndt-card ndt-list">
          <li v-for="row in closedFeedback" :key="row.id">
            <button type="button" class="ndt-row-main" @click="emit('openFeedbackDetail', row.id)">
              <span class="ndt-row-text">
                <strong>{{ plainWording(row.title) }}</strong>
                <small>期限 {{ row.deadline }}</small>
              </span>
            </button>
            <ElTag :type="getStatusTagType(row.status)" size="small" effect="plain">
              {{ plainWording(row.status) }}
            </ElTag>
          </li>
        </ul>
      </div>
    </section>

    <div class="ndt-action-tiles" aria-label="常用操作">
      <button type="button" :disabled="readOnly" @click="emit('uploadReport')">
        <ElIcon><UploadFilled /></ElIcon>上传检测报告
      </button>
      <button type="button" :disabled="readOnly" @click="filmDialogVisible = true">
        <ElIcon><Document /></ElIcon>登记底片编号
      </button>
      <button type="button" :disabled="readOnly" @click="goToChecklist">
        <ElIcon><FolderOpened /></ElIcon>上传其他资料
      </button>
    </div>

    <dl class="ndt-card ndt-stats" aria-label="已登记检测资料">
      <div>
        <dt>底片</dt>
        <dd>{{ films.length }}</dd>
      </div>
      <div>
        <dt>记录</dt>
        <dd>{{ records.length }}</dd>
      </div>
      <div>
        <dt>报告</dt>
        <dd>{{ reports.length }}</dd>
      </div>
      <div>
        <dt>待提交</dt>
        <dd>{{ batchSubmittableAtomicFiles.length }}</dd>
      </div>
    </dl>

    <section id="ndt-checklist" class="ndt-section" aria-label="资料类型与上传">
      <div class="ndt-section-head">
        <h2>{{ missingMaterialCount ? '还缺的资料' : '资料类型' }}</h2>
        <small>{{ ndtChecklistSummary.total }} 种中已传 {{ ndtChecklistSummary.types }} 种</small>
      </div>
      <ul class="ndt-card ndt-list">
        <li v-for="row in visibleChecklist" :key="row.code" class="ndt-material">
          <div class="ndt-material-line">
            <span class="ndt-material-name">{{ row.name }}</span>
            <!-- 0 项不做成可点：点开是空的，不如让人一眼看出还没传 -->
            <button
              v-if="row.uploadedCount"
              type="button"
              class="ndt-link"
              :aria-expanded="expandedMaterialCodes.includes(row.code)"
              @click="toggleMaterialFiles(row.code)"
            >
              {{ row.uploadedCount }} 份{{ expandedMaterialCodes.includes(row.code) ? ' ▴' : ' ▾' }}
            </button>
            <small v-else class="ndt-empty-count">0 份</small>
            <ElButton
              plain
              type="primary"
              :disabled="readOnly"
              :loading="loading"
              :aria-label="`上传${row.name}`"
              @click="handleMaterialUpload(row)"
            >
              上传
            </ElButton>
          </div>
          <!-- 上传状态和识别状态是两件事：文件已上传但 OCR 还在排队，跟文件根本没传上去，处置完全不同。 -->
          <ul
            v-if="expandedMaterialCodes.includes(row.code) && row.files.length"
            class="ndt-uploaded-files"
          >
            <li v-for="file in row.files" :key="file.id">
              <button type="button" class="ndt-link" @click="emit('viewMaterialFile', file.id)">
                {{ file.fileName }}
              </button>
              <small
                >{{ plainWording(file.fileStatus) }} · 资料处理：{{
                  plainWording(file.currentOcrStatus)
                }}</small
              >
            </li>
          </ul>
        </li>
      </ul>
      <button
        v-if="ndtMaterialChecklist.length > visibleChecklist.length || checklistExpanded"
        type="button"
        class="ndt-link ndt-expand"
        :aria-expanded="checklistExpanded"
        @click="checklistExpanded = !checklistExpanded"
      >
        {{ checklistExpanded ? '收起' : `展开全部 ${ndtMaterialChecklist.length} 种` }}
      </button>
    </section>

    <!-- 摘要「待提交」滚到这里。锚点必须真实存在——选择器写了而元素没有，滚动会静默失败 -->
    <section id="ndt-pending-files" class="ndt-section" aria-label="已上传资料">
      <div class="ndt-section-head">
        <h2>已上传</h2>
        <button
          v-if="batchSubmittableAtomicFiles.length"
          type="button"
          class="ndt-link"
          :disabled="readOnly || loading"
          @click="submitAtomicFilesBatch"
        >
          全部提交
        </button>
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
      <ul v-if="atomicFileRows.length" class="ndt-card ndt-list">
        <li v-for="row in atomicFileRows" :key="row.id">
          <button type="button" class="ndt-row-main" @click="emit('viewMaterialFile', row.id)">
            <FileTypeIcon :file-name="row.fileName" />
            <span class="ndt-row-text">
              <strong>{{ row.fileName }}</strong>
              <small>{{ ndtFileSubtext(row) }}</small>
            </span>
          </button>
          <ElButton
            v-if="canRetryDocumentUpload(row.uploadStatus)"
            type="danger"
            plain
            :disabled="loading"
            @click="retryAtomicFileUpload(row)"
          >
            重新上传
          </ElButton>
          <template v-else>
            <ElTag :type="getStatusTagType(row.approvalStatus)" size="small" effect="plain">
              {{ plainWording(row.approvalStatus) }}
            </ElTag>
            <ElButton
              v-if="row.canSubmit"
              plain
              type="primary"
              :loading="loading"
              @click="submitAtomicFile(row)"
            >
              提交
            </ElButton>
          </template>
          <ElDropdown
            trigger="click"
            @command="(command: string) => handleNdtFileMenu(command, row)"
          >
            <button type="button" class="ndt-more" aria-label="更多操作">⋯</button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem command="view">查看</ElDropdownItem>
                <ElDropdownItem
                  command="submit"
                  :disabled="!row.canSubmit"
                  :title="row.canSubmit ? '' : row.submitBlockedReason"
                >
                  提交审批
                </ElDropdownItem>
                <ElDropdownItem
                  command="rules"
                  :disabled="!row.canEdit"
                  :title="row.canEdit ? '' : row.editBlockedReason"
                >
                  调整业务规则
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </li>
      </ul>
      <p v-else class="ndt-card ndt-note is-empty">还没有上传无损检测资料：用上面的按钮开始。</p>
    </section>
  </div>
</template>

<style scoped>
.ndt-workspace {
  display: grid;
  max-width: 860px;
  margin: 0 auto 18px;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

/* —— 弹窗（底片登记 / 业务规则 / 回复反馈）—— */
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

.rectify-form :deep(.el-select) {
  width: 100%;
}

.ndt-submit-error,
.ndt-rectify-error {
  margin: 4px 0 0;
}

/* —— 分区 —— */
.ndt-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.ndt-section h2 {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  font-size: 17px;
  line-height: 24px;
  color: #172033;
}

.ndt-section-head {
  display: flex;
  gap: 12px;
  align-items: baseline;
  justify-content: space-between;
}

.ndt-section-head small {
  font-size: 13px;
  color: #667085;
}

.ndt-count {
  display: inline-grid;
  height: 20px;
  min-width: 20px;
  padding: 0 6px;
  font-size: 12px;
  color: #fff;
  background: #d64545;
  border-radius: 999px;
  place-items: center;
}

.ndt-card {
  padding: 0;
  margin: 0;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
}

.ndt-note {
  margin: 0;
  font-size: 13px;
  color: #667085;
}

.ndt-note.is-empty {
  padding: 18px 16px;
  text-align: center;
}

.ndt-link {
  padding: 0;
  font: inherit;
  font-size: 13px;
  color: var(--el-color-primary, #2f6bff);
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: 0;
}

.ndt-link:disabled {
  color: #98a2b3;
  cursor: not-allowed;
}

.ndt-link.is-muted {
  justify-self: start;
  color: #667085;
}

/* —— 监检反馈卡：浅红底 + 细边 —— */
.ndt-feedback-card {
  display: grid;
  padding: 14px 16px;
  background: #fff7f6;
  border: 1px solid #f0c8c3;
  border-radius: 12px;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
  justify-items: start;
}

.ndt-feedback-card strong {
  font-size: 15px;
  line-height: 22px;
  color: #172033;
  overflow-wrap: anywhere;
}

.ndt-feedback-card p {
  margin: 0;
  font-size: 14px;
  line-height: 20px;
  color: #475467;
  overflow-wrap: anywhere;
}

.ndt-feedback-foot {
  display: flex;
  width: 100%;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}

.ndt-feedback-foot small {
  font-size: 13px;
  color: #667085;
}

.ndt-feedback-actions {
  display: flex;
  gap: 8px;
}

.ndt-feedback-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.ndt-closed {
  display: grid;
  gap: 6px;
}

/* —— 三个常用操作 —— */
.ndt-action-tiles {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.ndt-action-tiles button {
  display: grid;
  min-height: 84px;
  padding: 12px 8px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
  place-items: center;
  gap: 6px;
  text-align: center;
}

.ndt-action-tiles button:hover:not(:disabled) {
  background: #f5f8ff;
  border-color: #c9d8f6;
}

.ndt-action-tiles button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ndt-action-tiles button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.ndt-action-tiles :deep(.el-icon) {
  font-size: 24px;
  color: var(--el-color-primary, #2f6bff);
}

/* —— 一行登记数 —— */
.ndt-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.ndt-stats div {
  display: grid;
  padding: 10px 4px;
  text-align: center;
  gap: 2px;
}

.ndt-stats div + div {
  border-left: 1px solid #eef1f6;
}

.ndt-stats dt {
  font-size: 12px;
  color: #667085;
}

.ndt-stats dd {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--el-color-primary, #2f6bff);
  font-variant-numeric: tabular-nums;
}

/* —— 列表行 —— */
.ndt-list {
  display: grid;
  list-style: none;
}

.ndt-list > li {
  display: flex;
  min-height: 56px;
  padding: 8px 10px 8px 14px;
  gap: 8px;
  align-items: center;
}

.ndt-list > li + li {
  border-top: 1px solid #eef1f6;
}

.ndt-list :deep(.el-button + .el-button) {
  margin-left: 0;
}

.ndt-row-main {
  display: flex;
  min-width: 0;
  min-height: 44px;
  padding: 0;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
  flex: 1;
  gap: 10px;
  align-items: center;
}

.ndt-row-text {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.ndt-row-text strong {
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ndt-row-text small {
  overflow: hidden;
  font-size: 12px;
  color: #667085;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ndt-more {
  display: grid;
  width: 36px;
  height: 44px;
  padding: 0;
  font-size: 18px;
  color: #667085;
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: 8px;
  place-items: center;
}

.ndt-more:hover {
  background: #f2f4f7;
}

/* —— 资料类型 —— */
.ndt-list > li.ndt-material {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
}

.ndt-material-line {
  display: flex;
  min-height: 44px;
  gap: 10px;
  align-items: center;
}

.ndt-material-name {
  min-width: 0;
  font-size: 14px;
  line-height: 20px;
  color: #172033;
  flex: 1;
  overflow-wrap: anywhere;
}

.ndt-empty-count {
  font-size: 13px;
  color: #b42318;
  white-space: nowrap;
}

.ndt-uploaded-files {
  display: grid;
  padding: 8px 10px;
  margin: 0 0 4px;
  list-style: none;
  background: #f8fafc;
  border-radius: 8px;
  gap: 6px;
}

.ndt-uploaded-files li {
  display: grid;
  gap: 2px;
}

.ndt-uploaded-files .ndt-link {
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}

.ndt-uploaded-files small {
  font-size: 12px;
  color: #667085;
}

.ndt-expand {
  justify-self: center;
  min-height: 36px;
}

@media (width <= 560px) {
  .ndt-workspace {
    gap: 14px;
  }

  .ndt-film-form {
    grid-template-columns: minmax(0, 1fr);
  }

  .ndt-action-tiles button {
    min-height: 76px;
    font-size: 13px;
  }

  .ndt-feedback-actions {
    width: 100%;
  }

  .ndt-feedback-actions :deep(.el-button) {
    flex: 1;
  }
}
</style>
