<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleCheck, WarningFilled } from '@element-plus/icons-vue'
import { ElAlert, ElButton, ElCard } from 'element-plus'
import UploadFilePicker from '../UploadFilePicker.vue'
import { canSubmitInlineUpload } from '../uploadFileSelection'
import type { ContractorWorkbenchModel } from './contractorWorkbenchViewModel'

const props = defineProps<{
  recentUpload: ContractorWorkbenchModel['recentUpload']
  loading: boolean
  readOnly?: boolean
  operationError?: string
  resetKey?: number
}>()

const emit = defineEmits<{
  submit: [files: File[]]
  'recent-filter': [filter: '全部' | '上传中' | '失败']
}>()

const selectedFiles = ref<File[]>([])
const canSubmit = computed(
  () => !props.readOnly && canSubmitInlineUpload(selectedFiles.value, props.loading)
)
const primaryActionLabel = computed(() =>
  selectedFiles.value.length ? `上传 ${selectedFiles.value.length} 个文件` : '请选择文件'
)

const submit = () => {
  if (canSubmit.value) emit('submit', [...selectedFiles.value])
}

watch(
  () => props.resetKey,
  () => {
    selectedFiles.value = []
  }
)
</script>

<template>
  <ElCard class="contractor-work-panel contractor-upload-panel" shadow="never">
    <template #header>
      <div class="panel-head">
        <div>
          <h2>一、统一上传资料</h2>
          <p>文件上传后由系统识别资料类别，可一次选择多个文件。</p>
        </div>
      </div>
    </template>

    <ElAlert
      v-if="operationError"
      class="inline-upload-error"
      type="error"
      title="上传失败"
      :closable="false"
      show-icon
    >
      <div class="inline-upload-error-content">
        <span>{{ operationError }}</span>
        <ElButton link type="primary" :loading="loading" @click="submit">重新上传</ElButton>
      </div>
    </ElAlert>

    <UploadFilePicker v-model="selectedFiles" compact :disabled="loading || readOnly" />

    <div v-if="selectedFiles.length" class="inline-upload-actions">
      <span>已选择 {{ selectedFiles.length }} 个文件</span>
      <ElButton type="primary" :loading="loading" :disabled="!canSubmit" @click="submit">
        {{ primaryActionLabel }}
      </ElButton>
    </div>

    <div class="recent-upload" aria-label="最近上传摘要">
      <button type="button" @click="emit('recent-filter', '全部')">
        最近上传：{{ recentUpload.total }} 个文件，{{ recentUpload.successful }} 个上传成功
      </button>
      <button
        v-if="recentUpload.processing"
        type="button"
        class="recent-state is-processing"
        @click="emit('recent-filter', '上传中')"
      >
        {{ recentUpload.processing }} 个处理中
      </button>
      <button
        v-if="recentUpload.failed"
        type="button"
        class="recent-state is-failed"
        @click="emit('recent-filter', '失败')"
      >
        <WarningFilled aria-hidden="true" />
        {{ recentUpload.failed }} 个失败
      </button>
      <CircleCheck
        v-else-if="recentUpload.total && !recentUpload.processing"
        class="recent-complete"
        aria-label="最近上传已处理完成"
      />
    </div>
  </ElCard>
</template>

<style scoped>
.contractor-work-panel {
  height: 100%;
  border: 0;
  border-radius: 8px;
  box-shadow: 0 6px 18px rgb(15 23 42 / 6%);
}

.contractor-work-panel :deep(.el-card__header) {
  padding: 14px 16px 10px;
  border-bottom: 0;
}

.contractor-work-panel :deep(.el-card__body) {
  padding: 0 16px 14px;
}

.panel-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
}

.panel-head p {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: #667085;
}

.inline-upload-error {
  margin-bottom: 10px;
}

.inline-upload-error-content,
.inline-upload-actions,
.recent-upload {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.inline-upload-actions {
  padding-top: 10px;
  font-size: 13px;
  color: #526178;
}

.recent-upload {
  min-height: 28px;
  margin-top: 10px;
  font-size: 13px;
  color: #526178;
  justify-content: flex-start;
}

.recent-upload button {
  padding: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.recent-upload button:hover {
  color: #2f6fed;
}

.recent-state {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.recent-state svg,
.recent-complete {
  width: 16px;
  height: 16px;
}

.recent-state.is-processing {
  color: #d97706;
}

.recent-state.is-failed {
  color: #dc2626;
}

.recent-complete {
  color: #12a66a;
}
</style>
