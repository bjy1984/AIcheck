<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElSelect,
  ElTag
} from 'element-plus'
import {
  trialProjectRule,
  type ProjectRule,
  type RuleTrialResult
} from '@/api/aicheck/projectRules'
import type { ConditionNode } from './ruleConditionModel'
const props = defineProps<{ projectId: string; rule: ProjectRule; disabled: boolean }>()
interface InputFact {
  field: string
  type: string
  value: string
  unit: string
  reference: string
}
const inputs = ref<InputFact[]>([])
const result = ref<RuleTrialResult>()
const error = ref('')
const busy = ref(false)
let generation = 0
const leaves = (node: ConditionNode): ConditionNode[] =>
  node.all || node.any
    ? (node.all || node.any || []).flatMap(leaves)
    : node.not
      ? leaves(node.not)
      : [node]
watch(
  () => [props.projectId, props.rule.id, props.rule.etag],
  () => {
    generation += 1
    result.value = undefined
    busy.value = false
    error.value = ''
    const conditions = props.rule.executionConditions
    const nodes = [
      ...(conditions?.checks || []),
      ...(conditions?.applicability ? leaves(conditions.applicability) : [])
    ]
    inputs.value = [
      ...new Map(
        nodes
          .filter((node) => node.field)
          .map((node) => [
            node.field!,
            {
              field: node.field!,
              type: typeof (Array.isArray(node.expected) ? node.expected[0] : node.expected),
              value: '',
              unit: node.unit || '',
              reference: ''
            }
          ])
      ).values()
    ]
  },
  { immediate: true }
)
watch(
  inputs,
  () => {
    result.value = undefined
  },
  { deep: true }
)
watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) {
      generation += 1
      result.value = undefined
      busy.value = false
    }
  }
)
const labels: Record<string, string> = {
  pass: '符合',
  fail: '不符合',
  evidence_insufficient: '证据不足',
  not_applicable: '不适用'
}
const reasons: Record<string, string> = {
  condition_evaluated: '已按保存的条件比较',
  fact_missing: '缺少字段值',
  evidence_reference_missing: '缺少示例引用',
  unit_mismatch: '单位不一致',
  fact_type_mismatch: '值类型不一致',
  applicability_unknown: '适用性证据不足',
  applicability_not_met: '适用条件不成立'
}
const run = async () => {
  busy.value = true
  error.value = ''
  result.value = undefined
  const current = generation
  const facts = Object.fromEntries(
    inputs.value.map((input) => [
      input.field,
      {
        value: !input.value.trim()
          ? null
          : input.type === 'number'
            ? Number(input.value)
            : input.type === 'boolean'
              ? input.value === 'true'
              : input.value,
        ...(input.unit.trim() ? { unit: input.unit.trim() } : {}),
        evidenceRefs: input.reference.trim() ? [input.reference.trim()] : []
      }
    ])
  )
  try {
    const response = await trialProjectRule(props.projectId, props.rule, facts)
    if (current === generation) result.value = response.data
  } catch (cause) {
    if (current === generation)
      error.value =
        cause instanceof Error ? cause.message : '试跑失败；若规则版本已变化，请重新加载后再试。'
  } finally {
    if (current === generation) busy.value = false
  }
}
</script>
<template>
  <section class="rule-trial">
    <h3>草稿试跑</h3>
    <ElAlert
      title="使用下面输入的示例数据测试已保存规则。引用尚未核验，结果不作为工程审查结论。"
      type="info"
      :closable="false"
    />
    <p v-if="disabled">请先保存当前修改，再试跑这一版本。</p>
    <ElForm label-position="top" :disabled="disabled || busy">
      <div v-for="input in inputs" :key="input.field" class="trial-fact">
        <ElFormItem :label="`${input.field} · 示例值（留空表示缺资料）`">
          <ElSelect v-if="input.type === 'boolean'" v-model="input.value" clearable
            ><ElOption label="是" value="true" /><ElOption label="否" value="false"
          /></ElSelect>
          <ElInput
            v-else
            v-model="input.value"
            :type="input.type === 'number' ? 'number' : 'text'"
          />
        </ElFormItem>
        <ElFormItem label="示例值单位"><ElInput v-model="input.unit" /></ElFormItem>
        <ElFormItem label="示例资料编号（留空可测试缺证据）"
          ><ElInput v-model="input.reference"
        /></ElFormItem>
      </div>
      <ElButton :loading="busy" :disabled="disabled" @click="run">运行草稿试跑</ElButton>
    </ElForm>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="result" role="status">
      <p
        >已保存版本修订 {{ result.ruleRevision }} ·
        <ElTag>{{ labels[result.result] || result.result }}</ElTag></p
      >
      <ul
        ><li v-for="check in result.checks" :key="check.id"
          >{{ check.field }}：{{ labels[check.result] || check.result }} —
          {{ reasons[check.reason] || check.reason }}</li
        ></ul
      >
    </div>
  </section>
</template>
<style scoped>
.rule-trial {
  display: grid;
  gap: 12px;
  margin-top: 20px;
}

.trial-fact {
  padding: 12px;
  margin: 12px 0;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}
</style>
