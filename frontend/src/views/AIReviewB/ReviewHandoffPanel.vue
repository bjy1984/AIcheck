<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDialog,
  ElEmpty,
  ElInput,
  ElMessageBox,
  ElPagination
} from 'element-plus'
import { getHandoff, listHandoffs, verifyHandoff, type Handoff } from '@/api/aicheck/reviewHandoffs'
import type { EvidenceLink } from '@/types/aicheck'
import {
  handoffBelongsTo,
  handoffCanConfirm,
  handoffReviewBlock,
  handoffStatusText
} from './handoffPresentation'

const props = defineProps<{ projectId: string; runId: string }>()
const emit = defineEmits<{ evidence: [value: EvidenceLink] }>()
const enabled = import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED === 'true'
const visible = ref(false)
const busy = ref(false)
const error = ref('')
const feedback = ref('')
const items = ref<Handoff[]>([])
const selected = ref<Handoff | null>(null)
const page = ref(1)
const total = ref(0)
const note = ref('')
const objectConfirmed = ref(false)
const evidenceConfirmed = ref(false)
const refreshRequired = ref(false)
let generation = 0
const dirty = computed(() => !!note.value || objectConfirmed.value || evidenceConfirmed.value)
const block = computed(() => (selected.value ? handoffReviewBlock(selected.value) : ''))
const resetForm = () => {
  note.value = ''
  objectConfirmed.value = false
  evidenceConfirmed.value = false
  refreshRequired.value = false
}
const reset = () => {
  generation++
  visible.value = false
  busy.value = false
  items.value = []
  selected.value = null
  error.value = ''
  feedback.value = ''
  page.value = 1
  total.value = 0
  resetForm()
}
watch(() => [props.projectId, props.runId], reset, { flush: 'sync' })
onBeforeUnmount(reset)
const discard = async () => {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('尚有未提交的核验意见，是否放弃？', '未提交的意见', {
      type: 'warning'
    })
    return true
  } catch {
    return false
  }
}
const close = async (done: () => void) => {
  if (busy.value || !(await discard())) return
  reset()
  done()
}
const load = async (nextPage = page.value) => {
  if (busy.value || !(await discard())) return
  const attempt = ++generation
  const project = props.projectId
  const run = props.runId
  selected.value = null
  items.value = []
  resetForm()
  error.value = ''
  busy.value = true
  try {
    const response = await listHandoffs(project, run, nextPage)
    if (attempt !== generation) return
    if (!response.data.items.every((item) => handoffBelongsTo(item, project, run)))
      throw new Error('handoff identity mismatch')
    items.value = response.data.items
    total.value = response.data.total
    page.value = nextPage
  } catch {
    if (attempt === generation) error.value = '交接列表加载失败，请确认双方节点及文件权限后重试。'
  } finally {
    if (attempt === generation) busy.value = false
  }
}
const open = () => {
  visible.value = true
  void load(1)
}
const choose = async (id: string) => {
  if (busy.value || !(await discard())) return
  const attempt = ++generation
  const project = props.projectId
  const run = props.runId
  busy.value = true
  error.value = ''
  feedback.value = ''
  selected.value = null
  resetForm()
  try {
    const response = await getHandoff(project, id)
    if (attempt !== generation) return
    if (response.data.id !== id || !handoffBelongsTo(response.data, project, run))
      throw new Error('handoff identity mismatch')
    selected.value = response.data
  } catch {
    if (attempt === generation) error.value = '交接详情不可用或权限已变化，请重新加载。'
  } finally {
    if (attempt === generation) busy.value = false
  }
}
const submit = async (outcome: 'verified' | 'rejected') => {
  const record = selected.value
  if (!record || busy.value || block.value || refreshRequired.value || !note.value.trim()) return
  if (
    outcome === 'verified' &&
    (!handoffCanConfirm(record) || !objectConfirmed.value || !evidenceConfirmed.value)
  )
    return
  const attempt = ++generation
  const project = props.projectId
  const run = props.runId
  busy.value = true
  error.value = ''
  feedback.value = ''
  try {
    const response = await verifyHandoff(
      project,
      record.id,
      {
        snapshotHash: record.draft.snapshotHash,
        expectedPreviousId: record.verifications?.at(-1)?.id || null,
        subject: record.draft.subject,
        outcome,
        objectMatchConfirmed: objectConfirmed.value,
        evidenceSupportConfirmed: evidenceConfirmed.value,
        note: note.value.trim()
      },
      crypto.randomUUID()
    )
    if (attempt !== generation) return
    if (response.data.id !== record.id || !handoffBelongsTo(response.data, project, run))
      throw new Error('handoff identity mismatch')
    resetForm()
    selected.value = null
    feedback.value =
      outcome === 'verified'
        ? '人工确认已保存，请重新打开交接查看当前状态。'
        : '退回意见已保存，请重新打开交接查看历史。'
  } catch {
    if (attempt === generation) {
      refreshRequired.value = true
      error.value =
        '提交结果未确认，或版本／权限已变化。意见已保留，请复制意见并重新加载交接核对最新记录后再操作。'
    }
  } finally {
    if (attempt === generation) busy.value = false
  }
}
const preview = (ref: EvidenceLink, index: number) => {
  const record = selected.value
  if (!record || !ref.documentVersionId) return
  emit('evidence', {
    ...ref,
    id: `HANDOFF-${record.id}-${index}`,
    projectId: props.projectId,
    nodeId: record.draft.source.nodeId,
    objectType: 'documentVersion',
    objectId: ref.documentVersionId
  })
}
const valueText = (value: unknown) =>
  typeof value === 'string' ? value : JSON.stringify(value, null, 2)
