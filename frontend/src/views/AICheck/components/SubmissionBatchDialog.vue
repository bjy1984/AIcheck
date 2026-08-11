<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { SubmissionDraftDetailPayload } from '@/api/aicheck'
import type { NodeFileBinding, NodePackagePayload, ProjectTreeNode } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  packageData?: NodePackagePayload
  treeGroups: Array<{ groupName: string; nodes: ProjectTreeNode[] }>
  draftDetail?: SubmissionDraftDetailPayload
  loading: boolean
  operationError?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [
    payload: {
      nodeIds: number[]
      bindingIds: string[]
      batchName: string
      submitterComment: string
    }
  ]
  saveDraft: [
    payload: {
      nodeIds: number[]
      bindingIds: string[]
      batchName: string
      remark: string
    }
  ]
}>()

const form = reactive({
  batchName: '',
  submitterComment: '',
  targetNodeIds: [] as number[]
})

const selectedBindings = ref<NodeFileBinding[]>([])
const lastAction = ref<'saveDraft' | 'submit'>()

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const selectedNode = computed(() => props.packageData?.node)
const bindings = computed(() => props.packageData?.bindings || [])
const selectedBindingIds = computed(() => selectedBindings.value.map((item) => item.id))
const targetNodeCount = computed(() => form.targetNodeIds.length)
// 文件本体没上传成功的资料不能提交：后端以版本内容哈希为准（DOCUMENT_BODY_MISSING），
// 这里同口径拦在按钮上，避免用户提交后才被拒。
const bindingBodyUploaded = (item: { bodyUploaded?: boolean }) => item.bodyUploaded !== false
const unuploadedBindings = computed(() =>
  selectedBindings.value.filter((item) => !bindingBodyUploaded(item))
)
const submitReadyCount = computed(
  () =>
    selectedBindings.value.filter(
      (item) => item.bindingStatus !== '已通过' && bindingBodyUploaded(item)
    ).length
)
const submitBlockedReason = computed(() => {
  if (!bindings.value.length) return '当前节点没有可提交的资料'
  if (!selectedBindings.value.length) return '请先勾选要提交的资料'
  if (unuploadedBindings.value.length) {
    const names = unuploadedBindings.value
      .slice(0, 2)
      .map((item) => item.fileName || item.id)
      .join('、')
    return `${names} 尚未上传成功，请重新上传后再提交`
  }
  if (!submitReadyCount.value) return '所选资料均已通过审查，无需重复提交'
  return ''
})
const isCrossNodeScope = computed(() => form.targetNodeIds.length > 1)
const retryLabel = computed(() => {
  if (lastAction.value === 'saveDraft') return '重试保存'
  return '重试提交'
})
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

const resetForm = () => {
  const draft = props.draftDetail
  form.batchName =
    draft?.batchName ||
    (selectedNode.value
      ? `节点 ${selectedNode.value.nodeId} ${selectedNode.value.name} 提交批次`
      : '节点资料提交批次')
  form.submitterComment = draft?.remark || ''
  form.targetNodeIds = draft?.nodeIds?.length
    ? [...draft.nodeIds]
    : selectedNode.value
      ? [selectedNode.value.nodeId]
      : []
  selectedBindings.value = []
}

const handleSelectionChange = (rows: NodeFileBinding[]) => {
  selectedBindings.value = rows
}

const handleSubmit = () => {
  if (!selectedNode.value) {
    ElMessage.warning('请先选择节点')
    return
  }
  if (!form.targetNodeIds.length) {
    ElMessage.warning('请选择提交节点范围')
    return
  }
  if (!selectedBindingIds.value.length && !isCrossNodeScope.value) {
    ElMessage.warning('请选择需要提交的资料，或选择多个节点进行范围提交')
    return
  }
  lastAction.value = 'submit'
  emit('submit', {
    nodeIds: form.targetNodeIds,
    bindingIds: selectedBindingIds.value,
    batchName: form.batchName.trim() || `节点 ${selectedNode.value.nodeId} 提交批次`,
    submitterComment: form.submitterComment.trim()
  })
}

const handleSaveDraft = () => {
  if (!selectedNode.value) {
    ElMessage.warning('请先选择节点')
    return
  }
  if (!form.targetNodeIds.length) {
    ElMessage.warning('请选择提交节点范围')
    return
  }
  if (!selectedBindingIds.value.length && !isCrossNodeScope.value) {
    ElMessage.warning('请选择需要保存的资料，或选择多个节点保存范围草稿')
    return
  }
  lastAction.value = 'saveDraft'
  emit('saveDraft', {
    nodeIds: form.targetNodeIds,
    bindingIds: selectedBindingIds.value,
    batchName: form.batchName.trim() || `节点 ${selectedNode.value.nodeId} 提交草稿`,
    remark: form.submitterComment.trim() || '从提交批次弹窗保存的草稿。'
  })
}

