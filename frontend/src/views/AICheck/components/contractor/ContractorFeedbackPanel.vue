<script setup lang="ts">
import { getStatusTagType } from '../status'
import { computed, ref } from 'vue'
import { ElButton, ElTag } from 'element-plus'

import { plainWording } from '@/utils/reviewerWording'

export type ContractorFeedbackRow = {
  id: string
  rectificationId: string
  nodeId: number
  node: string
  issue: string
  requirement: string
  status: string
  sourceStatus: string
  linkedFiles: number
  feedbackAt: string
  dueAt: string
}

const props = defineProps<{
  items: ContractorFeedbackRow[]
  readOnly?: boolean
  loading?: boolean
  issue?: string
}>()

const emit = defineEmits<{
  view: [rectificationId: string]
  upload: [payload: { rectificationId: string; nodeId: number }]
  bind: []
  rectify: [rectificationId: string]
}>()

const pendingItems = computed(() => props.items.filter((item) => item.sourceStatus === '待反馈'))
const doneItems = computed(() => props.items.filter((item) => item.sourceStatus !== '待反馈'))
const doneOpen = ref(false)

const tagType = getStatusTagType
/** 「监检退回补正」只是类别，真正要看的是监检写的那句话 */
const opinionOf = (item: ContractorFeedbackRow) => item.requirement || item.issue
</script>

<template>
  <!-- 2026-11-04 手机简化稿：待补正的意见一条一张淺红卡，按钮直接给「补交资料 / 提交反馈」；
       处理过的收起来。一条都没有时整块不占位。 -->
  <section
    v-if="pendingItems.length || doneItems.length || loading || issue"
    id="contractor-feedback-list"
    data-guide="contractor-feedback"
    class="contractor-feedback-panel"
    aria-label="监检退回"
  >
    <h2 class="feedback-title">
      监检退回，需要你处理
      <span v-if="pendingItems.length" class="feedback-count">{{ pendingItems.length }}</span>
    </h2>
    <p v-if="loading" class="feedback-note">正在更新补正清单…</p>
    <p v-else-if="issue" class="feedback-note is-error">补正清单加载失败，请重试</p>

    <article v-for="item in pendingItems" :key="item.id" class="feedback-card">
      <div class="feedback-card-head">
        <ElTag type="danger" size="small" effect="light">需补正</ElTag>
        <strong>{{ item.node }}</strong>
      </div>
      <p class="feedback-opinion">监检意见：{{ plainWording(opinionOf(item)) }}</p>
      <div class="feedback-card-foot">
        <small v-if="item.dueAt">期限 {{ item.dueAt }}</small>
        <small v-else-if="item.feedbackAt">退回于 {{ String(item.feedbackAt).slice(5, 10) }}</small>
        <div class="feedback-actions">
          <ElButton
            type="primary"
            :disabled="readOnly"
            @click="emit('upload', { rectificationId: item.rectificationId, nodeId: item.nodeId })"
          >
            补交资料
          </ElButton>
          <ElButton
            plain
            type="primary"
            :disabled="readOnly"
            @click="emit('rectify', item.rectificationId)"
          >
            提交反馈
          </ElButton>
        </div>
      </div>
      <div class="feedback-links">
        <button type="button" @click="emit('view', item.rectificationId)">查看详情</button>
        <button type="button" :disabled="readOnly" @click="emit('bind')">关联已有文件</button>
      </div>
    </article>

    <div v-if="doneItems.length" class="feedback-done">
      <button
        type="button"
        class="feedback-done-toggle"
        :aria-expanded="doneOpen"
        @click="doneOpen = !doneOpen"
      >
        已处理 {{ doneItems.length }} 条<span aria-hidden="true">{{
          doneOpen ? ' 收起' : ' ›'
        }}</span>
      </button>
      <ul v-if="doneOpen">
        <li v-for="item in doneItems" :key="item.id">
          <button type="button" @click="emit('view', item.rectificationId)">
            <span>{{ item.node }}</span>
            <ElTag :type="tagType(item.status)" size="small" effect="plain">
              {{ plainWording(item.status) }}
            </ElTag>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.contractor-feedback-panel {
  display: grid;
  margin-bottom: 18px;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.feedback-title {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  font-size: 17px;
  line-height: 24px;
  color: #172033;
}

.feedback-count {
  display: inline-grid;
  height: 20px;
  min-width: 20px;
  padding: 0 6px;
  font-size: 12px;
  color: #fff;
  background: #d64545;
  border-radius: 999px;
  place-items: center;
}

.feedback-note {
  margin: 0;
  font-size: 13px;
  color: #667085;
}

.feedback-note.is-error {
  color: #b42318;
}

.feedback-card {
  display: grid;
  padding: 14px 16px;
  background: #fff7f6;
  border: 1px solid #f0c8c3;
  border-radius: 12px;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
}

.feedback-card-head {
  display: flex;
  gap: 8px;
  align-items: center;
}

.feedback-card-head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 15px;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feedback-opinion {
  margin: 0;
  font-size: 14px;
  line-height: 20px;
  color: #475467;
  overflow-wrap: anywhere;
}

.feedback-card-foot {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}

.feedback-card-foot small {
  font-size: 13px;
  color: #667085;
}

.feedback-actions {
  display: flex;
  gap: 8px;
}

.feedback-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.feedback-links {
  display: flex;
  gap: 16px;
}

.feedback-links button,
.feedback-done-toggle,
.feedback-done li button {
  padding: 0;
  font: inherit;
  font-size: 13px;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  background: none;
  border: 0;
}

.feedback-links button:disabled {
  color: #98a2b3;
  cursor: not-allowed;
}

.feedback-done {
  display: grid;
  gap: 6px;
}

.feedback-done-toggle {
  justify-self: start;
  color: #667085;
}

.feedback-done ul {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 12px;
}

.feedback-done li + li {
  border-top: 1px solid #eef1f6;
}

.feedback-done li button {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 44px;
  padding: 0 14px;
  color: #172033;
}
</style>
