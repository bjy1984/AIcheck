<script setup lang="ts">
import { ChatDotRound, Clock, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'
import type {
  ContractorStatusCardKey,
  ContractorWorkbenchModel
} from './contractorWorkbenchViewModel'

const props = defineProps<{
  cards: ContractorWorkbenchModel['summaryCards']
  activeKey?: ContractorStatusCardKey | null
  feedbackUnavailable?: boolean
}>()

const emit = defineEmits<{
  select: [key: ContractorStatusCardKey]
}>()

const iconByKey = {
  feedback: ChatDotRound,
  pending: Tickets,
  reviewing: Clock
}

const cardsWithIcons = computed(() =>
  props.cards.map((card) => ({
    ...card,
    tone:
      card.count === 0 || (card.key === 'feedback' && props.feedbackUnavailable)
        ? 'gray'
        : card.tone,
    icon: iconByKey[card.key]
  }))
)
</script>

<template>
  <section class="contractor-status-cards" aria-label="施工资料办理状态">
    <button
      v-for="card in cardsWithIcons"
      :key="card.key"
      type="button"
      :class="[
        'contractor-status-card',
        `is-${card.tone}`,
        { 'is-active': activeKey === card.key }
      ]"
      :aria-pressed="activeKey === card.key"
      :aria-label="
        card.key === 'feedback' && feedbackUnavailable
          ? '待处理意见数量暂不可用'
          : `${card.label} ${card.count} 项`
      "
      @click="emit('select', card.key)"
    >
      <span class="contractor-status-icon" aria-hidden="true">
        <component :is="card.icon" />
      </span>
      <span class="contractor-status-label">{{ card.label }}</span>
      <strong>{{ card.key === 'feedback' && feedbackUnavailable ? '—' : card.count }}</strong>
    </button>
  </section>
</template>

<style scoped>
.contractor-status-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.contractor-status-card {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 12px;
  align-items: center;
  min-height: 72px;
  padding: 14px 18px;
  color: #1f2a44;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #dfe6f1;
  border-radius: 8px;
  box-shadow: none;
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.contractor-status-card:hover {
  border-color: #9ebcff;
  background: var(--aicheck-hover-bg, #f6faff);
}

.contractor-status-card:focus-visible {
  outline: 2px solid #2f6fed;
  outline-offset: 2px;
}

.contractor-status-card.is-active {
  border-color: #2f6fed;
  box-shadow: 0 0 0 2px rgb(47 111 237 / 12%);
}

.contractor-status-icon {
  display: inline-grid;
  width: 38px;
  height: 38px;
  place-items: center;
  color: #2f6fed;
  background: #eef4ff;
  border-radius: 50%;
}

.contractor-status-icon :deep(svg) {
  width: 21px;
  height: 21px;
}

.contractor-status-card.is-orange .contractor-status-icon {
  color: var(--aicheck-warning, #8a4b00);
  background: var(--aicheck-warning-bg, #fff7e6);
}

.contractor-status-card.is-green .contractor-status-icon {
  color: var(--aicheck-success, #087443);
  background: var(--aicheck-success-bg, #ecfdf3);
}

.contractor-status-card.is-gray .contractor-status-icon {
  color: var(--aicheck-neutral, #52647d);
  background: var(--aicheck-neutral-bg, #f2f4f7);
}

.contractor-status-label {
  font-size: 15px;
  font-weight: 600;
}

.contractor-status-card strong {
  font-size: 26px;
  line-height: 1;
  color: #172b4d;
}

@media (width <= 767px) {
  .contractor-status-cards {
    gap: 8px;
  }

  .contractor-status-card {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    min-height: 80px;
    padding: 12px 10px;
  }

  .contractor-status-icon {
    display: none;
  }

  .contractor-status-label {
    font-size: 14px;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .contractor-status-card strong {
    font-size: 24px;
  }
}
</style>
