<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElOption,
  ElPagination,
  ElSelect
} from 'element-plus'
import {
  createHandoff,
  listHandoffTargets,
  type HandoffCreate,
  type HandoffTarget
} from '@/api/aicheck/reviewHandoffs'
import type { EvidenceLink } from '@/types/aicheck'
const props = defineProps<{
  projectId: string
  runId: string
  projectEtag?: string
  evidenceLinks?: EvidenceLink[]
}>()
const visible = ref(false)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const feedback = ref('')
const targets = ref<HandoffTarget[]>([])
const target = ref<HandoffTarget | null>(null)
const page = ref(1)
const total = ref(0)
const objectType = ref('weld')
const objectId = ref('')
const eventId = ref('')
const repairRound = ref(0)
const question = ref('')
const selected = ref<string[]>([])
let generation = 0
onBeforeUnmount(() => {
  generation++
})
let attempt = { fingerprint: '', key: '' }
const canSave = computed(
  () =>
    target.value &&
    objectId.value.trim() &&
    eventId.value.trim() &&
    question.value.trim() &&
    Number.isInteger(repairRound.value) &&
    repairRound.value >= 0 &&
    !saving.value &&
    !loading.value
)
const availableEvidence = computed(() =>
  (props.evidenceLinks || []).filter(
    (item) => item.documentVersionId && Number.isInteger(item.pageNo) && Number(item.pageNo) > 0
  )
)
const load = async (next = 1) => {
  const context = ++generation
  loading.value = true
  error.value = ''
  try {
    const response = await listHandoffTargets(props.projectId, props.runId, next)
    if (context !== generation) return
    targets.value = response.data.items
    total.value = response.data.total
    page.value = next
  } catch {
    if (context === generation) error.value = '接收任务加载失败，请重试。已填写的内容仍保留。'
  } finally {
    if (context === generation) loading.value = false
  }
}
const open = () => {
  visible.value = true
  feedback.value = ''
  void load()
}
const save = async () => {
  if (!canSave.value || !target.value) return
  const context = generation
  const project = props.projectId
  const body: HandoffCreate = {
    sourceRunId: props.runId,
    targetRunId: target.value.runId,
    kind: 'collaboration',
    subject: {
      objectType: objectType.value,
      objectId: objectId.value.trim(),
      eventId: eventId.value.trim(),
      repairRound: repairRound.value
    },
    payload: { request: question.value.trim() },
    evidenceRefs: availableEvidence.value
      .filter((item) => selected.value.includes(item.id))
      .map((item) => ({ ...item }))
  }
  const fingerprint = JSON.stringify({ project, body })
  if (attempt.fingerprint !== fingerprint)
    attempt = { fingerprint, key: `handoff-create-${crypto.randomUUID()}` }
  saving.value = true
  error.value = ''
  try {
    await createHandoff(project, body, attempt.key, props.projectEtag)
    if (context !== generation) return
    feedback.value = `已建立交接草稿，接收方可在节点 ${target.value.nodeId} 的任务中核验。尚未作为判定依据使用。`
    question.value = ''
    selected.value = []
    visible.value = false
  } catch {
    if (context === generation)
      error.value =
        '交接未确认保存成功。请核对接收任务与原文是否仍有效；工程版本变化时先刷新工作台。内容已保留，可重试。'
  } finally {
    if (context === generation) saving.value = false
  }
}
watch(
  () => [props.projectId, props.runId],
  () => {
    generation++
    visible.value = false
    saving.value = false
    loading.value = false
    target.value = null
    targets.value = []
    total.value = 0
    objectId.value = ''
    eventId.value = ''
    question.value = ''
    repairRound.value = 0
    selected.value = []
    feedback.value = ''
    error.value = ''
  }
)
</script>
<template>
  <ElButton :disabled="!projectId || !runId || saving" @click="open">发起工位交接</ElButton>
  <p v-if="feedback" role="status">{{ feedback }}</p>
  <ElDialog
    v-model="visible"
    title="请另一工位协助核对"
    width="min(780px, 94vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <ElAlert
      title="交接先作为草稿。对象、事件和原文仍需接收方核验，不会自动触发审查或确认通过。"
      type="info"
      :closable="false"
    />
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <ElForm label-position="top" class="handoff-create-form">
      <ElFormItem label="接收工位与任务">
        <div class="handoff-targets" :aria-busy="loading">
          <ElButton
            v-for="item in targets"
            :key="item.runId"
            :type="target?.runId === item.runId ? 'primary' : 'default'"
            :aria-pressed="target?.runId === item.runId"
            :disabled="saving || loading"
            @click="target = item"
          >
            {{ item.stationId }} 工位 · 节点 {{ item.nodeId }} · {{ item.runId }} ·
            {{ item.status || '状态未提供' }}
          </ElButton>
          <ElEmpty
            v-if="!loading && !targets.length"
            description="没有可接收的其他节点任务。请先建立对应节点的审查任务。"
          />
          <ElButton :loading="loading" :disabled="saving" @click="load(page)">刷新任务</ElButton>
          <ElPagination
            v-if="total > 20"
            :current-page="page"
            :page-size="20"
            :total="total"
            :disabled="saving || loading"
            layout="prev, pager, next"
            @current-change="load"
          />
          <p v-if="target"
            >已选：{{ target.stationId }} 工位 · 节点 {{ target.nodeId }} · {{ target.runId }}</p
          >
        </div>
      </ElFormItem>
      <ElFormItem label="核对对象类型"
        ><ElSelect v-model="objectType" :disabled="saving"
          ><ElOption
            v-for="item in [
              { value: 'weld', label: '焊口' },
              { value: 'material', label: '材料批次' },
              { value: 'pipeline', label: '管线' },
              { value: 'component', label: '管道元件' },
              { value: 'project', label: '工程' }
            ]"
            :key="item.value"
            :value="item.value"
            :label="item.label" /></ElSelect
      ></ElFormItem>
      <ElFormItem label="对象编号"
        ><ElInput
          v-model="objectId"
          :disabled="saving"
          maxlength="200"
          placeholder="填写原资料中的焊口、批次或管线编号"
      /></ElFormItem>
      <ElFormItem label="事件编号"
        ><ElInput
          v-model="eventId"
          :disabled="saving"
          maxlength="200"
          placeholder="填写本次检测、施工或核验事件编号"
      /></ElFormItem>
      <ElFormItem label="返修轮次（未返修填0）"
        ><ElInputNumber v-model="repairRound" :disabled="saving" :min="0" :step="1"
      /></ElFormItem>
      <ElFormItem label="请对方核对什么"
        ><ElInput
          v-model="question"
          :disabled="saving"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
      /></ElFormItem>
      <ElFormItem label="附上原文引用（可选）"
        ><div class="handoff-targets"
          ><ElCheckbox
            v-for="item in availableEvidence"
            :key="item.id"
            :model-value="selected.includes(item.id)"
            @change="
              (value) =>
                (selected = value
                  ? [...selected, item.id]
                  : selected.filter((id) => id !== item.id))
            "
            :disabled="saving"
            >{{ item.fileName || '原文' }} · 第 {{ item.pageNo }} 页</ElCheckbox
          ><p v-if="!availableEvidence.length"
            >当前没有带页码的可选引用，可先写清问题建立协作草稿。</p
          ></div
        ></ElFormItem
      >
    </ElForm>
    <template #footer
      ><ElButton :disabled="saving" @click="visible = false">返回，保留填写内容</ElButton
      ><ElButton type="primary" :loading="saving" :disabled="!canSave" @click="save"
        >建立交接草稿</ElButton
      ></template
    >
  </ElDialog>
</template>
<style scoped>
.handoff-create-form {
  margin-top: 16px;
}

.handoff-targets {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.handoff-targets :deep(.el-button) {
  height: auto;
  min-height: 44px;
  margin: 0;
  text-align: left;
  white-space: normal;
}

.handoff-targets :deep(.el-checkbox__label) {
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
