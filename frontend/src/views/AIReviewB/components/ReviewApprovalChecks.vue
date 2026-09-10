<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElButton, ElTag } from 'element-plus'
import type { EvidenceLink } from '@/types/aicheck'
import type { ReviewApprovalCheck } from '@/types/ai-review-b'
import { approvalLabel, approvalMessage, approvalStatus } from '../approvalPresentation'
import { resolveProjectAnalysisEvidenceLink } from '../projectAnalysisConversation'
const props = defineProps<{ items: ReviewApprovalCheck[]; evidenceLinks: EvidenceLink[] }>()
const emit = defineEmits<{ evidence: [evidence: EvidenceLink] }>()
const all = ref(false)
const pending = computed(() => props.items.filter((row) => row.result !== 'passed').length)
const visible = computed(() =>
  props.items
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => all.value || row.result !== 'passed')
)
const resolve = (ref: Record<string, unknown>) =>
  resolveProjectAnalysisEvidenceLink(ref, props.evidenceLinks)
const open = (ref: Record<string, unknown>) => {
  const link = resolve(ref)
  if (link) emit('evidence', link)
}
</script>
<template>
  <section v-if="items.length" class="approval-checks" aria-label="签批记录核对">
    <h4>签批记录核对</h4>
    <p>共 {{ items.length }} 项，{{ pending }} 项待核对。这里是记录比对，最终结论仍由你确认。</p>
    <div role="group" aria-label="筛选签批记录">
      <ElButton :aria-pressed="!all" @click="all = false">待核对 {{ pending }}</ElButton>
      <ElButton :aria-pressed="all" @click="all = true">查看全部 {{ items.length }}</ElButton>
    </div>
    <p v-if="!visible.length">当前筛选没有待核对项，可以查看全部记录。</p>
    <ol>
      <li v-for="{ row, index } in visible" :key="index">
        <strong>{{ index + 1 }}. {{ approvalLabel(row) }}</strong>
        <ElTag
          :type="
            row.result === 'failed' ? 'danger' : row.result === 'passed' ? 'success' : 'warning'
          "
          >{{ approvalStatus(row.result) }}</ElTag
        >
        <p v-if="row.usageId">采用记录：{{ row.usageId }}</p>
        <p>{{ approvalMessage(row) }}</p>
        <p v-if="row.approvedAt || row.startedAt"
          >批复：{{ row.approvedAt || '未明确' }}；采用：{{ row.startedAt || '未明确' }}</p
        >
        <details>
          <summary>查看依据（{{ row.evidenceRefs?.length || 0 }} 处引用）</summary>
          <p v-if="!row.evidenceRefs?.length">这项暂时没有可用引用，请到所选文件核对来源。</p>
          <div v-for="(reference, refIndex) in row.evidenceRefs || []" :key="refIndex">
            <ElButton v-if="resolve(reference)" @click="open(reference)"
              >第 {{ reference.pageNo || '?' }} 页 · 查看原文</ElButton
            >
            <p v-else>第 {{ reference.pageNo || '?' }} 页 · 引用暂时打不开，请到所选文件核对。</p>
          </div>
        </details>
      </li>
    </ol>
  </section>
</template>
<style scoped>
.approval-checks {
  padding: 16px;
  margin: 16px 0;
  color: var(--el-text-color-primary);
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
}

ol {
  padding: 0;
  list-style: none;
}

li {
  padding: 16px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

p {
  line-height: 1.6;
}

.el-tag {
  margin-left: 12px;
}

.el-button,
summary {
  min-height: 44px;
}

summary {
  display: flex;
  align-items: center;
  cursor: pointer;
}

summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 3px;
}
</style>
