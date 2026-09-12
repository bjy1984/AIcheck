<script setup lang="ts">
/**
 * 本节点要哪些资料、齐了没、谁该传——节点页第一屏就要回答的问题。
 *
 * 2026-09-12 线上实测：节点包返回 258KB（5 条资料要求、命中状态、责任方、要核的字段、
 * 已确认证据数），节点页只渲染出 2.2KB 文本——「审查所需资料」表被锁在 `submission`
 * 审计项下，而节点页的目录只保留 ai_review / human_review 两项，那张表永远打不开。
 *
 * 第一版挂上去之后用户当场指出还是不好用，这一版按这几条重做：
 * - 数字不许自相矛盾：5 项里 4 项未找到，标题却写「还缺 2」（那个 2 来自 readiness 的
 *   必传口径，行列表却是全部要求）。现在所有计数都从同一份行数据算。
 * - 可选资料没交不是缺陷：原来和必传缺失一样标红，监检看见一片红反而分不出轻重。
 * - 每行别占两行：「未找到」后面再红一行「未挂接资料」是同义反复。
 * - 缺的要能立刻动手：每行给「去挂接」。
 * - 顺序按要处理的程度排，不是按后端返回顺序（原来可选的排在必传前面）。
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

const props = defineProps<{ rows: MaterialRow[] }>()
const emit = defineEmits<{ openMaterials: [] }>()

const isOptional = (row: MaterialRow) => row.requiredType === '可选'
const isDone = (row: MaterialRow) => row.status === '已确认'
/** 待确认＝挂上了但没人确认；未找到＝压根没挂。 */
const isPending = (row: MaterialRow) => row.status === '待确认' || row.status === '已驳回'

/** 必传缺失挡结论，条件必传缺失要判断，可选没交只是没交——三档不能一样红。 */
const severity = (row: MaterialRow): 'blocking' | 'attention' | 'optional' | 'done' => {
  if (isDone(row)) return 'done'
  if (isOptional(row)) return 'optional'
  return row.requiredType === '必传' ? 'blocking' : 'attention'
}
const RANK: Record<string, number> = { blocking: 0, attention: 1, optional: 3, done: 2 }

const sortedRows = computed(() =>
  [...props.rows].sort((left, right) => {
    const bySeverity = RANK[severity(left)] - RANK[severity(right)]
    if (bySeverity) return bySeverity
    // 同一档里先列没挂的，再列挂了待确认的
    return Number(isPending(left)) - Number(isPending(right))
  })
)

const statusText = (row: MaterialRow) => {
  if (isDone(row)) return '已确认'
  if (isPending(row)) return '待确认'
  return isOptional(row) ? '未提供' : '缺'
}
const statusTone = (row: MaterialRow) => {
  const level = severity(row)
  if (level === 'done') return 'green'
  if (isPending(row)) return 'orange'
  return level === 'blocking' ? 'red' : level === 'attention' ? 'orange' : 'gray'
}

/** 所有计数都从同一份行数据算，标题和列表不可能对不上。 */
const stats = computed(() => {
  const required = props.rows.filter((row) => !isOptional(row))
  const done = required.filter(isDone)
  const blocking = props.rows.filter((row) => severity(row) === 'blocking')
  const attention = props.rows.filter((row) => severity(row) === 'attention' && !isPending(row))
  const pending = props.rows.filter((row) => !isDone(row) && isPending(row))
  const optional = props.rows.filter((row) => isOptional(row) && !isDone(row))
  return {
    requiredTotal: required.length,
    requiredDone: done.length,
    blocking: blocking.length,
    attention: attention.length,
    pending: pending.length,
    optional: optional.length
  }
})

const summaryText = computed(() => {
  const { requiredDone, requiredTotal, pending, optional } = stats.value
  return [
    `必传 ${requiredDone}/${requiredTotal} 已确认`,
    pending ? `待确认 ${pending}` : '',
    optional ? `可选未提供 ${optional}` : ''
  ]
    .filter(Boolean)
    .join(' · ')
})

