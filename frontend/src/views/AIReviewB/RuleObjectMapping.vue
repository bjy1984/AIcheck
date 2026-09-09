<script setup lang="ts">
import { ElCheckbox, ElFormItem, ElInput, ElSelect, ElOption } from 'element-plus'
import type { RuleFactCandidate, RuleObjectMapping } from '@/api/aicheck/projectRules'
const props = defineProps<{ candidates: Record<string, RuleFactCandidate[]> }>()
const model = defineModel<RuleObjectMapping>({ required: true })
const select = (field: string, id: string) => {
  const fields = { ...model.value.fields }
  if (id) fields[field] = id
  else delete fields[field]
  model.value = { ...model.value, fields, confirmedSameObject: false }
}
const subject = (key: 'objectId' | 'objectType', value: string) => {
  model.value = {
    ...model.value,
    subject: { ...model.value.subject, [key]: value },
    confirmedSameObject: false
  }
}
const label = (item: RuleFactCandidate) => {
  const ref = item.evidenceRefs[0]
  return `${typeof item.value === 'string' ? `“${item.value}”` : JSON.stringify(item.value)} ${item.unit || ''} · ${item.objectId || '对象待确认'} · ${ref.documentVersionId} 第 ${ref.pageNo || '?'} 页 · ${ref.fieldId || '无字段编号'}`
}
</script>
<template>
  <section class="rule-object-mapping" aria-label="试跑对象与原文对应">
    <h4>这些资料是在说同一个对象吗？</h4>
    <p
      >每个字段请选择对应的原文记录，再核对它们是否属于同一焊口或批次。不会采用未选字段，也不会自动把这次选择用于正式审查。</p
    >
    <ElFormItem label="对象类型">
      <ElSelect
        :model-value="model.subject.objectType"
        @update:model-value="subject('objectType', $event)"
      >
        <ElOption label="焊口" value="weld" /><ElOption label="材料批次" value="material" />
        <ElOption label="管线" value="pipeline" /><ElOption
          label="元件"
          value="component"
        /><ElOption label="工程" value="project" />
      </ElSelect>
    </ElFormItem>
    <ElFormItem label="焊口／批次等对象编号">
      <ElInput
        :model-value="model.subject.objectId"
        maxlength="200"
        @update:model-value="subject('objectId', $event)"
      />
    </ElFormItem>
    <ElFormItem
      v-for="(items, field) in props.candidates"
      :key="field"
      :label="`${field} · 选择原文记录`"
    >
      <ElSelect
        :model-value="model.fields[field]"
        clearable
        placeholder="未选择，视为缺少资料"
        @update:model-value="select(String(field), $event)"
      >
        <ElOption
          v-for="(item, index) in items"
          :key="`${item.candidateId}-${index}`"
          :value="item.candidateId"
          :label="label(item)"
        />
      </ElSelect>
    </ElFormItem>
    <ElCheckbox
      :model-value="model.confirmedSameObject"
      @update:model-value="model = { ...model, confirmedSameObject: Boolean($event) }"
      >已核对所选原文属于上述同一个对象</ElCheckbox
    >
  </section>
</template>
<style scoped>
.rule-object-mapping {
  padding: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
}

.rule-object-mapping :deep(.el-checkbox) {
  min-height: 44px;
  white-space: normal;
}
</style>
