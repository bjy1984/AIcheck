<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCheckbox, ElInput } from 'element-plus'
import {
  suggestProjectRule,
  type RuleDraftInput,
  type RuleDraftSuggestion
} from '@/api/aicheck/projectRules'
import { ruleDraftDiff } from './ruleDraftDiff'
const props = defineProps<{ projectId: string; nodeId: number; disabled: boolean }>()
const emit = defineEmits<{ apply: [RuleDraftInput]; busy: [boolean] }>()
const description = ref('')
const suggestion = ref<RuleDraftSuggestion>()
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
let generation = 0
const invalidate = () => {
  generation++
  suggestion.value = undefined
  confirmed.value = false
  error.value = ''
  busy.value = false
  emit('busy', false)
}
watch(() => [props.projectId, props.nodeId, description.value], invalidate)
onBeforeUnmount(invalidate)
const generate = async () => {
  if (busy.value || props.disabled || !description.value.trim()) return
  const current = ++generation
  busy.value = true
  emit('busy', true)
  error.value = ''
  suggestion.value = undefined
  confirmed.value = false
  try {
    const response = await suggestProjectRule(
      props.projectId,
      props.nodeId,
      description.value.trim()
    )
    if (current === generation) suggestion.value = response.data
  } catch (cause) {
    if (current === generation)
      error.value = cause instanceof Error ? cause.message : '没能生成草稿，请稍后重试。'
  } finally {
    if (current === generation) {
      busy.value = false
      emit('busy', false)
    }
  }
}
const apply = () => {
  if (!suggestion.value || !confirmed.value || busy.value || props.disabled) return
  emit('apply', JSON.parse(JSON.stringify(suggestion.value.draft)))
  suggestion.value = undefined
  confirmed.value = false
}
</script>

<template>
  <section class="draft-assistant" aria-label="描述要求生成规则草稿" :aria-busy="busy">
    <h3>先说说你想怎么审</h3>
    <p>写清适用对象、要求和依据。生成会调用模型；内容需你核对，套入表单后还要保存和试跑。</p>
    <label for="rule-draft-description">规则要求</label>
    <ElInput
      id="rule-draft-description"
      v-model="description"
      type="textarea"
      :rows="3"
      maxlength="4000"
      show-word-limit
      :disabled="busy || disabled"
      placeholder="例如：对这批材料，按提供的设计要求核对厚度；厚度至少10mm。请保留适用范围。"
    />
    <ElButton :loading="busy" :disabled="disabled || !description.trim()" @click="generate"
      >生成待核对草稿</ElButton
    >
    <ElAlert v-if="error" type="error" :title="error" :closable="false" />
    <template v-if="suggestion">
      <h4>生成内容 · 尚未保存</h4>
      <article
        v-for="item in ruleDraftDiff(
          { inspectionItem: '', standardText: '', witnessText: '' },
          suggestion.draft
        )"
        :key="item.key"
      >
        <strong>{{ item.label }}</strong
        ><p class="suggestion-text">{{ item.after }}</p>
      </article>
      <template v-if="suggestion.questions.length">
        <h4>这些地方还要你确认</h4>
        <ul
          ><li v-for="(question, index) in suggestion.questions" :key="index">{{
            question
          }}</li></ul
        >
      </template>
      <ElCheckbox v-model="confirmed" :disabled="disabled"
        >我会核对适用范围、数值、单位和依据，并在表单中补齐待确认内容</ElCheckbox
      >
      <ElButton :disabled="disabled || !confirmed" @click="apply">套入表单继续编辑</ElButton>
    </template>
  </section>
</template>

<style scoped>
.draft-assistant {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
}

.suggestion-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.draft-assistant :deep(.el-button),
.draft-assistant :deep(.el-checkbox) {
  min-height: 44px;
}

.draft-assistant :deep(.el-checkbox) {
  height: auto;
}

.draft-assistant :deep(.el-checkbox__label) {
  white-space: normal;
}
</style>
