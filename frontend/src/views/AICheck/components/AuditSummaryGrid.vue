<script setup lang="ts">
export type AuditSummaryTone = 'blue' | 'green' | 'orange' | 'red'

export type AuditSummaryCard = {
  label: string
  value: string | number
  hint?: string
  tone?: AuditSummaryTone
}

defineProps<{
  cards: ReadonlyArray<AuditSummaryCard>
  ariaLabel?: string
}>()
</script>

<template>
  <section class="audit-summary-grid" :aria-label="ariaLabel || '审计摘要'">
    <article
      v-for="card in cards"
      :key="`${card.label}-${card.value}`"
      :class="['audit-summary-card', `audit-summary-card--${card.tone || 'blue'}`]"
    >
      <span>{{ card.label }}</span>
      <strong :title="String(card.value)">{{ card.value }}</strong>
      <small v-if="card.hint" :title="card.hint">{{ card.hint }}</small>
    </article>
  </section>
</template>

<style scoped>
.audit-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.audit-summary-card {
  min-height: 112px;
  padding: 15px 16px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 1px solid #dbe6f5;
  border-left: 4px solid #2563eb;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgb(20 34 56 / 4%);
}

.audit-summary-card span,
.audit-summary-card small {
  display: block;
  font-size: 13px;
  font-weight: 700;
  color: #667085;
}

.audit-summary-card strong {
  display: block;
  margin: 9px 0 8px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 900;
  line-height: 1.25;
  color: #172033;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-summary-card--green {
  border-left-color: #16a34a;
}

.audit-summary-card--orange {
  border-left-color: #f59e0b;
}

.audit-summary-card--red {
  border-left-color: #dc2626;
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
