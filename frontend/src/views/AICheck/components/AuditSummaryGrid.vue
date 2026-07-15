<script setup lang="ts">
import { computed } from 'vue'
import { ElCard, ElStatistic } from 'element-plus'

export type AuditSummaryTone = 'blue' | 'green' | 'orange' | 'red' | 'gray'

export type AuditSummaryCard = {
  label: string
  value: string | number
  hint?: string
  tone?: AuditSummaryTone
}

const props = defineProps<{
  cards: ReadonlyArray<AuditSummaryCard>
  ariaLabel?: string
}>()

const normalizedCards = computed(() =>
  props.cards.map((card) => {
    if (typeof card.value === 'number') {
      return { ...card, statisticValue: card.value, statisticSuffix: '' }
    }

    const match = String(card.value)
      .trim()
      .match(/^(-?\d+(?:\.\d+)?)\s*(.*)$/u)
    if (!match) {
      return { ...card, statisticValue: null, statisticSuffix: '' }
    }

    return {
      ...card,
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
    </ElCard>
  </section>
</template>

<style scoped>
.audit-summary-grid {
  display: grid;
  grid-template-columns: repeat(var(--audit-summary-columns, 4), minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.audit-summary-card {
  min-width: 0;
  min-height: 104px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 0;
  border-radius: 8px;
  box-shadow: 0 8px 20px rgb(15 23 42 / 7%);
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

.audit-summary-card--blue {
  background: linear-gradient(180deg, #fff, #f8fbff);
}

.audit-summary-card--green {
  background: linear-gradient(180deg, #fff, #f8fdf9);
}

.audit-summary-card--orange {
  background: linear-gradient(180deg, #fff, #fffaf0);
}

.audit-summary-card--red {
  background: linear-gradient(180deg, #fff, #fff7f7);
}

.audit-summary-card--gray {
  background: linear-gradient(180deg, #fff, #f8fafc);
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
