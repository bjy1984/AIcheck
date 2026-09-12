<script setup lang="ts">
/**
 * 本节点要哪些资料、齐了没、谁该传——节点页第一屏就要回答的问题。
 *
 * 2026-09-12 线上实测：节点包返回 258KB（5 条资料要求、命中状态、责任方、要核的字段、
 * 已确认证据数），节点页只渲染出 2.2KB 文本——「审查所需资料」表被锁在 `submission`
 * 审计项下，而节点页的目录只保留 ai_review / human_review 两项，那张表永远打不开。
 * 监检人员想知道「还缺什么」只能去问 AI 对话框。这张卡把它摆回台面上。
 */
import { computed } from 'vue'

import AuditStatusTag from './AuditStatusTag.vue'

type MaterialRow = {
  id: string
  name: string
  requiredType: string
  responsibleParty: string
  matchedFileNames: string[]
  status: string
}

const props = withDefaults(
  defineProps<{
    rows: MaterialRow[]
    /** 已确认证据的必传项数；取自 evidenceReadiness，缺失时按行状态兜底。 */
    satisfiedCount?: number
    missingCount?: number
  }>(),
  { satisfiedCount: undefined, missingCount: undefined }
)

const emit = defineEmits<{ openMaterials: [] }>()

/** 未找到 → 待确认 → 已确认：先看要处理的。 */
const STATUS_ORDER = ['未找到', '未命中', '待确认', '已驳回', '已确认']
const STATUS_TONES: Record<string, 'red' | 'orange' | 'green' | 'gray'> = {
  未找到: 'red',
  未命中: 'red',
  待确认: 'orange',
  已驳回: 'orange',
  已确认: 'green'
}

const sortedRows = computed(() =>
  [...props.rows].sort((left, right) => {
    const rank = (row: MaterialRow) => {
      const index = STATUS_ORDER.indexOf(row.status)
      return index < 0 ? STATUS_ORDER.length : index
    }
    return rank(left) - rank(right)
  })
)

const confirmed = computed(
  () => props.satisfiedCount ?? props.rows.filter((row) => row.status === '已确认').length
)
const missing = computed(
  () => props.missingCount ?? props.rows.filter((row) => row.status !== '已确认').length
)
const statusTone = (status: string) => STATUS_TONES[status] || 'gray'
/** 必传缺失是硬阻断，条件必传缺失只是提示——别让它们看起来一样严重。 */
const isBlocking = (row: MaterialRow) => row.requiredType === '必传' && row.status !== '已确认'
</script>

<template>
  <section v-if="rows.length" class="card node-materials-card" aria-label="本节点所需资料">
    <div class="card-head">
      <div>
        <h2>本节点所需资料</h2>
        <div class="sub">
          共 {{ rows.length }} 项 · 已确认 {{ confirmed }} · 还缺 {{ missing }}
        </div>
      </div>
      <AuditStatusTag :tone="missing ? 'orange' : 'green'" round>
        {{ missing ? `缺 ${missing} 项` : '资料齐备' }}
      </AuditStatusTag>
    </div>
    <div class="card-body">
      <ul class="node-materials-list">
        <li v-for="row in sortedRows" :key="row.id" :class="{ 'is-blocking': isBlocking(row) }">
          <AuditStatusTag :tone="statusTone(row.status)" round>{{ row.status }}</AuditStatusTag>
          <span class="node-materials-name">{{ row.name }}</span>
          <small class="node-materials-meta">
            {{ row.requiredType }} · {{ row.responsibleParty }}
          </small>
          <small v-if="row.matchedFileNames.length" class="node-materials-files">
            {{ row.matchedFileNames.join('、') }}
          </small>
          <small v-else class="node-materials-files is-empty">未挂接资料</small>
        </li>
      </ul>
      <button type="button" class="node-materials-more" @click="emit('openMaterials')">
        查看资料明细与挂接
      </button>
    </div>
  </section>
</template>

<style scoped>
.node-materials-card {
  margin-bottom: 14px;
}

.node-materials-list {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 6px;
}

.node-materials-list li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  padding-bottom: 6px;
  border-bottom: 1px solid #f0f3f9;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.node-materials-list li:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.node-materials-list li.is-blocking .node-materials-name {
  font-weight: 600;
}

.node-materials-name {
  flex: 1 1 220px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.node-materials-meta,
.node-materials-files {
  color: var(--aicheck-text-subtle, #667085);
}

.node-materials-files {
  flex-basis: 100%;
  padding-left: 4px;
}

.node-materials-files.is-empty {
  color: #b42318;
}

.node-materials-more {
  justify-self: start;
  margin-top: 10px;
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 13px;
}

.node-materials-more:hover {
  text-decoration: underline;
}
</style>
