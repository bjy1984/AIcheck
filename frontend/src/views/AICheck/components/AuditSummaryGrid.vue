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
  min-width: 0;
  min-height: 104px;
  padding: 15px 16px;
  background: linear-gradient(180deg, #fff, #f8fbff);
  border: 0;
  border-radius: 8px;
  box-shadow:
    0 0 0 1px #dbe6f5,
    0 8px 18px rgb(15 23 42 / 4%);
}

.audit-summary-card span,
.audit-summary-card small {
  display: block;
  font-size: 13px;
  font-weight: 700;
  color: #667085;
}

.audit-summary-card strong {
  display: -webkit-box;
  margin: 9px 0 8px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 900;
  line-height: 1.25;
  color: #172033;
  text-overflow: ellipsis;
  overflow-wrap: anywhere;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.audit-summary-card small {
  overflow: hidden;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-summary-card--blue {
  background: linear-gradient(180deg, #fff, #f8fbff);
  box-shadow:
    0 0 0 1px #cbdcf8,
    0 8px 18px rgb(15 23 42 / 4%);
}

.audit-summary-card--green {
  background: linear-gradient(180deg, #fff, #f8fdf9);
  box-shadow:
    0 0 0 1px #cfe8d7,
    0 8px 18px rgb(15 23 42 / 4%);
}

.audit-summary-card--orange {
  background: linear-gradient(180deg, #fff, #fffaf0);
  box-shadow:
    0 0 0 1px #f0dfb8,
    0 8px 18px rgb(15 23 42 / 4%);
}

.audit-summary-card--red {
  background: linear-gradient(180deg, #fff, #fff7f7);
  box-shadow:
    0 0 0 1px #efc8c8,
    0 8px 18px rgb(15 23 42 / 4%);
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
