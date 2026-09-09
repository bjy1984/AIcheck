<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElFormItem, ElInput, ElOption, ElSelect } from 'element-plus'
import {
  applyProjectRuleRelease,
  previewProjectRuleRelease,
  type ProjectRule,
  type RuleReleasePreview,
  type RuleReleaseInput
} from '@/api/aicheck/projectRules'

const props = defineProps<{
  projectId: string
  rule: ProjectRule
  rules: ProjectRule[]
  disabled?: boolean
}>()
const emit = defineEmits<{ changed: [string]; busy: [boolean] }>()
const reason = ref('')
const targetId = ref('')
const busy = ref(false)
const error = ref('')
const preview = ref<RuleReleasePreview>()
const completed = ref(false)
const action = computed(() => (props.rule.status === '已发布' ? 'rollback' : 'publish'))
const targets = computed(() =>
  props.rules.filter(
    (rule) =>
      rule.projectId === props.projectId &&
      rule.id !== props.rule.id &&
      rule.ruleKey === props.rule.ruleKey &&
      rule.status === '已回滚'
  )
)
const label = computed(() => (action.value === 'publish' ? '发布' : '回滚'))
const ready = computed(
  () =>
    !props.disabled &&
    !busy.value &&
    !completed.value &&
    reason.value.trim() &&
    (action.value === 'publish' || targets.value.some((rule) => rule.id === targetId.value))
)
let generation = 0
let retryKey = ''
let frozenInput: RuleReleaseInput | undefined
const reset = () => {
  generation++
  preview.value = undefined
  frozenInput = undefined
  retryKey = ''
  error.value = ''
  completed.value = false
}
watch(
  () => [
    props.projectId,
    props.rule.id,
    props.rule.etag,
    props.disabled,
    reason.value,
    targetId.value
  ],
  reset
)
onBeforeUnmount(() => {
  generation++
})
const run = async (confirm: boolean) => {
  if (!ready.value || (confirm && (!preview.value || !frozenInput))) return
  const revision = generation
  busy.value = true
  emit('busy', true)
  error.value = ''
  try {
    if (confirm) {
      const response = await applyProjectRuleRelease(
        props.projectId,
        props.rule,
        action.value,
        { ...frozenInput!, previewId: preview.value!.previewId },
        retryKey
      )
      if (revision !== generation) return
      completed.value = true
      preview.value = undefined
      emit('changed', (response.data.target || response.data.rule).id)
    } else {
      preview.value = undefined
      const input = {
        reason: reason.value.trim(),
        ...(action.value === 'rollback' ? { targetVersionId: targetId.value } : {})
      }
      const response = await previewProjectRuleRelease(
        props.projectId,
        props.rule.id,
        action.value,
        input
      )
      if (revision !== generation) return
      frozenInput = input
      retryKey = crypto.randomUUID()
      preview.value = response.data
    }
  } catch (cause) {
    if (revision === generation)
      error.value = `${cause instanceof Error ? cause.message : '操作未完成'}。输入已保留；若提示版本变化或预览过期，请重新查看影响。`
  } finally {
    busy.value = false
    emit('busy', false)
  }
}
const display = (value: unknown) =>
  value == null || value === ''
    ? '未填写'
    : Array.isArray(value)
      ? value.join('、')
      : typeof value === 'object'
        ? JSON.stringify(value, null, 2)
        : String(value)
</script>

<template>
  <section class="rule-release" aria-label="规则发布与回滚">
    <h3>{{ label }}工程规则</h3>
    <p>操作生效后，新建审查会采用新的规则版本。已开始的任务和历史结论保持原样。</p>
    <ElAlert
      v-if="disabled"
      title="请先保存修改，并确认当前拥有操作权限。"
      type="info"
      :closable="false"
    />
    <ElAlert
      v-if="rule.executionConditions"
      title="这些条件已经可以试跑，但发布验收还没完成，暂时不能生效。"
      type="warning"
      :closable="false"
    />
    <ElFormItem v-if="action === 'rollback'" label="恢复到哪个版本">
      <ElSelect v-model="targetId" :disabled="busy || disabled" placeholder="选择此前使用过的版本">
        <ElOption
          v-for="item in targets"
          :key="item.id"
          :value="item.id"
          :label="`${item.inspectionItem} · ${item.version}`"
        />
      </ElSelect>
      <p v-if="!targets.length">还没有可恢复的历史工程版本。</p>
    </ElFormItem>
    <ElFormItem :label="`为什么${label}`">
      <ElInput
        v-model="reason"
        type="textarea"
        :rows="2"
        maxlength="1000"
        :disabled="busy || disabled"
      />
    </ElFormItem>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <ElAlert
      v-if="completed"
      title="操作已完成，正在更新版本列表。"
      type="success"
      :closable="false"
    />
    <ElButton :disabled="!ready" :loading="busy" @click="run(false)">查看{{ label }}影响</ElButton>
    <section v-if="preview" aria-label="发布影响对照">
      <h4>请核对这次影响</h4>
      <p
        >适用节点：{{ preview.impact.nodeIds.join('、') }}。预览有效至
        {{ new Date(preview.expiresAt).toLocaleTimeString() }}。</p
      >
      <p v-for="warning in preview.impact.warnings" :key="warning">{{ warning }}</p>
      <article v-for="(change, index) in preview.impact.changes" :key="index">
        <h4
          >{{ change.label }}
          <small v-if="change.fromRuleVersionId"
            >（{{
              change.fromRuleScope === 'platform' ? '目前平台版本，平台本身不变' : '替换工程版本'
            }}
            {{ change.fromRuleVersionId }}）</small
          ></h4
        >
        <div class="release-diff">
          <div
            ><strong>操作前</strong><p>{{ display(change.before) }}</p></div
          >
          <div
            ><strong>操作后</strong><p>{{ display(change.after) }}</p></div
          >
        </div>
      </article>
      <ElButton type="primary" :disabled="!ready" :loading="busy" @click="run(true)"
        >确认{{ label }}</ElButton
      >
    </section>
  </section>
</template>

<style scoped>
.rule-release {
  display: grid;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
}

.release-diff {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

.release-diff p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.rule-release :deep(.el-button) {
  min-height: 44px;
}
</style>
