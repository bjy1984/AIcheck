<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElButton,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElInput,
  ElTable,
  ElTableColumn,
  ElTag
} from 'element-plus'
import type { NodeFileBinding, ProjectTreeNode, RectificationItem, TodoItem } from '@/types/aicheck'
import { getStatusTagType } from './status'

const props = defineProps<{
  modelValue: boolean
  node?: ProjectTreeNode
  bindings: NodeFileBinding[]
  todos: TodoItem[]
  rectificationId?: string
  rectification?: RectificationItem
  mode?: 'view' | 'submit'
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: { comment: string; bindingIds: string[]; rectificationId?: string }]
}>()

const comment = ref('已根据监检意见补充证明材料，请复审。')

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
})

const correctionBindings = computed(() => {
  const scoped = props.bindings.filter((binding) => binding.bindingStatus === '需补正')
  return scoped.length ? scoped : props.bindings
})

const nodeTodos = computed(() => props.todos.filter((todo) => todo.nodeId === props.node?.nodeId))

const handleSubmit = () => {
  emit('submit', {
    comment: comment.value.trim(),
    bindingIds: correctionBindings.value.map((binding) => binding.id),
    rectificationId: props.rectificationId
  })
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) comment.value = '已根据监检意见补充证明材料，请复审。'
  }
)
</script>

<template>
  <ElDialog
    v-model="visible"
    :title="mode === 'view' ? '查看监检意见' : '补正详情与反馈'"
    width="820px"
    append-to-body
  >
    <template v-if="node">
      <ElDescriptions :column="2" border class="summary">
        <ElDescriptionsItem label="节点"> {{ node.nodeId }} · {{ node.name }} </ElDescriptionsItem>
        <ElDescriptionsItem label="状态">
          <ElTag :type="getStatusTagType(node.status)" size="small">{{ node.status }}</ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="待办">
          {{ nodeTodos.length ? nodeTodos.map((todo) => todo.title).join('；') : '无待办' }}
        </ElDescriptionsItem>
        <ElDescriptionsItem label="补正资料">
          {{ correctionBindings.length }} 份
        </ElDescriptionsItem>
        <ElDescriptionsItem v-if="rectificationId" label="补正单">
          {{ rectificationId }}
        </ElDescriptionsItem>
        <ElDescriptionsItem v-if="rectification?.comment" label="监检意见" :span="2">
          {{ rectification.comment }}
        </ElDescriptionsItem>
      </ElDescriptions>

      <div class="section-title">需补正或随同提交资料</div>
      <ElTable :data="correctionBindings" border height="220">
        <ElTableColumn prop="fileName" label="文件" min-width="220" show-overflow-tooltip />
        <ElTableColumn
          prop="requirementName"
          label="资料要求"
          min-width="150"
          show-overflow-tooltip
        />
        <ElTableColumn prop="usage" label="用途" width="110" />
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.bindingStatus)" size="small" effect="plain">
              {{ row.bindingStatus }}
            </ElTag>
          </template>
        </ElTableColumn>
      </ElTable>

      <template v-if="mode !== 'view'">
        <div class="section-title">反馈说明</div>
        <ElInput
          v-model="comment"
          type="textarea"
          :rows="4"
          maxlength="400"
          show-word-limit
          aria-label="补正反馈说明"
        />
      </template>
    </template>
    <ElEmpty v-else description="请先选择节点" />

    <template #footer>
      <ElButton @click="visible = false">{{ mode === 'view' ? '关闭' : '取消' }}</ElButton>
      <ElButton
        v-if="mode !== 'view'"
        type="primary"
        :loading="loading"
        :disabled="!node"
        @click="handleSubmit"
      >
        提交补正反馈
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.summary {
  margin-bottom: 14px;
}

.section-title {
  margin: 14px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
</style>
