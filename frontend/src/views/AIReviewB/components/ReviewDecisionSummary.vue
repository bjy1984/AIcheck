<script setup lang="ts">
defineProps<{
  nodeLabel: string
  result: string
  opinion: string
  evidence: Array<{ id: string; fileName: string; versionId?: string; pageNo?: number }>
  excludedCount: number
  issues: string[]
  noResult: boolean
  stale: boolean
  hasTask: boolean
}>()
</script>

<template>
  <section class="decision-summary" aria-label="人工结论保存摘要">
    <p>{{ nodeLabel }}</p>
    <h3>你准备保存的结论：{{ result }}</h3>
    <p class="opinion">{{ opinion }}</p>
    <h3>随结论保存的证据（{{ evidence.length }} 条）</h3>
    <ul v-if="evidence.length">
      <li v-for="item in evidence" :key="item.id">
        {{ item.fileName }}
        <small
          >{{ item.versionId || '未提供文件版本' }} ·
          {{ item.pageNo ? `第 ${item.pageNo} 页` : '未提供页码' }}</small
        >
      </li>
    </ul>
    <p v-else>这次没有附带已人工确认的证据。</p>
    <p v-if="excludedCount"
      >另有
      {{ excludedCount }}
      条所选证据尚未人工确认，这次不会随结论保存。需要引用时，请返回引用证据区先确认。</p
    >
    <h3>保存前还需要留意</h3>
    <p v-if="noResult">系统还没有可展示的审查结果，请根据你实际核验的情况填写结论。</p>
    <p v-if="stale">资料已经变化，当前展示的是旧结果。</p>
    <p v-if="hasTask">还有人工待办尚未处理，保存结论不会自动完成该待办。</p>
    <p v-if="issues.length"
      >系统结果中仍有 {{ issues.length }} 项需要核对；保存人工结论不会改写这些系统判断。</p
    >
    <ul v-if="issues.length"
      ><li v-for="(issue, index) in issues" :key="index">{{ issue }}</li></ul
    >
    <p v-if="!issues.length && !noResult && !stale && !hasTask"
      >当前结构化结果中没有列出的待核对事项，仍以你的实际核验为准。</p
    >
  </section>
</template>

<style scoped>
.decision-summary {
  max-height: 60vh;
  padding-right: 12px;
  overflow-y: auto;
  line-height: 1.65;
  color: var(--el-text-color-primary);
  overflow-wrap: anywhere;
}

.decision-summary h3 {
  margin: 18px 0 8px;
  font-size: 15px;
}

.decision-summary p {
  margin: 8px 0;
}

.decision-summary small {
  display: block;
  color: var(--el-text-color-secondary);
}

.decision-summary .opinion {
  white-space: pre-wrap;
}
</style>
