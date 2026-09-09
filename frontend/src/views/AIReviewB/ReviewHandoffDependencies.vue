<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton } from 'element-plus'
import { getHandoffDependencies, type HandoffDependencies } from '@/api/aicheck/reviewHandoffs'
const props = defineProps<{ projectId: string; runId: string; refreshKey?: number }>()
const report = ref<HandoffDependencies>()
const busy = ref(false)
const error = ref('')
let generation = 0
const refresh = async () => {
  const attempt = ++generation
  report.value = undefined
  error.value = ''
  busy.value = false
  if (!props.projectId || !props.runId) return
  busy.value = true
  try {
    const response = await getHandoffDependencies(props.projectId, props.runId)
    if (attempt !== generation) return
    if (response.data.reviewRunId !== props.runId) throw new Error('任务已切换')
    report.value = response.data
  } catch {
    if (attempt === generation) error.value = '暂时无法核对本次交接是否仍有效，请刷新后再确认结果。'
  } finally {
    if (attempt === generation) busy.value = false
  }
}
watch(() => [props.projectId, props.runId, props.refreshKey], refresh, { immediate: true })
onBeforeUnmount(() => {
  generation++
})
</script>
<template>
  <section
    v-if="runId"
    class="handoff-dependencies"
    aria-label="本次交接依赖状态"
    :aria-busy="busy"
  >
    <p v-if="busy" role="status">正在核对本次使用的交接……</p>
    <ElAlert v-else-if="error" :title="error" type="warning" :closable="false" />
    <ElAlert
      v-else-if="report?.requiresRevalidation"
      title="本次交接需要重新核验"
      description="交接、上游资料或核验记录已经变化。旧结果保留供查看，请核对后再决定是否重新发起审查。"
      type="warning"
      :closable="false"
      show-icon
    />
    <p v-else-if="report?.status === 'current'"
      >本次使用的 {{ report.handoffIds?.length || 0 }} 份交接仍有效。</p
    >
    <ElButton v-if="error || report?.status !== 'not_used'" :loading="busy" @click="refresh"
      >重新核对交接状态</ElButton
    >
  </section>
</template>
<style scoped>
.handoff-dependencies {
  display: grid;
  gap: 8px;
  flex-basis: 100%;
}

.handoff-dependencies p {
  margin: 0;
  line-height: 1.6;
}

.handoff-dependencies :deep(.el-button) {
  min-height: 44px;
  justify-self: start;
}
</style>
