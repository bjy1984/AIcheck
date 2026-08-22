<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElButton, ElMessage, ElUpload } from 'element-plus'
import type { UploadFile, UploadInstance } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import {
  acceptedUploadFilesFromList,
  appendUniqueUploadFiles,
  isAcceptedUploadFile,
  rawFilesFromUploadList,
  removeUploadFileByIdentity
} from './uploadFileSelection'

const props = withDefaults(
  defineProps<{
    modelValue: File[]
    disabled?: boolean
    compact?: boolean
  }>(),
  {
    disabled: false,
    compact: false
  }
)

const emit = defineEmits<{
  'update:modelValue': [files: File[]]
}>()

const uploadRef = ref<UploadInstance>()
const internalUploadFiles = ref<UploadFile[]>([])
const accept = '.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.zip'
const fileRows = computed(() =>
  props.modelValue.map((file) => ({
    id: `${file.name}:${file.size}:${file.lastModified}`,
    file,
    name: file.name,
    meta: `${file.name.split('.').pop()?.toUpperCase() || 'FILE'} · ${Math.max(
      1,
      Math.round(file.size / 1024)
    )} KB`
  }))
)

const appendFiles = (files: File[]) => {
  const accepted = files.filter((file) => isAcceptedUploadFile(file.name))
  if (accepted.length !== files.length) {
    ElMessage.warning('仅支持 PDF、Word、Excel、图片和 ZIP 文件')
  }
  emit('update:modelValue', appendUniqueUploadFiles(props.modelValue, accepted))
}

const handleUploadChange = (_current: UploadFile, uploadFiles: UploadFile[]) => {
  const acceptedUploadFiles = acceptedUploadFilesFromList(uploadFiles)
  const rejectedUploadFiles = uploadFiles.filter(
    (uploadFile) => uploadFile.raw && !isAcceptedUploadFile(uploadFile.raw.name)
  )
  internalUploadFiles.value = acceptedUploadFiles
  appendFiles(rawFilesFromUploadList(uploadFiles))
  rejectedUploadFiles.forEach((uploadFile) => uploadRef.value?.handleRemove(uploadFile))
}

const removeFile = (id: string) => {
  const row = fileRows.value.find((item) => item.id === id)
  if (!row) return

  const internalUploadFile = internalUploadFiles.value.find(
    (uploadFile) =>
      uploadFile.raw &&
      `${uploadFile.raw.name}:${uploadFile.raw.size}:${uploadFile.raw.lastModified}` === id
  )
  if (internalUploadFile) uploadRef.value?.handleRemove(internalUploadFile)
  internalUploadFiles.value = removeUploadFileByIdentity(internalUploadFiles.value, row.file)

  emit(
    'update:modelValue',
    fileRows.value.filter((item) => item.id !== id).map((item) => item.file)
  )
}

watch(
  () => props.modelValue.length,
  (length) => {
    if (!length) uploadRef.value?.clearFiles()
  }
)
</script>

<template>
  <div :class="['upload-file-picker', { 'is-compact': compact }]">
    <ElUpload
      ref="uploadRef"
      class="file-uploader"
      drag
      multiple
      :disabled="disabled"
      :auto-upload="false"
      :show-file-list="false"
      :accept="accept"
      :on-change="handleUploadChange"
    >
      <div class="file-drop-zone">
        <UploadFilled class="upload-file-icon" aria-hidden="true" />
        <strong>将文件拖到此处</strong>
        <span>系统将自动识别资料类别，支持一次上传多个文件</span>
        <ElButton type="primary" :disabled="disabled">选择文件</ElButton>
      </div>
    </ElUpload>

    <ul v-if="fileRows.length" class="selected-files" aria-label="待上传文件">
      <li v-for="row in fileRows" :key="row.id">
        <span>
          <strong>{{ row.name }}</strong>
          <small>{{ row.meta }}</small>
        </span>
        <ElButton link type="danger" :disabled="disabled" @click.stop="removeFile(row.id)">
          移除
        </ElButton>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.upload-file-picker,
.file-uploader,
.file-uploader :deep(.el-upload),
.file-uploader :deep(.el-upload-dragger) {
  width: 100%;
}

.file-uploader :deep(.el-upload-dragger) {
  padding: 0;
  background: #fbfdff;
  border-color: #8fb2ff;
  border-radius: 8px;
}

.file-uploader :deep(.el-upload-dragger:hover),
.file-uploader :deep(.el-upload-dragger:focus-visible) {
  background: #f3f7ff;
  border-color: #2f6fed;
  outline: none;
  box-shadow: 0 0 0 3px rgb(47 111 237 / 12%);
}

.file-drop-zone {
  display: flex;
  flex-direction: column;
  gap: 9px;
  align-items: center;
  justify-content: center;
  min-height: 178px;
  padding: 22px;
  color: #26344d;
  text-align: center;
}

.is-compact .file-drop-zone {
  min-height: 150px;
}

.upload-file-icon {
  width: 42px;
  height: 42px;
  color: #2f6fed;
}

.file-drop-zone strong {
  font-size: 17px;
  font-weight: 600;
}

.file-drop-zone span {
  font-size: 13px;
  line-height: 1.5;
  color: #64748b;
}

.selected-files {
  display: grid;
  gap: 6px;
  padding: 0;
  margin: 10px 0 0;
  list-style: none;
}

.selected-files li {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid #e3e9f2;
  border-radius: 6px;
}

.selected-files li > span {
  display: grid;
  min-width: 0;
  text-align: left;
}

.selected-files strong {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selected-files small {
  font-size: 12px;
  color: #7a879b;
}
</style>
