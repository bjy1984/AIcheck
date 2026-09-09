<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCheckbox } from 'element-plus'
import { getHandoff, type Handoff } from '@/api/aicheck/reviewHandoffs'
import type { ReviewDocumentSelection } from '@/api/aicheck/reviewDocuments'
import { selectionWithHandoff } from './handoffSelection'

const props = defineProps<{
  projectId: string
  runId: string
  record: Handoff
  selection: ReviewDocumentSelection | null
  disabled?: boolean
}>()
const emit = defineEmits<{ use: [ReviewDocumentSelection]; busy: [boolean] }>()
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
const applied = computed(() =>
  props.selection?.handoffSelection?.items.some(
    (item) =>
      item.handoffId === props.record.id &&
      item.verificationId === props.record.verification?.latestVerificationId
  )
)
let generation = 0
const proposal = computed(() => {
  try {
    return {
      selection: selectionWithHandoff(props.record, props.projectId, props.runId, props.selection),
      error: ''
    }
  } catch (cause) {
    return { selection: null, error: cause instanceof Error ? cause.message : '交接暂不可用。' }
  }
})
const additions = computed(
  () =>
    proposal.value.selection?.versions.filter(
      (item) => !props.selection?.versions.some((current) => current.versionId === item.versionId)
    ) || []
)
watch(
  () => [
    props.projectId,
    props.runId,
    props.record.id,
    props.record.draft.snapshotHash,
    props.record.verification?.latestVerificationId,
    props.selection
  ],
  () => {
    generation++
    confirmed.value = false
    error.value = ''
  },
  { deep: true }
)
onBeforeUnmount(() => {
  generation++
})
const apply = async () => {
  if (props.disabled || busy.value || !confirmed.value || !proposal.value.selection) return
  const revision = generation
  busy.value = true
  emit('busy', true)
  error.value = ''
  try {
    const response = await getHandoff(props.projectId, props.record.id)
    if (revision !== generation) return
    if (
      response.data.id !== props.record.id ||
      response.data.draft.snapshotHash !== props.record.draft.snapshotHash ||
      response.data.verification?.latestVerificationId !==
        props.record.verification?.latestVerificationId
    )
      throw new Error('交接或核验记录已经更新，请重新打开后核对。')
    const selection = selectionWithHandoff(
      response.data,
      props.projectId,
      props.runId,
      props.selection
    )
    emit('use', selection)
  } catch (cause) {
    if (revision === generation)
      error.value = cause instanceof Error ? cause.message : '无法核对交接最新状态，请重试。'
  } finally {
    if (revision === generation) {
      busy.value = false
      emit('busy', false)
    }
  }
}
</script>
<template>
  <section class="handoff-use" aria-label="下次审查使用交接">
    <h4>让下次审查用上这份交接</h4>
    <p
      >对象 {{ record.draft.subject.objectId }} · 事件 {{ record.draft.subject.eventId }} · 返修轮次
      {{ record.draft.subject.repairRound }}</p
    >
    <p>这里只准备下次输入。你确认发起审查后才会运行，当前结果保持原样。</p>
    <ElAlert v-if="proposal.error" :title="proposal.error" type="info" :closable="false" />
    <template v-else>
      <p v-if="additions.length">将补充以下固定版本，使用整份文件：</p>
      <ul v-if="additions.length"
        ><li v-for="item in additions" :key="item.versionId"
          >{{ item.fileName }} · {{ item.versionId }}</li
        ></ul
      >
      <p v-else>引用原文已在所选资料中，保留现有页码范围。</p>
      <ElCheckbox v-model="confirmed" :disabled="busy || disabled"
        >下次审查针对同一对象、事件及返修轮次</ElCheckbox
      >
      <ElButton type="primary" :loading="busy" :disabled="disabled || !confirmed" @click="apply"
        >下次审查使用这份交接</ElButton
      >
    </template>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="applied" role="status">已加入下次资料，请关闭交接窗口后核对摘要并发起审查。</p>
  </section>
</template>
<style scoped>
.handoff-use {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
}

.handoff-use p,
.handoff-use h4 {
  margin: 0;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.handoff-use :deep(.el-checkbox) {
  height: auto;
  min-height: 44px;
}

.handoff-use :deep(.el-checkbox__label) {
  white-space: normal;
}
</style>
