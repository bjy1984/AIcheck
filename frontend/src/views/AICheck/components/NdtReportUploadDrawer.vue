<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDrawer,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElUpload
} from 'element-plus'
import type { FormInstance, FormRules, UploadFile, UploadInstance } from 'element-plus'
import type { NdtReportUploadRequest } from '@/api/aicheck'
import type { NdtFilm } from '@/types/aicheck'

type SubmitPayload = Omit<NdtReportUploadRequest, 'nodeId' | 'files'> & { files: File[] }

const props = defineProps<{
  modelValue: boolean
  nodeName?: string
  films: NdtFilm[]
  loading: boolean
  operationError?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: SubmitPayload]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})
const formRef = ref<FormInstance>()
const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File>()
const form = reactive({
  reportNo: '',
  entrustNo: '',
  method: 'RT' as NdtFilm['method'],
  detectionRatio: '10%',
  standardCode: 'NB/T 47013.2-2015',
  evaluatorName: '',
  reviewerName: '',
  conclusion: 'II级合格',
  relatedFilmIds: [] as string[]
})

const rules: FormRules = {}

const fileLabel = computed(() =>
  selectedFile.value
    ? `${selectedFile.value.name}（${Math.max(1, Math.round(selectedFile.value.size / 1024))} KB）`
    : '尚未选择报告文件'
)

const reset = () => {
  form.reportNo = ''
  form.entrustNo = ''
  form.method = 'RT'
  form.detectionRatio = '10%'
  form.standardCode = 'NB/T 47013.2-2015'
  form.evaluatorName = ''
  form.reviewerName = ''
  form.conclusion = 'II级合格'
  form.relatedFilmIds = []
  selectedFile.value = undefined
  uploadRef.value?.clearFiles()
  formRef.value?.clearValidate()
}

const handleUploadChange = (uploadFile: UploadFile) => {
  selectedFile.value = uploadFile.raw
}

const handleMethodChange = (method: NdtFilm['method']) => {
  if (method !== 'RT') {
    form.relatedFilmIds = []
    form.detectionRatio = ''
  } else {
    form.detectionRatio ||= '10%'
    form.standardCode ||= 'NB/T 47013.2-2015'
  }
}

const handleSubmit = async () => {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!selectedFile.value) {
    ElMessage.warning('请选择一份检测报告文件')
    return
  }
  emit('submit', {
    files: [selectedFile.value],
    reportNo: form.reportNo.trim(),
    entrustNo: form.entrustNo.trim() || undefined,
    method: form.method,
    detectionRatio: form.detectionRatio.trim() || undefined,
    standardCode: form.standardCode.trim(),
    evaluatorName: form.evaluatorName.trim(),
    reviewerName: form.reviewerName.trim() || undefined,
    conclusion: form.conclusion.trim(),
    relatedFilmIds: [...form.relatedFilmIds]
  })
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  }
)
</script>

<template>
  <ElDrawer v-model="visible" title="上传无损检测报告" size="min(680px, 96vw)" append-to-body>
    <div class="drawer-body">
      <ElAlert
        v-if="operationError"
        type="error"
        title="检测报告上传失败"
        :description="operationError"
        :closable="false"
        show-icon
      />

      <div class="upload-context">
        <span>办理节点</span>
        <strong>{{ nodeName || '无损检测节点' }}</strong>
      </div>

      <ElForm ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="form-grid">
          <ElFormItem label="报告编号" prop="reportNo">
            <ElInput v-model="form.reportNo" placeholder="例如：RT-R2-20260722-001" />
          </ElFormItem>
          <ElFormItem label="委托编号">
            <ElInput v-model="form.entrustNo" placeholder="请输入委托编号" />
          </ElFormItem>
          <ElFormItem label="检测方法" prop="method">
            <ElSelect v-model="form.method" @change="handleMethodChange">
              <ElOption label="RT 射线检测" value="RT" />
              <ElOption label="UT 超声检测" value="UT" />
              <ElOption label="MT 磁粉检测" value="MT" />
              <ElOption label="PT 渗透检测" value="PT" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="检测比例">
            <ElInput
              v-model="form.detectionRatio"
              :disabled="form.method !== 'RT'"
              placeholder="例如：10%"
            />
          </ElFormItem>
          <ElFormItem label="执行标准" prop="standardCode" class="full-width">
            <ElInput v-model="form.standardCode" placeholder="例如：NB/T 47013.2-2015" />
          </ElFormItem>
          <ElFormItem label="检测人员" prop="evaluatorName">
            <ElInput v-model="form.evaluatorName" placeholder="请输入检测人员姓名" />
          </ElFormItem>
          <ElFormItem label="复核人员">
            <ElInput v-model="form.reviewerName" placeholder="请输入复核人员姓名" />
          </ElFormItem>
          <ElFormItem label="检测结论（RT 必须包含合格级别）" prop="conclusion" class="full-width">
            <ElInput
              v-model="form.conclusion"
              type="textarea"
              :rows="3"
              placeholder="例如：RT II级合格"
            />
          </ElFormItem>
          <ElFormItem v-if="form.method === 'RT'" label="关联底片/影像" class="full-width">
            <ElCheckboxGroup v-model="form.relatedFilmIds" class="film-options">
              <ElCheckbox v-for="film in films" :key="film.id" :value="film.id">
                {{ film.filmNo }} · {{ film.weldNo }}
              </ElCheckbox>
            </ElCheckboxGroup>
            <span v-if="!films.length" class="empty-hint"
              >暂无可关联底片，请先登记底片或影像。</span
            >
          </ElFormItem>
        </div>
      </ElForm>

      <ElUpload
        ref="uploadRef"
        class="report-uploader"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :limit="1"
        accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.zip,.dcm"
        :on-change="handleUploadChange"
      >
        <div class="drop-zone">
          <strong>选择一份检测报告文件</strong>
          <span>支持 PDF、Word、图片、ZIP 和 DICOM 文件</span>
        </div>
      </ElUpload>
      <div class="selected-file">{{ fileLabel }}</div>

      <div class="drawer-actions">
        <ElButton @click="visible = false">取消</ElButton>
        <ElButton type="primary" :loading="loading" @click="handleSubmit"
          >上传并生成检测报告</ElButton
        >
      </div>
    </div>
  </ElDrawer>
</template>

<style scoped>
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.upload-context,
.selected-file {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  color: #475467;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.full-width {
  grid-column: 1 / -1;
}

.film-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
}

.empty-hint {
  color: #b45309;
}

.report-uploader,
.report-uploader :deep(.el-upload),
.report-uploader :deep(.el-upload-dragger) {
  width: 100%;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 24px;
  color: #344054;
}

.drawer-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

@media (width <= 640px) {
  .form-grid,
  .film-options {
    grid-template-columns: 1fr;
  }
}
</style>
