<script setup lang="ts">
/**
 * 本节点要哪些资料、齐了没、谁该传——节点页第一屏就要回答的问题。
 *
 * 2026-09-12 线上实测：节点包返回 258KB（5 条资料要求、命中状态、责任方、要核的字段、
 * 已确认证据数），节点页只渲染出 2.2KB 文本——「审查所需资料」表被锁在 `submission`
 * 审计项下，而节点页的目录只保留 ai_review / human_review 两项，那张表永远打不开。
 *
 * 第一版挂上去之后用户当场指出还是不好用，这一版按这几条重做：
 * - 数字不许自相矛盾：所有计数都从同一份行数据算（nodeReviewSummary.materialStats，
 *   页头摘要行用的也是它）。
 * - 可选资料没交不是缺陷：原来和必传缺失一样标红，监检看见一片红反而分不出轻重。
 * - 每行一行：状态、资料名、责任方、右边是附件或要做的事。
 * - 缺的要能立刻动手：「挂接资料」，以及直接把缺项写进补正要求的「通知补正」
 *   （2026-11-04 节点页简化）。
 * - 顺序按要处理的程度排，不是按后端返回顺序（原来可选的排在必传前面）。
 */
import { computed } from 'vue'
import { CircleCheckFilled } from '@element-plus/icons-vue'
import { ElIcon } from 'element-plus'

import {
  isPendingMaterial,
  materialSeverity,
  materialStats,
  type NodeMaterialRow
} from '../nodeReviewSummary'
import AuditStatusTag, { type AuditStatusTone } from './AuditStatusTag.vue'

const props = defineProps<{
  rows: NodeMaterialRow[]
  /** 文件名 → 文档 id；找得到的附件名可以点开原件。 */
  fileIds?: Record<string, string>
  /** 当前用户能退回补正时，缺项行才给「通知补正」。 */
  canRequestCorrection?: boolean
}>()
const emit = defineEmits<{
  openMaterials: []
  openFile: [documentId: string]
  requestCorrection: [row: NodeMaterialRow]
}>()

const RANK: Record<string, number> = { blocking: 0, attention: 1, optional: 3, done: 2 }

const sortedRows = computed(() =>
  [...props.rows].sort((left, right) => {
    const bySeverity = RANK[materialSeverity(left)] - RANK[materialSeverity(right)]
    if (bySeverity) return bySeverity
    // 同一档里先列没挂的，再列挂了待确认的
    return Number(isPendingMaterial(left)) - Number(isPendingMaterial(right))
  })
)

const isMissing = (row: NodeMaterialRow) =>
  materialSeverity(row) !== 'done' && !isPendingMaterial(row) && !row.matchedFileNames.length

/**
 * 颜色口径（2026-09-13 用户定）：已确认=绿、缺证据=黄、错误/阻断=红。
 * 必传缺失挡结论，等同「错误」用红；条件必传缺、挂了没确认属「证据不足」用黄；
 * 可选没交不是问题，灰。已确认的只画一个绿勾，不再占一个标签。
 */
const statusTag = (row: NodeMaterialRow): { label: string; tone: AuditStatusTone } | undefined => {
  const level = materialSeverity(row)
  if (level === 'done') return undefined
  if (isPendingMaterial(row)) return { label: '待确认', tone: 'orange' }
  if (level === 'optional') return { label: '未提供', tone: 'gray' }
  return level === 'blocking' ? { label: '缺', tone: 'red' } : { label: '缺', tone: 'orange' }
}

const stats = computed(() => materialStats(props.rows))
</script>

