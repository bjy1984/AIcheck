<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ElButton, ElCard, ElEmpty, ElTag } from 'element-plus'

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
}>()

const emit = defineEmits<{
  view: [rectificationId: string]
  upload: [payload: { rectificationId: string; nodeId: number }]
  bind: []
  rectify: [rectificationId: string]
}>()

const expandedId = ref('')

watch(
  () => props.items.map((item) => `${item.id}:${item.sourceStatus}`).join('|'),
  () => {
    const currentStillExists = props.items.some((item) => item.id === expandedId.value)
    if (currentStillExists) return
    expandedId.value =
      props.items.find((item) => item.sourceStatus === '待反馈')?.id || props.items[0]?.id || ''
  },
  { immediate: true }
)

const toggle = (id: string) => {
  expandedId.value = expandedId.value === id ? '' : id
}

const tagType = (status: string) => {
  if (status.includes('关闭') || status.includes('通过')) return 'success'
  if (status.includes('待')) return 'warning'
  return 'primary'
}
</script>

<template>
  <ElCard id="contractor-feedback-list" class="contractor-feedback-panel" shadow="never">
    <template #header>
      <div class="panel-head">
        <div>
          <h2>二、监检审查意见</h2>
          <p>优先处理待补正意见，上传资料时自动带入对应意见。</p>
        </div>
        <span class="feedback-count">
          {{ items.filter((item) => item.sourceStatus === '待反馈').length }} 项待处理
        </span>
      </div>
    </template>

    <div v-if="items.length" class="feedback-list">
      <article
        v-for="item in items"
        :key="item.id"
        :class="['feedback-item', { 'is-open': expandedId === item.id }]"
      >
        <button
          type="button"
          class="feedback-summary"
          :aria-expanded="expandedId === item.id"
          @click="toggle(item.id)"
        >
          <span class="feedback-id">{{ item.id }}</span>
          <strong>{{ item.issue }}</strong>
          <ElTag :type="tagType(item.status)" size="small" effect="light">
            {{ item.status }}
          </ElTag>
          <component :is="expandedId === item.id ? ArrowUp : ArrowDown" aria-hidden="true" />
        </button>

        <div v-if="expandedId === item.id" class="feedback-detail">
          <p>{{ item.requirement }}</p>
          <dl>
            <div
              ><dt>问题环节</dt><dd>{{ item.node }}</dd></div
            >
            <div
              ><dt>关联文件</dt><dd>{{ item.linkedFiles }} 个</dd></div
            >
            <div
              ><dt>反馈时间</dt><dd>{{ item.feedbackAt }}</dd></div
            >
            <div
              ><dt>截止要求</dt><dd>{{ item.dueAt }}</dd></div
            >
          </dl>
          <div class="feedback-actions">
            <ElButton @click="emit('view', item.rectificationId)">查看意见</ElButton>
            <ElButton
              type="primary"
              :disabled="readOnly || item.sourceStatus !== '待反馈'"
              @click="
                emit('upload', { rectificationId: item.rectificationId, nodeId: item.nodeId })
              "
            >
              上传补正资料
            </ElButton>
            <ElButton link type="primary" :disabled="readOnly" @click="emit('bind')">
              关联已有文件
            </ElButton>
            <ElButton
              link
              type="primary"
              :disabled="readOnly || item.sourceStatus !== '待反馈'"
              @click="emit('rectify', item.rectificationId)"
            >
              提交反馈
            </ElButton>
          </div>
        </div>
      </article>
    </div>
    <ElEmpty v-else :image-size="56" description="暂无监检审查意见" />
  </ElCard>
</template>

<style scoped>
.contractor-feedback-panel {
  height: 100%;
  border: 0;
  border-radius: 8px;
  box-shadow: 0 6px 18px rgb(15 23 42 / 6%);
}

.contractor-feedback-panel :deep(.el-card__header) {
  padding: 14px 16px 10px;
}

.contractor-feedback-panel :deep(.el-card__body) {
  padding: 10px 14px 14px;
}

.panel-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
}

.panel-head h2 {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
}

.panel-head p {
  margin: 4px 0 0;
  font-size: 13px;
  font-weight: 500;
  color: #667085;
}

.feedback-count {
  padding: 3px 9px;
  font-size: 12px;
  font-weight: 600;
  color: #d97706;
  background: #fff5e7;
  border-radius: 999px;
  flex: none;
}

.feedback-list {
  display: grid;
  gap: 7px;
}

.feedback-item {
  overflow: hidden;
  background: #fff;
  border: 1px solid #e4eaf2;
  border-radius: 7px;
}

.feedback-item.is-open {
  background: #fffafa;
  border-color: #ffc8c5;
  box-shadow: inset 3px 0 0 #f04438;
}

.feedback-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 9px;
  align-items: center;
  width: 100%;
  min-height: 42px;
  padding: 8px 10px;
  color: #26344d;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
}

.feedback-summary:focus-visible {
  outline: 3px solid rgb(47 111 237 / 20%);
  outline-offset: -3px;
}

.feedback-summary > svg {
  width: 15px;
  height: 15px;
  color: #718096;
}

.feedback-summary strong {
  overflow: hidden;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feedback-id {
  padding: 2px 6px;
  font-size: 11px;
  color: #526178;
  background: #f1f4f8;
  border-radius: 4px;
}

.feedback-detail {
  padding: 2px 12px 12px;
}

.feedback-detail > p {
  margin: 4px 0 9px;
  font-size: 13px;
  line-height: 1.65;
  color: #344054;
}

.feedback-detail dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
  margin: 0;
  font-size: 12px;
}

.feedback-detail dl > div {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
}

.feedback-detail dt {
  color: #7a879b;
}

.feedback-detail dd {
  min-width: 0;
  margin: 0;
  color: #344054;
}

.feedback-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  justify-content: flex-end;
  margin-top: 11px;
}
</style>
