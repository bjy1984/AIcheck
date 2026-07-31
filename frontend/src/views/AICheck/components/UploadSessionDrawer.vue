<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDrawer,
  ElMessage,
  ElTable,
  ElTableColumn,
  ElUpload
} from 'element-plus'
import type { UploadFile, UploadInstance } from 'element-plus'

const props = defineProps<{
  modelValue: boolean
  title?: string
  nodeName?: string
  materialCategory?: string
  loading: boolean
  operationError?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [files: File[]]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const uploadRef = ref<UploadInstance>()
const selectedFiles = ref<File[]>([])

const fileRows = computed(() =>
  selectedFiles.value.map((file, index) => ({
    id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
    file,
    fileName: file.name,
    fileType: file.type || file.name.split('.').pop()?.toLowerCase() || 'unknown',
    fileSizeKb: Math.max(1, Math.round(file.size / 1024))
  }))
)

const primaryActionLabel = computed(() => {
  const fileCount = selectedFiles.value.length
  return fileCount > 0 ? `上传 ${fileCount} 个文件` : '请先选择文件'
})

const resetFiles = () => {
  selectedFiles.value = []
  uploadRef.value?.clearFiles()
}

const appendFiles = (fileList: File[]) => {
  const incoming = Array.from(fileList)
  if (!incoming.length) return
  const existingKeys = new Set(
    selectedFiles.value.map((file) => `${file.name}:${file.size}:${file.lastModified}`)
  )
  selectedFiles.value = [
    ...selectedFiles.value,
    ...incoming.filter((file) => {
      const key = `${file.name}:${file.size}:${file.lastModified}`
      if (existingKeys.has(key)) return false
      existingKeys.add(key)
      return true
    })
  ]
}

const handleUploadChange = (uploadFile: UploadFile) => {
  if (uploadFile.raw) appendFiles([uploadFile.raw])
}

const removeFile = (id: string) => {
  selectedFiles.value = fileRows.value.filter((row) => row.id !== id).map((row) => row.file)
}

const handleSubmit = () => {
  if (!selectedFiles.value.length) {
    ElMessage.warning('请选择至少一个本地文件')
    return
  }
  emit('submit', selectedFiles.value)
}

const handleRetry = () => {
  handleSubmit()
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetFiles()
  }
)
</script>

<template>
  <ElDrawer
    v-model="visible"
    :title="title || '上传项目文件'"
    size="min(560px, 94vw)"
    append-to-body
  >
    <div class="drawer-body">
      <div v-if="materialCategory" class="target-category">
        <span>资料类别</span>
        <strong>{{ materialCategory }}</strong>
      </div>

      <ElAlert
        v-if="operationError"
        class="upload-drawer-error"
        type="error"
        title="上传失败"
        :closable="false"
        show-icon
      >
        <div class="drawer-error-content">
          <span>{{ operationError }}</span>
          <ElButton link type="primary" :loading="loading" @click="handleRetry">重试上传</ElButton>
        </div>
      </ElAlert>

      <ElUpload
        ref="uploadRef"
        class="file-uploader"
        drag
        multiple
        :auto-upload="false"
        :show-file-list="false"
        accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.zip"
        :on-change="handleUploadChange"
      >
        <div class="file-drop-zone">
          <strong>选择或拖拽文件到此处</strong>
          <span>支持 pdf、doc、docx、xls、xlsx、jpg、png、zip，可一次选择多个文件</span>
        </div>
      </ElUpload>

      <div class="upload-table-shell">
        <ElTable class="upload-table" :data="fileRows" border>
          <ElTableColumn prop="fileName" label="文件名称" min-width="260" show-overflow-tooltip />
          <ElTableColumn prop="fileType" label="类型" width="150" show-overflow-tooltip />
          <ElTableColumn prop="fileSizeKb" label="大小 KB" width="120" />
          <ElTableColumn label="操作" width="80">
            <template #default="{ row }">
              <ElButton link type="danger" @click="removeFile(row.id)">移除</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>

      <div class="drawer-actions">
        <ElButton @click="visible = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="loading"
          :disabled="!selectedFiles.length"
          @click="handleSubmit"
        >
          {{ primaryActionLabel }}
        </ElButton>
      </div>
    </div>
  </ElDrawer>
</template>

<style scoped>
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.target-category {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
}

.target-category span {
  color: #475467;
}

.upload-drawer-error {
  align-items: flex-start;
}

.drawer-error-content {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  line-height: 1.6;
}

.file-uploader,
.file-uploader :deep(.el-upload),
.file-uploader :deep(.el-upload-dragger) {
  width: 100%;
}

.file-drop-zone {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  min-height: 172px;
  padding: 24px;
  color: #344054;
  text-align: center;
}

.file-uploader :deep(.el-upload-dragger:hover),
.file-uploader :deep(.el-upload-dragger:focus-visible) {
  background: #eef6ff;
  border-color: #2f6fed;
  outline: none;
  box-shadow: 0 0 0 3px rgb(47 111 237 / 12%);
}

.file-drop-zone strong {
  font-size: 18px;
  font-weight: 600;
}

.file-drop-zone span {
  color: #667085;
  text-align: center;
}

.upload-table-shell {
  width: 100%;
  overflow-x: auto;
}

.upload-table {
  min-width: 540px;
}

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 6px;
}

@media (width <= 520px) {
  .drawer-error-content,
  .drawer-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