const handleRetry = () => {
  if (lastAction.value === 'saveDraft') {
    handleSaveDraft()
    return
  }
  handleSubmit()
}

watch(
  () => [props.modelValue, props.draftDetail?.draftId] as const,
  ([open]) => {
    if (open) resetForm()
  }
)
</script>

<template>
  <ElDialog v-model="visible" title="提交批次" width="860px" append-to-body>
    <template v-if="packageData">
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
        :closable="false"
        type="info"
        show-icon
        class="batch-alert"
        title="选择本次要提交的资料项；跨节点提交未勾选资料时，将提交所选节点范围内全部可提交挂载资料。"
      />
      <ElAlert
        v-if="draftDetail"
        :closable="false"
        type="warning"
        show-icon
        class="batch-alert"
        title="已恢复历史草稿；继续编辑会覆盖当前弹窗内容，原草稿仍可在提交历史中追溯。"
      />
      <ElAlert
        v-if="operationError"
        :closable="false"
        type="error"
        show-icon
        class="batch-alert submission-dialog-error"
        title="提交批次操作失败"
      >
        <div class="dialog-error-content">
          <span>{{ operationError }}</span>
          <ElButton link type="primary" :loading="loading" @click="handleRetry">
            {{ retryLabel }}
          </ElButton>
        </div>
      </ElAlert>

      <ElForm label-position="top" class="batch-form">
        <ElFormItem label="批次名称">
          <ElInput v-model="form.batchName" maxlength="80" show-word-limit />
        </ElFormItem>
        <ElFormItem label="提交节点范围" class="submission-node-scope-field">
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
        <ElFormItem label="提交说明">
          <ElInput
            v-model="form.submitterComment"
            type="textarea"
            :rows="3"
            maxlength="300"
            show-word-limit
          />
        </ElFormItem>
      </ElForm>

      <ElTable
        :data="bindings"
        border
        height="230"
        row-key="id"
        class="submission-batch-table"
        @selection-change="handleSelectionChange"
      >
        <ElTableColumn type="selection" width="48" />
        <ElTableColumn prop="fileName" label="资料" min-width="220" show-overflow-tooltip />
        <ElTableColumn
          prop="requirementName"
          label="资料要求"
          min-width="150"
          show-overflow-tooltip
        />
        <ElTableColumn prop="usage" label="用途" width="100" />
        <ElTableColumn label="状态" width="110">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.bindingStatus)" size="small" effect="plain">
              {{ row.bindingStatus }}
            </ElTag>
          </template>
        </ElTableColumn>
      </ElTable>
    </template>

    <ElEmpty v-else description="请选择节点后再提交" />

    <template #footer>
      <span v-if="submitBlockedReason" class="footer-hint footer-hint--blocked">
        {{ submitBlockedReason }}
      </span>
      <span v-else class="footer-hint"
        >已选择 {{ selectedBindingIds.length }} 项，可提交 {{ submitReadyCount }} 项，节点范围
        {{ targetNodeCount }} 个</span
      >
      <ElButton @click="visible = false">取消</ElButton>
      <ElButton plain :disabled="!bindings.length" :loading="loading" @click="handleSaveDraft">
        保存为草稿
      </ElButton>
      <ElButton
        type="primary"
        :disabled="Boolean(submitBlockedReason)"
        :loading="loading"
        @click="handleSubmit"
      >
        提交批次
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.node-summary,
.batch-alert,
.batch-form {
  margin-bottom: 14px;
}

.batch-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 12px;
  align-items: start;
}

.submission-node-scope-field {
  min-width: 0;
}

.dialog-error-content {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
  line-height: 1.5;
}

.footer-hint {
  float: left;
  min-height: 32px;
  line-height: 32px;
  color: #667085;
}

.footer-hint--blocked {
  color: #d97706;
}

@media (width <= 768px) {
  .batch-form {
    grid-template-columns: 1fr;
  }

  .footer-hint {
    display: block;
    float: none;
    margin-bottom: 8px;
    text-align: left;
  }

  .dialog-error-content {
    align-items: flex-start;
  }
}
</style>
