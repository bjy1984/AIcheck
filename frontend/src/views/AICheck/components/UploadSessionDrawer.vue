<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDrawer,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn
} from 'element-plus'

type UploadDraft = {
  id: number
  fileName: string
  fileType: string
  fileSizeKb: number
}

const props = defineProps<{
  modelValue: boolean
  nodeName?: string
  loading: boolean
  operationError?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [files: Array<{ fileName: string; fileType: string; fileSize: number }>]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const drafts = reactive<UploadDraft[]>([])

const resetDrafts = () => {
  drafts.splice(0, drafts.length, {
    id: Date.now(),
    fileName: `${props.nodeName || '节点资料'}-补充资料.pdf`,
    fileType: 'pdf',
    fileSizeKb: 240
  })
}

const addDraft = () => {
  drafts.push({
    id: Date.now() + drafts.length,
    fileName: '',
    fileType: 'pdf',
    fileSizeKb: 240
  })
}

const removeDraft = (id: number) => {
  if (drafts.length === 1) {
    ElMessage.warning('至少保留一个待上传文件')
    return
  }
  const index = drafts.findIndex((item) => item.id === id)
  if (index >= 0) drafts.splice(index, 1)
}

const handleSubmit = () => {
  const invalid = drafts.find((item) => !item.fileName.trim() || !item.fileType)
  if (invalid) {
    ElMessage.warning('请补齐文件名称和类型')
    return
  }
  emit(
    'submit',
    drafts.map((item) => ({
      fileName: item.fileName.trim(),
      fileType: item.fileType,
      fileSize: item.fileSizeKb * 1024
    }))
  )
}

const handleRetry = () => {
  handleSubmit()
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetDrafts()
  }
)
</script>

<template>
  <ElDrawer v-model="visible" title="创建上传会话" size="min(560px, 94vw)" append-to-body>
    <div class="drawer-body">
      <div class="helper-text">
        当前为 mock 上传，会直接把文件写入项目资料池，并生成可挂载版本。
      </div>

      <ElAlert
        v-if="operationError"
        class="upload-drawer-error"
        type="error"
        title="上传会话创建失败"
        :closable="false"
        show-icon
      >
        <div class="drawer-error-content">
          <span>{{ operationError }}</span>
          <ElButton link type="primary" :loading="loading" @click="handleRetry">重试创建</ElButton>
        </div>
      </ElAlert>

      <div class="upload-table-shell">
        <ElTable class="upload-table" :data="drafts" border>
          <ElTableColumn label="文件名称" min-width="220">
            <template #default="{ row }">
              <ElInput v-model="row.fileName" aria-label="文件名称" />
            </template>
          </ElTableColumn>
          <ElTableColumn label="类型" width="110">
            <template #default="{ row }">
              <ElSelect v-model="row.fileType" aria-label="文件类型">
                <ElOption label="PDF" value="pdf" />
                <ElOption label="Excel" value="xlsx" />
                <ElOption label="Word" value="docx" />
                <ElOption label="图片" value="jpg" />
              </ElSelect>
            </template>
          </ElTableColumn>
          <ElTableColumn label="大小 KB" width="130">
            <template #default="{ row }">
              <ElInputNumber
                v-model="row.fileSizeKb"
                aria-label="文件大小 KB"
                :min="1"
                :max="51200"
                controls-position="right"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="80">
            <template #default="{ row }">
              <ElButton link type="danger" @click="removeDraft(row.id)">移除</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>

      <div class="drawer-actions">
        <ElButton @click="addDraft">添加文件</ElButton>
        <ElButton @click="visible = false">取消</ElButton>
        <ElButton type="primary" :loading="loading" @click="handleSubmit">创建并入库</ElButton>
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

@media (max-width: 520px) {
  .drawer-error-content,
  .drawer-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
