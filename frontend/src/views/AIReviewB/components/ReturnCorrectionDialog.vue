<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDialog,
  ElInput,
  ElMessage,
  ElTag
} from 'element-plus'
import type { NodeRequirementMatch } from '@/types/aicheck'
import {
  buildReturnCorrectionPayload,
  createReturnCorrectionDraft
} from '@/views/AIReviewB/returnCorrection'
import type { ReturnCorrectionDraft, ReturnableBinding } from '@/views/AIReviewB/returnCorrection'

const props = defineProps<{
  modelValue: boolean
  bindings: ReturnableBinding[]
  missingRequirements: NodeRequirementMatch[]
  defaultOpinion: string
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: ReturnType<typeof buildReturnCorrectionPayload>]
}>()

const draft = ref<ReturnCorrectionDraft>()

/** 缺失资料的显示名：优先中文名，实在没有才退回原始码。
 *
 * 实操所见：补充资料单里列的是 `design_license`、`design_document`——
 * 这是给规则引擎比对用的码，而这张单子是发给施工方看的，
 * 收到「请补交 design_document」没人知道该交什么。
 * 后端其实同时发了 materialTypeName / reviewContent，只是没被用上。
 */
const requirementLabel = (item: NodeRequirementMatch) => {
  const candidate = item as NodeRequirementMatch & {
    materialTypeName?: string
    reviewContent?: string
  }
  return (
    String(candidate.materialTypeName || '').trim() ||
    String(candidate.reviewContent || '').trim() ||
    String(candidate.name || '').trim() ||
    String(candidate.materialTypeCode || '').trim() ||
    '未命名资料'
  )
}

/** 按资料类型去重。
 *
 * 实操所见：同一张单子里 `design_document` 出现两次，两项同名同码、
 * 勾选框也是两个——用户无从区分，勾了等于重复要一次同样的资料。
 * 同一资料类型对应多个审查点是正常的，但发给施工方的「要交什么」只该出现一次。
 */
const visibleRequirements = computed(() => {
  const seen = new Set<string>()
  const rows: NodeRequirementMatch[] = []
  for (const item of props.missingRequirements) {
    const key = String(item.materialTypeCode || '').trim() || item.id
    if (seen.has(key)) continue
    seen.add(key)
    rows.push(item)
  }
  return rows
})

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      draft.value = createReturnCorrectionDraft(
        props.bindings,
        visibleRequirements.value,
        props.defaultOpinion
      )
    }
  },
  { immediate: true }
)

const title = computed(() =>
  draft.value?.mode === 'supplement_request' ? '发起补充资料' : '退回补正'
)

const selectedRequirements = computed(() => {
  const ids = new Set(draft.value?.selectedRequirementIds || [])
  return visibleRequirements.value.filter((item) => ids.has(item.id))
})

const assigneeLabel = computed(() => {
  if (!draft.value) return '施工方'
  if (draft.value.mode === 'return_correction') {
    const selected = props.bindings.filter((item) =>
      draft.value?.selectedBindingIds.includes(item.id)
    )
    return selected.length && selected.every((item) => item.materialCategory === '无损检测资料')
      ? 'NDT'
      : '施工方'
  }
  const hasManual = draft.value.manualRequirementsText.split('\n').some((item) => item.trim())
  return !hasManual &&
    selectedRequirements.value.length > 0 &&
    selectedRequirements.value.every((item) =>
      ['ndt', '无损检测单位'].includes(String(item.responsibleParty || '').toLowerCase())
    )
    ? 'NDT'
    : '施工方'
})

const submit = () => {
  if (!draft.value) return
  try {
    emit(
      'submit',
      buildReturnCorrectionPayload(draft.value, props.bindings, visibleRequirements.value)
    )
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '请完善退回补正信息')
  }
}
</script>

<template>
  <ElDialog
    :model-value="modelValue"
    :title="title"
    width="620px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="draft">
      <ElAlert
        v-if="draft.mode === 'return_correction'"
        type="warning"
        :closable="false"
        show-icon
        title="请选择需要退回修改的已提交资料；系统已默认全选。"
      />
      <ElAlert
        v-else
        type="info"
        :closable="false"
        show-icon
        title="当前节点没有可退回的已提交资料，将创建补充资料单。"
      />

      <div class="correction-section">
        <strong>{{ draft.mode === 'return_correction' ? '退回资料' : '需要提交的资料' }}</strong>
        <ElCheckboxGroup
          v-if="draft.mode === 'return_correction'"
          v-model="draft.selectedBindingIds"
          class="correction-options"
        >
          <ElCheckbox v-for="binding in bindings" :key="binding.id" :value="binding.id" border>
            <span>{{ binding.fileName || binding.materialTypeName || binding.id }}</span>
            <small>{{ binding.materialTypeName || '已提交资料' }}</small>
          </ElCheckbox>
        </ElCheckboxGroup>
        <template v-else>
          <ElCheckboxGroup
            v-if="visibleRequirements.length"
            v-model="draft.selectedRequirementIds"
            class="correction-options"
          >
            <ElCheckbox
              v-for="requirement in visibleRequirements"
              :key="requirement.id"
              :value="requirement.id"
              border
            >
              <span>{{ requirementLabel(requirement) }}</span>
              <small>{{
                requirement.note || requirement.materialTypeCode || '系统识别缺失项'
              }}</small>
            </ElCheckbox>
          </ElCheckboxGroup>
          <ElInput
            v-model="draft.manualRequirementsText"
            type="textarea"
            :rows="3"
            maxlength="1000"
            show-word-limit
            placeholder="补充其他资料要求，每行一项"
          />
        </template>
      </div>

      <div class="correction-section">
        <div class="correction-label">
          <strong>补正原因和处理要求</strong>
          <ElTag effect="plain">通知：{{ assigneeLabel }}</ElTag>
        </div>
        <ElInput
          v-model="draft.reason"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="请具体说明需要修改或补充的内容"
        />
      </div>
    </template>

    <template #footer>
      <ElButton :disabled="loading" @click="emit('update:modelValue', false)">取消</ElButton>
      <ElButton type="danger" :loading="loading" @click="submit">
        {{ draft?.mode === 'supplement_request' ? '确认发起补充单' : '确认退回补正' }}
      </ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.correction-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 18px;
}

.correction-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
}

.correction-options :deep(.el-checkbox) {
  width: 100%;
  height: auto;
  min-height: 42px;
  padding: 8px 12px;
  margin-right: 0;
}

.correction-options span,
.correction-options small {
  display: block;
}

.correction-options small {
  margin-top: 2px;
  color: #667085;
}

.correction-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
