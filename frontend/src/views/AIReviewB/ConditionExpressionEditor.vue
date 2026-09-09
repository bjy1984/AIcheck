<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElFormItem, ElInput, ElOption, ElSelect } from 'element-plus'
import {
  changeConditionKind,
  conditionKind,
  newCondition,
  type ConditionNode,
  type ConditionValue
} from './ruleConditionModel'
const props = withDefaults(
  defineProps<{ modelValue: ConditionNode; grouped?: boolean; depth?: number }>(),
  { grouped: true, depth: 0 }
)
const emit = defineEmits<{ 'update:modelValue': [ConditionNode] }>()
const kind = computed(() => conditionKind(props.modelValue))
const children = computed(
  () =>
    props.modelValue.all ||
    props.modelValue.any ||
    (props.modelValue.not ? [props.modelValue.not] : [])
)
const sample = computed(() =>
  Array.isArray(props.modelValue.expected)
    ? props.modelValue.expected[0]
    : props.modelValue.expected
)
const valueType = computed(() => typeof sample.value)
const values = computed(() =>
  Array.isArray(props.modelValue.expected)
    ? props.modelValue.expected
    : [props.modelValue.expected ?? '']
)
const update = (key: string, value: unknown) =>
  emit('update:modelValue', { ...props.modelValue, [key]: value })
const updateChildren = (items: ConditionNode[]) =>
  emit('update:modelValue', kind.value === 'not' ? { not: items[0] } : { [kind.value]: items })
const updateChild = (index: number, node: ConditionNode) =>
  updateChildren(children.value.map((item, i) => (i === index ? node : item)))
const setType = (type: string) => {
  const value = type === 'number' ? 0 : type === 'boolean' ? false : ''
  update('expected', props.modelValue.operator === 'in' ? [value] : value)
}
const setOperator = (operator: string) =>
  emit('update:modelValue', {
    ...props.modelValue,
    operator,
    expected: operator === 'in' ? values.value : values.value[0]
  })
const setValue = (index: number, raw: string | boolean) => {
  const value: ConditionValue =
    valueType.value === 'number' ? (String(raw).trim() ? Number(raw) : Number.NaN) : raw
  const items = values.value.map((item, i) => (i === index ? value : item))
  update('expected', props.modelValue.operator === 'in' ? items : items[0])
}
const setUnit = (unit: string) => {
  const node = { ...props.modelValue }
  if (unit.trim()) node.unit = unit.trim()
  else delete node.unit
  emit('update:modelValue', node)
}
</script>
<template>
  <div class="condition-expression">
    <ElFormItem v-if="grouped" label="条件组合">
      <ElSelect
        :model-value="kind"
        @update:model-value="emit('update:modelValue', changeConditionKind(modelValue, $event))"
      >
        <ElOption label="比较条件" value="comparison" />
        <ElOption label="全部成立" value="all" :disabled="depth >= 7" />
        <ElOption label="任一成立" value="any" :disabled="depth >= 7" />
        <ElOption label="条件取反" value="not" :disabled="depth >= 7" />
      </ElSelect>
    </ElFormItem>
    <template v-if="kind === 'comparison'">
      <ElFormItem label="事实字段" required
        ><ElInput
          :model-value="modelValue.field"
          placeholder="例如：thickness"
          @update:model-value="update('field', $event)"
      /></ElFormItem>
      <ElFormItem label="比较方式"
        ><ElSelect :model-value="modelValue.operator" @update:model-value="setOperator">
          <ElOption
            v-for="option in [
              { value: 'eq', label: '等于' },
              { value: 'ne', label: '不等于' },
              { value: 'gt', label: '大于' },
              { value: 'gte', label: '大于或等于' },
              { value: 'lt', label: '小于' },
              { value: 'lte', label: '小于或等于' },
              { value: 'in', label: '属于列表中的任一值' }
            ]"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          /> </ElSelect
      ></ElFormItem>
      <ElFormItem label="比较值类型"
        ><ElSelect :model-value="valueType" @update:model-value="setType">
          <ElOption label="文字" value="string" /><ElOption label="数字" value="number" /><ElOption
            label="是 / 否"
            value="boolean"
          /> </ElSelect
      ></ElFormItem>
      <ElFormItem
        v-for="(value, index) in values"
        :key="index"
        :label="`比较值 ${index + 1}`"
        required
      >
        <ElSelect
          v-if="valueType === 'boolean'"
          :model-value="value"
          @update:model-value="setValue(index, $event)"
          ><ElOption label="是" :value="true" /><ElOption label="否" :value="false"
        /></ElSelect>
        <ElInput
          v-else
          :model-value="String(value)"
          :type="valueType === 'number' ? 'number' : 'text'"
          @update:model-value="setValue(index, $event)"
        />
        <ElButton
          v-if="modelValue.operator === 'in' && values.length > 1"
          text
          @click="
            update(
              'expected',
              values.filter((_, i) => i !== index)
            )
          "
          >移除此值</ElButton
        >
      </ElFormItem>
      <ElButton
        v-if="modelValue.operator === 'in'"
        @click="
          update('expected', [
            ...values,
            valueType === 'number' ? 0 : valueType === 'boolean' ? false : ''
          ])
        "
        >添加比较值</ElButton
      >
      <ElFormItem label="单位（无单位时留空）"
        ><ElInput
          :model-value="modelValue.unit"
          placeholder="例如：mm；与事实数据的单位一致"
          @update:model-value="setUnit"
      /></ElFormItem>
    </template>
    <template v-else>
      <div v-for="(child, index) in children" :key="index" class="condition-child">
        <ConditionExpressionEditor
          :model-value="child"
          :depth="depth + 1"
          @update:model-value="updateChild(index, $event)"
        />
        <ElButton
          v-if="kind !== 'not' && children.length > 1"
          @click="updateChildren(children.filter((_, i) => i !== index))"
          >移除此条件</ElButton
        >
      </div>
      <ElButton v-if="kind !== 'not'" @click="updateChildren([...children, newCondition()])"
        >添加子条件</ElButton
      >
    </template>
  </div>
</template>
<style scoped>
.condition-expression {
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}

.condition-child {
  margin-bottom: 12px;
}
</style>
