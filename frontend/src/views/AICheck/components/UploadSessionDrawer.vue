<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElAlert, ElButton, ElDrawer, ElMessage, ElTable, ElTableColumn } from 'element-plus'

const props = defineProps<{
  modelValue: boolean
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

const fileInputRef = ref<HTMLInputElement>()
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
  return fileCount > 0 ? `上传 ${fileCount} 个文件并入库` : '选择文件'
})

const resetFiles = () => {
  selectedFiles.value = []
  if (fileInputRef.value) fileInputRef.value.value = ''
}

const appendFiles = (fileList: FileList | File[]) => {
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

const handleFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files) appendFiles(input.files)
}

const handleDrop = (event: DragEvent) => {
  event.preventDefault()
  if (event.dataTransfer?.files) appendFiles(event.dataTransfer.files)
}

const openFilePicker = () => {
  fileInputRef.value?.click()
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

const handlePrimaryAction = () => {
  if (!selectedFiles.value.length) {
    openFilePicker()
    return
  }
  handleSubmit()
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
  <ElDrawer v-model="visible" title="上传项目文件" size="min(560px, 94vw)" append-to-body>
    <div class="drawer-body">
      <div class="helper-text">选择本地文件后，系统将创建真实上传会话并写入项目资料池。</div>
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

      <input
        ref="fileInputRef"
        class="native-file-input"
        type="file"
        multiple
        accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png,.zip"
        @change="handleFileChange"
      />

      <button
        type="button"
        class="file-drop-zone"
        @click="openFilePicker"
        @dragover.prevent
        @drop="handleDrop"
      >
        <strong>选择或拖拽文件到此处</strong>
        <span>支持 pdf、doc、docx、xls、xlsx、jpg、png、zip</span>
      </button>

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
        <ElButton type="primary" :loading="loading" @click="handlePrimaryAction">
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

.helper-text {
  padding: 10px 12px;
  line-height: 1.6;
  color: #475467;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
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

.native-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  clip-path: inset(50%);
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
  cursor: pointer;
  background: #f8fbff;
  border: 1px dashed #9ec5fe;
  border-radius: 8px;
  transition:
    background 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.file-drop-zone:hover,
.file-drop-zone:focus-visible {
  background: #eef6ff;
  border-color: #2f6fed;
  outline: none;
  box-shadow: 0 0 0 3px rgb(47 111 237 / 12%);
}

.file-drop-zone strong {
  font-size: 18px;
  font-weight: 700;
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