</script>

<template>
  <ElButton v-if="enabled" :disabled="!projectId || !runId" @click="open">工位交接</ElButton>
  <ElDialog
    v-model="visible"
    title="当前任务 · 收到的工位交接"
    width="min(920px, 94vw)"
    :before-close="close"
    :close-on-click-modal="false"
  >
    <div class="handoff-panel" :aria-busy="busy">
      <ElAlert
        title="人工核验仅确认这份交接的对象和证据，不代表节点或工程审查通过。"
        type="info"
        :closable="false"
      />
      <ElAlert v-if="error" :title="error" type="error" :closable="false" role="alert" />
      <p v-if="feedback" role="status">{{ feedback }}</p>
      <ElButton :loading="busy" @click="load()">刷新交接列表</ElButton>
      <ElEmpty v-if="!busy && !error && !items.length" description="当前任务没有可读取的交接。" />
      <nav class="handoff-list" aria-label="收到的交接">
        <ElButton
          v-for="item in items"
          :key="item.id"
          :disabled="busy"
          :aria-pressed="selected?.id === item.id"
          @click="choose(item.id)"
        >
          {{ item.draft.source.stationId }} → {{ item.draft.target.stationId }} ·
          {{ item.draft.subject.objectId }} · 事件 {{ item.draft.subject.eventId || '未记录' }}
        </ElButton>
      </nav>
      <ElPagination
        v-if="total > 20"
        :current-page="page"
        :page-size="20"
        :total="total"
        :disabled="busy"
        layout="prev, pager, next"
        @current-change="load"
      />
      <section v-if="selected" aria-label="交接详情" class="handoff-detail">
        <h3
          >{{ selected.draft.subject.objectId }} · 事件
          {{ selected.draft.subject.eventId || '未记录' }}</h3
        >
        <p
          >节点 {{ selected.draft.source.nodeId }} → {{ selected.draft.target.nodeId }} · 返修轮次
          {{ selected.draft.subject.repairRound }}</p
        >
        <p>{{ handoffStatusText(selected.verification?.status) }}</p>
        <dl>
          <template v-for="(value, key) in selected.draft.payload" :key="key">
            <dt>{{ key }}</dt
            ><dd>{{ valueText(value) }}</dd>
          </template>
        </dl>
        <h4>交接证据</h4>
        <p v-if="!selected.draft.evidenceRefs.length">未附引用；请核对协作事项是否仅为工作请求。</p>
        <div v-for="(reference, index) in selected.draft.evidenceRefs" :key="index">
          <p
            >{{ reference.fileName || reference.documentVersionId }} · 第
            {{ reference.pageNo }} 页</p
          >
          <blockquote v-if="reference.quotedText">{{ reference.quotedText }}</blockquote>
          <ElButton :disabled="!reference.documentVersionId" @click="preview(reference, index)"
            >查看原文 {{ index + 1 }}</ElButton
          >
        </div>
        <ElAlert v-if="block" :title="block" type="warning" :closable="false" />
        <ElAlert
          v-else-if="!handoffCanConfirm(selected)"
          title="证据页尚未定位，暂不能确认；可填写说明退回。"
          type="warning"
          :closable="false"
        />
        <fieldset :disabled="busy || !!block || refreshRequired">
          <legend>人工核验</legend>
          <ElCheckbox v-model="objectConfirmed">已核对对象、事件及返修轮次一致</ElCheckbox>
          <ElCheckbox v-model="evidenceConfirmed">已核对原文支持交接内容</ElCheckbox>
          <label for="handoff-note">核验说明（必填）</label>
          <ElInput
            id="handoff-note"
            v-model="note"
            type="textarea"
            :rows="3"
            :disabled="busy || !!block"
          />
          <div class="handoff-actions">
            <ElButton
              type="primary"
              :loading="busy"
              :disabled="
                !!block ||
                refreshRequired ||
                !note.trim() ||
                !objectConfirmed ||
                !evidenceConfirmed ||
                !handoffCanConfirm(selected)
              "
              @click="submit('verified')"
              >确认交接</ElButton
            >
            <ElButton
              :disabled="busy || !!block || refreshRequired || !note.trim()"
              @click="submit('rejected')"
              >退回交接</ElButton
            >
          </div>
        </fieldset>
        <h4>核验历史</h4>
        <p v-if="!selected.verifications?.length">尚无人工核验记录。</p>
        <ol
          ><li v-for="review in selected.verifications" :key="review.id">
            {{ handoffStatusText(review.outcome) }} · {{ review.reviewedByUserId }} ·
            {{ review.createdAt }}
            <p>{{ review.note }}</p>
          </li></ol
        >
      </section>
    </div>
  </ElDialog>
</template>

<style scoped>
.handoff-panel,
.handoff-detail {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.handoff-list,
.handoff-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.handoff-panel :deep(.el-button) {
  height: auto;
  min-height: 44px;
  margin-left: 0;
  white-space: normal;
}

.handoff-panel fieldset {
  display: grid;
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--el-border-color);
  gap: 12px;
}

.handoff-panel dd {
  margin: 8px 0 16px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.handoff-panel p,
.handoff-panel h3,
.handoff-panel blockquote {
  overflow-wrap: anywhere;
}

.handoff-panel :deep(.el-checkbox) {
  height: auto;
  min-height: 44px;
  white-space: normal;
}

.handoff-detail h3,
.handoff-detail h4,
.handoff-detail p,
.handoff-detail dl {
  margin: 0;
}

.handoff-panel :deep(.el-checkbox__label) {
  white-space: normal;
}
</style>
