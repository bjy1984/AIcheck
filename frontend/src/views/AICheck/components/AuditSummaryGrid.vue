<script setup lang="ts">
import { computed } from 'vue'
import { ElCard, ElStatistic } from 'element-plus'

export type AuditSummaryTone = 'blue' | 'green' | 'orange' | 'red' | 'gray'

export type AuditSummaryCard = {
  label: string
  value: string | number
  hint?: string
  tone?: AuditSummaryTone
  /** 配了才可点。**没有去处的卡片不做成按钮**——
      点了没反应比不可点更伤，用户会以为系统坏了。 */
  actionKey?: string
  actionLabel?: string
}

const props = defineProps<{
  cards: ReadonlyArray<AuditSummaryCard>
  ariaLabel?: string
}>()

const emit = defineEmits<{ cardAction: [actionKey: string] }>()

const normalizedCards = computed(() =>
  props.cards.map((card) => {
    const unavailable = ['未取得', '未获取', '未提供', '暂无数据', '待加载', '—', '-'].includes(
      String(card.value).trim()
    )
    const neutralCard = { ...card, tone: unavailable ? ('gray' as const) : card.tone }
    if (typeof card.value === 'number') {
      return {
        ...neutralCard,
        tone: card.value === 0 ? ('gray' as const) : neutralCard.tone,
        statisticValue: card.value,
        statisticSuffix: ''
      }
    }

    const match = String(card.value)
      .trim()
      .match(/^(-?\d+(?:\.\d+)?)\s*(.*)$/u)
    if (!match) {
      return { ...neutralCard, statisticValue: null, statisticSuffix: '' }
    }

    return {
      ...neutralCard,
      tone: Number(match[1]) === 0 ? ('gray' as const) : neutralCard.tone,
      statisticValue: Number(match[1]),
      statisticSuffix: match[2] || ''
    }
  })
)
</script>

<template>
  <section class="audit-summary-grid" role="list" :aria-label="ariaLabel || '审计摘要'">
    <ElCard
      v-for="card in normalizedCards"
      :key="`${card.label}-${card.value}`"
      :class="['audit-summary-card', `audit-summary-card--${card.tone || 'blue'}`]"
      shadow="never"
      role="listitem"
    >
      <ElStatistic v-if="card.statisticValue !== null" :value="card.statisticValue">
        <template #title>
          <span class="audit-summary-label">{{ card.label }}</span>
        </template>
        <template v-if="card.statisticSuffix" #suffix>
          <span class="audit-summary-suffix">{{ card.statisticSuffix }}</span>
        </template>
      </ElStatistic>
      <template v-else>
        <span class="audit-summary-label">{{ card.label }}</span>
        <strong class="audit-summary-text-value" :title="String(card.value)">
          {{ card.value }}
        </strong>
      </template>
      <small v-if="card.hint" :title="card.hint">{{ card.hint }}</small>
      <button
        v-if="card.actionKey"
        type="button"
        class="audit-summary-action"
        @click="emit('cardAction', card.actionKey)"
      >
        {{ card.actionLabel || '查看明细' }}
      </button>
    </ElCard>
  </section>
</template>

<style scoped>
.audit-summary-action {
  padding: 0;
  margin-top: 6px;
  color: #2f6fd0;
  font-size: 12px;
  background: none;
  border: 0;
  cursor: pointer;
}

.audit-summary-action:hover {
  text-decoration: underline;
}

.audit-summary-grid {
  display: grid;
  grid-template-columns: repeat(var(--audit-summary-columns, 4), minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.audit-summary-card {
  min-width: 0;
  min-height: 104px;
  background: var(--aicheck-surface, #fff);
  border: 1px solid var(--aicheck-border-soft, #e5ecf6);
  border-radius: 8px;
  box-shadow: none;
}

.audit-summary-card :deep(.el-card__body) {
  padding: 15px 16px;
}

.audit-summary-label,
.audit-summary-card small {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #667085;
}

.audit-summary-card :deep(.el-statistic__head) {
  margin-bottom: 9px;
}

.audit-summary-card :deep(.el-statistic__content),
.audit-summary-text-value {
  display: -webkit-box;
  margin: 0 0 8px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.25;
  color: #172033;
  text-overflow: ellipsis;
  overflow-wrap: anywhere;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.audit-summary-card :deep(.el-statistic__number) {
  font-size: inherit;
  font-weight: inherit;
  font-variant-numeric: tabular-nums;
}

.audit-summary-suffix {
  margin-left: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #667085;
}

.audit-summary-card small {
  overflow: hidden;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Keep the container quiet; status is expressed by the value and its label. */
.audit-summary-card--orange :deep(.el-statistic__content),
.audit-summary-card--orange .audit-summary-text-value {
  color: var(--aicheck-warning, #8a4b00);
}

.audit-summary-card--red :deep(.el-statistic__content),
.audit-summary-card--red .audit-summary-text-value {
  color: var(--aicheck-danger, #b42318);
}

.audit-summary-card--gray :deep(.el-statistic__content),
.audit-summary-card--gray .audit-summary-text-value {
  color: var(--aicheck-text-muted, #52647d);
}

@media (width <= 1180px) {
  .audit-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (width <= 640px) {
  .audit-summary-grid {
    grid-template-columns: 1fr;
  }

  .audit-summary-card {
    min-height: auto;
  }
}
</style>
