<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type {
  DocumentAsset,
  NodeFileBinding,
  NodePackagePayload,
  ProjectTreeNode,
  RoleCode
} from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  packageData?: NodePackagePayload
  treeGroups: Array<{ groupName: string; nodes: ProjectTreeNode[] }>
  role: RoleCode
  loading: boolean
  operationError?: string
  initialDocumentId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [
    payload: {
      nodeId?: number
      nodeIds: number[]
      bindings: Array<Pick<NodeFileBinding, 'documentId' | 'documentVersionId' | 'usage'>>
    }
  ]
}>()

const form = reactive({
  documentId: '',
  documentVersionId: '',
  usage: '原始提交' as NodeFileBinding['usage'],
  targetNodeIds: [] as number[]
})

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const projectFiles = computed(() => props.packageData?.projectFiles || [])
const projectFileStatus = (file: DocumentAsset) =>
  file.primaryBinding?.bindingStatus || file.bindings?.[0]?.bindingStatus || file.fileStatus
const selectedFile = computed<DocumentAsset | undefined>(() =>
  projectFiles.value.find((item) => item.id === form.documentId)
)
const versionOptions = computed(() =>
  (props.packageData?.availableVersions || []).filter((item) => item.documentId === form.documentId)
)
const selectedNode = computed(() => props.packageData?.node)
const nodeOptions = computed(() =>
  props.treeGroups.flatMap((group) =>
    group.nodes.map((node) => ({
      nodeId: node.nodeId,
      label: `${String(node.nodeId).padStart(2, '0')} · ${node.name}`,
      groupName: group.groupName,
      disabled: node.status === '已归档'
    }))
  )
)
const isContractor = computed(() => props.role === 'contractor')
const dialogTitle = computed(() =>
  isContractor.value ? '关联项目文件到审核环节' : '挂载资料到节点'
)

const resetForm = () => {
  const initialFile = props.initialDocumentId
    ? projectFiles.value.find((item) => item.id === props.initialDocumentId)
    : undefined
  const firstFile = initialFile || projectFiles.value[0]
  form.documentId = firstFile?.id || ''
  form.documentVersionId = firstFile?.currentVersionId || ''
  form.usage = props.role === 'ndt' ? '检测报告' : '原始提交'
  form.targetNodeIds = selectedNode.value ? [selectedNode.value.nodeId] : []
}

const handleFileChange = () => {
  form.documentVersionId = versionOptions.value[0]?.id || ''
}

const handleSubmit = () => {
  if (!selectedNode.value) {
    ElMessage.warning('请先选择节点')
    return
  }
  if (!form.documentId || !form.documentVersionId) {
    ElMessage.warning('请选择文件和版本')
    return
  }
  if (!form.targetNodeIds.length) {
    ElMessage.warning(isContractor.value ? '请选择至少一个审核环节' : '请选择至少一个目标节点')
    return
  }
  emit('submit', {
    nodeId: selectedNode.value.nodeId,
    nodeIds: form.targetNodeIds,
    bindings: [
      {
        documentId: form.documentId,
        documentVersionId: form.documentVersionId,
        usage: form.usage
      }
    ]
  })
}

const handleRetry = () => {
  handleSubmit()
}

watch(
  () => [props.modelValue, props.initialDocumentId] as const,
  ([open]) => {
    if (open) resetForm()
  }
)
</script>

<template>
  <ElDialog v-model="visible" :title="dialogTitle" width="760px" append-to-body>
    <template v-if="packageData && projectFiles.length">
      <ElDescriptions :column="2" border class="node-summary">
        <ElDescriptionsItem label="当前节点">
          {{ selectedNode?.nodeId }} · {{ selectedNode?.name }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="节点状态">
          <ElTag :type="getStatusTagType(selectedNode?.status)" size="small">
            {{ selectedNode?.status }}
          </ElTag>
        </ElDescriptionsItem>
      </ElDescriptions>

      <ElAlert
        v-if="operationError"
        :closable="false"
        type="error"
        show-icon
        class="bind-alert bind-dialog-error"
        :title="isContractor ? '关联审核环节失败' : '资料挂载失败'"
      >
        <div class="dialog-error-content">
          <span>{{ operationError }}</span>
          <ElButton link type="primary" :loading="loading" @click="handleRetry">
            {{ isContractor ? '重试关联' : '重试挂载' }}
          </ElButton>
        </div>
      </ElAlert>

      <ElForm label-position="top" class="bind-form">
        <ElFormItem label="项目资料">
          <ElSelect v-model="form.documentId" filterable @change="handleFileChange">
            <ElOption
              v-for="file in projectFiles"
              :key="file.id"
              :label="file.fileName"
              :value="file.id"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="资料版本">
          <ElSelect v-model="form.documentVersionId">
            <ElOption
              v-for="version in versionOptions"
              :key="version.id"
              :label="version.versionNo"
              :value="version.id"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem :label="isContractor ? '文件用途' : '挂载用途'">
          <ElSelect v-model="form.usage">
            <ElOption label="原始提交" value="原始提交" />
            <ElOption label="补正附件" value="补正附件" />
            <ElOption label="整改说明" value="整改说明" />
            <ElOption label="证明材料" value="证明材料" />
            <ElOption label="监检资料" value="监检资料" />
            <ElOption label="检测报告" value="检测报告" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem :label="isContractor ? '关联审核环节' : '目标节点'" class="target-node-field">
          <ElSelect
            v-model="form.targetNodeIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
          >
            <ElOption
              v-for="node in nodeOptions"
              :key="node.nodeId"
              :label="`${node.label} / ${node.groupName}`"
              :value="node.nodeId"
              :disabled="node.disabled"
            />
          </ElSelect>
        </ElFormItem>
      </ElForm>

      <ElTable :data="projectFiles" border height="180">
        <ElTableColumn prop="fileName" label="资料池文件" min-width="220" show-overflow-tooltip />
        <ElTableColumn prop="sourceOrgName" label="来源" width="150" show-overflow-tooltip />
        <ElTableColumn prop="currentOcrStatus" label="OCR" width="100" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(projectFileStatus(row))" size="small" effect="plain">
              {{ projectFileStatus(row) }}
            </ElTag>
          </template>
        </ElTableColumn>
      </ElTable>

      <div v-if="selectedFile" class="selected-file">
        已选择：{{ selectedFile.fileName }} / {{ form.usage }}
      </div>
    </template>

    <ElEmpty
      v-else
      :description="isContractor ? '项目文件库暂无可关联文件' : '资料池暂无可挂载文件'"
    />

    <template #footer>
      <ElButton @click="visible = false">取消</ElButton>
      <ElButton
        type="primary"
        :loading="loading"
        :disabled="!projectFiles.length"
        @click="handleSubmit"
      >
        {{ isContractor ? '确认关联' : '确认挂载' }}
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.node-summary,
.bind-alert {
  margin-bottom: 14px;
}

.bind-form {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) 140px 140px minmax(0, 1.4fr);
  gap: 12px;
  align-items: start;
}

.target-node-field {
  min-width: 0;
}

.selected-file {
  margin-top: 12px;
  font-size: 13px;
  color: #475467;
}

.dialog-error-content {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
  line-height: 1.5;
}

@media (width <= 768px) {
  .bind-form {
    grid-template-columns: 1fr;
  }

  .dialog-error-content {
    align-items: flex-start;
  }
}
</style>
