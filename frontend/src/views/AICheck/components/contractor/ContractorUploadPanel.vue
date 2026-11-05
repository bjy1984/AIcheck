<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleCheck, WarningFilled } from '@element-plus/icons-vue'
import { ElAlert, ElButton } from 'element-plus'
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
  <!-- 2026-11-04 手机简化稿：一个大按钮，选完再点「上传 N 个文件」；最近上传一行带过 -->
  <section class="contractor-upload-panel" aria-label="上传资料" data-guide="contractor-upload">
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

    <UploadFilePicker v-model="selectedFiles" variant="button" :disabled="loading || readOnly" />
    <p class="upload-hint">可一次选多个文件，系统自动识别资料类别</p>

    <div v-if="selectedFiles.length" class="inline-upload-actions">
      <span>已选择 {{ selectedFiles.length }} 个文件</span>
      <ElButton type="primary" :loading="loading" :disabled="!canSubmit" @click="submit">
        {{ primaryActionLabel }}
      </ElButton>
    </div>

    <div v-if="recentUpload.total" class="recent-upload" aria-label="最近上传摘要">
      <button type="button" @click="emit('recent-filter', '全部')">
        最近上传 {{ recentUpload.total }} 个，{{ recentUpload.successful }} 个成功
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
        v-else-if="!recentUpload.processing"
        class="recent-complete"
        aria-label="最近上传已处理完成"
      />
    </div>
  </section>
</template>

<style scoped>
.contractor-upload-panel {
  display: grid;
  margin-bottom: 18px;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.upload-hint {
  margin: 0;
  font-size: 13px;
  color: #667085;
  text-align: center;
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
