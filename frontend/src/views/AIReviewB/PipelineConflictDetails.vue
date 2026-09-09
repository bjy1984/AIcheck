<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ElAlert, ElButton, ElEmpty } from 'element-plus'
import { getPipelineConflicts, type PipelineConflictReport } from '@/api/aicheck/pipelineConflicts'
const props = defineProps<{ projectId: string; runId: string }>()
const report = ref<PipelineConflictReport | null>(null)
const error = ref('')
const loading = ref(false)
const generation = ref(0)
const reset = () => {
  generation.value++
  report.value = null
  error.value = ''
  loading.value = false
}
watch(() => [props.projectId, props.runId], reset, { flush: 'sync' })
onBeforeUnmount(reset)
const load = async () => {
  const attempt = ++generation.value
  const projectId = props.projectId
  const runId = props.runId
  report.value = null
  error.value = ''
  loading.value = true
  try {
    const response = await getPipelineConflicts(projectId, runId)
    if (attempt !== generation.value) return
    if (response.data.report.projectId !== projectId || response.data.report.reviewRunId !== runId)
      throw new Error('report identity mismatch')
    report.value = response.data.report
  } catch {
    if (attempt === generation.value)
      error.value = '冲突报告暂不可用或无权读取，请核对文件权限后重试。'
  } finally {
    if (attempt === generation.value) loading.value = false
  }
}
const valueText = (value: unknown) =>
  typeof value === 'string' ? value : (JSON.stringify(value) ?? '未记录')
const labels: Record<string, string> = {
  designPressureMPa: '设计压力（MPa）',
  designTemperatureC: '设计温度（℃）',
  pipelineGrade: '管道级别',
  material: '材质',
  specification: '规格',
  medium: '介质',
  mediumToxicity: '毒性程度',
  leakHazard: '泄漏危害性',
  weldingMethod: '焊接方法',
  ndtRatio: '检测比例',
  pressureClass: '压力等级',
  minimumTestPressureMPa: '最低试验压力（MPa）'
}
</script>
<template>
  <section class="pipeline-conflicts" aria-label="管线资料冲突" :aria-busy="loading">
    <ElButton :loading="loading" @click="load">{{
      report ? '重新读取冲突报告' : '查看冲突明细'
    }}</ElButton>
    <ElAlert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <template v-if="report">
      <p>以下为任务失败时的资料记录，尚未裁定哪一项正确。请按文件版本和页码核对原文。</p>
      <ElEmpty v-if="!report.conflicts.length" description="此报告未记录具体冲突项" />
      <article v-for="(conflict, index) in report.conflicts" :key="index">
        <h4>{{ conflict.pipelineId }} · {{ labels[conflict.field] || conflict.field }}</h4>
        <ul>
          <li v-for="(item, sourceIndex) in conflict.sources" :key="sourceIndex">
            <strong>{{ valueText(item.value) }}</strong>
            <span
              >{{ item.source.fileName || '来源文件' }} · 版本
              {{ item.source.documentVersionId }}</span
            >
            <span
              >页码 {{ item.source.pageNo ?? '未记录'
              }}<template v-if="item.source.tableId">
                · 表 {{ item.source.tableId }}</template
              ></span
            >
          </li>
        </ul>
      </article>
    </template>
  </section>
</template>
<style scoped>
.pipeline-conflicts {
  display: grid;
  gap: 12px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.pipeline-conflicts :deep(.el-button) {
  min-height: 44px;
  justify-self: start;
}

h4,
p {
  margin: 0;
}

article {
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}

ul {
  padding-left: 20px;
  margin: 8px 0 0;
}

li {
  margin-top: 8px;
}

li span {
  display: block;
  color: var(--el-text-color-regular);
}
</style>
