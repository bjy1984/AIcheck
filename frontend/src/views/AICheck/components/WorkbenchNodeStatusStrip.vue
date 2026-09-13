<script setup lang="ts">
/**
 * 节点七个审计项的状态条：资料提交 → OCR 抽取 → 证据确认 → AI 复核 → 人工结论 → 报告 → 归档。
 *
 * 2026-09-12 线上实测：节点页目录只保留 ai_review / human_review 两项
 * （`workbenchReviewSectionOrder`），另外五项的状态和摘要——包括 OCR 报的
 * 「抽取不完整、定位框缺失」、证据项报的「仍有必传审查点缺少已确认证据」——
 * 全都拿到了却不显示。这条状态条只显示状态与摘要，点一下切到那一项的内容区。
 */
import { computed } from 'vue'

import type { InspectionAuditItem, InspectionAuditItemKey } from '@/types/aicheck'

const props = defineProps<{ items: InspectionAuditItem[]; active: InspectionAuditItemKey }>()
const emit = defineEmits<{ select: [key: InspectionAuditItemKey] }>()

const ORDER: InspectionAuditItemKey[] = [
  'submission',
  'ocr',
  'evidence',
  'ai_review',
  'human_review',
  'report',
  'archive'
]
const LABELS: Record<string, string> = {
  submission: '资料提交',
  ocr: '资料抽取',
  evidence: '证据确认',
  ai_review: 'AI 复核',
  human_review: '人工结论',
  report: '报告',
  archive: '归档'
}
/** 颜色口径（2026-09-13 用户定）：完成=绿、要补东西=黄、失败=红、进行中=蓝、没开始=灰。 */
const TONES: Record<string, 'red' | 'orange' | 'green' | 'blue' | 'gray'> = {
  completed: 'green',
  in_progress: 'blue',
  needs_attention: 'orange',
  failed: 'red',
  not_started: 'gray'
}

const ordered = computed(() => {
  const byKey = new Map(props.items.map((item) => [item.key, item]))
  return ORDER.map((key) => byKey.get(key)).filter((item): item is InspectionAuditItem =>
    Boolean(item)
  )
})

/** 只把要人处理的摘要摊开：全绿时一条状态条就够了，不必把七段说明都铺出来。 */
const attention = computed(() =>
  ordered.value.filter((item) => item.status === 'needs_attention' || item.status === 'failed')
)

const label = (item: InspectionAuditItem) => LABELS[item.key] || item.label || item.key
const tone = (item: InspectionAuditItem) => TONES[item.status] || 'gray'
</script>

<template>
  <section v-if="ordered.length" class="card node-status-strip" aria-label="节点审计项状态">
    <div class="card-body">
      <ol class="node-status-list">
        <li
          v-for="item in ordered"
          :key="item.key"
          :class="[`is-${tone(item)}`, { 'is-active': item.key === active }]"
        >
          <button type="button" :title="item.statusLabel" @click="emit('select', item.key)">
            <i class="node-status-dot" aria-hidden="true"></i>
            <span>{{ label(item) }}</span>
            <small>{{ item.statusLabel }}</small>
          </button>
        </li>
      </ol>
      <ul v-if="attention.length" class="node-status-notes">
        <li v-for="item in attention" :key="item.key">
          <strong>{{ label(item) }}</strong>
          <span>{{ item.summary }}</span>
          <button type="button" @click="emit('select', item.key)">去处理</button>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
/* 同 WorkbenchNodeMaterialsCard：父组件的 .card-body 是 scoped 的，子组件吃不到。 */
.node-status-strip {
  margin-bottom: 14px;
}

.node-status-strip .card-body {
  padding: 12px 16px;
}

.node-status-list {
  display: flex;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 6px;
  flex-wrap: wrap;
}

.node-status-list button {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 4px 10px;
  border: 1px solid #e6edf7;
  border-radius: 999px;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
  line-height: 18px;
  color: #27364b;
}

.node-status-list li.is-active button {
  border-color: var(--el-color-primary, #2f6bff);
  background: #f3f7ff;
}

.node-status-list button:hover {
  border-color: var(--el-color-primary, #2f6bff);
}

.node-status-list small {
  color: var(--aicheck-text-subtle, #667085);
}

.node-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c6ccd8;
}

.is-green .node-status-dot {
  background: #1a7f4b;
}

.is-blue .node-status-dot {
  background: #2f6bff;
}

.is-orange .node-status-dot {
  background: #b54708;
}

.is-red .node-status-dot {
  background: #b42318;
}

.node-status-notes {
  display: grid;
  padding: 10px 0 0;
  margin: 10px 0 0;
  border-top: 1px dashed #e6edf7;
  list-style: none;
  gap: 6px;
}

.node-status-notes li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.node-status-notes strong {
  color: #b54708;
}

.node-status-notes span {
  flex: 1 1 260px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.node-status-notes button {
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 13px;
}

.node-status-notes button:hover {
  text-decoration: underline;
}
</style>
