<script setup lang="ts">
import { computed } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDrawer,
  ElEmpty,
  ElProgress,
  ElSkeleton,
  ElTag
} from 'element-plus'
import type { ExportTask } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  task?: ExportTask
  loading: boolean
  issue?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  download: [url: string]
  retry: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const fileSizeText = computed(() => {
  const size = props.task?.fileSize || 0
  if (!size) return '-'
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
})
const exportTypeLabel = computed(() => {
  const type = props.task?.exportType
  if (!type) return '-'
  const labelMap: Record<ExportTask['exportType'], string> = {
    report: '报告导出',
    'archive-package': '归档包',
    'evidence-package': '证据定位包',
    document: '单项资料下载',
    'config-package': '配置包导出'
  }
  return labelMap[type]
})
const isReadonlyExport = computed(() =>
  Boolean(
    props.task &&
      ['report', 'archive-package', 'evidence-package', 'document'].includes(props.task.exportType)
  )
)
const taskIssue = computed(() => {
  if (!props.task) return ''
  if (props.task.status === '失败') {
    return props.task.errorMessage || '导出任务生成失败，请重新加载状态或从原入口重新发起导出。'
  }
  if (props.task.status === '已过期') {
    return '下载地址已过期，请从原入口重新生成导出任务。'
  }
  return ''
})
</script>

<template>
  <ElDrawer v-model="visible" title="导出任务详情" size="480px" class="export-task-drawer">
    <ElSkeleton v-if="loading" :rows="6" animated />

    <ElAlert
      v-else-if="issue"
      class="export-task-error"
      type="error"
      title="导出任务详情加载失败"
      :closable="false"
      show-icon
    >
      <div class="drawer-error-content">
        <span>{{ issue }}</span>
        <ElButton link type="primary" @click="emit('retry')">重新加载导出任务</ElButton>
      </div>
    </ElAlert>

    <template v-else-if="task">
      <div class="task-head">
        <div>
          <span>任务号</span>
          <strong>{{ task.id }}</strong>
        </div>
        <ElTag :type="getStatusTagType(task.status)" effect="plain">
          {{ task.status }}
        </ElTag>
      </div>

      <ElProgress
        :percentage="task.progress"
        :status="task.status === '失败' ? 'exception' : undefined"
      />

      <ElAlert
        v-if="isReadonlyExport"
        class="readonly-export-alert"
        type="info"
        :closable="false"
        show-icon
        title="只读导出任务"
        description="该任务只生成预览或下载地址，不会修改项目资料、报告或归档状态。"
      />

      <ElAlert
        v-if="taskIssue"
        class="task-state-alert"
        :type="task.status === '失败' ? 'error' : 'warning'"
        :closable="false"
        show-icon
        :title="task.status === '失败' ? '导出任务失败' : '下载地址已过期'"
      >
        <div class="drawer-error-content">
          <span>{{ taskIssue }}</span>
          <ElButton link type="primary" @click="emit('retry')">重新加载任务状态</ElButton>
        </div>
      </ElAlert>

      <ElDescriptions :column="1" border class="task-descriptions">
        <ElDescriptionsItem label="导出类型">{{ exportTypeLabel }}</ElDescriptionsItem>
        <ElDescriptionsItem label="文件名">{{ task.fileName }}</ElDescriptionsItem>
        <ElDescriptionsItem label="文件大小">{{ fileSizeText }}</ElDescriptionsItem>
        <ElDescriptionsItem label="创建时间">{{ task.createdAt }}</ElDescriptionsItem>
        <ElDescriptionsItem label="完成时间">{{ task.finishedAt || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="过期时间">{{ task.expiresAt || '-' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="下载地址">
          <span class="download-url">{{ task.downloadUrl || '-' }}</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem v-if="task.errorMessage" label="失败原因">
          {{ task.errorMessage }}
        </ElDescriptionsItem>
      </ElDescriptions>

      <ElButton
        type="primary"
        class="download-button"
        :disabled="!task.downloadUrl || task.status !== '可下载'"
        @click="emit('download', task.downloadUrl!)"
      >
        下载文件
      </ElButton>
    </template>

    <ElEmpty v-else description="暂无导出任务" />
  </ElDrawer>
</template>

<style scoped>
.task-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.task-head span {
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: #667085;
}

.task-head strong {
  color: #1f2937;
}

.task-descriptions {
  margin-top: 14px;
}

.readonly-export-alert {
  margin-top: 14px;
}

.task-state-alert {
  margin-top: 12px;
}

.download-url {
  overflow-wrap: anywhere;
}

.download-button {
  width: 100%;
  margin-top: 14px;
}

.drawer-error-content {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  line-height: 1.6;
}

.drawer-error-content span {
  overflow-wrap: anywhere;
}

@media (max-width: 768px) {
  :global(.export-task-drawer.el-drawer) {
    width: 100vw !important;
    max-width: 100vw;
  }

  .drawer-error-content {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
