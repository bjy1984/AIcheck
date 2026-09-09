<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElTag
} from 'element-plus'
import {
  createProjectRule,
  forkProjectRule,
  listProjectRules,
  saveProjectRule,
  type ProjectRule,
  type RuleDraftInput
} from '@/api/aicheck/projectRules'

const props = defineProps<{ projectId: string; nodeId: number }>()
const enabled = import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true'
const visible = ref(false)
const busy = ref(false)
const error = ref('')
const rules = ref<ProjectRule[]>([])
const selectedId = ref('')
const form = ref<RuleDraftInput>({ inspectionItem: '', standardText: '', witnessText: '' })
const baseline = ref(JSON.stringify(form.value))
const selected = computed(() => rules.value.find((rule) => rule.id === selectedId.value))
const editable = computed(
  () =>
    !selected.value ||
    (selected.value.projectId === props.projectId && selected.value.status === '草稿')
)
const dirty = computed(() => JSON.stringify(form.value) !== baseline.value)
let contextRevision = 0
const setForm = (rule?: ProjectRule) => {
  selectedId.value = rule?.id || ''
  form.value = {
    inspectionItem: rule?.inspectionItem || '',
    standardText: rule?.standardText || '',
    witnessText: rule?.witnessText || ''
  }
  baseline.value = JSON.stringify(form.value)
}
const canDiscard = async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('尚有未保存的修改，是否放弃？', '未保存的草稿', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning'
    })
    return true
  } catch {
    return false
  }
}
const choose = async (id: string) => {
  if (await canDiscard()) setForm(rules.value.find((rule) => rule.id === id))
}
const close = async (done: () => void) => {
  if (!busy.value && (await canDiscard())) done()
}
const open = async () => {
  visible.value = true
  busy.value = true
  error.value = ''
  const revision = contextRevision
  try {
    const response = await listProjectRules(props.projectId)
    if (revision !== contextRevision) return
    rules.value = response.data.items.filter((rule) => rule.nodeIds.includes(props.nodeId))
    setForm(rules.value[0])
  } catch (cause) {
    if (revision === contextRevision)
      error.value =
        cause instanceof Error
          ? cause.message
          : '无法加载工程规则，请确认已启用工位模式且拥有当前节点权限。'
  } finally {
    if (revision === contextRevision) busy.value = false
  }
}
const save = async (fork = false) => {
  if (
    !fork &&
    (!form.value.inspectionItem.trim() ||
      (!form.value.standardText.trim() && !form.value.witnessText.trim()))
  ) {
    error.value = '请填写审查项目，以及判断依据或工作见证。'
    return
  }
  busy.value = true
  error.value = ''
  const revision = contextRevision
  try {
    const response =
      fork && selected.value
        ? await forkProjectRule(props.projectId, selected.value)
        : selected.value
          ? await saveProjectRule(props.projectId, selected.value, { ...form.value })
          : await createProjectRule(props.projectId, props.nodeId, { ...form.value })
    if (revision !== contextRevision) return
    rules.value = [
      response.data.rule,
      ...rules.value.filter((rule) => rule.id !== response.data.rule.id)
    ]
    setForm(response.data.rule)
    ElMessage.success('工程草稿已保存，尚未发布')
  } catch (cause) {
    if (revision === contextRevision)
      error.value = `${cause instanceof Error ? cause.message : '保存失败'}。输入已保留；若版本冲突，请先复制输入内容，再重新打开并核对最新版本。`
  } finally {
    if (revision === contextRevision) busy.value = false
  }
}
watch(
  () => [props.projectId, props.nodeId],
  () => {
    contextRevision += 1
    visible.value = false
    busy.value = false
    rules.value = []
    setForm()
  }
)
</script>

<template>
  <ElButton v-if="enabled" :disabled="!projectId || !nodeId" @click="open">工程规则</ElButton>
  <ElDialog
    v-model="visible"
    :title="`节点 ${nodeId} · 工程规则草稿`"
    width="min(760px, 94vw)"
    :before-close="close"
    :close-on-click-modal="false"
  >
    <div class="rule-editor" v-loading="busy">
      <ElAlert
        title="保存只产生工程草稿，不改变当前审查或历史结论。试跑与正式发布尚未开放。"
        type="info"
        :closable="false"
        show-icon
      />
      <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <label for="project-rule-choice">选择规则版本</label>
      <ElSelect
        id="project-rule-choice"
        :model-value="selectedId"
        :disabled="busy"
        @update:model-value="choose"
      >
        <ElOption label="新建工程草稿" value="" />
        <ElOption
          v-for="rule in rules"
          :key="rule.id"
          :value="rule.id"
          :label="`${rule.inspectionItem} · ${rule.projectId ? '本工程' : '平台'} · ${rule.status} · ${rule.version}`"
        />
      </ElSelect>
      <div v-if="selected" class="rule-editor-status">
        <ElTag>{{ selected.projectId ? '工程规则' : '平台模板' }}</ElTag>
        <ElTag type="info">{{ selected.status }}</ElTag>
        <span v-if="!editable">此版本只读，请复制为工程草稿后修改。</span>
      </div>
      <ElForm label-position="top" :disabled="busy || !editable">
        <ElFormItem label="审查项目" required
          ><ElInput v-model="form.inspectionItem" maxlength="200"
        /></ElFormItem>
        <ElFormItem label="判断依据与要求"
          ><ElInput
            v-model="form.standardText"
            type="textarea"
            :rows="5"
            maxlength="3000"
            show-word-limit
        /></ElFormItem>
        <ElFormItem label="核对方法与工作见证"
          ><ElInput
            v-model="form.witnessText"
            type="textarea"
            :rows="5"
            maxlength="3000"
            show-word-limit
        /></ElFormItem>
      </ElForm>
      <p
        >适用范围：当前工程、节点
        {{ selected?.nodeIds.join('、') || nodeId }}。文本修改不代表工具数值判定条件已经改变。</p
      >
    </div>
    <template #footer>
      <ElButton :disabled="busy" @click="close(() => (visible = false))">关闭</ElButton>
      <ElButton v-if="selected && !editable" :loading="busy" @click="save(true)"
        >复制为工程草稿</ElButton
      >
      <ElButton v-if="editable" type="primary" :loading="busy" @click="save()">保存草稿</ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.rule-editor {
  display: grid;
  gap: 16px;
}

.rule-editor-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.rule-editor p {
  margin: 0;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
</style>