<template>
  <section v-if="rows.length" class="card node-materials-card" aria-label="本节点所需资料">
    <div class="card-head">
      <h2>资料</h2>
      <span class="node-materials-count">
        必传 {{ stats.requiredDone }}/{{ stats.requiredTotal }}
      </span>
    </div>
    <ul class="node-materials-list">
      <li v-for="row in sortedRows" :key="row.id" :class="`is-${materialSeverity(row)}`">
        <span class="node-materials-status">
          <AuditStatusTag v-if="statusTag(row)" :tone="statusTag(row)!.tone" round>
            {{ statusTag(row)!.label }}
          </AuditStatusTag>
          <ElIcon v-else class="node-materials-done" aria-label="已确认">
            <CircleCheckFilled />
          </ElIcon>
        </span>
        <span class="node-materials-name">{{ row.name }}</span>
        <small class="node-materials-meta">
          {{
            row.requiredType === '必传'
              ? row.responsibleParty
              : `${row.requiredType} · ${row.responsibleParty}`
          }}
        </small>
        <span class="node-materials-end">
          <template v-if="row.matchedFileNames.length">
            <template v-for="fileName in row.matchedFileNames" :key="fileName">
              <button
                v-if="fileIds?.[fileName]"
                type="button"
                class="node-materials-file"
                :title="`打开 ${fileName}`"
                @click="emit('openFile', fileIds?.[fileName] || '')"
              >
                {{ fileName }}
              </button>
              <small v-else class="node-materials-file is-plain">{{ fileName }}</small>
            </template>
          </template>
          <template v-else-if="isMissing(row) && materialSeverity(row) !== 'optional'">
            <button type="button" class="node-materials-action" @click="emit('openMaterials')">
              挂接资料
            </button>
            <button
              v-if="canRequestCorrection"
              type="button"
              class="node-materials-action"
              @click="emit('requestCorrection', row)"
            >
              通知补正
            </button>
          </template>
        </span>
      </li>
    </ul>
    <div class="node-materials-foot">
      <button type="button" class="node-materials-more" @click="emit('openMaterials')">
        资料明细与挂接
      </button>
    </div>
  </section>
</template>

<style scoped>
/*
 * Workbench.vue 的 .card-head / .card-body 是 scoped 的：子组件只有根节点吃得到 .card，
 * 内部的 head/body 一点样式都没有——所以这里按同一套尺寸自己定义，别指望父组件的作用域。
 */
.node-materials-card {
  margin-bottom: 16px;
}

.node-materials-card .card-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 10px;
}

.node-materials-card .card-head h2 {
  margin: 0;
  font-size: 16px;
  line-height: 24px;
  color: var(--aicheck-text-strong, #172033);
}

.node-materials-count {
  font-size: 13px;
  color: var(--aicheck-text-subtle, #667085);
  font-variant-numeric: tabular-nums;
}

.node-materials-list {
  padding: 0 10px;
  margin: 0;
  list-style: none;
}

/* 状态列定宽，资料名、责任方、右侧附件各自对齐同一条竖线 */
.node-materials-list li {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto minmax(0, auto);
  gap: 12px;
  align-items: center;
  min-height: 44px;
  padding: 8px;
  font-size: 14px;
  line-height: 20px;
  color: #27364b;
}

.node-materials-list li + li {
  border-top: 1px solid var(--line-soft, #eef1f6);
}

.node-materials-list li.is-blocking {
  border-radius: 6px;
  background: #fff6f5;
}

.node-materials-list li.is-blocking + li {
  border-top-color: transparent;
}

.node-materials-list li.is-optional {
  color: var(--aicheck-text-subtle, #667085);
}

.node-materials-status {
  display: inline-flex;
  justify-content: center;
  white-space: nowrap;
}

.node-materials-done {
  font-size: 20px;
  color: #1f9d55;
}

.node-materials-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.node-materials-list li.is-blocking .node-materials-name {
  font-weight: 600;
}

.node-materials-meta {
  color: var(--aicheck-text-subtle, #667085);
  white-space: nowrap;
}

.node-materials-end {
  display: flex;
  gap: 14px;
  justify-content: flex-end;
  min-width: 0;
  flex-wrap: wrap;
}

.node-materials-file,
.node-materials-action,
.node-materials-more {
  padding: 0;
  border: none;
  background: none;
  font-size: 13px;
  cursor: pointer;
}

.node-materials-file {
  max-width: 260px;
  overflow: hidden;
  color: var(--el-color-primary, #2f6bff);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-materials-file.is-plain {
  color: var(--aicheck-text-subtle, #667085);
  cursor: default;
}

.node-materials-action {
  color: var(--el-color-primary, #2f6bff);
  white-space: nowrap;
}

.node-materials-foot {
  padding: 6px 18px 14px;
}

.node-materials-more {
  color: var(--aicheck-text-subtle, #667085);
}

.node-materials-file:not(.is-plain):hover,
.node-materials-action:hover,
.node-materials-more:hover {
  text-decoration: underline;
}

@media (width <= 720px) {
  .node-materials-list li {
    grid-template-columns: 52px minmax(0, 1fr);
  }

  .node-materials-meta,
  .node-materials-end {
    grid-column: 2;
    justify-content: flex-start;
  }
}
</style>
