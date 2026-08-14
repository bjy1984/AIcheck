<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElTag } from 'element-plus'

import type { AiReviewRun } from '@/types/aicheck'

defineProps<{
  evidenceBudget?: AiReviewRun['evidenceBudget']
  failure?: AiReviewRun['failure']
  failureKindLabel: string
}>()

const emit = defineEmits<{
  retry: []
}>()

const failureDetailExpanded = ref(false)
</script>

<template>
  <div v-if="evidenceBudget?.truncated" class="ai-truncation">
    <div class="ai-truncation-head">
      <ElTag size="small" type="warning" effect="dark">证据未送全</ElTag>
      <span>本次仅送审 {{ evidenceBudget.keptVersionCount }} 份资料</span>
    </div>
    <p class="ai-truncation-body">
      以下资料超出模型单次上下文预算，未参与本次 AI 审查，需人工核对：
    </p>
    <ul class="ai-truncation-list">
      <li v-for="name in evidenceBudget.droppedNames" :key="name">{{ name }}</li>
    </ul>
    <p class="ai-truncation-note">
      因证据不全，本次结论已降级为「待人工确认」，不作满足要求的判定。
    </p>
  </div>

  <div v-if="failure" class="ai-failure">
    <div class="ai-failure-head">
      <ElTag size="small" type="danger" effect="dark">AI 审查失败</ElTag>
      <span class="ai-failure-kind">{{ failureKindLabel }}</span>
    </div>
    <p class="ai-failure-reason">{{ failure.reason }}</p>
    <p class="ai-failure-next">{{ failure.nextStep }}</p>
    <div class="ai-failure-actions">
      <ElButton v-if="failure.retryable" size="small" type="primary" @click="emit('retry')">
        重跑本节点审查
      </ElButton>
      <!-- 重跑必然再失败时不给按钮，亮着只会让人白点。这里只做中性标注，
           该干什么由上面那行 nextStep 说——写死「环境问题」会和它打架：
           预算超限就不是环境问题，是送进去的内容太大。 -->
      <span v-else class="ai-failure-noretry">本次不提供重跑</span>
      <button
        type="button"
        class="ai-failure-detail-toggle"
        :aria-expanded="failureDetailExpanded"
        @click="failureDetailExpanded = !failureDetailExpanded"
      >
        {{ failureDetailExpanded ? '收起原始报错' : '查看原始报错' }}
      </button>
    </div>
    <pre v-show="failureDetailExpanded" class="ai-failure-detail">{{ failure.detail }}</pre>
  </div>
</template>

<style scoped>
.ai-truncation {
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 10px;
}

.ai-truncation-head {
  display: flex;
  font-size: 13px;
  color: #92400e;
  gap: 8px;
  align-items: center;
}

.ai-truncation-body {
  margin: 8px 0 4px;
  font-size: 13px;
  color: #92400e;
}

.ai-truncation-list {
  padding-left: 20px;
  margin: 0;
  font-size: 13px;
  color: #7c2d12;
}

.ai-truncation-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: #b45309;
}

.ai-failure {
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
}

.ai-failure-head {
  display: flex;
  gap: 8px;
  align-items: center;
}

.ai-failure-kind {
  font-size: 12px;
  color: #b91c1c;
}

.ai-failure-reason {
  margin: 8px 0 4px;
  font-size: 14px;
  color: #7f1d1d;
}

.ai-failure-next {
  margin: 0;
  font-size: 13px;
  color: #b45309;
}

.ai-failure-actions {
  display: flex;
  margin-top: 10px;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.ai-failure-noretry {
  font-size: 13px;
  color: #92400e;
}

.ai-failure-detail-toggle {
  padding: 0;
  font: inherit;
  font-size: 13px;
  color: #64748b;
  text-decoration: underline;
  cursor: pointer;
  background: none;
  border: none;
}

.ai-failure-detail {
  padding: 8px 10px;
  margin: 10px 0 0;
  font-size: 12px;
  color: #475569;
  word-break: break-all;
  white-space: pre-wrap;
  background: #fff;
  border: 1px solid #fecaca;
  border-radius: 6px;
}
</style>