const headline = computed(() => {
  const { blocking, attention, pending } = stats.value
  if (blocking) return `缺 ${blocking} 份必传资料`
  if (pending) return `${pending} 份待确认`
  if (attention) return `缺 ${attention} 份条件必传资料`
  return '必传资料齐备'
})
const headlineTone = computed(() =>
  stats.value.blocking ? 'red' : stats.value.pending || stats.value.attention ? 'orange' : 'green'
)
</script>

<template>
  <section v-if="rows.length" class="card node-materials-card" aria-label="本节点所需资料">
    <div class="card-head">
      <div>
        <h2>本节点所需资料</h2>
        <div class="sub">{{ summaryText }}</div>
      </div>
      <AuditStatusTag :tone="headlineTone" round>{{ headline }}</AuditStatusTag>
    </div>
    <div class="card-body">
      <ul class="node-materials-list">
        <li v-for="row in sortedRows" :key="row.id" :class="`is-${severity(row)}`">
          <AuditStatusTag :tone="statusTone(row)" round>{{ statusText(row) }}</AuditStatusTag>
          <span class="node-materials-name">{{ row.name }}</span>
          <small class="node-materials-meta"
            >{{ row.requiredType }} · {{ row.responsibleParty }}</small
          >
          <small v-if="row.matchedFileNames.length" class="node-materials-files">
            {{ row.matchedFileNames.join('、') }}
          </small>
          <button
            v-else-if="!isOptional(row)"
            type="button"
            class="node-materials-action"
            @click="emit('openMaterials')"
          >
            去挂接
          </button>
        </li>
      </ul>
      <button type="button" class="node-materials-more" @click="emit('openMaterials')">
        查看资料明细与挂接
      </button>
    </div>
  </section>
</template>

<style scoped>
/*
 * Workbench.vue 的 .card-head / .card-body 是 scoped 的：子组件只有根节点吃得到 .card，
 * 内部的 head/body 一点样式都没有——所以标题右边的标签掉到下一行、正文贴着边框
 * （2026-09-12 用户截图指出）。这里按同一套尺寸自己定义，别指望父组件的作用域。
 */
.node-materials-card {
  margin-bottom: 14px;
}

.node-materials-card .card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--line-soft, #eef1f6);
  background: var(--panel-soft, #fbfcfe);
}

.node-materials-card .card-head h2 {
  margin: 0;
  font-size: 15px;
  line-height: 22px;
  color: var(--aicheck-text-strong, #172033);
}

.node-materials-card .card-head .sub {
  margin-top: 2px;
  font-size: 12px;
  line-height: 18px;
  color: var(--aicheck-text-subtle, #667085);
}

.node-materials-card .card-body {
  padding: 10px 16px 14px;
}

.node-materials-list {
  display: grid;
  padding: 0;
  margin: 0;
  list-style: none;
  gap: 4px;
}

/* 状态列定宽，名称、责任方、附件名各自对齐同一条竖线——原来是 flex 自由排，
   每行标签宽度不同，名称就参差不齐。 */
.node-materials-list li {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr) auto;
  gap: 4px 12px;
  align-items: baseline;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 20px;
  color: #27364b;
}

.node-materials-list li.is-blocking {
  background: #fff6f5;
}

.node-materials-list li.is-optional {
  color: var(--aicheck-text-subtle, #667085);
}

.node-materials-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.node-materials-list li.is-blocking .node-materials-name {
  font-weight: 600;
}

.node-materials-meta {
  justify-self: end;
  color: var(--aicheck-text-subtle, #667085);
  white-space: nowrap;
}

/* 附件名另起一行，但对齐到名称那一列，不要贴回左边框 */
.node-materials-files {
  grid-column: 2 / -1;
  color: var(--aicheck-text-subtle, #667085);
  overflow-wrap: anywhere;
}

.node-materials-action,
.node-materials-more {
  padding: 0;
  border: none;
  background: none;
  color: var(--el-color-primary, #2f6bff);
  cursor: pointer;
  font-size: 13px;
}

.node-materials-action {
  justify-self: end;
  white-space: nowrap;
}

.node-materials-more {
  justify-self: start;
  margin-top: 10px;
}

.node-materials-action:hover,
.node-materials-more:hover {
  text-decoration: underline;
}
</style>
